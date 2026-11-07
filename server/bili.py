"""B站机器人（astrbot_plugin_bilibili_ai_bot）状态快照，全部只读。"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

PLUGIN_DIR = Path("data") / "plugin_data" / "astrbot_plugin_bilibili_ai_bot"
MAX_PROACTIVE = 6
MAX_RECENT_ACTIONS = 18

_KIND_LABEL = {
    "like": "点赞",
    "proactive_watch": "主动看视频",
    "proactive_owner_recommend": "推荐给主人",
    "proactive_owner_comment": "评论推荐",
    "comment": "评论回复",
    "private_reply": "私信回复",
    "dynamic_publish": "发动态",
    "danmaku": "弹幕",
    "search": "搜索",
}
_STATE_LABEL = {
    "succeeded": "成功",
    "failed": "失败",
    "pending": "进行中",
    "skipped": "跳过",
    "canceled": "取消",
}


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
    try:
        return datetime.fromtimestamp(float(value)).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _kind_label(kind: str) -> str:
    return _KIND_LABEL.get(str(kind or ""), str(kind or "未知"))


def _state_label(state: str) -> str:
    return _STATE_LABEL.get(str(state or ""), str(state or "未知"))


def _db_snapshot(base: Path, today: str) -> dict:
    out: dict = {
        "life": None,
        "actions": {"today_total": 0, "failed_today": 0, "by_kind": {}, "recent": []},
        "counts": {},
        "today_budget": None,
    }
    conn = _readonly(base / "bilibot.sqlite3")
    if conn is None:
        return out
    try:
        if _has_table(conn, "life_states"):
            row = conn.execute("select * from life_states order by id desc limit 1").fetchone()
            if row:
                out["life"] = {
                    "time": _fmt_time(row["at"]),
                    "mood": str(row["mood"] or ""),
                    "energy": round(float(row["energy"] or 0), 2),
                    "social": round(float(row["social"] or 0), 2),
                    "phase": str(row["phase"] or ""),
                    "note": str(row["note"] or ""),
                }

        if _has_table(conn, "actions"):
            day_start = datetime.strptime(today, "%Y-%m-%d").timestamp()
            rows = conn.execute(
                "select kind, state, count(*) as n from actions "
                "where created_at >= ? group by kind, state",
                (day_start,),
            ).fetchall()
            by_kind: dict[str, int] = {}
            total = 0
            failed = 0
            for row in rows:
                n = int(row["n"] or 0)
                total += n
                if str(row["state"]) == "failed":
                    failed += n
                if str(row["state"]) in ("succeeded", "pending"):
                    label = _kind_label(row["kind"])
                    by_kind[label] = by_kind.get(label, 0) + n
            out["actions"]["today_total"] = total
            out["actions"]["failed_today"] = failed
            out["actions"]["by_kind"] = dict(
                sorted(by_kind.items(), key=lambda kv: -kv[1])
            )

            recent = conn.execute(
                "select kind, state, target_id, created_at, detail from actions "
                "order by created_at desc limit ?",
                (MAX_RECENT_ACTIONS,),
            ).fetchall()
            items = []
            for row in recent:
                try:
                    detail = json.loads(row["detail"] or "{}")
                except Exception:
                    detail = {}
                items.append(
                    {
                        "time": _fmt_time(row["created_at"]),
                        "kind": _kind_label(row["kind"]),
                        "state": _state_label(row["state"]),
                        "ok": str(row["state"]) == "succeeded",
                        "target": str(row["target_id"] or ""),
                        "proactive": bool(detail.get("proactive")),
                        "source": str(detail.get("source") or ""),
                    }
                )
            out["actions"]["recent"] = items

        for table, key in (
            ("memories", "memories"),
            ("events", "events"),
            ("seen_videos", "seen_videos"),
            ("day_plans", "day_plans"),
            ("goals", "goals"),
        ):
            if _has_table(conn, table):
                try:
                    out["counts"][key] = conn.execute(
                        f"select count(*) from [{table}]"
                    ).fetchone()[0]
                except Exception:
                    pass

        if _has_table(conn, "counters"):
            row = conn.execute(
                "select count from counters where bucket='behavior:global:day' and window_key=?",
                (today,),
            ).fetchone()
            if row:
                out["today_budget"] = int(float(row["count"] or 0))
    except Exception:
        pass
    finally:
        conn.close()
    return out


def status(inst: dict) -> dict:
    base = Path(str(inst.get("root") or "")) / PLUGIN_DIR
    today = time.strftime("%Y-%m-%d")
    installed = (base / "bilibot.sqlite3").exists() or (base / "mood.json").exists()
    out: dict = {
        "installed": installed,
        "data_dir": str(base),
        "life": None,
        "mood_daily": None,
        "affection": [],
        "actions": {"today_total": 0, "failed_today": 0, "by_kind": {}, "recent": []},
        "counts": {},
        "today_budget": None,
        "proactive": [],
    }
    if not installed:
        return out

    out.update(_db_snapshot(base, today))

    mood = _read_json(base / "mood.json")
    if isinstance(mood, dict):
        out["mood_daily"] = {
            "date": str(mood.get("date") or ""),
            "mood": str(mood.get("mood") or ""),
            "prompt": str(mood.get("mood_prompt") or ""),
        }

    affection = _read_json(base / "affection.json")
    if isinstance(affection, dict):
        out["affection"] = [
            {"uid": str(uid), "value": int(round(float(value)))}
            for uid, value in sorted(
                affection.items(), key=lambda kv: -float(kv[1] or 0)
            )
        ][:8]

    proactive = _read_json(base / "proactive_log.json")
    if isinstance(proactive, list):
        out["proactive"] = [
            {
                "time": str(item.get("time") or ""),
                "bvid": str(item.get("bvid") or ""),
                "title": str(item.get("title") or ""),
                "comment": str(item.get("comment") or ""),
            }
            for item in proactive[-MAX_PROACTIVE:][::-1]
            if isinstance(item, dict)
        ]
    return out
