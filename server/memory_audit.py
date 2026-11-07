"""只读记忆体检：重复、疑似冲突与敏感信息。"""

from __future__ import annotations

import difflib
import json
import re

from . import memory

_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_KEY = re.compile(r"(?i)(?:sk-[a-z0-9]{16,}|bearer\s+[a-z0-9._-]{20,})")
_STOP = {"这个", "那个", "我们", "他们", "一个", "就是", "不是", "喜欢", "不喜欢", "可以"}


def _metadata(item: dict) -> dict:
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str) and metadata.strip():
        try:
            parsed = json.loads(metadata)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _text(item: dict) -> str:
    metadata = _metadata(item)
    return str(item.get("text") or metadata.get("persona_summary") or metadata.get("canonical_summary") or "").strip()


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").lower())


def _shingles(text: str) -> set[str]:
    value = _normalize(text)
    return {value[index:index + 2] for index in range(max(0, len(value) - 1))}


def _similar(left: str, right: str) -> bool:
    a, b = _shingles(left), _shingles(right)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.82


def _snippet(text: str, length: int = 100) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    return value if len(value) <= length else value[:length - 1] + "…"


def _contradiction(left: str, right: str) -> bool:
    pairs = (("喜欢", "不喜欢"), ("是", "不是"), ("会", "不会"), ("要", "不要"))
    longest = max(len(left), len(right))
    if longest > 160:
        return False
    shared = (_shingles(left) & _shingles(right)) - _STOP
    threshold = 2 if longest <= 40 else 3
    if len(shared) < threshold:
        return False
    if difflib.SequenceMatcher(None, left, right).ratio() < (0.6 if longest <= 40 else 0.5):
        return False
    for positive, negative in pairs:
        if (positive in left and negative in right) or (negative in left and positive in right):
            return True
    return False


def audit_items(items: list[dict]) -> dict:
    rows = []
    for item in items[:500]:
        if not isinstance(item, dict):
            continue
        text = _text(item)
        if text:
            rows.append({"id": item.get("id"), "text": text})

    groups = []
    used = set()
    for index, row in enumerate(rows):
        if index in used:
            continue
        group = [row]
        for other in range(index + 1, len(rows)):
            if other in used:
                continue
            if _normalize(row["text"]) == _normalize(rows[other]["text"]) or _similar(row["text"], rows[other]["text"]):
                group.append(rows[other])
                used.add(other)
        if len(group) > 1:
            used.add(index)
            groups.append([{"id": item["id"], "snippet": _snippet(item["text"])} for item in group[:6]])

    privacy = []
    seen = set()
    for row in rows:
        for kind, pattern in (("手机号", _PHONE), ("邮箱", _EMAIL), ("身份证", _ID_CARD), ("密钥", _KEY)):
            if pattern.search(row["text"]) and (row["id"], kind) not in seen:
                seen.add((row["id"], kind))
                privacy.append({"id": row["id"], "type": kind, "snippet": _snippet(row["text"])})

    conflicts = []
    for index, row in enumerate(rows):
        for other in range(index + 1, len(rows)):
            if _contradiction(row["text"], rows[other]["text"]):
                conflicts.append({
                    "left": {"id": row["id"], "snippet": _snippet(row["text"])},
                    "right": {"id": rows[other]["id"], "snippet": _snippet(rows[other]["text"])},
                })
                if len(conflicts) >= 20:
                    break
        if len(conflicts) >= 20:
            break

    return {
        "total": len(rows),
        "counts": {
            "duplicates": len(groups),
            "privacy": len(privacy),
            "conflicts": len(conflicts),
        },
        "duplicates": groups[:20],
        "privacy": privacy[:30],
        "conflicts": conflicts,
    }


def merge(audit: dict, forgetting=None) -> dict:
    """Attach read-only forgetting risk rows to an audit result.

    Every existing audit key (``total``/``counts``/``duplicates``/
    ``privacy``/``conflicts``) is preserved untouched; ``forgetting`` is only
    added when a payload is supplied. Nothing is written back.

    Args:
        audit: Result from ``collect`` or ``audit_items``.
        forgetting: Optional ``{"items": [...]}`` payload or a plain list.

    Returns:
        A new dict with the audit fields plus an optional ``forgetting`` list.
    """
    result = dict(audit) if isinstance(audit, dict) else {}
    if forgetting is None:
        return result
    items = forgetting.get("items") if isinstance(forgetting, dict) else forgetting
    result["forgetting"] = [
        item for item in (items or []) if isinstance(item, dict)
    ]
    return result


def collect(inst: dict, call=memory.call_memories) -> dict:
    data = call(inst, {"status": "all", "page": 1, "page_size": 200, "sort": "updated_desc"})
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items") or data.get("memories") or []
    else:
        items = []
    result = audit_items([item for item in items if isinstance(item, dict)])
    result["instance_id"] = inst.get("id")
    result["instance_name"] = inst.get("name")
    return result
