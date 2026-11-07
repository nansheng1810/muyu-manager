"""审批队列：本机创建、批准/拒绝、插件阻塞等待。"""

from __future__ import annotations

import time
from typing import Any

from . import fleet_store

DEFAULT_TTL = 1800
MAX_WAIT = 120
POLL_SECONDS = 0.5

VALID_CATEGORIES = {
    "bili_write", "douyin_write", "dsh_action", "manager_action", "other",
}


def _ttl(value: Any) -> int:
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TTL
    return max(60, min(ttl, 24 * 3600))


def create(category: str, title: str, target: str = "", payload: Any = None,
           requested_by: str = "manager", reason: str = "", ttl: int = DEFAULT_TTL) -> dict:
    category = str(category or "other").strip()
    if category not in VALID_CATEGORIES:
        category = "other"
    title = str(title or "").strip()
    if not title:
        raise ValueError("审批标题不能为空")
    return fleet_store.add_approval(
        category=category,
        title=title[:200],
        target=str(target or "")[:300],
        payload=payload or {},
        requested_by=str(requested_by or "manager")[:120],
        reason=str(reason or "")[:500],
        ttl=_ttl(ttl),
    )


def get(approval_id: str) -> dict | None:
    return fleet_store.get_approval(approval_id)


def list_items(status: str | None = "pending", limit: int = 100) -> list[dict]:
    return fleet_store.list_approvals(status=status or None, limit=limit)


def approve(approval_id: str, decided_by: str = "manager", result: Any = None) -> dict | None:
    return fleet_store.decide_approval(approval_id, "approved", decided_by=decided_by, result=result)


def deny(approval_id: str, decided_by: str = "manager", reason: str = "") -> dict | None:
    return fleet_store.decide_approval(approval_id, "denied", decided_by=decided_by,
                                       decision=reason or "denied")


def cancel(approval_id: str, decided_by: str = "manager") -> dict | None:
    return fleet_store.decide_approval(approval_id, "cancelled", decided_by=decided_by)


def summary() -> dict:
    counts = fleet_store.status_counts()
    return {"pending": counts.get("pending", 0), "counts": counts}


def request_and_wait(category: str, title: str, target: str = "", payload: Any = None,
                     requested_by: str = "plugin", reason: str = "",
                     timeout: int = MAX_WAIT, ttl: int = DEFAULT_TTL) -> dict:
    """创建审批并阻塞等待；超时返回 pending，调用方不得执行写操作。"""
    item = create(category, title, target, payload, requested_by, reason, ttl)
    deadline = time.time() + max(1, min(int(timeout), MAX_WAIT))
    while time.time() < deadline:
        current = get(item["id"])
        if current and current["status"] != "pending":
            return current
        time.sleep(POLL_SECONDS)
    current = get(item["id"])
    if current and current["status"] != "pending":
        return current
    return {"id": item["id"], "status": "pending", "timeout": True,
            "title": title, "target": target, "payload": payload or {}}
