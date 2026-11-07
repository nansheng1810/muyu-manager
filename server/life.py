"""管理器侧的生活线读取与设置。

插件写 ``life.json``（状态与事件）；管理器写 ``life_admin.json``（设置与
手动事件），两边互不覆盖。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_human_presence"

DEFAULT_SETTINGS = {
    "enabled": True,
    "inject": True,
    "inject_chars": 140,
    "sleep_time": "23:30",
    "wake_time": "07:30",
    "work_start": "09:00",
    "work_end": "18:00",
    "lunch_start": "12:00",
    "lunch_end": "13:30",
    "weekend_days": [5, 6],
    "quiet_start": "23:00",
    "quiet_end": "08:00",
}


def _base(inst: dict, create: bool = False) -> Path:
    root = str(inst.get("root") or "").strip()
    if not root:
        raise ValueError("实例没有本地路径，无法读取插件数据")
    path = Path(root) / "data" / "plugin_data" / PLUGIN_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _read(inst: dict, name: str, default):
    try:
        return json.loads((_base(inst) / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _write(inst: dict, name: str, data) -> None:
    path = _base(inst, create=True) / name
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    tmp.replace(path)


def _minute(value) -> int | None:
    text = str(value or "").strip()
    if len(text) != 5 or text[2] != ":":
        return None
    try:
        hour, minute = int(text[:2]), int(text[3:])
    except ValueError:
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour * 60 + minute
    return None


def normalize_settings(raw) -> dict:
    data = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        data.update({key: raw[key] for key in DEFAULT_SETTINGS if key in raw})
    data["enabled"] = bool(data.get("enabled", True))
    data["inject"] = bool(data.get("inject", True))
    try:
        data["inject_chars"] = max(60, min(600, int(data.get("inject_chars", 140))))
    except (TypeError, ValueError):
        data["inject_chars"] = 140
    for key in ("sleep_time", "wake_time", "work_start", "work_end",
                "lunch_start", "lunch_end", "quiet_start", "quiet_end"):
        if _minute(data.get(key)) is None:
            data[key] = DEFAULT_SETTINGS[key]
    days = data.get("weekend_days")
    if not isinstance(days, list):
        days = DEFAULT_SETTINGS["weekend_days"]
    cleaned = []
    for item in days:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 6 and value not in cleaned:
            cleaned.append(value)
    data["weekend_days"] = sorted(cleaned)
    return data


def _admin(inst: dict) -> dict:
    data = _read(inst, "life_admin.json", {})
    if not isinstance(data, dict):
        data = {}
    settings = normalize_settings(data.get("settings"))
    events = data.get("events")
    if not isinstance(events, list):
        events = []
    return {
        "version": int(data.get("version") or 1),
        "settings": settings,
        "events": [item for item in events if isinstance(item, dict)],
    }


def save_settings(inst: dict, patch: dict) -> dict:
    admin = _admin(inst)
    merged = dict(admin["settings"])
    if isinstance(patch, dict):
        merged.update({key: patch[key] for key in DEFAULT_SETTINGS if key in patch})
    admin["settings"] = normalize_settings(merged)
    admin["updated"] = time.time()
    _write(inst, "life_admin.json", admin)
    return admin["settings"]


def add_event(inst: dict, text: str, kind: str = "manual",
              ts: float | None = None) -> dict:
    text = " ".join(str(text or "").split())[:120]
    if not text:
        raise ValueError("事件内容不能为空")
    admin = _admin(inst)
    event = {
        "id": f"le_{uuid.uuid4().hex[:8]}",
        "ts": float(ts) if ts else time.time(),
        "kind": str(kind or "manual")[:20],
        "text": text,
    }
    admin["events"].append(event)
    admin["events"] = admin["events"][-200:]
    admin["updated"] = time.time()
    _write(inst, "life_admin.json", admin)
    return event


def delete_event(inst: dict, event_id: str) -> bool:
    admin = _admin(inst)
    before = len(admin["events"])
    admin["events"] = [
        item for item in admin["events"]
        if str(item.get("id") or "") != str(event_id)
    ]
    if len(admin["events"]) == before:
        return False
    admin["updated"] = time.time()
    _write(inst, "life_admin.json", admin)
    return True


def _events(life: dict, admin: dict) -> list[dict]:
    events: list[dict] = []
    raw = life.get("events")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                ts = float(item.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts <= 0 or not str(item.get("text") or "").strip():
                continue
            events.append({
                "id": str(item.get("id") or f"auto_{int(ts)}_{item.get('kind', '')}"),
                "ts": ts,
                "kind": str(item.get("kind") or "auto"),
                "text": str(item.get("text") or "")[:120],
                "source": str(item.get("source") or "auto"),
            })
    for item in admin["events"]:
        try:
            ts = float(item.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts <= 0:
            continue
        events.append({
            "id": str(item.get("id") or ""),
            "ts": ts,
            "kind": str(item.get("kind") or "manual"),
            "text": str(item.get("text") or "")[:120],
            "source": "manual",
        })
    events.sort(key=lambda item: item["ts"])
    return events


def snapshot(inst: dict, days: int = 7) -> dict:
    days = max(1, min(30, int(days or 7)))
    life = _read(inst, "life.json", {})
    if not isinstance(life, dict):
        life = {}
    admin = _admin(inst)
    cutoff = time.time() - days * 86400
    events = [item for item in _events(life, admin) if item["ts"] >= cutoff]
    state = life.get("state") if isinstance(life.get("state"), dict) else {}
    today = time.strftime("%Y-%m-%d")
    today_events = [
        item for item in events
        if time.strftime("%Y-%m-%d", time.localtime(item["ts"])) == today
    ]
    days_map: dict[str, list[dict]] = {}
    for item in events:
        day = time.strftime("%Y-%m-%d", time.localtime(item["ts"]))
        days_map.setdefault(day, []).append(item)
    return {
        "plugin": PLUGIN_NAME,
        "settings": admin["settings"],
        "state": {
            "date": str(state.get("date") or ""),
            "phase": str(state.get("phase") or ""),
            "phase_label": str(state.get("phase_label") or ""),
            "doing": str(state.get("doing") or ""),
            "energy": int(state.get("energy") or 0),
            "weekday": str(state.get("weekday") or ""),
            "clock": str(state.get("clock") or ""),
            "since": float(state.get("since") or 0),
        },
        "updated": float(life.get("updated") or 0),
        "today": today_events,
        "events": events,
        "days": [
            {"date": date, "events": days_map[date]}
            for date in sorted(days_map.keys(), reverse=True)
        ],
        "total": len(events),
    }
