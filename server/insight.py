"""管理器侧读取/写入大肥鱼插件的本地数据。

包括回复复盘轨迹、记忆纠错队列、主人授权。插件和管理器共用
AstrBot/data/plugin_data/astrbot_plugin_dafeiyu_clean/ 下的 JSON 文件。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


PLUGIN_NAME = "astrbot_plugin_dafeiyu_clean"


def _base(inst: dict) -> Path:
    root = str(inst.get("root") or "").strip()
    if not root:
        raise ValueError("实例没有本地路径，无法读取插件数据")
    path = Path(root) / "data" / "plugin_data" / PLUGIN_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(inst: dict, name: str, default):
    try:
        return json.loads((_base(inst) / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _write(inst: dict, name: str, data) -> None:
    path = _base(inst) / name
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    tmp.replace(path)


def _trace_items(inst: dict) -> list[dict]:
    data = _read(inst, "traces.json", {"version": 1, "items": []})
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def traces(inst: dict, limit: int = 30, keyword: str = "") -> list[dict]:
    keyword = (keyword or "").strip().lower()
    out: list[dict] = []
    for trace in _trace_items(inst):
        if not isinstance(trace, dict):
            continue
        blob = " ".join(
            str(trace.get(key) or "")
            for key in ("user_text", "outgoing", "response", "sender_name", "umo")
        ).lower()
        if keyword and keyword not in blob:
            continue
        review = trace.get("review") or {}
        owner = trace.get("owner_check") or {}
        out.append(
            {
                "id": trace.get("id"),
                "created": trace.get("created"),
                "umo": trace.get("umo"),
                "group_id": trace.get("group_id"),
                "sender_id": trace.get("sender_id"),
                "sender_name": trace.get("sender_name"),
                "user_text": str(trace.get("user_text") or "")[:160],
                "outgoing": str(trace.get("outgoing") or trace.get("response") or "")[:160],
                "flags": trace.get("flags") or {},
                "memory_count": len(trace.get("memory_items") or []),
                "quote": trace.get("quote"),
                "owner": owner,
                "review": {
                    "wrong": bool(review.get("wrong")),
                    "reason": review.get("reason") or "",
                },
                "llm_calls": trace.get("llm_calls") or 0,
                "model": trace.get("model") or "",
            }
        )
        if len(out) >= max(1, int(limit)):
            break
    return out


def trace_detail(inst: dict, trace_id: str) -> dict | None:
    for trace in _trace_items(inst):
        if isinstance(trace, dict) and trace.get("id") == trace_id:
            return trace
    return None


# ---------------------------------------------------------------- corrections


def _correction_items(inst: dict) -> list[dict]:
    data = _read(inst, "corrections.json", {"version": 1, "items": []})
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def corrections(inst: dict, status: str = "") -> list[dict]:
    items = _correction_items(inst)
    if status:
        items = [item for item in items if item.get("status") == status]
    return items


def add_correction(inst: dict, payload: dict) -> dict:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("纠错内容不能为空")
    items = _correction_items(inst)
    item = {
        "id": uuid.uuid4().hex[:10],
        "created": time.time(),
        "umo": str(payload.get("umo") or ""),
        "group_id": str(payload.get("group_id") or ""),
        "sender_id": str(payload.get("sender_id") or "manager"),
        "sender_name": str(payload.get("sender_name") or "管理器"),
        "text": text[:500],
        "hint": str(payload.get("hint") or text)[:200],
        "owner": True,
        "status": "pending",
        "source": "manager",
    }
    items.insert(0, item)
    _write(inst, "corrections.json", {"version": 1, "items": items[:100]})
    return item


def _settle(inst: dict, item_id: str, status: str, resolution: dict) -> dict:
    items = _correction_items(inst)
    target = None
    for item in items:
        if item.get("id") == item_id:
            item["status"] = status
            item["resolved_at"] = time.time()
            item["resolution"] = resolution
            target = item
            break
    if target is None:
        raise ValueError(f"纠错项不存在：{item_id}")
    _write(inst, "corrections.json", {"version": 1, "items": items})
    return target


def resolve_correction(inst: dict, item_id: str, payload: dict) -> dict:
    """失效/改写/降权都落到 livingmemory，再标记队列项已处理。"""
    from . import memory

    action = str(payload.get("action") or "").strip().lower()
    memory_id = payload.get("memory_id")
    reason = str(payload.get("reason") or "记忆纠错队列").strip()[:200]
    rewrite = str(payload.get("rewrite") or "").strip()
    if action not in {"archive", "rewrite", "downweight"}:
        raise ValueError("action 必须是 archive / rewrite / downweight")
    if not memory_id:
        raise ValueError("请先选择要处理的相关记忆")
    if action == "archive":
        memory.call_update(inst, memory_id, "status", "archived", reason=reason)
    elif action == "downweight":
        memory.call_update(inst, memory_id, "importance", 0.05, reason=reason)
    else:
        if not rewrite:
            raise ValueError("改写需要填写新内容")
        memory.call_update(
            inst,
            memory_id,
            "structured",
            {"content": rewrite, "importance": 0.6, "status": "active"},
            reason=reason,
        )
    return _settle(
        inst,
        item_id,
        "resolved",
        {
            "action": action,
            "memory_id": memory_id,
            "rewrite": rewrite,
            "reason": reason,
        },
    )


def dismiss_correction(inst: dict, item_id: str, note: str = "") -> dict:
    return _settle(inst, item_id, "dismissed", {"note": note})


# -------------------------------------------------------------------- owner


def owner_grants(inst: dict) -> list[dict]:
    now = time.time()
    data = _read(inst, "owner_grants.json", {"version": 1, "grants": []})
    grants = data.get("grants") if isinstance(data, dict) else data
    return [
        grant
        for grant in (grants if isinstance(grants, list) else [])
        if isinstance(grant, dict) and float(grant.get("expires_at") or 0) >= now
    ]


def grant_owner(inst: dict, payload: dict) -> dict:
    umo = str(payload.get("umo") or "").strip()
    if not umo:
        raise ValueError("要授权的会话（umo）不能为空")
    minutes = max(5, min(1440, int(payload.get("minutes") or 60)))
    now = time.time()
    data = _read(inst, "owner_grants.json", {"version": 1, "grants": []})
    grants = data.get("grants") if isinstance(data, dict) else data
    grants = [grant for grant in (grants if isinstance(grants, list) else []) if grant]
    grant = {
        "id": uuid.uuid4().hex[:10],
        "umo": umo,
        "sender_id": str(payload.get("sender_id") or ""),
        "created": now,
        "expires_at": now + minutes * 60,
        "by": "manager",
        "note": str(payload.get("note") or "")[:120],
    }
    grants.insert(0, grant)
    _write(inst, "owner_grants.json", {"version": 1, "grants": grants[:40]})
    return grant


def revoke_owner(inst: dict, grant_id: str) -> None:
    data = _read(inst, "owner_grants.json", {"version": 1, "grants": []})
    grants = data.get("grants") if isinstance(data, dict) else data
    grants = [
        grant
        for grant in (grants if isinstance(grants, list) else [])
        if isinstance(grant, dict) and grant.get("id") != grant_id
    ]
    _write(inst, "owner_grants.json", {"version": 1, "grants": grants})


def recent_sessions(inst: dict, limit: int = 12) -> list[dict]:
    seen: dict[str, dict] = {}
    for trace in _trace_items(inst):
        umo = str(trace.get("umo") or "")
        if not umo:
            continue
        owner = trace.get("owner_check") or {}
        rec = seen.get(umo)
        if rec is None:
            if len(seen) >= limit:
                break
            rec = {
                "umo": umo,
                "group_id": trace.get("group_id") or "",
                "sender_id": trace.get("sender_id") or "",
                "sender_name": trace.get("sender_name") or "",
                "owner_sender_id": "",
                "owner_sender_name": "",
                "last": trace.get("updated") or trace.get("created"),
            }
            seen[umo] = rec
        # 主人可能不是最近发言的人，单独记录该会话里最近一次识别到的主人。
        if owner.get("owner") and not rec["owner_sender_id"]:
            rec["owner_sender_id"] = trace.get("sender_id") or ""
            rec["owner_sender_name"] = trace.get("sender_name") or ""
            rec["last_owner"] = trace.get("created")
    return list(seen.values())
