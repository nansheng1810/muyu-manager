"""AstrBot 进程的启停、状态探测与日志读取。"""

from __future__ import annotations

import ctypes
import os
import re
import socket
import subprocess
import time
from pathlib import Path

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")

_kernel32 = ctypes.windll.kernel32
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102


class RunnerError(Exception):
    pass


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        return _kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        _kernel32.CloseHandle(handle)


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _tcp_rows() -> list[tuple[int, int, int]]:
    """返回 [(连接状态, 本地端口, 进程 PID)]（IPv4）。

    状态值即 Windows MIB_TCP_STATE：2 = LISTEN，5 = ESTABLISHED。
    """
    try:
        from ctypes import wintypes

        class _Row(ctypes.Structure):
            _fields_ = [
                ("dwState", wintypes.DWORD),
                ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD),
            ]

        iphlpapi = ctypes.windll.iphlpapi
        size = wintypes.DWORD(0)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 5, 0)
        if not size.value:
            return []
        buf = ctypes.create_string_buffer(size.value)
        if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, 5, 0) != 0:
            return []
        count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
        rows = ctypes.cast(
            ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD), ctypes.POINTER(_Row)
        )
        result: list[tuple[int, int, int]] = []
        for idx in range(count):
            row = rows[idx]
            result.append(
                (row.dwState, socket.ntohs(row.dwLocalPort & 0xFFFF), row.dwOwningPid)
            )
        return result
    except Exception:
        return []


def _tcp_established() -> dict[int, int]:
    """返回 {本地端口: ESTABLISHED 连接数}（IPv4）。"""
    result: dict[int, int] = {}
    for state, port, _pid in _tcp_rows():
        if state != 5:  # MIB_TCP_STATE_ESTAB
            continue
        result[port] = result.get(port, 0) + 1
    return result


def listening_pid(port: int) -> int:
    """返回正监听该端口的进程 PID（用于接管外部启动的实例），找不到返回 0。"""
    if not port:
        return 0
    for state, local_port, pid in _tcp_rows():
        if state == 2 and local_port == int(port) and pid:  # MIB_TCP_STATE_LISTEN
            return int(pid)
    return 0


def established_connections(port: int) -> int:
    if not port:
        return 0
    return _tcp_established().get(int(port), 0)


def _process_entries(image: str) -> list[tuple[str, int]]:
    """枚举指定进程名的 (可执行路径, PID)。"""
    try:
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        QUERY_LIMITED = 0x1000

        class _Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = _kernel32
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == ctypes.c_void_p(-1).value:
            return []
        entries: list[tuple[str, int]] = []
        try:
            entry = _Entry()
            entry.dwSize = ctypes.sizeof(_Entry)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if str(entry.szExeFile).lower() == image.lower():
                    handle = kernel32.OpenProcess(QUERY_LIMITED, False, entry.th32ProcessID)
                    if handle:
                        try:
                            buf = ctypes.create_unicode_buffer(1024)
                            size = wintypes.DWORD(1024)
                            if kernel32.QueryFullProcessImageNameW(
                                handle, 0, buf, ctypes.byref(size)
                            ):
                                entries.append((buf.value, entry.th32ProcessID))
                        finally:
                            kernel32.CloseHandle(handle)
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
        return entries
    except Exception:
        return []


def _process_paths(image: str) -> list[str]:
    """枚举指定进程名的可执行路径。"""
    return [path for path, _ in _process_entries(image)]


def napcat_process_running(napcat_dir: Path) -> bool:
    """NapCat 自带的 QQ.exe 是否正在运行。"""
    try:
        base = str(Path(napcat_dir).resolve()).lower().rstrip("\\") + "\\"
    except OSError:
        return False
    if len(base) <= 1:
        return False
    return any(path.lower().startswith(base) for path in _process_paths("QQ.exe"))


def kill_napcat_processes(napcat_dir: Path) -> int:
    """结束该 NapCat 目录下的 QQ.exe 与 NapCatWinBootMain.exe，返回数量。"""
    try:
        base = str(Path(napcat_dir).resolve()).lower().rstrip("\\") + "\\"
    except OSError:
        return 0
    if len(base) <= 1:
        return 0
    pids: list[int] = []
    for image in ("QQ.exe", "NapCatWinBootMain.exe"):
        for path, pid in _process_entries(image):
            if path.lower().startswith(base) and pid not in pids:
                pids.append(pid)
    killed = 0
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            killed += 1
        except Exception:
            continue
    return killed


def napcat_boot_command(boot: Path, qq: str = "") -> str:
    """构建 NapCat 启动命令：先切 UTF-8 代码页，避免控制台中文乱码。"""
    command = f'cmd.exe /c chcp 65001 >nul && "{boot}"'
    qq = str(qq or "").strip()
    if qq:
        command += f" {qq}"
    return command


def find_napcat_bat(napcat_dir: Path, qq: str = "") -> Path | None:
    """定位 NapCat 启动脚本，优先匹配包含目标 QQ 号的脚本。"""
    napcat = Path(napcat_dir)
    if not napcat.is_dir():
        return None
    candidates: list[Path] = []
    for name in ("napcat.quick.bat", "napcat.bat"):
        candidate = napcat / name
        if candidate.is_file():
            candidates.append(candidate)
    for pattern in ("*/napcat.quick.bat", "*/napcat.bat", "*/*/napcat.quick.bat", "*/*/napcat.bat"):
        for hit in sorted(napcat.glob(pattern)):
            if hit not in candidates:
                candidates.append(hit)
    if not candidates:
        return None
    qq = str(qq or "").strip()
    if qq:
        for candidate in candidates:
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if qq in text:
                return candidate
    return candidates[0]


def tail(path: Path, lines: int = 200, max_bytes: int = 512 * 1024) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read()
        text = data.decode("utf-8", "replace")
        parts = [_ANSI_RE.sub("", line) for line in text.splitlines()]
        return parts[-lines:]
    except Exception:
        return []


class Runner:
    """管理已启动的 AstrBot 子进程。"""

    def __init__(self) -> None:
        self.procs: dict[str, subprocess.Popen] = {}
        self.started_at: dict[str, float] = {}

    # ------------------------------------------------------------- status

    def status(self, inst: dict) -> dict:
        pid = int(inst.get("pid") or 0)
        alive = pid_alive(pid)
        dash_ready = port_open(inst.get("dash_port", 0))
        if not alive and pid:
            inst["pid"] = None
            self.started_at.pop(inst["id"], None)
        return {
            "running": bool(alive or dash_ready),
            "managed": alive,
            "dashboard_ready": dash_ready,
            "pid": pid if alive else None,
            "uptime": (
                int(time.time() - self.started_at[inst["id"]])
                if alive and inst["id"] in self.started_at
                else None
            ),
        }

    # -------------------------------------------------------------- start

    def start(self, inst: dict, settings: dict, extra_wait: float = 0.0) -> dict:
        if self.status(inst)["managed"]:
            raise RunnerError("该机器人已在运行")
        if port_open(inst.get("dash_port", 0)):
            raise RunnerError(
                f"Dashboard 端口 {inst['dash_port']} 已被占用，可能已在其他窗口运行"
            )

        python = Path(settings.get("python_exe", ""))
        source = Path(settings.get("astrbot_source", ""))
        main_py = source / "main.py"
        root = Path(inst["root"])
        if not python.exists():
            raise RunnerError(f"Python 解释器不存在：{python}")
        if not main_py.exists():
            raise RunnerError(f"未找到 AstrBot 源码：{main_py}")
        if not (root / "data").exists():
            (root / "data").mkdir(parents=True, exist_ok=True)

        log_dir = root / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        console_path = log_dir / "manager-console.log"
        console = open(console_path, "a", encoding="utf-8", errors="replace")
        console.write(f"\n\n===== 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        console.flush()

        env = os.environ.copy()
        env["ASTRBOT_ROOT"] = str(root)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("PYTHONPATH", None)

        try:
            proc = subprocess.Popen(
                [str(python), str(main_py)],
                cwd=str(root),
                env=env,
                stdout=console,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
            )
        except Exception as exc:  # noqa: BLE001
            console.close()
            raise RunnerError(f"启动失败：{exc}") from exc
        finally:
            try:
                console.close()
            except Exception:
                pass

        self.procs[inst["id"]] = proc
        self.started_at[inst["id"]] = time.time()
        inst["pid"] = proc.pid

        if extra_wait:
            deadline = time.time() + extra_wait
            while time.time() < deadline:
                if port_open(inst.get("dash_port", 0)):
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.5)
        return {"pid": proc.pid}

    # --------------------------------------------------------------- stop

    def stop(self, inst: dict, wait: float = 8.0) -> None:
        pid = int(inst.get("pid") or 0)
        proc = self.procs.get(inst["id"])
        if proc is not None and proc.poll() is not None:
            proc = None
        if not pid and proc is None:
            if port_open(inst.get("dash_port", 0)):
                raise RunnerError(
                    "该机器人由外部窗口启动，管理器无法直接结束；请在其控制台关闭或手动结束进程"
                )
            return
        target = pid or (proc.pid if proc else 0)
        subprocess.run(
            ["taskkill", "/PID", str(target), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.time() + wait
        while time.time() < deadline:
            if not pid_alive(target) and not port_open(inst.get("dash_port", 0)):
                break
            time.sleep(0.4)
        self.procs.pop(inst["id"], None)
        self.started_at.pop(inst["id"], None)
        inst["pid"] = None

    def restart(self, inst: dict, settings: dict) -> dict:
        self.stop(inst, wait=10.0)
        time.sleep(1.0)
        return self.start(inst, settings)

    # ------------------------------------------------------------- napcat

    def napcat_status(self, inst: dict) -> dict:
        """在线 = NapCat 已反向连上本实例的 WS 端口（QQ 已登录并握手成功）。"""
        napcat_dir = Path(inst.get("napcat_dir") or "")
        ws_port = int(inst.get("ws_port") or 0)
        port = int(inst.get("napcat_port") or 0)
        clients = established_connections(ws_port) if ws_port else 0
        up = port_open(port) if port else False
        return {
            "running": bool(clients or up),
            "clients": clients,
            "port": port,
            "ws_port": ws_port,
            "configured": napcat_dir.is_dir(),
            "boot": str(find_napcat_bat(napcat_dir, str(inst.get("qq") or "")) or ""),
        }

    def start_napcat(self, inst: dict) -> dict:
        napcat = Path(inst.get("napcat_dir") or "")
        bat = find_napcat_bat(napcat, str(inst.get("qq") or ""))
        if bat is None:
            raise RunnerError("未在 NapCat 目录中找到 napcat.quick.bat / napcat.bat")
        if napcat_process_running(napcat):
            return {"launched": None, "already": True, "script": str(bat)}
        qq = str(inst.get("qq") or "").strip()
        boot = bat.parent / "NapCatWinBootMain.exe"
        if boot.is_file():
            subprocess.Popen(
                napcat_boot_command(boot, qq),
                cwd=str(boot.parent),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            subprocess.Popen(
                ["cmd.exe", "/c", bat.name],
                cwd=str(bat.parent),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        return {"launched": str(bat), "already": False}


runner = Runner()
