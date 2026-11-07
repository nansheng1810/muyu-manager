"""聊天记录采样（QQ / B站私信），只用标准库，数据库仅只读打开。"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from . import store

MAX_TEXT = 500
SPEAKER_LIMIT = 12

# 群聊记录里常带「[时间 周x 时:分:秒] 昵称(ID:123): 正文」这类前缀，学习前要剥掉
_PREFIX_RE = re.compile(
    r"^(?:\[[^\]]{4,40}\]\s*)?[^\n:：]{1,40}\(ID:\d+\)\s*(?:【[^】]*】)?\s*[:：]\s*"
)
_AT_NOTE_RE = re.compile(r"^【@指向说明】[^：:]{0,80}[:：]\s*")
_AT_TAG_RE = re.compile(r"\[At:\d+\|[^\]]*\]")

BILI_PLUGIN_DIR = Path("data") / "plugin_data" / "astrbot_plugin_bilibili_ai_bot"


# ----------------------------------------------------------------- helpers


def _readonly(db_path: Path) -> sqlite3.Connection | None:
    try:
        if not db_path.exists():
            return None
        uri = "file:" + db_path.resolve().as_posix() + "?mode=ro&uri=true"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "select 1 from sqlite_master where type='table' and name=?", (name,)
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _fmt_time(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""
    text = str(value).strip()
    return text[:16] if text else ""


def _clean_line(line: str) -> str:
    text = _PREFIX_RE.sub("", line)
    text = _AT_NOTE_RE.sub("", text)
    text = _AT_TAG_RE.sub("", text)
    return text.strip()


def _text_of(raw) -> str:
    """解析 AstrBot 的两种消息 JSON 格式，只提取纯文本。"""
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return ""
    else:
        data = raw
    pieces: list[str] = []
    if isinstance(data, dict):
        for item in data.get("message") or []:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not text and isinstance(item.get("data"), dict):
                text = item["data"].get("text")
            if isinstance(text, str) and text.strip():
                pieces.append(text)
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("type") not in ("text", "plain"):
                continue
            text = item.get("text")
            if not text and isinstance(item.get("data"), dict):
                text = item["data"].get("text")
            if isinstance(text, str) and text.strip():
                pieces.append(text)
    lines = [_clean_line(line) for line in "".join(pieces).splitlines()]
    text = "\n".join(line for line in lines if line).strip()
    if not text or len(text) > MAX_TEXT:
        return ""
    return text


@lru_cache(maxsize=8)
def _bot_ids_cached(mtime: float, own_qq: str) -> frozenset[str]:
    ids = {own_qq} if own_qq else set()
    try:
        for item in store.load_instances():
            qq = str(item.get("qq") or "").strip()
            if qq:
                ids.add(qq)
    except Exception:
        pass
    return frozenset(ids)


def bot_ids(inst: dict) -> frozenset[str]:
    """舰队内所有机器人的 QQ。按 mtime 缓存，注册表变化后自动刷新。"""
    try:
        mtime = store.INSTANCES_PATH.stat().st_mtime
    except Exception:
        mtime = 0.0
    return _bot_ids_cached(mtime, str(inst.get("qq") or "").strip())


def _is_bot_sender(name: str, inst: dict, sender_id: str = "") -> bool:
    """过滤机器人自己的发言，避免学习到自己的口吻。

    首选 sender_id：QQ 消息历史里它稳定是发送者 QQ，能同时排除舰队内其它
    机器人（例如同群的二号机）。名字只做精确兜底，避免把「绯奈大肥鱼」
    这类普通群友误判成机器人。
    """
    sid = str(sender_id or "").strip()
    if sid and sid in bot_ids(inst):
        return True
    name = str(name or "").strip()
    if not name:
        return False
    if name == "AstrBot":
        return True
    inst_name = str(inst.get("name") or "").strip()
    return bool(inst_name and name == inst_name)


def _qq_conn(inst: dict) -> sqlite3.Connection | None:
    root = Path(str(inst.get("root") or ""))
    return _readonly(root / "data" / "data_v4.db")


def _speaker_rows(conn: sqlite3.Connection, user_id: str, inst: dict) -> list[dict]:
    rows = conn.execute(
        "select sender_id, sender_name, count(*) as n from platform_message_history "
        "where user_id=? and sender_name<>'' group by sender_id, sender_name "
        "order by n desc limit ?",
        (user_id, SPEAKER_LIMIT * 3),
    ).fetchall()
    merged: dict[str, int] = {}
    for row in rows:
        if _is_bot_sender(row["sender_name"], inst, row["sender_id"]):
            continue
        name = str(row["sender_name"] or "").strip()
        if name:
            merged[name] = merged.get(name, 0) + int(row["n"])
    return [
        {"name": name, "count": count}
        for name, count in sorted(merged.items(), key=lambda kv: -kv[1])[:SPEAKER_LIMIT]
    ]


# ------------------------------------------------------------------ bilibili


def _bili_dir(inst: dict) -> Path:
    return Path(str(inst.get("root") or "")) / BILI_PLUGIN_DIR


def _bili_messages(inst: dict) -> list[dict]:
    base = _bili_dir(inst)
    bot_name = str(inst.get("name") or "大肥鱼")
    messages: list[dict] = []
    seen: set[tuple[str, str]] = set()

    conn = _readonly(base / "bilibot.sqlite3")
    if conn is not None:
        try:
            if _has_table(conn, "events"):
                rows = conn.execute(
                    "select actor_name, content, created_at from events "
                    "where source_type='private' order by created_at asc"
                ).fetchall()
                for row in rows:
                    text = str(row["content"] or "").strip()
                    if not text or len(text) > MAX_TEXT:
                        continue
                    sender = str(row["actor_name"] or "").strip() or "B站用户"
                    seen.add((sender, text))
                    messages.append(
                        {
                            "time": _fmt_time(row["created_at"]),
                            "sender": sender,
                            "text": text,
                        }
                    )
        except Exception:
            pass
        finally:
            conn.close()

    try:
        log_path = base / "reply_log.json"
        if log_path.exists():
            entries = json.loads(log_path.read_text(encoding="utf-8-sig"))
        else:
            entries = []
    except Exception:
        entries = []
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            if str(item.get("channel") or "private") != "private":
                continue
            time_text = _fmt_time(item.get("time"))
            sender = str(item.get("username") or "").strip() or "B站用户"
            text = str(item.get("content") or "").strip()
            if text and len(text) <= MAX_TEXT and (sender, text) not in seen:
                seen.add((sender, text))
                messages.append({"time": time_text, "sender": sender, "text": text})
            reply = str(item.get("reply") or "").strip()
            if reply and len(reply) <= MAX_TEXT:
                messages.append({"time": time_text, "sender": bot_name, "text": reply})

    messages.sort(key=lambda m: m.get("time") or "")
    return messages


# ------------------------------------------------------------------ sources


def list_sources(inst: dict) -> dict:
    qq: list[dict] = []
    conn = _qq_conn(inst)
    if conn is not None:
        try:
            if _has_table(conn, "platform_message_history"):
                rows = conn.execute(
                    "select user_id, max(platform_id) as platform_id, count(*) as n, "
                    "max(created_at) as last_at from platform_message_history "
                    "where platform_id<>'webchat' group by user_id"
                ).fetchall()
                ids = bot_ids(inst)
                for row in rows:
                    user_id = str(row["user_id"])
                    speakers = _speaker_rows(conn, user_id, inst)
                    is_group = len(speakers) >= 3
                    count = int(row["n"])
                    if ids:
                        marks = ",".join("?" * len(ids))
                        bot_count = conn.execute(
                            "select count(*) from platform_message_history "
                            f"where user_id=? and sender_id in ({marks})",
                            (user_id, *ids),
                        ).fetchone()[0]
                        count = max(0, count - int(bot_count or 0))
                    qq.append(
                        {
                            "key": f"qq:{user_id}",
                            "user_id": user_id,
                            "platform_id": str(row["platform_id"]),
                            "label": f"{'群聊' if is_group else '私聊'} {user_id}",
                            "is_group": is_group,
                            "count": count,
                            "last_at": _fmt_time(row["last_at"]),
                            "speakers": speakers,
                        }
                    )
        except Exception:
            pass
        finally:
            conn.close()

    qq.sort(key=lambda item: item.get("last_at") or "", reverse=True)

    bili: list[dict] = []
    try:
        merged = _bili_messages(inst)
    except Exception:
        merged = []
    human = [m for m in merged if not _is_bot_sender(m["sender"], inst)]
    if human:
        counts: dict[str, int] = {}
        for msg in human:
            counts[msg["sender"]] = counts.get(msg["sender"], 0) + 1
        speakers = sorted(
            ({"name": name, "count": n} for name, n in counts.items()),
            key=lambda item: item["count"],
            reverse=True,
        )[:SPEAKER_LIMIT]
        bili.append(
            {
                "key": "bili:private",
                "label": "B站私信",
                "count": len(human),
                "last_at": max((m.get("time") or "" for m in human), default=""),
                "speakers": speakers,
            }
        )

    return {"qq": qq, "bili": bili}


# ------------------------------------------------------------------- sample


def _qq_messages(inst: dict, key: str, speaker: str, limit: int) -> list[dict]:
    user_id = key.split(":", 1)[1] if ":" in key else key
    conn = _qq_conn(inst)
    if conn is None:
        return []
    try:
        if not _has_table(conn, "platform_message_history"):
            return []
        sql = (
            "select created_at, sender_id, sender_name, content from platform_message_history "
            "where user_id=? and platform_id<>'webchat'"
        )
        params: list = [user_id]
        if speaker:
            sql += " and sender_name=?"
            params.append(speaker)
        sql += " order by random() limit ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        return []
    finally:
        conn.close()

    messages: list[dict] = []
    for row in rows:
        text = _text_of(row["content"])
        if not text:
            continue
        sender = str(row["sender_name"] or "").strip() or "未知"
        if not speaker and _is_bot_sender(sender, inst, row["sender_id"]):
            continue
        messages.append(
            {
                "time": _fmt_time(row["created_at"]),
                "sender": sender,
                "text": text,
            }
        )
    messages.sort(key=lambda m: m.get("time") or "")
    return messages


def sample(inst: dict, source: str, key: str, speaker: str = "", limit: int = 200) -> list[dict]:
    try:
        limit = max(1, min(int(limit), 500))
    except Exception:
        limit = 200
    speaker = str(speaker or "").strip()

    if source == "bili":
        messages = _bili_messages(inst)
        if speaker:
            messages = [m for m in messages if m["sender"] == speaker]
        else:
            messages = [m for m in messages if not _is_bot_sender(m["sender"], inst)]
        if len(messages) > limit:
            messages = random.sample(messages, limit)
        return messages

    if source == "qq":
        return _qq_messages(inst, key, speaker, limit)

    return []
