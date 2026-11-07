"""拟人模式与每日心情共用的实例设置。"""

from __future__ import annotations

import json
import re
import time

from . import fleet_store

DEFAULTS = {
    "mood_enabled": True,
    "reset_hour": 5,
    "provider_id": "",
    "human_enabled": True,
    "shadow": True,
    "silence_enabled": False,
    "silence_probability": 0.08,
    "silence_daily_limit": 2,
    "split_enabled": True,
    "split_probability": 0.25,
    "delay_enabled": True,
    "delay_probability": 0.25,
    "short_probability": 0.12,
    "max_delay_ms": 3000,
    "max_chunks": 3,
    "chunk_max_chars": 120,
    "rhythm_enabled": True,
    "wake_time": "08:00",
    "sleep_time": "23:30",
    "work_start": "09:00",
    "work_end": "18:00",
    "weekend_days": [5, 6],
    "auto_adjust": True,
    "override_until": 0.0,
    "override_note": "",
    "override_phase": "",
}

_BOOL_KEYS = {
    "mood_enabled", "human_enabled", "shadow", "silence_enabled",
    "split_enabled", "delay_enabled", "rhythm_enabled", "auto_adjust",
}
_TIME_KEYS = {"wake_time", "sleep_time", "work_start", "work_end"}
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
OVERRIDE_PHASES = ("", "sleeping", "working", "off_work", "weekend", "quiet")
_RANGES = {
    "reset_hour": (0, 23, int),
    "silence_daily_limit": (0, 20, int),
    "max_delay_ms": (0, 4000, int),
    "max_chunks": (1, 3, int),
    "chunk_max_chars": (20, 120, int),
    "silence_probability": (0.0, 1.0, float),
    "split_probability": (0.0, 1.0, float),
    "delay_probability": (0.0, 1.0, float),
    "short_probability": (0.0, 1.0, float),
    "override_until": (0.0, 4102444800.0, float),
}


class SettingsError(Exception):
    pass


def validate_patch(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise SettingsError("设置必须是对象")
    out: dict = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise SettingsError(f"未知设置项：{key}")
        if key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise SettingsError(f"{key} 必须是布尔值")
            out[key] = value
        elif key == "provider_id":
            if not isinstance(value, str):
                raise SettingsError("provider_id 必须是字符串")
            out[key] = value.strip()[:200]
        elif key in _TIME_KEYS:
            if not isinstance(value, str) or not _TIME_RE.fullmatch(value.strip()):
                raise SettingsError(f"{key} 必须是 HH:MM")
            out[key] = value.strip()
        elif key == "weekend_days":
            if not isinstance(value, list):
                raise SettingsError("weekend_days 必须是数组")
            days: list[int] = []
            for item in value:
                if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 6:
                    raise SettingsError("weekend_days 项必须是 0–6 的整数")
                if item not in days:
                    days.append(item)
            out[key] = sorted(days)
        elif key == "override_note":
            if not isinstance(value, str):
                raise SettingsError("override_note 必须是字符串")
            out[key] = value.strip()[:200]
        elif key == "override_phase":
            if not isinstance(value, str):
                raise SettingsError("override_phase 必须是字符串")
            phase = value.strip()
            if phase not in OVERRIDE_PHASES:
                raise SettingsError("override_phase 取值无效")
            out[key] = phase
        else:
            low, high, kind = _RANGES[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SettingsError(f"{key} 必须是数字")
            number = kind(value)
            if number < low or number > high:
                raise SettingsError(f"{key} 必须在 {low}–{high} 之间")
            out[key] = number
    return out


def get_settings(instance_id: str, db_path=None) -> dict:
    with fleet_store.session(db_path) as conn:
        row = conn.execute(
            "SELECT json FROM human_config WHERE instance_id=?", (instance_id,)
        ).fetchone()
    cfg = {key: (list(value) if isinstance(value, list) else value)
           for key, value in DEFAULTS.items()}
    if row:
        try:
            saved = json.loads(row["json"])
        except (TypeError, ValueError):
            saved = {}
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    return cfg


def save_settings(instance_id: str, patch: dict, db_path=None) -> dict:
    current = get_settings(instance_id, db_path=db_path)
    current.update(validate_patch(patch))
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO human_config(instance_id, json, updated) VALUES(?,?,?) "
            "ON CONFLICT(instance_id) DO UPDATE SET json=excluded.json, updated=excluded.updated",
            (instance_id, json.dumps(current, ensure_ascii=False), time.time()),
        )
    return current
