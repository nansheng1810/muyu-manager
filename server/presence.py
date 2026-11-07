"""活人感数据：关系、里程碑、未完成话题、日记、事件与设置。"""

from __future__ import annotations

import datetime as _dt
import json
import re
import time
import uuid
from pathlib import Path

from . import dashboard, fleet_store, human_settings, llm, memory, mood, store

DEFAULTS = {
    "followup_enabled": True,
    "followup_shadow": True,
    "familiarity_threshold": 30,
    "daily_limit": 1,
    "weekly_limit": 3,
    "quiet_start": "23:00",
    "quiet_end": "08:00",
    "quiet_after_hours": 6,
    "scan_min_messages": 6,
    "scan_min_hours": 6,
    "radar_window_seconds": 5,
    "radar_retention_days": 7,
    "diary_enabled": True,
    "diary_time": "23:30",
    "diary_inject_next_day": True,
    "diary_max_chars": 500,
}

_BOOL_KEYS = {
    "followup_enabled", "followup_shadow", "diary_enabled", "diary_inject_next_day",
}
_TIME_KEYS = {"quiet_start", "quiet_end", "diary_time"}
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_RANGES = {
    "familiarity_threshold": (0, 100, int),
    "daily_limit": (0, 20, int),
    "weekly_limit": (0, 100, int),
    "quiet_after_hours": (0, 168, int),
    "scan_min_messages": (1, 100, int),
    "scan_min_hours": (0, 168, int),
    "radar_window_seconds": (1, 60, int),
    "radar_retention_days": (1, 90, int),
    "diary_max_chars": (50, 2000, int),
}

STAGES = ("stranger", "familiar", "close")
LOOP_STATUSES = ("open", "resolved", "ignored")
_SOURCES = ("auto", "manual")
_LOOP_UPDATE_KEYS = {
    "topic", "detail", "status", "confidence", "thread_key", "follow_up_after",
    "follow_up_after_hours", "follow_up_text", "follow_up_generated_at", "last_seen",
}
_DIARY_UPDATE_KEYS = {"text", "mood", "memory_ids", "model_id", "summary"}
_RELATION_UPDATE_KEYS = {
    "display_name", "nickname", "stage", "notes", "allow_memory", "followup_enabled",
    "aliases", "traits", "tags", "likes", "dislikes", "boundaries",
    "recent_summary", "last_group_id",
}

PRESENCE_PLUGIN_ID = "astrbot_plugin_human_presence"
PROACTIVE_PLUGIN_ID = "astrbot_plugin_proactive_chat"
GC_PLUGIN_ID = "astrbot_plugin_group_chat_plus"
# 群聊读空气页只允许改这些键；真正生效前还要与插件 _conf_schema.json 取交集。
GC_KEY_CANDIDATES = (
    "enabled_groups",
    "initial_probability",
    "after_reply_probability",
    "probability_duration",
    "enable_dynamic_reply_probability",
    "reply_time_periods",
    "proactive_enabled_groups",
    "proactive_quiet_start",
    "proactive_quiet_end",
    "enable_debug_log",
)
_AUTO_MILESTONE_TITLES = {
    "first_contact": "第一次聊天",
    "first_private": "第一次私聊",
    "message_10": "聊到 10 条消息",
    "message_100": "聊到 100 条消息",
    "days_30": "认识 30 天",
}
_RADAR_KINDS = ("radar_reply", "radar_silent")
_FOLLOWUP_MAX_CHARS = 40
_DIARY_MAX_SUMMARY = 120
_TIME_RE_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class PresenceError(Exception):
    pass


def _text(value, field: str, required: bool = False, limit: int | None = None) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise PresenceError(f"{field} 必须是字符串")
    text = value.strip()
    if required and not text:
        raise PresenceError(f"{field} 不能为空")
    return text[:limit] if limit else text


def _number(value, field: str, low=None, high=None, default=0.0) -> float:
    if value is None:
        return float(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PresenceError(f"{field} 必须是数字")
    number = float(value)
    if low is not None and number < low:
        raise PresenceError(f"{field} 不能小于 {low}")
    if high is not None and number > high:
        raise PresenceError(f"{field} 不能大于 {high}")
    return number


def _timestamp(value, field: str, default: float) -> float:
    number = _number(value, field, low=0, default=default)
    # 0 表示“没给”，直接回落到当前时间，避免首见/发生时间停留在 1970。
    return number if number > 0 else float(default)


def _count(value, field: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PresenceError(f"{field} 必须是非负整数")
    return value


def _date(value) -> str:
    text = _text(value, "date", required=True, limit=10)
    try:
        _dt.date.fromisoformat(text)
    except ValueError:
        raise PresenceError("date 必须是 YYYY-MM-DD") from None
    return text


def _mood(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PresenceError("mood 必须是对象")
    return value


def _memory_ids(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PresenceError("memory_ids 必须是数组")
    return [_text(item, "memory_ids 项", required=True, limit=100) for item in value[:100]]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value, default):
    try:
        parsed = json.loads(value) if value else default
    except (TypeError, ValueError):
        return default
    return parsed


def validate_settings(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise PresenceError("设置必须是对象")
    out: dict = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise PresenceError(f"未知设置项：{key}")
        if key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise PresenceError(f"{key} 必须是布尔值")
            out[key] = value
        elif key in _TIME_KEYS:
            if not isinstance(value, str) or not _TIME_RE.fullmatch(value.strip()):
                raise PresenceError(f"{key} 必须是 HH:MM")
            out[key] = value.strip()
        else:
            low, high, kind = _RANGES[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PresenceError(f"{key} 必须是数字")
            number = kind(value)
            if number < low or number > high:
                raise PresenceError(f"{key} 必须在 {low}–{high} 之间")
            out[key] = number
    return out


def get_settings(instance_id: str, db_path=None) -> dict:
    instance_id = _text(instance_id, "instance_id", required=True)
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT json FROM presence_settings WHERE instance_id=?", (instance_id,)
        ).fetchone()
    cfg = dict(DEFAULTS)
    if row:
        saved = _loads(row["json"], {})
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    return cfg


def save_settings(instance_id: str, patch: dict, db_path=None) -> dict:
    instance_id = _text(instance_id, "instance_id", required=True)
    current = get_settings(instance_id, db_path=db_path)
    current.update(validate_settings(patch))
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO presence_settings(instance_id, json, updated) VALUES(?,?,?) "
            "ON CONFLICT(instance_id) DO UPDATE SET json=excluded.json, updated=excluded.updated",
            (instance_id, _json(current), time.time()),
        )
    return current


def _relation_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["allow_memory"] = bool(item.get("allow_memory"))
    item["followup_enabled"] = bool(item.get("followup_enabled"))
    for field in ("aliases", "traits", "tags"):
        raw = item.pop(f"{field}_json", "[]")
        try:
            value = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            value = []
        if not isinstance(value, list):
            value = []
        item[field] = [str(entry)[:40] for entry in value if str(entry).strip()][:20]
    return item


def _string_list(value, field: str, limit: int = 20) -> str:
    """把标签/别名列表收敛成 JSON 字符串。"""
    if not isinstance(value, list):
        raise PresenceError(f"{field} 必须是列表")
    items = [
        " ".join(str(entry).split())[:40]
        for entry in value
        if str(entry).strip()
    ][:limit]
    return json.dumps(items, ensure_ascii=False)


def get_relation(instance_id: str, platform: str, person_key: str, db_path=None) -> dict | None:
    instance_id = _text(instance_id, "instance_id", required=True)
    platform = _text(platform, "platform", required=True)
    person_key = _text(person_key, "person_key", required=True)
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM presence_relations WHERE instance_id=? AND platform=? AND person_key=?",
            (instance_id, platform, person_key),
        ).fetchone()
    return _relation_row(row)


def get_relation_by_id(relation_id: str, db_path=None) -> dict | None:
    relation_id = _text(relation_id, "id", required=True)
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM presence_relations WHERE id=?", (relation_id,)
        ).fetchone()
    return _relation_row(row)


def update_relation(relation_id: str, patch: dict, db_path=None) -> dict:
    relation_id = _text(relation_id, "id", required=True)
    if not isinstance(patch, dict):
        raise PresenceError("更新内容必须是对象")
    unknown = set(patch) - _RELATION_UPDATE_KEYS
    if unknown:
        raise PresenceError(f"未知字段：{sorted(unknown)[0]}")
    updates: dict = {}
    if "display_name" in patch:
        updates["display_name"] = _text(
            patch["display_name"], "display_name", limit=80)
    if "nickname" in patch:
        updates["nickname"] = _text(patch["nickname"], "nickname", limit=80)
    if "stage" in patch:
        stage = _text(patch["stage"], "stage", required=True)
        if stage not in STAGES:
            raise PresenceError("stage 取值无效")
        updates["stage"] = stage
    if "notes" in patch:
        updates["notes"] = _text(patch["notes"], "notes", limit=2000)
    for field in ("aliases", "traits", "tags"):
        if field in patch:
            updates[f"{field}_json"] = _string_list(patch[field], field)
    for field, limit in (
        ("likes", 500), ("dislikes", 500), ("boundaries", 500),
        ("recent_summary", 300),
    ):
        if field in patch:
            updates[field] = _text(patch[field], field, limit=limit)
    if "last_group_id" in patch:
        updates["last_group_id"] = _text(
            patch["last_group_id"], "last_group_id", limit=80)
    for field in ("allow_memory", "followup_enabled"):
        if field not in patch:
            continue
        flag = patch[field]
        if not isinstance(flag, (bool, int)) or (
                isinstance(flag, int) and not isinstance(flag, bool)
                and flag not in (0, 1)):
            raise PresenceError(f"{field} 必须是布尔值")
        updates[field] = int(bool(flag))
    updates["updated"] = time.time()
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM presence_relations WHERE id=?", (relation_id,)
        ).fetchone()
        if row is None:
            raise PresenceError("关系不存在")
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(
            f"UPDATE presence_relations SET {assignments} WHERE id=?",
            [*updates.values(), relation_id],
        )
        saved = conn.execute(
            "SELECT * FROM presence_relations WHERE id=?", (relation_id,)
        ).fetchone()
    return _relation_row(saved) or {}


def upsert_relation(instance_id: str, platform: str, person_key: str,
                    display_name: str = "", nickname: str = "", stage: str = "",
                    allow_memory=None, followup_enabled=None,
                    first_seen=None, last_seen=None, message_count=0,
                    notes=None, db_path=None) -> dict:
    """新增或更新关系；message_count 是本次新增消息数（累加）。"""
    instance_id = _text(instance_id, "instance_id", required=True)
    platform = _text(platform, "platform", required=True)
    person_key = _text(person_key, "person_key", required=True)
    display_name = _text(display_name, "display_name", limit=80)
    nickname = _text(nickname, "nickname", limit=80)
    if stage and stage not in STAGES:
        raise PresenceError("stage 取值无效")
    for field, flag in (("allow_memory", allow_memory),
                        ("followup_enabled", followup_enabled)):
        if flag is None:
            continue
        if not isinstance(flag, (bool, int)) or (isinstance(flag, int)
                                                 and not isinstance(flag, bool)
                                                 and flag not in (0, 1)):
            raise PresenceError(f"{field} 必须是布尔值")
    delta = _count(message_count, "message_count")
    notes_value = None if notes is None else _text(notes, "notes", limit=2000)
    now = time.time()
    first = _timestamp(first_seen, "first_seen", now)
    last = _timestamp(last_seen, "last_seen", now)
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM presence_relations WHERE instance_id=? AND platform=? AND person_key=?",
            (instance_id, platform, person_key),
        ).fetchone()
        existing = dict(row) if row is not None else {}
        rel_id = existing.get("id") or "pr_" + uuid.uuid4().hex[:12]
        existing_first = float(existing.get("first_seen") or 0)
        if existing_first > 0:
            first = min(existing_first, first)
        last = max(float(existing.get("last_seen") or 0), last)
        stored_stage = stage or str(existing.get("stage") or "stranger")
        stored_allow = int(bool(allow_memory)) if allow_memory is not None \
            else int(existing.get("allow_memory", 1))
        stored_followup = int(bool(followup_enabled)) if followup_enabled is not None \
            else int(existing.get("followup_enabled", 1))
        stored_name = display_name or str(existing.get("display_name") or "")
        stored_nickname = nickname or str(existing.get("nickname") or "")
        stored_notes = str(existing.get("notes") or "") if notes_value is None else notes_value
        stored_count = int(existing.get("message_count") or 0) + delta
        conn.execute(
            "INSERT INTO presence_relations(id, instance_id, platform, person_key, display_name, "
            "nickname, stage, allow_memory, followup_enabled, first_seen, last_seen, message_count, "
            "notes, updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(instance_id, platform, person_key) DO UPDATE SET "
            "display_name=excluded.display_name, nickname=excluded.nickname, stage=excluded.stage, "
            "allow_memory=excluded.allow_memory, followup_enabled=excluded.followup_enabled, "
            "first_seen=excluded.first_seen, last_seen=excluded.last_seen, "
            "message_count=excluded.message_count, notes=excluded.notes, updated=excluded.updated",
            (rel_id, instance_id, platform, person_key, stored_name, stored_nickname,
             stored_stage, stored_allow, stored_followup, first, last, stored_count,
             stored_notes, now),
        )
        saved = conn.execute(
            "SELECT * FROM presence_relations WHERE instance_id=? AND platform=? AND person_key=?",
            (instance_id, platform, person_key),
        ).fetchone()
    return _relation_row(saved) or {}


def list_relations(instance_id: str, merge: bool = True, limit: int = 200,
                   db_path=None) -> list[dict]:
    """列出关系；merge=True 时只读合并 human_relations 的好感动怒与熟悉度。"""
    instance_id = _text(instance_id, "instance_id", required=True)
    limit = max(1, min(int(limit), 500))
    if merge:
        sql = (
            "SELECT p.*, h.familiarity AS familiarity, h.affection AS affection, "
            "h.anger AS anger FROM presence_relations p "
            "LEFT JOIN human_relations h ON h.instance_id=p.instance_id "
            "AND h.platform=p.platform AND h.person_key=p.person_key "
            "WHERE p.instance_id=? ORDER BY p.last_seen DESC LIMIT ?"
        )
    else:
        sql = ("SELECT * FROM presence_relations WHERE instance_id=? "
               "ORDER BY last_seen DESC LIMIT ?")
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(sql, (instance_id, limit)).fetchall()
    items = [_relation_row(row) or {} for row in rows]
    if merge:
        for item in items:
            for key in ("familiarity", "affection", "anger"):
                if item.get(key) is None:
                    item[key] = 0.0
    return items


def _insert_milestone(conn, instance_id: str, platform: str, person_key: str,
                      kind: str, title: str, detail: str, occurred_at: float,
                      source: str, now: float) -> dict:
    milestone_id = "ms_" + uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO presence_milestones(id, instance_id, platform, person_key, kind, title, "
        "detail, occurred_at, source, created) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (milestone_id, instance_id, platform, person_key, kind, title,
         detail, occurred_at, source, now),
    )
    row = conn.execute(
        "SELECT * FROM presence_milestones WHERE id=?", (milestone_id,)
    ).fetchone()
    return dict(row) if row is not None else {}


def add_milestone(instance_id: str, platform: str, person_key: str, kind: str,
                  title: str, detail: str = "", occurred_at=None,
                  source: str = "manual", db_path=None) -> dict:
    instance_id = _text(instance_id, "instance_id", required=True)
    platform = _text(platform, "platform", required=True)
    person_key = _text(person_key, "person_key", required=True)
    kind = _text(kind, "kind", required=True, limit=40)
    title = _text(title, "title", required=True, limit=120)
    detail = _text(detail, "detail", limit=2000)
    if source not in _SOURCES:
        raise PresenceError("source 取值无效")
    now = time.time()
    occurred = _timestamp(occurred_at, "occurred_at", now)
    with fleet_store.session(db_path) as conn:
        return _insert_milestone(conn, instance_id, platform, person_key, kind,
                                 title, detail, occurred, source, now)


def get_milestone(milestone_id: str, db_path=None) -> dict | None:
    milestone_id = _text(milestone_id, "id", required=True)
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM presence_milestones WHERE id=?", (milestone_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def list_milestones(instance_id: str, platform: str | None = None,
                    person_key: str | None = None, limit: int = 100,
                    db_path=None) -> list[dict]:
    instance_id = _text(instance_id, "instance_id", required=True)
    clauses = ["instance_id=?"]
    params: list = [instance_id]
    if platform:
        clauses.append("platform=?")
        params.append(_text(platform, "platform", required=True))
    if person_key:
        clauses.append("person_key=?")
        params.append(_text(person_key, "person_key", required=True))
    limit = max(1, min(int(limit), 500))
    params.append(limit)
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM presence_milestones WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC, created DESC LIMIT ?", params,
        ).fetchall()
    return [dict(row) for row in rows]


def delete_milestone(milestone_id: str, db_path=None) -> bool:
    milestone_id = _text(milestone_id, "id", required=True)
    with fleet_store.session(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM presence_milestones WHERE id=?", (milestone_id,))
        return bool(cur.rowcount)


def _loop_row(row) -> dict | None:
    return dict(row) if row is not None else None


def get_loop(loop_id: str, db_path=None) -> dict | None:
    loop_id = _text(loop_id, "id", required=True)
    with fleet_store.session(db_path) as conn:
        row = conn.execute("SELECT * FROM presence_loops WHERE id=?", (loop_id,)).fetchone()
    return _loop_row(row)


def add_loop(instance_id: str, platform: str, person_key: str, topic: str,
             thread_key: str = "", detail: str = "", confidence=0.5,
             source: str = "auto", follow_up_after_hours=24.0, db_path=None) -> dict:
    instance_id = _text(instance_id, "instance_id", required=True)
    platform = _text(platform, "platform", required=True)
    person_key = _text(person_key, "person_key", required=True)
    topic = _text(topic, "topic", required=True, limit=120)
    thread_key = _text(thread_key, "thread_key", limit=200)
    detail = _text(detail, "detail", limit=2000)
    confidence = _number(confidence, "confidence", low=0, high=1, default=0.5)
    if source not in _SOURCES:
        raise PresenceError("source 取值无效")
    hours = _number(follow_up_after_hours, "follow_up_after_hours",
                    low=0, high=8760, default=24)
    now = time.time()
    loop_id = "lp_" + uuid.uuid4().hex[:12]
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO presence_loops(id, instance_id, platform, person_key, thread_key, "
            "topic, detail, status, confidence, source, created, last_seen, follow_up_after) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (loop_id, instance_id, platform, person_key, thread_key, topic, detail,
             "open", confidence, source, now, now, now + hours * 3600),
        )
        row = conn.execute("SELECT * FROM presence_loops WHERE id=?", (loop_id,)).fetchone()
    return _loop_row(row) or {}


def list_loops(instance_id: str, status: str | None = None, limit: int = 100,
               db_path=None) -> list[dict]:
    instance_id = _text(instance_id, "instance_id", required=True)
    if status is not None and status not in LOOP_STATUSES:
        raise PresenceError("status 取值无效")
    clauses = ["instance_id=?"]
    params: list = [instance_id]
    if status:
        clauses.append("status=?")
        params.append(status)
    limit = max(1, min(int(limit), 500))
    params.append(limit)
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM presence_loops WHERE {' AND '.join(clauses)} "
            "ORDER BY follow_up_after ASC, created DESC LIMIT ?", params,
        ).fetchall()
    return [dict(row) for row in rows]


def update_loop(loop_id: str, patch: dict, db_path=None) -> dict:
    loop_id = _text(loop_id, "id", required=True)
    if not isinstance(patch, dict):
        raise PresenceError("更新内容必须是对象")
    unknown = set(patch) - _LOOP_UPDATE_KEYS
    if unknown:
        raise PresenceError(f"未知字段：{sorted(unknown)[0]}")
    updates: dict = {}
    if "topic" in patch:
        updates["topic"] = _text(patch["topic"], "topic", required=True, limit=120)
    if "detail" in patch:
        updates["detail"] = _text(patch["detail"], "detail", limit=2000)
    if "status" in patch:
        status = _text(patch["status"], "status", required=True)
        if status not in LOOP_STATUSES:
            raise PresenceError("status 取值无效")
        updates["status"] = status
    if "confidence" in patch:
        updates["confidence"] = _number(patch["confidence"], "confidence",
                                        low=0, high=1, default=0.5)
    if "thread_key" in patch:
        updates["thread_key"] = _text(patch["thread_key"], "thread_key", limit=200)
    if "follow_up_after" in patch:
        updates["follow_up_after"] = _timestamp(
            patch["follow_up_after"], "follow_up_after", time.time())
    if "follow_up_after_hours" in patch:
        hours = _number(patch["follow_up_after_hours"], "follow_up_after_hours",
                        low=0, high=8760, default=24)
        updates["follow_up_after"] = time.time() + hours * 3600
    if "follow_up_text" in patch:
        updates["follow_up_text"] = _text(patch["follow_up_text"], "follow_up_text",
                                          limit=1000)
    if "follow_up_generated_at" in patch:
        updates["follow_up_generated_at"] = _timestamp(
            patch["follow_up_generated_at"], "follow_up_generated_at", time.time())
    if "last_seen" in patch:
        updates["last_seen"] = _timestamp(patch["last_seen"], "last_seen", time.time())
    with fleet_store.session(db_path) as conn:
        row = conn.execute("SELECT id FROM presence_loops WHERE id=?", (loop_id,)).fetchone()
        if row is None:
            raise PresenceError("未完成话题不存在")
        if updates:
            assignments = ", ".join(f"{key}=?" for key in updates)
            conn.execute(
                f"UPDATE presence_loops SET {assignments} WHERE id=?",
                [*updates.values(), loop_id],
            )
        saved = conn.execute("SELECT * FROM presence_loops WHERE id=?", (loop_id,)).fetchone()
    return _loop_row(saved) or {}


def resolve_loop(loop_id: str, db_path=None) -> dict:
    return update_loop(loop_id, {"status": "resolved"}, db_path=db_path)


def ignore_loop(loop_id: str, db_path=None) -> dict:
    return update_loop(loop_id, {"status": "ignored"}, db_path=db_path)


def _diary_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["mood"] = _loads(item.pop("mood_json", ""), {})
    item["memory_ids"] = _loads(item.pop("memory_ids_json", ""), [])
    mood = item["mood"] if isinstance(item["mood"], dict) else {}
    item["summary"] = str(mood.get("summary") or "")
    return item


def upsert_diary(instance_id: str, date: str, text: str, mood=None,
                 memory_ids=None, model_id: str = "", db_path=None) -> dict:
    instance_id = _text(instance_id, "instance_id", required=True)
    date = _date(date)
    text = _text(text, "text", required=True, limit=5000)
    mood = _mood(mood)
    memory_ids = _memory_ids(memory_ids)
    model_id = _text(model_id, "model_id", limit=200)
    now = time.time()
    diary_id = "dy_" + uuid.uuid4().hex[:12]
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO presence_diaries(id, instance_id, date, text, mood_json, "
            "memory_ids_json, model_id, created, updated) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(instance_id, date) DO UPDATE SET text=excluded.text, "
            "mood_json=excluded.mood_json, memory_ids_json=excluded.memory_ids_json, "
            "model_id=excluded.model_id, updated=excluded.updated",
            (diary_id, instance_id, date, text, _json(mood), _json(memory_ids),
             model_id, now, now),
        )
        row = conn.execute(
            "SELECT * FROM presence_diaries WHERE instance_id=? AND date=?",
            (instance_id, date),
        ).fetchone()
    return _diary_row(row) or {}


def list_diaries(instance_id: str, limit: int = 60, db_path=None) -> list[dict]:
    instance_id = _text(instance_id, "instance_id", required=True)
    limit = max(1, min(int(limit), 365))
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM presence_diaries WHERE instance_id=? ORDER BY date DESC LIMIT ?",
            (instance_id, limit),
        ).fetchall()
    return [_diary_row(row) or {} for row in rows]


def get_diary(instance_id: str, date: str, db_path=None) -> dict | None:
    instance_id = _text(instance_id, "instance_id", required=True)
    date = _date(date)
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM presence_diaries WHERE instance_id=? AND date=?",
            (instance_id, date),
        ).fetchone()
    return _diary_row(row)


def update_diary(diary_id: str, patch: dict, db_path=None) -> dict:
    diary_id = _text(diary_id, "id", required=True)
    if not isinstance(patch, dict):
        raise PresenceError("更新内容必须是对象")
    unknown = set(patch) - _DIARY_UPDATE_KEYS
    if unknown:
        raise PresenceError(f"未知字段：{sorted(unknown)[0]}")
    updates: dict = {}
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM presence_diaries WHERE id=?", (diary_id,)).fetchone()
        if row is None:
            raise PresenceError("日记不存在")
        if "text" in patch:
            updates["text"] = _text(patch["text"], "text", required=True, limit=5000)
        if "mood" in patch or "summary" in patch:
            current = _loads(row["mood_json"], {})
            mood_value = _mood(patch["mood"]) if "mood" in patch \
                else (current if isinstance(current, dict) else {})
            if "summary" in patch:
                mood_value = dict(mood_value)
                mood_value["summary"] = _text(
                    patch["summary"], "summary", limit=_DIARY_MAX_SUMMARY)
            updates["mood_json"] = _json(mood_value)
        if "memory_ids" in patch:
            updates["memory_ids_json"] = _json(_memory_ids(patch["memory_ids"]))
        if "model_id" in patch:
            updates["model_id"] = _text(patch["model_id"], "model_id", limit=200)
        updates["updated"] = time.time()
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(
            f"UPDATE presence_diaries SET {assignments} WHERE id=?",
            [*updates.values(), diary_id],
        )
        saved = conn.execute(
            "SELECT * FROM presence_diaries WHERE id=?", (diary_id,)).fetchone()
    return _diary_row(saved) or {}


def get_diary_by_id(diary_id: str, db_path=None) -> dict | None:
    diary_id = _text(diary_id, "id", required=True)
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM presence_diaries WHERE id=?", (diary_id,)).fetchone()
    return _diary_row(row)


def delete_diary(diary_id: str, db_path=None) -> bool:
    diary_id = _text(diary_id, "id", required=True)
    with fleet_store.session(db_path) as conn:
        cur = conn.execute("DELETE FROM presence_diaries WHERE id=?", (diary_id,))
        return bool(cur.rowcount)


def add_event(instance_id: str, kind: str, group_id: str = "", person_key: str = "",
              payload=None, db_path=None) -> int:
    instance_id = _text(instance_id, "instance_id", required=True)
    kind = _text(kind, "kind", required=True, limit=40)
    group_id = _text(group_id, "group_id", limit=200)
    person_key = _text(person_key, "person_key", limit=200)
    if payload is None:
        payload = {}
    try:
        payload_json = _json(payload)
    except (TypeError, ValueError):
        raise PresenceError("payload 无法序列化") from None
    with fleet_store.session(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO presence_events(instance_id, kind, group_id, person_key, "
            "payload_json, created) VALUES(?,?,?,?,?,?)",
            (instance_id, kind, group_id, person_key, payload_json, time.time()),
        )
        return int(cur.lastrowid)


def _event_row(row) -> dict:
    item = dict(row)
    item["payload"] = _loads(item.pop("payload_json", ""), {})
    return item


def list_events(instance_id: str, kind: str | None = None, since=None,
                limit: int = 100, db_path=None) -> list[dict]:
    instance_id = _text(instance_id, "instance_id", required=True)
    clauses = ["instance_id=?"]
    params: list = [instance_id]
    if kind:
        clauses.append("kind=?")
        params.append(_text(kind, "kind", required=True, limit=40))
    if since is not None:
        clauses.append("created>=?")
        params.append(_number(since, "since", low=0, default=0))
    limit = max(1, min(int(limit), 500))
    params.append(limit)
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM presence_events WHERE {' AND '.join(clauses)} "
            "ORDER BY created DESC, id DESC LIMIT ?", params,
        ).fetchall()
    return [_event_row(row) for row in rows]


def prune_events(instance_id: str | None = None, retention_days=7, db_path=None) -> int:
    days = _number(retention_days, "retention_days", low=1, high=365, default=7)
    cutoff = time.time() - days * 86400
    with fleet_store.session(db_path) as conn:
        if instance_id:
            instance_id = _text(instance_id, "instance_id", required=True)
            cur = conn.execute(
                "DELETE FROM presence_events WHERE instance_id=? AND created<?",
                (instance_id, cutoff),
            )
        else:
            cur = conn.execute("DELETE FROM presence_events WHERE created<?", (cutoff,))
        return int(cur.rowcount)


# ------------------------------------------------------- 活动、上下文与关系


def _private_flag(payload: dict, default: bool = False) -> bool:
    value = payload.get("is_private")
    if value is None:
        value = payload.get("private")
    if value is not None:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "yes", "private"}
    kind = str(payload.get("kind") or payload.get("scene") or "").strip().lower()
    if kind:
        return kind in {"private", "friendmessage", "friend", "private_message"}
    return default


def _pick_provider(inst: dict, instance_id: str, db_path=None) -> str:
    settings = human_settings.get_settings(instance_id, db_path=db_path)
    return mood._pick_provider(inst, settings)


def _memory_context(inst: dict, db_path=None) -> tuple[list[str], list[str], list[str]]:
    """只读 LivingMemory 的 working/relations 摘要，供扫描、回访与日记使用。

    只调用只读 GET 接口，绝不调用任何记忆写入/更新接口；插件不可达时返回空，
    不影响扫描、回访或日记本身。

    Args:
        inst: 管理器实例字典。
        db_path: 测试用临时数据库路径；合并关系时也走同一路径。

    Returns:
        ``(记忆摘要, 记忆 ID, 关系摘要)`` 三个列表；关系摘要不含人名。
    """
    lines: list[str] = []
    memory_ids: list[str] = []
    relation_lines: list[str] = []
    if not isinstance(inst, dict):
        return lines, memory_ids, relation_lines

    def short_call(inst, method, path, payload=None, query=None, timeout=5):
        # 记忆只是附加输入，单次最多等 5 秒，避免拖垮扫描/日记整体超时。
        return dashboard.call(inst, method, path, payload, query=query,
                              timeout=min(float(timeout or 5), 5))

    try:
        working = memory.call_working(inst, limit=20, call=short_call) or {}
    except Exception:  # noqa: BLE001 - 记忆插件不可用时跳过记忆输入
        working = {}
    sessions = working.get("sessions") if isinstance(working, dict) else None
    if isinstance(sessions, list):
        for item in sessions[:10]:
            if not isinstance(item, dict):
                continue
            for key in ("summary", "title", "topic", "name"):
                line = str(item.get(key) or "").strip()
                if line:
                    lines.append(line[:80])
                    break
            memory_id = str(item.get("id") or "").strip()
            if memory_id:
                memory_ids.append(memory_id[:100])
    try:
        cards = memory.call_relations(
            inst, limit=10, call=short_call,
            relation_lookup=lambda iid, plat, key: mood.get_relation(
                iid, plat, key, db_path=db_path),
            events_lookup=lambda iid, limit=200: mood.events(
                iid, limit, db_path=db_path),
        ) or {}
    except Exception:  # noqa: BLE001
        cards = {}
    rows = cards.get("relations") if isinstance(cards, dict) else None
    for card in (rows or [])[:10]:
        if not isinstance(card, dict):
            continue
        stage = str(card.get("stage") or "").strip()
        if not stage:
            continue
        mood_block = card.get("mood") if isinstance(card.get("mood"), dict) else {}
        familiarity = mood_block.get("familiarity", card.get("familiarity"))
        try:
            familiarity_text = f"{float(familiarity):.0f}"
        except (TypeError, ValueError):
            familiarity_text = "未知"
        relation_lines.append(f"{stage}（熟悉度 {familiarity_text}）")
    return lines, memory_ids, relation_lines


def _decode_json_object(raw) -> dict:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise PresenceError("模型没有返回 JSON")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        raise PresenceError("模型返回的 JSON 无法解析") from None
    if not isinstance(data, dict):
        raise PresenceError("模型返回的不是对象")
    return data


def _clean_followup_text(raw) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("text"):
            text = text[4:]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = lines[0] if lines else ""
    text = text.strip().strip("\"'“”‘’「」『』").strip()
    if text.startswith("私聊："):
        text = text[3:].strip()
    return text[:_FOLLOWUP_MAX_CHARS]


def record_activity(payload: dict, instances=None, db_path=None) -> dict:
    """记录一次关系活动并自动补里程碑；message_count 为本次新增消息数。"""
    if not isinstance(payload, dict):
        raise PresenceError("活动必须是对象")
    pool = instances if instances is not None else store.load_instances()
    inst = mood.resolve_instance(payload, pool)
    instance_id = str(inst.get("id") or "")
    platform = _text(payload.get("platform") or "qq", "platform", required=True, limit=40)
    person_key = _text(payload.get("person_key"), "person_key", required=True, limit=200)
    display_name = _text(
        payload.get("display_name") or payload.get("sender_name") or "",
        "display_name", limit=80)
    raw_count = payload.get("message_count")
    if raw_count is None:
        messages = payload.get("messages")
        raw_count = len(messages) if isinstance(messages, list) and messages else 1
    count = _count(raw_count, "message_count")
    private = _private_flag(payload)
    now = time.time()
    occurred = _timestamp(
        payload.get("occurred_at") if payload.get("occurred_at") is not None
        else payload.get("ts"), "occurred_at", now)
    existing = get_relation(instance_id, platform, person_key, db_path=db_path)
    upsert_relation(
        instance_id, platform, person_key, display_name=display_name,
        first_seen=occurred, last_seen=occurred, message_count=count,
        db_path=db_path)
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM presence_relations WHERE instance_id=? AND platform=? "
            "AND person_key=?", (instance_id, platform, person_key)).fetchone()
        relation = _relation_row(row) or {}
        kinds = {item["kind"] for item in conn.execute(
            "SELECT kind FROM presence_milestones WHERE instance_id=? AND platform=? "
            "AND person_key=?", (instance_id, platform, person_key)).fetchall()}
        created: list[dict] = []

        def auto(kind: str, detail: str, at: float) -> None:
            if kind in kinds:
                return
            created.append(_insert_milestone(
                conn, instance_id, platform, person_key, kind,
                _AUTO_MILESTONE_TITLES[kind], detail, at, "auto", now))
            kinds.add(kind)

        who = display_name or person_key
        if existing is None:
            auto("first_contact", f"在 {platform} 第一次见到 {who}", occurred)
        if private:
            auto("first_private", f"和 {who} 第一次私聊", occurred)
        total = int(relation.get("message_count") or 0)
        if total >= 10:
            auto("message_10", f"累计聊到 {total} 条消息", occurred)
        if total >= 100:
            auto("message_100", f"累计聊到 {total} 条消息", occurred)
        first_seen = float(relation.get("first_seen") or occurred)
        last_seen = float(relation.get("last_seen") or occurred)
        if last_seen - first_seen >= 30 * 86400:
            auto("days_30", f"和 {who} 认识满 30 天", last_seen)
    return {"instance_id": instance_id, "relation": relation,
            "milestones": created}


def context(instance_id: str, platform: str, person_key: str, thread_key: str = "",
            db_path=None) -> dict:
    """插件回复前拉取的短上下文：昵称、阶段、最近里程碑与昨日摘要。

    ``thread_key`` 被收件箱接管时返回空上下文，确保接管会话绝不注入任何
    关系、里程碑或日记内容。
    """
    instance_id = _text(instance_id, "instance_id", required=True)
    platform = _text(platform, "platform", required=True, limit=40)
    person_key = _text(person_key, "person_key", required=True, limit=200)
    thread_key = str(thread_key or "").strip()
    if thread_key and _thread_takeover(instance_id, platform, thread_key, db_path):
        return {"relation": None, "nickname": "", "stage": "",
                "allow_memory": False, "milestones": [],
                "diary_summary": "", "takeover": True}
    relation = get_relation(instance_id, platform, person_key, db_path=db_path)
    diaries = list_diaries(instance_id, limit=1, db_path=db_path)
    summary = str(diaries[0].get("summary") or "") if diaries else ""
    if relation is None:
        return {"relation": None, "nickname": "", "stage": "",
                "allow_memory": False, "milestones": [],
                "diary_summary": summary, "takeover": False}
    milestones = list_milestones(instance_id, platform, person_key, limit=2,
                                 db_path=db_path)
    return {
        "relation": relation,
        "nickname": str(relation.get("nickname") or relation.get("display_name") or ""),
        "stage": str(relation.get("stage") or "stranger"),
        "allow_memory": bool(relation.get("allow_memory")),
        "milestones": milestones,
        "diary_summary": summary,
        "aliases": relation.get("aliases") or [],
        "traits": relation.get("traits") or [],
        "tags": relation.get("tags") or [],
        "likes": str(relation.get("likes") or ""),
        "dislikes": str(relation.get("dislikes") or ""),
        "boundaries": str(relation.get("boundaries") or ""),
        "recent_summary": str(relation.get("recent_summary") or ""),
        "takeover": False,
    }


# --------------------------------------------------------- 未完成话题扫描


def scan_loops(inst: dict, payload: dict, db_path=None) -> dict:
    """用实例当前模型扫描最近的私聊，提取未完成话题；失败只返回 error。"""
    if not isinstance(payload, dict) or not isinstance(inst, dict):
        raise PresenceError("扫描参数必须是对象")
    instance_id = str(inst.get("id") or "").strip()
    if not instance_id:
        raise PresenceError("instance_id 不能为空")
    platform = _text(payload.get("platform") or "qq", "platform",
                     required=True, limit=40)
    person_key = _text(payload.get("person_key"), "person_key",
                       required=True, limit=200)
    if not _private_flag(payload, default=True):
        raise PresenceError("只扫描私聊，群聊不做未完成话题")
    thread_key = _text(payload.get("thread_key") or person_key, "thread_key",
                       limit=200)
    if _thread_takeover(instance_id, platform, thread_key, db_path):
        return {"loops": [], "skipped": 0,
                "error": "会话已被收件箱接管，跳过未完成话题扫描"}
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = payload.get("recent") if isinstance(payload.get("recent"), list) else []
    transcript = []
    for item in messages[-20:]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        transcript.append({
            "speaker": str(item.get("speaker") or item.get("sender_name") or "")
            .strip()[:20],
            "text": text[:300],
        })
    if not transcript:
        return {"loops": [], "skipped": 0, "error": "没有可扫描的私聊消息"}
    existing_topics = {
        str(item.get("topic") or "").strip().lower()
        for item in list_loops(instance_id, status="open", limit=500,
                               db_path=db_path)
        if item.get("person_key") == person_key
    }
    system = (
        "你是「牧鱼」的未完成话题提取器。只输出一个 JSON 对象，不要 Markdown、"
        "不要解释、不要思维链。格式："
        '{"loops":[{"topic":"不超过 30 字","detail":"不超过 80 字",'
        '"confidence":0.0,"follow_up_after_hours":24}]}。\n'
        "只提取对方明确提到的未来指向、还没做完的事；已完成、客套、玩笑、"
        "没有具体指向的内容都不算。每次最多 3 条，没有就返回 {\"loops\":[]}。"
    )
    memory_lines, _, relation_lines = _memory_context(inst, db_path=db_path)
    user = _json({
        "人物": person_key,
        "最近私聊": transcript,
        "记忆摘要": memory_lines,
        "关系摘要": relation_lines,
        "当前时间": time.strftime("%Y-%m-%d %H:%M"),
    })
    try:
        provider_id = _pick_provider(inst, instance_id, db_path=db_path)
        raw = llm.chat(inst, provider_id, [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=400, timeout=15)
        data = _decode_json_object(raw)
        candidates = data.get("loops")
        if not isinstance(candidates, list):
            raise PresenceError("模型没有返回 loops 数组")
    except Exception as exc:  # noqa: BLE001 - 扫描失败不阻塞聊天
        return {"loops": [], "skipped": 0, "error": str(exc)[:200]}
    created: list[dict] = []
    skipped = 0
    seen = set(existing_topics)
    for item in candidates:
        if len(created) >= 3:
            break
        try:
            if not isinstance(item, dict):
                raise PresenceError("候选不是对象")
            topic = _text(item.get("topic"), "topic", required=True, limit=120)
            detail = _text(item.get("detail") or "", "detail", limit=2000)
            confidence = _number(item.get("confidence", 0.5), "confidence",
                                 low=0, high=1, default=0.5)
            hours = _number(item.get("follow_up_after_hours", 24),
                            "follow_up_after_hours", default=24)
        except PresenceError:
            skipped += 1
            continue
        normalized = topic.strip().lower()
        if confidence < 0.5 or normalized in seen:
            skipped += 1
            continue
        seen.add(normalized)
        created.append(add_loop(
            instance_id, platform, person_key, topic, thread_key=thread_key,
            detail=detail, confidence=confidence, source="auto",
            follow_up_after_hours=max(1.0, min(720.0, hours)), db_path=db_path))
    return {"loops": created, "skipped": skipped, "error": ""}


def generate_follow_up(inst: dict, loop_id: str, db_path=None) -> dict:
    """为一条未完成话题生成不超过 40 字的私聊回访文案。"""
    loop = get_loop(loop_id, db_path=db_path)
    if loop is None:
        raise PresenceError("未完成话题不存在")
    if _thread_takeover(str(loop["instance_id"]), str(loop["platform"]),
                        str(loop.get("thread_key") or ""), db_path):
        raise PresenceError("会话已被收件箱接管，不能生成回访")
    relation = get_relation(str(loop["instance_id"]), str(loop["platform"]),
                            str(loop["person_key"]), db_path=db_path) or {}
    nickname = str(relation.get("nickname") or relation.get("display_name") or "")
    system = (
        "你在替一个真实的人写一条私聊回访。只输出这一句话本身：不超过 40 个字，"
        "自然口语，最多带一个轻问题；不要编造新事实、不要提“回访/话题/系统/AI”，"
        "不要施压、不要连续追问、不要使用括号说明。"
    )
    memory_lines, _, _ = _memory_context(inst, db_path=db_path)
    user = _json({
        "对方称呼": nickname or str(loop["person_key"]),
        "关系阶段": relation.get("stage") or "stranger",
        "未完成话题": loop["topic"],
        "细节": loop.get("detail") or "",
        "记忆摘要": memory_lines,
    })
    try:
        provider_id = _pick_provider(inst, str(loop["instance_id"]),
                                     db_path=db_path)
        raw = llm.chat(inst, provider_id, [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=160, timeout=15)
    except Exception as exc:  # noqa: BLE001 - 统一转成 PresenceError
        raise PresenceError(f"生成回访失败：{exc}") from None
    text = _clean_followup_text(raw)
    if not text:
        raise PresenceError("模型没有生成回访文案")
    return update_loop(loop_id, {
        "follow_up_text": text,
        "follow_up_generated_at": time.time(),
    }, db_path=db_path)


# ------------------------------------------------------------- 到期回访


def _hhmm(value) -> int | None:
    text = str(value or "").strip()
    if not _TIME_RE_HHMM.fullmatch(text):
        return None
    return int(text[:2]) * 60 + int(text[3:])


def _in_window(minute: int, start: int | None, end: int | None) -> bool:
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def _dashboard_list(payload) -> list:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("plugins", "items", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _proactive_conflict(inst: dict | None, call=None) -> bool:
    """检测 proactive_chat 是否已开启私聊主动消息；任何读取失败按不冲突处理。"""
    if not isinstance(inst, dict):
        return False
    call = call or dashboard.call
    try:
        items = _dashboard_list(call(inst, "GET", "plugins", timeout=10))
        target = None
        for item in items:
            if not isinstance(item, dict):
                continue
            plugin_id = str(item.get("id") or item.get("name") or "")
            if plugin_id == PROACTIVE_PLUGIN_ID or plugin_id.endswith(
                    "_proactive_chat"):
                target = item
                break
        if target is None:
            return False
        enabled = target.get("activated", target.get("enabled"))
        if isinstance(enabled, bool) and not enabled:
            return False
        result = call(inst, "GET", "plugins/config",
                      query={"plugin_id": PROACTIVE_PLUGIN_ID}, timeout=10)
        data = result.get("data") if isinstance(result, dict) else None
        config = (data or {}).get("config") if isinstance(data, dict) else None
        friend = config.get("friend_settings") if isinstance(config, dict) else None
        return bool(isinstance(friend, dict) and friend.get("enable"))
    except Exception:  # noqa: BLE001 - Dashboard 不可用时不能阻断回访判断
        return False


def _looks_group_thread(thread_key: str) -> bool:
    key = str(thread_key or "")
    return key.startswith("group:") or ":GroupMessage:" in key


def _thread_takeover(instance_id: str, platform: str, thread_key: str,
                     db_path=None) -> bool:
    """只读检查收件箱是否已接管该会话；查询失败按未接管处理。

    Args:
        instance_id: 管理器实例 ID，对应 inbox_threads.account_id。
        platform: 平台标识，例如 ``qq``。
        thread_key: 会话 UMO；为空时不查库。
        db_path: 测试用临时数据库路径。

    Returns:
        该会话 takeover=1 时返回 True。
    """
    thread_key = str(thread_key or "").strip()
    if not thread_key:
        return False
    try:
        with fleet_store.session(db_path) as conn:
            row = conn.execute(
                "SELECT takeover FROM inbox_threads WHERE account_id=? "
                "AND platform=? AND thread_key=?",
                (instance_id, platform, thread_key),
            ).fetchone()
    except Exception:  # noqa: BLE001 - 接管状态只是附加约束
        return False
    return bool(row and int(row["takeover"] or 0))


def due_followups(instance_id: str, now=None, inst: dict | None = None,
                  db_path=None, call=None) -> dict:
    """返回真实模式下可发送的到期回访；影子模式恒为空。"""
    instance_id = _text(instance_id, "instance_id", required=True)
    now = time.time() if now is None else float(now)
    settings = get_settings(instance_id, db_path=db_path)
    if settings["followup_shadow"]:
        return {"loops": [], "shadow": True, "blocked_reason": ""}
    loops = list_loops(instance_id, status="open", limit=500, db_path=db_path)
    if not loops:
        return {"loops": [], "shadow": False, "blocked_reason": ""}
    if _proactive_conflict(inst, call):
        return {"loops": [], "shadow": False,
                "blocked_reason": "proactive_chat_conflict"}
    week_start = now - 7 * 86400
    local = _dt.datetime.fromtimestamp(now)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with fleet_store.session(db_path) as conn:
        relations = {
            (row["platform"], row["person_key"]): _relation_row(row) or {}
            for row in conn.execute(
                "SELECT * FROM presence_relations WHERE instance_id=?",
                (instance_id,)).fetchall()
        }
        familiarity = {
            (row["platform"], row["person_key"]): float(row["familiarity"] or 0)
            for row in conn.execute(
                "SELECT platform, person_key, familiarity FROM human_relations "
                "WHERE instance_id=?", (instance_id,)).fetchall()
        }
        threads = {
            (row["platform"], row["thread_key"]): {
                "kind": row["kind"], "takeover": int(row["takeover"] or 0)}
            for row in conn.execute(
                "SELECT platform, thread_key, kind, takeover FROM inbox_threads "
                "WHERE account_id=?", (instance_id,)).fetchall()
        }
        sent_today: dict[str, int] = {}
        sent_week: dict[str, int] = {}
        for row in conn.execute(
                "SELECT person_key, created FROM presence_events WHERE instance_id=? "
                "AND kind='followup_sent' AND created>=?",
                (instance_id, week_start)).fetchall():
            person = str(row["person_key"] or "")
            sent_week[person] = sent_week.get(person, 0) + 1
            if float(row["created"]) >= day_start:
                sent_today[person] = sent_today.get(person, 0) + 1
    minute = local.hour * 60 + local.minute
    if _in_window(minute, _hhmm(settings["quiet_start"]),
                  _hhmm(settings["quiet_end"])):
        return {"loops": [], "shadow": False, "blocked_reason": ""}
    picked: set[str] = set()
    out: list[dict] = []
    generated = 0
    threshold = float(settings["familiarity_threshold"])
    quiet_after = float(settings["quiet_after_hours"]) * 3600
    for loop in loops:
        person = str(loop.get("person_key") or "")
        if person in picked:
            continue
        if float(loop.get("follow_up_after") or 0) > now:
            continue
        relation = relations.get((str(loop.get("platform") or ""), person))
        if not relation or not relation.get("followup_enabled"):
            continue
        if familiarity.get((str(loop.get("platform") or ""), person), 0.0) < threshold:
            continue
        thread = threads.get(
            (str(loop.get("platform") or ""), str(loop.get("thread_key") or "")))
        if thread is not None:
            if thread["kind"] == "group" or thread["takeover"]:
                continue
        elif _looks_group_thread(str(loop.get("thread_key") or "")):
            continue
        last_seen = float(relation.get("last_seen") or 0)
        if last_seen and now - last_seen < quiet_after:
            continue
        if sent_today.get(person, 0) >= int(settings["daily_limit"]):
            continue
        if sent_week.get(person, 0) >= int(settings["weekly_limit"]):
            continue
        text = str(loop.get("follow_up_text") or "")
        if not text:
            # 每次 due 最多现场生成一条，避免插件轮询被多条模型调用拖过超时；
            # 其余到期话题留给下一轮轮询。
            if inst is None or generated >= 1:
                continue
            try:
                loop = generate_follow_up(inst, loop["id"], db_path=db_path)
            except PresenceError:
                continue
            generated += 1
        picked.add(person)
        out.append(loop)
    return {"loops": out, "shadow": False, "blocked_reason": ""}


def mark_sent(loop_id: str, db_path=None) -> dict:
    loop = get_loop(loop_id, db_path=db_path)
    if loop is None:
        raise PresenceError("未完成话题不存在")
    now = time.time()
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "UPDATE presence_loops SET follow_up_count=follow_up_count+1, "
            "last_follow_up_at=? WHERE id=?", (now, loop["id"]))
    add_event(str(loop["instance_id"]), "followup_sent",
              person_key=str(loop["person_key"]),
              payload={"loop_id": loop["id"], "topic": loop["topic"],
                       "text": str(loop.get("follow_up_text") or "")},
              db_path=db_path)
    return get_loop(loop_id, db_path=db_path) or {}


def send_now(inst: dict, loop_id: str, call=None, db_path=None) -> dict:
    """确认后调用 presence 插件发送一条私聊回访，再标记已发送。"""
    loop = get_loop(loop_id, db_path=db_path)
    if loop is None:
        raise PresenceError("未完成话题不存在")
    if str(loop.get("instance_id") or "") != str(inst.get("id") or ""):
        raise PresenceError("未完成话题不属于该实例")
    if _thread_takeover(str(loop.get("instance_id") or ""),
                        str(loop.get("platform") or "qq"),
                        str(loop.get("thread_key") or ""), db_path):
        raise PresenceError("会话已被收件箱接管，不能发送回访")
    text = str(loop.get("follow_up_text") or "")
    if not text:
        loop = generate_follow_up(inst, loop_id, db_path=db_path)
        text = str(loop.get("follow_up_text") or "")
    call = call or dashboard.call
    path = f"plugins/extensions/{PRESENCE_PLUGIN_ID}/send"
    try:
        result = call(inst, "POST", path, {
            "umo": str(loop.get("thread_key") or ""),
            "text": text,
            "loop_id": loop["id"],
        }, timeout=30)
    except dashboard.DashboardError as exc:
        raise PresenceError(f"调用回访插件失败：{exc.message}") from None
    if isinstance(result, dict):
        if str(result.get("status") or "") == "error":
            raise PresenceError(str(result.get("message") or "回访插件返回错误"))
        data = result.get("data")
        if isinstance(data, dict):
            if str(data.get("status") or "") == "error":
                raise PresenceError(str(data.get("message") or "回访插件返回错误"))
            if data.get("sent") is False:
                raise PresenceError("回访插件未确认发送")
    return mark_sent(loop_id, db_path=db_path)


# --------------------------------------------------------------- 自我日记


def generate_diary(inst: dict, date: str | None = None, force: bool = False,
                   db_path=None) -> dict:
    """汇总当天事件生成只给管理器看的日记；事件不足且未 force 时跳过。"""
    if not isinstance(inst, dict) or not inst.get("id"):
        raise PresenceError("instance_id 不能为空")
    instance_id = str(inst["id"])
    now = time.time()
    date = _date(date) if date else time.strftime("%Y-%m-%d", time.localtime(now))
    day = _dt.date.fromisoformat(date)
    start = _dt.datetime.combine(day, _dt.time.min).timestamp()
    end = start + 86400
    settings = get_settings(instance_id, db_path=db_path)
    with fleet_store.session(db_path) as conn:
        event_rows = conn.execute(
            "SELECT * FROM human_mood_events WHERE instance_id=? AND created>=? "
            "AND created<? ORDER BY created", (instance_id, start, end)).fetchall()
        milestone_rows = conn.execute(
            "SELECT * FROM presence_milestones WHERE instance_id=? AND occurred_at>=? "
            "AND occurred_at<? ORDER BY occurred_at", (instance_id, start, end)).fetchall()
    loops = list_loops(instance_id, status="open", limit=10, db_path=db_path)
    events = []
    for row in event_rows:
        assessment = _loads(row["assessment_json"], {})
        events.append({
            "mood": str((assessment or {}).get("mood") or ""),
            "reason": str((assessment or {}).get("reason") or "")[:80],
            "tone": str((assessment or {}).get("tone_hint") or "")[:60],
        })
    milestones = [dict(row) for row in milestone_rows]
    if not settings["diary_enabled"] and not force:
        return {"skipped": True, "date": date, "reason": "日记已关闭"}
    if len(events) + len(milestones) + min(len(loops), 5) < 2 and not force:
        return {"skipped": True, "date": date, "reason": "当天事件不足"}
    # 只读 LivingMemory 摘要；不写记忆、不改人格。
    memory_lines, memory_ids, relation_lines = _memory_context(inst, db_path=db_path)
    system = (
        "你在写今天只给自己看的日记。用中文写 200–500 字，第一人称，语气自然；"
        "只依据给定的事件，不编造没有发生的事，不声称真实的线下行动，"
        "不要提出插件、模型、系统或提示词。再写一句不超过 120 字、"
        "不含任何人名或昵称的摘要，供明天参考。只输出 JSON："
        '{"text":"日记正文","summary":"一句摘要"}。'
    )
    user = _json({
        "日期": date,
        "心情事件": events[:30],
        "未完成话题": [item.get("topic") for item in loops],
        "里程碑": [{"kind": item.get("kind"), "title": item.get("title")}
                   for item in milestones[:20]],
        "记忆摘要": memory_lines,
        "关系摘要": relation_lines,
    })
    try:
        provider_id = _pick_provider(inst, instance_id, db_path=db_path)
        raw = llm.chat(inst, provider_id, [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=900, timeout=15)
        data = _decode_json_object(raw)
    except Exception as exc:  # noqa: BLE001
        raise PresenceError(f"生成日记失败：{exc}") from None
    text = str(data.get("text") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if not text:
        raise PresenceError("日记正文为空")
    if not summary:
        raise PresenceError("日记摘要为空")
    text = text[:int(settings["diary_max_chars"])]
    summary = summary[:_DIARY_MAX_SUMMARY]
    latest = events[-1]["mood"] if events else "calm"
    diary = upsert_diary(
        instance_id, date, text,
        mood={"mood": latest, "summary": summary, "source": "auto"},
        memory_ids=memory_ids, model_id=provider_id, db_path=db_path)
    return {"skipped": False, "date": date, "diary": diary}


# ------------------------------------------------------------- 群聊雷达


def radar_events(payload: dict, instances=None, db_path=None) -> dict:
    if not isinstance(payload, dict):
        raise PresenceError("雷达上报必须是对象")
    pool = instances if instances is not None else store.load_instances()
    inst = mood.resolve_instance(payload, pool)
    instance_id = str(inst.get("id") or "")
    items = payload.get("events")
    if items is None:
        items = [payload]
    if not isinstance(items, list):
        raise PresenceError("events 必须是数组")
    saved = 0
    for item in items[:100]:
        if not isinstance(item, dict):
            raise PresenceError("雷达事件必须是对象")
        kind = _text(item.get("kind"), "kind", required=True, limit=40)
        if kind not in _RADAR_KINDS:
            raise PresenceError("雷达事件 kind 无效")
        add_event(instance_id, kind,
                  group_id=_text(item.get("group_id") or "", "group_id", limit=200),
                  person_key=_text(item.get("person_key") or "", "person_key",
                                   limit=200),
                  payload=item.get("payload") or {},
                  db_path=db_path)
        saved += 1
    settings = get_settings(instance_id, db_path=db_path)
    pruned = prune_events(instance_id, retention_days=settings["radar_retention_days"],
                          db_path=db_path)
    return {"saved": saved, "pruned": pruned}


def radar_stats(instance_id: str, days=7, db_path=None) -> dict:
    instance_id = _text(instance_id, "instance_id", required=True)
    days = int(max(1, min(int(days), 90)))
    since = time.time() - days * 86400
    items = list_events(instance_id, since=since, limit=500, db_path=db_path)
    reply = sum(1 for item in items if item.get("kind") == "radar_reply")
    silent = sum(1 for item in items if item.get("kind") == "radar_silent")
    groups: dict[str, dict] = {}
    for item in items:
        group_id = str(item.get("group_id") or "")
        entry = groups.setdefault(group_id, {
            "group_id": group_id, "reply": 0, "silent": 0})
        if item.get("kind") == "radar_reply":
            entry["reply"] += 1
        elif item.get("kind") == "radar_silent":
            entry["silent"] += 1
    return {
        "window_days": days,
        "reply": reply,
        "silent": silent,
        "total": reply + silent,
        "groups": sorted(groups.values(),
                         key=lambda item: item["reply"] + item["silent"],
                         reverse=True),
        "recent": items[:50],
    }


# --------------------------------------------------- group_chat_plus 白名单


def _gc_schema_path(inst: dict | None = None) -> Path:
    """优先读目标实例自己的插件 schema，再回退到管理器配置的 AstrBot 目录。"""
    roots: list[str] = []
    if isinstance(inst, dict):
        root = str(inst.get("root") or "").strip()
        if root:
            roots.append(root)
    source = str(store.load_settings().get("astrbot_source") or "").strip()
    if source and source not in roots:
        roots.append(source)
    if not roots:
        raise PresenceError("未配置 AstrBot 源码目录，无法读取群聊插件 schema")
    candidates = [
        Path(root) / "data" / "plugins" / GC_PLUGIN_ID / "_conf_schema.json"
        for root in roots
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise PresenceError(f"未找到群聊插件配置 schema：{candidates[0]}")


def _load_gc_schema(path=None, inst=None) -> dict:
    target = Path(path) if path else _gc_schema_path(inst)
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise PresenceError(f"未找到群聊插件配置 schema：{target}") from None
    except Exception as exc:  # noqa: BLE001
        raise PresenceError(f"读取群聊插件配置 schema 失败：{exc}") from None
    if not isinstance(data, dict):
        raise PresenceError("群聊插件配置 schema 格式无效")
    return data


def gc_allowed_keys(schema=None, path=None, inst=None) -> list[str]:
    """只返回 _conf_schema.json 中真实存在的白名单键，未列出的键一律拒绝。"""
    schema = schema if isinstance(schema, dict) else _load_gc_schema(path, inst)
    return [key for key in GC_KEY_CANDIDATES if key in schema]


def gc_config(inst: dict, call=None, schema=None, path=None) -> dict:
    allowed = gc_allowed_keys(schema, path, inst)
    call = call or dashboard.call
    try:
        result = call(inst, "GET", "plugins/config",
                      query={"plugin_id": GC_PLUGIN_ID}, timeout=30)
    except dashboard.DashboardError as exc:
        raise PresenceError(f"读取群聊插件配置失败：{exc.message}") from None
    data = result.get("data") if isinstance(result, dict) else None
    raw = (data or {}).get("config") if isinstance(data, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    return {
        "plugin_id": GC_PLUGIN_ID,
        "allowed_keys": allowed,
        "config": {key: raw.get(key) for key in allowed if key in raw},
    }


def save_gc_config(inst: dict, patch: dict, call=None, schema=None,
                   path=None) -> dict:
    if not isinstance(patch, dict):
        raise PresenceError("config 必须是对象")
    allowed = gc_allowed_keys(schema, path, inst)
    unknown = [key for key in patch if key not in allowed]
    if unknown:
        raise PresenceError(f"不允许修改配置项：{unknown[0]}")
    call = call or dashboard.call
    try:
        current = call(inst, "GET", "plugins/config",
                       query={"plugin_id": GC_PLUGIN_ID}, timeout=30)
        data = current.get("data") if isinstance(current, dict) else None
        raw = (data or {}).get("config") if isinstance(data, dict) else None
        if not isinstance(raw, dict) or not raw:
            # 读不到完整配置时拒绝 PUT，避免只带白名单键覆盖掉插件其余设置。
            raise PresenceError("群聊插件配置为空，拒绝覆盖")
        merged = dict(raw)
        merged.update(patch)
        call(inst, "PUT", "plugins/config",
             {"plugin_id": GC_PLUGIN_ID, "config": merged}, timeout=60)
    except dashboard.DashboardError as exc:
        raise PresenceError(f"保存群聊插件配置失败：{exc.message}") from None
    return {
        "plugin_id": GC_PLUGIN_ID,
        "allowed_keys": allowed,
        "config": {key: merged.get(key) for key in allowed if key in merged},
    }
