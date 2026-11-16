"""概率回复：Agent 模式群消息抽签与普通模式接话概率。

Agent 模式下，群消息只有命中概率才会进入 DSH/Codex 的会话队列；
被 @ 到时会绕过概率直接放行。普通模式的接话概率由 AstrBot
群聊插件（astrbot_plugin_group_chat_plus）的 initial_probability 控制。
"""

from __future__ import annotations

import random
import threading
import time
from pathlib import Path

from . import store

DEFAULT_PROBABILITY = 1.0
PROBABILITY_PATH = store.DATA_DIR / "reply_probability.json"
MAX_PERCENT = 100.0

_lock = threading.RLock()
_started_at = time.time()
_stats: dict[str, dict] = {}

_MENTION_TYPES = {"at", "mention", "atuser"}


class ReplyProbabilityError(Exception):
    pass


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def load() -> dict:
    data = store.read_json(PROBABILITY_PATH, {})
    if not isinstance(data, dict):
        data = {}
    agents = data.get("agents")
    data["agents"] = agents if isinstance(agents, dict) else {}
    return data


def _clamp(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ReplyProbabilityError("概率必须是数字") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise ReplyProbabilityError("概率必须是数字")
    if number < 0 or number > 1:
        raise ReplyProbabilityError("概率需在 0–1 之间")
    return round(number, 4)


def get(instance_id: str) -> float:
    iid = str(instance_id or "")
    if not iid:
        return DEFAULT_PROBABILITY
    with _lock:
        value = (load().get("agents") or {}).get(iid)
    if value is None:
        return DEFAULT_PROBABILITY
    try:
        return _clamp(value)
    except ReplyProbabilityError:
        return DEFAULT_PROBABILITY


def set_probability(instance_id: str, value: float) -> float:
    """保存单个实例的 Agent 回复概率，value 为 0–1。"""
    iid = str(instance_id or "").strip()
    if not iid:
        raise ReplyProbabilityError("instance_id 不能为空")
    ratio = _clamp(value)
    with _lock:
        data = load()
        agents = data.get("agents") or {}
        agents[iid] = ratio
        data["agents"] = agents
        data["updated_at"] = _now()
        store.write_json(PROBABILITY_PATH, data)
    return ratio


def pct_to_ratio(value) -> float:
    """接口统一用百分比传输，0–100。"""
    try:
        percent = float(value)
    except (TypeError, ValueError):
        raise ReplyProbabilityError("概率必须是数字") from None
    if percent != percent or percent < 0 or percent > MAX_PERCENT:
        raise ReplyProbabilityError("概率需在 0–100 之间")
    return round(percent / MAX_PERCENT, 4)


def mentions_self(self_id: str, segments) -> bool:
    target = str(self_id or "")
    if not target or not isinstance(segments, list):
        return False
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        kind = str(seg.get("type") or seg.get("msg_type") or "").lower()
        if kind not in _MENTION_TYPES:
            continue
        data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
        qq = str(
            data.get("qq")
            or seg.get("qq")
            or data.get("user_id")
            or seg.get("user_id")
            or ""
        )
        if qq and qq == target:
            return True
    return False


def should_deliver(instance_id: str, self_id: str = "", segments=None) -> bool:
    """Agent 会话是否接收这条群消息。"""
    probability = get(instance_id)
    if probability <= 0:
        allowed = False
        reason = "zero"
    elif mentions_self(self_id, segments):
        allowed = True
        reason = "mention"
    elif probability >= 1:
        allowed = True
        reason = "always"
    else:
        allowed = random.random() < probability
        reason = "hit" if allowed else "miss"
    _record(str(instance_id or ""), allowed, reason)
    return allowed


def _record(instance_id: str, allowed: bool, reason: str) -> None:
    if not instance_id:
        return
    with _lock:
        row = _stats.setdefault(
            instance_id,
            {"delivered": 0, "dropped": 0, "last_at": 0.0, "last_reason": ""},
        )
        row["delivered" if allowed else "dropped"] += 1
        row["last_at"] = time.time()
        row["last_reason"] = reason


def snapshot(instances) -> dict:
    """合并实例、Agent 模式与抽签统计。与 NapCat 普通模式互不影响。"""
    from . import agent_mode

    rows = []
    for inst in instances or []:
        inst_id = str(inst.get("id") or "")
        if not inst_id:
            continue
        try:
            mode = agent_mode.status(inst_id)
        except Exception as exc:  # noqa: BLE001
            mode = {"error": str(exc) or "读取 Agent 模式失败"}
        with _lock:
            stats = dict(
                _stats.get(inst_id)
                or {"delivered": 0, "dropped": 0, "last_at": 0.0, "last_reason": ""}
            )
        rows.append({
            "id": inst_id,
            "name": str(inst.get("name") or inst_id),
            "agent": str(mode.get("agent") or ""),
            "agent_label": str(mode.get("agent_label") or ""),
            "agent_mode": {
                "enabled": bool(mode.get("enabled")),
                "group_id": str(mode.get("group_id") or ""),
                "group_name": str(mode.get("group_name") or ""),
                "runtime_status": str((mode.get("runtime") or {}).get("status") or ""),
                "error": str((mode.get("runtime") or {}).get("error") or ""),
            },
            "agent_probability_pct": round(get(inst_id) * MAX_PERCENT, 2),
            "stats": stats,
        })
    return {
        "instances": rows,
        "default_pct": round(DEFAULT_PROBABILITY * MAX_PERCENT, 2),
        "stats_since": _started_at,
        "updated_at": load().get("updated_at") or "",
    }
