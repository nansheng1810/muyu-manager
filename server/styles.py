"""独立说话风格档案；不写人格。"""

from __future__ import annotations

import time
import uuid

from . import fleet_store

SCOPES = {"instance", "relationship"}
SOURCES = {"manual", "auto", "migration"}
MAX_NOTE = 12000
MAX_PROMPT = 1200
APPEND_SEPARATOR = "\n\n---\n\n"


class StyleError(Exception):
    pass


def _enabled(value) -> int:
    """严格布尔语义：仅接受 bool 或 0/1，字符串等其他输入一律拒绝。"""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and value in (0, 1):
        return value
    raise StyleError("enabled 必须是布尔值或 0/1")


def _text(value, label: str, max_len: int | None = None, allow_empty: bool = False) -> str:
    """校验并归一化文本字段，拒绝非字符串与空值。"""
    if not isinstance(value, str):
        raise StyleError(f"{label}必须是字符串")
    text = str(value or "").strip()
    if not text and not allow_empty:
        raise StyleError(f"{label}不能为空")
    if max_len is not None and len(text) > max_len:
        raise StyleError(f"{label}不能超过 {max_len} 字")
    return text


def _style(row) -> dict | None:
    return dict(row) if row is not None else None


def get_style(style_id: str, db_path=None) -> dict | None:
    with fleet_store.session(db_path) as conn:
        return _style(conn.execute("SELECT * FROM style_profiles WHERE id=?", (style_id,)).fetchone())


def list_styles(instance_id: str, db_path=None) -> list[dict]:
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM style_profiles WHERE instance_id=? ORDER BY updated DESC",
            (instance_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_style(instance_id, name, note, scope="instance", person_key="",
               source="manual", enabled=True, db_path=None) -> dict:
    instance_id = str(instance_id or "").strip()
    name = str(name or "").strip()[:80]
    note = str(note or "").strip()
    scope = str(scope or "instance")
    person_key = str(person_key or "").strip()
    if not instance_id or not name or not note:
        raise StyleError("实例、名称和内容不能为空")
    if scope not in SCOPES:
        raise StyleError("作用域无效")
    if scope == "relationship" and not person_key:
        raise StyleError("关系级风格需要 person_key")
    if source not in SOURCES:
        raise StyleError("来源无效")
    if len(note) > MAX_NOTE:
        raise StyleError(f"风格内容不能超过 {MAX_NOTE} 字")
    style_id = "sty_" + uuid.uuid4().hex[:12]
    now = time.time()
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO style_profiles(id, instance_id, scope, person_key, name, note, source, enabled, created, updated) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (style_id, instance_id, scope, person_key, name, note, source, _enabled(enabled), now, now),
        )
    return get_style(style_id, db_path=db_path) or {}


def update_style(style_id: str, patch: dict, db_path=None) -> dict:
    current = get_style(style_id, db_path=db_path)
    if not current:
        raise StyleError("风格档案不存在")
    if not isinstance(patch, dict):
        raise StyleError("更新内容必须是对象")
    name = str(current.get("name") or "").strip()
    note = str(current.get("note") or "").strip()
    person_key = str(current.get("person_key") or "").strip()
    scope = current.get("scope")
    enabled = _enabled(current.get("enabled"))
    if "name" in patch:
        name = _text(patch["name"], "名称")[:80]
    if "note" in patch:
        note = _text(patch["note"], "内容", max_len=MAX_NOTE)
    if "person_key" in patch:
        person_key = _text(patch["person_key"], "person_key", allow_empty=True)
    if "scope" in patch:
        scope = patch["scope"]
    if "enabled" in patch:
        enabled = _enabled(patch["enabled"])
    if not name or not note:
        raise StyleError("名称和内容不能为空")
    if scope not in SCOPES:
        raise StyleError("作用域无效")
    if scope == "relationship" and not person_key:
        raise StyleError("关系级风格需要 person_key")
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "UPDATE style_profiles SET name=?, note=?, scope=?, person_key=?, enabled=?, updated=? WHERE id=?",
            (name, note, scope, person_key, enabled, time.time(), style_id),
        )
    return get_style(style_id, db_path=db_path) or {}


def delete_style(style_id: str, db_path=None) -> bool:
    with fleet_store.session(db_path) as conn:
        cur = conn.execute("DELETE FROM style_profiles WHERE id=?", (style_id,))
        return bool(cur.rowcount)


def _trim_note(note: str, limit: int = MAX_NOTE) -> str:
    """保留最早的开头段落和最新的追加段落，超出上限时丢弃最旧的学习记录。"""
    text = str(note or "")
    if len(text) <= limit:
        return text
    parts = text.split(APPEND_SEPARATOR)
    head = parts[0]
    kept: list[str] = []
    total = len(head)
    for part in reversed(parts[1:]):
        addition = len(APPEND_SEPARATOR) + len(part)
        if total + addition > limit:
            break
        kept.insert(0, part)
        total += addition
    if kept:
        return head + APPEND_SEPARATOR + APPEND_SEPARATOR.join(kept)
    return text[:limit]


def append_style_note(style_id: str, note: str, label: str = "学习记录", db_path=None) -> dict:
    """把一次学习结果追加到同一风格档案；第一次由 save_style 新建。"""
    current = get_style(style_id, db_path=db_path)
    if not current:
        raise StyleError("风格档案不存在")
    text = str(note or "").strip()
    if not text:
        raise StyleError("学习内容不能为空")
    if len(text) > MAX_NOTE:
        raise StyleError(f"学习内容不能超过 {MAX_NOTE} 字")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    section = f"## {(label or '学习记录').strip()} · {stamp}\n{text}"
    base = str(current.get("note") or "").rstrip()
    merged = base + APPEND_SEPARATOR + section if base else section
    return update_style(style_id, {"note": _trim_note(merged)}, db_path=db_path)


def _prompt_note(note: str, limit: int) -> str:
    """风格提示优先使用最新追加的学习记录；没有追加历史时使用开头部分。"""
    text = str(note or "")
    if len(text) <= limit:
        return text
    parts = text.split(APPEND_SEPARATOR)
    if len(parts) == 1:
        return text[:limit]
    kept: list[str] = []
    total = 0
    for part in reversed(parts):
        addition = len(part) + (len(APPEND_SEPARATOR) if kept else 0)
        if total + addition > limit:
            break
        kept.insert(0, part)
        total += addition
    if kept:
        return APPEND_SEPARATOR.join(kept)
    return parts[-1][:limit]


def save_auto_style(instance_id: str, name: str, note: str, db_path=None) -> dict:
    instance_id = str(instance_id or "").strip()
    name = str(name or "").strip()[:80]
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM style_profiles WHERE instance_id=? AND source='auto' AND name=? "
            "ORDER BY updated DESC LIMIT 1",
            (instance_id, name),
        ).fetchone()
    if row:
        # 同名自动档案只追加：保留用户手动关闭的启用状态，学习不能把停用的档案重新打开
        return append_style_note(row["id"], note, label="自动学习", db_path=db_path)
    return save_style(instance_id, name, note, source="auto", db_path=db_path)


def style_prompt(instance_id: str, person_key: str = "", db_path=None) -> str:
    person_key = str(person_key or "").strip()
    items = [x for x in list_styles(instance_id, db_path=db_path) if x.get("enabled")]
    relation = [
        x for x in items
        if x["scope"] == "relationship" and person_key and x["person_key"] == person_key
    ]
    instance_items = [x for x in items if x["scope"] == "instance"]
    chosen = relation[:2] + instance_items[:2]
    if not chosen:
        return ""
    budget = MAX_PROMPT - len("【说话风格】\n") - sum(len(f"### {x['name']}\n") for x in chosen)
    per_item = max(200, budget // max(1, len(chosen)))
    text = "\n\n".join(
        f"### {x['name']}\n{_prompt_note(x['note'], per_item)}" for x in chosen
    )
    return ("【说话风格】\n" + text)[:MAX_PROMPT]
