"""Whitelisted proxy for LivingMemory's human-memory page API."""

from __future__ import annotations

import json
import math
import re
import threading
import time

from . import dashboard, mood

PLUGIN = "astrbot_plugin_livingmemory"
PREFIX = f"plugins/extensions/{PLUGIN}/page"
TIMEOUTS = {
    "read": 20,
    "recall": 30,
    "sleep_preview": 30,
    "sleep_run": 30,
    "recon_preview": 60,
    "recon_apply": 30,
    "backfill_preview": 30,
    "backfill_run": 30,
    "resummarize": 120,
    "arousal": 30,
    "prompt_preview": 30,
    "prompt_merge": 30,
    "working": 20,
    "relations": 30,
    "emotion": 30,
    "forgetting": 30,
    "review_preview": 20,
    "review": 30,
    "active_recall": 20,
    "active_recall_preview": 30,
    "vector": 15,
    "vector_probe": 30,
    "vector_rebuild": 30,
}
ALLOWED_CONFIG_PREFIX = "human_memory."
# The sleep card exposes the global consolidation cap; the recall lab exposes
# the two-stage recall switch and bounds. These are the only non-human_memory
# paths the memory page may write.
EXTRA_CONFIG_PATHS = frozenset(
    {
        "memory_consolidation.max_groups_per_run",
        "recall_engine.two_stage_enabled",
        "recall_engine.two_stage_candidates",
        "recall_engine.two_stage_vector_weight",
        "recall_engine.two_stage_fuzzy_weight",
        "recall_engine.two_stage_vector_k",
        "recall_engine.cross_context_enabled",
        "recall_engine.cross_context_limit",
        "recall_engine.cross_context_private_to_group",
        "recall_engine.cross_context_group_to_private",
    }
)

MOOD_EVENT_SCAN = 200
MOOD_EVENT_LIMIT = 10
EXPORT_PAGE_SIZE = 200
EXPORT_MAX_PAGES = 20
EXPORT_STATUSES = frozenset({"all", "active", "archived"})
_EMBEDDING_KEYS = frozenset(
    {
        "embedding",
        "embeddings",
        "vector",
        "vectors",
        "embedding_vector",
        "embedding_vectors",
    }
)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class MemoryError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = str(message)
        self.status = int(status)


def normalize(payload: dict) -> dict:
    if isinstance(payload, dict) and payload.get("status") == "error":
        raise MemoryError(str(payload.get("message") or "插件返回错误"), 502)
    if isinstance(payload, dict) and "data" in payload:
        data = payload["data"]
        if isinstance(data, dict):
            if data.get("status") == "error":
                raise MemoryError(str(data.get("message") or "插件返回错误"), 502)
            if "data" in data:
                return data["data"]
            return data
        return data
    return payload if isinstance(payload, dict) else {}


def _call(
    inst,
    method: str,
    path: str,
    payload=None,
    *,
    query: dict | None = None,
    timeout: float = TIMEOUTS["read"],
    call=dashboard.call,
) -> dict:
    try:
        result = call(
            inst,
            method,
            f"{PREFIX}/{path.lstrip('/')}",
            payload,
            query=query,
            timeout=timeout,
        )
    except dashboard.DashboardError as exc:
        raise MemoryError(
            exc.message, exc.status if exc.status >= 400 else 502
        ) from exc
    return normalize(result)


def _memory_id(value) -> int:
    try:
        memory_id = int(value)
    except (TypeError, ValueError) as exc:
        raise MemoryError("memory_id 必须是整数", 400) from exc
    if memory_id <= 0:
        raise MemoryError("memory_id 必须是正整数", 400)
    return memory_id


def _arousal(value) -> float:
    try:
        arousal = float(value)
    except (TypeError, ValueError) as exc:
        raise MemoryError("arousal 必须是 0 到 1 之间的数字", 400) from exc
    if not math.isfinite(arousal):
        raise MemoryError("arousal 必须是 0 到 1 之间的数字", 400)
    if arousal < 0.0 or arousal > 1.0:
        raise MemoryError("arousal 必须在 0 到 1 之间", 400)
    return arousal


def _scope(value) -> str:
    scope = str(value or "private").strip().lower() or "private"
    if scope not in {"private", "group"}:
        raise MemoryError("scope 必须是 private 或 group", 400)
    return scope


def _bounded_int(value, default: int, low: int, high: int, name: str = "参数") -> int:
    """Coerce a query value into an inclusive integer range.

    Args:
        value: Raw caller value; ``None`` or blank falls back to ``default``.
        default: Value used when the caller omits the parameter.
        low: Inclusive lower bound.
        high: Inclusive upper bound.
        name: Parameter name used in the validation error.

    Returns:
        The clamped integer.

    Raises:
        MemoryError: When the value is not an integer.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        value = default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise MemoryError(f"{name} 必须是整数", 400) from exc
    return max(low, min(number, high))


def _num(value, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(default)
    return float(value)


def _event_parts(event: dict) -> tuple[dict, dict, dict]:
    assessment = event.get("assessment") if isinstance(event.get("assessment"), dict) else {}
    after = event.get("after") if isinstance(event.get("after"), dict) else {}
    state = after.get("state") if isinstance(after.get("state"), dict) else {}
    relation = after.get("relation") if isinstance(after.get("relation"), dict) else {}
    return assessment, state, relation


def _mood_label(value) -> str | None:
    mood_value = str(value or "").strip()
    if not mood_value:
        return None
    return mood.MOOD_LABEL.get(mood_value, mood_value)


def _mood_current(event: dict) -> dict:
    assessment, state, _ = _event_parts(event)
    value = assessment.get("mood") or state.get("mood")
    return {
        "mood": str(value or "") or None,
        "label": _mood_label(value),
        "intensity": _num(state.get("intensity")),
        "energy": _num(state.get("energy")),
        "social": _num(state.get("social")),
    }


def _mood_event(event: dict) -> dict:
    assessment, _, relation = _event_parts(event)
    value = assessment.get("mood")
    return {
        "created": _num(event.get("created")),
        "mood": str(value or "") or None,
        "label": _mood_label(value),
        "reason": str(assessment.get("reason") or ""),
        "tone_hint": str(assessment.get("tone_hint") or ""),
        "anger_delta": _num(assessment.get("anger_delta")),
        "affection_delta": _num(assessment.get("affection_delta")),
        "familiarity_delta": _num(assessment.get("familiarity_delta")),
        "anger": _num(relation.get("anger")),
        "affection": _num(relation.get("affection")),
        "familiarity": _num(relation.get("familiarity")),
        "error": str(event.get("error") or ""),
    }


def _platform_key(value) -> str:
    """统一记忆插件与本地心情库的平台标识（AstrBot 用 aiocqhttp，心情用 qq）。"""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in {"aiocqhttp", "qq", "qq_official"}:
        return "qq"
    if "bili" in text:
        return "bilibili"
    if "douyin" in text:
        return "douyin"
    return text


def merge_relations(
    inst: dict,
    relations,
    *,
    relation_lookup=None,
    events_lookup=None,
) -> list[dict]:
    """Merge manager-side mood relations/events into plugin relation cards.

    Cards are matched by ``platform`` + ``sender_id`` (``person_key`` in the
    mood store). Plugin data is copied, never mutated, and neither lookup
    writes to the mood database.

    Args:
        inst: Instance dictionary; ``id`` selects the mood rows.
        relations: Relation cards returned by the plugin.
        relation_lookup: Optional override of ``mood.get_relation`` for tests.
        events_lookup: Optional override of ``mood.events`` for tests.

    Returns:
        New cards with a nullable ``mood`` block. Lookup failures degrade to
        ``None`` so a local mood database problem never hides memory relations.
    """
    items = (
        [dict(item) for item in relations if isinstance(item, dict)]
        if isinstance(relations, list)
        else []
    )
    instance_id = str(inst.get("id") or "").strip()
    if not instance_id or not items:
        return items
    relation_lookup = relation_lookup or mood.get_relation
    events_lookup = events_lookup or mood.events
    try:
        all_events = events_lookup(instance_id, MOOD_EVENT_SCAN)
    except Exception:  # noqa: BLE001
        all_events = []
    if not isinstance(all_events, list):
        all_events = []

    for item in items:
        platform = _platform_key(item.get("platform"))
        sender_id = str(item.get("sender_id") or "").strip()
        identity_key = str(item.get("identity_key") or "").strip()
        if ":" in identity_key:
            key_platform, key_sender = identity_key.split(":", 1)
            platform = platform or _platform_key(key_platform)
            sender_id = sender_id or key_sender.strip()
        if not platform or not sender_id:
            item["mood"] = None
            continue
        try:
            row = relation_lookup(instance_id, platform, sender_id)
        except Exception:  # noqa: BLE001
            row = None
        events = [
            event
            for event in all_events
            if isinstance(event, dict)
            and _platform_key(event.get("platform")) == platform
            and str(event.get("person_key") or "").strip() == sender_id
        ]
        # The plugin store already returns newest-first; sorting again keeps
        # injected/unsorted payloads deterministic for "current mood".
        events.sort(key=lambda event: -_num(event.get("created")))
        if not isinstance(row, dict) and not events:
            item["mood"] = None
            continue
        row = row if isinstance(row, dict) else {}
        item["mood"] = {
            "anger": _num(row.get("anger")),
            "affection": _num(row.get("affection")),
            "familiarity": _num(row.get("familiarity")),
            "display_name": str(row.get("display_name") or ""),
            "last_seen": _num(row.get("last_seen")),
            "updated": _num(row.get("updated")),
            "thread_key": str(row.get("last_thread") or ""),
            "current": _mood_current(events[0]) if events else None,
            "events": [_mood_event(event) for event in events[:MOOD_EVENT_LIMIT]],
        }
    return items


def lock_for(inst: dict, name: str) -> threading.Lock:
    key = f"{inst.get('id') or inst.get('root')}:{name}"
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _locked(inst: dict, name: str, message: str):
    lock = lock_for(inst, name)
    if not lock.acquire(blocking=False):
        raise MemoryError(message, 409)
    return lock


def call_status(inst, call=dashboard.call) -> dict:
    return _call(inst, "GET", "human/status", call=call)


def call_memories(inst, query: dict, call=dashboard.call) -> dict:
    return _call(inst, "GET", "memories", query=query, call=call)


def call_detail(inst, memory_id: int, call=dashboard.call) -> dict:
    return _call(
        inst,
        "GET",
        "memories/detail",
        query={"memory_id": _memory_id(memory_id)},
        call=call,
    )


def call_update(
    inst,
    memory_id: int,
    field: str,
    value,
    reason: str = "",
    call=dashboard.call,
) -> dict:
    return _call(
        inst,
        "POST",
        "memories/update",
        {
            "memory_id": _memory_id(memory_id),
            "field": str(field),
            "value": value,
            "reason": str(reason or ""),
        },
        timeout=TIMEOUTS["resummarize"],
        call=call,
    )


def call_resummarize(inst, memory_id: int, call=dashboard.call) -> dict:
    return _call(
        inst,
        "POST",
        "memories/resummarize",
        {"memory_id": _memory_id(memory_id)},
        timeout=TIMEOUTS["resummarize"],
        call=call,
    )


def call_arousal_update(
    inst,
    memory_id: int,
    arousal,
    reason: str = "",
    call=dashboard.call,
) -> dict:
    """Correct one memory's arousal through the plugin human API.

    Args:
        inst: Instance dictionary with the dashboard address.
        memory_id: Positive memory document id.
        arousal: New arousal value inside the inclusive 0-1 range.
        reason: Optional audit reason, at most 120 characters.
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload with ``before``/``after`` arousal and salience.

    Raises:
        MemoryError: On invalid arguments or plugin failure.
    """
    body = {
        "memory_id": _memory_id(memory_id),
        "arousal": _arousal(arousal),
        "reason": str(reason or "").strip(),
    }
    if len(body["reason"]) > 120:
        raise MemoryError("reason 不能超过 120 字", 400)
    return _call(
        inst,
        "POST",
        "human/memory/arousal",
        body,
        timeout=TIMEOUTS["arousal"],
        call=call,
    )


def call_prompt_preview(inst, scope: str = "private", call=dashboard.call) -> dict:
    return _call(
        inst,
        "GET",
        "human/prompt/preview",
        query={"scope": _scope(scope)},
        timeout=TIMEOUTS["prompt_preview"],
        call=call,
    )


def call_prompt_merge(
    inst,
    scope: str,
    confirm: str = "",
    call=dashboard.call,
) -> dict:
    """Back up and merge the missing prompt fields after explicit confirmation.

    Args:
        inst: Instance dictionary with the dashboard address.
        scope: ``private`` or ``group`` prompt scope.
        confirm: Must be the literal ``MERGE``.
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload describing the backup path and merged fields.

    Raises:
        MemoryError: On invalid scope/confirmation, concurrent merge or plugin
            failure.
    """
    body = {"scope": _scope(scope), "confirm": str(confirm or "")}
    if body["confirm"] != "MERGE":
        raise MemoryError('需要 confirm 为 "MERGE" 才能合并提示词', 400)
    lock = _locked(inst, "prompt_merge", "已有提示词合并任务在运行")
    try:
        return _call(
            inst,
            "POST",
            "human/prompt/merge",
            body,
            timeout=TIMEOUTS["prompt_merge"],
            call=call,
        )
    finally:
        lock.release()


def call_working(
    inst,
    session_id: str = "",
    limit: int = 20,
    call=dashboard.call,
) -> dict:
    """Read one session's working memory or the recent session list.

    Args:
        inst: Instance dictionary with the dashboard address.
        session_id: Optional session to inspect; blank lists recent sessions.
        limit: Maximum recent memories/atoms/graph entries (1-100).
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin snapshot with ``sessions`` or the flat session detail.

    Raises:
        MemoryError: On invalid arguments or plugin failure.
    """
    query = {"limit": _bounded_int(limit, 20, 1, 100, "limit")}
    session = str(session_id or "").strip()
    if session:
        query["session_id"] = session
    return _call(
        inst,
        "GET",
        "human/working",
        query=query,
        timeout=TIMEOUTS["working"],
        call=call,
    )


def call_relations(
    inst,
    days: int = 90,
    limit: int = 100,
    call=dashboard.call,
    *,
    relation_lookup=None,
    events_lookup=None,
) -> dict:
    """Read participant relation cards and merge local mood relation data.

    Args:
        inst: Instance dictionary with the dashboard address.
        days: Aggregation window in days (1-3650).
        limit: Maximum relation cards (1-500).
        call: Injectable dashboard transport used by tests.
        relation_lookup: Optional ``mood.get_relation`` override.
        events_lookup: Optional ``mood.events`` override.

    Returns:
        ``{"relations": [...]}`` where each card also carries ``mood``.

    Raises:
        MemoryError: On invalid arguments or plugin failure.
    """
    query = {
        "days": _bounded_int(days, 90, 1, 3650, "days"),
        "limit": _bounded_int(limit, 100, 1, 500, "limit"),
    }
    data = _call(
        inst,
        "GET",
        "human/relations",
        query=query,
        timeout=TIMEOUTS["relations"],
        call=call,
    )
    relations = data.get("relations") if isinstance(data, dict) else data
    if not isinstance(relations, list):
        relations = []
    return {
        "relations": merge_relations(
            inst,
            relations,
            relation_lookup=relation_lookup,
            events_lookup=events_lookup,
        )
    }


def call_emotion(
    inst,
    identity_key: str,
    days: int = 90,
    limit: int = 200,
    call=dashboard.call,
) -> dict:
    """Read one identity's memory emotion timeline.

    Args:
        inst: Instance dictionary with the dashboard address.
        identity_key: ``platform:sender_id`` identity key from relations.
        days: Timeline window in days (1-3650).
        limit: Maximum timeline items (1-500).
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload with ``items``.

    Raises:
        MemoryError: On invalid arguments or plugin failure.
    """
    identity = str(identity_key or "").strip()
    if not identity:
        raise MemoryError("identity_key 不能为空", 400)
    query = {
        "identity_key": identity,
        "days": _bounded_int(days, 90, 1, 3650, "days"),
        "limit": _bounded_int(limit, 200, 1, 500, "limit"),
    }
    return _call(
        inst,
        "GET",
        "human/emotion",
        query=query,
        timeout=TIMEOUTS["emotion"],
        call=call,
    )


def call_forgetting(
    inst,
    limit: int = 50,
    status: str = "active",
    call=dashboard.call,
) -> dict:
    """Read the forgetting-risk ranking computed by the plugin.

    Args:
        inst: Instance dictionary with the dashboard address.
        limit: Maximum risk rows (1-200).
        status: ``active``, ``archived`` or ``all``.
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload with ``items`` sorted by risk.

    Raises:
        MemoryError: On invalid arguments or plugin failure.
    """
    status_filter = str(status or "active").strip().lower() or "active"
    if status_filter not in EXPORT_STATUSES:
        raise MemoryError("status 必须是 active、archived 或 all", 400)
    query = {
        "limit": _bounded_int(limit, 50, 1, 200, "limit"),
        "status": status_filter,
    }
    return _call(
        inst,
        "GET",
        "human/health/forgetting",
        query=query,
        timeout=TIMEOUTS["forgetting"],
        call=call,
    )


def call_review_preview(inst, memory_id, call=dashboard.call) -> dict:
    """Preview a rehearsal without writing access/rehearsal counters.

    The preview is read-only, so it deliberately takes no instance lock: two
    previews may run concurrently and never block sleep/backfill jobs.

    Args:
        inst: Instance dictionary with the dashboard address.
        memory_id: Positive memory document id.
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload with ``before``/``after`` counters and ``writes=False``.

    Raises:
        MemoryError: On invalid id or plugin failure.
    """
    return _call(
        inst,
        "POST",
        "human/health/review-preview",
        {"memory_id": _memory_id(memory_id)},
        timeout=TIMEOUTS["review_preview"],
        call=call,
    )


def call_review(inst, memory_id, confirm: str = "", call=dashboard.call) -> dict:
    """Reinforce one memory after explicit REVIEW confirmation.

    The write takes the per-instance ``review`` lock so two confirmations
    cannot race the same rehearse path. Counters only; the plugin never
    rewrites the memory text or importance here.

    Args:
        inst: Instance dictionary with the dashboard address.
        memory_id: Positive memory document id.
        confirm: Must be the literal ``REVIEW``.
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload with the reinforced memory id and status.

    Raises:
        MemoryError: On invalid id/confirmation, a concurrent review (409) or
            plugin failure.
    """
    body = {"memory_id": _memory_id(memory_id), "confirm": str(confirm or "")}
    if body["confirm"] != "REVIEW":
        raise MemoryError('需要 confirm 为 "REVIEW" 才能执行复习', 400)
    lock = _locked(inst, "review", "已有复习任务在运行")
    try:
        return _call(
            inst,
            "POST",
            "human/health/review",
            body,
            timeout=TIMEOUTS["review"],
            call=call,
        )
    finally:
        lock.release()


def call_active_recall_status(inst, call=dashboard.call) -> dict:
    """Read active recall configuration and today's counters.

    Args:
        inst: Instance dictionary with the dashboard address.
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload with config, today's shadow/real counters and paths.

    Raises:
        MemoryError: On plugin failure.
    """
    return _call(
        inst,
        "GET",
        "human/active-recall/status",
        timeout=TIMEOUTS["active_recall"],
        call=call,
    )


def call_active_recall_events(inst, limit: int = 50, call=dashboard.call) -> dict:
    """Read recent shadow/real active recall events, newest first.

    Args:
        inst: Instance dictionary with the dashboard address.
        limit: Maximum events (1-200).
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload with ``items`` and ``count``.

    Raises:
        MemoryError: On a non-integer limit or plugin failure.
    """
    query = {"limit": _bounded_int(limit, 50, 1, 200, "limit")}
    return _call(
        inst,
        "GET",
        "human/active-recall/events",
        query=query,
        timeout=TIMEOUTS["active_recall"],
        call=call,
    )


def call_active_recall_preview(
    inst,
    query,
    session_id: str = "",
    call=dashboard.call,
) -> dict:
    """Preview active recall selection without writing or injecting.

    The plugin runs its selection in dry-run mode against the existing recall
    results, so the preview is read-only and takes no instance lock.

    Args:
        inst: Instance dictionary with the dashboard address.
        query: Non-empty recall query text.
        session_id: Optional session scope for the preview.
        call: Injectable dashboard transport used by tests.

    Returns:
        Plugin payload with the dry-run selection and blocked reason.

    Raises:
        MemoryError: On a blank query or plugin failure.
    """
    text = str(query or "").strip()
    if not text:
        raise MemoryError("query 不能为空", 400)
    body = {"query": text}
    session = str(session_id or "").strip()
    if session:
        body["session_id"] = session
    return _call(
        inst,
        "POST",
        "human/active-recall/preview",
        body,
        timeout=TIMEOUTS["active_recall_preview"],
        call=call,
    )


def _strip_embeddings(value):
    """Drop embedding/vector keys at any depth of an export metadata tree."""
    if isinstance(value, dict):
        return {
            key: _strip_embeddings(child)
            for key, child in value.items()
            if str(key).strip().lower() not in _EMBEDDING_KEYS
        }
    if isinstance(value, list):
        return [_strip_embeddings(child) for child in value]
    return value


def _export_item(item: dict) -> dict:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict) and isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
        except (TypeError, ValueError):
            parsed = {}
        metadata = parsed if isinstance(parsed, dict) else {}
    return {
        "id": item.get("id"),
        "text": str(item.get("text") or ""),
        "metadata": _strip_embeddings(metadata) if isinstance(metadata, dict) else {},
        "created_at": item.get("created_at"),
    }


def export_filename(inst: dict, now=None) -> str:
    """Build a header-safe JSON export filename with instance and time.

    Args:
        inst: Instance dictionary; the id is preferred because it is stable
            ASCII, then the display name.
        now: Optional unix timestamp used by tests.

    Returns:
        ``memory-<label>-<YYYYmmdd-HHMMSS>.json`` containing only
        ``[A-Za-z0-9_-]`` label characters, safe inside a quoted header.
    """
    moment = time.time() if now is None else float(now)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(moment))
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", str(inst.get("id") or "")).strip("-_")
    if not label:
        label = re.sub(r"[^A-Za-z0-9_-]+", "-", str(inst.get("name") or "")).strip("-_")
    return f"memory-{label or 'instance'}-{stamp}.json"


def export_memories(
    inst,
    filters=None,
    call=dashboard.call,
    *,
    page_size: int = EXPORT_PAGE_SIZE,
    max_pages: int = EXPORT_MAX_PAGES,
) -> dict:
    """Collect the filtered memory list as read-only export rows.

    Pages are fetched with GET only; nothing is written to the plugin or the
    manager. Embedding vectors are stripped from ``metadata`` recursively.

    Args:
        inst: Instance dictionary with the dashboard address.
        filters: ``q``/``keyword``, ``type`` and ``status`` filters.
        call: Injectable dashboard transport used by tests.
        page_size: Rows requested per page (capped at 500).
        max_pages: Safety cap on fetched pages.

    Returns:
        Export payload with ``items`` (id/text/metadata/created_at), counts,
        filters, truncated flag and a safe ``filename``.

    Raises:
        MemoryError: On an unsupported status or plugin failure.
    """
    params = filters if isinstance(filters, dict) else {}
    keyword = str(params.get("q") or params.get("keyword") or "").strip()
    memory_type = str(params.get("type") or "").strip()
    status = str(params.get("status") or "all").strip().lower() or "all"
    if status not in EXPORT_STATUSES:
        raise MemoryError("status 必须是 all、active 或 archived", 400)
    page_size = max(1, min(int(page_size), 500))
    max_pages = max(1, int(max_pages))

    rows: list[dict] = []
    total = 0
    truncated = False
    for page in range(1, max_pages + 1):
        data = call_memories(
            inst,
            {
                "keyword": keyword,
                "type": memory_type or None,
                "status": status,
                "sort": "created_desc",
                "page": page,
                "page_size": page_size,
            },
            call,
        )
        if isinstance(data, list):
            items = data
            has_more = False
        elif isinstance(data, dict):
            items = data.get("items") or data.get("memories") or []
            has_more = bool(data.get("has_more"))
            if data.get("total") is not None:
                try:
                    total = int(data["total"])
                except (TypeError, ValueError):
                    total = 0
        else:
            items = []
            has_more = False
        rows.extend(_export_item(item) for item in items if isinstance(item, dict))
        if not has_more or not items:
            break
        if page == max_pages:
            truncated = True
    return {
        "instance_id": inst.get("id"),
        "instance_name": inst.get("name"),
        "filters": {"q": keyword, "type": memory_type, "status": status},
        "count": len(rows),
        "total": total if total >= len(rows) else len(rows),
        "truncated": truncated,
        "filename": export_filename(inst),
        "items": rows,
    }


def call_recall(inst, payload: dict, call=dashboard.call) -> dict:
    return _call(
        inst,
        "POST",
        "recall/test",
        payload,
        timeout=TIMEOUTS["recall"],
        call=call,
    )


def call_vector_status(inst, call=dashboard.call) -> dict:
    return _call(
        inst, "GET", "human/vector/status",
        timeout=TIMEOUTS["vector"], call=call)


def call_vector_probe(inst, call=dashboard.call) -> dict:
    return _call(
        inst, "POST", "human/vector/probe", {},
        timeout=TIMEOUTS["vector_probe"], call=call)


def call_vector_rebuild(inst, call=dashboard.call) -> dict:
    return _call(
        inst, "POST", "human/vector/rebuild", {},
        timeout=TIMEOUTS["vector_rebuild"], call=call)


def call_graph(inst, query: dict, call=dashboard.call) -> dict:
    return _call(inst, "GET", "graph/overview", query=query, call=call)


def call_sleep_status(inst, call=dashboard.call) -> dict:
    return _call(inst, "GET", "human/sleep/status", call=call)


def call_sleep_preview(inst, call=dashboard.call) -> dict:
    return _call(
        inst,
        "GET",
        "human/sleep/preview",
        timeout=TIMEOUTS["sleep_preview"],
        call=call,
    )


def call_sleep_reports(inst, limit: int = 30, call=dashboard.call) -> dict:
    return _call(
        inst,
        "GET",
        "human/sleep/reports",
        query={"limit": max(1, min(int(limit), 100))},
        call=call,
    )


def call_sleep_run(inst, call=dashboard.call) -> dict:
    lock = _locked(inst, "sleep", "已有睡眠任务在运行")
    try:
        return _call(
            inst,
            "POST",
            "human/sleep/run",
            {},
            timeout=TIMEOUTS["sleep_run"],
            call=call,
        )
    finally:
        lock.release()


def call_recon_status(inst, call=dashboard.call) -> dict:
    return _call(inst, "GET", "human/reconsolidation/status", call=call)


def call_recon_manual(
    inst, payload: dict, mode: str, call=dashboard.call
) -> dict:
    lock = _locked(inst, "recon_manual", "已有手动再巩固任务在运行")
    try:
        body = {
            "memory_id": _memory_id(payload.get("memory_id")),
            "user_message": str(payload.get("user_message", "")),
            "mode": "preview" if mode == "preview" else "apply",
        }
        return _call(
            inst,
            "POST",
            "human/reconsolidation/manual",
            body,
            timeout=(
                TIMEOUTS["recon_preview"]
                if body["mode"] == "preview"
                else TIMEOUTS["recon_apply"]
            ),
            call=call,
        )
    finally:
        lock.release()


def call_backfill_preview(inst, call=dashboard.call) -> dict:
    return _call(
        inst,
        "GET",
        "human/backfill/preview",
        timeout=TIMEOUTS["backfill_preview"],
        call=call,
    )


def call_backfill_status(inst, call=dashboard.call) -> dict:
    return _call(inst, "GET", "human/backfill/status", call=call)


def call_backfill_run(inst, call=dashboard.call) -> dict:
    lock = _locked(inst, "backfill", "已有回填任务在运行")
    try:
        return _call(
            inst,
            "POST",
            "human/backfill/run",
            {},
            timeout=TIMEOUTS["backfill_run"],
            call=call,
        )
    finally:
        lock.release()


def call_backfill_cancel(inst, call=dashboard.call) -> dict:
    return _call(inst, "POST", "human/backfill/cancel", {}, call=call)


def call_config(inst, call=dashboard.call) -> dict:
    return _call(inst, "GET", "config", query={"lang": "zh"}, call=call)


def filter_config_values(values) -> dict:
    if not isinstance(values, dict) or not values:
        raise MemoryError("没有需要保存的配置项", 400)
    bad = sorted(
        key
        for key in values
        if not str(key).startswith(ALLOWED_CONFIG_PREFIX)
        and str(key) not in EXTRA_CONFIG_PATHS
    )
    if bad:
        raise MemoryError(f"不支持的配置项: {', '.join(bad)}", 400)
    return values


def call_save_config(inst, values: dict, call=dashboard.call) -> dict:
    payload = {"values": filter_config_values(values)}
    return _call(inst, "POST", "config/update", payload, call=call)
