"""异地备份：把本地备份 zip 上传到 WebDAV，并按保留数清理远端。"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from . import backup, fleet_store, store

TICK_SECONDS = 300
DAV_NS = "{DAV:}"


class OffsiteError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = str(message)
        self.status = int(status)


def _settings() -> dict:
    return store.load_settings()


def _base_url(config: dict | None = None) -> str:
    config = config or _settings()
    url = str(config.get("offsite_url") or "").strip().rstrip("/")
    if not url:
        raise OffsiteError("请先填写 WebDAV 地址")
    if not url.startswith(("http://", "https://")):
        raise OffsiteError("WebDAV 地址必须以 http:// 或 https:// 开头")
    return url


def _dir_url(config: dict | None = None) -> str:
    config = config or _settings()
    base = _base_url(config)
    folder = str(config.get("offsite_dir") or "").strip().strip("/")
    if not folder:
        return base
    return base + "/" + urllib.parse.quote(folder, safe="/")


def _auth(config: dict) -> str:
    user = str(config.get("offsite_user") or "")
    password = str(config.get("offsite_password") or "")
    if not user:
        return ""
    raw = f"{user}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _request(method: str, url: str, config: dict, body: bytes | None = None,
             headers: dict | None = None, timeout: float = 60.0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method.upper())
    auth = _auth(config)
    if auth:
        request.add_header("Authorization", auth)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return int(exc.code), raw
    except Exception as exc:  # noqa: BLE001
        raise OffsiteError(f"WebDAV 请求失败：{exc}", 502) from exc


def _ensure_dir(config: dict) -> None:
    status, _ = _request("MKCOL", _dir_url(config), config, timeout=20)
    if status in (200, 201, 204, 405):
        return
    if status in (401, 403):
        raise OffsiteError("WebDAV 认证失败，请检查用户名和密码", 401)
    raise OffsiteError(f"无法创建远程目录（HTTP {status}）", 502)


def _safe_local(path_value: str) -> Path:
    path = Path(str(path_value or "")).resolve()
    base = backup.BACKUP_DIR.resolve()
    if base not in path.parents:
        raise OffsiteError("只能上传管理器备份目录里的文件")
    if path.suffix != ".zip" or not path.is_file():
        raise OffsiteError("备份文件不存在")
    return path


def _record(backup_name: str, digest: str, remote_path: str, size: int,
            status: str = "ok", error: str = "") -> None:
    with fleet_store.session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO offsite_uploads(id, backup_name, sha256, remote_path, bytes, status, error, created) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (f"of_{uuid.uuid4().hex[:12]}", backup_name, digest, remote_path, size,
             status, error[:400], time.time()),
        )


def upload(path_value: str, prune: bool = True) -> dict:
    config = _settings()
    path = _safe_local(path_value)
    base = backup.BACKUP_DIR
    sha_file = path.with_suffix(path.suffix + ".sha256")
    digest = ""
    if sha_file.exists():
        digest = sha_file.read_text(encoding="utf-8").split()[0]
    _ensure_dir(config)
    target = _dir_url(config) + "/" + urllib.parse.quote(path.name, safe="")
    data = path.read_bytes()
    status, raw = _request(
        "PUT", target, config, data,
        {"Content-Type": "application/zip", "Content-Length": str(len(data))},
        timeout=max(60.0, len(data) / (1024 * 1024) * 3),
    )
    if status not in (200, 201, 204):
        message = raw.decode("utf-8", "replace").strip()[:200]
        _record(path.name, digest, target, len(data), "error", f"HTTP {status} {message}")
        raise OffsiteError(f"上传失败（HTTP {status}）{message}", 502)
    _record(path.name, digest, target, len(data), "ok")
    pruned = 0
    if prune:
        try:
            pruned = prune_remote()
        except OffsiteError:
            pruned = 0
    return {"name": path.name, "bytes": len(data), "remote": target,
            "sha256": digest, "pruned": pruned}


def _parse_propfind(raw: bytes) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    items = []
    for response in root.findall(f"{DAV_NS}response"):
        href = response.findtext(f"{DAV_NS}href") or ""
        name = urllib.parse.unquote(href.rstrip("/").rsplit("/", 1)[-1])
        if not name.lower().endswith(".zip"):
            continue
        size = 0
        modified = ""
        for prop in response.findall(f"{DAV_NS}propstat"):
            size_text = prop.findtext(f"{DAV_NS}prop/{DAV_NS}getcontentlength")
            if size_text:
                try:
                    size = int(size_text)
                except ValueError:
                    size = 0
            modified = prop.findtext(f"{DAV_NS}prop/{DAV_NS}getlastmodified") or modified
        items.append({"name": name, "bytes": size, "modified": modified, "href": href})
    return items


def list_remote() -> list[dict]:
    config = _settings()
    _ensure_dir(config)
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:propfind xmlns:d="DAV:"><d:prop>'
        "<d:getcontentlength/><d:getlastmodified/><d:resourcetype/>"
        "</d:prop></d:propfind>"
    ).encode("utf-8")
    status, raw = _request(
        "PROPFIND", _dir_url(config) + "/", config, body,
        {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
        timeout=30,
    )
    if status == 401:
        raise OffsiteError("WebDAV 认证失败", 401)
    if status not in (200, 207):
        raise OffsiteError(f"读取远程目录失败（HTTP {status}）", 502)
    items = _parse_propfind(raw)
    items.sort(key=lambda item: item.get("modified") or "", reverse=True)
    return items


def prune_remote() -> int:
    config = _settings()
    keep = max(0, int(config.get("offsite_keep") or 0))
    if keep <= 0:
        return 0
    items = list_remote()
    removed = 0
    for item in items[keep:]:
        delete_remote(item["name"])
        removed += 1
    return removed


def delete_remote(name: str) -> dict:
    config = _settings()
    safe = Path(str(name or "")).name
    if not safe.lower().endswith(".zip"):
        raise OffsiteError("只能删除远程 zip 备份")
    target = _dir_url(config) + "/" + urllib.parse.quote(safe, safe="")
    status, _ = _request("DELETE", target, config, timeout=30)
    if status not in (200, 204, 404):
        raise OffsiteError(f"删除远程备份失败（HTTP {status}）", 502)
    with fleet_store.session() as conn:
        conn.execute("DELETE FROM offsite_uploads WHERE backup_name=?", (safe,))
    return {"deleted": safe}


def test_connection() -> dict:
    config = _settings()
    _ensure_dir(config)
    status, _ = _request(
        "PROPFIND", _dir_url(config) + "/", config,
        b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>',
        {"Depth": "0", "Content-Type": "application/xml"},
        timeout=20,
    )
    if status == 401:
        raise OffsiteError("WebDAV 认证失败，请检查用户名和密码", 401)
    if status not in (200, 207, 405):
        raise OffsiteError(f"连接失败（HTTP {status}）", 502)
    return {"ok": True, "url": _dir_url(config), "status": status}


def status() -> dict:
    config = _settings()
    records = []
    with fleet_store.session() as conn:
        rows = conn.execute(
            "SELECT backup_name, sha256, remote_path, bytes, status, error, created "
            "FROM offsite_uploads ORDER BY created DESC LIMIT 20"
        ).fetchall()
        records = [dict(row) for row in rows]
    password = str(config.get("offsite_password") or "")
    return {
        "enabled": bool(config.get("offsite_enabled")),
        "url": str(config.get("offsite_url") or ""),
        "user": str(config.get("offsite_user") or ""),
        "has_password": bool(password),
        "password_masked": ("••••" if password else ""),
        "dir": str(config.get("offsite_dir") or ""),
        "keep": int(config.get("offsite_keep") or 0),
        "local": backup.list_backups()[:20],
        "uploads": records,
        "tick_seconds": TICK_SECONDS,
    }


def auto_upload_latest() -> dict | None:
    config = _settings()
    if not config.get("offsite_enabled") or not config.get("offsite_url"):
        return None
    backups = backup.list_backups()
    if not backups:
        return None
    latest = backups[0]
    with fleet_store.session() as conn:
        row = conn.execute(
            "SELECT 1 FROM offsite_uploads WHERE backup_name=? AND status='ok'",
            (latest["name"],),
        ).fetchone()
    if row:
        return None
    return upload(latest["path"])


class _Worker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run = 0.0
        self.last_result = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="offsite-backup")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(20):
            try:
                result = auto_upload_latest()
                self.last_run = time.time()
                self.last_result = (result or {}).get("name", "无需上传")
            except Exception as exc:  # noqa: BLE001
                self.last_run = time.time()
                self.last_result = f"上传失败：{exc}"
            self._stop.wait(TICK_SECONDS)


worker = _Worker()
