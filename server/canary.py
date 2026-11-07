"""只读端到端巡检：按组件计时，结果写入事件表。"""

from __future__ import annotations

import json
import time

from . import backup as backup_mod, fleet_store, health as health_mod, store
from . import tasks as tasks_mod


def _worst(rows: list[dict]) -> str:
    statuses = {str(row.get("status") or "warn") for row in rows}
    return "bad" if "bad" in statuses else "warn" if "warn" in statuses else "ok"


def _timed(check_id: str, label: str, func, route: str = "") -> list[dict]:
    started = time.perf_counter()
    try:
        result = func()
        rows = result if isinstance(result, list) else [result]
        error = ""
    except Exception as exc:  # noqa: BLE001
        rows = [health_mod.component(check_id, label, "bad", f"{type(exc).__name__}: {str(exc)[:200]}")]
        error = str(exc)[:300]
    latency = round((time.perf_counter() - started) * 1000, 1)
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "id": row.get("id") or check_id,
                "label": row.get("label") or label,
                "status": row.get("status") if row.get("status") in {"ok", "warn", "bad"} else "warn",
                "summary": str(row.get("summary") or ""),
                "latency_ms": latency,
                "route": row.get("route") or route,
                "error": error,
            }
        )
    return out


def _scheduler_check() -> dict:
    thread = getattr(tasks_mod.scheduler, "_thread", None)
    alive = bool(thread and thread.is_alive())
    return health_mod.component(
        "scheduler",
        "任务调度器",
        "ok" if alive else "warn",
        "30 秒 tick 运行中" if alive else "调度线程未运行",
        {"alive": alive},
        route="#/tasks",
    )


def _approval_check() -> dict:
    pending = fleet_store.pending_count()
    return health_mod.component(
        "approvals",
        "审批队列",
        "warn" if pending else "ok",
        f"{pending} 条待审批" if pending else "没有待审批",
        {"pending": pending},
        route="#/approvals",
    )


def _backup_check() -> dict:
    items = backup_mod.list_backups()
    latest = max((float(item.get("created") or 0) for item in items), default=0)
    age = max(0.0, time.time() - latest) if latest else None
    if latest is None:
        level, summary = "warn", "还没有备份"
    elif age > 48 * 3600:
        level, summary = "warn", f"最近备份在 {int(age // 3600)} 小时前"
    else:
        level, summary = "ok", f"最近备份在 {int(age // 60)} 分钟前"
    return health_mod.component(
        "backup",
        "备份",
        level,
        summary,
        {"latest": latest, "count": len(items), "age_seconds": age},
        route="#/settings",
    )


def run_checks(instances: list[dict] | None = None, instance_check=None,
               global_checks=None) -> dict:
    instance_check = instance_check or health_mod.check_instance
    checks: list[dict] = []
    default_global = (
        ("manager", "管理器", health_mod.check_manager, "#/settings"),
        ("dsh", "DSH", health_mod.check_dsh, "#/capDshPlugins"),
        ("market", "插件市场索引", health_mod.check_market, "#/capMarket"),
        ("disk", "数据磁盘", health_mod.check_disk, "#/settings"),
        ("scheduler", "任务调度器", _scheduler_check, "#/tasks"),
        ("approvals", "审批队列", _approval_check, "#/approvals"),
        ("backup", "备份", _backup_check, "#/settings"),
    )
    for check_id, label, func, route in (global_checks if global_checks is not None else default_global):
        checks.extend(_timed(check_id, label, func, route))
    for inst in (instances if instances is not None else store.load_instances()):
        checks.extend(_timed(
            f"instance:{inst.get('id')}",
            str(inst.get("name") or inst.get("id") or "实例"),
            lambda inst=inst: instance_check(inst),
            "#/bots",
        ))
    counts = {"ok": 0, "warn": 0, "bad": 0}
    for row in checks:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    overall = _worst(checks)
    return {
        "generated_at": time.time(),
        "overall": overall,
        "counts": {**counts, "total": len(checks)},
        "checks": checks,
    }


def run(instances: list[dict] | None = None) -> dict:
    result = run_checks(instances)
    fleet_store.add_event(
        "canary",
        "manager",
        "info" if result["overall"] == "ok" else "warn",
        f"巡检完成：{result['overall']}",
        result,
    )
    return result


def last() -> dict | None:
    with fleet_store.session() as conn:
        row = conn.execute(
            "SELECT ts, detail_json FROM events WHERE kind='canary' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["detail_json"] or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return None
    data.setdefault("generated_at", row["ts"])
    return data
