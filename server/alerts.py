"""舰队告警中心：把健康、审批、任务与备份聚合成可处理告警。"""

from __future__ import annotations

import time

from . import backup as backup_mod, fleet_store, health as health_mod

APPROVAL_AGE = 600
APPROVAL_CRITICAL_AGE = 1800
BACKUP_MAX_AGE = 48 * 3600
TASK_WINDOW = 24 * 3600


def _severity_for_status(status: str) -> str:
    return "critical" if status == "bad" else "warning"


def _health_alerts(health: dict) -> list[dict]:
    alerts = []
    for item in health.get("components") or []:
        if not isinstance(item, dict) or item.get("status") == "ok":
            continue
        alerts.append(
            {
                "id": f"health:{item.get('id')}",
                "severity": _severity_for_status(str(item.get("status"))),
                "kind": "health",
                "title": str(item.get("label") or item.get("id")),
                "summary": str(item.get("summary") or ""),
                "route": str(item.get("route") or ""),
                "ref": str(item.get("id") or ""),
            }
        )
    return alerts


def _approval_alerts(approvals: list[dict], now: float) -> list[dict]:
    alerts = []
    for item in approvals:
        if item.get("status") != "pending":
            continue
        age = max(0.0, now - float(item.get("created") or now))
        if age < APPROVAL_AGE:
            continue
        alerts.append(
            {
                "id": f"approval:{item.get('id')}",
                "severity": "critical" if age >= APPROVAL_CRITICAL_AGE else "warning",
                "kind": "approval",
                "title": f"审批等待 {int(age // 60)} 分钟：{item.get('title') or '未命名'}",
                "summary": str(item.get("target") or "未指定目标"),
                "route": "#/approvals",
                "ref": str(item.get("id") or ""),
            }
        )
    return alerts


def _task_alerts(runs: list[dict], names: dict[str, str], now: float) -> list[dict]:
    alerts = []
    seen = set()
    for run in runs:
        task_id = str(run.get("task_id") or "")
        if not task_id or task_id in seen:
            continue
        seen.add(task_id)
        started = float(run.get("started") or 0)
        if started < now - TASK_WINDOW or run.get("status") != "failed":
            continue
        alerts.append(
            {
                "id": f"task:{task_id}",
                "severity": "warning",
                "kind": "task",
                "title": f"任务失败：{names.get(task_id) or task_id}",
                "summary": str(run.get("summary") or "最近 24 小时有失败记录"),
                "route": "#/tasks",
                "ref": task_id,
            }
        )
    return alerts


def _backup_alerts(backups: list[dict], now: float) -> list[dict]:
    latest = max((float(item.get("created") or 0) for item in backups), default=0)
    if latest and now - latest < BACKUP_MAX_AGE:
        return []
    summary = "还没有任何备份" if not latest else f"最近备份在 {int((now - latest) // 3600)} 小时前"
    return [
        {
            "id": "backup:stale",
            "severity": "warning",
            "kind": "backup",
            "title": "备份超过 48 小时未更新",
            "summary": summary,
            "route": "#/settings",
            "ref": "backup",
        }
    ]


def build(health: dict, approvals: list[dict], task_runs: list[dict],
          task_names: dict[str, str], backups: list[dict], now: float | None = None) -> dict:
    current = time.time() if now is None else float(now)
    alerts = [
        *_health_alerts(health),
        *_approval_alerts(approvals, current),
        *_task_alerts(task_runs, task_names, current),
        *_backup_alerts(backups, current),
    ]
    counts = {"critical": 0, "warning": 0}
    for item in alerts:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    overall = "critical" if counts["critical"] else "warning" if counts["warning"] else "ok"
    return {
        "generated_at": current,
        "overall": overall,
        "counts": {**counts, "total": len(alerts)},
        "alerts": alerts,
    }


def _recent_runs_and_names(now: float) -> tuple[list[dict], dict[str, str]]:
    with fleet_store.session() as conn:
        rows = conn.execute(
            "SELECT task_id, started, status, summary FROM task_runs "
            "WHERE started >= ? ORDER BY started DESC",
            (now - TASK_WINDOW,),
        ).fetchall()
        names = {
            str(row["id"]): str(row["name"])
            for row in conn.execute("SELECT id, name FROM tasks").fetchall()
        }
    return [dict(row) for row in rows], names


def collect(force_health: bool = False) -> dict:
    now = time.time()
    runs, names = _recent_runs_and_names(now)
    return build(
        health_mod.collect_health(force=force_health),
        fleet_store.list_approvals(status="pending", limit=100),
        runs,
        names,
        backup_mod.list_backups(),
        now,
    )
