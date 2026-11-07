"""NapCat WebUI 客户端：读取配置、登录取凭据、获取 QQ 扫码二维码。

NapCat 的 WebUI（默认 6099/6100）在未登录时会持续生成 QQ 登录二维码。
管理台直接调用这些接口，把二维码搬进页面里，不再依赖弹出的 QQ 登录窗口。
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .runner import port_open

TIMEOUT = 6.0
# 腾讯二维码有效期约两分钟，管理器在到期前主动换一张，避免用户扫到失效码。
QRCODE_REFRESH_SECONDS = 110.0
MAX_IMAGE_BYTES = 4_000_000

_credentials: dict[str, str] = {}
_qrcode_files: dict[str, Path] = {}
_last_refresh: dict[str, float] = {}


class NapCatError(Exception):
    pass


def token_hash(token: str) -> str:
    """NapCat WebUI 的登录口令：sha256(token + ".napcat")。"""
    return hashlib.sha256((str(token) + ".napcat").encode("utf-8")).hexdigest()


def find_webui_config(napcat_dir: Path) -> Path | None:
    """在 NapCat 目录里找 webui.json，优先当前运行版本（mtime 最新）。"""
    root = Path(napcat_dir or "")
    if not root.is_dir():
        return None
    direct = root / "config" / "webui.json"
    if direct.is_file():
        return direct
    hits: list[tuple[float, Path]] = []
    try:
        for path in root.rglob("webui.json"):
            try:
                hits.append((path.stat().st_mtime, path))
            except OSError:
                continue
    except OSError:
        return None
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


def webui_config(napcat_dir: Path) -> dict:
    """读取 WebUI 端口与 token；缺失或损坏时返回空字典。"""
    path = find_webui_config(napcat_dir)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    try:
        port = int(data.get("port") or 6099)
    except (TypeError, ValueError):
        port = 6099
    return {"port": port, "token": str(data.get("token") or ""), "path": str(path)}


def _post(port: int, path: str, payload: dict | None = None, credential: str = "") -> dict:
    url = f"http://127.0.0.1:{int(port)}/api{path}"
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if credential:
        req.add_header("Authorization", f"Bearer {credential}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise NapCatError(f"NapCat WebUI 返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise NapCatError(f"无法连接 NapCat WebUI：{exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise NapCatError("NapCat WebUI 返回了无效数据") from exc
    if not isinstance(data, dict):
        raise NapCatError("NapCat WebUI 返回格式异常")
    if data.get("code") not in (0, None):
        raise NapCatError(str(data.get("message") or "NapCat WebUI 调用失败"))
    return data


def _login(port: int, token: str) -> str:
    if not token:
        raise NapCatError("NapCat WebUI 未设置 token，无法读取二维码")
    data = _post(port, "/auth/login", {"hash": token_hash(token)})
    payload = data.get("data") or {}
    credential = payload.get("Credential") or payload.get("credential")
    if not credential:
        raise NapCatError("NapCat WebUI 登录失败（token 可能已变更）")
    return str(credential)


def _call(port: int, token: str, path: str, payload: dict | None = None) -> dict:
    """带凭据调用 WebUI；凭据失效时自动重新登录一次。"""
    key = f"{port}:{token_hash(token)[:16]}"
    credential = _credentials.get(key)
    if not credential:
        credential = _login(port, token)
        _credentials[key] = credential
    try:
        return _post(port, path, payload or {}, credential)
    except NapCatError:
        _credentials.pop(key, None)
        credential = _login(port, token)
        _credentials[key] = credential
        return _post(port, path, payload or {}, credential)


def _local_qrcode_image(napcat_dir: Path) -> str:
    """读取 NapCat 保存的二维码图片并转成 data URI（链接本身是网页，不能直接显示）。"""
    key = str(napcat_dir)
    cached = _qrcode_files.get(key)
    path = cached if cached and cached.is_file() else None
    if path is None:
        if not napcat_dir.is_dir():
            return ""
        patterns = (
            "NapCat.*/versions/*/resources/app/napcat/cache/qrcode.png",
            "*/versions/*/resources/app/napcat/cache/qrcode.png",
            "*/resources/app/napcat/cache/qrcode.png",
        )
        hits: list[Path] = []
        for pattern in patterns:
            hits.extend(napcat_dir.glob(pattern))
        if not hits:
            return ""
        path = max(hits, key=lambda item: item.stat().st_mtime)
        _qrcode_files[key] = path
    try:
        content = path.read_bytes()
    except OSError:
        _qrcode_files.pop(key, None)
        return ""
    if not content or len(content) > MAX_IMAGE_BYTES:
        return ""
    return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


def _qrcode_image(url: str) -> str:
    """把二维码链接转成 data URI，避免 QQ 图片链接的跨域限制。"""
    if not url.startswith(("http://", "https://")):
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content = resp.read()
            ctype = (resp.headers.get("Content-Type") or "image/png").split(";")[0]
    except (urllib.error.URLError, OSError):
        return url
    if not content or len(content) > MAX_IMAGE_BYTES:
        return url
    if not ctype.startswith("image/"):
        return ""
    return f"data:{ctype};base64," + base64.b64encode(content).decode("ascii")


def login_state(inst: dict, force_refresh: bool = False) -> dict:
    """返回实例的 NapCat 登录状态与可展示的二维码。

    输出字段：running / logged_in / qrcode / phase / message / refresh_in。
    """
    napcat_dir = Path(inst.get("napcat_dir") or "")
    config = webui_config(napcat_dir)
    if not config:
        return {
            "running": False,
            "logged_in": False,
            "qrcode": "",
            "message": "未找到 NapCat WebUI 配置（config/webui.json）",
        }
    port = config["port"]
    if not port_open(port):
        return {
            "running": False,
            "logged_in": False,
            "port": port,
            "qrcode": "",
            "message": "NapCat 未运行，点击“启动并扫码”",
        }

    status = _call(port, config["token"], "/QQLogin/CheckLoginStatus")
    data = status.get("data") or {}
    logged_in = bool(data.get("isLogin") or data.get("coreReady"))
    phase = str(data.get("loginPhase") or "")
    if logged_in:
        return {
            "running": True,
            "logged_in": True,
            "port": port,
            "phase": phase,
            "qrcode": "",
            "qq": str(inst.get("qq") or ""),
            "message": "QQ 已登录，无需扫码",
        }

    key = f"{inst.get('id')}:{port}"
    now = time.time()
    last = _last_refresh.get(key, 0.0)
    qr_url = str(data.get("qrcodeurl") or "")
    refreshed = False
    if force_refresh or not qr_url or now - last >= QRCODE_REFRESH_SECONDS:
        try:
            fresh = _call(port, config["token"], "/QQLogin/RefreshQRcode").get("data") or {}
            qr_url = str(fresh.get("qrcodeurl") or fresh.get("qrcode") or qr_url)
            if qr_url:
                _last_refresh[key] = now
                refreshed = True
        except NapCatError:
            pass
    if not qr_url:
        try:
            fallback = _call(port, config["token"], "/QQLogin/GetQQLoginQrcode").get("data") or {}
            qr_url = str(fallback.get("qrcode") or "")
            if qr_url:
                _last_refresh.setdefault(key, now)
        except NapCatError:
            pass

    message = "请使用手机 QQ 扫码登录"
    if phase == "qrcode_scanned":
        message = "已扫码，请在手机上确认登录"
    elif phase == "initializing":
        message = "已确认，正在初始化 NapCat"
    elif phase == "generating_qrcode":
        message = "正在生成二维码…"
    elif data.get("loginError"):
        message = str(data.get("loginError"))

    since = now - _last_refresh.get(key, now)
    return {
        "running": True,
        "logged_in": False,
        "port": port,
        "phase": phase,
        "qrcode": (_local_qrcode_image(napcat_dir) or _qrcode_image(qr_url)) if qr_url else "",
        "message": message,
        "refreshed": refreshed,
        "refresh_in": max(0, int(QRCODE_REFRESH_SECONDS - since)),
    }
