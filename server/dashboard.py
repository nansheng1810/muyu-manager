"""AstrBot Dashboard API 客户端（带令牌缓存）。"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request


class DashboardError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


_tokens: dict[str, str] = {}
_lock = threading.Lock()


def _cache_key(inst: dict) -> str:
    return f"{inst.get('dash_port')}:{inst.get('dash_user')}"


def _base(inst: dict) -> str:
    return f"http://127.0.0.1:{int(inst.get('dash_port') or 0)}"


def _extract_error(raw: str) -> str:
    try:
        data = json.loads(raw)
    except Exception:
        return raw.strip()[:300]
    if isinstance(data, dict):
        for key in ("message", "detail", "msg", "error"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("message"), str):
            return inner["message"]
    return ""


def _raw_request(
    inst: dict,
    method: str,
    path: str,
    payload=None,
    query: dict | None = None,
    token: str | None = None,
    timeout: float = 60.0,
) -> dict:
    url = _base(inst) + "/api/v1/" + path.lstrip("/")
    if query:
        clean = {k: v for k, v in query.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean, doseq=True)
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method.upper())
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise DashboardError(_extract_error(raw) or f"HTTP {exc.code}", exc.code) from exc
    except Exception as exc:  # noqa: BLE001
        raise DashboardError(
            f"无法连接 Dashboard（{_base(inst)}）：{exc}", 503
        ) from exc
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {"data": raw}


def login(inst: dict, force: bool = False) -> str:
    key = _cache_key(inst)
    with _lock:
        if not force and key in _tokens:
            return _tokens[key]
    user = inst.get("dash_user") or "astrbot"
    password = inst.get("dash_pass") or ""
    if not password:
        raise DashboardError("尚未配置该机器人的 Dashboard 密码", 401)
    result = _raw_request(
        inst,
        "POST",
        "auth/login",
        {"username": user, "password": password},
        timeout=20,
    )
    data = result.get("data") if isinstance(result, dict) else None
    token = ""
    if isinstance(data, dict):
        token = str(data.get("token") or "")
    if not token:
        message = _extract_error(json.dumps(result, ensure_ascii=False)) or "登录失败"
        raise DashboardError(f"Dashboard 登录失败：{message}", 401)
    with _lock:
        _tokens[key] = token
    return token


def call(
    inst: dict,
    method: str,
    path: str,
    payload=None,
    query: dict | None = None,
    timeout: float = 60.0,
    auth: bool = True,
) -> dict:
    token = login(inst) if auth else None
    try:
        return _raw_request(inst, method, path, payload, query, token, timeout)
    except DashboardError as exc:
        if auth and exc.status == 401:
            token = login(inst, force=True)
            return _raw_request(inst, method, path, payload, query, token, timeout)
        raise


def upload_raw(
    inst: dict,
    path: str,
    body: bytes,
    content_type: str,
    timeout: float = 600.0,
) -> dict:
    """原样转发 multipart 请求体（用于插件 zip 上传）。"""
    url = _base(inst) + "/api/v1/" + path.lstrip("/")

    def _send(token: str) -> dict:
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", content_type)
        request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise DashboardError(
                _extract_error(raw) or f"HTTP {exc.code}", exc.code
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise DashboardError(
                f"无法连接 Dashboard（{_base(inst)}）：{exc}", 503
            ) from exc
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {"data": raw}

    token = login(inst)
    try:
        return _send(token)
    except DashboardError as exc:
        if exc.status == 401:
            return _send(login(inst, force=True))
        raise


def ping(inst: dict) -> dict:
    """快速探活：登录并取插件数量。"""
    plugins = call(inst, "GET", "plugins", timeout=15)
    return {"ok": True, "plugins": len(plugins.get("data") or [])}
