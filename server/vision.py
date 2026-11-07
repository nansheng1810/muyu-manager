"""管理器侧的看图接话：图片记录、设置与删除标记。

插件写 ``vision.json``（记录），管理器写 ``vision_admin.json``（设置）
和 ``vision_deleted.json``（删除标记），互不覆盖。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_human_presence"

DEFAULT_SETTINGS = {
    "enabled": True,
    "inject": True,
    "auto_reply": False,
    "probability": 0.15,
    "hourly_limit": 3,
    "groups": [],
    "max_chars": 90,
    "provider_id": "",
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
    data["auto_reply"] = bool(data.get("auto_reply", False))
    try:
        data["probability"] = round(
            max(0.0, min(1.0, float(data.get("probability", 0.15)))), 4
        )
    except (TypeError, ValueError):
        data["probability"] = 0.15
    for key, low, high, default in (
        ("hourly_limit", 0, 100, 3),
        ("max_chars", 20, 400, 90),
    ):
        try:
            data[key] = max(low, min(high, int(data.get(key, default))))
        except (TypeError, ValueError):
            data[key] = default
    groups = data.get("groups")
    if not isinstance(groups, list):
        groups = []
    cleaned = []
    for item in groups:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    data["groups"] = cleaned[:50]
    data["provider_id"] = str(data.get("provider_id") or "").strip()[:60]
    return data


def _admin(inst: dict) -> dict:
    data = _read(inst, "vision_admin.json", {})
    if not isinstance(data, dict):
        data = {}
    return {
        "version": int(data.get("version") or 1),
        "settings": normalize_settings(
            data.get("settings") if isinstance(data.get("settings"), dict) else {}),
    }


def save_settings(inst: dict, patch: dict) -> dict:
    admin = _admin(inst)
    merged = dict(admin["settings"])
    if isinstance(patch, dict):
        merged.update({key: patch[key] for key in DEFAULT_SETTINGS if key in patch})
    admin["settings"] = normalize_settings(merged)
    admin["updated"] = time.time()
    _write(inst, "vision_admin.json", admin)
    return admin["settings"]


def _deleted(inst: dict) -> list[str]:
    data = _read(inst, "vision_deleted.json", {})
    if not isinstance(data, dict):
        return []
    values = data.get("ids")
    return [str(item) for item in values] if isinstance(values, list) else []


def list_items(inst: dict, limit: int = 60) -> dict:
    limit = max(1, min(300, int(limit or 60)))
    settings = _admin(inst)["settings"]
    deleted = set(_deleted(inst))
    data = _read(inst, "vision.json", {})
    raw = data.get("items") if isinstance(data, dict) else None
    items = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "")
            if not item_id or item_id in deleted:
                continue
            try:
                ts = float(item.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            items.append({
                "id": item_id,
                "umo": str(item.get("umo") or ""),
                "group_id": str(item.get("group_id") or ""),
                "sender_id": str(item.get("sender_id") or ""),
                "sender_name": str(item.get("sender_name") or ""),
                "url": str(item.get("url") or ""),
                "caption": str(item.get("caption") or "")[:200],
                "description": str(item.get("description") or "")[:300],
                "ts": ts,
                "auto_reply": bool(item.get("auto_reply")),
                "reply_text": str(item.get("reply_text") or "")[:300],
            })
    items.sort(key=lambda item: item["ts"], reverse=True)
    today = time.strftime("%Y-%m-%d")
    stats = {
        "total": len(items),
        "auto_replies": sum(1 for item in items if item["auto_reply"]),
        "today": sum(
            1 for item in items
            if time.strftime("%Y-%m-%d", time.localtime(item["ts"] or 0)) == today
        ),
        "described": sum(1 for item in items if item["description"]),
    }
    return {
        "plugin": PLUGIN_NAME,
        "settings": settings,
        "items": items[:limit],
        "stats": stats,
        "updated": float(data.get("updated") or 0) if isinstance(data, dict) else 0,
    }


def delete_item(inst: dict, item_id: str) -> bool:
    item_id = str(item_id or "").strip()
    if not item_id:
        return False
    values = _deleted(inst)
    if item_id not in values:
        values.append(item_id)
    _write(inst, "vision_deleted.json", {
        "version": 1, "updated": time.time(), "ids": values[-1000:]})
    return True


def clear_all(inst: dict) -> int:
    data = _read(inst, "vision.json", {})
    raw = data.get("items") if isinstance(data, dict) else None
    ids = [str(item.get("id") or "") for item in raw or []
           if isinstance(item, dict) and item.get("id")]
    if not ids:
        return 0
    values = _deleted(inst)
    for item_id in ids:
        if item_id not in values:
            values.append(item_id)
    _write(inst, "vision_deleted.json", {
        "version": 1, "updated": time.time(), "ids": values[-1000:]})
    return len(ids)
