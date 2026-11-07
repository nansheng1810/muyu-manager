"""舰队日报：只读聚合健康、实例、审批、任务与备份。"""

from __future__ import annotations

import json
import time
from datetime import datetime

from . import backup as backup_mod, fleet_store, health as health_mod, runner as runner_mod, store

STATUS_LABEL = {"ok": "正常", "warn": "注意", "bad": "异常"}


def day_bounds(day: str | None = None, now: float | None = None) -> tuple[float, float, str]:
    current = time.time() if now is None else float(now)
    if day:
        try:
            parsed = datetime.strptime(str(day), "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("日期格式应为 YYYY-MM-DD") from exc
    else:
        parsed = datetime.fromtimestamp(current)
    start = datetime(parsed.year, parsed.month, parsed.day).timestamp()
    return start, start + 86400, parsed.strftime("%Y-%m-%d")


def _loads(value) -> dict:
    try:
        data = json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _events(start: float, end: float) -> list[dict]:
    with fleet_store.session() as conn:
        rows = conn.execute(
            "SELECT ts, kind, source, severity, title, detail_json, ref FROM events "
            "WHERE ts >= ? AND ts < ? ORDER BY ts DESC",
            (start, end),
        ).fetchall()
    return [
        {
            "ts": row["ts"],
            "kind": row["kind"],
            "source": row["source"],
            "severity": row["severity"],
            "title": row["title"],
            "detail": _loads(row["detail_json"]),
            "ref": row["ref"],
        }
        for row in rows
    ]


def _approvals(start: float, end: float) -> dict:
    with fleet_store.session() as conn:
        rows = conn.execute(
            "SELECT status, category, title, target, created, updated FROM approvals "
            "WHERE created >= ? AND created < ? ORDER BY created DESC",
            (start, end),
        ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    return {
        "total": len(rows),
        "counts": counts,
        "pending_total": fleet_store.pending_count(),
        "items": [dict(row) for row in rows[:20]],
    }


def _task_runs(start: float, end: float) -> dict:
    with fleet_store.session() as conn:
        rows = conn.execute(
            "SELECT id, task_id, started, finished, status, summary FROM task_runs "
            "WHERE started >= ? AND started < ? ORDER BY started DESC",
            (start, end),
        ).fetchall()
        names = {
            row["id"]: row["name"]
            for row in conn.execute("SELECT id, name FROM tasks").fetchall()
        }
    counts: dict[str, int] = {}
    items = []
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
        item = dict(row)
        item["task_name"] = names.get(item["task_id"], item["task_id"])
        items.append(item)
    return {
        "total": len(rows),
        "counts": counts,
        "items": items[:20],
    }


def _backups(start: float, end: float) -> dict:
    items = [item for item in backup_mod.list_backups() if start <= item.get("created", 0) < end]
    return {"total": len(items), "items": items[:10]}


def _instances() -> list[dict]:
    out = []
    for inst in store.load_instances():
        try:
            status = runner_mod.runner.status(inst)
        except Exception:  # noqa: BLE001
            status = {"running": False, "dashboard_ready": False}
        out.append(
            {
                "id": inst.get("id"),
                "name": inst.get("name") or inst.get("id"),
                "running": bool(status.get("running")),
                "dashboard_ready": bool(status.get("dashboard_ready")),
            }
        )
    return out


def _health_summary(health: dict) -> dict:
    components = [
        {
            "id": item.get("id"),
            "label": item.get("label") or item.get("id"),
            "status": item.get("status") or "warn",
            "summary": item.get("summary") or "",
            "route": item.get("route") or "",
        }
        for item in health.get("components") or []
        if isinstance(item, dict)
    ]
    counts = {"ok": 0, "warn": 0, "bad": 0}
    for item in components:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "overall": health.get("overall") or "warn",
        "generated_at": health.get("generated_at"),
        "counts": counts,
        "components": components,
    }


def build(
    day: str,
    health: dict,
    instances: list[dict],
    events: list[dict],
    approvals: dict,
    task_runs: dict,
    backups: dict,
    generated_at: float | None = None,
) -> dict:
    online = sum(1 for item in instances if item.get("running"))
    return {
        "date": day,
        "generated_at": generated_at or time.time(),
        "overall": health.get("overall") or "warn",
        "fleet": {
            "total": len(instances),
            "online": online,
            "instances": instances,
        },
        "health": health,
        "approvals": approvals,
        "tasks": task_runs,
        "backups": backups,
        "events": events[:40],
        "counts": {
            "events": len(events),
            "approvals": approvals.get("total", 0),
            "task_runs": task_runs.get("total", 0),
            "backups": backups.get("total", 0),
        },
    }


def collect(day: str | None = None, force_health: bool = False) -> dict:
    start, end, label = day_bounds(day)
    return build(
        label,
        _health_summary(health_mod.collect_health(force=force_health)),
        _instances(),
        _events(start, end),
        _approvals(start, end),
        _task_runs(start, end),
        _backups(start, end),
    )


def _time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M")
    except (TypeError, ValueError, OSError):
        return "--:--"


def markdown(data: dict) -> str:
    fleet = data.get("fleet") or {}
    health = data.get("health") or {}
    approvals = data.get("approvals") or {}
    tasks = data.get("tasks") or {}
    backups = data.get("backups") or {}
    lines = [
        f"# 舰队日报 · {data.get('date', '')}",
        "",
        f"- 总体状态：{STATUS_LABEL.get(data.get('overall'), data.get('overall') or '未知')}",
        f"- 机器人：{fleet.get('online', 0)} / {fleet.get('total', 0)} 在线",
        f"- 健康组件：正常 {health.get('counts', {}).get('ok', 0)} · 注意 {health.get('counts', {}).get('warn', 0)} · 异常 {health.get('counts', {}).get('bad', 0)}",
        f"- 审批：今日 {approvals.get('total', 0)} 条，当前待审批 {approvals.get('pending_total', 0)} 条",
        f"- 任务：今日 {tasks.get('total', 0)} 次运行，成功 {tasks.get('counts', {}).get('success', 0)} 次，失败 {tasks.get('counts', {}).get('failed', 0)} 次",
        f"- 备份：今日 {backups.get('total', 0)} 份",
        "",
        "## 机器人",
    ]
    if fleet.get("instances"):
        for item in fleet["instances"]:
            state = "在线" if item.get("running") else "离线"
            if item.get("running") and not item.get("dashboard_ready"):
                state = "进程在运行，Dashboard 未就绪"
            lines.append(f"- {item.get('name')}：{state}")
    else:
        lines.append("- 未接入实例")
    lines.extend(["", "## 健康"])
    for item in health.get("components") or []:
        lines.append(
            f"- [{STATUS_LABEL.get(item.get('status'), item.get('status'))}] "
            f"{item.get('label')}：{item.get('summary')}"
        )
    lines.extend(["", "## 审批"])
    if approvals.get("items"):
        for item in approvals["items"]:
            lines.append(
                f"- {item.get('status')} · {item.get('title')}（{item.get('target') or '未指定目标'}）"
            )
    else:
        lines.append("- 今日没有审批记录")
    lines.extend(["", "## 任务"])
    if tasks.get("items"):
        for item in tasks["items"]:
            lines.append(
                f"- {_time(item.get('started'))} {item.get('task_name')}：{item.get('status')} · {item.get('summary') or ''}"
            )
    else:
        lines.append("- 今日没有任务运行")
    lines.extend(["", "## 今日事件"])
    if data.get("events"):
        for item in data["events"]:
            lines.append(f"- {_time(item.get('ts'))} {item.get('title')}")
    else:
        lines.append("- 暂无事件")
    return "\n".join(lines).strip() + "\n"
