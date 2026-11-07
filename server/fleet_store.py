"""舰队共享运行数据：审批、事件与后续任务/备份/评测表。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import store

DB_PATH = store.DATA_DIR / "fleet_ops.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, ts REAL, kind TEXT, source TEXT, severity TEXT,
  title TEXT, detail_json TEXT, ref TEXT
);
CREATE TABLE IF NOT EXISTS approvals(
  id TEXT PRIMARY KEY, created REAL, updated REAL, status TEXT,
  category TEXT, title TEXT, target TEXT, payload_json TEXT,
  requested_by TEXT, reason TEXT, decision TEXT, decided_by TEXT,
  expires_at REAL, result_json TEXT
);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, name TEXT, kind TEXT, schedule TEXT,
  config_json TEXT, enabled INTEGER, last_run REAL, next_run REAL,
  created REAL, updated REAL
);
CREATE TABLE IF NOT EXISTS task_runs(
  id TEXT PRIMARY KEY, task_id TEXT, started REAL, finished REAL,
  status TEXT, summary TEXT, detail_json TEXT
);
CREATE TABLE IF NOT EXISTS backups(
  id TEXT PRIMARY KEY, created REAL, path TEXT, bytes INTEGER,
  sha256 TEXT, components_json TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS eval_runs(
  id TEXT PRIMARY KEY, created REAL, fixture TEXT, model TEXT,
  persona TEXT, score_json TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS duet_scenes(
  id TEXT PRIMARY KEY, mode TEXT, group_id TEXT, topic TEXT,
  status TEXT, config_json TEXT, note TEXT, created REAL, updated REAL
);
CREATE TABLE IF NOT EXISTS duet_turns(
  id TEXT PRIMARY KEY, scene_id TEXT, speaker TEXT, speaker_name TEXT,
  text TEXT, platform_message_id TEXT, status TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS duet_config(
  id INTEGER PRIMARY KEY CHECK(id=1), json TEXT, updated REAL
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id, started);
CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON eval_runs(created);
CREATE INDEX IF NOT EXISTS idx_duet_scenes_created ON duet_scenes(created);
CREATE INDEX IF NOT EXISTS idx_duet_turns_scene ON duet_turns(scene_id, created);
CREATE TABLE IF NOT EXISTS inbox_threads(
  id TEXT PRIMARY KEY, platform TEXT NOT NULL, account_id TEXT NOT NULL,
  thread_key TEXT NOT NULL, kind TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '', avatar TEXT NOT NULL DEFAULT '',
  last_message_at REAL NOT NULL DEFAULT 0, last_text TEXT NOT NULL DEFAULT '',
  last_read_at REAL NOT NULL DEFAULT 0, takeover INTEGER NOT NULL DEFAULT 0,
  created REAL NOT NULL, updated REAL NOT NULL,
  UNIQUE(platform, account_id, thread_key)
);
CREATE TABLE IF NOT EXISTS inbox_messages(
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, platform TEXT NOT NULL,
  account_id TEXT NOT NULL, direction TEXT NOT NULL,
  sender_id TEXT NOT NULL DEFAULT '', sender_name TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL, ts REAL NOT NULL, external_id TEXT NOT NULL,
  source TEXT NOT NULL, created REAL NOT NULL,
  UNIQUE(platform, account_id, external_id)
);
CREATE TABLE IF NOT EXISTS inbox_source_state(
  source TEXT PRIMARY KEY, cursor REAL NOT NULL DEFAULT 0, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inbox_threads_last ON inbox_threads(platform, kind, last_message_at);
CREATE INDEX IF NOT EXISTS idx_inbox_messages_thread ON inbox_messages(thread_id, ts);
CREATE TABLE IF NOT EXISTS style_profiles(
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'instance', person_key TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL, note TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual',
  enabled INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_style_profiles_instance ON style_profiles(instance_id, updated);
CREATE TABLE IF NOT EXISTS human_global(
  instance_id TEXT PRIMARY KEY, date TEXT NOT NULL, mood TEXT NOT NULL,
  intensity REAL NOT NULL, energy REAL NOT NULL, social REAL NOT NULL,
  source TEXT NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS human_relations(
  id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, platform TEXT NOT NULL,
  person_key TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
  anger REAL NOT NULL DEFAULT 0, affection REAL NOT NULL DEFAULT 0,
  familiarity REAL NOT NULL DEFAULT 0, last_thread TEXT NOT NULL DEFAULT '',
  last_seen REAL NOT NULL DEFAULT 0, updated REAL NOT NULL,
  UNIQUE(instance_id, platform, person_key)
);
CREATE TABLE IF NOT EXISTS human_mood_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, instance_id TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT '', person_key TEXT NOT NULL DEFAULT '',
  thread_key TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
  message_hash TEXT NOT NULL DEFAULT '', assessment_json TEXT NOT NULL DEFAULT '{}',
  before_json TEXT NOT NULL DEFAULT '{}', after_json TEXT NOT NULL DEFAULT '{}',
  error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS human_behavior_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, instance_id TEXT NOT NULL,
  thread_key TEXT NOT NULL DEFAULT '', action TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '', shadow INTEGER NOT NULL DEFAULT 1,
  created REAL NOT NULL, text_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS human_config(
  instance_id TEXT PRIMARY KEY, json TEXT NOT NULL, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_human_relations_instance ON human_relations(instance_id, last_seen);
CREATE INDEX IF NOT EXISTS idx_human_mood_events_instance ON human_mood_events(instance_id, created);
CREATE INDEX IF NOT EXISTS idx_human_behavior_events_instance ON human_behavior_events(instance_id, created);
CREATE TABLE IF NOT EXISTS presence_relations(
  id TEXT PRIMARY KEY,
  instance_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  person_key TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  nickname TEXT NOT NULL DEFAULT '',
  stage TEXT NOT NULL DEFAULT 'stranger',
  allow_memory INTEGER NOT NULL DEFAULT 1,
  followup_enabled INTEGER NOT NULL DEFAULT 1,
  first_seen REAL NOT NULL DEFAULT 0,
  last_seen REAL NOT NULL DEFAULT 0,
  message_count INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  traits_json TEXT NOT NULL DEFAULT '[]',
  tags_json TEXT NOT NULL DEFAULT '[]',
  likes TEXT NOT NULL DEFAULT '',
  dislikes TEXT NOT NULL DEFAULT '',
  boundaries TEXT NOT NULL DEFAULT '',
  recent_summary TEXT NOT NULL DEFAULT '',
  last_group_id TEXT NOT NULL DEFAULT '',
  updated REAL NOT NULL,
  UNIQUE(instance_id, platform, person_key)
);
CREATE TABLE IF NOT EXISTS presence_milestones(
  id TEXT PRIMARY KEY,
  instance_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  person_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  occurred_at REAL NOT NULL,
  source TEXT NOT NULL DEFAULT 'auto',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS presence_loops(
  id TEXT PRIMARY KEY,
  instance_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  person_key TEXT NOT NULL,
  thread_key TEXT NOT NULL,
  topic TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  confidence REAL NOT NULL DEFAULT 0.5,
  source TEXT NOT NULL DEFAULT 'auto',
  created REAL NOT NULL,
  last_seen REAL NOT NULL,
  follow_up_after REAL NOT NULL DEFAULT 0,
  follow_up_count INTEGER NOT NULL DEFAULT 0,
  last_follow_up_at REAL NOT NULL DEFAULT 0,
  follow_up_text TEXT NOT NULL DEFAULT '',
  follow_up_generated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS presence_diaries(
  id TEXT PRIMARY KEY,
  instance_id TEXT NOT NULL,
  date TEXT NOT NULL,
  text TEXT NOT NULL,
  mood_json TEXT NOT NULL DEFAULT '{}',
  memory_ids_json TEXT NOT NULL DEFAULT '[]',
  model_id TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL,
  updated REAL NOT NULL,
  UNIQUE(instance_id, date)
);
CREATE TABLE IF NOT EXISTS presence_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  instance_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  group_id TEXT NOT NULL DEFAULT '',
  person_key TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS presence_settings(
  instance_id TEXT PRIMARY KEY,
  json TEXT NOT NULL,
  updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_presence_relations_instance ON presence_relations(instance_id, last_seen);
CREATE INDEX IF NOT EXISTS idx_presence_milestones_person ON presence_milestones(instance_id, platform, person_key, occurred_at);
CREATE INDEX IF NOT EXISTS idx_presence_loops_due ON presence_loops(instance_id, status, follow_up_after);
CREATE INDEX IF NOT EXISTS idx_presence_diaries_instance ON presence_diaries(instance_id, date);
CREATE INDEX IF NOT EXISTS idx_presence_events_instance ON presence_events(instance_id, created);
CREATE INDEX IF NOT EXISTS idx_presence_events_kind ON presence_events(instance_id, kind, created);
"""

_init_lock = threading.Lock()
_initialized: set[str] = set()


def _path(db_path: str | Path | None = None) -> Path:
    return Path(db_path) if db_path else Path(DB_PATH)


def init(db_path: str | Path | None = None) -> None:
    path = _path(db_path)
    key = str(path.resolve())
    if key in _initialized:
        return
    with _init_lock:
        if key in _initialized:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=5)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(_SCHEMA)
            _migrate(conn)
            conn.commit()
        finally:
            conn.close()
        _initialized.add(key)


_RELATION_EXTRA_COLUMNS = {
    "aliases_json": "TEXT NOT NULL DEFAULT '[]'",
    "traits_json": "TEXT NOT NULL DEFAULT '[]'",
    "tags_json": "TEXT NOT NULL DEFAULT '[]'",
    "likes": "TEXT NOT NULL DEFAULT ''",
    "dislikes": "TEXT NOT NULL DEFAULT ''",
    "boundaries": "TEXT NOT NULL DEFAULT ''",
    "recent_summary": "TEXT NOT NULL DEFAULT ''",
    "last_group_id": "TEXT NOT NULL DEFAULT ''",
}


def _migrate(conn: sqlite3.Connection) -> None:
    """给老库补人物档案扩展列；新库创建时已包含这些列。"""
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(presence_relations)")
    }
    for name, ddl in _RELATION_EXTRA_COLUMNS.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE presence_relations ADD COLUMN {name} {ddl}")


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    init(db_path)
    conn = sqlite3.connect(_path(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def session(db_path: str | Path | None = None):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None) -> Any:
    try:
        return json.loads(value) if value else None
    except (TypeError, ValueError):
        return None


def add_event(kind: str, source: str, severity: str, title: str,
              detail: Any = None, ref: str = "", db_path: str | Path | None = None) -> int:
    with session(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO events(ts, kind, source, severity, title, detail_json, ref) VALUES(?,?,?,?,?,?,?)",
            (time.time(), kind, source, severity, title, _json(detail), ref),
        )
        return int(cur.lastrowid)


def add_approval(category: str, title: str, target: str, payload: Any,
                 requested_by: str = "", reason: str = "", ttl: int = 1800,
                 db_path: str | Path | None = None) -> dict:
    now = time.time()
    approval_id = f"ap_{uuid.uuid4().hex[:12]}"
    expires_at = now + max(1, int(ttl))
    with session(db_path) as conn:
        conn.execute(
            "INSERT INTO approvals(id, created, updated, status, category, title, target, "
            "payload_json, requested_by, reason, decision, decided_by, expires_at, result_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,'','',?,NULL)",
            (approval_id, now, now, "pending", category, title, target,
             _json(payload), requested_by, reason, expires_at),
        )
    add_event("approval", requested_by or "unknown", "info",
              f"待审批：{title}", {"approval_id": approval_id, "target": target}, approval_id, db_path)
    return get_approval(approval_id, db_path=db_path) or {}


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["payload"] = _loads(item.pop("payload_json", None)) or {}
    item["result"] = _loads(item.pop("result_json", None))
    return item


def get_approval(approval_id: str, db_path: str | Path | None = None) -> dict | None:
    expire_stale(db_path)
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    return _row(row)


def list_approvals(status: str | None = None, limit: int = 100,
                   db_path: str | Path | None = None) -> list[dict]:
    expire_stale(db_path)
    sql = "SELECT * FROM approvals"
    params: list[Any] = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY created DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with session(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(row) for row in rows if row is not None]


def expire_stale(db_path: str | Path | None = None) -> int:
    now = time.time()
    with session(db_path) as conn:
        cur = conn.execute(
            "UPDATE approvals SET status='expired', updated=?, decision='expired' "
            "WHERE status='pending' AND expires_at<=?",
            (now, now),
        )
        return int(cur.rowcount)


def decide_approval(approval_id: str, status: str, decided_by: str = "",
                    decision: str = "", result: Any = None,
                    db_path: str | Path | None = None) -> dict | None:
    if status not in {"approved", "denied", "cancelled"}:
        raise ValueError("invalid approval status")
    expire_stale(db_path)
    now = time.time()
    with session(db_path) as conn:
        cur = conn.execute(
            "UPDATE approvals SET status=?, updated=?, decision=?, decided_by=?, result_json=? "
            "WHERE id=? AND status='pending'",
            (status, now, decision or status, decided_by, _json(result) if result is not None else None, approval_id),
        )
        changed = int(cur.rowcount)
    item = get_approval(approval_id, db_path=db_path)
    if changed and item:
        add_event("approval", decided_by or "manager", "info" if status == "approved" else "warn",
                  f"{'已批准' if status == 'approved' else '已拒绝'}：{item.get('title', '')}",
                  {"approval_id": approval_id, "status": status}, approval_id, db_path)
    return item


def pending_count(db_path: str | Path | None = None) -> int:
    expire_stale(db_path)
    with session(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM approvals WHERE status='pending'").fetchone()
    return int(row["n"] if row else 0)


def status_counts(db_path: str | Path | None = None) -> dict:
    expire_stale(db_path)
    counts = {"pending": 0, "approved": 0, "denied": 0, "expired": 0, "cancelled": 0}
    with session(db_path) as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM approvals GROUP BY status").fetchall()
    for row in rows:
        counts[str(row["status"])] = int(row["n"])
    counts["total"] = sum(counts.values())
    return counts
