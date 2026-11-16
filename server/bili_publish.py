"""牧鱼 · B站发布（bili-cli）管理页 API。"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query, Request

from . import bili_cli, store

router = APIRouter()
PLUGIN_ID = "astrbot_plugin_bilibili_ai_bot"
UPLOAD_DIR = store.DATA_DIR / "bili_publish_uploads"
MAX_UPLOAD = 2 * 1024 * 1024 * 1024
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".flv", ".avi", ".webm", ".m4v"}

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _ok(data: Any = None, message: str = "") -> dict[str, Any]:
    return {"status": "ok", "message": message, "data": data}


def _fail(message: str, code: int = 400) -> dict[str, Any]:
    return {"status": "error", "message": message, "data": None, "code": code}


def _instance(inst_id: str) -> dict[str, Any]:
    for item in store.load_instances():
        if str(item.get("id")) == str(inst_id):
            return item
    raise ValueError(f"机器人不存在：{inst_id}")


def _plugin_data(inst: dict[str, Any]) -> Path:
    return Path(str(inst.get("root") or "")) / "data" / "plugin_data" / PLUGIN_ID


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _safe_name(value: str, fallback: str = "video.mp4") -> str:
    name = Path(str(value or "")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        stem = Path(name).stem or "video"
        return f"{stem[:76]}.mp4"
    return name[:80] or fallback


def _status_payload() -> dict[str, Any]:
    try:
        exe = bili_cli.resolve_executable()
    except bili_cli.BiliCliError as exc:
        return {
            "installed": False,
            "error": exc.message,
            "hint": exc.hint,
            "exe": "",
            "version": "",
            "logged_in": False,
        }
    payload: dict[str, Any] = {
        "installed": True,
        "exe": exe,
        "version": "",
        "logged_in": False,
        "error": "",
        "hint": "",
    }
    try:
        payload["version"] = bili_cli.version()
    except bili_cli.BiliCliError:
        pass
    try:
        data = bili_cli.status()
        payload["logged_in"] = bool(data.get("logged_in"))
        payload["user"] = data.get("user") or {}
        code = str(data.get("code") or "")
        payload["pending"] = code == "login_pending" or data.get("status") == "pending"
        payload["pending_detail"] = data.get("detail") or {}
        if code not in {"not_logged_in", "login_pending", ""}:
            payload["error"] = str(data.get("message") or "")
            payload["hint"] = str(data.get("hint") or "")
    except bili_cli.BiliCliError as exc:
        payload["error"] = exc.message
        payload["hint"] = exc.hint
    return payload


@router.get("/api/instances/{inst_id}/bili-publish/status")
def bili_publish_status(inst_id: str):
    try:
        _instance(inst_id)
    except ValueError as exc:
        return _fail(str(exc), 404)
    return _ok(_status_payload())


@router.post("/api/instances/{inst_id}/bili-publish/login")
def bili_publish_login(inst_id: str):
    try:
        _instance(inst_id)
        data = bili_cli.login()
    except ValueError as exc:
        return _fail(str(exc), 404)
    except bili_cli.BiliCliError as exc:
        return _fail(f"{exc.message} {exc.hint}".strip(), 502)
    return _ok(data)


@router.get("/api/instances/{inst_id}/bili-publish/login/status")
def bili_publish_login_status(inst_id: str):
    try:
        _instance(inst_id)
        data = bili_cli.status()
    except ValueError as exc:
        return _fail(str(exc), 404)
    except bili_cli.BiliCliError as exc:
        return _fail(f"{exc.message} {exc.hint}".strip(), 502)
    return _ok(data)


@router.get("/api/instances/{inst_id}/bili-publish/history")
def bili_publish_history(inst_id: str, limit: int = Query(30)):
    try:
        inst = _instance(inst_id)
    except ValueError as exc:
        return _fail(str(exc), 404)
    base = _plugin_data(inst)
    items: list[dict[str, Any]] = []
    for filename, source in (
        ("video_publish_log.json", "自动发布"),
        ("creative_publish_log.json", "旧创作"),
    ):
        rows = _load_json(base / filename, [])
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                items.append({
                    "time": str(row.get("time") or row.get("published_at") or ""),
                    "title": str(row.get("title") or ""),
                    "bvid": str(row.get("bvid") or ""),
                    "aid": str(row.get("aid") or ""),
                    "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
                    "source": source,
                })
    items.sort(key=lambda item: item["time"], reverse=True)
    pending = _load_json(base / "creative_pending.json", {})
    pending_info = {}
    if isinstance(pending, dict) and pending:
        video = Path(str(pending.get("video_path") or ""))
        pending_info = {
            "title": str(pending.get("title") or ""),
            "video_path": str(video),
            "exists": video.is_file(),
            "publish_error": str(pending.get("publish_error") or ""),
        }
    return _ok({
        "items": items[:max(1, min(int(limit or 30), 100))],
        "total": len(items),
        "legacy_pending": pending_info,
    })


@router.post("/api/instances/{inst_id}/bili-publish/files")
async def bili_publish_file(inst_id: str, request: Request,
                            filename: str = Query("")):
    try:
        _instance(inst_id)
    except ValueError as exc:
        return _fail(str(exc), 404)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    name = _safe_name(filename or request.headers.get("x-filename", ""))
    target = UPLOAD_DIR / f"{token}_{name}"
    total = 0
    try:
        with target.open("wb") as fh:
            async for chunk in request.stream():
                total += len(chunk)
                if total > MAX_UPLOAD:
                    fh.close()
                    target.unlink(missing_ok=True)
                    return _fail("视频超过 2GB 上限", 413)
                fh.write(chunk)
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        return _fail(f"保存视频失败：{exc}", 500)
    if not total:
        target.unlink(missing_ok=True)
        return _fail("没有收到视频文件")
    return _ok({"file_id": target.name, "name": name, "size": total})


def _start_job(inst_id: str, video: Path, title: str, tags: list[str],
               desc: str, tid: int | None) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "instance_id": inst_id,
        "status": "queued",
        "title": title,
        "video": video.name,
        "started": time.time(),
        "finished": 0.0,
        "message": "排队中",
        "bvid": "",
        "error": "",
    }
    with _jobs_lock:
        _jobs[job_id] = job

    def run() -> None:
        job.update(status="running", message="bili-cli 正在上传")
        try:
            result = bili_cli.upload(video, title, desc, tags, tid)
        except bili_cli.BiliCliError as exc:
            job.update(
                status="error",
                error=f"{exc.code}: {exc.message}",
                message=exc.hint or exc.message,
                finished=time.time(),
            )
            return
        except Exception as exc:  # noqa: BLE001
            job.update(status="error", error=str(exc), message=str(exc),
                       finished=time.time())
            return
        job.update(
            status="success",
            bvid=str(result.get("bvid") or ""),
            message=f"投稿成功：{result.get('bvid') or ''}",
            finished=time.time(),
        )

    threading.Thread(target=run, daemon=True, name=f"bili-publish-{job_id}").start()
    return job


@router.post("/api/instances/{inst_id}/bili-publish/publish")
def bili_publish_start(inst_id: str, payload: dict = Body(...)):
    try:
        _instance(inst_id)
    except ValueError as exc:
        return _fail(str(exc), 404)
    file_id = Path(str(payload.get("file_id") or "")).name
    video = UPLOAD_DIR / file_id
    if not file_id or not video.is_file():
        return _fail("上传文件不存在，请重新选择视频")
    title = str(payload.get("title") or "").strip()
    if not title:
        return _fail("请填写标题")
    tags = payload.get("tags")
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",")]
    tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()][:10]
    if not tags:
        return _fail("请至少填写一个标签")
    try:
        tid = int(payload.get("tid")) if payload.get("tid") not in (None, "") else None
    except (TypeError, ValueError):
        return _fail("分区必须是数字")
    job = _start_job(
        inst_id, video, title, tags,
        str(payload.get("desc") or ""), tid,
    )
    return _ok(job, "已开始上传")


@router.get("/api/instances/{inst_id}/bili-publish/jobs/{job_id}")
def bili_publish_job(inst_id: str, job_id: str):
    with _jobs_lock:
        job = dict(_jobs.get(job_id) or {})
    if not job or job.get("instance_id") != inst_id:
        return _fail("任务不存在", 404)
    return _ok(job)
