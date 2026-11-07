"""统一任务中心：受限时间表达、单线程调度、退避与运行历史。"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta

from . import (
    backup as backup_mod,
    consoles,
    digest as digest_mod,
    fleet_store,
    memory,
    store,
)

KINDS = {
    "backup": "备份",
    "digest": "舰队日报",
    "memory_sleep": "记忆睡眠",
    "bili_proactive": "B站主动刷",
    "douyin_proactive": "抖音主动刷",
    "dsh_workflow": "DSH 工作流",
    "dsh_prompt": "DSH 技能任务",
    "health_patrol": "健康巡检",
    "resource_scan": "资源采样",
    "drift_scan": "一致性扫描",
    "canary_patrol": "端到端巡检",
    "workflow": "工作流",
}
TICK_SECONDS = 30
BACKOFF = (60, 300, 900)
MAX_RETRIES = 3
DEFAULT_TIME = 9 * 60
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class TaskError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = str(message)
        self.status = int(status)


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(task_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(task_id, threading.Lock())


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def _loads(value, fallback):
    try:
        data = json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback
    return data


def _parse_time(text: str) -> int:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    if not match:
        raise TaskError(f"时间格式应为 HH:MM：{text}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise TaskError(f"时间超出范围：{text}")
    return hour * 60 + minute


def parse_schedule(text: str) -> dict:
    raw = str(text or "").strip().lower()
    if not raw:
        raise TaskError("调度时间不能为空")
    if raw == "daily":
        return {"kind": "daily", "minute": DEFAULT_TIME, "text": "daily"}
    if raw.startswith("weekly:"):
        names = [part.strip()[:3] for part in raw.split(":", 1)[1].split(",") if part.strip()]
        days = []
        for name in names:
            if name not in WEEKDAYS:
                raise TaskError(f"未知星期：{name}")
            days.append(WEEKDAYS[name])
        if not days:
            raise TaskError("weekly 至少需要一个星期")
        days = sorted(set(days))
        return {
            "kind": "weekly",
            "days": days,
            "minute": DEFAULT_TIME,
            "text": "weekly:" + ",".join(
                next(key for key, value in WEEKDAYS.items() if value == day) for day in days
            ),
        }
    if raw.startswith("every:"):
        match = re.fullmatch(r"every:(\d+)\s*([mh])", raw)
        if not match:
            raise TaskError("周期格式应为 every:30m 或 every:6h")
        amount = int(match.group(1))
        minutes = amount if match.group(2) == "m" else amount * 60
        if minutes < 1:
            raise TaskError("周期不能小于 1 分钟")
        return {"kind": "every", "minutes": minutes, "text": f"every:{minutes}m"}
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    times = sorted({_parse_time(part) for part in parts})
    if not times:
        raise TaskError("调度时间不能为空")
    return {"kind": "times", "times": times, "text": ",".join(f"{m // 60:02d}:{m % 60:02d}" for m in times)}


def next_run_at(schedule: str, after: float | None = None) -> float:
    parsed = parse_schedule(schedule)
    now = datetime.fromtimestamp(time.time() if after is None else float(after))
    if parsed["kind"] == "every":
        return (now + timedelta(minutes=parsed["minutes"])).timestamp()
    if parsed["kind"] == "times":
        for minute in parsed["times"]:
            candidate = now.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)
            if candidate.timestamp() > now.timestamp():
                return candidate.timestamp()
        first = parsed["times"][0]
        tomorrow = (now + timedelta(days=1)).replace(
            hour=first // 60, minute=first % 60, second=0, microsecond=0
        )
        return tomorrow.timestamp()
    if parsed["kind"] == "daily":
        candidate = now.replace(
            hour=parsed["minute"] // 60, minute=parsed["minute"] % 60, second=0, microsecond=0
        )
        if candidate.timestamp() <= now.timestamp():
            candidate += timedelta(days=1)
        return candidate.timestamp()
    for offset in range(0, 8):
        candidate = (now + timedelta(days=offset)).replace(
            hour=parsed["minute"] // 60, minute=parsed["minute"] % 60, second=0, microsecond=0
        )
        if candidate.timestamp() > now.timestamp() and candidate.weekday() in parsed["days"]:
            return candidate.timestamp()
    return (now + timedelta(days=7)).timestamp()


def _task(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "schedule": row["schedule"],
        "config": _loads(row["config_json"], {}),
        "enabled": bool(row["enabled"]),
        "last_run": row["last_run"],
        "next_run": row["next_run"],
        "created": row["created"],
        "updated": row["updated"],
        "kind_label": KINDS.get(row["kind"], row["kind"]),
    }


def _get(task_id: str, db_path=None) -> dict | None:
    with fleet_store.session(db_path) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task(row) if row else None


def ensure_seeded(db_path=None) -> None:
    # 内置任务统一由 automation 注册表按 id 补齐，避免「已有任务就整体跳过」。
    from . import automation

    automation.ensure_builtin(db_path)


def list_tasks(db_path=None) -> list[dict]:
    ensure_seeded(db_path)
    with fleet_store.session(db_path) as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created ASC").fetchall()
    return [_task(row) for row in rows]


def create(name: str, kind: str, schedule: str, config: dict | None = None,
           enabled: bool = False, db_path=None) -> dict:
    name = str(name or "").strip()
    if not name:
        raise TaskError("任务名称不能为空")
    if kind not in KINDS:
        raise TaskError(f"未知任务类型：{kind}")
    parsed = parse_schedule(schedule)
    now = time.time()
    task_id = f"task_{uuid.uuid4().hex[:10]}"
    next_run = next_run_at(parsed["text"], now) if enabled else 0
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO tasks(id, name, kind, schedule, config_json, enabled, last_run, next_run, created, updated) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, name, kind, parsed["text"], _json(config or {}), 1 if enabled else 0,
             0, next_run, now, now),
        )
    return _get(task_id, db_path) or {}


def update(task_id: str, patch: dict, db_path=None) -> dict:
    current = _get(task_id, db_path)
    if not current:
        raise TaskError("任务不存在", 404)
    name = str(patch.get("name", current["name"])).strip()
    if not name:
        raise TaskError("任务名称不能为空")
    kind = str(patch.get("kind", current["kind"]))
    if kind not in KINDS:
        raise TaskError(f"未知任务类型：{kind}")
    schedule = parse_schedule(patch.get("schedule", current["schedule"]))
    config = patch.get("config", current["config"])
    if not isinstance(config, dict):
        raise TaskError("config 必须是对象")
    enabled = bool(patch.get("enabled", current["enabled"]))
    now = time.time()
    next_run = 0
    if enabled:
        next_run = (
            next_run_at(schedule["text"], now)
            if not current["enabled"] or patch.get("schedule")
            else current["next_run"] or next_run_at(schedule["text"], now)
        )
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "UPDATE tasks SET name=?, kind=?, schedule=?, config_json=?, enabled=?, next_run=?, updated=? WHERE id=?",
            (name, kind, schedule["text"], _json(config), 1 if enabled else 0, next_run, now, task_id),
        )
    return _get(task_id, db_path) or {}


def delete(task_id: str, db_path=None) -> bool:
    with fleet_store.session(db_path) as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    return bool(cur.rowcount)


def list_runs(task_id: str = "", limit: int = 100, db_path=None) -> list[dict]:
    sql = "SELECT * FROM task_runs"
    params = []
    if task_id:
        sql += " WHERE task_id=?"
        params.append(task_id)
    sql += " ORDER BY started DESC LIMIT ?"
    params.append(max(1, min(int(limit), 300)))
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["detail"] = _loads(item.pop("detail_json", None), {})
        out.append(item)
    return out


def _instance(instance_id: str) -> dict:
    instance_id = str(instance_id or "").strip()
    if not instance_id:
        raise TaskError("任务未配置 instance_id")
    for inst in store.load_instances():
        if inst.get("id") == instance_id:
            return inst
    raise TaskError(f"实例不存在：{instance_id}", 404)


def _dispatch_workflow(task: dict, dispatch) -> dict:
    steps = (task.get("config") or {}).get("steps")
    if not isinstance(steps, list) or not steps:
        raise TaskError("工作流需要 config.steps 非空数组")
    results = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise TaskError(f"工作流第 {index + 1} 步不是对象")
        kind = str(step.get("kind") or "")
        if kind not in KINDS or kind == "workflow":
            raise TaskError(f"工作流第 {index + 1} 步类型不受支持：{kind}")
        sub = {
            "id": f"{task['id']}:{index + 1}",
            "name": f"{task.get('name') or '工作流'} · {KINDS[kind]}",
            "kind": kind,
            "config": step.get("config") if isinstance(step.get("config"), dict) else {},
        }
        try:
            result = dispatch(sub)
        except Exception as exc:  # noqa: BLE001
            raise TaskError(f"工作流第 {index + 1} 步（{KINDS[kind]}）失败：{exc}") from exc
        results.append({"kind": kind, "summary": str((result or {}).get("summary") or "")})
    return {"summary": f"工作流完成 {len(results)} 步", "steps": results}


def _dispatch(task: dict) -> dict:
    kind = task["kind"]
    config = task.get("config") or {}
    if kind == "workflow":
        return _dispatch_workflow(task, _dispatch)
    if kind == "backup":
        item = backup_mod.create(
            components=config.get("components"),
            include_login=bool(config.get("include_login", False)),
            label=str(config.get("label") or f"task:{task['id']}"),
        )
        return {
            "summary": f"备份完成 · {item.get('bytes', 0)} bytes",
            "backup": item,
        }
    if kind == "digest":
        data = digest_mod.collect()
        return {"summary": f"日报 {data.get('date')} · {data.get('overall')}", "digest": data}
    if kind == "memory_sleep":
        target = str(config.get("instance_id") or "").strip()
        if target:
            inst = _instance(target)
            memory.call_sleep_run(inst)
            return {"summary": f"已触发 {inst.get('name') or inst.get('id')} 记忆睡眠"}
        from . import runner as runner_mod

        done, skipped, failed = [], 0, []
        for inst in store.load_instances():
            if not runner_mod.runner.status(inst).get("running"):
                skipped += 1
                continue
            try:
                memory.call_sleep_run(inst)
                done.append(str(inst.get("name") or inst.get("id")))
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{inst.get('name') or inst.get('id')}: {exc}")
        if not done and failed:
            raise TaskError("记忆睡眠全部失败：" + "；".join(failed)[:240])
        summary = f"记忆睡眠完成 {len(done)} 个实例"
        if failed:
            summary += f"，失败 {len(failed)} 个"
        if skipped:
            summary += f"，跳过 {skipped} 个未运行实例"
        return {"summary": summary, "done": done, "failed": failed, "skipped": skipped}
    if kind in {"bili_proactive", "douyin_proactive"}:
        if not config.get("allow_write"):
            raise TaskError("写操作未开启：请在任务配置中显式设置 allow_write=true")
        inst = _instance(config.get("instance_id", ""))
        platform = "bili" if kind == "bili_proactive" else "douyin"
        consoles.call_run(inst, platform)
        return {"summary": f"已触发 {platform} 主动刷"}
    if kind == "health_patrol":
        from . import alerts as alerts_mod, health as health_mod

        health = health_mod.collect_health(force=True)
        alert_data = alerts_mod.collect()
        counts = alert_data.get("counts") or {}
        return {
            "summary": f"健康巡检 · {health.get('overall')} · 告警 {counts.get('total', 0)} 项",
            "health": health,
            "alerts": alert_data,
        }
    if kind == "resource_scan":
        from . import resources as resources_mod

        data = resources_mod.collect()
        system = data.get("system") or {}
        return {
            "summary": (
                f"CPU {system.get('cpu_percent', '—')}% · 内存 "
                f"{system.get('memory_percent', '—')}% · 磁盘余 "
                f"{system.get('disk_free_gb', '—')}GB"
            ),
            "resources": data,
        }
    if kind == "drift_scan":
        from . import drift as drift_mod

        data = drift_mod.collect()
        counts = data.get("counts") or {}
        return {
            "summary": f"一致性 {data.get('overall')} · {counts.get('total', 0)} 处差异",
            "drift": data,
        }
    if kind == "canary_patrol":
        from . import canary as canary_mod

        data = canary_mod.run()
        counts = data.get("counts") or {}
        return {
            "summary": f"端到端巡检 {data.get('overall')} · {counts.get('total', 0)} 项",
            "canary": data,
        }
    if kind == "dsh_prompt":
        prompt = str(config.get("prompt") or "").strip()
        if not prompt:
            raise TaskError("DSH 技能任务需要 config.prompt 指令")
        skill = str(config.get("skill_name") or config.get("skill") or "").strip()
        if skill and skill not in prompt:
            prompt = f"请使用「{skill}」技能完成以下任务：\n{prompt}"
        from . import dsh as dsh_mod

        try:
            timeout = max(60, min(int(config.get("timeout_sec") or 600), 1800))
        except (TypeError, ValueError):
            timeout = 600
        data = dsh_mod.run_prompt(
            prompt,
            cwd=str(config.get("cwd") or "").strip() or None,
            timeout=float(timeout),
        )
        text = str(data.get("text") or "")
        return {
            "summary": f"DSH 完成 · {data.get('duration_ms', 0) // 1000}s · {len(text)} 字",
            "text": text,
            "session_id": data.get("sessionId") or "",
            "duration_ms": data.get("duration_ms") or 0,
        }
    raise TaskError(f"未知任务类型：{kind}")


def run_task(task: dict, dispatch=None, db_path=None, manual: bool = False) -> dict:
    task_id = task["id"]
    lock = _lock_for(task_id)
    if not lock.acquire(blocking=False):
        raise TaskError("该任务正在运行", 409)
    run_id = f"tr_{uuid.uuid4().hex[:10]}"
    started = time.time()
    try:
        with fleet_store.session(db_path) as conn:
            conn.execute(
                "INSERT INTO task_runs(id, task_id, started, finished, status, summary, detail_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (run_id, task_id, started, 0, "running", "", "{}"),
            )
        try:
            result = (dispatch or _dispatch)(task)
            status = "success"
            summary = str((result or {}).get("summary") or "完成")
            detail = result or {}
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            summary = str(exc)[:300]
            detail = {"error": summary}
        finished = time.time()
        with fleet_store.session(db_path) as conn:
            conn.execute(
                "UPDATE task_runs SET finished=?, status=?, summary=?, detail_json=? WHERE id=?",
                (finished, status, summary, _json(detail), run_id),
            )
            conn.execute(
                "UPDATE tasks SET last_run=?, updated=? WHERE id=?",
                (finished, finished, task_id),
            )
        fleet_store.add_event(
            "task",
            "manual" if manual else "scheduler",
            "info" if status == "success" else "warn",
            f"任务{('完成' if status == 'success' else '失败')}：{task.get('name')}",
            {"task_id": task_id, "run_id": run_id, "summary": summary},
            run_id,
            db_path,
        )
        return {
            "id": run_id,
            "task_id": task_id,
            "started": started,
            "finished": finished,
            "status": status,
            "summary": summary,
            "detail": detail,
        }
    finally:
        lock.release()


def _set_next(task: dict, next_run: float, failures: int, db_path=None) -> None:
    config = dict(task.get("config") or {})
    if failures:
        config["_failures"] = failures
    else:
        config.pop("_failures", None)
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "UPDATE tasks SET next_run=?, config_json=?, updated=? WHERE id=?",
            (next_run, _json(config), time.time(), task["id"]),
        )


class Scheduler:
    def __init__(self, interval: float = TICK_SECONDS, db_path=None):
        self.interval = float(interval)
        self.db_path = db_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="fleet-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                continue

    def tick(self, now: float | None = None) -> list[dict]:
        if not self._tick_lock.acquire(blocking=False):
            return []
        results = []
        try:
            current = time.time() if now is None else float(now)
            for task in list_tasks(self.db_path):
                if not task.get("enabled"):
                    continue
                due = task.get("next_run") or 0
                if due and due > current:
                    continue
                try:
                    run = run_task(task, db_path=self.db_path)
                except TaskError:
                    continue
                results.append(run)
                failures = int((task.get("config") or {}).get("_failures", 0))
                if run["status"] == "success":
                    _set_next(task, next_run_at(task["schedule"], current), 0, self.db_path)
                else:
                    failures += 1
                    if failures <= MAX_RETRIES:
                        _set_next(
                            task,
                            current + BACKOFF[min(failures - 1, len(BACKOFF) - 1)],
                            failures,
                            self.db_path,
                        )
                    else:
                        _set_next(task, next_run_at(task["schedule"], current), 0, self.db_path)
        finally:
            self._tick_lock.release()
        return results


scheduler = Scheduler()
