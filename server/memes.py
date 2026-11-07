"""管理器侧的群梗库：正式梗表、自动候选、设置与候选转正。

正式梗表在插件数据目录的 ``memes.json``（管理器与 /梗 命令共同维护），
自动候选在 ``meme_candidates.json``（插件写，管理器确认或忽略）。
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
    "max_inject": 8,
    "auto_capture": True,
    "min_count": 4,
    "min_speakers": 2,
    "window_hours": 72,
    "max_candidates": 80,
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


def normalize_settings(raw) -> dict:
    data = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        data.update({key: raw[key] for key in DEFAULT_SETTINGS if key in raw})
    data["enabled"] = bool(data.get("enabled", True))
    data["inject"] = bool(data.get("inject", True))
    data["auto_capture"] = bool(data.get("auto_capture", True))
    for key, low, high, default in (
        ("max_inject", 0, 20, 8),
        ("min_count", 2, 50, 4),
        ("min_speakers", 1, 20, 2),
        ("window_hours", 1, 720, 72),
        ("max_candidates", 10, 500, 80),
    ):
        try:
            data[key] = max(low, min(high, int(data.get(key, default))))
        except (TypeError, ValueError):
            data[key] = default
    return data


def _main(inst: dict) -> dict:
    data = _read(inst, "memes.json", {})
    if not isinstance(data, dict):
        data = {}
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    settings = normalize_settings(
        data.get("settings") if isinstance(data.get("settings"), dict) else {})
    return {"version": int(data.get("version") or 1), "settings": settings,
            "items": [item for item in items if isinstance(item, dict)]}


def _dismissed(inst: dict) -> list[str]:
    data = _read(inst, "meme_dismissed.json", {})
    if not isinstance(data, dict):
        return []
    values = data.get("phrases")
    return [str(item) for item in values] if isinstance(values, list) else []


def _save_dismissed(inst: dict, phrases: list[str]) -> None:
    _write(inst, "meme_dismissed.json", {
        "version": 1, "updated": time.time(), "phrases": phrases[-500:]})


def _normalize_item(raw: dict) -> dict:
    return {
        "id": str(raw.get("id") or f"m_{uuid.uuid4().hex[:8]}"),
        "phrase": str(raw.get("phrase") or "")[:40],
        "meaning": str(raw.get("meaning") or "")[:300],
        "example": str(raw.get("example") or "")[:300],
        "status": str(raw.get("status") or "active"),
        "count": int(raw.get("count") or 0),
        "source": str(raw.get("source") or "manual"),
        "first_seen": float(raw.get("first_seen") or 0),
        "last_seen": float(raw.get("last_seen") or 0),
        "updated": float(raw.get("updated") or 0),
    }


def list_all(inst: dict, status: str = "") -> dict:
    main = _main(inst)
    dismissed = set(_dismissed(inst))
    items = [_normalize_item(item) for item in main["items"]]
    items = [item for item in items if item["phrase"]]
    all_items = list(items)
    known = {item["phrase"] for item in items}
    candidates = []
    data = _read(inst, "meme_candidates.json", {})
    groups = data.get("groups") if isinstance(data, dict) else None
    if isinstance(groups, dict):
        for group_id, stats in groups.items():
            if not isinstance(stats, dict):
                continue
            for phrase, raw in stats.items():
                if not isinstance(raw, dict):
                    continue
                phrase = str(phrase or "").strip()
                if not phrase or phrase in known or phrase in dismissed:
                    continue
                candidates.append({
                    "id": f"c_{group_id}_{phrase}",
                    "phrase": phrase[:40],
                    "group_id": str(group_id),
                    "count": int(raw.get("count") or 0),
                    "speakers": len(raw.get("speakers") or []),
                    "speaker_ids": [str(x) for x in raw.get("speakers") or []][:12],
                    "sample": str(raw.get("sample") or "")[:120],
                    "first_seen": float(raw.get("first") or 0),
                    "last_seen": float(raw.get("last") or 0),
                })
    candidates.sort(key=lambda item: item["count"], reverse=True)
    filtered = []
    if status in ("active", "disabled"):
        filtered = [item for item in items if item["status"] == status]
    elif status == "candidate":
        filtered = []
        items = []
    elif status == "":
        filtered = items
    return {
        "plugin": PLUGIN_NAME,
        "settings": main["settings"],
        "items": filtered,
        "all_items": all_items,
        "candidates": candidates[:120],
        "stats": {
            "total": len(all_items),
            "active": sum(1 for item in all_items if item["status"] == "active"),
            "disabled": sum(1 for item in all_items if item["status"] == "disabled"),
            "candidates": len(candidates),
        },
        "updated": float(data.get("updated") or 0) if isinstance(data, dict) else 0,
    }


def add(inst: dict, phrase: str, meaning: str = "", example: str = "",
        source: str = "manual", group_id: str = "") -> dict:
    phrase = " ".join(str(phrase or "").split())[:40]
    if not phrase:
        raise ValueError("短语不能为空")
    main = _main(inst)
    now = time.time()
    for item in main["items"]:
        if str(item.get("phrase") or "") == phrase:
            if meaning:
                item["meaning"] = str(meaning)[:300]
            if example:
                item["example"] = str(example)[:300]
            item["status"] = "active"
            item["updated"] = now
            main["updated"] = now
            _write(inst, "memes.json", main)
            return _normalize_item(item)
    item = {
        "id": f"m_{uuid.uuid4().hex[:8]}",
        "phrase": phrase,
        "meaning": str(meaning or "")[:300],
        "example": str(example or "")[:300],
        "status": "active",
        "count": 0,
        "source": str(source or "manual"),
        "group_id": str(group_id or ""),
        "first_seen": now,
        "last_seen": now,
        "updated": now,
    }
    main["items"].append(item)
    main["updated"] = now
    _write(inst, "memes.json", main)
    return _normalize_item(item)


def update(inst: dict, item_id: str, patch: dict) -> dict:
    main = _main(inst)
    target = None
    for item in main["items"]:
        if str(item.get("id") or "") == str(item_id):
            target = item
            break
    if target is None:
        raise ValueError("没有找到这条群梗")
    if "phrase" in patch:
        phrase = " ".join(str(patch["phrase"] or "").split())[:40]
        if not phrase:
            raise ValueError("短语不能为空")
        if any(str(item.get("phrase") or "") == phrase
               and str(item.get("id") or "") != str(item_id)
               for item in main["items"]):
            raise ValueError("已经有同名的群梗")
        target["phrase"] = phrase
    if "meaning" in patch:
        target["meaning"] = str(patch["meaning"] or "")[:300]
    if "example" in patch:
        target["example"] = str(patch["example"] or "")[:300]
    if "status" in patch:
        status = str(patch["status"] or "").strip()
        if status not in ("active", "disabled"):
            raise ValueError("状态只能是 active 或 disabled")
        target["status"] = status
    target["updated"] = time.time()
    main["updated"] = target["updated"]
    _write(inst, "memes.json", main)
    return _normalize_item(target)


def delete(inst: dict, item_id: str) -> bool:
    main = _main(inst)
    before = len(main["items"])
    main["items"] = [
        item for item in main["items"]
        if str(item.get("id") or "") != str(item_id)
    ]
    if len(main["items"]) == before:
        return False
    main["updated"] = time.time()
    _write(inst, "memes.json", main)
    return True


def activate_candidate(inst: dict, phrase: str, meaning: str = "",
                       group_id: str = "") -> dict:
    phrase = " ".join(str(phrase or "").split())[:40]
    if not phrase:
        raise ValueError("短语不能为空")
    item = add(inst, phrase, meaning, source="auto", group_id=group_id)
    _save_dismissed(inst, [
        value for value in _dismissed(inst) if value != phrase])
    return item


def dismiss_candidate(inst: dict, phrase: str) -> bool:
    phrase = " ".join(str(phrase or "").split())[:40]
    if not phrase:
        return False
    values = _dismissed(inst)
    if phrase not in values:
        values.append(phrase)
    _save_dismissed(inst, values)
    return True


def save_settings(inst: dict, patch: dict) -> dict:
    main = _main(inst)
    merged = dict(main["settings"])
    if isinstance(patch, dict):
        merged.update({key: patch[key] for key in DEFAULT_SETTINGS if key in patch})
    main["settings"] = normalize_settings(merged)
    main["updated"] = time.time()
    _write(inst, "memes.json", main)
    return main["settings"]
