"""SnowLuma QQ 后端：保留 AstrBot，只替换 NapCat 传输层。"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from . import agent_mode, codex_model, dsh as dsh_mod, runner as runner_mod, store

router = APIRouter()

SNOWLUMA_DEFAULT = Path("D:/驰风车队项目/SnowLuma")
STATE_PATH = store.DATA_DIR / "snowluma.json"
LOG_DIR = store.DATA_DIR / "logs"
RUN_LOG = LOG_DIR / "snowluma-native.log"
BUILD_LOG = LOG_DIR / "snowluma-build.log"
DATA_DIR = store.DATA_DIR / "snowluma_native"
HTTP_NAME = "muyu-manager"
WS_NAME = "muyu-astrbot"
FACTORY_HTTP = {"http-default", "muyu-http", HTTP_NAME}
FACTORY_WS = {"ws-default", "muyu-ws"}

DEFAULT_STATE = {
    "root": str(SNOWLUMA_DEFAULT),
    "source": {
        "pid": 0,
        "started_at": "",
        "webui_port": 0,
        "webui_password": "",
        "data_dir": str(DATA_DIR),
    },
    "bindings": {},
    "updated_at": "",
}

_lock = threading.RLock()
_build_lock = threading.Lock()
_build_job: dict = {
    "active": False,
    "phase": "",
    "ok": False,
    "error": "",
    "started_at": 0.0,
    "finished_at": 0.0,
}


class SnowLumaError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ok(data=None, message: str = "") -> dict:
    return {"status": "ok", "message": message, "data": data}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_state() -> dict:
    data = store.read_json(STATE_PATH, {})
    state = _deep_merge(DEFAULT_STATE, data if isinstance(data, dict) else {})
    state["bindings"] = {
        str(k): v for k, v in (state.get("bindings") or {}).items() if isinstance(v, dict)
    }
    return state


def save_state(state: dict) -> None:
    state["updated_at"] = _now()
    store.write_json(STATE_PATH, state)


def _patch_state(**parts) -> dict:
    with _lock:
        state = load_state()
        state.update(parts)
        save_state(state)
        return state


def _root(state: dict | None = None) -> Path:
    state = state or load_state()
    return Path(state.get("root") or SNOWLUMA_DEFAULT).expanduser()


def _source(state: dict | None = None) -> dict:
    return dict((state or load_state()).get("source") or {})


def _port_open(port: int) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.35):
            return True
    except OSError:
        return False


def _free_port(start: int) -> int:
    for port in range(int(start), int(start) + 200):
        if not _port_open(port):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SnowLumaError("找不到可用的本地端口。", 500)


def _source_built(root: Path) -> bool:
    return (root / "dist" / "index.mjs").is_file()


def _source_version(root: Path) -> str:
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except (OSError, ValueError):
        return ""


def _source_running(state: dict | None = None) -> bool:
    src = _source(state)
    pid = int(src.get("pid") or 0)
    port = int(src.get("webui_port") or 0)
    return bool(pid and port and runner_mod.pid_alive(pid) and _port_open(port))


def _webui_base(state: dict | None = None) -> str:
    src = _source(state)
    port = int(src.get("webui_port") or 0)
    if not port:
        raise SnowLumaError("SnowLuma 还没有启动。", 409)
    return f"http://127.0.0.1:{port}"


def _webui_request(
    path: str,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
    timeout: int = 15,
) -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(_webui_base() + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        message = payload.get("message") or payload.get("detail") or f"SnowLuma 控制台请求失败（HTTP {exc.code}）"
        if payload.get("consentRequired"):
            message = "请先打开 SnowLuma 控制台，阅读并同意 EULA / 隐私政策。"
        raise SnowLumaError(str(message), 409) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SnowLumaError("连不上 SnowLuma 控制台，请确认 SnowLuma 正在运行。", 409) from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise SnowLumaError("SnowLuma 控制台返回了无法解析的数据。", 502) from None
    if not isinstance(payload, dict):
        raise SnowLumaError("SnowLuma 控制台返回了未知数据。", 502)
    return payload


def _webui_token() -> str:
    state = load_state()
    password = str(_source(state).get("webui_password") or "")
    if not password:
        raise SnowLumaError("缺少 SnowLuma 控制台密码，请重新启动 SnowLuma。", 409)
    payload = _webui_request("/api/login", "POST", {"password": password})
    token = str(payload.get("token") or "")
    if not token:
        raise SnowLumaError("SnowLuma 控制台登录失败，密码可能已被修改。", 409)
    return token


def _write_runtime_config(data_dir: Path, webui_port: int) -> None:
    config = data_dir / "config"
    config.mkdir(parents=True, exist_ok=True)
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    runtime_path = config / "runtime.json"
    current = store.read_json(runtime_path, {})
    if not isinstance(current, dict):
        current = {}
    current.update({"webuiPort": webui_port, "webuiHost": "127.0.0.1"})
    current.setdefault("hookAutoLoad", False)
    store.write_json(runtime_path, current)
    onebot_path = config / "onebot.json"
    if not onebot_path.is_file():
        store.write_json(
            onebot_path,
            {
                "networks": {
                    "httpServers": [],
                    "httpClients": [],
                    "wsServers": [],
                    "wsClients": [],
                },
                "statusCommand": {"enabled": False, "swallow": False, "cooldownSeconds": 5, "trigger": "#sl"},
                "historySync": {"enabled": False},
                "notifications": {"channelIds": []},
            },
        )


def _source_ports(state: dict) -> int:
    src = _source(state)
    port = int(src.get("webui_port") or 0)
    if not port or _port_open(port):
        port = _free_port(6800)
    return port


def runtime_status() -> dict:
    with _build_lock:
        build = dict(_build_job)
    state = load_state()
    src = _source(state)
    root = _root(state)
    running = _source_running(state)
    if running:
        try:
            health = _webui_request("/api/status", token=_webui_token(), timeout=3)
        except SnowLumaError:
            health = {}
    else:
        health = {}
    return {
        "root": str(root),
        "root_exists": (root / "package.json").is_file(),
        "version": _source_version(root) if (root / "package.json").is_file() else "",
        "built": _source_built(root) if (root / "package.json").is_file() else False,
        "running": running,
        "pid": int(src.get("pid") or 0),
        "started_at": str(src.get("started_at") or ""),
        "webui_url": _webui_base(state) if int(src.get("webui_port") or 0) else "",
        "webui_password_saved": bool(src.get("webui_password")),
        "health": health,
        "data_dir": str(src.get("data_dir") or DATA_DIR),
        "build": build,
    }


def start_build() -> dict:
    state = load_state()
    root = _root(state)
    if not (root / "package.json").is_file():
        raise SnowLumaError("SnowLuma 源码目录无效：缺少 package.json。", 409)
    with _build_lock:
        if _build_job.get("active"):
            return dict(_build_job)
    if not shutil.which("pnpm"):
        raise SnowLumaError("未找到 pnpm，请先安装 pnpm 11.25.0。", 409)
    if not shutil.which("node"):
        raise SnowLumaError("未找到 Node.js。", 409)
    with _build_lock:
        _build_job.update(
            active=True,
            phase="准备",
            ok=False,
            error="",
            started_at=time.time(),
            finished_at=0.0,
        )
    threading.Thread(target=_build_worker, args=(root,), daemon=True, name="muyu-snowluma-build").start()
    time.sleep(0.2)
    with _build_lock:
        return dict(_build_job)


def _build_worker(root: Path) -> None:
    global _build_job
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    phases = [
        ("安装依赖", [shutil.which("pnpm") or "pnpm", "install", "--frozen-lockfile"]),
        ("构建全部", [shutil.which("pnpm") or "pnpm", "build:all"]),
    ]
    env = dict(os.environ)
    env.update(CI="1", SNOWLUMA_TARGET="win32-x64", NO_COLOR="1")
    ok = True
    error = ""
    with BUILD_LOG.open("w", encoding="utf-8") as log:
        log.write(f"[{_now()}] SnowLuma source build: {root}\n")
        log.flush()
        for phase, args in phases:
            with _build_lock:
                _build_job.update(active=True, phase=phase, ok=False, error="")
            log.write(f"\n[{_now()}] {phase}: {' '.join(str(x) for x in args)}\n")
            log.flush()
            try:
                proc = subprocess.run(
                    args,
                    cwd=str(root),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    timeout=3600,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                )
                if proc.returncode != 0:
                    ok = False
                    error = f"{phase}失败，退出码 {proc.returncode}"
                    break
            except (OSError, subprocess.TimeoutExpired) as exc:
                ok = False
                error = f"{phase}失败：{exc}"
                break
        if ok and not _source_built(root):
            ok = False
            error = "构建结束但缺少 dist/index.mjs"
        log.write(f"\n[{_now()}] {'完成' if ok else error}\n")
    with _build_lock:
        _build_job.update(
            active=False,
            phase="完成" if ok else "失败",
            ok=ok,
            error=error,
            finished_at=time.time(),
        )


def start_runtime() -> dict:
    state = load_state()
    root = _root(state)
    if not _source_built(root):
        raise SnowLumaError("SnowLuma 还没有构建，请先构建。", 409)
    src = _source(state)
    if _source_running(state):
        return runtime_status()
    port = _source_ports(state)
    password = str(src.get("webui_password") or "") or secrets.token_urlsafe(24)
    data_dir = Path(src.get("data_dir") or DATA_DIR).expanduser()
    _write_runtime_config(data_dir, port)
    node = shutil.which("node")
    if not node:
        raise SnowLumaError("未找到 Node.js。", 409)
    env = dict(os.environ)
    env["SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD"] = password
    env["SNOWLUMA_UPDATE_CHECK"] = "off"
    env["NO_COLOR"] = "1"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = RUN_LOG.open("ab")
    log.write(f"\n[{_now()}] manager starting SnowLuma: {root}\n".encode("utf-8"))
    log.flush()
    try:
        proc = subprocess.Popen(
            [node, str(root / "dist" / "index.mjs")],
            cwd=str(data_dir),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
    except OSError as exc:
        log.close()
        raise SnowLumaError(f"启动 SnowLuma 失败：{exc}", 500) from None
    finally:
        log.close()
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        if _port_open(port):
            break
        time.sleep(0.4)
    if proc.poll() is not None or not _port_open(port):
        try:
            if proc.poll() is None:
                proc.terminate()
        except OSError:
            pass
        raise SnowLumaError("SnowLuma WebUI 没有在 60 秒内启动，请查看日志。", 500)
    src.update(
        pid=proc.pid,
        started_at=_now(),
        webui_port=port,
        webui_password=password,
        data_dir=str(data_dir),
    )
    _patch_state(source=src)
    return runtime_status()


def stop_runtime() -> dict:
    state = load_state()
    src = _source(state)
    pid = int(src.get("pid") or 0)
    if pid and runner_mod.pid_alive(pid):
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                raise SnowLumaError("停止 SnowLuma 失败，请手动检查进程。", 500)
        else:
            try:
                os.kill(pid, 15)
            except OSError as exc:
                raise SnowLumaError(f"停止 SnowLuma 失败：{exc}", 500) from None
    src["pid"] = 0
    _patch_state(source=src)
    return runtime_status()


def webui_secret() -> dict:
    state = load_state()
    src = _source(state)
    port = int(src.get("webui_port") or 0)
    return {
        "url": f"http://127.0.0.1:{port}" if port else "",
        "password": str(src.get("webui_password") or ""),
    }


def set_root(path: str) -> dict:
    root = Path(str(path or "").strip()).expanduser()
    if not (root / "package.json").is_file():
        raise SnowLumaError("目录无效：缺少 package.json。", 409)
    if _source_running():
        raise SnowLumaError("请先停止 SnowLuma，再切换源码目录。", 409)
    state = load_state()
    state["root"] = str(root)
    save_state(state)
    return runtime_status()


def _instances() -> list[dict]:
    return store.load_instances()


def _instance(inst_id: str) -> dict:
    for item in _instances():
        if str(item.get("id")) == str(inst_id):
            return item
    raise SnowLumaError("找不到指定的机器人实例。", 404)


def _napcat_process(inst: dict) -> bool:
    path = Path(str(inst.get("napcat_dir") or ""))
    try:
        return bool(path.is_dir() and runner_mod.napcat_process_running(path))
    except Exception:
        return False


def stop_napcat(inst_id: str) -> dict:
    inst = _instance(inst_id)
    path = Path(str(inst.get("napcat_dir") or ""))
    killed = runner_mod.kill_napcat_processes(path) if path.is_dir() else 0
    return {
        "instance_id": str(inst_id),
        "killed": int(killed),
        "napcat": {
            "running": _napcat_process(inst),
            "clients": runner_mod.established_connections(int(inst.get("ws_port") or 0)),
        },
    }


def astrbot_target(inst: dict) -> dict:
    root = Path(str(inst.get("root") or ""))
    config_path = root / "data" / "cmd_config.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise SnowLumaError("读不到 AstrBot 的 cmd_config.json，请先启动过这个实例。", 409) from None
    platforms = data.get("platform") if isinstance(data, dict) else None
    if not isinstance(platforms, list):
        raise SnowLumaError("AstrBot 配置中没有平台列表。", 409)
    candidates = [item for item in platforms if isinstance(item, dict) and item.get("type") == "aiocqhttp"]
    target = next((item for item in candidates if str(item.get("id") or "") == str(inst.get("platform_id") or "")), None)
    if target is None and candidates:
        target = candidates[0]
    if target is None:
        raise SnowLumaError("AstrBot 没有 aiocqhttp 平台，无法接 SnowLuma。", 409)
    port = int(target.get("ws_reverse_port") or 0)
    if not port:
        raise SnowLumaError("AstrBot 的 aiocqhttp 端口为空。", 409)
    token = str(target.get("ws_reverse_token") or "")
    return {
        "platform_id": str(target.get("id") or ""),
        "port": port,
        "token_set": bool(token),
        "url": f"ws://127.0.0.1:{port}/ws",
        "_token": token,
    }


def _public_target(target: dict) -> dict:
    return {key: value for key, value in target.items() if not key.startswith("_")}


def _binding_http_port(state: dict, inst_id: str, existing: dict | None = None) -> int:
    candidates = {str(k): v for k, v in (state.get("bindings") or {}).items() if isinstance(v, dict)}
    used = {
        int(item.get("http_port") or 0)
        for key, item in candidates.items()
        if key != str(inst_id) and int(item.get("http_port") or 0)
    }
    port = int((existing or {}).get("http_port") or 0)
    if port and port not in used and not _port_open(port):
        return port
    for candidate in range(6911, 7011):
        if candidate not in used and not _port_open(candidate):
            return candidate
    raise SnowLumaError("没有可用的 OneBot HTTP 端口。", 500)


def _empty_networks() -> dict:
    return {"httpServers": [], "httpClients": [], "wsServers": [], "wsClients": []}


def merge_binding_config(
    config: dict,
    *,
    http_port: int,
    http_token: str,
    astrbot_url: str,
    astrbot_token: str,
) -> dict:
    merged = json.loads(json.dumps(config or {}))
    networks = merged.get("networks")
    if not isinstance(networks, dict):
        networks = _empty_networks()
        merged["networks"] = networks
    for key, value in _empty_networks().items():
        if not isinstance(networks.get(key), list):
            networks[key] = value
    networks["httpServers"] = [
        item
        for item in networks["httpServers"]
        if isinstance(item, dict) and str(item.get("name") or "") not in FACTORY_HTTP
    ]
    networks["wsServers"] = [
        item
        for item in networks["wsServers"]
        if isinstance(item, dict) and str(item.get("name") or "") not in FACTORY_WS
    ]
    networks["wsClients"] = [
        item
        for item in networks["wsClients"]
        if isinstance(item, dict) and str(item.get("name") or "") != WS_NAME
    ]
    networks["httpServers"].append(
        {
            "name": HTTP_NAME,
            "host": "127.0.0.1",
            "port": int(http_port),
            "path": "/",
            "enableWebSocket": False,
            "enableSse": False,
            "accessToken": http_token,
            "messageFormat": "array",
            "reportSelfMessage": False,
        }
    )
    client = {
        "name": WS_NAME,
        "url": astrbot_url,
        "role": "Universal",
        "messageFormat": "array",
        "reportSelfMessage": False,
        "reconnectIntervalMs": 1000,
    }
    if astrbot_token:
        client["accessToken"] = astrbot_token
    networks["wsClients"].append(client)
    if not isinstance(merged.get("statusCommand"), dict):
        merged["statusCommand"] = {"enabled": False, "swallow": False, "cooldownSeconds": 5, "trigger": "#sl"}
    if not isinstance(merged.get("historySync"), dict):
        merged["historySync"] = {"enabled": False}
    if not isinstance(merged.get("notifications"), dict):
        merged["notifications"] = {"channelIds": []}
    return merged


def remove_binding_config(config: dict) -> dict:
    cleaned = json.loads(json.dumps(config or {}))
    networks = cleaned.get("networks")
    if not isinstance(networks, dict):
        return cleaned
    for key in _empty_networks():
        if not isinstance(networks.get(key), list):
            networks[key] = []
    networks["httpServers"] = [
        item for item in networks["httpServers"] if isinstance(item, dict) and str(item.get("name") or "") != HTTP_NAME
    ]
    networks["wsClients"] = [
        item for item in networks["wsClients"] if isinstance(item, dict) and str(item.get("name") or "") != WS_NAME
    ]
    return cleaned


def _save_account_config(uin: str, config: dict) -> dict:
    token = _webui_token()
    payload = _webui_request(f"/api/config/{uin}", "POST", config, token=token, timeout=20)
    if not payload.get("saved"):
        raise SnowLumaError(str(payload.get("message") or "SnowLuma 配置没有保存成功。"), 409)
    return payload


def _load_account_config(uin: str) -> dict:
    token = _webui_token()
    payload = _webui_request(f"/api/config/{uin}", token=token)
    config = payload.get("config")
    if not isinstance(config, dict):
        raise SnowLumaError("SnowLuma 返回的账号配置无效。", 502)
    return config


def _binding_onebot_call(binding: dict, action: str, params: dict | None = None, timeout: int = 3):
    port = int(binding.get("http_port") or 0)
    token = str(binding.get("http_token") or "")
    if not port or not token:
        raise SnowLumaError("绑定尚未配置 OneBot HTTP。", 409)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/{action}",
        data=json.dumps(params or {}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        raise SnowLumaError("OneBot 端口尚未就绪。", 409) from None
    if not isinstance(payload, dict) or payload.get("status") != "ok" or payload.get("retcode") != 0:
        raise SnowLumaError("OneBot 返回失败，请检查 QQ 登录状态。", 409)
    return payload.get("data")


def _binding_ready(binding: dict, uin: str) -> tuple[bool, str]:
    try:
        info = _binding_onebot_call(binding, "get_login_info", timeout=2)
        account = str((info or {}).get("user_id") or "")
        return account == str(uin), account
    except SnowLumaError:
        return False, ""


def _processes() -> list[dict]:
    token = _webui_token()
    payload = _webui_request("/api/processes", token=token)
    rows = payload.get("list") if isinstance(payload, dict) else []
    result = []
    instances = _instances()
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        account = item.get("account") if isinstance(item.get("account"), dict) else {}
        uin = str(item.get("uin") or account.get("uin") or "")
        blocked = bool(re.search(r"napcat|astrbot", path, re.IGNORECASE))
        owner = next((x for x in instances if uin and str(x.get("qq") or "") == uin), None)
        result.append(
            {
                "pid": int(item.get("pid") or 0),
                "name": str(item.get("name") or ""),
                "path": path,
                "status": str(item.get("status") or ""),
                "logged_in": bool(item.get("loggedIn")),
                "uin": uin,
                "nickname": str(account.get("nickname") or ""),
                "blocked": blocked,
                "reason": "该 QQ 进程由 NapCat/AstrBot 使用，不能同时被 SnowLuma 接管。" if blocked else "",
                "instance_id": str(owner.get("id") or "") if owner else "",
                "instance_name": str(owner.get("name") or "") if owner else "",
            }
        )
    return result


def _pick_process(rows: list[dict], expected_qq: str) -> dict:
    if not expected_qq:
        raise SnowLumaError("这个实例没有填写 QQ 号，无法自动匹配 SnowLuma 进程。", 409)
    matches = [
        item
        for item in rows
        if not item.get("blocked") and str(item.get("uin") or "") == str(expected_qq)
    ]
    if not matches:
        raise SnowLumaError(
            f"没有找到 QQ {expected_qq} 的进程。请先在 SnowLuma 控制台登录这个 QQ，再刷新进程列表。",
            409,
        )
    matches.sort(key=lambda item: (not item.get("logged_in"), item.get("status") != "running"))
    return matches[0]


def _validate_process(item: dict, expected_qq: str) -> None:
    if item.get("blocked"):
        raise SnowLumaError(str(item.get("reason") or "该 QQ 进程不能绑定。"), 409)
    uin = str(item.get("uin") or "")
    if not uin:
        raise SnowLumaError("这个 QQ 进程还没有登录，请先在 SnowLuma 控制台完成登录。", 409)
    if expected_qq and uin != str(expected_qq):
        raise SnowLumaError(f"进程 {item.get('pid')} 登录的是 QQ {uin}，与实例 QQ {expected_qq} 不一致。", 409)


def _wait_binding(binding: dict, uin: str, timeout: float = 25.0) -> tuple[bool, str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, account = _binding_ready(binding, uin)
        if ready:
            return True, account
        time.sleep(1)
    return False, ""


def _wait_astrbot(inst: dict, timeout: float = 10.0) -> bool:
    port = int(inst.get("ws_port") or 0)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port and runner_mod.established_connections(port):
            return True
        time.sleep(0.5)
    return False


def bind_instance(inst_id: str, pid: int = 0) -> dict:
    inst = _instance(inst_id)
    expected_qq = str(inst.get("qq") or "").strip()
    if not expected_qq:
        raise SnowLumaError("这个实例没有填写 QQ 号，无法绑定 SnowLuma。", 409)
    if _napcat_process(inst):
        raise SnowLumaError("这个实例的 NapCat 进程还在运行，请先停止 NapCat，再绑定 SnowLuma。", 409)
    state = load_state()
    if not _source_running(state):
        start_runtime()
        state = load_state()
    if not _source_running(state):
        raise SnowLumaError("SnowLuma 没有启动成功。", 409)
    rows = _processes()
    if pid:
        try:
            chosen = next(item for item in rows if int(item.get("pid") or 0) == int(pid))
        except StopIteration:
            raise SnowLumaError("QQ 进程列表已变化，请刷新后重试。", 409) from None
    else:
        chosen = _pick_process(rows, expected_qq)
    _validate_process(chosen, expected_qq)
    target = astrbot_target(inst)
    existing = (state.get("bindings") or {}).get(str(inst_id)) or {}
    http_port = _binding_http_port(state, str(inst_id), existing if isinstance(existing, dict) else None)
    http_token = str((existing or {}).get("http_token") or "") or secrets.token_urlsafe(32)
    current = _load_account_config(expected_qq)
    merged = merge_binding_config(
        current,
        http_port=http_port,
        http_token=http_token,
        astrbot_url=target["url"],
        astrbot_token=str(target.get("_token") or ""),
    )
    saved = _save_account_config(expected_qq, merged)
    binding = {
        "instance_id": str(inst_id),
        "enabled": True,
        "uin": expected_qq,
        "pid": int(chosen.get("pid") or 0),
        "process_path": str(chosen.get("path") or ""),
        "http_port": http_port,
        "http_token": http_token,
        "astrbot_url": target["url"],
        "astrbot_ws_port": target["port"],
        "bound_at": _now(),
        "error": "",
    }
    with _lock:
        state = load_state()
        bindings = dict(state.get("bindings") or {})
        bindings[str(inst_id)] = binding
        state["bindings"] = bindings
        save_state(state)
    ready, account = _wait_binding(binding, expected_qq, timeout=2)
    load_error = ""
    if not ready:
        try:
            token = _webui_token()
            _webui_request(f"/api/processes/{int(binding['pid'])}/load", "POST", {}, token=token, timeout=40)
        except SnowLumaError as exc:
            load_error = exc.message
        ready, account = _wait_binding(binding, expected_qq, timeout=25)
    astrbot_connected = _wait_astrbot(inst, timeout=10 if ready else 2)
    if ready and account:
        binding["uin"] = account
    if not ready:
        binding["error"] = load_error or "QQ 还在登录或尚未加载，请稍后刷新。"
    with _lock:
        state = load_state()
        bindings = dict(state.get("bindings") or {})
        bindings[str(inst_id)] = binding
        state["bindings"] = bindings
        save_state(state)
    return {
        "instance_id": str(inst_id),
        "binding": _public_binding(binding),
        "process": {key: chosen.get(key) for key in ("pid", "name", "uin", "status", "logged_in")},
        "astrbot": _public_target(target),
        "snowluma": {
            "saved": bool(saved.get("saved")),
            "applied": bool(saved.get("applied")),
            "online": bool(saved.get("online")),
            "message": str(saved.get("message") or ""),
        },
        "onebot": {"ready": ready, "account": account, "error": "" if ready else binding["error"]},
        "astrbot_connected": astrbot_connected,
    }


def _remove_config_nodes(uin: str) -> dict:
    if _source_running():
        current = _load_account_config(uin)
        cleaned = remove_binding_config(current)
        return _save_account_config(uin, cleaned)
    state = load_state()
    data_dir = Path(_source(state).get("data_dir") or DATA_DIR)
    path = data_dir / "config" / f"onebot_{uin}.json"
    current = store.read_json(path, {})
    if not isinstance(current, dict):
        return {"saved": False, "applied": False, "message": "没有找到账号配置。"}
    cleaned = remove_binding_config(current)
    store.write_json(path, cleaned)
    return {"saved": True, "applied": False, "message": "SnowLuma 未运行，解除已写入配置，下次启动生效。"}


def unbind_instance(inst_id: str) -> dict:
    inst = _instance(inst_id)
    try:
        agent_mode.disable(inst_id)
    except Exception:  # noqa: BLE001
        pass
    state = load_state()
    binding = (state.get("bindings") or {}).get(str(inst_id)) or {}
    if not isinstance(binding, dict) or not binding:
        raise SnowLumaError("这个实例还没有 SnowLuma 绑定。", 409)
    uin = str(binding.get("uin") or inst.get("qq") or "")
    result = _remove_config_nodes(uin) if uin else {"saved": False, "message": "绑定没有 QQ 号。"}
    binding["enabled"] = False
    binding["unbound_at"] = _now()
    binding["error"] = ""
    with _lock:
        state = load_state()
        bindings = dict(state.get("bindings") or {})
        bindings[str(inst_id)] = binding
        state["bindings"] = bindings
        save_state(state)
    return {"instance_id": str(inst_id), "binding": _public_binding(binding), "config": result}


def switch_to_napcat(inst_id: str) -> dict:
    inst = _instance(inst_id)
    state = load_state()
    binding = (state.get("bindings") or {}).get(str(inst_id)) or {}
    if isinstance(binding, dict) and binding.get("enabled"):
        unbind_instance(inst_id)
        binding = (load_state().get("bindings") or {}).get(str(inst_id)) or binding
    pid = int((binding or {}).get("pid") or 0)
    if pid and _source_running():
        token = _webui_token()
        try:
            _webui_request(f"/api/processes/{pid}/unload", "POST", {}, token=token, timeout=30)
        except SnowLumaError as exc:
            raise SnowLumaError(
                "已解除 AstrBot 绑定，但 SnowLuma 没有释放 QQ 进程；请先在 SnowLuma 控制台卸载它，再启动 NapCat。"
                f"（{exc.message}）",
                409,
            ) from None
    started = runner_mod.runner.start_napcat(inst)
    with _lock:
        state = load_state()
        bindings = dict(state.get("bindings") or {})
        record = dict((bindings.get(str(inst_id)) or {}))
        record.update({"enabled": False, "pid": 0, "unloaded_at": _now()})
        bindings[str(inst_id)] = record
        state["bindings"] = bindings
        save_state(state)
    return {"instance_id": str(inst_id), "napcat": started, "binding": _public_binding(record)}


def binding_enabled(inst_id: str) -> bool:
    binding = (load_state().get("bindings") or {}).get(str(inst_id)) or {}
    return bool(isinstance(binding, dict) and binding.get("enabled"))


def set_agent_mode(
    inst_id: str,
    enabled: bool,
    group_id: str = "",
    group_name: str = "",
    model_provider: str = "",
    model: str = "",
) -> dict:
    _instance(inst_id)
    binding = (load_state().get("bindings") or {}).get(str(inst_id)) or {}
    if not isinstance(binding, dict) or not binding.get("enabled"):
        raise SnowLumaError("这个实例还没有启用 SnowLuma 绑定。", 409)
    if enabled:
        if not _source_running():
            raise SnowLumaError("SnowLuma 没有运行，无法接管。", 409)
        choice = {"provider": model_provider, "model": model} if model_provider and model else None
        result = agent_mode.enable(inst_id, group_id, group_name, choice)
    else:
        result = agent_mode.disable(inst_id)
    return {
        "instance_id": str(inst_id),
        "binding": _public_binding(binding),
        "agent": result,
    }


def set_agent_model(inst_id: str, provider: str, model: str) -> dict:
    _instance(inst_id)
    binding = (load_state().get("bindings") or {}).get(str(inst_id)) or {}
    if not isinstance(binding, dict) or not binding.get("enabled"):
        raise SnowLumaError("这个实例还没有启用 SnowLuma 绑定。", 409)
    agent = str(agent_mode.status(inst_id).get("agent") or "")
    if agent == "codex":
        result = agent_mode.set_codex_model(inst_id, model)
    elif agent == "dsh":
        result = agent_mode.set_dsh_model(inst_id, provider, model)
    else:
        raise SnowLumaError("这个实例没有绑定 Agent，无法切换模型。", 409)
    return {
        "instance_id": str(inst_id),
        "binding": _public_binding(binding),
        "agent": result,
    }


def set_agent_group(inst_id: str, group_id: str, group_name: str = "") -> dict:
    _instance(inst_id)
    binding = (load_state().get("bindings") or {}).get(str(inst_id)) or {}
    if not isinstance(binding, dict) or not binding.get("enabled"):
        raise SnowLumaError("这个实例还没有启用 SnowLuma 绑定。", 409)
    return {
        "instance_id": str(inst_id),
        "binding": _public_binding(binding),
        "agent": agent_mode.set_group(inst_id, group_id, group_name),
    }


def _public_binding(binding: dict) -> dict:
    return {
        "instance_id": str(binding.get("instance_id") or ""),
        "enabled": bool(binding.get("enabled")),
        "uin": str(binding.get("uin") or ""),
        "pid": int(binding.get("pid") or 0),
        "http_port": int(binding.get("http_port") or 0),
        "astrbot_url": str(binding.get("astrbot_url") or ""),
        "astrbot_ws_port": int(binding.get("astrbot_ws_port") or 0),
        "bound_at": str(binding.get("bound_at") or ""),
        "unbound_at": str(binding.get("unbound_at") or ""),
        "error": str(binding.get("error") or ""),
    }


def public_status() -> dict:
    state = load_state()
    runtime = runtime_status()
    rows = []
    bindings = state.get("bindings") or {}
    for inst in _instances():
        inst_id = str(inst.get("id") or "")
        binding = bindings.get(inst_id) if isinstance(bindings, dict) else None
        binding = binding if isinstance(binding, dict) else {}
        napcat = {}
        napcat_process = _napcat_process(inst)
        try:
            napcat = runner_mod.runner.napcat_status(inst)
        except Exception:
            napcat = {}
        account_ready = False
        account = ""
        if binding.get("enabled") and runtime.get("running"):
            account_ready, account = _binding_ready(binding, str(binding.get("uin") or inst.get("qq") or ""))
        clients = 0
        try:
            clients = runner_mod.established_connections(int(inst.get("ws_port") or 0))
        except Exception:
            clients = 0
        backend = "offline"
        if account_ready and clients:
            backend = "snowluma"
        elif napcat_process:
            backend = "napcat"
        elif clients:
            backend = "snowluma" if binding.get("enabled") else "napcat"
        napcat_clients = int(napcat.get("clients") or 0) if not (binding.get("enabled") and account_ready) else 0
        rows.append(
            {
                "id": inst_id,
                "name": str(inst.get("name") or inst_id),
                "qq": str(inst.get("qq") or ""),
                "platform_id": str(inst.get("platform_id") or ""),
                "ws_port": int(inst.get("ws_port") or 0),
                "running": bool((inst.get("status") or {}).get("running")) if isinstance(inst.get("status"), dict) else runner_mod.pid_alive(int(inst.get("pid") or 0)),
                "backend": backend,
                "astrbot_clients": clients,
                "napcat": {
                    "running": bool(napcat_process),
                    "clients": napcat_clients,
                    "port": int(napcat.get("port") or 0),
                },
                "snowluma": {
                    "bound": bool(binding.get("enabled")),
                    "account_ready": account_ready,
                    "account": account,
                    "binding": _public_binding(binding) if binding else {},
                },
                "agent": agent_mode.status(inst_id),
            }
        )
    models: dict = {"default": {}, "groups": []}
    if any(str((row.get("agent") or {}).get("agent") or "") == "dsh" for row in rows):
        try:
            catalog = dsh_mod.model_catalog()
            models = {
                "default": catalog.get("default") or {},
                "groups": [
                    {
                        "id": str(group.get("id") or ""),
                        "name": str(group.get("name") or group.get("id") or ""),
                        "models": [str(item.get("id") or "") for item in group.get("models") or []],
                    }
                    for group in catalog.get("groups") or []
                ],
            }
        except Exception:  # noqa: BLE001
            pass
    codex_models: dict = {"current": "", "models": [], "error": ""}
    if any(str((row.get("agent") or {}).get("agent") or "") == "codex" for row in rows):
        try:
            codex_models = codex_model.catalog()
        except Exception as exc:  # noqa: BLE001
            codex_models = {"current": "", "models": [], "error": str(exc) or "读取 Codex 模型目录失败"}
    return {
        "runtime": runtime,
        "instances": rows,
        "binding_count": len([item for item in rows if item["snowluma"]["bound"]]),
        "dsh_models": models,
        "codex_models": codex_models,
    }


def logs(source: str = "run", lines: int = 200) -> dict:
    path = BUILD_LOG if source == "build" else RUN_LOG
    text = runner_mod.tail(path, lines=max(1, min(int(lines), 500)))
    return {"source": source, "path": str(path), "text": text}


def _guard(fn, *args, **kwargs):
    try:
        return _ok(fn(*args, **kwargs))
    except SnowLumaError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.get("/api/snowluma/status")
def api_status():
    return _guard(public_status)


@router.post("/api/snowluma/build")
def api_build():
    return _guard(start_build)


@router.post("/api/snowluma/start")
def api_start():
    return _guard(start_runtime)


@router.post("/api/snowluma/stop")
def api_stop():
    return _guard(stop_runtime)


@router.post("/api/snowluma/webui")
def api_webui():
    return _guard(webui_secret)


@router.post("/api/snowluma/root")
def api_root(payload: dict = Body(...)):
    return _guard(set_root, str(payload.get("path") or ""))


@router.get("/api/snowluma/processes")
def api_processes():
    return _guard(lambda: {"items": _processes()})


@router.post("/api/snowluma/bind")
def api_bind(payload: dict = Body(...)):
    return _guard(bind_instance, str(payload.get("instance_id") or ""), int(payload.get("pid") or 0))


@router.post("/api/snowluma/unbind")
def api_unbind(payload: dict = Body(...)):
    return _guard(unbind_instance, str(payload.get("instance_id") or ""))


@router.post("/api/snowluma/agent-mode")
def api_agent_mode(payload: dict = Body(...)):
    return _guard(
        set_agent_mode,
        str(payload.get("instance_id") or ""),
        bool(payload.get("enabled")),
        str(payload.get("group_id") or ""),
        str(payload.get("group_name") or ""),
        str(payload.get("model_provider") or ""),
        str(payload.get("model") or ""),
    )


@router.post("/api/snowluma/agent-model")
def api_agent_model(payload: dict = Body(...)):
    return _guard(
        set_agent_model,
        str(payload.get("instance_id") or ""),
        str(payload.get("provider") or ""),
        str(payload.get("model") or ""),
    )


@router.post("/api/snowluma/agent-group")
def api_agent_group(payload: dict = Body(...)):
    return _guard(
        set_agent_group,
        str(payload.get("instance_id") or ""),
        str(payload.get("group_id") or ""),
        str(payload.get("group_name") or ""),
    )


@router.post("/api/snowluma/napcat-stop")
def api_napcat_stop(payload: dict = Body(...)):
    return _guard(stop_napcat, str(payload.get("instance_id") or ""))


@router.post("/api/snowluma/napcat")
def api_napcat(payload: dict = Body(...)):
    return _guard(switch_to_napcat, str(payload.get("instance_id") or ""))


@router.get("/api/snowluma/logs")
def api_logs(source: str = "run", lines: int = 200):
    return _guard(logs, source, lines)
