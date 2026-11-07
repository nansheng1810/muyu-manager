"""HTTP 接口层。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import (
    alerts as alerts_mod,
    approvals,
    automation as automation_mod,
    backup as backup_mod,
    bili,
    canary as canary_mod,
    consoles,
    creator,
    dashboard,
    deploy as deploy_mod,
    digest as digest_mod,
    drift as drift_mod,
    dsh as dsh_mod,
    duet as duet_mod,
    eval as eval_mod,
    fleet_store,
    health as health_mod,
    human_mode as human_mode_mod,
    human_settings,
    inbox as inbox_mod,
    insight as insight_mod,
    learn,
    learn_auto,
    life as life_mod,
    live_think,
    llm,
    market,
    matrix as matrix_mod,
    memes as memes_mod,
    memory,
    memory_audit,
    mood as mood_mod,
    napcat as napcat_mod,
    notify as notify_mod,
    persona as persona_mod,
    presence as presence_mod,
    provisioner as provisioner_mod,
    resources as resources_mod,
    rhythm as rhythm_mod,
    runner as runner_mod,
    store,
    styles,
    tasks as tasks_mod,
    vision as vision_mod,
    watchdog as watchdog_mod,
)
from .store import (
    BASE_DIR,
    WEB_DIR,
    load_instances,
    load_settings,
    public_instance,
    save_instances,
    save_settings,
    seed_instances,
)

app = FastAPI(title="牧鱼", version="1.23.12")
runner = runner_mod.runner
watchdog = watchdog_mod.watchdog
app.include_router(dsh_mod.router)

_INST_LOCK = threading.Lock()


@app.on_event("startup")
def _start_watchdog() -> None:
    if os.environ.get("ASTRBOT_MANAGER_NO_BACKGROUND") == "1":
        return
    watchdog.start()
    learn_auto.auto_learn.start()
    tasks_mod.scheduler.start()
    notify_mod.pusher.start()
    duet_mod.engine.start_auto()
    inbox_mod.start_sync()
    threading.Thread(
        target=dsh_mod.auto_start, daemon=True, name="dsh-autostart"
    ).start()


@app.on_event("shutdown")
def _stop_scheduler() -> None:
    tasks_mod.scheduler.stop()
    notify_mod.pusher.stop()
    duet_mod.engine.shutdown()
    inbox_mod.stop_sync()


# ----------------------------------------------------------------- helpers


def _ok(data=None, message: str = "") -> dict:
    return {"status": "ok", "message": message, "data": data}


def _fail(message: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"status": "error", "message": message, "data": None}, status_code=code)


def _settings() -> dict:
    return load_settings()


def _instances() -> list[dict]:
    return load_instances()


def _require(instances: list[dict], inst_id: str) -> dict:
    for item in instances:
        if item.get("id") == inst_id:
            return item
    raise HTTPException(status_code=404, detail=f"机器人不存在：{inst_id}")


def _decorate(inst: dict) -> dict:
    view = public_instance(inst)
    view["status"] = runner.status(inst)
    view["napcat"] = runner.napcat_status(inst)
    view["napcat"]["watchdog"] = watchdog.snapshot().get(inst["id"]) or {
        "stage": "idle",
        "note": "",
        "relogin_count": 0,
        "offline_seconds": 0,
    }
    return view


def _persist(inst: dict) -> None:
    """回写单个实例的可变字段（pid 等）。"""
    with _INST_LOCK:
        instances = load_instances()
        for idx, item in enumerate(instances):
            if item.get("id") == inst.get("id"):
                instances[idx] = inst
                break
        else:
            instances.append(inst)
        save_instances(instances)


# ------------------------------------------------------------------- meta


@app.get("/api/health")
def health():
    return _ok({"time": time.strftime("%Y-%m-%d %H:%M:%S")})


@app.get("/api/health/fleet")
def fleet_health(force: bool = Query(False)):
    return _ok(health_mod.collect_health(force=force))


@app.get("/api/approvals")
def approvals_list(status: str = Query("pending"), limit: int = Query(100)):
    normalized = None if status in ("", "all") else status
    return _ok(approvals.list_items(status=normalized, limit=limit))


@app.get("/api/approvals/summary")
def approvals_summary():
    return _ok(approvals.summary())


@app.post("/api/approvals")
def approvals_create(payload: dict = Body(...)):
    try:
        item = approvals.create(
            category=payload.get("category", "other"),
            title=payload.get("title", ""),
            target=payload.get("target", ""),
            payload=payload.get("payload") or {},
            requested_by=payload.get("requested_by", "manager"),
            reason=payload.get("reason", ""),
            ttl=payload.get("ttl", approvals.DEFAULT_TTL),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(item)


@app.post("/api/approvals/request-and-wait")
def approvals_request_wait(payload: dict = Body(...)):
    item = approvals.request_and_wait(
        category=payload.get("category", "other"),
        title=payload.get("title", ""),
        target=payload.get("target", ""),
        payload=payload.get("payload") or {},
        requested_by=payload.get("requested_by", "plugin"),
        reason=payload.get("reason", ""),
        timeout=payload.get("timeout", approvals.MAX_WAIT),
        ttl=payload.get("ttl", approvals.DEFAULT_TTL),
    )
    return _ok(item)


@app.post("/api/approvals/{approval_id}/approve")
def approvals_approve(approval_id: str, payload: dict = Body(default={})):
    item = approvals.approve(approval_id, decided_by=payload.get("decided_by", "manager"),
                             result=payload.get("result"))
    if not item:
        raise HTTPException(status_code=404, detail="approval not found")
    if item.get("status") != "approved":
        return _fail(f"审批当前状态为 {item.get('status')}", 409)
    return _ok(item)


@app.post("/api/approvals/{approval_id}/deny")
def approvals_deny(approval_id: str, payload: dict = Body(default={})):
    item = approvals.deny(approval_id, decided_by=payload.get("decided_by", "manager"),
                          reason=payload.get("reason", ""))
    if not item:
        raise HTTPException(status_code=404, detail="approval not found")
    if item.get("status") != "denied":
        return _fail(f"审批当前状态为 {item.get('status')}", 409)
    return _ok(item)


@app.post("/api/approvals/{approval_id}/cancel")
def approvals_cancel(approval_id: str):
    item = approvals.cancel(approval_id)
    if not item:
        raise HTTPException(status_code=404, detail="approval not found")
    return _ok(item)


@app.get("/api/backups")
def backups_list():
    return _ok(backup_mod.list_backups())


@app.post("/api/backups")
def backups_create(payload: dict = Body(default={})):
    try:
        item = backup_mod.create(
            components=payload.get("components"),
            include_login=bool(payload.get("include_login", False)),
            label=payload.get("label", "manual"),
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"备份失败：{exc}", 500)
    return _ok(item)


@app.post("/api/backups/verify")
def backups_verify(payload: dict = Body(...)):
    try:
        return _ok(backup_mod.verify(payload.get("path", "")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/backups/rehearse")
def backups_rehearse(payload: dict = Body(...)):
    try:
        return _ok(backup_mod.rehearse(payload.get("path", "")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        return _fail(f"恢复演练失败：{exc}", 500)


@app.post("/api/backups/restore")
def backups_restore(payload: dict = Body(...)):
    try:
        item = backup_mod.restore(payload.get("path", ""), confirm=payload.get("confirm", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        return _fail(f"恢复失败：{exc}", 500)
    return _ok(item)


@app.get("/api/events")
def events_list(limit: int = Query(100)):
    with fleet_store.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return _ok([dict(row) for row in rows])


@app.get("/api/alerts")
def alerts_get(force: bool = Query(False)):
    return _ok(alerts_mod.collect(force_health=force))


@app.get("/api/drift")
def drift_get():
    return _ok(drift_mod.collect())


@app.get("/api/notify/status")
def notify_status():
    return _ok(notify_mod.status())


@app.post("/api/notify/test")
def notify_test():
    result = notify_mod.test()
    if not result.get("ok"):
        return _fail(result.get("error") or "推送失败", 400)
    return _ok(result, "测试消息已发送")


@app.post("/api/notify/run")
def notify_run():
    return _ok(notify_mod.run(force=True))


@app.post("/api/drift/align")
def drift_align(payload: dict = Body(...)):

    try:
        return _ok(drift_mod.align(
            reference_id=str(payload.get("reference") or ""),
            target_ids=payload.get("targets") or [],
            kinds=payload.get("kinds") or ["plugins", "personas"],
            confirm=str(payload.get("confirm") or ""),
        ))
    except ValueError as exc:
        return _fail(str(exc), 400)


@app.get("/api/matrix")
def matrix_get():
    return _ok(matrix_mod.collect())


@app.get("/api/resources")
def resources_get():
    return _ok(resources_mod.collect())


@app.post("/api/canary/run")
def canary_run():
    try:
        return _ok(canary_mod.run())
    except Exception as exc:  # noqa: BLE001
        return _fail(f"巡检失败：{exc}", 500)


@app.get("/api/canary/last")
def canary_last():
    return _ok(canary_mod.last())


@app.get("/api/digest")
def digest_get(date: str = Query(""), force: bool = Query(False)):
    try:
        data = digest_mod.collect(date or None, force_health=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok({**data, "markdown": digest_mod.markdown(data)})


@app.post("/api/digest/run")
def digest_run(payload: dict = Body(default={})):
    try:
        data = digest_mod.collect(payload.get("date") or None, force_health=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fleet_store.add_event(
        "digest",
        "manager",
        "info",
        f"舰队日报 {data.get('date')}",
        {"overall": data.get("overall"), "counts": data.get("counts")},
    )
    return _ok({**data, "markdown": digest_mod.markdown(data)})


@app.get("/api/evals/fixtures")
def evals_fixtures():
    try:
        return _ok(eval_mod.load_fixtures())
    except eval_mod.EvalError as exc:
        return _fail(str(exc), 400)


@app.get("/api/evals/runs")
def evals_runs(limit: int = Query(50)):
    return _ok(eval_mod.list_runs(limit))


@app.get("/api/evals/trend")
def evals_trend(limit: int = Query(300)):
    return _ok(eval_mod.trend(limit))


@app.post("/api/evals/run")
def evals_run(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("inst_id") or ""))
    try:
        data = eval_mod.run(
            inst,
            provider_id=str(payload.get("provider_id") or ""),
            persona_id=str(payload.get("persona_id") or ""),
            fixture_ids=payload.get("fixture_ids") or [],
            max_tokens=int(payload.get("max_tokens") or 600),
        )
    except eval_mod.EvalError as exc:
        return _fail(str(exc), 400)
    return _ok(data)


@app.get("/api/tasks")
def tasks_list():
    return _ok(tasks_mod.list_tasks())


@app.get("/api/tasks/runs")
def tasks_runs(task_id: str = Query(""), limit: int = Query(100)):
    return _ok(tasks_mod.list_runs(task_id, limit))


@app.post("/api/tasks")
def tasks_create(payload: dict = Body(...)):
    try:
        item = tasks_mod.create(
            name=payload.get("name", ""),
            kind=payload.get("kind", ""),
            schedule=payload.get("schedule", ""),
            config=payload.get("config") or {},
            enabled=bool(payload.get("enabled", False)),
        )
    except tasks_mod.TaskError as exc:
        return _fail(exc.message, exc.status)
    return _ok(item)


@app.put("/api/tasks/{task_id}")
def tasks_update(task_id: str, payload: dict = Body(...)):
    try:
        item = tasks_mod.update(task_id, payload)
    except tasks_mod.TaskError as exc:
        return _fail(exc.message, exc.status)
    return _ok(item)


@app.delete("/api/tasks/{task_id}")
def tasks_delete(task_id: str):
    if not tasks_mod.delete(task_id):
        return _fail("任务不存在", 404)
    return _ok({"deleted": True})


@app.post("/api/tasks/{task_id}/run")
def tasks_run(task_id: str):
    item = tasks_mod._get(task_id)
    if not item:
        return _fail("任务不存在", 404)
    try:
        return _ok(tasks_mod.run_task(item, manual=True))
    except tasks_mod.TaskError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/automation/overview")
def automation_overview():
    try:
        return _ok(automation_mod.overview())
    except Exception as exc:  # noqa: BLE001
        return _fail(f"读取自动化概览失败：{exc}", 500)


@app.get("/api/automation/logs")
def automation_logs(since: int = Query(0), limit: int = Query(80)):
    return _ok(automation_mod.logs(since, limit))


# ------------------------------------------------------------------- duet


@app.get("/api/duet/status")
def duet_status():
    return _ok(duet_mod.engine.status())


@app.get("/api/duet/scenes")
def duet_scenes(limit: int = Query(20, ge=1, le=100)):
    return _ok(duet_mod.engine.scenes(limit))


@app.get("/api/duet/scenes/{scene_id}")
def duet_scene(scene_id: str):
    try:
        return _ok(duet_mod.engine.scene(scene_id))
    except duet_mod.DuetError as exc:
        return _fail(str(exc), 404)


@app.post("/api/duet/start")
def duet_start(payload: dict = Body(default={})):
    try:
        return _ok(duet_mod.engine.start(payload))
    except duet_mod.DuetError as exc:
        return _fail(str(exc), 400)
    except Exception as exc:
        return _fail(f"启动失败：{exc}", 502)


@app.post("/api/duet/{scene_id}/pause")
def duet_pause(scene_id: str):
    try:
        return _ok(duet_mod.engine.pause(scene_id))
    except duet_mod.DuetError as exc:
        return _fail(str(exc), 409)


@app.post("/api/duet/{scene_id}/resume")
def duet_resume(scene_id: str):
    try:
        return _ok(duet_mod.engine.resume(scene_id))
    except duet_mod.DuetError as exc:
        return _fail(str(exc), 409)


@app.post("/api/duet/{scene_id}/stop")
def duet_stop(scene_id: str):
    try:
        return _ok(duet_mod.engine.stop(scene_id))
    except duet_mod.DuetError as exc:
        return _fail(str(exc), 404)


@app.put("/api/duet/auto")
def duet_auto(payload: dict = Body(...)):
    try:
        return _ok(duet_mod.engine.update_auto(payload))
    except duet_mod.DuetError as exc:
        return _fail(str(exc), 400)


# ------------------------------------------------------------------ inbox


@app.get("/api/inbox/status")
def inbox_status():
    # 只读缓存：这里绝不能触发同步，否则每次轮询都会卡住几十秒
    return _ok(inbox_mod.status())


@app.get("/api/inbox/threads")
def inbox_threads(platform: str = Query(""), kind: str = Query(""), q: str = Query(""),
                  unread: bool = Query(False), limit: int = Query(100)):
    return _ok(inbox_mod.list_threads(platform, kind, q, unread, limit, instances=_instances()))


@app.get("/api/inbox/threads/{thread_id}/messages")
def inbox_messages(thread_id: str, before: float = Query(0),
                   before_rowid: int = Query(0), limit: int = Query(50)):
    # before + before_rowid 是同一时间戳消息的精确翻页游标
    return _ok(inbox_mod.thread_messages(thread_id, before, before_rowid, limit))


@app.post("/api/inbox/threads/{thread_id}/read")
def inbox_read(thread_id: str):
    return _ok(inbox_mod.mark_read(thread_id))


@app.post("/api/inbox/threads/{thread_id}/takeover")
def inbox_takeover(thread_id: str, payload: dict = Body(...)):
    # 只有布尔 True 才算开启；字符串 "false"/"0" 等不能被当成开启
    try:
        return _ok(inbox_mod.set_takeover(thread_id, payload.get("enabled") is True,
                                          instances=_instances()))
    except inbox_mod.InboxError as exc:
        return _fail(str(exc), 400)


@app.post("/api/inbox/threads/{thread_id}/send")
def inbox_send(thread_id: str, payload: dict = Body(...)):
    try:
        return _ok(inbox_mod.send_message(thread_id, payload.get("text", ""),
                                          payload.get("confirm", ""),
                                          instances=_instances()))
    except inbox_mod.InboxError as exc:
        return _fail(str(exc), 400)


@app.post("/api/inbox/sync")
def inbox_sync():
    # 手动刷新允许等待，但和后台循环共用单飞的 sync_once（进行中会返回 skipped）
    try:
        return _ok(inbox_mod.sync_once(_instances()))
    except inbox_mod.InboxError as exc:
        return _fail(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"同步失败：{exc}", 500)


@app.post("/api/inbox/ingest")
def inbox_ingest(payload: dict = Body(...)):
    try:
        return _ok(inbox_mod.ingest_message(payload, instances=_instances()))
    except inbox_mod.InboxError as exc:
        return _fail(str(exc), 400)


# ------------------------------------------------------------------- mood


@app.post("/api/mood/observe")
def mood_observe(payload: dict = Body(...)):
    try:
        return _ok(mood_mod.observe(payload, instances=_instances()))
    except mood_mod.MoodError as exc:
        return _fail(str(exc), 400)


@app.get("/api/mood/status")
def mood_status(instance_id: str = Query("")):
    inst = _require(_instances(), instance_id)
    return _ok(mood_mod.status(str(inst["id"])))


@app.get("/api/mood/events")
def mood_events(instance_id: str = Query(""), limit: int = Query(30)):
    inst = _require(_instances(), instance_id)
    return _ok(mood_mod.events(str(inst["id"]), limit))


@app.post("/api/mood/adjust")
def mood_adjust(payload: dict = Body(...)):
    try:
        _require(_instances(), str(payload.get("instance_id") or ""))
        return _ok(mood_mod.adjust(payload))
    except mood_mod.MoodError as exc:
        return _fail(str(exc), 400)


@app.post("/api/mood/reset")
def mood_reset(payload: dict = Body(...)):
    try:
        _require(_instances(), str(payload.get("instance_id") or ""))
        return _ok(mood_mod.reset(payload))
    except mood_mod.MoodError as exc:
        return _fail(str(exc), 400)


@app.put("/api/mood/settings")
def mood_settings(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    patch = {k: v for k, v in payload.items() if k != "instance_id"}
    try:
        return _ok(human_settings.save_settings(str(inst["id"]), patch))
    except human_settings.SettingsError as exc:
        return _fail(str(exc), 400)


# ------------------------------------------------------------------- human

@app.post("/api/human/plan")
def human_plan(payload: dict = Body(...)):
    try:
        return _ok(human_mode_mod.plan(payload, instances=_instances()))
    except human_mode_mod.HumanError as exc:
        return _fail(str(exc), 400)
    except mood_mod.MoodError as exc:
        return _fail(str(exc), 400)


@app.get("/api/human/status")
def human_status(instance_id: str = Query("")):
    inst = _require(_instances(), instance_id)
    return _ok(human_mode_mod.status(str(inst["id"])))


@app.put("/api/human/settings")
def human_settings_update(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    try:
        return _ok(human_mode_mod.save_settings({**payload, "instance_id": str(inst["id"])}))
    except human_mode_mod.HumanError as exc:
        return _fail(str(exc), 400)


@app.get("/api/human/styles")
def human_styles(instance_id: str = Query("")):
    inst = _require(_instances(), instance_id)
    return _ok(styles.list_styles(str(inst["id"])))


@app.post("/api/human/styles")
def human_styles_create(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    try:
        item = styles.save_style(
            str(inst["id"]), payload.get("name", ""), payload.get("note", ""),
            scope=payload.get("scope", "instance"),
            person_key=payload.get("person_key", ""),
            source="manual", enabled=payload.get("enabled", True))
    except styles.StyleError as exc:
        return _fail(str(exc), 400)
    return _ok(item)


@app.delete("/api/human/styles/{style_id}")
def human_styles_delete(style_id: str, instance_id: str = Query("")):
    inst = _require(_instances(), instance_id)
    current = styles.get_style(style_id)
    if not current or current.get("instance_id") != str(inst["id"]):
        return _fail("风格档案不存在", 404)
    return _ok({"deleted": styles.delete_style(style_id)})


# ---------------------------------------------------------------- presence


def _presence_confirmed(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "send", "confirm", "确认"}


def _presence_instance(payload: dict) -> dict:
    return mood_mod.resolve_instance(payload, _instances())


@app.post("/api/presence/activity")
def presence_activity(payload: dict = Body(...)):
    try:
        activities = payload.get("activities")
        if isinstance(activities, list):
            base = {key: payload[key] for key in
                    ("instance_id", "platform_id", "account_id")
                    if payload.get(key)}
            saved = [
                presence_mod.record_activity({**base, **item},
                                            instances=_instances())
                for item in activities[:100] if isinstance(item, dict)
            ]
            return _ok({"activities": saved})
        return _ok(presence_mod.record_activity(payload, instances=_instances()))
    except (presence_mod.PresenceError, mood_mod.MoodError) as exc:
        return _fail(str(exc), 400)


@app.post("/api/presence/scan")
def presence_scan(payload: dict = Body(...)):
    try:
        inst = _presence_instance(payload)
        return _ok(presence_mod.scan_loops(inst, payload))
    except (presence_mod.PresenceError, mood_mod.MoodError) as exc:
        return _fail(str(exc), 400)


@app.get("/api/presence/context")
def presence_context(instance_id: str = Query(""), platform: str = Query("qq"),
                     person_key: str = Query(""), platform_id: str = Query(""),
                     thread_key: str = Query("")):
    try:
        inst = _presence_instance({"instance_id": instance_id,
                                   "platform_id": platform_id})
        thread = thread_key if isinstance(thread_key, str) else ""
        return _ok(presence_mod.context(
            str(inst["id"]), platform, person_key, thread))
    except (presence_mod.PresenceError, mood_mod.MoodError) as exc:
        return _fail(str(exc), 400)


@app.get("/api/presence/followups/due")
def presence_followups_due(instance_id: str = Query(""),
                           platform_id: str = Query("")):
    try:
        inst = _presence_instance({"instance_id": instance_id,
                                   "platform_id": platform_id})
        return _ok(presence_mod.due_followups(str(inst["id"]), inst=inst))
    except (presence_mod.PresenceError, mood_mod.MoodError) as exc:
        return _fail(str(exc), 400)


@app.post("/api/presence/followups/{loop_id}/sent")
def presence_followup_sent(loop_id: str, payload: dict = Body(default={})):
    loop = presence_mod.get_loop(loop_id)
    if loop is None:
        return _fail("未完成话题不存在", 404)
    instance_id = str(payload.get("instance_id") or loop.get("instance_id") or "")
    _require(_instances(), instance_id)
    if str(loop.get("instance_id")) != instance_id:
        return _fail("未完成话题不属于该实例", 404)
    try:
        return _ok(presence_mod.mark_sent(loop_id))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.post("/api/presence/radar")
def presence_radar(payload: dict = Body(...)):
    try:
        return _ok(presence_mod.radar_events(payload, instances=_instances()))
    except (presence_mod.PresenceError, mood_mod.MoodError) as exc:
        return _fail(str(exc), 400)


@app.get("/api/presence/radar")
def presence_radar_list(instance_id: str = Query(""), days: int = Query(7)):
    inst = _require(_instances(), instance_id)
    try:
        return _ok(presence_mod.radar_stats(str(inst["id"]), days))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.get("/api/presence/loops")
def presence_loops(instance_id: str = Query(""), status: str = Query(""),
                   limit: int = Query(100)):
    inst = _require(_instances(), instance_id)
    try:
        return _ok(presence_mod.list_loops(str(inst["id"]), status or None, limit))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.post("/api/presence/loops")
def presence_loops_create(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    try:
        item = presence_mod.add_loop(
            str(inst["id"]), str(payload.get("platform") or "qq"),
            str(payload.get("person_key") or ""), str(payload.get("topic") or ""),
            thread_key=str(payload.get("thread_key") or ""),
            detail=str(payload.get("detail") or ""),
            confidence=payload.get("confidence", 0.5),
            source="manual",
            follow_up_after_hours=payload.get("follow_up_after_hours", 24))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)
    return _ok(item)


@app.patch("/api/presence/loops/{loop_id}")
def presence_loops_update(loop_id: str, payload: dict = Body(...)):
    loop = presence_mod.get_loop(loop_id)
    if loop is None:
        return _fail("未完成话题不存在", 404)
    _require(_instances(), str(loop.get("instance_id") or ""))
    if payload.get("instance_id") and str(payload["instance_id"]) != str(loop["instance_id"]):
        return _fail("未完成话题不属于该实例", 404)
    patch = {key: value for key, value in payload.items() if key != "instance_id"}
    try:
        return _ok(presence_mod.update_loop(loop_id, patch))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.post("/api/presence/loops/{loop_id}/preview")
def presence_loops_preview(loop_id: str, payload: dict = Body(default={})):
    loop = presence_mod.get_loop(loop_id)
    if loop is None:
        return _fail("未完成话题不存在", 404)
    inst = _require(_instances(), str(loop.get("instance_id") or ""))
    try:
        saved = presence_mod.generate_follow_up(inst, loop_id)
        shadow = bool(presence_mod.get_settings(str(inst["id"]))["followup_shadow"])
        presence_mod.add_event(
            str(inst["id"]), "followup_shadow", person_key=str(saved["person_key"]),
            payload={"loop_id": saved["id"], "topic": saved["topic"],
                     "text": saved["follow_up_text"], "shadow": shadow})
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)
    return _ok({"loop": saved, "shadow": shadow})


@app.post("/api/presence/loops/{loop_id}/send")
def presence_loop_send(loop_id: str, payload: dict = Body(default={})):
    if not _presence_confirmed(payload.get("confirm")):
        return _fail("发送回访需要 confirm=true 确认", 400)
    loop = presence_mod.get_loop(loop_id)
    if loop is None:
        return _fail("未完成话题不存在", 404)
    inst = _require(_instances(), str(loop.get("instance_id") or ""))
    try:
        return _ok(presence_mod.send_now(inst, loop_id))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.get("/api/presence/relations")
def presence_relations(instance_id: str = Query(""), limit: int = Query(200)):
    inst = _require(_instances(), instance_id)
    return _ok(presence_mod.list_relations(str(inst["id"]), limit=limit))


@app.patch("/api/presence/relations/{relation_id}")
def presence_relations_update(relation_id: str, payload: dict = Body(...)):
    relation = presence_mod.get_relation_by_id(relation_id)
    if relation is None:
        return _fail("关系不存在", 404)
    _require(_instances(), str(relation.get("instance_id") or ""))
    if payload.get("instance_id") and str(payload["instance_id"]) != str(
            relation["instance_id"]):
        return _fail("关系不属于该实例", 404)
    patch = {key: value for key, value in payload.items() if key != "instance_id"}
    try:
        return _ok(presence_mod.update_relation(relation_id, patch))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.get("/api/presence/milestones")
def presence_milestones(instance_id: str = Query(""), platform: str = Query(""),
                        person_key: str = Query(""), limit: int = Query(100)):
    inst = _require(_instances(), instance_id)
    return _ok(presence_mod.list_milestones(
        str(inst["id"]), platform or None, person_key or None, limit))


@app.post("/api/presence/milestones")
def presence_milestones_create(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    try:
        item = presence_mod.add_milestone(
            str(inst["id"]), str(payload.get("platform") or "qq"),
            str(payload.get("person_key") or ""),
            str(payload.get("kind") or "custom"),
            str(payload.get("title") or ""),
            detail=str(payload.get("detail") or ""),
            occurred_at=payload.get("occurred_at"),
            source="manual")
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)
    return _ok(item)


@app.delete("/api/presence/milestones")
def presence_milestones_delete(milestone_id: str = Query(""),
                               instance_id: str = Query("")):
    item = presence_mod.get_milestone(milestone_id) if milestone_id else None
    if item is None:
        return _fail("里程碑不存在", 404)
    _require(_instances(), str(item.get("instance_id") or ""))
    if instance_id and instance_id != str(item["instance_id"]):
        return _fail("里程碑不属于该实例", 404)
    return _ok({"deleted": presence_mod.delete_milestone(milestone_id)})


@app.get("/api/presence/rhythm")
def presence_rhythm(instance_id: str = Query("")):
    inst = _require(_instances(), instance_id)
    try:
        return _ok(rhythm_mod.current(str(inst["id"])))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.put("/api/presence/rhythm")
def presence_rhythm_update(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    patch = {key: value for key, value in payload.items() if key != "instance_id"}
    try:
        human_settings.save_settings(str(inst["id"]), patch)
        return _ok(rhythm_mod.current(str(inst["id"])))
    except (human_settings.SettingsError, presence_mod.PresenceError) as exc:
        return _fail(str(exc), 400)


@app.get("/api/presence/group-config")
def presence_group_config(instance_id: str = Query("")):
    inst = _require(_instances(), instance_id)
    try:
        return _ok(presence_mod.gc_config(inst))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.put("/api/presence/group-config")
def presence_group_config_update(payload: dict = Body(...)):
    if not _presence_confirmed(payload.get("confirm")):
        return _fail("写入群聊配置需要 confirm=true 确认", 400)
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    config = payload.get("config")
    if not isinstance(config, dict):
        return _fail("config 必须是对象", 400)
    try:
        return _ok(presence_mod.save_gc_config(inst, config))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.get("/api/presence/diaries")
def presence_diaries(instance_id: str = Query(""), limit: int = Query(60)):
    inst = _require(_instances(), instance_id)
    return _ok(presence_mod.list_diaries(str(inst["id"]), limit))


@app.post("/api/presence/diaries/generate")
def presence_diaries_generate(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    try:
        return _ok(presence_mod.generate_diary(
            inst, date=payload.get("date") or None,
            force=bool(payload.get("force"))))
    except (presence_mod.PresenceError, mood_mod.MoodError) as exc:
        return _fail(str(exc), 400)


@app.patch("/api/presence/diaries/{diary_id}")
def presence_diaries_update(diary_id: str, payload: dict = Body(...)):
    diary = presence_mod.get_diary_by_id(diary_id)
    if diary is None:
        return _fail("日记不存在", 404)
    _require(_instances(), str(diary.get("instance_id") or ""))
    if payload.get("instance_id") and str(payload["instance_id"]) != str(
            diary["instance_id"]):
        return _fail("日记不属于该实例", 404)
    patch = {key: value for key, value in payload.items() if key != "instance_id"}
    try:
        return _ok(presence_mod.update_diary(diary_id, patch))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.delete("/api/presence/diaries/{diary_id}")
def presence_diaries_delete(diary_id: str, instance_id: str = Query(""),
                            confirm: bool = Query(False)):
    if not confirm:
        return _fail("删除日记需要 confirm=true 确认", 400)
    diary = presence_mod.get_diary_by_id(diary_id)
    if diary is None:
        return _fail("日记不存在", 404)
    _require(_instances(), str(diary.get("instance_id") or ""))
    if instance_id and instance_id != str(diary["instance_id"]):
        return _fail("日记不属于该实例", 404)
    return _ok({"deleted": presence_mod.delete_diary(diary_id)})


@app.get("/api/presence/settings")
def presence_settings(instance_id: str = Query("")):
    inst = _require(_instances(), instance_id)
    return _ok(presence_mod.get_settings(str(inst["id"])))


@app.put("/api/presence/settings")
def presence_settings_update(payload: dict = Body(...)):
    inst = _require(_instances(), str(payload.get("instance_id") or ""))
    patch = {key: value for key, value in payload.items() if key != "instance_id"}
    try:
        return _ok(presence_mod.save_settings(str(inst["id"]), patch))
    except presence_mod.PresenceError as exc:
        return _fail(str(exc), 400)


@app.get("/api/bootstrap")
def bootstrap():
    settings = _settings()
    instances = seed_instances(settings)
    source = Path(settings.get("astrbot_source", ""))
    python = Path(settings.get("python_exe", ""))
    return _ok(
        {
            "settings": settings,
            "instances": [_decorate(i) for i in instances],
            "env": {
                "source_ok": (source / "main.py").exists(),
                "python_ok": python.exists(),
                "source": str(source),
                "python": str(python),
                "market_index": len(market.load_items(settings)),
                "data_dir": str(store.DATA_DIR),
                "base_dir": str(BASE_DIR),
            },
        }
    )


# -------------------------------------------------------------- deploy


@app.get("/api/deploy/status")
def deploy_status():
    """零机器人首屏：是否需要一键部署以及环境是否就绪。"""
    settings = _settings()
    instances = seed_instances(settings)
    data = deploy_mod.status(settings, instances)
    data["runtime"] = provisioner_mod.runtime_status(settings, instances)
    return _ok(data)


@app.post("/api/deploy/env")
def deploy_env(payload: dict = Body(...)):
    try:
        return _ok(deploy_mod.save_env(payload, _settings()))
    except deploy_mod.DeployError as exc:
        return _fail(str(exc), 400)


@app.post("/api/deploy/quick")
def deploy_quick(payload: dict = Body(...)):
    """创建第一个机器人并后台启动，返回部署任务供前端轮询。"""
    settings = _settings()
    with _INST_LOCK:
        instances = _instances()
        try:
            instance, provider = deploy_mod.prepare(payload, settings, instances)
        except deploy_mod.DeployError as exc:
            return _fail(str(exc), 400)
        instances.append(instance)
        save_instances(instances)
    job = deploy_mod.start(instance, settings, provider)
    return _ok(
        {"instance": _decorate(instance), "job": job},
        "机器人已创建，正在启动",
    )


@app.get("/api/deploy/jobs/{job_id}")
def deploy_job(job_id: str):
    job = deploy_mod.job(job_id)
    if not job:
        return _fail("部署任务不存在或已过期", 404)
    return _ok(job)


@app.post("/api/deploy/test")
def deploy_test(payload: dict = Body(...)):
    """用最小请求测试模型接口与 API Key 是否可用。"""
    try:
        return _ok(deploy_mod.test_connection(payload), "模型连接正常")
    except deploy_mod.DeployError as exc:
        return _fail(str(exc), 400)


@app.post("/api/deploy/models")
def deploy_models(payload: dict = Body(...)):
    """用 API Key 拉取服务商真实可用的模型列表。"""
    try:
        data = deploy_mod.list_models(payload)
    except deploy_mod.DeployError as exc:
        return _fail(str(exc), 400)
    return _ok(data, str(data.get("message") or ""))


@app.post("/api/deploy/install/env")
def deploy_install_env():
    """下载 AstrBot 源码、准备 Python 与依赖。"""
    job = provisioner_mod.install_environment(_settings())
    return _ok(job, "已开始安装运行环境")


@app.post("/api/deploy/install/napcat")
def deploy_install_napcat(payload: dict | None = Body(default=None)):
    payload = payload or {}
    try:
        job = provisioner_mod.install_napcat(
            str(payload.get("instance_id") or ""),
            _settings(),
            qq=str(payload.get("qq") or ""),
            start=bool(payload.get("start")),
        )
    except provisioner_mod.InstallError as exc:
        return _fail(str(exc), 400)
    return _ok(job, "已开始安装 QQ 登录环境")


@app.post("/api/deploy/install/plugins")
def deploy_install_plugins(payload: dict | None = Body(default=None)):
    payload = payload or {}
    ids = payload.get("plugins")
    try:
        job = provisioner_mod.install_plugins(
            str(payload.get("instance_id") or ""),
            _settings(),
            [str(item) for item in ids] if isinstance(ids, list) else None,
        )
    except provisioner_mod.InstallError as exc:
        return _fail(str(exc), 400)
    return _ok(job, "已开始安装插件套装")


@app.get("/api/deploy/install/jobs/{job_id}")
def deploy_install_job(job_id: str):
    job = provisioner_mod.job(job_id)
    if not job:
        return _fail("安装任务不存在或已过期", 404)
    return _ok(job)


# -------------------------------------------------------------- instances


@app.get("/api/instances")
def list_instances():
    return _ok([_decorate(i) for i in _instances()])


@app.post("/api/instances")
def create_instance(payload: dict = Body(...)):
    settings = _settings()
    instances = _instances()
    try:
        inst = creator.create_instance(payload, settings, instances)
    except creator.CreateError as exc:
        return _fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"创建失败：{exc}")
    instances.append(inst)
    save_instances(instances)

    if payload.get("auto_start"):
        try:
            runner.start(inst, settings)
            _persist(inst)
            _spawn_provision(inst)
        except Exception as exc:  # noqa: BLE001
            return _ok(_decorate(inst), f"已创建，但启动失败：{exc}")
    return _ok(_decorate(inst), "机器人已创建")


@app.put("/api/instances/{inst_id}")
def update_instance(inst_id: str, payload: dict = Body(...)):
    instances = _instances()
    inst = _require(instances, inst_id)
    editable = {
        "name",
        "qq",
        "dash_port",
        "ws_port",
        "dash_user",
        "dash_pass",
        "napcat_dir",
        "napcat_port",
        "note",
        "color",
        "root",
        "persona_prompt",
    }
    for key in editable:
        if key in payload and payload[key] is not None:
            inst[key] = payload[key]
    for key in ("dash_port", "ws_port", "napcat_port"):
        if key in inst:
            try:
                inst[key] = int(inst[key])
            except Exception:
                pass
    save_instances(instances)
    return _ok(_decorate(inst), "已保存")


@app.delete("/api/instances/{inst_id}")
def delete_instance(inst_id: str, purge: bool = Query(False)):
    instances = _instances()
    inst = _require(instances, inst_id)
    try:
        runner.stop(inst)
    except Exception:  # noqa: BLE001
        pass
    instances = [i for i in instances if i.get("id") != inst_id]
    save_instances(instances)
    purged = False
    if purge:
        root = Path(inst.get("root", ""))
        allowed = Path(_settings().get("instances_dir", "")).resolve()
        try:
            if root.exists() and allowed in root.resolve().parents:
                shutil.rmtree(root)
                purged = True
        except Exception:
            purged = False
    return _ok({"purged": purged}, "已移除")


def _start_flow(inst: dict, restart: bool = False) -> tuple[dict, str]:
    """启动（或重启）AstrBot，并在需要时联动拉起 NapCat。"""
    notes = creator.sync_platform(inst)
    settings = _settings()
    if restart:
        runner.restart(inst, settings)
    else:
        runner.start(inst, settings)
    _persist(inst)
    _spawn_provision(inst)

    napcat_note = ""
    napcat_info = runner.napcat_status(inst)
    if napcat_info.get("configured"):
        if napcat_info.get("running"):
            napcat_note = "NapCat 已在线"
        else:
            try:
                creator.sync_napcat(inst)
                launched = runner.start_napcat(inst)
                napcat_note = (
                    "NapCat 已在运行，请在「扫码 / 控制台」页确认登录状态"
                    if launched.get("already")
                    else "已同时启动 NapCat，请打开「扫码 / 控制台」页扫码登录（登录成功后消息才会回复）"
                )
            except Exception as exc:  # noqa: BLE001
                napcat_note = f"NapCat 启动失败：{exc}"

    view = _decorate(inst)
    view["sync"] = notes
    view["napcat_note"] = napcat_note
    message = "；".join(part for part in ("启动指令已发送", napcat_note) if part)
    return view, message


@app.post("/api/instances/{inst_id}/start")
def start_instance(inst_id: str):
    inst = _require(_instances(), inst_id)
    try:
        view, message = _start_flow(inst)
    except runner_mod.RunnerError as exc:
        return _fail(str(exc))
    return _ok(view, message)


@app.post("/api/instances/{inst_id}/stop")
def stop_instance(inst_id: str):
    instances = _instances()
    inst = _require(instances, inst_id)
    try:
        runner.stop(inst)
    except runner_mod.RunnerError as exc:
        return _fail(str(exc))
    _persist(inst)
    return _ok(_decorate(inst), "已停止")


@app.post("/api/instances/{inst_id}/restart")
def restart_instance(inst_id: str):
    inst = _require(_instances(), inst_id)
    try:
        view, message = _start_flow(inst, restart=True)
    except runner_mod.RunnerError as exc:
        return _fail(str(exc))
    return _ok(view, message.replace("启动指令已发送", "重启指令已发送"))


@app.post("/api/instances/{inst_id}/adopt")
def adopt_instance(inst_id: str):
    """接管外部启动的实例：找到监听 Dashboard 端口的进程并登记 PID。"""
    instances = _instances()
    inst = _require(instances, inst_id)
    port = int(inst.get("dash_port") or 0)
    pid = runner_mod.listening_pid(port)
    if not pid:
        return _fail(f"端口 {port} 上没有找到可接管的进程（机器人可能没在运行）")
    inst["pid"] = pid
    _persist(inst)
    return _ok(_decorate(inst), f"已接管进程 PID {pid}，此后可在此启停")


@app.post("/api/instances/{inst_id}/napcat/start")
def start_napcat(inst_id: str):
    instances = _instances()
    inst = _require(instances, inst_id)
    try:
        creator.sync_napcat(inst)
        result = runner.start_napcat(inst)
    except runner_mod.RunnerError as exc:
        return _fail(str(exc))
    if result.get("already"):
        return _ok(result, "NapCat 已在运行，可在「扫码登录」页查看二维码")
    return _ok(result, "NapCat 已在后台启动，请打开「扫码登录」页完成 QQ 登录")


@app.post("/api/instances/{inst_id}/napcat/login")
def napcat_login(inst_id: str):
    """启动 NapCat（无窗口）并返回当前二维码/登录状态。"""
    inst = _require(_instances(), inst_id)
    if not Path(inst.get("napcat_dir") or "").is_dir():
        return _fail("请先在设置里填写有效的 NapCat 目录")
    try:
        creator.sync_napcat(inst)
        result = runner.start_napcat(inst)
        state = napcat_mod.login_state(inst)
    except runner_mod.RunnerError as exc:
        return _fail(str(exc))
    except napcat_mod.NapCatError as exc:
        return _fail(str(exc), 502)
    message = "NapCat 已在后台运行，二维码生成后自动显示" if result.get("already") else "NapCat 正在后台启动，请稍候"
    return _ok(state, message)


@app.get("/api/instances/{inst_id}/napcat/qrcode")
def napcat_qrcode(inst_id: str, refresh: int = 0):
    """轮询扫码状态；refresh=1 时立即换一张新二维码。"""
    inst = _require(_instances(), inst_id)
    try:
        return _ok(napcat_mod.login_state(inst, force_refresh=bool(refresh)))
    except napcat_mod.NapCatError as exc:
        return _fail(str(exc), 502)


@app.get("/api/instances/{inst_id}/logs")
def instance_logs(inst_id: str, lines: int = 200, source: str = "bot"):
    instances = _instances()
    inst = _require(instances, inst_id)
    data_dir = Path(inst["root"]) / "data" / "logs"
    if source == "console":
        path = data_dir / "manager-console.log"
    elif source == "napcat":
        path = data_dir / "napcat-console.log"
    else:
        path = data_dir / "astrbot.log"
    text = runner_mod.tail(path, lines)
    if not text and source == "bot":
        # AstrBot 默认只往控制台输出，没有 astrbot.log 时回退到管理器捕获的控制台日志
        console = data_dir / "manager-console.log"
        fallback = runner_mod.tail(console, lines)
        if fallback:
            return _ok(
                {"text": "\n".join(fallback), "path": str(console), "fallback": True}
            )
    return _ok({"text": "\n".join(text), "path": str(path)})


def _list_data(payload) -> list:
    """Dashboard 有些接口把列表包在 data.xxx 里，这里统一摊平成列表。"""
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "list", "providers", "bots", "plugins", "personas"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


@app.get("/api/instances/{inst_id}/summary")
def instance_summary(inst_id: str):
    instances = _instances()
    inst = _require(instances, inst_id)
    summary: dict = {"status": runner.status(inst), "plugins": None, "providers": None}
    try:
        plugins = _list_data(dashboard.call(inst, "GET", "plugins", timeout=12))
        summary["plugins"] = len(plugins)
        summary["plugin_list"] = [
            {
                "id": p.get("id") or p.get("name"),
                "name": p.get("name"),
                "version": p.get("version"),
                "enabled": p.get("enabled", p.get("activated")),
                "desc": p.get("desc", ""),
            }
            for p in plugins
            if isinstance(p, dict)
        ]
    except Exception as exc:  # noqa: BLE001
        summary["error"] = str(exc)
    try:
        providers = _list_data(dashboard.call(inst, "GET", "providers", timeout=12))
        summary["providers"] = [
            {
                "id": p.get("id"),
                "model": p.get("model"),
                "type": p.get("provider_type") or p.get("type"),
                "enable": p.get("enable", True),
            }
            for p in providers
            if isinstance(p, dict)
        ]
    except Exception:
        pass
    try:
        summary["bots"] = _list_data(dashboard.call(inst, "GET", "bots", timeout=12))
    except Exception:
        pass
    return _ok(summary)


@app.post("/api/instances/{inst_id}/provision")
def provision_instance(inst_id: str):
    instances = _instances()
    inst = _require(instances, inst_id)
    result = creator.provision(inst, timeout=90)
    if result.get("ok"):
        inst["provisioned"] = True
        _persist(inst)
    return _ok(result, "初始化完成" if result.get("ok") else result.get("message", ""))


@app.get("/api/instances/{inst_id}/bili")
def instance_bili(inst_id: str):
    inst = _require(_instances(), inst_id)
    try:
        return _ok(bili.status(inst))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"读取 B站数据失败：{exc}", 500)


@app.get("/api/instances/{inst_id}/consoles/{kind}/status")
def console_status(inst_id: str, kind: str):
    inst = _require(_instances(), inst_id)
    try:
        data = consoles.call_status(inst, kind)
    except consoles.ConsoleError as exc:
        return _fail(exc.message, exc.status)
    snapshot = None
    if kind == "bili":
        try:
            snapshot = bili.status(inst)
        except Exception:  # noqa: BLE001
            snapshot = None
    return _ok({"kind": kind, "status": data, "snapshot": snapshot})


@app.post("/api/instances/{inst_id}/consoles/{kind}/run")
def console_run(inst_id: str, kind: str):
    inst = _require(_instances(), inst_id)
    try:
        return _ok(consoles.call_run(inst, kind), "已触发")
    except consoles.ConsoleError as exc:
        return _fail(exc.message, exc.status)


# ------------------------------------------------------------ memory page


def _memory_instance(inst_id: str):
    return _require(_instances(), inst_id)


@app.get("/api/instances/{inst_id}/memory/status")
def memory_status(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_status(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/items")
def memory_items(
    inst_id: str,
    request: Request,
    keyword: str = "",
    session_id: str = "",
    persona_id: str = "",
    status: str = "all",
    type: str = "",
    sort: str = "created_desc",
    page: int = 1,
    page_size: int = 20,
):
    inst = _memory_instance(inst_id)
    if page < 1 or page_size < 1 or page_size > 200:
        return _fail("分页参数无效", 400)
    query = {
        "keyword": keyword.strip(),
        "session_id": session_id.strip() or None,
        "persona_id": persona_id.strip() or None,
        "status": status.strip() or "all",
        "type": type.strip() or None,
        "sort": sort.strip() or "created_desc",
        "page": page,
        "page_size": page_size,
    }
    try:
        return _ok(memory.call_memories(inst, query))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/items/{memory_id}")
def memory_detail(inst_id: str, memory_id: int):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_detail(inst, memory_id))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/items/{memory_id}/update")
def memory_update(inst_id: str, memory_id: int, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    field = str(payload.get("field", "")).strip()
    allowed = {"content", "topics", "key_facts", "importance", "status", "type", "structured"}
    if field not in allowed:
        return _fail("不支持的编辑字段", 400)
    if "value" not in payload:
        return _fail("缺少 value", 400)
    try:
        return _ok(
            memory.call_update(
                inst,
                memory_id,
                field,
                payload.get("value"),
                str(payload.get("reason", "")),
            )
        )
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/items/{memory_id}/resummarize")
def memory_resummarize(inst_id: str, memory_id: int):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_resummarize(inst, memory_id))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/items/{memory_id}/arousal")
def memory_arousal(inst_id: str, memory_id: int, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    if payload.get("arousal") is None or payload.get("arousal") == "":
        return _fail("arousal 不能为空", 400)
    try:
        return _ok(
            memory.call_arousal_update(
                inst,
                memory_id,
                payload.get("arousal"),
                str(payload.get("reason") or ""),
            )
        )
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/prompt/preview")
def memory_prompt_preview(inst_id: str, scope: str = "private"):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_prompt_preview(inst, scope))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/prompt/merge")
def memory_prompt_merge(inst_id: str, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    try:
        result = memory.call_prompt_merge(
            inst,
            payload.get("scope", "private"),
            payload.get("confirm", ""),
        )
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)
    message = "已合并，请手动重载插件" if result.get("merged") else ""
    return _ok(result, message)


@app.get("/api/instances/{inst_id}/memory/working")
def memory_working(inst_id: str, session_id: str = "", limit: int = 20):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_working(inst, session_id, limit))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/relations")
def memory_relations(inst_id: str, days: int = 90, limit: int = 100):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_relations(inst, days, limit))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/emotion")
def memory_emotion(
    inst_id: str,
    identity_key: str = "",
    days: int = 90,
    limit: int = 200,
):
    inst = _memory_instance(inst_id)
    if not identity_key.strip():
        return _fail("identity_key 不能为空", 400)
    try:
        return _ok(memory.call_emotion(inst, identity_key, days, limit))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/health/forgetting")
def memory_health_forgetting(inst_id: str, limit: int = 50, status: str = "active"):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_forgetting(inst, limit, status))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/health/review-preview")
def memory_health_review_preview(inst_id: str, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    raw_id = payload.get("memory_id")
    if raw_id is None or raw_id == "":
        return _fail("memory_id 不能为空", 400)
    try:
        memory_id = int(raw_id)
    except (TypeError, ValueError):
        return _fail("memory_id 必须是整数", 400)
    if memory_id <= 0:
        return _fail("memory_id 必须是正整数", 400)
    try:
        return _ok(memory.call_review_preview(inst, memory_id))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/active-recall/status")
def memory_active_recall_status(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_active_recall_status(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/active-recall/events")
def memory_active_recall_events(inst_id: str, limit: int = 50):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_active_recall_events(inst, limit))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/active-recall/preview")
def memory_active_recall_preview(inst_id: str, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    query = str(payload.get("query", "")).strip()
    if not query:
        return _fail("查询内容不能为空", 400)
    try:
        return _ok(
            memory.call_active_recall_preview(
                inst, query, str(payload.get("session_id") or "")
            )
        )
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/health/review")
def memory_health_review(inst_id: str, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    raw_id = payload.get("memory_id")
    if raw_id is None or raw_id == "":
        return _fail("memory_id 不能为空", 400)
    try:
        memory_id = int(raw_id)
    except (TypeError, ValueError):
        return _fail("memory_id 必须是整数", 400)
    if memory_id <= 0:
        return _fail("memory_id 必须是正整数", 400)
    confirm = str(payload.get("confirm") or "")
    if confirm != "REVIEW":
        return _fail('需要 confirm 为 "REVIEW" 才能执行复习', 400)
    try:
        return _ok(memory.call_review(inst, memory_id, confirm))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/export")
def memory_export(inst_id: str, q: str = "", type: str = "", status: str = "all"):
    inst = _memory_instance(inst_id)
    try:
        result = memory.export_memories(
            inst,
            {"q": q.strip(), "type": type.strip(), "status": status.strip() or "all"},
        )
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)
    filename = str(result.get("filename") or "memory-export.json")
    return JSONResponse(
        _ok(result),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/instances/{inst_id}/memory/recall")
def memory_recall(inst_id: str, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    query = str(payload.get("query", "")).strip()
    if not query:
        return _fail("查询内容不能为空", 400)
    try:
        k = max(1, min(int(payload.get("k", 5)), 50))
    except (TypeError, ValueError):
        return _fail("k 必须是整数", 400)
    session_id = str(payload.get("session_id", "")).strip() or None
    person_identity = str(payload.get("person_identity", "")).strip()
    is_private = payload.get("is_private")
    if not isinstance(is_private, bool):
        is_private = None
    if is_private is None and session_id:
        if "FriendMessage" in session_id:
            is_private = True
        elif "GroupMessage" in session_id:
            is_private = False
    body = {"query": query, "k": k, "session_id": session_id}
    if person_identity:
        body["person_identity"] = person_identity
    if isinstance(is_private, bool):
        body["is_private"] = is_private
    try:
        return _ok(memory.call_recall(inst, body))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/graph")
def memory_graph(
    inst_id: str,
    request: Request,
    session_id: str = "",
    persona_id: str = "",
    limit_memories: int = 12,
    limit_entries: int = 36,
    limit_nodes: int = 48,
    limit_edges: int = 72,
):
    inst = _memory_instance(inst_id)
    query = {
        "session_id": session_id.strip() or None,
        "persona_id": persona_id.strip() or None,
        "limit_memories": max(1, min(limit_memories, 24)),
        "limit_entries": max(12, min(limit_entries, 80)),
        "limit_nodes": max(12, min(limit_nodes, 80)),
        "limit_edges": max(12, min(limit_edges, 120)),
    }
    try:
        return _ok(memory.call_graph(inst, query))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/audit")
def memory_audit_get(inst_id: str, include_forgetting: bool = False):
    inst = _memory_instance(inst_id)
    try:
        result = memory_audit.collect(inst)
        if include_forgetting:
            try:
                forgetting = memory.call_forgetting(inst)
            except memory.MemoryError:
                # Old plugins without the B2 health route still return the
                # aggregate audit unchanged; forgetting is an optional extra.
                forgetting = None
            result = memory_audit.merge(result, forgetting)
        return _ok(result)
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/sleep/status")
def memory_sleep_status(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_sleep_status(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/sleep/preview")
def memory_sleep_preview(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_sleep_preview(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/sleep/run")
def memory_sleep_run(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_sleep_run(inst), "已触发")
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/sleep/reports")
def memory_sleep_reports(inst_id: str, limit: int = 30):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_sleep_reports(inst, limit))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/reconsolidation/status")
def memory_recon_status(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_recon_status(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/reconsolidation/manual")
def memory_recon_manual(inst_id: str, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    mode = str(payload.get("mode", "preview")).strip().lower()
    if mode not in {"preview", "apply"}:
        return _fail("mode 必须是 preview 或 apply", 400)
    if not str(payload.get("user_message", "")).strip():
        return _fail("校正文本不能为空", 400)
    try:
        return _ok(memory.call_recon_manual(inst, payload, mode))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/backfill/preview")
def memory_backfill_preview(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_backfill_preview(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/backfill/status")
def memory_backfill_status(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_backfill_status(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/backfill/run")
def memory_backfill_run(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_backfill_run(inst), "已触发")
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/backfill/cancel")
def memory_backfill_cancel(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_backfill_cancel(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/vector/status")
def memory_vector_status(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_vector_status(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/vector/probe")
def memory_vector_probe(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_vector_probe(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/memory/vector/rebuild")
def memory_vector_rebuild(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_vector_rebuild(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.get("/api/instances/{inst_id}/memory/config")
def memory_config(inst_id: str):
    inst = _memory_instance(inst_id)
    try:
        return _ok(memory.call_config(inst))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.put("/api/instances/{inst_id}/memory/config")
def memory_config_save(inst_id: str, payload: dict = Body(...)):
    inst = _memory_instance(inst_id)
    values = payload.get("values")
    try:
        return _ok(memory.call_save_config(inst, values))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


def _spawn_provision(inst: dict) -> None:
    """仅对管理器新建的实例自动初始化，避免改写已有实例的配置。"""
    if inst.get("source") != "created" or inst.get("provisioned"):
        return

    def _job() -> None:
        result = creator.provision(inst, timeout=240)
        if result.get("ok"):
            inst["provisioned"] = True
            _persist(inst)

    threading.Thread(target=_job, daemon=True).start()


# ------------------------------------------------------- dashboard 代理


_BLOCKED = {"..", ".", ""}


@app.api_route(
    "/api/instances/{inst_id}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy(inst_id: str, path: str, request: Request):
    instances = _instances()
    inst = _require(instances, inst_id)
    parts = path.split("/")
    if any(part in _BLOCKED for part in parts):
        return _fail("非法路径", 400)
    payload = None
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        raw = await request.body()
        if raw:
            try:
                payload = json.loads(raw)
            except Exception:
                payload = None
    query = dict(request.query_params)
    timeout = 300.0 if "install" in path else 90.0
    try:
        result = dashboard.call(
            inst, request.method, path, payload, query, timeout=timeout
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    if isinstance(result, dict) and result.get("status") == "error":
        return _fail(result.get("message") or "Dashboard 返回错误", 502)
    return _ok(result.get("data", result), result.get("message", ""))


# ----------------------------------------------------------------- market


@app.get("/api/market")
def market_search(
    q: str = Query(""),
    category: str = Query(""),
    page: int = Query(1),
    size: int = Query(24),
):
    return _ok(market.search(_settings(), q, category, page, size))


@app.get("/api/market/categories")
def market_categories():
    return _ok(market.categories(_settings()))


@app.post("/api/market/refresh")
def market_refresh():
    try:
        return _ok(market.refresh(_settings()), "市场索引已刷新")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"刷新失败：{exc}")


def _repair_legacy_market_archive(inst: dict, entry: dict, plugin_id: str,
                                  download_url: str) -> tuple[dict | None, str]:
    """下载市场包并在缺 metadata 时补齐上传；无需修复时返回 (None, "")。"""
    if not download_url:
        return None, ""
    try:
        raw = market.download_archive(download_url)
        repaired = market.inject_metadata(raw, entry or {"id": plugin_id})
    except Exception:  # noqa: BLE001 - 无法确认缺 metadata 时保留原始错误
        return None, ""
    if repaired == raw:
        return None, ""
    try:
        upload_body, content_type = market.multipart_payload(
            {"ignore_version_check": "true"}, "plugin.zip", repaired)
        result = dashboard.upload_raw(
            inst, "plugins/install/upload", upload_body, content_type, timeout=600)
    except dashboard.DashboardError as exc:
        return None, f"自动补齐 metadata 失败：{exc.message}"
    if isinstance(result, dict) and result.get("status") == "error":
        return None, (
            "自动补齐 metadata 后安装失败："
            f"{result.get('message') or '未知错误'}")
    return result, ""


@app.post("/api/market/install")
def market_install(payload: dict = Body(...)):
    """把市场索引中的插件安装到某个实例；旧包缺 metadata 时自动补齐。"""
    settings = _settings()
    instances = _instances()
    inst_id = str(payload.get("instance_id") or "")
    plugin_id = str(payload.get("plugin_id") or "")
    url = str(payload.get("url") or "")
    download_url = str(payload.get("download_url") or "")
    if not inst_id:
        return _fail("请选择目标机器人")
    inst = _require(instances, inst_id)
    entry = market.find(settings, plugin_id) if plugin_id else {}
    entry = entry or {}
    if not download_url:
        download_url = str(entry.get("download_url") or "")
    url = url or str(entry.get("repo") or "")
    body = {
        "url": url,
        "download_url": download_url,
        "ignore_version_check": bool(payload.get("ignore_version_check", True)),
        "proxy": "",
    }
    if not download_url and not url:
        return _fail("缺少下载地址")
    try:
        result = dashboard.call(inst, "POST", "plugins/install/url", body, timeout=600)
    except dashboard.DashboardError as exc:
        repaired, repair_error = _repair_legacy_market_archive(
            inst, entry, plugin_id, download_url)
        if repair_error:
            return _fail(repair_error, 502)
        if repaired is None:
            return _fail(exc.message, exc.status if exc.status >= 400 else 502)
        return _ok(
            repaired.get("data", repaired),
            "插件包缺少 metadata，已按市场信息补齐后安装")
    if isinstance(result, dict) and result.get("status") == "error":
        # AstrBot 缺 metadata 时也走 HTTP 200 + status=error，必须在这里再试修复。
        repaired, repair_error = _repair_legacy_market_archive(
            inst, entry, plugin_id, download_url)
        if repair_error:
            return _fail(repair_error, 502)
        if repaired is None:
            return _fail(result.get("message") or "插件安装失败", 502)
        return _ok(
            repaired.get("data", repaired),
            "插件包缺少 metadata，已按市场信息补齐后安装")
    return _ok(result.get("data", result), result.get("message", "安装请求已完成"))


@app.post("/api/data/open")
def open_data_dir():
    """在资源管理器中打开统一数据目录。"""
    try:
        store.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(store.DATA_DIR))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(store.DATA_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(store.DATA_DIR)])
        return _ok({"path": str(store.DATA_DIR)})
    except Exception as exc:  # noqa: BLE001
        return _fail(f"打开失败：{exc}", 500)


# --------------------------------------------------------------- settings


@app.get("/api/settings")
def get_settings():
    return _ok(_settings())


@app.put("/api/settings")
def put_settings(payload: dict = Body(...)):
    return _ok(save_settings(payload), "设置已保存")


# ---------------------------------------------------------------- plugins


def _plugin_view(item: dict) -> dict:
    return {
        "id": item.get("id") or item.get("name") or "",
        "name": item.get("name") or item.get("id") or "",
        "display_name": item.get("display_name") or item.get("name") or "",
        "version": item.get("version") or "",
        "enabled": bool(item.get("activated", item.get("enabled", False))),
        "desc": item.get("desc") or "",
        "author": item.get("author") or "",
    }


def _plugin_id(plugin_id: str) -> str:
    return urllib.parse.quote(plugin_id, safe="")


@app.get("/api/instances/{inst_id}/plugins")
def instance_plugins(inst_id: str):
    inst = _require(_instances(), inst_id)
    try:
        payload = dashboard.call(inst, "GET", "plugins", timeout=30)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    plugins = [_plugin_view(p) for p in _list_data(payload) if isinstance(p, dict)]
    plugins.sort(key=lambda p: str(p.get("display_name") or p.get("name") or "").lower())
    return _ok(plugins)


@app.patch("/api/instances/{inst_id}/plugins/{plugin_id}/enabled")
def set_plugin_enabled(inst_id: str, plugin_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    enabled = bool(payload.get("enabled"))
    try:
        result = dashboard.call(
            inst,
            "PATCH",
            f"plugins/{_plugin_id(plugin_id)}/enabled",
            {"enabled": enabled},
            timeout=90,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok(result.get("data", result), result.get("message", "") or "已更新")


@app.post("/api/instances/{inst_id}/plugins/{plugin_id}/reload")
def reload_plugin(inst_id: str, plugin_id: str):
    inst = _require(_instances(), inst_id)
    try:
        result = dashboard.call(
            inst, "POST", f"plugins/{_plugin_id(plugin_id)}/reload", timeout=120
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok(result.get("data", result), result.get("message", "") or "已重载")


@app.delete("/api/instances/{inst_id}/plugins/{plugin_id}")
def uninstall_plugin(inst_id: str, plugin_id: str):
    inst = _require(_instances(), inst_id)
    try:
        result = dashboard.call(
            inst,
            "DELETE",
            "plugins/by-id",
            query={"plugin_id": plugin_id},
            timeout=180,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok(result.get("data", result), result.get("message", "") or "已卸载")


@app.post("/api/instances/{inst_id}/plugins/install")
def install_plugin(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    repository = str(payload.get("repository") or "").strip()
    url = str(payload.get("url") or "").strip()
    download_url = str(payload.get("download_url") or "").strip()
    if not repository and not url and not download_url:
        return _fail("请填写 GitHub 仓库地址或下载直链")
    try:
        if repository:
            body = {
                "url": repository,
                "ignore_version_check": True,
                "proxy": "",
            }
            if download_url:
                body["download_url"] = download_url
            result = dashboard.call(
                inst, "POST", "plugins/install/github", body, timeout=600
            )
        else:
            body = {
                "url": url,
                "download_url": download_url,
                "ignore_version_check": True,
                "proxy": "",
            }
            result = dashboard.call(inst, "POST", "plugins/install/url", body, timeout=600)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    if isinstance(result, dict) and result.get("status") == "error":
        return _fail(result.get("message") or "插件安装失败", 502)
    return _ok(result.get("data", result), result.get("message", "安装请求已完成"))


@app.post("/api/instances/{inst_id}/plugins/upload")
async def upload_plugin(inst_id: str, request: Request):
    inst = _require(_instances(), inst_id)
    body = await request.body()
    if not body:
        return _fail("没有收到文件内容")
    content_type = request.headers.get("content-type") or "multipart/form-data"
    try:
        result = dashboard.upload_raw(
            inst, "plugins/install/upload", body, content_type, timeout=600
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    if isinstance(result, dict) and result.get("status") == "error":
        return _fail(result.get("message") or "插件安装失败", 502)
    return _ok(result.get("data", result), result.get("message", "安装请求已完成"))


@app.get("/api/instances/{inst_id}/plugins/{plugin_id}/config")
def plugin_config(inst_id: str, plugin_id: str):
    inst = _require(_instances(), inst_id)
    try:
        result = dashboard.call(
            inst,
            "GET",
            "plugins/config",
            query={"plugin_id": plugin_id},
            timeout=30,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    data = result.get("data") if isinstance(result, dict) else None
    data = data or {}
    return _ok(
        {
            "plugin_name": data.get("plugin_name") or plugin_id,
            "config": data.get("config") or {},
            "metadata": data.get("metadata") or {},
        }
    )


@app.put("/api/instances/{inst_id}/plugins/{plugin_id}/config")
def save_plugin_config(inst_id: str, plugin_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    config = payload.get("config")
    if not isinstance(config, dict):
        return _fail("config 必须是对象")
    try:
        result = dashboard.call(
            inst,
            "PUT",
            "plugins/config",
            {"plugin_id": plugin_id, "config": config},
            timeout=120,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok(result.get("data", result), result.get("message", "") or "配置已保存")


# --------------------------------------------------------------- thinking


def _profile_config(inst: dict) -> dict:
    profile = dashboard.call(inst, "GET", "config-profiles/default", timeout=20)
    return (profile.get("data") or {}).get("config") or {}


def _current_provider(inst: dict) -> str:
    config = _profile_config(inst)
    runner = config.get("agent_runner") or {}
    model = (runner.get("config") or {}).get("model") or {}
    return str(model.get("provider_id") or "")


@app.get("/api/instances/{inst_id}/thinking")
def get_thinking(inst_id: str):
    inst = _require(_instances(), inst_id)
    try:
        providers = [
            p
            for p in _list_data(dashboard.call(inst, "GET", "providers", timeout=20))
            if isinstance(p, dict) and p.get("provider_type") == "chat_completion"
        ]
        config = _profile_config(inst)
        runner = config.get("agent_runner") or {}
        model = (runner.get("config") or {}).get("model") or {}
        current = str(model.get("provider_id") or "")
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)

    items = []
    for provider in providers:
        provider_id = str(provider.get("id") or "")
        effort = ""
        try:
            detail = dashboard.call(
                inst,
                "GET",
                "providers/by-id",
                query={"provider_id": provider_id, "merged": "true"},
                timeout=20,
            )
            data = detail.get("data") or {}
            extra = (data.get("provider") or {}).get("custom_extra_body") or {}
            if isinstance(extra, dict):
                effort = str(extra.get("reasoning_effort") or "")
        except dashboard.DashboardError:
            effort = ""
        items.append(
            {"id": provider_id, "model": provider.get("model") or "", "effort": effort}
        )
    return _ok({"current": current, "providers": items})


@app.put("/api/instances/{inst_id}/thinking")
def set_thinking(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    provider_id = str(payload.get("provider_id") or "").strip()
    effort = str(payload.get("effort") or "").strip()
    if not provider_id:
        return _fail("缺少 provider_id")
    if effort not in {"", "low", "medium", "high"}:
        return _fail("effort 只能是空、low、medium 或 high")
    try:
        detail = dashboard.call(
            inst,
            "GET",
            "providers/by-id",
            query={"provider_id": provider_id, "merged": "true"},
            timeout=30,
        )
        provider = (detail.get("data") or {}).get("provider") or {}
        if not provider:
            return _fail(f"模型服务不存在：{provider_id}")
        extra = dict(provider.get("custom_extra_body") or {})
        if effort:
            extra["reasoning_effort"] = effort
        else:
            extra.pop("reasoning_effort", None)
        if extra:
            provider["custom_extra_body"] = extra
        else:
            provider.pop("custom_extra_body", None)
        dashboard.call(
            inst,
            "PUT",
            "providers/by-id",
            {"provider_id": provider_id, "config": provider},
            timeout=60,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({"provider_id": provider_id, "effort": effort}, "推理强度已更新")


# --------------------------------------------------------------- providers

_PROVIDER_TYPES = {
    "openai_chat_completion": "openai",
    "anthropic_chat_completion": "anthropic",
    "googlegenai_chat_completion": "google",
}
_PROVIDER_TYPE_ALIAS = {
    "openai": "openai_chat_completion",
    "openai_chat_completion": "openai_chat_completion",
    "anthropic": "anthropic_chat_completion",
    "anthropic_chat_completion": "anthropic_chat_completion",
    "google": "googlegenai_chat_completion",
    "gemini": "googlegenai_chat_completion",
    "googlegenai_chat_completion": "googlegenai_chat_completion",
}


def _is_chat_provider(provider: dict) -> bool:
    provider_type = str(provider.get("provider_type") or "")
    if provider_type:
        return provider_type == "chat_completion"
    return "chat_completion" in str(provider.get("type") or "")


def _provider_keys(provider: dict) -> list[str]:
    keys = provider.get("key")
    if isinstance(keys, str):
        keys = [keys]
    return [str(item).strip() for item in (keys or []) if str(item or "").strip()]


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "••••"
    return f"{key[:3]}••••{key[-4:]}"


def _provider_view(provider: dict, current: str = "") -> dict:
    provider_id = str(provider.get("id") or "")
    keys = _provider_keys(provider)
    extra = provider.get("custom_extra_body")
    effort = ""
    if isinstance(extra, dict):
        effort = str(extra.get("reasoning_effort") or "")
    return {
        "id": provider_id,
        "model": str(provider.get("model") or ""),
        "type": str(provider.get("type") or ""),
        "provider_type": str(provider.get("provider_type") or ""),
        "enable": bool(provider.get("enable", True)),
        "api_base": str(provider.get("api_base") or ""),
        "has_key": bool(keys),
        "key_masked": _mask_key(keys[0]) if keys else "",
        "timeout": provider.get("timeout") or 120,
        "proxy": str(provider.get("proxy") or ""),
        "effort": effort,
        "source_id": str(provider.get("provider_source_id") or ""),
        "current": provider_id == current,
    }


def _provider_detail(inst: dict, provider_id: str, merged: bool = True) -> dict:
    detail = dashboard.call(
        inst,
        "GET",
        "providers/by-id",
        query={"provider_id": provider_id, "merged": "true" if merged else "false"},
        timeout=30,
    )
    return (detail.get("data") or {}).get("provider") or {}


def _provider_exists(inst: dict, provider_id: str) -> bool:
    for provider in _list_data(dashboard.call(inst, "GET", "providers", timeout=30)):
        if isinstance(provider, dict) and provider.get("id") == provider_id:
            return True
    return False


@app.get("/api/instances/{inst_id}/providers")
def list_model_providers(inst_id: str):
    inst = _require(_instances(), inst_id)
    try:
        current = _current_provider(inst)
        providers = [
            p
            for p in _list_data(dashboard.call(inst, "GET", "providers", timeout=30))
            if isinstance(p, dict) and _is_chat_provider(p)
        ]
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({
        "current": current,
        "providers": [_provider_view(p, current) for p in providers],
    })


@app.post("/api/instances/{inst_id}/providers")
def create_model_provider(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    provider_id = str(payload.get("id") or "").strip()
    model = str(payload.get("model") or "").strip()
    api_base = str(payload.get("api_base") or "").strip()
    if not provider_id:
        return _fail("请填写模型 ID")
    if len(provider_id) > 64 or any(ch in provider_id for ch in "/?#"):
        return _fail("模型 ID 不能包含 / ? #，且不超过 64 字")
    if not model:
        return _fail("请填写模型名称")
    if not api_base:
        return _fail("请填写 API Base")
    type_key = str(payload.get("type") or payload.get("provider_type") or "openai").strip()
    provider_type = _PROVIDER_TYPE_ALIAS.get(type_key)
    if not provider_type:
        return _fail("暂不支持该服务商类型")
    try:
        timeout = int(payload.get("timeout") or 120)
    except (TypeError, ValueError):
        timeout = 120
    timeout = max(5, min(timeout, 600))
    effort = str(payload.get("effort") or "")
    if effort not in {"", "low", "medium", "high"}:
        effort = ""
    key = str(payload.get("key") or "").strip()
    config = {
        "id": provider_id,
        "type": provider_type,
        "provider_type": "chat_completion",
        "provider": _PROVIDER_TYPES[provider_type],
        "key": [key] if key else [],
        "api_base": api_base,
        "model": model,
        "timeout": timeout,
        "proxy": str(payload.get("proxy") or "").strip(),
        "custom_headers": {},
        "enable": True,
    }
    if effort:
        config["custom_extra_body"] = {"reasoning_effort": effort}
    try:
        if _provider_exists(inst, provider_id):
            return _fail(f"模型 ID 已存在：{provider_id}")
        dashboard.call(inst, "POST", "providers", {"config": config}, timeout=60)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({"id": provider_id}, f"模型 {provider_id} 已添加")


@app.put("/api/instances/{inst_id}/providers/{provider_id}")
def update_model_provider(inst_id: str, provider_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        raw = _provider_detail(inst, provider_id, merged=False)
        merged = _provider_detail(inst, provider_id, merged=True)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    if not raw:
        return _fail(f"模型服务不存在：{provider_id}", 404)

    new_id = str(payload.get("id") or provider_id).strip()
    if new_id != provider_id:
        if len(new_id) > 64 or any(ch in new_id for ch in "/?#"):
            return _fail("模型 ID 不能包含 / ? #，且不超过 64 字")
        try:
            if _provider_exists(inst, new_id):
                return _fail(f"模型 ID 已存在：{new_id}")
        except dashboard.DashboardError as exc:
            return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    raw["id"] = new_id

    if "model" in payload:
        model = str(payload.get("model") or "").strip()
        if not model:
            return _fail("模型名称不能为空")
        raw["model"] = model

    if "api_base" in payload:
        api_base = str(payload.get("api_base") or "").strip()
        if api_base != str(merged.get("api_base") or ""):
            if not api_base:
                return _fail("API Base 不能为空")
            raw["api_base"] = api_base

    key = str(payload.get("key") or "").strip()
    if key:
        raw["key"] = [key]

    if "timeout" in payload:
        try:
            timeout = int(payload.get("timeout") or 120)
        except (TypeError, ValueError):
            timeout = 120
        timeout = max(5, min(timeout, 600))
        if timeout != (merged.get("timeout") or 120):
            raw["timeout"] = timeout

    if "proxy" in payload:
        proxy = str(payload.get("proxy") or "").strip()
        if proxy != str(merged.get("proxy") or ""):
            raw["proxy"] = proxy

    if "effort" in payload:
        effort = str(payload.get("effort") or "")
        if effort not in {"", "low", "medium", "high"}:
            return _fail("推理强度只能是空、low、medium 或 high")
        extra = dict(raw.get("custom_extra_body") or {})
        if effort:
            extra["reasoning_effort"] = effort
        else:
            extra.pop("reasoning_effort", None)
        if extra:
            raw["custom_extra_body"] = extra
        else:
            raw.pop("custom_extra_body", None)

    if "enabled" in payload:
        enabled = bool(payload.get("enabled"))
        if not enabled and provider_id == _current_provider(inst):
            return _fail("这是当前正在使用的模型，请先切换其他模型再禁用")
        raw["enable"] = enabled

    try:
        dashboard.call(
            inst,
            "PUT",
            "providers/by-id",
            {"provider_id": provider_id, "config": raw},
            timeout=60,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({"id": new_id}, f"模型 {new_id} 已保存")


@app.delete("/api/instances/{inst_id}/providers/{provider_id}")
def delete_model_provider(inst_id: str, provider_id: str):
    inst = _require(_instances(), inst_id)
    try:
        if not _provider_detail(inst, provider_id, merged=False):
            return _fail(f"模型服务不存在：{provider_id}", 404)
        current = _current_provider(inst)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    if provider_id == current:
        return _fail("这是当前正在使用的模型，请先切换到其他模型再删除")
    try:
        dashboard.call(
            inst,
            "DELETE",
            "providers/by-id",
            query={"provider_id": provider_id},
            timeout=60,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({"id": provider_id}, f"模型 {provider_id} 已删除")


@app.patch("/api/instances/{inst_id}/providers/{provider_id}/enabled")
def toggle_model_provider(inst_id: str, provider_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    enabled = bool(payload.get("enabled"))
    try:
        if not _provider_detail(inst, provider_id, merged=False):
            return _fail(f"模型服务不存在：{provider_id}", 404)
        if not enabled and provider_id == _current_provider(inst):
            return _fail("这是当前正在使用的模型，请先切换其他模型再禁用")
        dashboard.call(
            inst,
            "PATCH",
            "providers/enabled",
            {"provider_id": provider_id, "enabled": enabled},
            timeout=60,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({"id": provider_id, "enabled": enabled}, "已启用" if enabled else "已禁用")


@app.post("/api/instances/{inst_id}/providers/{provider_id}/test")
def test_model_provider(inst_id: str, provider_id: str):
    inst = _require(_instances(), inst_id)
    try:
        result = dashboard.call(
            inst,
            "POST",
            "providers/test",
            {"provider_id": provider_id},
            timeout=90,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        data = {"status": "unavailable", "error": "模型未返回测试结果"}
    message = "连接正常" if data.get("status") == "available" else (
        "连接失败：" + str(data.get("error") or "未知错误")
    )
    return _ok(data, message)


@app.post("/api/instances/{inst_id}/providers/{provider_id}/current")
def set_current_model_provider(inst_id: str, provider_id: str):
    inst = _require(_instances(), inst_id)
    try:
        provider = _provider_detail(inst, provider_id, merged=True)
        if not provider:
            return _fail(f"模型服务不存在：{provider_id}", 404)
        if not provider.get("enable", True):
            return _fail("该模型已禁用，请先启用")
        config = _profile_config(inst)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    config = dict(config)
    runner = config.get("agent_runner")
    runner = dict(runner) if isinstance(runner, dict) else {}
    runner_config = runner.get("config")
    runner_config = dict(runner_config) if isinstance(runner_config, dict) else {}
    model = runner_config.get("model")
    model = dict(model) if isinstance(model, dict) else {}
    if model.get("provider_id") == provider_id:
        return _ok({"provider_id": provider_id}, "已经是当前模型")
    model["provider_id"] = provider_id
    runner_config["model"] = model
    runner["config"] = runner_config
    config["agent_runner"] = runner
    try:
        dashboard.call(
            inst,
            "PUT",
            "config-profiles/default",
            config,
            timeout=90,
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({"provider_id": provider_id}, f"已切换为 {provider_id}")


def _think_params(inst: dict, payload: dict):
    """校验思考请求，返回 (provider_id, messages, max_tokens, 错误消息)。"""
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return "", [], 0, "请先输入一个让模型思考的问题"
    if len(prompt) > 8000:
        return "", [], 0, "问题太长了，请控制在 8000 字以内"
    provider_id = str(payload.get("provider_id") or "").strip()
    if not provider_id:
        try:
            provider_id = _current_provider(inst)
        except dashboard.DashboardError as exc:
            return "", [], 0, exc.message
    if not provider_id:
        return "", [], 0, "没有可用的对话模型，请先在「模型服务」中选择默认模型"
    try:
        max_tokens = int(payload.get("max_tokens") or 8000)
    except (TypeError, ValueError):
        max_tokens = 8000
    max_tokens = max(256, min(max_tokens, 16000))
    system = str(payload.get("system_prompt") or "").strip()
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return provider_id, messages, max_tokens, ""


@app.post("/api/instances/{inst_id}/think/stream")
def think_stream(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    provider_id, messages, max_tokens, error = _think_params(inst, payload)
    if error:
        return _fail(error)
    try:
        events = llm.chat_stream(
            inst, provider_id, messages, max_tokens=max_tokens, timeout=300
        )
    except llm.LLMError as exc:
        return _fail(exc.message, 502)

    def emit():
        try:
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except llm.LLMError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': exc.message}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        emit(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# -------------------------------------------------------------- live think


def _match_instance(instances: list[dict], source: str) -> dict | None:
    """按插件上报的 AstrBot 根目录定位实例。"""
    raw = (source or "").strip()
    if not raw:
        return None
    try:
        target = str(Path(raw).resolve()).lower()
    except Exception:  # noqa: BLE001
        target = raw.lower()
    for inst in instances:
        root = str(inst.get("root") or "")
        if not root:
            continue
        try:
            norm = str(Path(root).resolve()).lower()
        except Exception:  # noqa: BLE001
            norm = root.lower()
        if norm == target:
            return inst
    return None


@app.get("/api/live-think/ping")
def live_think_ping():
    return _ok({"app": "astrbot-manager", "runs": len(live_think.hub.recent(40))})


@app.post("/api/live-think/ingest")
def live_think_ingest(payload: dict = Body(...)):
    source = str(payload.get("source") or "").strip()
    inst = _match_instance(_instances(), source)
    snap = live_think.hub.ingest(
        payload,
        instance_id=str(inst.get("id") or "") if inst else "",
        instance_name=str(inst.get("name") or "") if inst else "",
    )
    return _ok({"run_id": snap["run_id"]})


@app.get("/api/live-think/recent")
def live_think_recent(limit: int = Query(20)):
    runs = live_think.hub.recent(limit)
    colors = {i.get("id"): i.get("color") for i in _instances()}
    for run in runs:
        run["color"] = colors.get(run.get("instance_id")) or "#5b8cff"
    return _ok({"runs": runs})


@app.post("/api/live-think/clear")
def live_think_clear():
    return _ok({"cleared": live_think.hub.clear()})


@app.get("/api/live-think/stream")
def live_think_stream():
    sub = live_think.hub.subscribe()
    return StreamingResponse(
        live_think.hub.stream(sub),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------ learn


@app.get("/api/instances/{inst_id}/learn/sources")
def learn_sources(inst_id: str):
    inst = _require(_instances(), inst_id)
    try:
        return _ok(learn.list_sources(inst))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"读取聊天记录失败：{exc}", 500)


@app.post("/api/instances/{inst_id}/learn/sample")
def learn_sample(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    source = str(payload.get("source") or "").strip()
    key = str(payload.get("key") or "").strip()
    speaker = str(payload.get("speaker") or "").strip()
    limit = payload.get("limit", 200)
    if source not in {"qq", "bili"}:
        return _fail("source 只能是 qq 或 bili")
    if not key:
        return _fail("缺少 key")
    try:
        messages = learn.sample(inst, source, key, speaker, limit)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"抽样失败：{exc}", 500)
    return _ok({"messages": messages, "count": len(messages)})


SUMMARY_SYSTEM = "你是语言风格分析助手，只根据聊天记录做归纳，不要编造。"


@app.post("/api/instances/{inst_id}/learn/summarize")
def learn_summarize(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    source = str(payload.get("source") or "").strip()
    key = str(payload.get("key") or "").strip()
    speaker = str(payload.get("speaker") or "").strip()
    limit = payload.get("limit", 200)
    if source not in {"qq", "bili"} or not key:
        return _fail("请先选择要学习的聊天记录来源")
    try:
        messages = learn.sample(inst, source, key, speaker, limit)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"抽样失败：{exc}", 500)
    if not messages:
        return _fail("没有抽到可用的聊天记录，换一个来源或减少过滤条件试试")

    provider_id = str(payload.get("provider_id") or "").strip()
    if not provider_id:
        try:
            provider_id = _current_provider(inst)
        except dashboard.DashboardError as exc:
            return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    if not provider_id:
        return _fail("没有可用的对话模型，请先在「模型与人格」设置默认模型")

    target = speaker or "该会话中的成员"
    lines = [f"{m['sender']}：{m['text']}" for m in messages]
    transcript = "\n".join(lines)
    if len(transcript) > 6000:
        transcript = transcript[:6000]
    prompt = (
        f"目标：学习「{target}」的说话风格，供另一个 AI 模仿。\n"
        f"以下是聊天记录（每行「昵称：内容」）：\n{transcript}\n\n"
        "要求：只依据上述记录，输出 Markdown，包含以下六个小节：\n"
        "## 语言风格\n## 口头禅与语气词\n## 标点与表情习惯\n## 话题偏好\n"
        "## 情绪与互动方式\n## 可直接用于风格档案的说明\n"
        "最后一节用 150-250 字，写成可以直接放入系统提示词的中文说明。"
    )
    try:
        note = llm.chat(
            inst,
            provider_id,
            [
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=8000,
            timeout=300,
        )
    except llm.LLMError as exc:
        return _fail(exc.message, 502)

    saved_style = None
    appended = False
    save_error = ""
    if payload.get("save"):
        name = str(payload.get("name") or "").strip() or "手动学习风格"
        scope = str(payload.get("scope") or "instance")
        person_key = str(payload.get("person_key") or "").strip()
        problem = learn_auto.note_problem(note)
        if problem:
            save_error = f"学习笔记未通过校验，未保存：{problem}"
        else:
            try:
                saved_style, appended = _save_manual_style_note(
                    inst, name, note, scope, person_key)
            except styles.StyleError as exc:
                save_error = str(exc)
    return _ok({
        "note": note,
        "sampled": len(messages),
        "provider_id": provider_id,
        "saved": bool(saved_style),
        "appended": appended,
        "style": saved_style,
        "save_error": save_error,
    })


def _save_manual_style_note(inst: dict, name: str, note: str,
                            scope: str, person_key: str) -> tuple[dict, bool]:
    """手动学习落库：同名同作用域档案追加，第一次才新建。"""
    existing = next(
        (
            item
            for item in styles.list_styles(str(inst.get("id")))
            if str(item.get("source") or "") == "manual"
            and str(item.get("name") or "") == name
            and str(item.get("scope") or "instance") == scope
            and str(item.get("person_key") or "") == person_key
        ),
        None,
    )
    if existing and existing.get("id"):
        return styles.append_style_note(
            str(existing["id"]), note, label="手动学习"), True
    return styles.save_style(
        str(inst.get("id")), name, note, scope=scope,
        person_key=person_key, source="manual",
    ), False


@app.post("/api/instances/{inst_id}/learn/apply")
def learn_apply(inst_id: str, payload: dict = Body(...)):
    """把手动学习笔记追加到同名风格档案；第一次新建，不改人格。"""
    inst = _require(_instances(), inst_id)
    note = str(payload.get("note") or "").strip()
    name = str(payload.get("name") or "").strip() or "手动学习风格"
    scope = str(payload.get("scope") or "instance")
    person_key = str(payload.get("person_key") or "").strip()
    if not note:
        return _fail("学习笔记不能为空")
    try:
        style, appended = _save_manual_style_note(inst, name, note, scope, person_key)
    except styles.StyleError as exc:
        return _fail(str(exc), 400)
    return _ok({"style": style, "persona_unchanged": True, "appended": appended},
               "已追加到风格档案（不写人格）" if appended else "已新建风格档案（不写人格）")


# --------------------------------------------------------- style profiles


@app.get("/api/instances/{inst_id}/styles")
def styles_list(inst_id: str):
    _require(_instances(), inst_id)
    return _ok(styles.list_styles(inst_id))


@app.post("/api/instances/{inst_id}/styles")
def styles_create(inst_id: str, payload: dict = Body(...)):
    _require(_instances(), inst_id)
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        return _fail("enabled 必须是布尔值")
    try:
        item = styles.save_style(
            inst_id,
            payload.get("name", ""),
            payload.get("note", ""),
            scope=payload.get("scope", "instance"),
            person_key=payload.get("person_key", ""),
            source="manual",
            enabled=enabled,
        )
    except styles.StyleError as exc:
        return _fail(str(exc), 400)
    return _ok(item)


@app.patch("/api/instances/{inst_id}/styles/{style_id}")
def styles_update(inst_id: str, style_id: str, payload: dict = Body(...)):
    _require(_instances(), inst_id)
    current = styles.get_style(style_id)
    if not current or str(current.get("instance_id") or "") != inst_id:
        return _fail("风格档案不存在", 404)
    try:
        return _ok(styles.update_style(style_id, payload))
    except styles.StyleError as exc:
        return _fail(str(exc), 400)


@app.delete("/api/instances/{inst_id}/styles/{style_id}")
def styles_delete(inst_id: str, style_id: str):
    _require(_instances(), inst_id)
    current = styles.get_style(style_id)
    if not current or str(current.get("instance_id") or "") != inst_id:
        return _fail("风格档案不存在", 404)
    return _ok({"deleted": styles.delete_style(style_id)})


@app.post("/api/instances/{inst_id}/styles/migrate-persona")
def styles_migrate_persona(inst_id: str, payload: dict = Body(...)):
    """剥离人格里的旧自动学习块并存成风格档案；先存档案，清人格失败则回滚。"""
    inst = _require(_instances(), inst_id)
    persona_id = str(payload.get("persona_id") or "").strip()
    if not persona_id:
        return _fail("请选择人格")
    name = str(payload.get("name") or "").strip() or "旧人格自动学习"
    try:
        old = persona_mod.current_prompt(inst, persona_id)
        blocks = persona_mod.extract_auto_blocks(old)
        if not blocks:
            return _fail("该人格没有自动学习块")
        parts = []
        for block in blocks:
            text = block.replace(persona_mod.AUTO_BEGIN, "").replace(persona_mod.AUTO_END, "")
            text = text.replace("## 自动学习到的说话风格", "").strip()
            if text:
                parts.append(text)
        note = "\n\n".join(parts)
        if not note:
            return _fail("自动学习块为空")
        style = styles.save_style(inst_id, name, note, source="migration")
        try:
            cleared = persona_mod.clear_auto_block(inst, persona_id)
        except Exception:
            styles.delete_style(style["id"])
            raise
        if not (isinstance(cleared, dict) and cleared.get("removed")):
            styles.delete_style(style["id"])
            return _fail("人格里的自动学习块已不存在，本次迁移已撤销")
    except (styles.StyleError, dashboard.DashboardError) as exc:
        return _fail(str(exc), 400)
    # 迁移前后的人格字数由前端直接展示，避免再拉一次人格详情。
    after_chars = cleared.get("chars")
    return _ok(
        {
            "style": style,
            "persona_id": persona_id,
            "persona_unchanged": False,
            "auto_block_removed": bool(cleared.get("removed")),
            "before_chars": len(old),
            "after_chars": int(after_chars) if isinstance(after_chars, (int, float)) else 0,
        },
        "已剥离人格自动学习块并保存为风格档案",
    )


# ------------------------------------------------------- persona workbench


def _workbench_payload(inst: dict, persona_id: str) -> dict:
    prompt = persona_mod.current_prompt(inst, persona_id)
    return {
        "persona_id": persona_id,
        "prompt": prompt,
        "chars": len(prompt),
        "outline": persona_mod.outline(prompt),
        "auto_learn": persona_mod.auto_learn_state(prompt),
        "versions": persona_mod.list_versions(inst, persona_id),
    }


@app.get("/api/instances/{inst_id}/personas/workbench")
def workbench_get(inst_id: str, persona_id: str = Query("")):
    inst = _require(_instances(), inst_id)
    try:
        if not persona_id:
            persona_id = persona_mod.default_persona_id(inst)
            if not persona_id:
                return _ok({"personas": [], "empty": True})
        return _ok(
            {
                "personas": persona_mod.list_personas(inst),
                **_workbench_payload(inst, persona_id),
            }
        )
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)


@app.put("/api/instances/{inst_id}/personas/workbench")
def workbench_save(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    persona_id = str(payload.get("persona_id") or "").strip()
    prompt = str(payload.get("prompt") or "")
    label = str(payload.get("label") or "").strip() or "手动保存"
    if not persona_id:
        return _fail("缺少 persona_id")
    if not prompt.strip():
        return _fail("人格提示词不能为空")
    try:
        result = persona_mod.save(inst, persona_id, prompt, label)
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({**result, **_workbench_payload(inst, persona_id)}, "已保存（原内容已快照）")


@app.post("/api/instances/{inst_id}/personas/workbench/import")
def workbench_import(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    persona_id = str(payload.get("persona_id") or "").strip()
    text = str(payload.get("text") or "")
    preserve = bool(payload.get("preserve_auto", True))
    if not persona_id:
        return _fail("缺少 persona_id")
    try:
        result = persona_mod.import_text(inst, persona_id, text, preserve)
    except persona_mod.PersonaError as exc:
        return _fail(str(exc))
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    note = "已导入" + ("（自动学习块已保留并追加）" if result["auto_learn_kept"] else "")
    return _ok({**result, **_workbench_payload(inst, persona_id)}, note)


@app.post("/api/instances/{inst_id}/personas/workbench/restore")
def workbench_restore(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    persona_id = str(payload.get("persona_id") or "").strip()
    try:
        ts_ms = int(payload.get("ts") or 0)
    except (TypeError, ValueError):
        return _fail("版本号不正确")
    if not persona_id or not ts_ms:
        return _fail("缺少 persona_id 或版本号")
    try:
        result = persona_mod.restore(inst, persona_id, ts_ms)
    except persona_mod.PersonaError as exc:
        return _fail(str(exc))
    except dashboard.DashboardError as exc:
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _ok({**result, **_workbench_payload(inst, persona_id)}, "已恢复到该版本")


# 旧 `personas/workbench/clear-auto` 路由已移除：只保留 migrate-persona，
# 确保剥离自动学习块时必须先归档成风格档案，不会丢失内容。


# ------------------------------------------------------------- auto learn


@app.get("/api/auto-learn")
def auto_learn_list():
    return _ok(learn_auto.auto_learn.snapshot())


@app.put("/api/auto-learn/{inst_id}")
def auto_learn_update(inst_id: str, payload: dict = Body(...)):
    _require(_instances(), inst_id)
    try:
        cfg = learn_auto.auto_learn.update(inst_id, payload)
    except ValueError as exc:
        return _fail(str(exc))
    return _ok(cfg, "已保存")


@app.post("/api/auto-learn/{inst_id}/run")
def auto_learn_run(inst_id: str, payload: dict | None = Body(None)):
    _require(_instances(), inst_id)
    dry_run = bool((payload or {}).get("dry_run"))
    started = learn_auto.auto_learn.trigger(inst_id, force=True, dry_run=dry_run)
    if not started:
        return _ok({"started": False, "dry_run": dry_run}, "正在学习中，请稍候")
    if dry_run:
        return _ok({"started": True, "dry_run": True}, "已开始试学，本轮只预览，不保存风格档案")
    return _ok({"started": True, "dry_run": False}, "已开始学习，完成后会保存为风格档案（不写人格）")


# ------------------------------------------- dafeiyu insight / corrections


def _insight_instance(inst_id: str):
    return _require(_instances(), inst_id)


@app.get("/api/instances/{inst_id}/insight/traces")
def insight_traces(inst_id: str, limit: int = Query(30), keyword: str = Query("")):
    inst = _insight_instance(inst_id)
    return _ok(insight_mod.traces(inst, limit, keyword))


@app.get("/api/instances/{inst_id}/insight/traces/{trace_id}")
def insight_trace_detail(inst_id: str, trace_id: str):
    inst = _insight_instance(inst_id)
    detail = insight_mod.trace_detail(inst, trace_id)
    if not detail:
        return _fail("这条回复轨迹不存在或已被清理", 404)
    system_prompt = str(detail.get("system_prompt") or "")
    matched = []
    for item in persona_mod.persona_prompts(inst):
        probe = str(item.get("prompt") or "").strip()[:120]
        if probe and probe in system_prompt:
            matched.append({"persona_id": item.get("persona_id"), "chars": item.get("chars")})
    detail["personas"] = matched
    return _ok(detail)


@app.get("/api/instances/{inst_id}/insight/corrections")
def insight_corrections(inst_id: str, status: str = Query("")):
    inst = _insight_instance(inst_id)
    return _ok(insight_mod.corrections(inst, status))


@app.post("/api/instances/{inst_id}/insight/corrections")
def insight_correction_add(inst_id: str, payload: dict = Body(...)):
    inst = _insight_instance(inst_id)
    try:
        return _ok(insight_mod.add_correction(inst, payload), "已加入待确认纠错队列")
    except ValueError as exc:
        return _fail(str(exc))


@app.post("/api/instances/{inst_id}/insight/corrections/{item_id}/resolve")
def insight_correction_resolve(inst_id: str, item_id: str, payload: dict = Body(...)):
    inst = _insight_instance(inst_id)
    try:
        return _ok(insight_mod.resolve_correction(inst, item_id, payload), "已处理相关记忆")
    except ValueError as exc:
        return _fail(str(exc))
    except memory.MemoryError as exc:
        return _fail(exc.message, exc.status)


@app.post("/api/instances/{inst_id}/insight/corrections/{item_id}/dismiss")
def insight_correction_dismiss(inst_id: str, item_id: str, payload: dict = Body(...)):
    inst = _insight_instance(inst_id)
    try:
        return _ok(
            insight_mod.dismiss_correction(inst, item_id, str(payload.get("note") or "")),
            "已忽略这条纠错",
        )
    except ValueError as exc:
        return _fail(str(exc))


@app.get("/api/instances/{inst_id}/insight/owner/grants")
def insight_owner_grants(inst_id: str):
    inst = _insight_instance(inst_id)
    return _ok(insight_mod.owner_grants(inst))


@app.post("/api/instances/{inst_id}/insight/owner/grants")
def insight_owner_grant(inst_id: str, payload: dict = Body(...)):
    inst = _insight_instance(inst_id)
    try:
        return _ok(insight_mod.grant_owner(inst, payload), "已授权该会话")
    except ValueError as exc:
        return _fail(str(exc))


@app.delete("/api/instances/{inst_id}/insight/owner/grants/{grant_id}")
def insight_owner_revoke(inst_id: str, grant_id: str):
    inst = _insight_instance(inst_id)
    insight_mod.revoke_owner(inst, grant_id)
    return _ok({"revoked": True}, "已撤销授权")


@app.get("/api/instances/{inst_id}/insight/sessions")
def insight_sessions(inst_id: str, limit: int = Query(12)):
    inst = _insight_instance(inst_id)
    return _ok(insight_mod.recent_sessions(inst, limit))


# ------------------------------------------------- persona candidates / gray


def _persona_fail(exc: Exception):
    if isinstance(exc, dashboard.DashboardError):
        return _fail(exc.message, exc.status if exc.status >= 400 else 502)
    return _fail(str(exc), 400)


@app.get("/api/instances/{inst_id}/personas/candidates")
def persona_candidates(inst_id: str, persona_id: str = Query("")):
    _require(_instances(), inst_id)
    return _ok(persona_mod.list_candidates(persona_id))


@app.post("/api/instances/{inst_id}/personas/candidates")
def persona_candidate_create(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        return _ok(persona_mod.create_candidate(inst, payload), "已创建候选人格")
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


@app.get("/api/instances/{inst_id}/personas/candidates/{candidate_id}")
def persona_candidate_detail(inst_id: str, candidate_id: str):
    _require(_instances(), inst_id)
    try:
        return _ok(persona_mod.get_candidate(candidate_id))
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


@app.patch("/api/instances/{inst_id}/personas/candidates/{candidate_id}")
def persona_candidate_update(inst_id: str, candidate_id: str, payload: dict = Body(...)):
    _require(_instances(), inst_id)
    try:
        return _ok(persona_mod.update_candidate(candidate_id, payload), "已保存候选人格")
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


@app.delete("/api/instances/{inst_id}/personas/candidates/{candidate_id}")
def persona_candidate_delete(inst_id: str, candidate_id: str):
    _require(_instances(), inst_id)
    return _ok({"deleted": persona_mod.delete_candidate(candidate_id)})


@app.get("/api/instances/{inst_id}/personas/candidates/{candidate_id}/diff")
def persona_candidate_diff(inst_id: str, candidate_id: str):
    inst = _require(_instances(), inst_id)
    try:
        candidate = persona_mod.get_candidate(candidate_id)
        current = persona_mod.strip_auto_block(
            persona_mod.current_prompt(inst, str(candidate.get("persona_id") or ""))
        )
        return _ok(
            {
                "candidate": candidate,
                "diff": persona_mod.diff_texts(current, str(candidate.get("prompt") or "")),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


@app.post("/api/instances/{inst_id}/personas/candidates/{candidate_id}/shadow")
def persona_candidate_shadow(inst_id: str, candidate_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        result = persona_mod.shadow_run(
            inst,
            candidate_id,
            str(payload.get("provider_id") or ""),
            payload.get("fixture_ids") or None,
        )
        return _ok(result, "影子跑分完成（未写入线上）")
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


@app.post("/api/instances/{inst_id}/personas/candidates/{candidate_id}/ab")
def persona_candidate_ab(inst_id: str, candidate_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        result = persona_mod.ab_run(
            inst,
            candidate_id,
            str(payload.get("provider_id") or ""),
            payload.get("fixture_ids") or None,
        )
        return _ok(result, "A/B 对比完成")
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


@app.post("/api/instances/{inst_id}/personas/candidates/{candidate_id}/deploy")
def persona_candidate_deploy(inst_id: str, candidate_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        result = persona_mod.deploy_candidate(
            inst,
            candidate_id,
            _instances(),
            payload.get("instances") or [],
            str(payload.get("mode") or "gray"),
        )
        return _ok(
            result,
            "已灰度上线" if result.get("mode") == "gray" else "已全量上线",
        )
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


@app.post("/api/instances/{inst_id}/personas/candidates/{candidate_id}/rollback")
def persona_candidate_rollback(inst_id: str, candidate_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        result = persona_mod.rollback_candidate(
            candidate_id, _instances(), str(payload.get("point") or "")
        )
        return _ok(result, "已回滚到上线前快照")
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


@app.get("/api/instances/{inst_id}/personas/versions/diff")
def persona_versions_diff(
    inst_id: str,
    persona_id: str = Query(""),
    a: int = Query(0),
    b: int = Query(0),
):
    inst = _require(_instances(), inst_id)
    if not persona_id:
        return _fail("缺少 persona_id")
    try:
        return _ok(persona_mod.version_diff(inst, persona_id, a, b))
    except Exception as exc:  # noqa: BLE001
        return _persona_fail(exc)


# ------------------------------------------------------------ 生活线 / 群梗 / 看图


@app.get("/api/instances/{inst_id}/life")
def life_snapshot(inst_id: str, days: int = Query(7)):
    inst = _require(_instances(), inst_id)
    try:
        return _ok(life_mod.snapshot(inst, days))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.patch("/api/instances/{inst_id}/life/settings")
def life_save_settings(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        settings = life_mod.save_settings(inst, payload)
        return _ok(settings, "生活线设置已保存")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.post("/api/instances/{inst_id}/life/events")
def life_add_event(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        event = life_mod.add_event(
            inst,
            str(payload.get("text") or ""),
            str(payload.get("kind") or "manual"),
        )
        return _ok(event, "已记入生活线")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.delete("/api/instances/{inst_id}/life/events/{event_id}")
def life_delete_event(inst_id: str, event_id: str):
    inst = _require(_instances(), inst_id)
    try:
        removed = life_mod.delete_event(inst, event_id)
        return _ok({"removed": removed}, "已删除" if removed else "没有找到这条记录")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.get("/api/instances/{inst_id}/memes")
def memes_list(inst_id: str, status: str = Query("")):
    inst = _require(_instances(), inst_id)
    try:
        return _ok(memes_mod.list_all(inst, status))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.post("/api/instances/{inst_id}/memes")
def memes_add(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        item = memes_mod.add(
            inst,
            str(payload.get("phrase") or ""),
            str(payload.get("meaning") or ""),
            str(payload.get("example") or ""),
        )
        return _ok(item, "群梗已收录")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.patch("/api/instances/{inst_id}/memes/settings")
def memes_save_settings(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        settings = memes_mod.save_settings(inst, payload)
        return _ok(settings, "群梗库设置已保存")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.post("/api/instances/{inst_id}/memes/candidates/activate")
def memes_activate_candidate(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        item = memes_mod.activate_candidate(
            inst,
            str(payload.get("phrase") or ""),
            str(payload.get("meaning") or ""),
            str(payload.get("group_id") or ""),
        )
        return _ok(item, "候选已转正")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.post("/api/instances/{inst_id}/memes/candidates/dismiss")
def memes_dismiss_candidate(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        removed = memes_mod.dismiss_candidate(
            inst, str(payload.get("phrase") or ""))
        return _ok({"dismissed": removed}, "已忽略候选")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.patch("/api/instances/{inst_id}/memes/{item_id}")
def memes_update(inst_id: str, item_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        item = memes_mod.update(inst, item_id, payload)
        return _ok(item, "群梗已更新")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.delete("/api/instances/{inst_id}/memes/{item_id}")
def memes_delete(inst_id: str, item_id: str):
    inst = _require(_instances(), inst_id)
    try:
        removed = memes_mod.delete(inst, item_id)
        return _ok({"removed": removed}, "已删除" if removed else "没有找到这条群梗")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.get("/api/instances/{inst_id}/vision")
def vision_list(inst_id: str, limit: int = Query(60)):
    inst = _require(_instances(), inst_id)
    try:
        return _ok(vision_mod.list_items(inst, limit))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.patch("/api/instances/{inst_id}/vision/settings")
def vision_save_settings(inst_id: str, payload: dict = Body(...)):
    inst = _require(_instances(), inst_id)
    try:
        settings = vision_mod.save_settings(inst, payload)
        return _ok(settings, "看图接话设置已保存")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


@app.delete("/api/instances/{inst_id}/vision/{item_id}")
def vision_delete(inst_id: str, item_id: str):
    inst = _require(_instances(), inst_id)
    try:
        removed = vision_mod.delete_item(inst, item_id)
        return _ok({"removed": removed}, "已删除" if removed else "没有找到这条记录")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


# ------------------------------------------------------------ static files


if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")


@app.get("/")
def index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/favicon.ico")
def favicon():
    icon = WEB_DIR / "assets" / "favicon.svg"
    if icon.exists():
        return FileResponse(str(icon), media_type="image/svg+xml")
    return JSONResponse({}, status_code=404)


@app.get("/manifest.webmanifest")
def manifest():
    path = WEB_DIR / "manifest.webmanifest"
    if not path.exists():
        return JSONResponse({}, status_code=404)
    return FileResponse(str(path), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    path = WEB_DIR / "sw.js"
    if not path.exists():
        return JSONResponse({}, status_code=404)
    return FileResponse(str(path), media_type="application/javascript")
