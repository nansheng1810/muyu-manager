"""NapCat 掉线监控与自动快速登录。

「在线」以 NapCat 反向 WS 是否与 AstrBot 保持 ESTABLISHED 连接为准。
掉线后先给 NapCat 自愈窗口（它会自动重启 Worker），仍不在线才结束残留
进程并执行 napcat.quick.bat 快速登录；登录后仍连不上则标记「等待扫码」。
"""

from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from . import store
from .runner import (
    established_connections,
    find_napcat_bat,
    napcat_process_running,
)

POLL_INTERVAL = 20.0        # 轮询周期（秒）
OFFLINE_CONFIRM = 3         # 连续 N 次无连接才判定掉线
SELF_HEAL_WAIT = 150.0      # 掉线后等待 NapCat 自愈的时长（秒）
RELOGIN_TIMEOUT = 180.0     # 快速登录后等待重连的时长（秒）
RELOGIN_COOLDOWN = 900.0    # 两次自动重登的最小间隔（秒）

LOG_PATH = store.DATA_DIR / "watchdog.log"
LOG_MAX_BYTES = 512 * 1024  # 超过即截断，只保留尾部

CREATE_NEW_CONSOLE = 0x00000010


def _rotate_log() -> None:
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            keep = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = keep[-200:]
            LOG_PATH.write_text("".join(line + "\n" for line in tail), encoding="utf-8")
    except Exception:
        pass


def _log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log()
        stamp = datetime.now().strftime("%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


class _Watch:
    def __init__(self) -> None:
        self.was_online = False
        self.strikes = 0
        self.offline_since = 0.0
        self.stage = "idle"   # idle / self_heal / relogin / qrcode
        self.stage_since = 0.0
        self.last_relogin = 0.0
        self.relogin_count = 0
        self.note = ""


class Watchdog:
    """逐实例跟踪 NapCat 在线状态，掉线后自动快速登录。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._watches: dict[str, _Watch] = {}
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- api

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="napcat-watchdog"
        )
        self._thread.start()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                iid: {
                    "stage": w.stage,
                    "note": w.note,
                    "relogin_count": w.relogin_count,
                    "offline_seconds": (
                        int(time.time() - w.offline_since) if w.offline_since else 0
                    ),
                }
                for iid, w in self._watches.items()
            }

    # ------------------------------------------------------------ 内部逻辑

    def _loop(self) -> None:
        _log("看门狗已启动")
        while True:
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                _log(f"轮询异常：{exc}")
            time.sleep(POLL_INTERVAL)

    def tick(self) -> None:
        settings = store.load_settings()
        if not settings.get("napcat_auto_relogin", True):
            return
        for inst in store.load_instances():
            try:
                self._check(inst)
            except Exception as exc:  # noqa: BLE001
                _log(f"[{inst.get('name')}] 检查异常：{exc}")

    @staticmethod
    def _online(inst: dict) -> bool:
        ws_port = int(inst.get("ws_port") or 0)
        # 只认反向 WS 的 ESTABLISHED 连接：NapCat WebUI 端口即使 QQ
        # 掉线也保持打开，不能作为登录在线的依据。
        return bool(ws_port and established_connections(ws_port) > 0)

    def _check(self, inst: dict) -> None:
        iid = inst["id"]
        name = inst.get("name") or iid
        napcat_dir = Path(inst.get("napcat_dir") or "")
        if not napcat_dir.is_dir():
            return
        with self._lock:
            watch = self._watches.setdefault(iid, _Watch())
        now = time.time()

        if self._online(inst):
            if watch.stage == "self_heal":
                _log(f"[{name}] NapCat 自愈成功，已恢复在线")
            elif watch.stage == "relogin":
                _log(f"[{name}] 快速登录成功，已恢复在线")
            elif watch.stage == "qrcode":
                _log(f"[{name}] 检测到已在线（应为扫码完成）")
            watch.was_online = True
            watch.strikes = 0
            watch.offline_since = 0.0
            watch.stage = "idle"
            watch.note = ""
            return

        if watch.was_online and not watch.offline_since:
            watch.offline_since = now
            watch.stage = "self_heal"
            watch.stage_since = now
            watch.note = "检测到掉线，观察自愈中"
            _log(f"[{name}] NapCat 掉线，先等待自愈（{SELF_HEAL_WAIT:.0f}s）")
            return
        if not watch.was_online:
            # 从未在线过（例如开机后还没登录）不属于「掉线」，不自动处理。
            return

        watch.strikes += 1

        if watch.stage == "self_heal":
            if napcat_process_running(napcat_dir) and now - watch.stage_since < SELF_HEAL_WAIT:
                return
            if now - watch.last_relogin < RELOGIN_COOLDOWN:
                return
            self._relogin(inst, watch, napcat_dir)
        elif watch.stage == "relogin":
            if now - watch.stage_since > RELOGIN_TIMEOUT:
                watch.stage = "qrcode"
                watch.stage_since = now
                watch.note = "快速登录未能恢复在线，可能需要在弹出的窗口扫码"
                _log(f"[{name}] {watch.note}")
        elif watch.stage == "qrcode":
            # 等待扫码；若 NapCat 进程退出了且冷却已过，可再试一次快速登录。
            if (
                not napcat_process_running(napcat_dir)
                and now - watch.last_relogin > RELOGIN_COOLDOWN
            ):
                _log(f"[{name}] NapCat 进程已退出，冷却结束，再次尝试快速登录")
                self._relogin(inst, watch, napcat_dir)

    def _relogin(self, inst: dict, watch: _Watch, napcat_dir: Path) -> None:
        from .runner import kill_napcat_processes, napcat_boot_command, runner

        name = inst.get("name") or inst.get("id")
        watch.last_relogin = time.time()
        watch.relogin_count += 1
        try:
            killed = kill_napcat_processes(napcat_dir)
            if killed:
                _log(f"[{name}] 已结束 {killed} 个残留进程")
                time.sleep(3)
            bat = find_napcat_bat(napcat_dir, str(inst.get("qq") or ""))
            if bat is None:
                boot = napcat_dir / "NapCatWinBootMain.exe"
                if not boot.is_file():
                    watch.stage = "qrcode"
                    watch.note = "未找到快速登录入口，无法自动登录"
                    _log(f"[{name}] {watch.note}")
                    return
                qq = str(inst.get("qq") or "").strip()
                subprocess.Popen(
                    napcat_boot_command(boot, qq),
                    cwd=str(napcat_dir),
                    creationflags=CREATE_NEW_CONSOLE,
                )
            else:
                # 直接走引导器：bat 里的 pause 会挂住 cmd /c，
                # NapCatWinBootMain 前台拉起更可靠；先切 UTF-8 代码页避免中文乱码。
                boot = bat.parent / "NapCatWinBootMain.exe"
                if not boot.is_file():
                    boot = napcat_dir / "NapCatWinBootMain.exe"
                qq = str(inst.get("qq") or "").strip()
                if boot.is_file() and qq:
                    subprocess.Popen(
                        napcat_boot_command(boot, qq), cwd=str(boot.parent),
                        creationflags=CREATE_NEW_CONSOLE,
                    )
                else:
                    subprocess.Popen(
                        ["cmd.exe", "/c", bat.name], cwd=str(bat.parent),
                        creationflags=CREATE_NEW_CONSOLE,
                    )
            watch.stage = "relogin"
            watch.stage_since = time.time()
            watch.note = "已执行快速登录，等待重连"
            _log(f"[{name}] 已执行快速登录，等待重连")
        except Exception as exc:  # noqa: BLE001
            watch.stage = "qrcode"
            watch.note = f"快速登录执行失败：{exc}"
            _log(f"[{name}] 快速登录执行失败：{exc}")


watchdog = Watchdog()
