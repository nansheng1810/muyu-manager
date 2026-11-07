"""只读权限矩阵：跨实例汇总 B站/抖音的写开关与审批状态。"""

from __future__ import annotations

import json
from pathlib import Path

from . import runner as runner_mod, store

BILI_PLUGIN = "astrbot_plugin_bilibili_ai_bot"
DOUYIN_PLUGIN = "astrbot_plugin_douyin_dm"

ROWS = [
    {"id": "bili.private", "plugin": "bili", "key": "ENABLE_PRIVATE_MESSAGES", "label": "B站私信", "risk": "write"},
    {"id": "bili.private_reply", "plugin": "bili", "key": "PRIVATE_MESSAGE_AUTO_REPLY", "label": "B站私信自动回复", "risk": "write"},
    {"id": "bili.proactive", "plugin": "bili", "key": "ENABLE_PROACTIVE", "label": "B站主动互动", "risk": "write"},
    {"id": "bili.dynamic", "plugin": "bili", "key": "ENABLE_DYNAMIC", "label": "B站动态", "risk": "write"},
    {"id": "bili.video_publish", "plugin": "bili", "key": "ENABLE_VIDEO_PUBLISH", "label": "B站投稿", "risk": "write"},
    {"id": "bili.approval", "plugin": "bili", "key": "APPROVAL_MODE", "label": "B站写审批", "risk": "approval"},
    {"id": "douyin.enabled", "plugin": "douyin", "key": "enabled", "label": "抖音接入", "risk": "read"},
    {"id": "douyin.auto_reply", "plugin": "douyin", "key": "auto_reply_enabled", "label": "抖音私信自动回复", "risk": "write"},
    {"id": "douyin.public_comments", "plugin": "douyin", "key": "allow_public_comments", "label": "抖音公开评论", "risk": "write"},
    {"id": "douyin.like", "plugin": "douyin", "key": "allow_like", "label": "抖音点赞", "risk": "write"},
    {"id": "douyin.favorite", "plugin": "douyin", "key": "allow_favorite", "label": "抖音收藏", "risk": "write"},
    {"id": "douyin.follow", "plugin": "douyin", "key": "allow_follow", "label": "抖音关注", "risk": "write"},
    {"id": "douyin.dry_run", "plugin": "douyin", "key": "interaction_dry_run", "label": "抖音干跑", "risk": "safety", "inverted": True},
    {"id": "douyin.approval", "plugin": "douyin", "key": "approval_mode", "label": "抖音写审批", "risk": "approval"},
    {"id": "douyin.client_comment", "plugin": "douyin", "key": "client_comment_enabled", "label": "抖音客户端评论", "risk": "write"},
]

_PLUGIN_META = {
    "bili": (BILI_PLUGIN, "astrbot_plugin_bilibili_ai_bot_config.json"),
    "douyin": (DOUYIN_PLUGIN, "astrbot_plugin_douyin_dm_config.json"),
}


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def instance_matrix(inst: dict, read_config=_load_json) -> dict:
    root = Path(str(inst.get("root") or ""))
    item = {
        "id": str(inst.get("id") or ""),
        "name": str(inst.get("name") or inst.get("id") or ""),
        "online": bool(runner_mod.runner.status(inst).get("running")),
        "plugins": {},
        "values": {},
    }
    for kind, (plugin_id, config_name) in _PLUGIN_META.items():
        installed = (root / "data" / "plugins" / plugin_id / "main.py").is_file()
        config = read_config(root / "data" / "config" / config_name) if installed else {}
        item["plugins"][kind] = {"installed": installed, "config_found": bool(config)}
        for row in ROWS:
            if row["plugin"] != kind:
                continue
            if not installed or not config:
                item["values"][row["id"]] = None
            else:
                value = config.get(row["key"])
                item["values"][row["id"]] = value if isinstance(value, bool) else None
    return item


def collect(instances: list[dict] | None = None, read_config=_load_json) -> dict:
    items = [instance_matrix(inst, read_config) for inst in (instances if instances is not None else store.load_instances())]
    rows = []
    write_on = 0
    for row in ROWS:
        values = {item["id"]: item["values"].get(row["id"]) for item in items}
        write_on += sum(1 for value in values.values() if value is True and row["risk"] == "write")
        rows.append({**row, "values": values})
    approval_off = 0
    dry_run_off = 0
    for item in items:
        writes = any(
            row["risk"] == "write" and item["values"].get(row["id"]) is True
            for row in ROWS
        )
        if writes and not (item["values"].get("bili.approval") or item["values"].get("douyin.approval")):
            approval_off += 1
        if item["values"].get("douyin.dry_run") is False:
            dry_run_off += 1
    return {
        "instances": items,
        "rows": rows,
        "summary": {
            "instances": len(items),
            "write_on": write_on,
            "approval_off": approval_off,
            "dry_run_off": dry_run_off,
            "plugins_missing": sum(1 for item in items for meta in item["plugins"].values() if not meta["installed"]),
        },
    }
