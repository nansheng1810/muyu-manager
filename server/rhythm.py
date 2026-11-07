"""生活节律：按作息计算当前阶段与有效精力/社交电量。"""

from __future__ import annotations

import datetime as _dt
import time

from . import fleet_store, human_settings, presence

PHASES = ("sleeping", "working", "off_work", "weekend", "quiet")
PHASE_LABEL = {
    "sleeping": "睡眠",
    "working": "工作",
    "off_work": "休息",
    "weekend": "周末",
    "quiet": "安静",
    "override": "手动覆盖",
}
# 基础修正：睡眠 -20、工作 -5、休息/周末 +5；安静时段不额外修正。
PHASE_MOD = {
    "sleeping": (-20, -20),
    "working": (-5, -5),
    "off_work": (5, 5),
    "weekend": (5, 5),
    "quiet": (0, 0),
}
AUTO_ADJUST = 5
AUTO_HOT_COUNT = 10
AUTO_COLD_COUNT = 2
_WEEK_SECONDS = 7 * 86400


def _minutes(text) -> int | None:
    raw = str(text or "").strip()
    if len(raw) != 5 or raw[2] != ":":
        return None
    try:
        hour, minute = int(raw[:2]), int(raw[3:])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _hit(minute: int, start: int | None, end: int | None) -> bool:
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= minute < end
    # 跨午夜窗口，例如 23:30–08:00。
    return minute >= start or minute < end


def _float(value, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(default)
    return float(value)


def _compute_phase(dt: _dt.datetime, settings: dict, quiet: dict) -> str:
    minute = dt.hour * 60 + dt.minute
    sleeping = _hit(minute, _minutes(settings.get("sleep_time")),
                    _minutes(settings.get("wake_time")))
    if sleeping:
        return "sleeping"
    if _hit(minute, _minutes(quiet.get("quiet_start")),
            _minutes(quiet.get("quiet_end"))):
        return "quiet"
    weekend_days = settings.get("weekend_days") or []
    if isinstance(weekend_days, list) and dt.weekday() in weekend_days:
        return "weekend"
    if _hit(minute, _minutes(settings.get("work_start")),
            _minutes(settings.get("work_end"))):
        return "working"
    return "off_work"


def _auto_mod(instance_id: str, now: float, db_path=None) -> int:
    """按近 7 天同小时的心情事件数做 ±5 微调；只读，不写任何状态。"""
    since = now - _WEEK_SECONDS
    hour = _dt.datetime.fromtimestamp(now).hour
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            "SELECT created FROM human_mood_events WHERE instance_id=? "
            "AND created>=? AND created<=?",
            (instance_id, since, now),
        ).fetchall()
    count = sum(
        1 for row in rows
        if _dt.datetime.fromtimestamp(_float(row["created"])).hour == hour
    )
    if count >= AUTO_HOT_COUNT:
        return AUTO_ADJUST
    # 完全没有历史时保持中性，避免默认把每个时段都压 -5。
    if 0 < count <= AUTO_COLD_COUNT:
        return -AUTO_ADJUST
    return 0


def current(instance_id: str, now: float | None = None, db_path=None) -> dict:
    instance_id = str(instance_id or "").strip()
    if not instance_id:
        raise presence.PresenceError("instance_id 不能为空")
    now = time.time() if now is None else float(now)
    settings = human_settings.get_settings(instance_id, db_path=db_path)
    quiet = presence.get_settings(instance_id, db_path=db_path)
    dt = _dt.datetime.fromtimestamp(now)
    base_phase = _compute_phase(dt, settings, quiet)
    schedule = {
        "rhythm_enabled": bool(settings.get("rhythm_enabled")),
        "wake_time": settings.get("wake_time", ""),
        "sleep_time": settings.get("sleep_time", ""),
        "work_start": settings.get("work_start", ""),
        "work_end": settings.get("work_end", ""),
        "weekend_days": list(settings.get("weekend_days") or []),
        "auto_adjust": bool(settings.get("auto_adjust")),
    }
    override_until = _float(settings.get("override_until"))
    override_phase = str(settings.get("override_phase") or "").strip()
    override_note = str(settings.get("override_note") or "").strip()
    override = {
        "active": False,
        "until": override_until,
        "phase": override_phase,
        "note": override_note,
    }
    if not schedule["rhythm_enabled"]:
        energy_mod, social_mod = PHASE_MOD[base_phase]
        return {
            "phase": base_phase,
            "label": PHASE_LABEL[base_phase],
            "energy_mod": 0,
            "social_mod": 0,
            "auto_mod": 0,
            "override": override,
            "schedule": schedule,
        }
    if override_until > now:
        chosen = override_phase if override_phase in PHASES else ""
        energy_mod, social_mod = PHASE_MOD[chosen] if chosen else (0, 0)
        override["active"] = True
        return {
            "phase": "override",
            "label": f"手动·{PHASE_LABEL[chosen]}" if chosen else PHASE_LABEL["override"],
            "energy_mod": energy_mod,
            "social_mod": social_mod,
            "auto_mod": 0,
            "override": override,
            "schedule": schedule,
        }
    auto_mod = _auto_mod(instance_id, now, db_path) if schedule["auto_adjust"] else 0
    base_energy, base_social = PHASE_MOD[base_phase]
    return {
        "phase": base_phase,
        "label": PHASE_LABEL[base_phase],
        "energy_mod": base_energy + auto_mod,
        "social_mod": base_social + auto_mod,
        "auto_mod": auto_mod,
        "override": override,
        "schedule": schedule,
    }


def effective(state: dict, rhythm: dict | None) -> dict:
    """把节律修正叠加到心情状态上，返回钳制后的有效精力/社交电量。"""
    state = state if isinstance(state, dict) else {}
    rhythm = rhythm if isinstance(rhythm, dict) else {}
    energy = _float(state.get("energy")) + _float(rhythm.get("energy_mod"))
    social = _float(state.get("social")) + _float(rhythm.get("social_mod"))
    return {
        "energy": round(max(0.0, min(100.0, energy)), 1),
        "social": round(max(0.0, min(100.0, social)), 1),
    }
