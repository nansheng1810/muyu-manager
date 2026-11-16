"""自动化注册表：内置巡检任务、一次性补种、DSH 技能接入与监控概览。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from . import fleet_store, store, tasks as tasks_mod

VERSION = "1.30.8"
DSH_CACHE_SECONDS = 15.0

# 可按 id 补种的内置任务；已有同名任务时只补齐缺失项，不覆盖用户配置。
BUILTINS = [
    {
        "id": "task_daily_backup",
        "name": "每日备份",
        "kind": "backup",
        "schedule": "03:30",
        "config": {"label": "scheduled"},
        "enabled": True,
        "group": "维护",
        "desc": "每天凌晨备份管理器、实例与 DSH 配置，保留最近若干份。",
    },
    {
        "id": "task_daily_digest",
        "name": "每日舰队日报",
        "kind": "digest",
        "schedule": "09:00",
        "config": {},
        "enabled": True,
        "group": "维护",
        "desc": "汇总前一天的健康、审批、任务与事件，写入事件流。",
    },
    {
        "id": "task_memory_sleep",
        "name": "记忆睡眠巩固",
        "kind": "memory_sleep",
        "schedule": "weekly:mon,thu",
        "config": {},
        "enabled": True,
        "group": "维护",
        "desc": "每个实例自动执行记忆睡眠；未指定 instance_id 时遍历全部实例。",
    },
    {
        "id": "task_auto_health",
        "name": "健康巡检",
        "kind": "health_patrol",
        "schedule": "every:30m",
        "config": {},
        "enabled": True,
        "group": "巡检",
        "desc": "强制刷新实例、DSH、端口与调度健康，异常写入告警与事件流。",
    },
    {
        "id": "task_auto_resources",
        "name": "资源采样",
        "kind": "resource_scan",
        "schedule": "every:60m",
        "config": {},
        "enabled": True,
        "group": "巡检",
        "desc": "记录 CPU、内存、磁盘与实例进程占用，便于回看资源趋势。",
    },
    {
        "id": "task_auto_drift",
        "name": "一致性扫描",
        "kind": "drift_scan",
        "schedule": "every:6h",
        "config": {},
        "enabled": True,
        "group": "巡检",
        "desc": "对比实例之间的插件、模型与人格差异，发现配置漂移。",
    },
    {
        "id": "task_auto_canary",
        "name": "端到端巡检",
        "kind": "canary_patrol",
        "schedule": "07:00",
        "config": {},
        "enabled": True,
        "group": "巡检",
        "desc": "只读检查登录、调度、备份与插件链路，输出整体通过率。",
    },
]
BUILTIN_IDS = {item["id"]: item for item in BUILTINS}
LEGACY_ONCE = {"task_daily_backup", "task_daily_digest", "task_memory_sleep"}

_dsh_lock = threading.Lock()
_dsh_cache: dict = {"at": 0.0, "value": None}


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def _loads(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def _marker_path(db_path=None) -> Path:
    if db_path:
        return Path(db_path).with_suffix(".automation_seeded")
    return store.DATA_DIR / "automation_defaults.json"


def _write_marker(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json({"version": VERSION, "seeded_at": time.time()}), "utf-8")
    except OSError:
        pass


def ensure_builtin(db_path=None) -> None:
    """按 id 补齐内置任务；首次升级时把从未运行过的旧种子切到安全默认。"""
    marker = _marker_path(db_path)
    first = not marker.exists()
    now = time.time()
    with fleet_store.session(db_path) as conn:
        rows = {
            str(row["id"]): row
            for row in conn.execute(
                "SELECT id, enabled, last_run FROM tasks"
            ).fetchall()
        }
        used = {
            str(row["task_id"])
            for row in conn.execute("SELECT DISTINCT task_id FROM task_runs").fetchall()
        }
        for item in BUILTINS:
            current = rows.get(item["id"])
            if current is not None:
                if (
                    first
                    and item["id"] in LEGACY_ONCE
                    and not current["enabled"]
                    and float(current["last_run"] or 0) <= 0
                    and item["id"] not in used
                ):
                    next_run = tasks_mod.next_run_at(item["schedule"], now)
                    conn.execute(
                        "UPDATE tasks SET enabled=1, next_run=?, updated=? WHERE id=?",
                        (next_run, now, item["id"]),
                    )
                continue
            enabled = bool(item["enabled"])
            next_run = tasks_mod.next_run_at(item["schedule"], now) if enabled else 0
            conn.execute(
                "INSERT INTO tasks(id, name, kind, schedule, config_json, enabled, "
                "last_run, next_run, created, updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    item["id"],
                    item["name"],
                    item["kind"],
                    item["schedule"],
                    _json(item["config"]),
                    1 if enabled else 0,
                    0,
                    next_run,
                    now,
                    now,
                ),
            )
    if first:
        _write_marker(marker)


def _dsh_state() -> dict:
    now = time.time()
    with _dsh_lock:
        cached = _dsh_cache.get("value")
        if cached and now - float(_dsh_cache.get("at") or 0) < DSH_CACHE_SECONDS:
            return dict(cached)
    value = {"running": False, "ready": False, "version": "", "skills": [], "error": ""}
    try:
        from . import dsh

        status = dsh.public_status(include_counts=False, log_lines=0)
        value.update(
            {
                "running": bool(status.get("running")),
                "ready": bool(status.get("ready")),
                "version": str(status.get("version") or ""),
                "error": str(status.get("error") or ""),
            }
        )
        if value["ready"]:
            try:
                payload = dsh.skillhub("list", timeout=8.0)
                items = payload.get("items") or []
                value["skills"] = [
                    {
                        "slug": str(item.get("slug") or ""),
                        "name": str(item.get("name") or item.get("slug") or ""),
                        "description": str(item.get("description") or ""),
                        "category": str(item.get("category") or ""),
                        "version": str(item.get("version") or ""),
                    }
                    for item in items
                    if isinstance(item, dict) and item.get("slug")
                ]
            except Exception as exc:  # noqa: BLE001
                value["error"] = f"读取已安装技能失败：{exc}"
    except Exception as exc:  # noqa: BLE001
        value["error"] = str(exc)
    with _dsh_lock:
        _dsh_cache.update({"at": now, "value": dict(value)})
    return value


def invalidate_dsh_cache() -> None:
    with _dsh_lock:
        _dsh_cache.update({"at": 0.0, "value": None})


def _events(where: str, limit: int, ascending: bool, db_path=None) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    order = "ASC" if ascending else "DESC"
    sql = f"SELECT * FROM events {where} ORDER BY id {order} LIMIT ?"
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["detail"] = _loads(item.pop("detail_json", None), {})
        out.append(item)
    return out


def logs(since: int = 0, limit: int = 80, db_path=None) -> dict:
    since = int(since or 0)
    if since > 0:
        with fleet_store.session(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE id > ? ORDER BY id ASC LIMIT ?",
                (since, max(1, min(int(limit), 200))),
            ).fetchall()
        items = []
        for row in rows:
            entry = dict(row)
            entry["detail"] = _loads(entry.pop("detail_json", None), {})
            items.append(entry)
    else:
        items = _events("", limit, False, db_path)
        items.reverse()
    return {
        "events": items,
        "last_id": int(items[-1]["id"]) if items else since,
        "server_time": time.time(),
    }


def overview(db_path=None) -> dict:
    ensure_builtin(db_path)
    now = time.time()
    tasks = tasks_mod.list_tasks(db_path)
    runs = tasks_mod.list_runs("", limit=150, db_path=db_path)
    latest: dict[str, dict] = {}
    for run in runs:
        latest.setdefault(str(run.get("task_id") or ""), run)
    window = now - 24 * 3600
    recent = [run for run in runs if float(run.get("started") or 0) >= window]
    success = sum(1 for run in recent if run.get("status") == "success")
    failed = sum(1 for run in recent if run.get("status") == "failed")
    running = sum(1 for run in recent if run.get("status") == "running")
    enabled = [task for task in tasks if task.get("enabled")]
    next_run = min(
        (float(task.get("next_run") or 0) for task in enabled if task.get("next_run")),
        default=0,
    )
    rows = []
    for task in tasks:
        meta = BUILTIN_IDS.get(task["id"]) or {}
        if meta:
            group = meta["group"]
        elif task["kind"] == "dsh_prompt":
            group = "DSH 技能"
        else:
            group = "自定义"
        rows.append(
            {
                **task,
                "builtin": bool(meta),
                "group": group,
                "desc": str(meta.get("desc") or ""),
                "last_status": str((latest.get(task["id"]) or {}).get("status") or ""),
                "last_summary": str((latest.get(task["id"]) or {}).get("summary") or ""),
            }
        )
    scheduler_alive = False
    try:
        scheduler_alive = bool(tasks_mod.scheduler.alive())
    except Exception:  # noqa: BLE001
        pass
    return {
        "version": VERSION,
        "server_time": now,
        "stats": {
            "total": len(tasks),
            "enabled": len(enabled),
            "runs_24h": len(recent),
            "success_24h": success,
            "failed_24h": failed,
            "running": running,
            "next_run": next_run,
            "scheduler_alive": scheduler_alive,
        },
        "tasks": rows,
        "runs": runs[:40],
        "events": _events("", 30, False, db_path),
        "dsh": _dsh_state(),
    }
