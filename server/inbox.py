"""统一收件箱：只读采集、会话状态与人工发送。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import dashboard, fleet_store
from .store import load_instances

PLATFORMS = {"qq", "bilibili", "douyin"}
DIRECTIONS = {"in", "out"}
SEND_LIMIT = 500
# 接管推送串行化：读库与调用插件在同一把锁内，避免一次 stale 推送覆盖刚开启的接管
_takeover_lock = threading.Lock()
# 已上报过的推送失败 (db_path, instance_id, platform) -> error，避免每 15 秒重复写事件
_push_failures: dict[tuple[str, str, str], str] = {}
_push_failures_lock = threading.Lock()


class InboxError(Exception):
    pass


def _thread_id(platform: str, account_id: str, thread_key: str) -> str:
    digest = hashlib.sha1(f"{platform}|{account_id}|{thread_key}".encode("utf-8")).hexdigest()[:16]
    return f"in_{digest}"


def _thread_row(row) -> dict | None:
    return dict(row) if row is not None else None


def get_thread(thread_id: str, db_path=None) -> dict | None:
    with fleet_store.session(db_path) as conn:
        return _thread_row(conn.execute("SELECT * FROM inbox_threads WHERE id=?", (thread_id,)).fetchone())


def upsert_thread(platform, account_id, thread_key, kind, display_name="", avatar="", db_path=None):
    """Create or refresh a thread row. All `ts` columns store epoch seconds."""
    if platform not in PLATFORMS or kind not in {"private", "group"}:
        raise InboxError("平台或会话类型无效")
    thread_id = _thread_id(platform, account_id, thread_key)
    now = time.time()
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO inbox_threads(id, platform, account_id, thread_key, kind, display_name, avatar, created, updated) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(platform, account_id, thread_key) DO UPDATE SET "
            "kind=excluded.kind, "
            "display_name=CASE WHEN excluded.display_name<>'' THEN excluded.display_name ELSE inbox_threads.display_name END, "
            "avatar=CASE WHEN excluded.avatar<>'' THEN excluded.avatar ELSE inbox_threads.avatar END, "
            "updated=excluded.updated",
            (thread_id, platform, account_id, thread_key, kind, display_name or "", avatar or "", now, now),
        )
    return get_thread(thread_id, db_path=db_path) or {}


def add_message(thread_id, platform, account_id, direction, sender_id, sender_name, text, ts, external_id, source, db_path=None):
    """Store one message for an existing thread; `ts` is epoch seconds.

    Returns True when the row was inserted and False when (platform, account_id,
    external_id) already existed. Other constraint violations (for example a NULL
    `source`) still raise instead of being silently dropped.
    """
    if direction not in DIRECTIONS:
        raise InboxError("消息方向无效")
    if not str(external_id or "").strip():
        raise InboxError("缺少外部消息 ID")
    message_id = "msg_" + uuid.uuid4().hex[:16]
    now = time.time()
    with fleet_store.session(db_path) as conn:
        if conn.execute("SELECT 1 FROM inbox_threads WHERE id=?", (thread_id,)).fetchone() is None:
            raise InboxError("会话不存在")
        cur = conn.execute(
            "INSERT INTO inbox_messages(id, thread_id, platform, account_id, direction, "
            "sender_id, sender_name, text, ts, external_id, source, created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(platform, account_id, external_id) DO NOTHING",
            (message_id, thread_id, platform, account_id, direction, sender_id or "", sender_name or "",
             str(text or "")[:4000], float(ts or now), str(external_id), source, now),
        )
        inserted = bool(cur.rowcount)
        if inserted:
            conn.execute(
                "UPDATE inbox_threads SET last_message_at=?, last_text=?, updated=? "
                "WHERE id=? AND last_message_at<=?",
                (float(ts or now), str(text or "")[:200], now, thread_id, float(ts or now)),
            )
    return inserted


def list_threads(platform="", kind="", query="", unread_only=False, limit=100,
                 db_path=None, instances=None):
    """List threads newest-first. `query` is a literal substring match (`instr`), so
    `%` and `_` are not treated as LIKE wildcards.

    Every row also carries `account_name`, resolved from `load_instances()` so two
    instances of the same platform can be told apart in the UI. It is joined in
    Python (no schema change) and falls back to the raw `account_id` when the
    instance has been removed from the store.

    Args:
        platform: optional platform filter (`qq`/`bilibili`/`douyin`).
        kind: optional `private`/`group` filter.
        query: literal substring searched in the display name and last text.
        unread_only: when true, keep only threads with at least one unread message.
        limit: page size, clamped to 1..300.
        db_path: optional fleet database path override.
        instances: optional instance list; loaded from the store when omitted.
    """
    where, params = [], []
    if platform:
        where.append("platform=?"); params.append(platform)
    if kind:
        where.append("kind=?"); params.append(kind)
    if query:
        where.append("(instr(display_name, ?)>0 OR instr(last_text, ?)>0)")
        params.extend([str(query), str(query)])
    inner = (
        "SELECT t.*, (SELECT COUNT(*) FROM inbox_messages m WHERE m.thread_id=t.id "
        "AND m.direction='in' AND m.ts>t.last_read_at) AS unread FROM inbox_threads t"
    )
    if where:
        inner += " WHERE " + " AND ".join(where)
    sql = "SELECT * FROM (" + inner + ")"
    if unread_only:
        sql += " WHERE unread>0"
    sql += " ORDER BY last_message_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 300)))
    with fleet_store.session(db_path) as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    names = {
        str(inst.get("id") or ""): str(inst.get("name") or inst.get("id") or "")
        for inst in (instances if instances is not None else load_instances())
    }
    for row in rows:
        account_id = str(row.get("account_id") or "")
        row["account_name"] = names.get(account_id) or account_id
    return rows


def thread_messages(thread_id, before=0, before_rowid=0, limit=50, db_path=None):
    """Return one ascending page of messages, selected newest-first.

    `ts` and `before` are epoch seconds. Each returned row carries `row_id` (the
    SQLite rowid). For exact paging when several messages share a timestamp, pass
    the oldest loaded message's `ts` as `before` together with its `row_id` as
    `before_rowid`; with only `before` the filter is inclusive (`ts<=before`) so
    no boundary message is skipped, at the cost of possibly repeating same-ts rows.
    """
    params = [thread_id]
    sql = "SELECT rowid AS row_id, * FROM inbox_messages WHERE thread_id=?"
    if before and before_rowid:
        sql += " AND (ts<? OR (ts=? AND rowid<?))"
        params.extend([float(before), float(before), int(before_rowid)])
    elif before:
        sql += " AND ts<=?"
        params.append(float(before))
    sql += " ORDER BY ts DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    with fleet_store.session(db_path) as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    return list(reversed(rows))


def mark_read(thread_id, db_path=None):
    """Mark a thread read; `last_read_at` is epoch seconds. Returns the thread or None."""
    now = time.time()
    with fleet_store.session(db_path) as conn:
        conn.execute("UPDATE inbox_threads SET last_read_at=?, updated=? WHERE id=?", (now, now, thread_id))
    return get_thread(thread_id, db_path=db_path)


def _cursor(source: str, db_path=None) -> float:
    """Read the incremental cursor (epoch seconds) of one collection source; 0 when unseen."""
    with fleet_store.session(db_path) as conn:
        row = conn.execute("SELECT cursor FROM inbox_source_state WHERE source=?", (source,)).fetchone()
    return float(row["cursor"]) if row else 0.0


def _set_cursor(source: str, cursor: float, db_path=None) -> None:
    """Persist the highest timestamp consumed for one collection source."""
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO inbox_source_state(source, cursor, updated) VALUES(?,?,?) "
            "ON CONFLICT(source) DO UPDATE SET cursor=excluded.cursor, updated=excluded.updated",
            (source, float(cursor), time.time()),
        )


def _readonly(path) -> sqlite3.Connection:
    """Open a LivingMemory SQLite file read-only so collection never writes the source.

    Raises:
        InboxError: when the source file does not exist.
    """
    target = Path(path)
    if not target.exists():
        raise InboxError(f"源库不存在：{target}")
    conn = sqlite3.connect("file:" + target.resolve().as_posix() + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def sync_livingmemory(inst, platform, source_db, db_path=None):
    """Append new QQ / Douyin messages from one LivingMemory database into the inbox.

    The source DB is opened read-only and rows at or after the stored cursor are
    scanned (`timestamp>=cursor`), so rows written in the same whole second after a
    sync are still picked up. Message dedupe relies on (platform, account_id,
    external_id), so boundary rows are rescanned and a repeated sync inserts nothing.

    Args:
        inst: instance dict; its `id` becomes the inbox `account_id`.
        platform: `"qq"` (platform `aiocqhttp`) or `"douyin"` (platform `douyin_dm`).
        source_db: path to the LivingMemory `conversations.db`.
        db_path: optional fleet database path override.

    Returns:
        {"source": str, "scanned": int, "inserted": int, "cursor": float}

    Raises:
        InboxError: for unsupported platforms or a missing source database.
    """
    if platform not in {"qq", "douyin"}:
        raise InboxError("LivingMemory 只支持 qq/douyin")
    account_id = str(inst.get("id") or "")
    source = f"lm-{platform}:{account_id}"
    cursor = _cursor(source, db_path=db_path)
    conn = _readonly(source_db)
    try:
        if platform == "qq":
            sql = ("SELECT rowid AS rid, * FROM messages WHERE platform='aiocqhttp' "
                   "AND (session_id LIKE '%:GroupMessage:%' OR session_id LIKE '%:FriendMessage:%') "
                   "AND timestamp>=? ORDER BY timestamp, rowid LIMIT 5000")
        else:
            sql = ("SELECT rowid AS rid, * FROM messages WHERE platform='douyin_dm' "
                   "AND timestamp>=? ORDER BY timestamp, rowid LIMIT 5000")
        rows = conn.execute(sql, (cursor,)).fetchall()
    finally:
        conn.close()
    inserted = 0
    max_cursor = cursor
    current_names: dict[str, str] = {}
    for row in rows:
        session_id = str(row["session_id"] or "")
        if not session_id:
            continue
        kind = "group" if ":GroupMessage:" in session_id else "private"
        role = str(row["role"] or "")
        if kind == "group":
            group_key = str(row["group_id"] or session_id.rsplit(":", 1)[-1])
            display = f"群 {group_key.rsplit(':', 1)[-1]}"
        elif role == "user":
            display = str(row["sender_name"] or "")
        else:
            # Outbound rows keep the peer's human name already stored (empty display is
            # ignored by upsert_thread); only a thread that never saw an inbound row
            # falls back to the session peer segment.
            if session_id not in current_names:
                stored = get_thread(_thread_id(platform, account_id, session_id), db_path=db_path) or {}
                current_names[session_id] = str(stored.get("display_name") or "")
            display = "" if current_names[session_id] else session_id.rsplit(":", 1)[-1]
        thread = upsert_thread(platform, account_id, session_id, kind, display, db_path=db_path)
        current_names[session_id] = str(thread.get("display_name") or "")
        direction = "in" if role == "user" else "out"
        if add_message(thread["id"], platform, account_id, direction,
                       str(row["sender_id"] or ""), str(row["sender_name"] or ""),
                       str(row["content"] or ""), float(row["timestamp"] or 0),
                       f"lm:{row['rid']}", "livingmemory", db_path=db_path):
            inserted += 1
        max_cursor = max(max_cursor, float(row["timestamp"] or 0))
    _set_cursor(source, max_cursor, db_path=db_path)
    return {"source": source, "scanned": len(rows), "inserted": inserted, "cursor": max_cursor}


def _parse_reply_time(value) -> float:
    """Parse a reply_log `time` ("YYYY-MM-DD HH:MM", local time) into epoch seconds.

    Returns:
        0.0 for empty or malformed values so one bad log entry cannot abort a sync.
    """
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M").timestamp()
    except (TypeError, ValueError):
        return 0.0


def sync_bili(inst, plugin_dir, db_path=None):
    """Append new B站 private messages from bilibot.sqlite3 and reply_log.json into the inbox.

    The plugin database is opened read-only. Inbound private events are rows with
    `source_type` `'private'` (written by the current plugin) or `'dm'` (older rows);
    the query selects `created_at>=cursor`, matching `sync_livingmemory`, so boundary
    rows are rescanned and deduped by (platform, account_id, external_id) and a
    same-second write after a sync is still picked up. Outbound private replies come
    from `reply_log.json`, which the plugin keeps to 500 entries: it is fully
    rescanned on every sync and deduped on sha1(time|mid|reply), so reply timestamps
    never advance the events cursor (a reply written later than an event must not
    hide that event from the next sync).

    Args:
        inst: instance dict; its `id` becomes the inbox `account_id`.
        plugin_dir: B站 plugin data directory holding bilibot.sqlite3 / reply_log.json.
        db_path: optional fleet database path override.

    Returns:
        {"source": str, "scanned": int, "inserted": int, "cursor": float}
    """
    plugin_dir = Path(plugin_dir)
    account_id = str(inst.get("id") or "")
    source = f"bili:{account_id}"
    cursor = _cursor(source, db_path=db_path)
    inserted = 0
    scanned = 0
    max_cursor = cursor
    db_file = plugin_dir / "bilibot.sqlite3"
    if db_file.exists():
        conn = _readonly(db_file)
        try:
            rows = conn.execute(
                "SELECT id, actor_id, actor_name, content, created_at FROM events "
                "WHERE source_type IN ('dm','private') AND created_at>=? "
                "ORDER BY created_at, id LIMIT 5000",
                (cursor,),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            scanned += 1
            key = str(row["actor_id"] or "")
            if not key:
                continue
            mid = key.rsplit(":", 1)[-1]
            thread = upsert_thread("bilibili", account_id, key, "private",
                                   str(row["actor_name"] or mid), db_path=db_path)
            if add_message(thread["id"], "bilibili", account_id, "in", mid,
                           str(row["actor_name"] or ""), str(row["content"] or ""),
                           float(row["created_at"] or 0), f"bili-event:{row['id']}",
                           "bili_events", db_path=db_path):
                inserted += 1
            max_cursor = max(max_cursor, float(row["created_at"] or 0))
    log_file = plugin_dir / "reply_log.json"
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            entries = []
        # Full rescan: no cursor, so a large reply `time` cannot skip event rows.
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or str(entry.get("channel") or "") != "private":
                continue
            scanned += 1
            mid = str(entry.get("mid") or "").strip()
            reply = str(entry.get("reply") or "").strip()
            if not mid or not reply:
                continue
            ts = _parse_reply_time(entry.get("time"))
            key = f"bili:{mid}"
            thread = upsert_thread("bilibili", account_id, key, "private",
                                   str(entry.get("username") or mid), db_path=db_path)
            external = "bili-reply:" + hashlib.sha1(
                f"{entry.get('time')}|{mid}|{reply}".encode("utf-8")
            ).hexdigest()
            if add_message(thread["id"], "bilibili", account_id, "out", mid,
                           str(entry.get("username") or ""), reply, ts, external,
                           "reply_log", db_path=db_path):
                inserted += 1
    _set_cursor(source, max_cursor, db_path=db_path)
    return {"source": source, "scanned": scanned, "inserted": inserted, "cursor": max_cursor}


def _instance_by_platform(platform_id, instances=None):
    """Resolve one instance by its AstrBot platform id (the UMO prefix).

    Args:
        platform_id: platform id reported by a plugin, e.g. `"大肥鱼"`.
        instances: optional instance list; loaded from the store when omitted.

    Returns:
        The first instance whose `platform_id` matches.

    Raises:
        InboxError: when `platform_id` is empty (an unconfigured instance must not
            swallow it) or no instance carries this platform id.
    """
    target = str(platform_id or "").strip()
    if not target:
        raise InboxError("platform_id 缺失")
    for inst in instances or load_instances():
        if str(inst.get("platform_id") or "").strip() == target:
            return inst
    raise InboxError(f"找不到 platform_id={platform_id} 的实例")


def sync_instance(inst, db_path=None):
    """Collect every local source of one instance and report per-source results.

    A failing source is reported as `{"source": ..., "error": ...}` instead of
    aborting the whole instance, so one broken plugin directory cannot hide the
    other platforms. An empty `root` is such an error: it is never resolved to the
    manager's current working directory, which could expose unrelated data.

    Args:
        inst: instance dict; `root` points at the AstrBot directory.
        db_path: optional fleet database path override.

    Returns:
        {"instance_id": str, "sources": [sync result or error dict, ...]}
    """
    root = str(inst.get("root") or "").strip()
    result = {"instance_id": inst.get("id"), "sources": []}
    if not root:
        result["sources"].append({"source": f"root:{inst.get('id')}", "error": "实例目录未配置"})
        return result
    root = Path(root)
    lm = root / "data" / "plugin_data" / "astrbot_plugin_livingmemory" / "conversations.db"
    if lm.exists():
        for platform in ("qq", "douyin"):
            try:
                result["sources"].append(sync_livingmemory(inst, platform, lm, db_path=db_path))
            except Exception as exc:
                result["sources"].append({"source": f"lm-{platform}:{inst.get('id')}", "error": str(exc)})
    bili = root / "data" / "plugin_data" / "astrbot_plugin_bilibili_ai_bot"
    if bili.exists():
        try:
            result["sources"].append(sync_bili(inst, bili, db_path=db_path))
        except Exception as exc:
            result["sources"].append({"source": f"bili:{inst.get('id')}", "error": str(exc)})
    return result


def sync_all(instances=None, db_path=None):
    """Sync every instance; returns one `sync_instance` result per instance."""
    return [sync_instance(inst, db_path=db_path) for inst in (instances or load_instances())]


def ingest_message(payload, db_path=None, instances=None):
    """Store one message reported by a takeover plugin (QQ / B站 / 抖音).

    The target account is resolved by `account_id` first and by `platform_id`
    (the AstrBot platform id) second. Dedupe is the same as collection:
    (platform, account_id, external_id). Group threads are labelled from the
    thread key (`群 <peer id>`) so a later LivingMemory sync does not flip the
    name back and forth; only private threads take the sender nickname.

    Args:
        payload: plugin report with platform / thread_key / text / external_id
            plus optional platform_id, account_id, kind, sender_* and ts.
        db_path: optional fleet database path override.
        instances: optional instance list; loaded from the store when omitted.

    Returns:
        {"thread": dict, "inserted": bool, "message": {"thread_id", "text", "external_id"}}

    Raises:
        InboxError: for an unknown platform, a missing instance, missing fields
            or a non-numeric `ts`.
    """
    platform = str(payload.get("platform") or "")
    if platform not in PLATFORMS:
        raise InboxError("平台无效")
    inst = None
    if payload.get("account_id"):
        inst = next((x for x in (instances or load_instances()) if x.get("id") == payload["account_id"]), None)
    if inst is None:
        inst = _instance_by_platform(payload.get("platform_id"), instances)
    thread_key = str(payload.get("thread_key") or "").strip()
    text = str(payload.get("text") or "").strip()
    external_id = str(payload.get("external_id") or "").strip()
    if not thread_key or not text or not external_id:
        raise InboxError("thread_key/text/external_id 缺失")
    try:
        ts = float(payload.get("ts") or time.time())
    except (TypeError, ValueError):
        raise InboxError("ts 无效") from None
    kind = str(payload.get("kind") or "private")
    sender_name = str(payload.get("sender_name") or "")
    display = f"群 {thread_key.rsplit(':', 1)[-1]}" if kind == "group" else sender_name
    thread = upsert_thread(platform, str(inst["id"]), thread_key, kind, display, db_path=db_path)
    inserted = add_message(thread["id"], platform, str(inst["id"]), "in",
                           str(payload.get("sender_id") or ""),
                           sender_name, text, ts, external_id,
                           "plugin_ingest", db_path=db_path)
    return {"thread": thread, "inserted": inserted,
            "message": {"thread_id": thread["id"], "text": text, "external_id": external_id}}


def sync_takeover(inst, platform, db_path=None, call=None):
    """Push every taken-over thread of one platform/account to its plugin.

    Plugin routes differ per platform: QQ receives UMOs, B站 receives mids and
    the Douyin plugin receives peer keys. Errors are returned instead of raised
    so one unreachable plugin cannot block the other platforms; an unknown
    platform is reported the same way instead of guessing a plugin route.

    AstrBot answers a missing plugin route with HTTP 200 and
    `{"status": "error", "message": "未找到该路由"}`, so a top-level or
    `data.status` error is treated as a failed push instead of a success.

    The takeover store is read and pushed under one module lock. A background
    `push_all_takeovers` that started with a stale key set therefore cannot
    reach the plugin after a `set_takeover` push that already included the new
    key: whichever push runs last read the store while holding the lock.

    Args:
        inst: instance dict; its `id` is the inbox `account_id`.
        platform: one of `qq`/`bilibili`/`douyin`.
        db_path: optional fleet database path override.
        call: injectable dashboard caller, defaults to `dashboard.call`.

    Returns:
        One-element list `[{"platform", "ok", "keys"[, "error"]}]`.
    """
    call = call or dashboard.call
    if platform not in PLATFORMS:
        return [{"platform": platform, "ok": False, "error": "平台无效", "keys": []}]
    with _takeover_lock:
        with fleet_store.session(db_path) as conn:
            rows = conn.execute(
                "SELECT thread_key FROM inbox_threads WHERE platform=? AND account_id=? AND takeover=1",
                (platform, str(inst.get("id"))),
            ).fetchall()
        keys = [str(row["thread_key"]) for row in rows]
        if platform == "qq":
            path = "plugins/extensions/astrbot_plugin_fleet_inbox/takeover"
            payload = {"umos": keys, "account_id": str(inst.get("id") or "")}
        elif platform == "bilibili":
            path = "plugins/extensions/astrbot_plugin_bilibili_ai_bot/inbox/takeover"
            payload = {"mids": [key.removeprefix("bili:") for key in keys]}
        else:
            path = "plugins/extensions/astrbot_plugin_douyin_dm/inbox/takeover"
            payload = {"peer_keys": [key.rsplit(":", 1)[-1] for key in keys],
                       "account_id": str(inst.get("id") or "")}
        try:
            result = call(inst, "POST", path, payload, timeout=15)
        except Exception as exc:
            return [{"platform": platform, "ok": False, "error": str(exc), "keys": keys}]
    message = ""
    if isinstance(result, dict):
        data = result.get("data")
        failed = str(result.get("status") or "").lower() == "error"
        if isinstance(data, dict) and str(data.get("status") or "").lower() == "error":
            failed = True
            message = str(data.get("message") or "")
        message = str(result.get("message") or "") or message
        if failed:
            return [{"platform": platform, "ok": False,
                     "error": message or "插件拒绝接管", "keys": keys}]
    return [{"platform": platform, "ok": True, "keys": keys}]


def set_takeover(thread_id, enabled, db_path=None, instances=None, call=None):
    """Toggle manual takeover of one thread and resync that platform's plugin.

    The previous flag is remembered before the DB update. When the plugin does
    not confirm the push (HTTP error, or AstrBot's HTTP 200 `status:error` for a
    missing route), the flag is rolled back and `InboxError` is raised, so the
    UI never claims that automatic replies are paused.

    Args:
        thread_id: inbox thread id.
        enabled: truthy to enable takeover, falsy to restore automatic replies.
        db_path: optional fleet database path override.
        instances: optional instance list; loaded from the store when omitted.
        call: injectable dashboard caller, defaults to `dashboard.call`.

    Returns:
        {"thread": dict, "sync": list of plugin sync results}

    Raises:
        InboxError: when the thread does not exist, its account has no instance,
            or the plugin rejected the push (the flag is reverted first).
    """
    thread = get_thread(thread_id, db_path=db_path)
    if not thread:
        raise InboxError("会话不存在")
    inst = next((x for x in (instances or load_instances()) if x.get("id") == thread["account_id"]), None)
    if not inst:
        raise InboxError("实例不存在")
    previous = 1 if thread.get("takeover") else 0
    with fleet_store.session(db_path) as conn:
        conn.execute("UPDATE inbox_threads SET takeover=?, updated=? WHERE id=?",
                     (1 if enabled else 0, time.time(), thread_id))
    sync = sync_takeover(inst, thread["platform"], db_path=db_path, call=call)
    failures = [item for item in sync if not item.get("ok")]
    if failures:
        with fleet_store.session(db_path) as conn:
            conn.execute("UPDATE inbox_threads SET takeover=?, updated=? WHERE id=?",
                         (previous, time.time(), thread_id))
        detail = "; ".join(
            f"{item.get('platform')}: {item.get('error') or '插件拒绝接管'}" for item in failures
        )
        raise InboxError(f"插件未确认接管：{detail}")
    return {"thread": get_thread(thread_id, db_path=db_path), "sync": sync}


def push_all_takeovers(instances=None, db_path=None, call=None):
    """Replay the takeover state of every instance/platform to its plugin.

    Failed pushes are reported as `inbox` warn events. Only an error that is new
    for its (instance, platform) pair is written, so a plugin that stays
    unreachable across the 15 s sync loop cannot flood the event table while a
    fresh failure is still never silent.
    """
    out = []
    for inst in (instances or load_instances()):
        for platform in ("qq", "bilibili", "douyin"):
            results = sync_takeover(inst, platform, db_path=db_path, call=call)
            for item in results:
                key = (str(db_path or ""), str(inst.get("id") or ""), str(item.get("platform") or ""))
                if item.get("ok"):
                    with _push_failures_lock:
                        _push_failures.pop(key, None)
                    continue
                error = str(item.get("error") or "插件未确认接管")[:200]
                with _push_failures_lock:
                    if _push_failures.get(key) == error:
                        continue
                    _push_failures[key] = error
                fleet_store.add_event(
                    "inbox", "manager", "warn", "收件箱接管推送失败",
                    {"instance_id": key[1], "platform": key[2], "error": error},
                    key[1], db_path,
                )
            out.extend(results)
    return out


def _clean_text(text):
    """把一条人工回复压成单行并校验长度上限。

    Args:
        text: 输入框原文；`None` 视为空。

    Returns:
        去掉首尾空白、CR/LF 已替换为空格、其余 C0 控制字符与 DEL 已删除后的文本；
        普通空格与正文内部的空白保持不变。

    Raises:
        InboxError: 清洗后为空，或长度超过 `SEND_LIMIT`。
    """
    value = str(text or "").replace("\r", " ").replace("\n", " ")
    # 去掉 TAB/ESC/NUL 等 C0 控制字符（U+0000..U+001F）以及 DEL（U+007F），保留空格
    value = "".join(ch for ch in value if ch >= " " and ch != "\x7f").strip()
    if not value:
        raise InboxError("发送内容为空")
    if len(value) > SEND_LIMIT:
        raise InboxError(f"发送内容超过 {SEND_LIMIT} 字")
    return value


def send_message(thread_id, text, confirm, db_path=None, instances=None, call=None):
    """人工发送：校验通过后按平台路由发出，并落库、写审计事件。

    所有校验都在调用插件之前完成：请求必须带 `confirm="SEND"`，正文要能通过
    `_clean_text`，会话必须存在且已开启接管，其账号必须有对应实例。QQ 走
    AstrBot 开放接口（`im/messages`，UMO 即 thread_key），B站与抖音分别走各自
    插件的 `inbox/send` 路由。插件即使以 HTTP 200 返回 `{"status": "error"}` 也算
    发送失败。发送失败只报错一次、不重试、不写出站消息，避免收件箱里出现平台并未
    接受的消息。

    Args:
        thread_id: 收件箱会话 id。
        text: 纯文本正文；CR/LF 折成空格，1..`SEND_LIMIT` 字。
        confirm: 字面量 `"SEND"`，来自界面的二次确认。
        db_path: 可选的舰队库路径覆盖。
        instances: 可选的实例列表；省略时从 store 读取。
        call: 可注入的 dashboard 调用器，默认 `dashboard.call`。

    Returns:
        {"ok": True, "thread": 刷新后的会话行}

    Raises:
        InboxError: 确认词缺失、正文为空或超长、会话或平台未知、未开接管、实例
            缺失，或插件/dashboard 拒绝发送。
    """
    if str(confirm or "") != "SEND":
        raise InboxError("发送确认失败")
    text = _clean_text(text)
    thread = get_thread(thread_id, db_path=db_path)
    if not thread:
        raise InboxError("会话不存在")
    if not thread.get("takeover"):
        raise InboxError("请先开启人工接管")
    inst = next((x for x in (instances or load_instances()) if x.get("id") == thread["account_id"]), None)
    if not inst:
        raise InboxError("实例不存在")
    platform = thread["platform"]
    if platform not in PLATFORMS:
        raise InboxError("平台无效")
    call = call or dashboard.call
    try:
        if platform == "qq":
            result = call(inst, "POST", "im/messages", {
                "umo": thread["thread_key"],
                "message": [{"type": "plain", "text": text}],
            }, timeout=30)
        elif platform == "bilibili":
            result = call(inst, "POST", "plugins/extensions/astrbot_plugin_bilibili_ai_bot/inbox/send", {
                "mid": thread["thread_key"].removeprefix("bili:"), "text": text,
            }, timeout=30)
        else:
            result = call(inst, "POST", "plugins/extensions/astrbot_plugin_douyin_dm/inbox/send", {
                "peer_key": thread["thread_key"].rsplit(":", 1)[-1],
                "name": thread.get("display_name") or "",
                "text": text,
            }, timeout=30)
        # 插件可能以 HTTP 200 + {"status": "error"} 拒发，必须落到失败路径
        if isinstance(result, dict) and str(result.get("status") or "").lower() == "error":
            raise RuntimeError(result.get("message") or "插件拒绝发送")
    except Exception as exc:
        fleet_store.add_event("inbox", "manager", "warn", "收件箱发送失败",
                              {"thread_id": thread_id, "platform": platform,
                               "account_id": thread["account_id"], "error": str(exc)[:200]},
                              thread_id, db_path)
        raise InboxError(f"发送失败：{exc}") from exc
    now = time.time()
    external = "manager:" + hashlib.sha1(f"{thread_id}|{now}|{text}".encode("utf-8")).hexdigest()
    add_message(thread_id, platform, thread["account_id"], "out", "", "牧鱼", text,
                now, external, "manager_send", db_path=db_path)
    fleet_store.add_event("inbox", "manager", "info", "收件箱人工发送",
                          {"thread_id": thread_id, "platform": platform,
                           "account_id": thread["account_id"],
                           "text": text[:80], "chars": len(text)}, thread_id, db_path)
    return {"ok": True, "thread": get_thread(thread_id, db_path=db_path)}


# ------------------------------------------------------------ background sync

_sync_stop = threading.Event()
_sync_thread: threading.Thread | None = None
_sync_lock = threading.Lock()
_sync_state = {"last_sync": 0.0, "sources": [], "syncing": False, "error": ""}


def sync_once(instances=None, db_path=None):
    """Run one full sync; manual refresh and the background loop share this entry.

    Only one sync may run at a time. A caller that arrives while another sync
    holds the lock returns a `skipped` result immediately instead of queueing,
    so a slow sync cannot pile up status polls or refreshes behind it. Takeover
    state is replayed to the plugins here, before collection, so a plugin never
    keeps auto-replying to a thread the manager already shows as taken over.

    Args:
        instances: optional instance list; loaded from the store when omitted.
        db_path: optional fleet database path override.

    Returns:
        The `sync_all` result (one `sync_instance` dict per instance), or
        `{"skipped": True, "reason": "同步正在进行", ...last state}` when busy.

    Raises:
        Exception: whatever `push_all_takeovers` / `sync_all` raised, after the
            message is recorded in the cached state for `status()`.
    """
    if not _sync_lock.acquire(blocking=False):
        return {"skipped": True, "reason": "同步正在进行", **_sync_state}
    try:
        _sync_state["syncing"] = True
        instances = instances or load_instances()
        push_all_takeovers(instances, db_path=db_path)
        result = sync_all(instances, db_path=db_path)
        _sync_state.update(last_sync=time.time(), sources=result, error="")
        return result
    except Exception as exc:
        _sync_state.update(last_sync=time.time(), error=str(exc)[:300])
        raise
    finally:
        _sync_state["syncing"] = False
        _sync_lock.release()


def status():
    """Return a copy of the last sync state; never triggers a sync itself."""
    return dict(_sync_state)


def start_sync(interval: float = 15.0):
    """Start the daemon background sync loop; no-op when it is already running.

    Args:
        interval: seconds to wait between two syncs.
    """
    global _sync_thread
    if _sync_thread and _sync_thread.is_alive():
        return
    _sync_stop.clear()

    def loop():
        while not _sync_stop.wait(interval):
            try:
                sync_once(load_instances())
            except Exception:
                pass

    _sync_thread = threading.Thread(target=loop, daemon=True, name="inbox-sync")
    _sync_thread.start()


def stop_sync():
    """Ask the background sync loop to exit (its next wait returns immediately)."""
    _sync_stop.set()
