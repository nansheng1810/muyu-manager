"""MCP mode: manage external agents that talk to QQ through Tulpa + SnowLuma.

The manager is the control plane only. Tulpa owns the persistent chat loop and
SnowLuma owns the OneBot transport. Tokens never leave this module's state file
and are never returned by public status endpoints.
"""

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
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException

from . import runner as runner_mod, store

router = APIRouter()

TULPA_DEFAULT = Path("D:/驰风车队项目/Tulpa")
SNOWLUMA_DEFAULT = Path("D:/驰风车队项目/SnowLuma")
DSH_PACKAGE_VERSION = "0.2.0-rc.2"
CODEX_SERVER = "muyu_qq"
RAW_SERVER = "muyu_raw"
DSH_PROFILE = "web"
DSH_MARK_BEGIN = "# === muyu mcp BEGIN (managed by 牧鱼) ==="
DSH_MARK_END = "# === muyu mcp END ==="
CODEX_MARK_BEGIN = "# === muyu mcp BEGIN (managed by 牧鱼) ==="
CODEX_MARK_END = "# === muyu mcp END ==="
STATE_PATH = store.DATA_DIR / "mcp_mode.json"
MCP_DIR = store.DATA_DIR / "mcp"
LOG_DIR = store.DATA_DIR / "logs"
RAW_WRAPPER = MCP_DIR / "muyu_raw_snowluma.mjs"
def _dsh_target() -> Path:
    raw = str(os.environ.get("MUYU_DSH_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    candidate = Path("D:/驰风车队项目/ai机器人管理/mcp_dsh")
    if candidate.is_dir() or candidate.parent.is_dir():
        return candidate
    return MCP_DIR / "dsh"


DSH_TARGET = _dsh_target()
SOURCE_BUILD_LOG = LOG_DIR / "mcp-snowluma-build.log"
SOURCE_RUN_LOG = LOG_DIR / "mcp-snowluma.log"

DEFAULT_STATE = {
    "tulpa_root": "",
    "backend": "managed",
    "snowluma_source": str(SNOWLUMA_DEFAULT),
    "source": {
        "http_port": 0,
        "ws_port": 0,
        "webui_port": 0,
        "token": "",
        "webui_password": "",
        "pid": 0,
        "started_at": "",
        "data_dir": str(MCP_DIR / "snowluma"),
        "uin": "",
    },
    "connection": {},
    "agents": {
        "codex": {"server_name": CODEX_SERVER},
        "dsh": {"server_name": CODEX_SERVER, "profile": DSH_PROFILE},
    },
    "raw": {"enabled": False, "write": False},
    "updated_at": "",
}

_lock = threading.RLock()
_build_lock = threading.Lock()
_dsh_install_lock = threading.Lock()
_build_job: dict = {
    "active": False,
    "phase": "",
    "ok": False,
    "error": "",
    "started_at": 0.0,
    "finished_at": 0.0,
}
_dsh_job: dict = {
    "active": False,
    "phase": "",
    "ok": False,
    "error": "",
    "started_at": 0.0,
    "finished_at": 0.0,
}


class McpModeError(Exception):
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
    return _deep_merge(DEFAULT_STATE, data if isinstance(data, dict) else {})


def save_state(data: dict) -> dict:
    data = _deep_merge(DEFAULT_STATE, data)
    data["updated_at"] = _now()
    store.write_json(STATE_PATH, data)
    return data


def _patch_state(**patch) -> dict:
    with _lock:
        data = load_state()
        data.update(patch)
        return save_state(data)


def _free_port(start: int) -> int:
    for port in range(int(start), int(start) + 200):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    raise McpModeError("找不到空闲本机端口。", 500)


def _port_open(port: int) -> bool:
    return bool(port) and runner_mod.port_open(int(port), timeout=0.5)


def _run(args, *, cwd=None, timeout=30, env=None) -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [str(item) for item in args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            creationflags=flags,
        )
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "命令超时"}
    except OSError as exc:
        return {"ok": False, "code": -1, "stdout": "", "stderr": str(exc)}


def _json_output(text: str):
    raw = (text or "").lstrip("\ufeff").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        pass
    starts = [idx for idx in (raw.find("{"), raw.find("[")) if idx >= 0]
    if not starts:
        return None
    start = min(starts)
    end = max(raw.rfind("}"), raw.rfind("]"))
    if end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except ValueError:
        return None


def _fail_from_output(result: dict, fallback: str) -> McpModeError:
    data = _json_output(result.get("stdout", ""))
    if isinstance(data, dict):
        message = data.get("message") or data.get("error") or data.get("detail")
        if message:
            return McpModeError(str(message), 400)
    stderr = (result.get("stderr") or "").strip().splitlines()
    if stderr:
        return McpModeError(stderr[-1][:300], 400)
    return McpModeError(fallback, 400)


# ----------------------------------------------------------------- Tulpa


def tulpa_root(value: str | None = None) -> Path:
    if value:
        path = Path(value).expanduser()
        if (path / "Tulpa.CLI.exe").is_file():
            return path
        raise McpModeError("所选目录没有 Tulpa.CLI.exe。")
    state = load_state()
    candidates = [
        state.get("tulpa_root"),
        os.environ.get("TULPA_ROOT"),
        str(TULPA_DEFAULT),
        str(store.BASE_DIR.parent / "Tulpa"),
        str(Path.home() / "Tulpa"),
    ]
    seen = set()
    for item in candidates:
        if not item:
            continue
        path = Path(item).expanduser()
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if (path / "Tulpa.CLI.exe").is_file():
            return path
    raise McpModeError("未找到 Tulpa：目录中缺少 Tulpa.CLI.exe。")


def _tulpa_cli(root: Path | None = None) -> Path:
    return (root or tulpa_root()) / "Tulpa.CLI.exe"


def tulpa_status() -> dict:
    root = tulpa_root()
    cli = _tulpa_cli(root)
    result = _run([cli, "--json", "status"], cwd=root, timeout=30)
    data = _json_output(result["stdout"])
    if not isinstance(data, dict):
        raise _fail_from_output(result, "Tulpa 状态读取失败。")
    data["root"] = str(root)
    data["cli"] = str(cli)
    return data


def _tulpa_service() -> tuple[str, dict]:
    status = tulpa_status()
    url = str(status.get("url") or "").rstrip("/")
    if not url:
        raise McpModeError("Tulpa 服务地址不可用。")
    parsed = urlparse(url)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise McpModeError("Tulpa 只允许本机地址。")
    return url, status


def tulpa_api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 40):
    base, _status = _tulpa_service()
    data = None
    headers = {
        "Accept": "application/json",
        "Origin": base,
        "x-chatweave-ui": "1",
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base + path, data=data, headers=headers, method=method
    )
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
        message = payload.get("detail") or payload.get("message") or payload.get("error")
        raise McpModeError(str(message or f"Tulpa 接口失败（HTTP {exc.code}）"), 400) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise McpModeError("连接不上 Tulpa 服务，请先启动 Tulpa。", 502) from None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise McpModeError("Tulpa 接口返回了无法解析的数据。", 502) from None


def tulpa_start() -> dict:
    root = tulpa_root()
    result = _run([_tulpa_cli(root), "start"], cwd=root, timeout=90)
    if not result["ok"]:
        raise _fail_from_output(result, "Tulpa 启动失败。")
    return tulpa_status()


def tulpa_stop() -> dict:
    root = tulpa_root()
    result = _run([_tulpa_cli(root), "stop"], cwd=root, timeout=60)
    if not result["ok"]:
        raise _fail_from_output(result, "Tulpa 停止失败。")
    return {"stopped": True, "root": str(root)}


def tulpa_enable_mcp() -> dict:
    try:
        current = tulpa_api("/api/mcp")
    except McpModeError:
        tulpa_start()
        current = tulpa_api("/api/mcp")
    if current.get("enabled") and current.get("running"):
        return current
    return tulpa_api(
        "/api/mcp",
        "PUT",
        {"enabled": True, "port": int(current.get("port") or 18777)},
    )


def tulpa_sl_status() -> dict:
    root = tulpa_root()
    result = _run([_tulpa_cli(root), "--json", "sl", "status"], cwd=root, timeout=30)
    data = _json_output(result["stdout"])
    if not isinstance(data, dict):
        raise _fail_from_output(result, "SnowLuma 托管状态读取失败。")
    data["choices"] = [
        _public_managed_choice(item) for item in (data.get("choices") or [])
    ]
    return data


def _public_managed_choice(item: dict) -> dict:
    path = str(item.get("path") or "")
    blocked = bool(re.search(r"napcat|astrbot", path, re.IGNORECASE))
    return {
        "id": item.get("id", ""),
        "pid": item.get("pid", 0),
        "path": path,
        "account": item.get("account", ""),
        "account_label": item.get("account_label", ""),
        "blocked": blocked,
        "reason": "该 QQ 进程由 NapCat/AstrBot 使用，不能同时被 SnowLuma 接管。" if blocked else "",
    }


def _json_or_ok(result: dict, fallback: str) -> dict:
    data = _json_output(result.get("stdout", ""))
    if isinstance(data, dict):
        return data
    if result.get("ok"):
        text = (result.get("stdout") or result.get("stderr") or "").strip()
        return {"ok": True, "message": text[-500:]}
    raise _fail_from_output(result, fallback)


def tulpa_sl_configure() -> dict:
    status = tulpa_sl_status()
    if not status.get("has_consent") or not status.get("consent_current"):
        raise McpModeError("需要先在 Tulpa 中同意当前 SnowLuma 协议。", 409)
    fingerprint = str(status.get("consent_fingerprint") or "")
    if not fingerprint:
        raise McpModeError("缺少 SnowLuma 授权指纹，请在 Tulpa 中重新配置。", 409)
    root = tulpa_root()
    result = _run(
        [_tulpa_cli(root), "--json", "sl", "configure", "--accept", fingerprint],
        cwd=root,
        timeout=120,
    )
    return _json_or_ok(result, "SnowLuma 配置失败。")


def tulpa_sl_select(choice_id: str) -> dict:
    choice_id = str(choice_id or "").strip()
    if not choice_id:
        raise McpModeError("请选择一个 QQ 进程。")
    status = tulpa_sl_status()
    choice = next(
        (item for item in status.get("choices", []) if item.get("id") == choice_id),
        None,
    )
    if not choice:
        raise McpModeError("QQ 进程列表已变化，请刷新后重试。", 409)
    if choice.get("blocked"):
        raise McpModeError(choice.get("reason") or "不能绑定 NapCat 进程。", 409)
    root = tulpa_root()
    result = _run(
        [_tulpa_cli(root), "--json", "sl", "select", choice_id],
        cwd=root,
        timeout=120,
    )
    return _json_or_ok(result, "绑定 QQ 进程失败。")


def tulpa_sl_test() -> dict:
    root = tulpa_root()
    result = _run([_tulpa_cli(root), "--json", "sl", "test"], cwd=root, timeout=90)
    return _json_or_ok(result, "OneBot 自检失败。")


def tulpa_sl_cancel() -> dict:
    root = tulpa_root()
    result = _run([_tulpa_cli(root), "--json", "sl", "cancel"], cwd=root, timeout=90)
    return _json_or_ok(result, "取消 SnowLuma 托管失败。")


def tulpa_personas() -> list[dict]:
    data = tulpa_api("/api/mcp/chat-personas")
    rows = (data.get("personas") or data.get("items") or []) if isinstance(data, dict) else data
    result = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": item.get("id") or item.get("name") or "",
                "name": item.get("name") or item.get("id") or "",
                "summary": item.get("summary") or "",
            }
        )
    return result


def tulpa_live_groups() -> list[dict]:
    data = tulpa_api("/api/mcp/live-groups")
    rows = data.get("items") if isinstance(data, dict) else []
    result = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "platform": item.get("platform") or "qq",
                "conversation_id": item.get("conversation_id") or "",
                "name": item.get("name") or item.get("conversation_id") or "",
                "count": item.get("count") or "",
            }
        )
    return result


def tulpa_live_friends() -> list[dict]:
    data = tulpa_api("/api/mcp/live-friends")
    rows = data.get("items") if isinstance(data, dict) else []
    return [
        {
            "platform": item.get("platform") or "qq",
            "conversation_id": item.get("conversation_id") or "",
            "name": item.get("name") or item.get("conversation_id") or "",
            "count": item.get("count") or "",
        }
        for item in rows or []
        if isinstance(item, dict)
    ]


def _connection_body(conversation_id: str, persona_preset: str, participation: str, flags: dict) -> dict:
    cid = str(conversation_id or "").strip()
    if not re.fullmatch(r"\d{5,10}:(?:group|direct):\d{5,20}", cid):
        raise McpModeError("会话 ID 格式应为 账号:group:群号 或 账号:direct:QQ。")
    if participation not in ("quiet", "natural", "active"):
        participation = "natural"
    body = {
        "name": "牧鱼 MCP",
        "modules": {"qq": True, "wechat": False, "bilibili": False},
        "platforms": ["qq"],
        "history_platforms": [],
        "conversations": [["qq", cid]],
        "all_conversations": False,
        "start": "",
        "end": "",
        "media": False,
        "prepare": False,
        "voice": False,
        "onebot": False,
        "send": True,
        "manage": bool(flags.get("manage")),
        "chat": True,
        "bilibili_read": False,
        "bilibili_share": False,
        "chat_images": bool(flags.get("chat_images", True)),
        "chat_sticker_send": bool(flags.get("chat_sticker_send", True)),
        "chat_sticker_collect": bool(flags.get("chat_sticker_collect", False)),
        "chat_reactions": bool(flags.get("chat_reactions", True)),
    }
    return body


def create_connection(payload: dict) -> dict:
    conversation_id = payload.get("conversation_id") or ""
    persona = payload.get("persona_preset") or ""
    participation = payload.get("participation") or "natural"
    flags = payload.get("flags") if isinstance(payload.get("flags"), dict) else {}
    body = _connection_body(conversation_id, persona, participation, flags)
    token = tulpa_enable_mcp()
    if not token.get("running"):
        raise McpModeError("Tulpa MCP 服务未运行。", 409)
    created = tulpa_api("/api/mcp/connections", "POST", body)
    token_value = str(created.get("token") or "")
    if not token_value:
        raise McpModeError("Tulpa 没有返回连接凭据。", 502)
    stored = {
        "id": created.get("id", ""),
        "name": created.get("name") or body["name"],
        "token": token_value,
        "conversation_id": conversation_id,
        "persona_preset": persona,
        "participation": participation,
        "flags": flags,
        "scope": {
            key: body.get(key)
            for key in (
                "platforms",
                "conversations",
                "send",
                "manage",
                "chat",
                "chat_images",
                "chat_sticker_send",
                "chat_sticker_collect",
                "chat_reactions",
            )
        },
        "created_at": _now(),
    }
    state = _patch_state(connection=stored)
    return _public_connection(state)


def _public_connection(state: dict | None = None) -> dict:
    state = state or load_state()
    item = dict(state.get("connection") or {})
    token = str(item.pop("token", "") or "")
    item["token_saved"] = bool(token)
    return item


def _connection_token() -> tuple[dict, str]:
    state = load_state()
    item = state.get("connection") or {}
    token = str(item.get("token") or "")
    if not item.get("id") or not token:
        raise McpModeError("还没有可用的聊天连接，请先创建连接。", 409)
    return item, token


def revoke_connection() -> dict:
    state = load_state()
    item = state.get("connection") or {}
    gid = item.get("id")
    if gid:
        try:
            tulpa_api(f"/api/mcp/connections/{gid}/revoke", "POST", {})
        except McpModeError:
            pass
    _patch_state(connection={})
    return {"revoked": bool(gid)}


def test_connection() -> dict:
    _item, token = _connection_token()
    result = tulpa_api("/api/mcp/test", "POST", {"token": token}, timeout=40)
    return result


def chat_sessions() -> dict:
    data = tulpa_api("/api/mcp/chats")
    sessions = []
    for item in (data.get("sessions") or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        sessions.append(
            {
                "id": item.get("id") or "",
                "name": item.get("name") or "",
                "conversation_id": item.get("conversation_id") or "",
                "persona_name": item.get("persona_name") or "",
                "participation": item.get("participation") or "",
                "active": bool(item.get("active")),
                "updated": item.get("updated") or 0,
                "note": item.get("note") or "",
            }
        )
    return {
        "sessions": sessions,
        "receiver": (data.get("receiver") if isinstance(data, dict) else {}) or {},
    }


def start_chat() -> dict:
    item, _token = _connection_token()
    cid = str(item.get("conversation_id") or "")
    persona = str(item.get("persona_preset") or "")
    if not cid:
        raise McpModeError("连接缺少会话 ID。", 409)
    body = {
        "connection_id": item.get("id"),
        "conversation_id": cid,
        "persona_preset": persona,
        "idempotency_key": secrets.token_hex(16),
    }
    return tulpa_api("/api/mcp/chats/start", "POST", body)


def stop_chat(session_id: str) -> dict:
    sid = str(session_id or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", sid):
        raise McpModeError("会话 ID 无效。")
    return tulpa_api(f"/api/mcp/chats/{sid}/stop", "POST", {})


# ------------------------------------------------------------- Codex / DSH


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()


def _safe_server_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(value or "")):
        raise McpModeError("MCP 名称只能包含 1–64 位字母、数字、下划线或短横线。")
    return str(value)


def _codex_block(url: str, token: str, server_name: str, raw: bool) -> str:
    lines = [
        CODEX_MARK_BEGIN,
        f"[mcp_servers.{server_name}]",
        f"url = {json.dumps(url)}",
        f"http_headers = {{ Authorization = {json.dumps('Bearer ' + token)} }}",
        "tool_timeout_sec = 240",
    ]
    if raw:
        lines += [
            "",
            f"[mcp_servers.{RAW_SERVER}]",
            f"command = {json.dumps(shutil.which('node') or 'node')}",
            f"args = [{json.dumps(str(RAW_WRAPPER))}]",
            "tool_timeout_sec = 120",
        ]
    lines.append(CODEX_MARK_END)
    return chr(10).join(lines) + chr(10)


def install_codex(home: Path | None = None, server_name: str = CODEX_SERVER) -> dict:
    item, token = _connection_token()
    status = tulpa_status()
    url = str((status.get("mcp") or {}).get("url") or "")
    if not url:
        raise McpModeError("Tulpa MCP 地址不可用。", 409)
    server_name = _safe_server_name(server_name)
    raw = bool(load_state().get("raw", {}).get("enabled"))
    home = Path(home) if home is not None else codex_home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.toml"
    with _lock:
        original = path.read_bytes() if path.exists() else b""
        text = original.decode("utf-8-sig").replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))
        block = _codex_block(url, token, server_name, raw)
        block_data = tomllib.loads(block)
        start = text.find(CODEX_MARK_BEGIN)
        if start >= 0:
            end = text.find(CODEX_MARK_END, start)
            if end < 0:
                raise McpModeError("Codex 配置中的牧鱼标记不完整，未修改。", 409)
            end += len(CODEX_MARK_END)
            if text[start:end].strip() == block.strip():
                return {"installed": True, "changed": False, "path": str(path), "server_name": server_name, "connection_id": item.get("id")}
            base_text = text[:start].rstrip() + chr(10) + text[end:].lstrip(chr(10))
        else:
            if (f"[mcp_servers.{server_name}]" in text or f"[mcp_servers.{RAW_SERVER}]" in text):
                raise McpModeError(f"Codex 已有同名 MCP 配置但没有牧鱼标记，未覆盖。", 409)
            base_text = text
        try:
            before = tomllib.loads(base_text) if base_text.strip() else {}
        except (ValueError, UnicodeError):
            raise McpModeError("Codex 配置无法解析，未修改。", 409) from None
        updated = ((base_text.rstrip() + chr(10) + chr(10)) if base_text.strip() else "") + block
        try:
            after = tomllib.loads(updated)
        except (ValueError, UnicodeError):
            raise McpModeError("生成的 Codex 配置无法解析，未修改。", 409) from None
        expected = dict(before)
        expected["mcp_servers"] = dict(before.get("mcp_servers") or {})
        expected["mcp_servers"].update(block_data.get("mcp_servers") or {})
        if after != expected:
            raise McpModeError("无法安全合并 Codex 配置，未修改。", 409)
        if original:
            backup_dir = home / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"config-before-muyu-{time.time_ns()}.toml"
            backup.write_bytes(original)
        tmp = path.with_suffix(".toml.muyu.tmp")
        tmp.write_bytes(updated.encode("utf-8"))
        os.replace(tmp, path)
    return {"installed": True, "changed": True, "path": str(path), "server_name": server_name, "connection_id": item.get("id")}


def codex_status() -> dict:
    path = codex_home() / "config.toml"
    if not path.exists():
        return {"installed": False, "path": str(path)}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        return {"installed": False, "path": str(path), "error": "配置无法解析"}
    entry = (data.get("mcp_servers") or {}).get(CODEX_SERVER)
    if not isinstance(entry, dict):
        return {"installed": False, "path": str(path)}
    return {
        "installed": True,
        "path": str(path),
        "url": entry.get("url") or "",
        "server_name": CODEX_SERVER,
        "token_saved": bool((entry.get("http_headers") or {}).get("Authorization")),
        "raw_installed": isinstance((data.get("mcp_servers") or {}).get(RAW_SERVER), dict),
    }


def dsh_home() -> Path:
    return Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh")).expanduser()


def dsh_patch_path() -> Path:
    return dsh_home() / "profiles" / DSH_PROFILE / "cordis.patch.yml"


def _dsh_block(url: str, raw: bool, raw_wrapper: Path) -> str:
    lines = [
        DSH_MARK_BEGIN,
        "- insert:",
        "    - id: mcp-muyu-qq",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        "      config:",
        "        serverName: muyu_qq",
        "        transport: streamable-http",
        f"        url: {json.dumps(url)}",
        "        headers:",
        "          Authorization: !!js '`Bearer ${process.env.MUYU_MCP_TOKEN}`'",
        "        toolCallTimeoutMs: 240000",
        "        failOnStartupError: true",
    ]
    if raw:
        lines += [
            "    - id: mcp-muyu-raw",
            "      name: '@deepseek-ai/dsh-mcp-client'",
            "      config:",
            "        serverName: muyu_raw",
            "        transport: stdio",
            f"        command: {json.dumps(shutil.which('node') or 'node')}",
            "        args:",
            f"          - {json.dumps(str(raw_wrapper))}",
            "        toolCallTimeoutMs: 120000",
        ]
    lines.append(DSH_MARK_END)
    return "\n".join(lines) + "\n"


def install_dsh() -> dict:
    item, _token = _connection_token()
    status = tulpa_status()
    url = str((status.get("mcp") or {}).get("url") or "")
    if not url:
        raise McpModeError("Tulpa MCP 地址不可用。", 409)
    raw = bool(load_state().get("raw", {}).get("enabled"))
    block = _dsh_block(url, raw, RAW_WRAPPER)
    path = dsh_patch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        start = original.find(DSH_MARK_BEGIN)
        if start >= 0:
            end = original.find(DSH_MARK_END, start)
            if end < 0:
                raise McpModeError("DSH 配置中的牧鱼标记不完整，未修改。", 409)
            updated = original[:start].rstrip() + "\n\n" + block + original[end + len(DSH_MARK_END):].lstrip("\n")
        else:
            if "id: mcp-muyu-qq" in original:
                raise McpModeError("DSH 已有同名 MCP 配置但没有牧鱼标记，未覆盖。", 409)
            updated = original.rstrip() + "\n\n" + block
        if updated == original:
            return {"installed": True, "changed": False, "path": str(path), "server_name": CODEX_SERVER, "restart_required": True, "connection_id": item.get("id")}
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"cordis.patch.before-muyu-{time.time_ns()}.yml"
        backup.write_text(original, encoding="utf-8")
        tmp = path.with_suffix(".yml.muyu.tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, path)
    return {"installed": True, "changed": True, "path": str(path), "server_name": CODEX_SERVER, "restart_required": True, "connection_id": item.get("id")}


def dsh_status() -> dict:
    path = dsh_patch_path()
    text = ""
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
    bin_js = ""
    version = ""
    error = ""
    launchable = False
    try:
        from . import dsh as dsh_mod

        bin_js = str(dsh_mod.resolve_bin_js())
        version = dsh_mod.read_version()
        node = shutil.which("node") or "node"
        probe = _run([node, bin_js, "--version"], timeout=15)
        launchable = bool(probe["ok"] and (probe["stdout"].strip() or probe["stderr"].strip()))
        if not launchable:
            error = (probe["stderr"] or probe["stdout"] or "DSH 无法启动").strip().splitlines()[-1][:300]
    except Exception as exc:  # noqa: BLE001
        error = getattr(exc, "message", str(exc))
    return {
        "installed": bool(bin_js and launchable),
        "launchable": launchable,
        "version": version,
        "bin_js": bin_js,
        "error": error,
        "patch_path": str(path),
        "config_installed": "id: mcp-muyu-qq" in text,
        "raw_installed": "id: mcp-muyu-raw" in text,
        "running": runner_mod.port_open(3080, timeout=0.4),
        "package_dir": str(DSH_TARGET),
        "install": dict(_dsh_job),
    }


def dsh_env() -> dict:
    state = load_state()
    item = state.get("connection") or {}
    token = str(item.get("token") or "")
    if not token:
        return {}
    try:
        status = tulpa_status()
        url = str((status.get("mcp") or {}).get("url") or "")
    except McpModeError:
        url = ""
    return {
        "MUYU_MCP_TOKEN": token,
        "MUYU_MCP_URL": url or "http://127.0.0.1:18777/mcp",
    }


def _dsh_install_worker() -> None:
    global _dsh_job
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "mcp-dsh-install.log"
    with _dsh_install_lock:
        _dsh_job.update(active=True, phase="安装 DSH", ok=False, error="", started_at=time.time(), finished_at=0.0)
    npm = shutil.which("npm")
    if not npm:
        with _dsh_install_lock:
            _dsh_job.update(active=False, phase="失败", error="未找到 npm。", finished_at=time.time())
        return
    DSH_TARGET.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["npm_config_audit"] = "false"
    env["npm_config_fund"] = "false"
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"[{_now()}] npm install @deepseek-ai/dsh@{DSH_PACKAGE_VERSION}\n")
        log.flush()
        try:
            proc = subprocess.run(
                [npm, "install", "--prefix", str(DSH_TARGET), "--no-audit", "--no-fund", f"@deepseek-ai/dsh@{DSH_PACKAGE_VERSION}"],
                cwd=str(DSH_TARGET),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=1800,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            ok = proc.returncode == 0
            binary = DSH_TARGET / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
            if ok and not binary.is_file():
                ok = False
                error = "安装结束但没有找到 DSH bin.js。"
            else:
                error = "" if ok else f"npm 退出码 {proc.returncode}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            ok = False
            error = f"安装失败：{exc}"
        with _dsh_install_lock:
            _dsh_job.update(active=False, phase="完成" if ok else "失败", ok=ok, error=error, finished_at=time.time())


def start_dsh_install() -> dict:
    with _dsh_install_lock:
        if _dsh_job.get("active"):
            return dict(_dsh_job)
    threading.Thread(target=_dsh_install_worker, daemon=True, name="muyu-dsh-install").start()
    time.sleep(0.2)
    with _dsh_install_lock:
        return dict(_dsh_job)


def dsh_install_status() -> dict:
    with _dsh_install_lock:
        job = dict(_dsh_job)
    job["binary_exists"] = (DSH_TARGET / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js").is_file()
    return job


# --------------------------------------------------------- SnowLuma source


def source_root() -> Path:
    state = load_state()
    path = Path(state.get("snowluma_source") or SNOWLUMA_DEFAULT).expanduser()
    if not (path / "package.json").is_file():
        raise McpModeError("SnowLuma 源码目录无效：缺少 package.json。")
    return path


def _source_built(root: Path | None = None) -> bool:
    root = root or source_root()
    return (root / "dist" / "index.mjs").is_file() and (root / "packages" / "mcp" / "dist" / "server.js").is_file()


def _source_ports(state: dict) -> tuple[int, int, int]:
    src = state.get("source") or {}
    http = int(src.get("http_port") or 0)
    ws = int(src.get("ws_port") or 0)
    webui = int(src.get("webui_port") or 0)
    if not http or _port_open(http):
        http = _free_port(6801)
    if not ws or _port_open(ws) or ws == http:
        ws = _free_port(http + 1)
    if not webui or _port_open(webui) or webui in (http, ws):
        webui = _free_port(6800)
    return http, ws, webui


def _source_onebot_config(http_port: int, ws_port: int, token: str) -> dict:
    return {
        "networks": {
            "httpServers": [
                {
                    "name": "muyu-http",
                    "host": "127.0.0.1",
                    "port": http_port,
                    "path": "/",
                    "enableWebSocket": False,
                    "enableSse": False,
                    "accessToken": token,
                    "messageFormat": "array",
                    "reportSelfMessage": False,
                }
            ],
            "httpClients": [],
            "wsServers": [
                {
                    "name": "muyu-ws",
                    "host": "127.0.0.1",
                    "port": ws_port,
                    "path": "/",
                    "role": "Universal",
                    "accessToken": token,
                    "messageFormat": "array",
                    "reportSelfMessage": True,
                }
            ],
            "wsClients": [],
        },
        "statusCommand": {"enabled": True, "swallow": False, "cooldownSeconds": 5, "trigger": "#sl"},
        "historySync": {"enabled": False},
        "notifications": {"channelIds": []},
    }


def _write_source_config(data_dir: Path, http_port: int, ws_port: int, webui_port: int, token: str) -> None:
    config = data_dir / "config"
    config.mkdir(parents=True, exist_ok=True)
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    store.write_json(config / "runtime.json", {"webuiPort": webui_port})
    store.write_json(config / "onebot.json", _source_onebot_config(http_port, ws_port, token))


def onebot_call(action: str, params: dict | None = None, timeout: int = 6):
    state = load_state()
    src = state.get("source") or {}
    port = int(src.get("http_port") or 0)
    token = str(src.get("token") or "")
    if not port or not token:
        raise McpModeError("源码后端还没有启动。", 409)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/{action}",
        data=json.dumps(params or {}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise McpModeError(f"OneBot 接口拒绝请求（HTTP {exc.code}）。", 409) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise McpModeError("连不上源码 SnowLuma 的 OneBot 接口。", 409) from None
    if not isinstance(payload, dict) or payload.get("retcode") != 0 or payload.get("status") != "ok":
        raise McpModeError("OneBot 返回失败，请检查账号登录状态。", 409)
    return payload.get("data")


def source_status() -> dict:
    state = load_state()
    src = state.get("source") or {}
    root = Path(state.get("snowluma_source") or SNOWLUMA_DEFAULT)
    pid = int(src.get("pid") or 0)
    ports = {
        "http": int(src.get("http_port") or 0),
        "ws": int(src.get("ws_port") or 0),
        "webui": int(src.get("webui_port") or 0),
    }
    running = bool(pid and runner_mod.pid_alive(pid) and ports["webui"] and _port_open(ports["webui"]))
    account = ""
    onebot_ready = False
    onebot_error = ""
    if running:
        try:
            info = onebot_call("get_login_info", timeout=2)
            account = str((info or {}).get("user_id") or "")
            onebot_ready = bool(account)
        except McpModeError:
            onebot_error = "OneBot 端口尚未启动；请在 SnowLuma 控制台加载 QQ 进程并完成登录。"
    with _build_lock:
        job = dict(_build_job)
    return {
        "root": str(root),
        "root_exists": (root / "package.json").is_file(),
        "built": _source_built(root) if (root / "package.json").is_file() else False,
        "running": running,
        "pid": pid,
        "ports": ports,
        "webui_url": f"http://127.0.0.1:{ports['webui']}" if ports["webui"] else "",
        "onebot": {
            "http_url": f"http://127.0.0.1:{ports['http']}/" if ports["http"] else "",
            "ws_url": f"ws://127.0.0.1:{ports['ws']}/" if ports["ws"] else "",
            "token_saved": bool(src.get("token")),
            "ready": onebot_ready,
            "account": account,
            "error": onebot_error,
        },
        "webui_password_saved": bool(src.get("webui_password")),
        "build": job,
        "data_dir": str(src.get("data_dir") or (MCP_DIR / "snowluma")),
        "uin": src.get("uin") or "",
    }


def _source_build_worker(root: Path) -> None:
    global _build_job
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    phases = [
        ("安装依赖", [shutil.which("pnpm") or "pnpm", "install", "--frozen-lockfile"]),
        ("构建全部", [shutil.which("pnpm") or "pnpm", "build:all"]),
    ]
    env = dict(os.environ)
    env["CI"] = "1"
    env["SNOWLUMA_TARGET"] = "win32-x64"
    env["NO_COLOR"] = "1"
    ok = True
    error = ""
    with SOURCE_BUILD_LOG.open("w", encoding="utf-8") as log:
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
            error = "构建结束但缺少 dist/index.mjs 或 packages/mcp/dist/server.js"
        log.write(f"\n[{_now()}] {'完成' if ok else error}\n")
    with _build_lock:
        _build_job.update(
            active=False,
            phase="完成" if ok else "失败",
            ok=ok,
            error=error,
            finished_at=time.time(),
        )


def start_source_build() -> dict:
    root = source_root()
    with _build_lock:
        if _build_job.get("active"):
            return dict(_build_job)
    if not shutil.which("pnpm"):
        raise McpModeError("未找到 pnpm，请先安装 pnpm 11.25.0。", 409)
    if not shutil.which("node"):
        raise McpModeError("未找到 Node.js。", 409)
    with _build_lock:
        _build_job.update(
            active=True,
            phase="准备",
            ok=False,
            error="",
            started_at=time.time(),
            finished_at=0.0,
        )
    threading.Thread(target=_source_build_worker, args=(root,), daemon=True, name="muyu-snowluma-build").start()
    time.sleep(0.2)
    with _build_lock:
        return dict(_build_job)


def start_source() -> dict:
    root = source_root()
    if not _source_built(root):
        raise McpModeError("源码后端还没有构建，请先构建。", 409)
    state = load_state()
    src = dict(state.get("source") or {})
    pid = int(src.get("pid") or 0)
    if pid and runner_mod.pid_alive(pid):
        return source_status()
    http_port, ws_port, webui_port = _source_ports(state)
    token = str(src.get("token") or "") or secrets.token_urlsafe(32)
    password = str(src.get("webui_password") or "") or secrets.token_urlsafe(24)
    data_dir = Path(src.get("data_dir") or (MCP_DIR / "snowluma")).expanduser()
    _write_source_config(data_dir, http_port, ws_port, webui_port, token)
    node = shutil.which("node")
    if not node:
        raise McpModeError("未找到 Node.js。", 409)
    env = dict(os.environ)
    env["SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD"] = password
    env["SNOWLUMA_UPDATE_CHECK"] = "off"
    env["NO_COLOR"] = "1"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = SOURCE_RUN_LOG.open("ab")
    log.write(f"\n[{_now()}] manager starting SnowLuma source: {root}\n".encode("utf-8"))
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
        raise McpModeError(f"启动 SnowLuma 失败：{exc}", 500) from None
    finally:
        log.close()
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        if _port_open(webui_port):
            break
        time.sleep(0.4)
    if proc.poll() is not None or not _port_open(webui_port):
        try:
            if proc.poll() is None:
                proc.terminate()
        except OSError:
            pass
        raise McpModeError("SnowLuma WebUI 没有在 60 秒内启动，请查看日志。", 500)
    src.update(
        http_port=http_port,
        ws_port=ws_port,
        webui_port=webui_port,
        token=token,
        webui_password=password,
        pid=proc.pid,
        started_at=_now(),
        data_dir=str(data_dir),
    )
    _patch_state(source=src)
    return source_status()


def stop_source() -> dict:
    state = load_state()
    src = dict(state.get("source") or {})
    pid = int(src.get("pid") or 0)
    if pid and runner_mod.pid_alive(pid):
        if os.name == "nt":
            result = _run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=20)
            if not result["ok"]:
                raise McpModeError("停止 SnowLuma 失败，请手动检查进程。", 500)
        else:
            try:
                os.kill(pid, 15)
            except OSError as exc:
                raise McpModeError(f"停止 SnowLuma 失败：{exc}", 500) from None
    src["pid"] = 0
    _patch_state(source=src)
    return source_status()


def source_webui_secret() -> dict:
    state = load_state()
    src = state.get("source") or {}
    return {
        "url": f"http://127.0.0.1:{int(src.get('webui_port') or 0)}" if src.get("webui_port") else "",
        "password": str(src.get("webui_password") or ""),
    }


def _source_webui_base() -> str:
    state = load_state()
    port = int((state.get("source") or {}).get("webui_port") or 0)
    if not port:
        raise McpModeError("源码 SnowLuma 还没有启动。", 409)
    return f"http://127.0.0.1:{port}"


def _source_webui_request(path: str, method: str = "GET", body: dict | None = None, token: str | None = None, timeout: int = 15):
    base = _source_webui_base()
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
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
            message = "请先打开 SnowLuma 控制台，阅读并同意 EULA / 隐私政策，再读取 QQ 进程。"
        raise McpModeError(str(message), 409) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise McpModeError("连不上 SnowLuma 控制台，请确认源码后端在运行。", 409) from None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise McpModeError("SnowLuma 控制台返回了无法解析的数据。", 502) from None


def _source_webui_token() -> str:
    state = load_state()
    password = str((state.get("source") or {}).get("webui_password") or "")
    if not password:
        raise McpModeError("缺少 SnowLuma 控制台密码，请重新启动源码后端。", 409)
    payload = _source_webui_request("/api/login", "POST", {"password": password})
    token = str(payload.get("token") or "") if isinstance(payload, dict) else ""
    if not token:
        raise McpModeError("SnowLuma 控制台登录失败，可能已在控制台修改密码。", 409)
    return token


def source_webui_overview() -> dict:
    token = _source_webui_token()
    status = _source_webui_request("/api/status", token=token)
    agreements = _source_webui_request("/api/agreements", token=token)
    return {
        "status": status if isinstance(status, dict) else {},
        "agreements": {
            "version": agreements.get("version") if isinstance(agreements, dict) else "",
            "consent_required": bool(agreements.get("consentRequired")) if isinstance(agreements, dict) else False,
            "documents": [
                {"id": item.get("id"), "title": item.get("title")}
                for item in (agreements.get("documents") or [])
                if isinstance(item, dict)
            ] if isinstance(agreements, dict) else [],
        },
        "webui_url": _source_webui_base(),
    }


def source_processes() -> list[dict]:
    token = _source_webui_token()
    payload = _source_webui_request("/api/processes", token=token)
    rows = payload.get("list") if isinstance(payload, dict) else []
    result = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        blocked = bool(re.search(r"napcat|astrbot", path, re.IGNORECASE))
        account = item.get("account") if isinstance(item.get("account"), dict) else {}
        result.append(
            {
                "pid": item.get("pid", 0),
                "name": item.get("name") or "",
                "path": path,
                "status": item.get("status") or "",
                "logged_in": bool(item.get("loggedIn")),
                "uin": item.get("uin") or "",
                "account": account.get("uin") or "",
                "nickname": account.get("nickname") or "",
                "blocked": blocked,
                "reason": "该 QQ 进程由 NapCat/AstrBot 使用，不能同时被 SnowLuma 接管。" if blocked else "",
            }
        )
    return result


def source_select_process(pid: int) -> dict:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise McpModeError("QQ 进程号无效。")
    if pid <= 0:
        raise McpModeError("QQ 进程号无效。")
    token = _source_webui_token()
    rows = source_processes()
    choice = next((item for item in rows if int(item.get("pid") or 0) == pid), None)
    if not choice:
        raise McpModeError("QQ 进程列表已变化，请刷新后重试。", 409)
    if choice.get("blocked"):
        raise McpModeError(choice.get("reason") or "不能绑定 NapCat 进程。", 409)
    response = _source_webui_request(f"/api/processes/{pid}/load", "POST", {}, token=token, timeout=40)
    deadline = time.time() + 25
    ready = False
    account = ""
    while time.time() < deadline:
        try:
            info = onebot_call("get_login_info", timeout=2)
            account = str((info or {}).get("user_id") or "")
            ready = bool(account)
            if ready:
                break
        except McpModeError:
            pass
        time.sleep(1)
    state = load_state()
    src = dict(state.get("source") or {})
    if account:
        src["uin"] = account
        _patch_state(source=src)
    return {
        "process": response if isinstance(response, dict) else {},
        "choice": choice,
        "onebot": {
            "ready": ready,
            "account": account,
            "error": "" if ready else "QQ 还在登录或尚未开始接收；请在 QQ 客户端完成扫码后刷新。",
        },
    }


def connect_source_to_tulpa(force: bool = False) -> dict:
    state = load_state()
    src = state.get("source") or {}
    if not int(src.get("pid") or 0) or not _port_open(int(src.get("http_port") or 0)):
        raise McpModeError("源码 SnowLuma 没有运行或 OneBot 接口未启动。", 409)
    info = onebot_call("get_login_info")
    account = str((info or {}).get("user_id") or "")
    try:
        managed = tulpa_sl_status()
    except McpModeError:
        managed = {}
    if managed.get("enabled") and not force:
        raise McpModeError("当前正在使用托管 QQ；切换会停止托管 SnowLuma，请确认后重试。", 409)
    if managed.get("enabled"):
        try:
            tulpa_sl_cancel()
        except McpModeError:
            pass
    body = {
        "sender_url": f"http://127.0.0.1:{int(src.get('http_port') or 0)}/",
        "sender_token": str(src.get("token") or ""),
        "events_url": f"ws://127.0.0.1:{int(src.get('ws_port') or 0)}/",
        "events_token": str(src.get("token") or ""),
    }
    saved = tulpa_api("/api/desktop/settings", "PUT", body)
    src["uin"] = account
    _patch_state(source=src)
    return {"account": account, "settings": saved, "onebot": source_status()["onebot"]}


def source_groups() -> list[dict]:
    rows = onebot_call("get_group_list", {"no_cache": True})
    result = []
    account = source_status()["onebot"].get("account") or ""
    for item in rows or []:
        if not isinstance(item, dict) or not str(item.get("group_id", "")).isdigit():
            continue
        result.append(
            {
                "platform": "qq",
                "conversation_id": f"{account}:group:{item['group_id']}",
                "name": str(item.get("group_name") or item.get("group_id")),
                "count": "OneBot",
            }
        )
    return result


# ------------------------------------------------------------ raw actions


def _raw_wrapper_text(state: dict) -> str:
    src = state.get("source") or {}
    raw = state.get("raw") or {}
    port = int(src.get("http_port") or 0)
    ws = int(src.get("ws_port") or 0)
    token = str(src.get("token") or "")
    server = source_root() / "packages" / "mcp" / "dist" / "server.js"
    mode = "write" if raw.get("write") else "read"
    return (
        "import { pathToFileURL } from 'node:url';\n"
        f"process.env.SNOWLUMA_MCP_ENDPOINT = {json.dumps(f'http://127.0.0.1:{port}/')};\n"
        f"process.env.SNOWLUMA_MCP_TOKEN = {json.dumps(token)};\n"
        f"process.env.SNOWLUMA_MCP_MODE = {json.dumps(mode)};\n"
        f"process.env.SNOWLUMA_MCP_EVENTS_URL = {json.dumps(f'ws://127.0.0.1:{ws}/')};\n"
        f"await import(pathToFileURL({json.dumps(str(server))}).href);\n"
    )


def raw_status() -> dict:
    state = load_state()
    raw = state.get("raw") or {}
    root = Path(state.get("snowluma_source") or SNOWLUMA_DEFAULT)
    server = root / "packages" / "mcp" / "dist" / "server.js"
    return {
        "enabled": bool(raw.get("enabled")),
        "write": bool(raw.get("write")),
        "server_built": server.is_file(),
        "wrapper": str(RAW_WRAPPER),
        "wrapper_exists": RAW_WRAPPER.is_file(),
    }


def save_raw(enabled: bool, write: bool) -> dict:
    if write and not enabled:
        raise McpModeError("要写操作必须先启用全量动作。")
    state = load_state()
    state["raw"] = {"enabled": bool(enabled), "write": bool(write)}
    if enabled:
        root = Path(state.get("snowluma_source") or SNOWLUMA_DEFAULT)
        if not (root / "packages" / "mcp" / "dist" / "server.js").is_file():
            raise McpModeError("SnowLuma MCP 还没有构建，请先构建源码。", 409)
        src = state.get("source") or {}
        if not int(src.get("pid") or 0) or not int(src.get("http_port") or 0) or not src.get("token"):
            raise McpModeError("请先启动源码后端，再启用全量动作。", 409)
        RAW_WRAPPER.parent.mkdir(parents=True, exist_ok=True)
        RAW_WRAPPER.write_text(_raw_wrapper_text(state), encoding="utf-8")
    save_state(state)
    return raw_status()


# ----------------------------------------------------------------- agents


def agents_status() -> dict:
    return {"codex": codex_status(), "dsh": dsh_status()}


def install_agent(agent: str) -> dict:
    if agent == "codex":
        return install_codex()
    if agent == "dsh":
        return install_dsh()
    raise McpModeError("未知 Agent。")


def test_agent(agent: str) -> dict:
    if agent not in ("codex", "dsh"):
        raise McpModeError("未知 Agent。")
    result = test_connection()
    return {"agent": agent, "mcp": result}


def agent_prompt() -> str:
    item = _public_connection()
    cid = item.get("conversation_id") or "<会话 ID>"
    persona = item.get("persona_preset") or "<人格>"
    participation = item.get("participation") or "natural"
    return (
        "你现在通过 Tulpa MCP 在 QQ 中持续聊天。先调用 list_chat_sessions 查看是否有同目标会话；"
        "没有就调用 list_chat_groups 和 list_chat_personas，选择 "
        f"{cid}、人格 {persona}、参与度 {participation}，再调用 start_chat_session。"
        "随后持续执行 wait_chat_messages → plan_chat_reply → send_chat_reply；"
        "idle 不是结束，继续 wait。用户明确停止时调用 stop_chat_session。"
        "不要结束当前任务，不要把工具返回的内部字段发到群里。"
    )


# ------------------------------------------------------------------ status


def public_status() -> dict:
    state = load_state()
    tulpa = {}
    tulpa_error = ""
    try:
        tulpa = tulpa_status()
    except Exception as exc:  # noqa: BLE001
        tulpa_error = getattr(exc, "message", str(exc))
    managed = {}
    managed_error = ""
    try:
        managed = tulpa_sl_status()
    except Exception as exc:  # noqa: BLE001
        managed_error = getattr(exc, "message", str(exc))
    try:
        source = source_status()
    except Exception as exc:  # noqa: BLE001
        source = {
            "root": str(state.get("snowluma_source") or ""),
            "root_exists": False,
            "built": False,
            "running": False,
            "pid": 0,
            "ports": {"http": 0, "ws": 0, "webui": 0},
            "webui_url": "",
            "onebot": {"ready": False, "account": "", "error": getattr(exc, "message", str(exc))},
            "webui_password_saved": False,
            "build": {},
            "data_dir": "",
            "uin": "",
        }
    try:
        agents = agents_status()
    except Exception as exc:  # noqa: BLE001
        agents = {"codex": {"installed": False, "error": str(exc)}, "dsh": {"installed": False, "error": str(exc)}}
    return {
        "tulpa": {
            "root": str(tulpa.get("root") or ""),
            "version": str(tulpa.get("version") or ""),
            "url": str(tulpa.get("url") or ""),
            "mcp": tulpa.get("mcp") or {},
            "connections": tulpa.get("connections") or 0,
            "error": tulpa_error,
        },
        "backend": state.get("backend") or "managed",
        "managed": {
            "version": managed.get("version") or "",
            "phase": managed.get("phase") or "",
            "phase_label": managed.get("phase_label") or "",
            "account": managed.get("account") or "",
            "message": managed.get("message") or "",
            "choices": managed.get("choices") or [],
            "selection_required": bool(managed.get("selection_required")),
            "has_consent": bool(managed.get("has_consent")),
            "consent_current": bool(managed.get("consent_current")),
            "consent_fingerprint": managed.get("consent_fingerprint") or "",
            "ports": managed.get("ports") or {},
            "qq_ready": bool(managed.get("qq_ready")),
            "error": managed_error,
        },
        "source": source,
        "connection": _public_connection(state),
        "agents": agents,
        "raw": raw_status(),
        "prompt": agent_prompt(),
        "security": {
            "loopback_only": True,
            "napcat_exclusive": True,
            "snowluma_license": "源码可见非商业许可，仅本地自用构建，不随牧鱼安装包分发。",
        },
        "updated_at": state.get("updated_at") or "",
    }


def set_backend(kind: str) -> dict:
    if kind not in ("managed", "source"):
        raise McpModeError("后端只能是 managed 或 source。")
    _patch_state(backend=kind)
    return public_status()


def set_tulpa_root(path: str) -> dict:
    root = tulpa_root(path)
    _patch_state(tulpa_root=str(root))
    return public_status()


def logs(lines: int = 120) -> dict:
    text = []
    for path, label in (
        (SOURCE_BUILD_LOG, "snowluma-build"),
        (SOURCE_RUN_LOG, "snowluma"),
        (LOG_DIR / "mcp-dsh-install.log", "dsh-install"),
    ):
        if not path.exists():
            continue
        try:
            tail = runner_mod.tail(path, lines=max(1, min(int(lines), 400)))
        except Exception:
            tail = []
        if tail:
            text.append(f"== {label} ==")
            text.extend(tail)
    return {"text": "\n".join(text[-800:])}


# ------------------------------------------------------------------ routes


def _guard(fn, *args, **kwargs):
    try:
        return _ok(fn(*args, **kwargs))
    except McpModeError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.get("/api/mcp-mode/status")
def api_status():
    return _guard(public_status)


@router.get("/api/mcp-mode/tulpa")
def api_tulpa():
    def read():
        status = tulpa_status()
        managed = {}
        try:
            managed = tulpa_sl_status()
        except McpModeError as exc:
            managed = {"error": exc.message}
        return {"tulpa": status, "managed": managed}

    return _guard(read)


@router.post("/api/mcp-mode/tulpa/start")
def api_tulpa_start():
    return _guard(tulpa_start)


@router.post("/api/mcp-mode/tulpa/stop")
def api_tulpa_stop():
    return _guard(tulpa_stop)


@router.post("/api/mcp-mode/tulpa/enable")
def api_tulpa_enable():
    return _guard(tulpa_enable_mcp)


@router.post("/api/mcp-mode/tulpa/root")
def api_tulpa_root(payload: dict = Body(...)):
    return _guard(set_tulpa_root, str(payload.get("path") or ""))


@router.get("/api/mcp-mode/groups")
def api_groups():
    def read():
        state = load_state()
        if state.get("backend") == "source" and (state.get("source") or {}).get("pid"):
            return {"items": source_groups()}
        return {"items": tulpa_live_groups()}

    return _guard(read)


@router.get("/api/mcp-mode/friends")
def api_friends():
    return _guard(lambda: {"items": tulpa_live_friends()})


@router.get("/api/mcp-mode/personas")
def api_personas():
    return _guard(lambda: {"items": tulpa_personas()})


@router.post("/api/mcp-mode/connection")
def api_connection(payload: dict = Body(...)):
    return _guard(create_connection, payload)


@router.delete("/api/mcp-mode/connection")
def api_connection_delete():
    return _guard(revoke_connection)


@router.post("/api/mcp-mode/connection/test")
def api_connection_test():
    return _guard(test_connection)


@router.get("/api/mcp-mode/chats")
def api_chats():
    return _guard(chat_sessions)


@router.post("/api/mcp-mode/chats/start")
def api_chat_start():
    return _guard(start_chat)


@router.post("/api/mcp-mode/chats/{session_id}/stop")
def api_chat_stop(session_id: str):
    return _guard(stop_chat, session_id)


@router.get("/api/mcp-mode/agents")
def api_agents():
    return _guard(agents_status)


@router.post("/api/mcp-mode/agents/{agent}/install")
def api_agent_install(agent: str):
    return _guard(install_agent, agent)


@router.post("/api/mcp-mode/agents/{agent}/test")
def api_agent_test(agent: str):
    return _guard(test_agent, agent)


@router.post("/api/mcp-mode/agents/dsh/install-runtime")
def api_dsh_install_runtime():
    return _guard(start_dsh_install)


@router.get("/api/mcp-mode/agents/dsh/install-status")
def api_dsh_install_status():
    return _guard(dsh_install_status)


@router.post("/api/mcp-mode/backend")
def api_backend(payload: dict = Body(...)):
    return _guard(set_backend, str(payload.get("backend") or ""))


@router.get("/api/mcp-mode/snowluma")
def api_snowluma():
    def read():
        managed = {}
        try:
            managed = tulpa_sl_status()
        except McpModeError as exc:
            managed = {"error": exc.message}
        return {"managed": managed, "source": source_status()}

    return _guard(read)


@router.post("/api/mcp-mode/snowluma/managed/configure")
def api_managed_configure():
    return _guard(tulpa_sl_configure)


@router.post("/api/mcp-mode/snowluma/managed/select")
def api_managed_select(payload: dict = Body(...)):
    return _guard(tulpa_sl_select, str(payload.get("choice_id") or ""))


@router.post("/api/mcp-mode/snowluma/managed/test")
def api_managed_test():
    return _guard(tulpa_sl_test)


@router.post("/api/mcp-mode/snowluma/managed/cancel")
def api_managed_cancel():
    return _guard(tulpa_sl_cancel)


@router.post("/api/mcp-mode/snowluma/source/build")
def api_source_build():
    return _guard(start_source_build)


@router.post("/api/mcp-mode/snowluma/source/start")
def api_source_start():
    return _guard(start_source)


@router.post("/api/mcp-mode/snowluma/source/stop")
def api_source_stop():
    return _guard(stop_source)


@router.post("/api/mcp-mode/snowluma/source/reveal")
def api_source_reveal():
    return _guard(source_webui_secret)


@router.get("/api/mcp-mode/snowluma/source/webui")
def api_source_webui():
    return _guard(source_webui_overview)


@router.get("/api/mcp-mode/snowluma/source/processes")
def api_source_processes():
    return _guard(lambda: {"items": source_processes()})


@router.post("/api/mcp-mode/snowluma/source/select")
def api_source_select(payload: dict = Body(...)):
    return _guard(source_select_process, int(payload.get("pid") or 0))


@router.post("/api/mcp-mode/snowluma/source/connect")
def api_source_connect(payload: dict = Body(default={})):
    return _guard(connect_source_to_tulpa, bool((payload or {}).get("force")))


@router.get("/api/mcp-mode/raw")
def api_raw():
    return _guard(raw_status)


@router.post("/api/mcp-mode/raw")
def api_raw_save(payload: dict = Body(...)):
    return _guard(
        save_raw,
        bool(payload.get("enabled")),
        bool(payload.get("write")),
    )


@router.get("/api/mcp-mode/logs")
def api_logs(lines: int = 120):
    return _guard(logs, lines)
