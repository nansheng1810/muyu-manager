"""DeepSeek Harness control plane for the fleet manager.

The manager owns a loopback `dsh web` process on 3080 and proxies the
SkillHub local API mounted by the web profile.  AstrBot is kept on the
0.1.x dotted-RPC bridge; DSH 0.2+ namespace RPC is deliberately not used.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query

from . import dashboard, market, runner as runner_mod, store

router = APIRouter()

PORT = 3080
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"
PROFILE = "web"
STATE_PATH = store.DATA_DIR / "dsh_runtime.json"
OVERLAY_PATH = store.DATA_DIR / "dsh-runtime-overlay.yml"
LOG_PATH = store.DATA_DIR / "logs" / "dsh-web.log"
BRIDGE_PLUGIN_ID = "astrbot_plugin_dsh_bridge"
BRIDGE_MARKET_ID = "Fantasality/astrbot_plugin_dsh_bridge"
BRIDGE_REPO = "https://github.com/Fantasality/astrbot_plugin_dsh_bridge"
BRIDGE_DOWNLOAD = (
    "https://astrbot-cloud-test-s3.astrbot.app/plugins/releases/fantasality/"
    "astrbot_plugin_dsh_bridge/1.0.0/"
    "astrbot_plugin_dsh_bridge-1.0.0-71d5f8097771.zip"
)
BRIDGE_TOOLS = ("dsh_ask", "dsh_ping")
SKILLHUB_METHODS = {
    "search",
    "install",
    "list",
    "uninstall",
    "detail",
    "plugins",
    "pluginCategories",
    "installedPlugins",
    "pluginReadme",
    "pluginInstall",
    "pluginInstallStatus",
    "pluginUninstall",
}
SAFE_SLUG = re.compile(r"^[A-Za-z0-9@._-]+$")
SAFE_PLUGIN_PART = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_PKG = re.compile(r"^@?[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?$")

_lock = threading.Lock()
_web_lock = threading.Lock()
_web_opener: urllib.request.OpenerDirector | None = None
_install_lock = threading.Lock()
_install_job: dict[str, Any] = {
    "active": False,
    "action": "",
    "target": "",
    "started_at": 0.0,
    "finished_at": 0.0,
    "message": "",
    "error": "",
    "result": None,
}


class DshError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def _ok(data=None, message: str = "") -> dict:
    return {"status": "ok", "message": message, "data": data}


def _fail(message: str, code: int = 400):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {"status": "error", "message": message, "data": None}, status_code=code
    )


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def resolve_home() -> Path:
    raw = str(os.environ.get("DSH_HOME") or "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".dsh"


def resolve_node() -> str:
    return shutil.which("node") or "node"


def resolve_bin_js() -> Path:
    explicit = str(os.environ.get("DSH_BIN_JS") or "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    found = shutil.which("dsh")
    if found:
        candidates.append(
            Path(found).resolve().parent
            / "node_modules"
            / "@deepseek-ai"
            / "dsh"
            / "lib"
            / "bin.js"
        )
    candidates.append(
        Path("D:/驰风车队项目/ai机器人管理/mcp_dsh")
        / "node_modules"
        / "@deepseek-ai"
        / "dsh"
        / "lib"
        / "bin.js"
    )
    candidates.append(
        store.DATA_DIR
        / "mcp"
        / "dsh"
        / "node_modules"
        / "@deepseek-ai"
        / "dsh"
        / "lib"
        / "bin.js"
    )
    appdata = str(os.environ.get("APPDATA") or "").strip()
    if appdata:
        candidates.append(
            Path(appdata)
            / "npm"
            / "node_modules"
            / "@deepseek-ai"
            / "dsh"
            / "lib"
            / "bin.js"
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise DshError("未找到 DSH 安装：缺少 @deepseek-ai/dsh/lib/bin.js")


def parse_version(raw: str) -> str:
    match = re.search(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", str(raw or ""))
    return match.group(0) if match else ""


def read_version() -> str:
    try:
        package = resolve_bin_js().parent.parent / "package.json"
        data = json.loads(package.read_text("utf-8"))
        return str(data.get("version") or "")
    except Exception:
        return ""


def _profile_dir() -> Path:
    return resolve_home() / "profiles" / PROFILE


def needs_local_memory_overlay() -> bool:
    profile = _profile_dir()
    try:
        package = json.loads((profile / "package.json").read_text("utf-8"))
        deps = package.get("dependencies") or {}
        if "dsh-local-memory" in deps:
            return True
    except Exception:
        pass
    try:
        patch = (profile / "cordis.patch.yml").read_text("utf-8")
        return "local-memory" in patch
    except Exception:
        return False


def ensure_overlay() -> Path | None:
    if not needs_local_memory_overlay():
        return None
    if not OVERLAY_PATH.exists():
        OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
        OVERLAY_PATH.write_text(
            "# Runtime-only DSH overlay. local-memory currently fails ESM resolution;\n"
            "# disabling it lets the rest of the web profile boot.\n"
            "- id: local-memory\n  disabled: true\n",
            "utf-8",
        )
    return OVERLAY_PATH


def build_start_args(
    bin_js: Path | str, overlay: Path | str | None, port: int = PORT
) -> list[str]:
    args = [
        resolve_node(),
        str(bin_js),
        "--profile",
        PROFILE,
    ]
    if overlay:
        args.extend(["--patch", str(overlay)])
    args.extend(["--host", HOST, "--port", str(port), "--no-open"])
    return args


def _read_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    data = store.read_json(STATE_PATH, {})
    return data if isinstance(data, dict) else {}


def _write_state(data: dict) -> None:
    store.write_json(STATE_PATH, data)


def _clear_state() -> None:
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass


def _tail(path: Path = LOG_PATH, lines: int = 120) -> list[str]:
    try:
        return runner_mod.tail(path, lines=max(1, min(int(lines), 500)))
    except Exception:
        return []


def _latest_token_url() -> str:
    """DSH 2.4+ 的 Web 认证：启动日志里会打印带 token 的入口地址。"""
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    pattern = re.compile(r"dsh web:\s*(http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_\-]+)")
    prefix = f"http://{HOST}:{PORT}/"
    for line in reversed(lines):
        match = pattern.search(line)
        if match and match.group(1).startswith(prefix):
            return match.group(1)
    return ""


def _web_client(force: bool = False) -> urllib.request.OpenerDirector | None:
    """用启动 token 换取浏览器 cookie，之后的 /api 与 /skillhub 请求都带上它。"""
    global _web_opener
    with _web_lock:
        if _web_opener is not None and not force:
            return _web_opener
        token_url = _latest_token_url()
        if not token_url:
            return None
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        try:
            with opener.open(token_url, timeout=15) as response:
                response.read()
        except Exception as exc:  # noqa: BLE001
            raise DshError(f"DSH Web 认证失败：{exc}", 502) from exc
        _web_opener = opener
        return opener


def _http_json(
    url: str,
    payload: dict | None = None,
    timeout: float = 20.0,
) -> dict:
    body = None
    headers = {"content-type": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def send() -> str:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = _web_client()
        if opener is None:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        with opener.open(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")

    try:
        raw = send()
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raw = exc.read().decode("utf-8", "replace")
            raise DshError(f"DSH 返回 HTTP {exc.code}：{raw[:300]}", 502) from exc
        try:
            exc.read()
        except Exception:  # noqa: BLE001
            pass
        if _web_client(force=True) is None:
            raise DshError(
                "DSH Web 要求浏览器认证，但日志里没有启动 token。请在管理器里重启一次 DSH。",
                409,
            )
        try:
            raw = send()
        except urllib.error.HTTPError as retry_exc:
            text = retry_exc.read().decode("utf-8", "replace")
            raise DshError(
                f"DSH 返回 HTTP {retry_exc.code}：{text[:300]}", 502
            ) from retry_exc
    except DshError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DshError(f"无法连接 DSH Web（{url}）：{exc}", 503) from exc
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise DshError(f"DSH 返回非 JSON：{raw[:200]}", 502) from exc
    return data if isinstance(data, dict) else {}


def skillhub(method: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    if method not in SKILLHUB_METHODS:
        raise DshError(f"不支持的 SkillHub 方法：{method}", 400)
    body = {"method": method}
    body.update(payload or {})
    data = _http_json(f"{URL}/skillhub", body, timeout=timeout)
    if not data.get("ok"):
        raise DshError(str(data.get("error") or f"SkillHub {method} 失败"), 502)
    return data


def rpc_011(method: str, args: dict | None = None, timeout: float = 20.0) -> dict:
    """Call the DSH RPC surface.

    DSH 0.1.x 使用 ``/api/session.create`` 这种点号路径；2.x 的 API 网关改成
    ``/api/session/create`` 两段式路径，这里按顺序自动兼容。
    """
    payload = dict(args or {})
    candidates = [(method, f"{URL}/api/{method}", payload)]
    if "." in method:
        slash = method.replace(".", "/")
        wrapped = {"args": {"request": payload}} if payload else {"args": {}}
        candidates.append((slash, f"{URL}/api/{slash}", wrapped))
    data: dict = {}
    last_error: DshError | None = None
    for endpoint, url, body in candidates:
        envelope = {
            "type": "client-request",
            "rpcId": f"manager-{time.time_ns()}",
            "method": endpoint,
            "payload": body,
        }
        try:
            data = _http_json(url, envelope, timeout=timeout)
            break
        except DshError as exc:
            last_error = exc
            if "HTTP 404" not in exc.message:
                raise
    else:
        raise last_error or DshError(f"DSH RPC {method} 不可用", 502)
    if data.get("type") != "server-response":
        raise DshError("DSH RPC 返回了意外响应", 502)
    result = data.get("result") or {}
    if not result.get("ok"):
        error = result.get("error") or {}
        raise DshError(str(error.get("message") or f"DSH RPC {method} 失败"), 502)
    value = result.get("value")
    return value if isinstance(value, dict) else {"value": value}


_catalog_lock = threading.Lock()
_catalog_cache: dict[str, Any] = {"at": 0.0, "value": {}}


def model_catalog(max_age: float = 120.0) -> dict:
    """读取 DSH 的模型目录（默认模型 + 各 provider 的模型列表），短缓存。"""
    with _catalog_lock:
        cached = _catalog_cache.get("value") or {}
        if cached and time.time() - float(_catalog_cache.get("at") or 0.0) < max_age:
            return cached
    catalog = rpc_011("session.modelCatalog", {}, timeout=30)
    with _catalog_lock:
        _catalog_cache["at"] = time.time()
        _catalog_cache["value"] = catalog
    return catalog


def select_model(session_id: str, provider: str, model: str) -> dict:
    """给指定 DSH 会话指定模型，用于绕过不可用的默认模型。"""
    provider = str(provider or "").strip()
    model = str(model or "").strip()
    if not provider or not model:
        raise DshError("provider 和 model 都不能为空", 400)
    selected = rpc_011(
        "session.selectModel",
        {"sessionId": session_id, "provider": provider, "model": model},
        timeout=30,
    )
    with _catalog_lock:
        _catalog_cache["at"] = 0.0
    return selected


def _extract_reply_text(data: dict) -> str:
    message = data.get("message") if isinstance(data, dict) else {}
    content = (message or {}).get("content") or []
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts).strip()


def _session_events(session_id: str) -> list:
    """读取会话事件；兼容 0.1.x 的 session.history 与 2.x 的 projections+page。"""
    try:
        history = rpc_011(
            "session.history", {"sessionId": session_id, "maxMessages": 300}, timeout=20
        )
        return list(history.get("events") or [])
    except DshError as exc:
        if "HTTP 404" not in exc.message:
            raise
    projection = rpc_011("session.projections", {"sessionId": session_id}, timeout=20)
    through_seq = int(projection.get("asOfSeq") or 0)
    page = rpc_011(
        "session.page",
        {
            "address": {"kind": "session", "sessionId": session_id},
            "throughSeq": through_seq,
            "maxMessages": 300,
        },
        timeout=30,
    )
    return list(page.get("records") or [])


def _cancel_session(session_id: str) -> None:
    try:
        rpc_011("session.cancel", {"sessionId": session_id}, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def run_prompt(
    prompt: str,
    cwd: str | None = None,
    session_id: str | None = None,
    timeout: float = 600.0,
    poll_interval: float = 2.0,
    max_chars: int = 6000,
) -> dict:
    """向 DSH 投递一条 prompt，同步轮询到本轮结束并返回最终文本。"""
    text = str(prompt or "").strip()
    if not text:
        raise DshError("prompt 不能为空", 400)
    if not runner_mod.port_open(PORT, timeout=0.4):
        raise DshError("DSH Web 未运行，无法自动执行技能任务", 409)
    own_session = not str(session_id or "").strip()
    baseline = 0
    if own_session:
        payload: dict[str, Any] = {}
        if cwd:
            payload["cwd"] = str(cwd)
        created = rpc_011("session.create", payload, timeout=30)
        session_id = str(created.get("sessionId") or "")
        if not session_id:
            raise DshError("DSH 未返回会话 ID", 502)
    else:
        baseline = len(_session_events(session_id))
    try:
        rpc_011(
            "session.prompt",
            {
                "sessionId": session_id,
                "requestId": f"manager-{time.time_ns()}",
                "mode": "queue",
                "content": [{"type": "text", "text": text}],
                "clientTimeZone": "Asia/Shanghai",
            },
            timeout=30,
        )
    except DshError:
        if own_session:
            _cancel_session(session_id)
        raise
    start = time.monotonic()
    texts: list[str] = []
    last_error = ""
    done = False
    done_polls = 0
    while time.monotonic() - start < timeout:
        time.sleep(max(0.5, min(float(poll_interval), 10.0)))
        events = _session_events(session_id)
        for entry in events[baseline:]:
            ev = entry.get("event") if isinstance(entry, dict) else None
            if not isinstance(ev, dict):
                continue
            ev_type = str(ev.get("type") or "")
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            if ev_type == "assistant/message":
                part = _extract_reply_text(data)
                if part and (not texts or texts[-1] != part):
                    texts.append(part)
            elif ev_type == "turn/end":
                done = True
                reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
                if reason.get("kind") == "error":
                    error = reason.get("error") if isinstance(reason.get("error"), dict) else {}
                    last_error = str(error.get("message") or "模型调用失败")
        if done:
            done_polls += 1
            if texts or done_polls >= 2:
                break
    duration_ms = int((time.monotonic() - start) * 1000)
    if not done:
        if own_session:
            _cancel_session(session_id)
        raise DshError(
            f"DSH 在 {int(timeout)} 秒内未完成技能任务（会话 {session_id} 已取消）", 504
        )
    reply = "\n\n".join(part for part in texts if part).strip() or "（DSH 未返回可见文本）"
    truncated = False
    if max_chars > 0 and len(reply) > max_chars:
        reply = reply[:max_chars] + "\n…（结果过长已截断）"
        truncated = True
    return {
        "text": reply,
        "sessionId": session_id,
        "duration_ms": duration_ms,
        "truncated": truncated,
        "error": last_error,
    }


def _port_pid() -> int:
    try:
        return int(runner_mod.listening_pid(PORT) or 0)
    except Exception:
        return 0


def _ready() -> bool:
    if not runner_mod.port_open(PORT, timeout=0.4):
        return False
    try:
        skillhub("list", timeout=3.0)
        return True
    except DshError:
        return False


def _managed_pid() -> int:
    state = _read_state()
    try:
        return int(state.get("pid") or 0)
    except (TypeError, ValueError):
        return 0


def public_status(
    include_counts: bool = True,
    log_lines: int = 40,
    prepare_overlay: bool = True,
) -> dict:
    home = resolve_home()
    bin_js = ""
    installed = False
    error = ""
    try:
        bin_js = str(resolve_bin_js())
        installed = True
    except DshError as exc:
        error = exc.message
    running = runner_mod.port_open(PORT, timeout=0.4)
    ready = _ready() if running else False
    pid = _port_pid() if running else 0
    managed = bool(pid and _managed_pid() == pid)
    state = _read_state() if managed else {}
    plugins_count = None
    skills_count = None
    if ready and include_counts:
        try:
            plugins_count = len((skillhub("installedPlugins", timeout=5.0) or {}).get("items") or [])
            skills_count = len((skillhub("list", timeout=5.0) or {}).get("items") or [])
        except DshError:
            pass
    overlay = (
        ensure_overlay()
        if installed and prepare_overlay
        else (OVERLAY_PATH if OVERLAY_PATH.exists() else None)
    )
    return {
        "installed": installed,
        "version": read_version() if installed else "",
        "bin_js": bin_js,
        "home": str(home),
        "profile": PROFILE,
        "profile_dir": str(_profile_dir()),
        "port": PORT,
        "url": URL,
        "running": running,
        "ready": ready,
        "managed": managed,
        "pid": pid or None,
        "started_at": state.get("started_at") or "",
        "overlay": str(overlay) if overlay else "",
        "overlay_active": bool(overlay and managed),
        "plugins_count": plugins_count,
        "skills_count": skills_count,
        "error": error,
        "log_path": str(LOG_PATH),
        "log_tail": _tail(lines=log_lines),
    }


def start() -> dict:
    with _lock:
        if runner_mod.port_open(PORT, timeout=0.4):
            status = public_status(include_counts=False)
            if status["ready"]:
                return status
            raise DshError(
                f"端口 {PORT} 已被占用，但未响应 SkillHub。请先释放端口。", 409
            )
        try:
            bin_js = resolve_bin_js()
        except DshError as exc:
            raise DshError(exc.message, 400) from exc
        overlay = ensure_overlay()
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("ab") as log:
            log.write(f"\n[{_now()}] manager starting dsh web\n".encode("utf-8"))
            log.flush()
            creation = 0
            if os.name == "nt":
                creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            env = dict(os.environ)
            env["DSH_HOME"] = str(resolve_home())
            try:
                from . import mcp_mode

                env.update(mcp_mode.dsh_env())
            except Exception:
                pass
            try:
                from . import mcp_native

                env.update(mcp_native.dsh_env())
            except Exception:
                pass
            try:
                proc = subprocess.Popen(
                    build_start_args(bin_js, overlay),
                    cwd=str(Path.home()),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    creationflags=creation,
                    close_fds=True,
                )
            except Exception as exc:  # noqa: BLE001
                raise DshError(f"启动 DSH 失败：{exc}", 500) from exc
        deadline = time.time() + 45
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            if _ready():
                _write_state(
                    {
                        "pid": proc.pid,
                        "started_at": _now(),
                        "port": PORT,
                        "overlay": str(overlay) if overlay else "",
                    }
                )
                return public_status(include_counts=False)
            time.sleep(0.4)
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        tail = "\n".join(_tail(lines=18))
        raise DshError(
            "DSH Web 启动失败。" + (f"\n{tail}" if tail else " 请查看 DSH 日志。"), 502
        )


def stop() -> dict:
    with _lock:
        pid = _port_pid()
        if not pid:
            _clear_state()
            return {"stopped": True, "was_running": False}
        managed = _managed_pid()
        if managed != pid:
            raise DshError(
                "3080 上的 DSH 由外部启动，管理器不会终止它。请手动停止外部进程。", 409
            )
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
        deadline = time.time() + 12
        while time.time() < deadline and runner_mod.port_open(PORT, timeout=0.3):
            time.sleep(0.3)
        if runner_mod.port_open(PORT, timeout=0.3):
            raise DshError("停止 DSH 超时，端口仍在监听。", 500)
        _clear_state()
        return {"stopped": True, "was_running": True, "pid": pid}


def restart() -> dict:
    status = public_status(include_counts=False)
    if status["running"] and not status["managed"]:
        raise DshError(
            "3080 上的 DSH 由外部启动，管理器不能重启外部进程。", 409
        )
    if status["running"]:
        stop()
    return start()


def _plugin_job_view() -> dict:
    with _install_lock:
        job = dict(_install_job)
    if job.get("active"):
        try:
            progress = skillhub("pluginInstallStatus", timeout=5.0)
            job["progress"] = {
                key: progress.get(key)
                for key in (
                    "active",
                    "target",
                    "seconds",
                    "lastLine",
                    "phase",
                    "done",
                    "total",
                    "currentPackage",
                    "error",
                )
                if key in progress
            }
        except DshError:
            job["progress"] = {}
    job["restart_required"] = bool(
        job.get("finished_at") and not job.get("error")
    )
    return job


def start_plugin_install(owner: str, name: str) -> dict:
    owner = str(owner or "").strip()
    name = str(name or "").strip()
    if not SAFE_PLUGIN_PART.match(owner) or not SAFE_PLUGIN_PART.match(name):
        raise DshError("插件标识不合法", 400)
    with _install_lock:
        if _install_job.get("active"):
            raise DshError("已有插件安装任务在运行。", 409)
        _install_job.update(
            {
                "active": True,
                "action": "install",
                "target": f"{owner}/{name}",
                "started_at": time.time(),
                "finished_at": 0.0,
                "message": "准备安装",
                "error": "",
                "result": None,
            }
        )

    def run() -> None:
        try:
            result = skillhub(
                "pluginInstall", {"owner": owner, "name": name}, timeout=900.0
            )
            with _install_lock:
                _install_job.update(
                    {
                        "active": False,
                        "finished_at": time.time(),
                        "message": "安装完成，重启 DSH 后生效",
                        "result": result,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            text = exc.message if isinstance(exc, DshError) else str(exc)
            with _install_lock:
                _install_job.update(
                    {
                        "active": False,
                        "finished_at": time.time(),
                        "message": "安装失败",
                        "error": text,
                    }
                )

    threading.Thread(target=run, daemon=True, name="dsh-plugin-install").start()
    return _plugin_job_view()


def plugin_uninstall(pkg: str) -> dict:
    pkg = str(pkg or "").strip()
    if not SAFE_PKG.match(pkg):
        raise DshError("插件包名不合法", 400)
    return skillhub("pluginUninstall", {"pkg": pkg}, timeout=180.0)


def install_skill(slug: str, version: str = "") -> dict:
    slug = str(slug or "").strip()
    version = str(version or "").strip()
    if not slug or "/" in slug or "\\" in slug or slug in {".", ".."}:
        raise DshError("技能 slug 不合法", 400)
    payload = {"slug": slug}
    if version:
        payload["version"] = version
    return skillhub("install", payload, timeout=240.0)


def uninstall_skill(slug: str) -> dict:
    slug = str(slug or "").strip()
    if not slug or "/" in slug or "\\" in slug or slug in {".", ".."}:
        raise DshError("技能 slug 不合法", 400)
    return skillhub("uninstall", {"slug": slug}, timeout=60.0)


def _plugin_id(item: dict) -> str:
    return str(item.get("id") or item.get("name") or "")


def should_auto_start(state: dict, port_is_open: bool, installed: bool) -> bool:
    return bool(installed and not port_is_open and state.get("pid"))


def auto_start() -> dict:
    try:
        if runner_mod.port_open(PORT, timeout=0.4):
            return {"started": False, "reason": "already running"}
        installed = True
        try:
            resolve_bin_js()
        except DshError:
            installed = False
        if not should_auto_start(_read_state(), False, installed):
            return {"started": False, "reason": "not previously managed"}
        return {"started": True, "status": start()}
    except Exception as exc:  # noqa: BLE001
        return {"started": False, "error": str(exc)}


def _bridge_view(item: dict) -> dict:
    plugin_id = _plugin_id(item)
    return {
        "id": plugin_id,
        "name": str(item.get("display_name") or item.get("name") or plugin_id),
        "version": str(item.get("version") or ""),
        "enabled": bool(item.get("activated", item.get("enabled"))),
        "compatible": plugin_id == BRIDGE_PLUGIN_ID,
    }


def connectors() -> dict:
    settings = store.load_settings()
    bridge_entry = market.find(settings, BRIDGE_MARKET_ID) or {
        "repo": BRIDGE_REPO,
        "download_url": BRIDGE_DOWNLOAD,
        "version": "1.0.0",
    }
    dsh = public_status(include_counts=False, log_lines=0)
    items = []
    for inst in store.load_instances():
        entry = {
            "id": inst.get("id"),
            "name": inst.get("name"),
            "running": bool(runner_mod.runner.status(inst).get("running")),
            "installed": False,
            "plugin": None,
            "config": {},
            "tools": {},
            "error": "",
        }
        if not entry["running"]:
            entry["error"] = "机器人未运行"
            items.append(entry)
            continue
        try:
            plugins = dashboard.call(inst, "GET", "plugins", timeout=20)
            rows = plugins.get("data") if isinstance(plugins, dict) else []
            matched = [
                p
                for p in (rows or [])
                if isinstance(p, dict) and "dsh" in _plugin_id(p).lower()
            ]
            matched.sort(key=lambda p: 0 if _plugin_id(p) == BRIDGE_PLUGIN_ID else 1)
            entry["dsh_plugins"] = [_bridge_view(p) for p in matched]
            if matched:
                plugin = _bridge_view(matched[0])
                entry["plugin"] = plugin
                entry["installed"] = plugin["compatible"]
                if plugin["compatible"]:
                    try:
                        cfg = dashboard.call(
                            inst,
                            "GET",
                            "plugins/config",
                            query={"plugin_id": plugin["id"]},
                            timeout=20,
                        )
                        data = cfg.get("data") if isinstance(cfg, dict) else {}
                        entry["config"] = (data or {}).get("config") or {}
                    except dashboard.DashboardError:
                        pass
                try:
                    tool_payload = dashboard.call(inst, "GET", "tools", timeout=20)
                    tool_rows = (
                        tool_payload.get("data") if isinstance(tool_payload, dict) else []
                    ) or []
                    for tool in tool_rows:
                        if not isinstance(tool, dict):
                            continue
                        name = str(tool.get("name") or "")
                        if name in BRIDGE_TOOLS:
                            entry["tools"][name] = str(tool.get("permission") or "")
                except dashboard.DashboardError:
                    pass
            entry["dsh_ready"] = dsh["ready"]
            entry["bridge_expected"] = {
                "version": str(bridge_entry.get("version") or "1.0.0"),
                "repo": str(bridge_entry.get("repo") or BRIDGE_REPO),
            }
        except dashboard.DashboardError as exc:
            entry["error"] = exc.message
        items.append(entry)
    return {
        "bridge_market_id": BRIDGE_MARKET_ID,
        "bridge_plugin_id": BRIDGE_PLUGIN_ID,
        "bridge_repo": str(bridge_entry.get("repo") or BRIDGE_REPO),
        "bridge_version": str(bridge_entry.get("version") or "1.0.0"),
        "incompatible_ids": ["astrbot_plugin_dsh_connector", "astrbot_plugin_dsh"],
        "dsh": {
            "ready": dsh["ready"],
            "url": dsh["url"],
            "version": dsh["version"],
        },
        "instances": items,
    }


def _bridge_entry() -> dict:
    settings = store.load_settings()
    return market.find(settings, BRIDGE_MARKET_ID) or {
        "repo": BRIDGE_REPO,
        "download_url": BRIDGE_DOWNLOAD,
    }


def _merged_bridge_config(existing: dict) -> dict:
    config = dict(existing or {})
    config.update(
        {
            "dsh_host": HOST,
            "dsh_port": PORT,
            "session_mode": "new",
            "inject_prompt_enabled": True,
            "request_timeout_seconds": 900,
        }
    )
    return config


def _find_plugin(inst: dict, plugin_id: str) -> dict | None:
    payload = dashboard.call(inst, "GET", "plugins", timeout=20)
    rows = payload.get("data") if isinstance(payload, dict) else []
    for item in rows or []:
        if isinstance(item, dict) and _plugin_id(item) == plugin_id:
            return item
    return None


def _lock_down_tools(inst: dict) -> dict:
    result = {}
    payload = dashboard.call(inst, "GET", "tools", timeout=20)
    rows = payload.get("data") if isinstance(payload, dict) else []
    for tool in rows or []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        if name not in BRIDGE_TOOLS:
            continue
        try:
            dashboard.call(
                inst,
                "PATCH",
                f"tools/{name}/permission",
                {"permission": "admin"},
                timeout=30,
            )
            result[name] = "admin"
        except dashboard.DashboardError as exc:
            result[name] = f"error: {exc.message}"
    return result


def install_connector(inst_id: str) -> dict:
    inst = _require_instance(inst_id)
    if not runner_mod.runner.status(inst).get("running"):
        raise DshError("机器人未运行，无法安装连接器", 409)
    existing = _find_plugin(inst, BRIDGE_PLUGIN_ID)
    if existing is not None:
        return configure_connector(inst_id, {})
    for incompatible in ("astrbot_plugin_dsh_connector", "astrbot_plugin_dsh"):
        if _find_plugin(inst, incompatible) is not None:
            raise DshError(
                f"已安装 {incompatible}：它与 DSH 0.1.1 协议不兼容。请先在插件页停用/卸载后再安装兼容桥。",
                409,
            )
    entry = _bridge_entry()
    body = {
        "url": str(entry.get("repo") or BRIDGE_REPO),
        "download_url": str(entry.get("download_url") or BRIDGE_DOWNLOAD),
        "ignore_version_check": True,
        "proxy": "",
    }
    result = dashboard.call(
        inst, "POST", "plugins/install/github", body, timeout=600
    )
    if isinstance(result, dict) and result.get("status") == "error":
        raise DshError(str(result.get("message") or "连接器安装失败"), 502)
    try:
        dashboard.call(
            inst,
            "PATCH",
            f"plugins/{BRIDGE_PLUGIN_ID}/enabled",
            {"enabled": True},
            timeout=60,
        )
    except dashboard.DashboardError:
        pass
    try:
        dashboard.call(
            inst, "POST", f"plugins/{BRIDGE_PLUGIN_ID}/reload", timeout=120
        )
    except dashboard.DashboardError:
        pass
    time.sleep(1.0)
    configured = configure_connector(inst_id, {})
    return {
        "installed": True,
        "install_result": result.get("data", result),
        "configured": configured,
    }


def configure_connector(inst_id: str, patch: dict) -> dict:
    inst = _require_instance(inst_id)
    plugin = _find_plugin(inst, BRIDGE_PLUGIN_ID)
    if plugin is None:
        raise DshError("兼容桥尚未安装", 404)
    current = dashboard.call(
        inst,
        "GET",
        "plugins/config",
        query={"plugin_id": BRIDGE_PLUGIN_ID},
        timeout=20,
    )
    data = current.get("data") if isinstance(current, dict) else {}
    existing = (data or {}).get("config") or {}
    merged = _merged_bridge_config(existing)
    for key in (
        "dsh_host",
        "dsh_port",
        "session_mode",
        "inject_prompt_enabled",
        "request_timeout_seconds",
        "max_result_chars",
        "default_cwd",
    ):
        if key in patch:
            merged[key] = patch[key]
    dashboard.call(
        inst,
        "PUT",
        "plugins/config",
        {"plugin_id": BRIDGE_PLUGIN_ID, "config": merged},
        timeout=90,
    )
    try:
        tools = _lock_down_tools(inst)
    except dashboard.DashboardError as exc:
        tools = {"error": exc.message}
    return {"config": merged, "tools": tools}


def test_connector(inst_id: str) -> dict:
    inst = _require_instance(inst_id)
    plugin = _find_plugin(inst, BRIDGE_PLUGIN_ID)
    if plugin is None:
        raise DshError("兼容桥尚未安装", 404)
    status = public_status(include_counts=False, log_lines=0)
    if not status["ready"]:
        raise DshError("DSH Web 未就绪，请先启动 DSH", 409)
    value = rpc_011("session.list", {}, timeout=12)
    items = value.get("items") or []
    return {
        "ok": True,
        "url": URL,
        "version": status["version"],
        "sessions": len(items) if isinstance(items, list) else 0,
        "plugin_version": str(plugin.get("version") or ""),
    }


def reload_connector(inst_id: str) -> dict:
    inst = _require_instance(inst_id)
    result = dashboard.call(
        inst, "POST", f"plugins/{BRIDGE_PLUGIN_ID}/reload", timeout=120
    )
    return result.get("data", result) if isinstance(result, dict) else {}


def _require_instance(inst_id: str) -> dict:
    for inst in store.load_instances():
        if str(inst.get("id")) == str(inst_id):
            return inst
    raise DshError(f"机器人不存在：{inst_id}", 404)


# ------------------------------------------------------------------ routes


@router.get("/api/dsh/status")
def api_status(log_lines: int = Query(40)):
    return _ok(public_status(include_counts=True, log_lines=log_lines))


@router.get("/api/dsh/logs")
def api_logs(lines: int = Query(120)):
    return _ok({"path": str(LOG_PATH), "lines": _tail(lines=lines)})


@router.post("/api/dsh/runtime/start")
def api_start():
    try:
        return _ok(start(), "DSH 已启动")
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.post("/api/dsh/runtime/stop")
def api_stop():
    try:
        return _ok(stop(), "DSH 已停止")
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.post("/api/dsh/runtime/restart")
def api_restart():
    try:
        return _ok(restart(), "DSH 已重启")
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.get("/api/dsh/skillhub/plugins")
def api_plugin_search(
    q: str = Query(""),
    category: str = Query(""),
    page: int = Query(1),
    limit: int = Query(12),
):
    try:
        payload = {"q": q, "page": page, "limit": limit}
        if category:
            payload["category"] = category
        return _ok(skillhub("plugins", payload, timeout=30.0))
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.get("/api/dsh/skillhub/plugins/installed")
def api_installed_plugins():
    try:
        return _ok(skillhub("installedPlugins", timeout=20.0))
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.get("/api/dsh/skillhub/plugin-categories")
def api_plugin_categories():
    try:
        return _ok(skillhub("pluginCategories", timeout=20.0))
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.post("/api/dsh/skillhub/plugins/install")
def api_plugin_install(payload: dict = Body(...)):
    try:
        return _ok(
            start_plugin_install(
                str(payload.get("owner") or ""), str(payload.get("name") or "")
            ),
            "安装任务已开始",
        )
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.post("/api/dsh/skillhub/plugins/uninstall")
def api_plugin_uninstall(payload: dict = Body(...)):
    try:
        return _ok(plugin_uninstall(str(payload.get("pkg") or "")), "插件已卸载，重启后生效")
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.get("/api/dsh/skillhub/plugins/install-status")
def api_plugin_install_status():
    return _ok(_plugin_job_view())


@router.get("/api/dsh/skillhub/skills")
def api_skill_search(
    q: str = Query(""),
    limit: int = Query(12),
    offset: int = Query(0),
):
    try:
        return _ok(
            skillhub(
                "search",
                {"query": q, "limit": limit, "offset": offset},
                timeout=30.0,
            )
        )
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.get("/api/dsh/skillhub/skills/installed")
def api_installed_skills():
    try:
        return _ok(skillhub("list", timeout=20.0))
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.post("/api/dsh/skillhub/skills/install")
def api_skill_install(payload: dict = Body(...)):
    try:
        return _ok(
            install_skill(
                str(payload.get("slug") or ""), str(payload.get("version") or "")
            ),
            "技能已安装",
        )
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.post("/api/dsh/skillhub/skills/uninstall")
def api_skill_uninstall(payload: dict = Body(...)):
    try:
        return _ok(uninstall_skill(str(payload.get("slug") or "")), "技能已卸载")
    except DshError as exc:
        return _fail(exc.message, exc.status)


@router.get("/api/dsh/connectors")
def api_connectors():
    try:
        return _ok(connectors())
    except Exception as exc:  # noqa: BLE001
        return _fail(f"读取连接器状态失败：{exc}", 502)


@router.post("/api/dsh/connectors/install")
def api_connector_install(payload: dict = Body(...)):
    try:
        return _ok(install_connector(str(payload.get("instance_id") or "")), "兼容桥已安装")
    except DshError as exc:
        return _fail(exc.message, exc.status)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)


@router.put("/api/dsh/connectors/{inst_id}/config")
def api_connector_config(inst_id: str, payload: dict = Body(...)):
    try:
        return _ok(configure_connector(inst_id, payload), "配置已保存")
    except DshError as exc:
        return _fail(exc.message, exc.status)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)


@router.post("/api/dsh/connectors/{inst_id}/test")
def api_connector_test(inst_id: str):
    try:
        return _ok(test_connector(inst_id), "DSH 连接正常")
    except DshError as exc:
        return _fail(exc.message, exc.status)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)


@router.post("/api/dsh/connectors/{inst_id}/reload")
def api_connector_reload(inst_id: str):
    try:
        return _ok(reload_connector(inst_id), "连接器已重载")
    except DshError as exc:
        return _fail(exc.message, exc.status)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
