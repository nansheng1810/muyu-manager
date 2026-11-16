"""bili-cli 本机适配器：状态、登录、上传。"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

CREATE_NO_WINDOW = 0x08000000


class BiliCliError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str = "",
                 detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = str(code or "unknown")
        self.message = str(message or "")
        self.hint = str(hint or "")
        self.detail = detail or {}


def resolve_executable() -> str:
    candidates = [
        shutil.which("bili"),
        shutil.which("bili.exe"),
        str(Path.home() / ".local" / "bin" / "bili.exe"),
        str(Path.home() / ".local" / "bin" / "bili"),
    ]
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        tools = Path(local_appdata) / "uv" / "tools"
        candidates.extend([
            str(tools / "bili-agent" / "Scripts" / "bili.exe"),
            str(tools / "bili-agent" / "bin" / "bili"),
        ])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise BiliCliError(
        "not_installed",
        "未找到 bili 命令",
        "先运行 uv tool install bili-agent，再刷新本页。",
    )


def _parse(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise BiliCliError("invalid_output", "bili-cli 没有返回内容")
    try:
        doc = json.loads(raw)
    except ValueError:
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                doc = json.loads(line)
                break
            except ValueError:
                continue
        else:
            raise BiliCliError("invalid_output", f"bili-cli 返回非 JSON：{raw[:200]}")
    if not isinstance(doc, dict):
        raise BiliCliError("invalid_output", "bili-cli 返回结构不是对象")
    return doc


def _decode(doc: dict[str, Any]) -> dict[str, Any]:
    if doc.get("ok"):
        data = doc.get("data")
        return data if isinstance(data, dict) else {}
    error = doc.get("error") if isinstance(doc.get("error"), dict) else {}
    raise BiliCliError(
        str(error.get("code") or "unknown"),
        str(error.get("message") or "bili-cli 返回错误"),
        str(error.get("hint") or ""),
        error.get("detail") if isinstance(error.get("detail"), dict) else {},
    )


def _sanitize_proxy_env(env: dict[str, str]) -> None:
    """curl_cffi 会把 NO_PROXY 里的 [::1] 误解析成端口，去掉 IPv6 括号项。"""
    for key in ("NO_PROXY", "no_proxy"):
        value = env.get(key)
        if not value:
            continue
        parts = [
            part.strip()
            for part in value.split(",")
            if part.strip() and "[" not in part and "]" not in part
        ]
        env[key] = ",".join(parts) or "localhost,127.0.0.1"


def _run(args: list[str], timeout: float = 60) -> dict[str, Any]:
    exe = resolve_executable()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    _sanitize_proxy_env(env)
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            timeout=timeout,
            env=env,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise BiliCliError(
            "timeout", f"bili 命令超过 {int(timeout)} 秒未完成",
            "稍后重试；大视频上传可稍后再试。",
        ) from exc
    text = proc.stdout.decode("utf-8", "replace").strip()
    err = proc.stderr.decode("utf-8", "replace").strip()
    try:
        return _decode(_parse(text))
    except BiliCliError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BiliCliError("invalid_output", f"解析 bili 输出失败：{exc}", err[:300]) from exc


def status() -> dict[str, Any]:
    try:
        return _run(["auth", "status", "--compact"], 30)
    except BiliCliError as exc:
        if exc.code in {"not_logged_in", "auth_expired", "login_pending"}:
            return {
                "logged_in": False,
                "code": exc.code,
                "message": exc.message,
                "hint": exc.hint,
                "detail": exc.detail,
            }
        raise


def version() -> str:
    return str(_run(["--version", "--compact"], 20).get("version") or "")


def login() -> dict[str, Any]:
    data = _run(["auth", "login", "--compact"], 30)
    qr_path = str(data.get("qr_image") or "")
    data["qr_data_url"] = ""
    if qr_path and Path(qr_path).is_file():
        try:
            raw = Path(qr_path).read_bytes()
            data["qr_data_url"] = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        except OSError:
            pass
    return data


def upload(video: Path, title: str, desc: str, tags: list[str],
           tid: int | None = None, cover: Path | None = None,
           timeout: float = 1800) -> dict[str, Any]:
    video = Path(video)
    if not video.is_file():
        raise BiliCliError("invalid_argument", f"视频文件不存在：{video}")
    args = [
        "upload", "video", str(video),
        "--title", str(title)[:80],
        "--desc", str(desc or ""),
        "--ai-declare", "--compact",
    ]
    for tag in (tags or ["B站"]):
        args.extend(["--tag", str(tag)[:20]])
    if tid:
        args.extend(["--tid", str(int(tid))])
    if cover and Path(cover).is_file():
        args.extend(["--cover", str(cover)])
    return _run(args, timeout)
