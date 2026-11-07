"""每日心情：全局状态、关系态度、模型评估与语气块。"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import random
import time
import uuid

from . import dashboard, fleet_store, human_settings, llm

MOODS = ("calm", "happy", "low", "annoyed", "angry")
MOOD_LABEL = {
    "calm": "平静", "happy": "开心", "low": "低落",
    "annoyed": "烦躁", "angry": "生气",
}
MOOD_TONE = {
    "calm": "正常聊天，放松一点。",
    "happy": "语气轻快一点，可以主动接话。",
    "low": "话少一点，别硬撑热情。",
    "annoyed": "有点不耐烦，回复短一些。",
    "angry": "语气冷一点，别主动讨好。",
}
MAX_BLOCK = 240


class MoodError(Exception):
    pass


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _num(value, default=0.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(default)
    return float(value)


def mood_date(ts=None, reset_hour=5) -> str:
    dt = _dt.datetime.fromtimestamp(time.time() if ts is None else float(ts))
    if dt.hour < int(reset_hour):
        dt -= _dt.timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def day_start(reset_hour=5, ts=None) -> float:
    now = time.time() if ts is None else float(ts)
    dt = _dt.datetime.fromtimestamp(now).replace(minute=0, second=0, microsecond=0)
    cutoff = dt.replace(hour=int(reset_hour))
    if dt < cutoff:
        cutoff -= _dt.timedelta(days=1)
    return cutoff.timestamp()


def _default_state() -> dict:
    return {
        "mood": "calm",
        "intensity": round(random.uniform(30, 50), 1),
        "energy": round(random.uniform(55, 80), 1),
        "social": round(random.uniform(45, 75), 1),
        "source": "daily_reset",
    }


def _ensure_global(conn, instance_id: str, reset_hour: int, now: float) -> dict:
    # 先只读判日期：行已存在且就是当前日键时直接返回，避免心情页每 2 秒轮询都触发写库。
    key = mood_date(now, reset_hour)
    row = conn.execute(
        "SELECT * FROM human_global WHERE instance_id=?", (instance_id,)
    ).fetchone()
    if row is not None and row["date"] == key:
        return dict(row)
    # 缺失或跨日才走 UPSERT（DO UPDATE ... WHERE 需 SQLite >= 3.24）：日期不同才会覆盖成
    # 当日随机状态；以 rowcount 判断本次是否真的跨日，保证关系衰减每日恰好一次，避免并发重复衰减。
    state = _default_state()
    cur = conn.execute(
        "INSERT INTO human_global(instance_id, date, mood, intensity, energy, social, source, updated) "
        "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(instance_id) DO UPDATE SET "
        "date=excluded.date, mood=excluded.mood, intensity=excluded.intensity, "
        "energy=excluded.energy, social=excluded.social, source=excluded.source, updated=excluded.updated "
        "WHERE human_global.date<>excluded.date",
        (instance_id, key, state["mood"], state["intensity"], state["energy"],
         state["social"], state["source"], now),
    )
    if cur.rowcount and row is not None:
        # 只有“行原本存在、日期又不同”才是跨日重置；首次插入不衰减既有关系。
        conn.execute(
            "UPDATE human_relations SET anger=anger*0.9, affection=affection*0.9, updated=? "
            "WHERE instance_id=?", (now, instance_id),
        )
    row = conn.execute(
        "SELECT * FROM human_global WHERE instance_id=?", (instance_id,)
    ).fetchone()
    return dict(row)


def get_state(instance_id: str, db_path=None) -> dict:
    reset_hour = int(human_settings.get_settings(instance_id, db_path=db_path)["reset_hour"])
    with fleet_store.session(db_path) as conn:
        return _ensure_global(conn, instance_id, reset_hour, time.time())


def _relation_row(row) -> dict | None:
    return dict(row) if row is not None else None


def get_relation(instance_id: str, platform: str, person_key: str, db_path=None) -> dict | None:
    if not person_key:
        return None
    with fleet_store.session(db_path) as conn:
        return _relation_row(conn.execute(
            "SELECT * FROM human_relations WHERE instance_id=? AND platform=? AND person_key=?",
            (instance_id, platform, person_key),
        ).fetchone())


def _upsert_relation(conn, instance_id, platform, person_key, display_name,
                     anger, affection, familiarity, thread_key, now) -> dict:
    row = conn.execute(
        "SELECT * FROM human_relations WHERE instance_id=? AND platform=? AND person_key=?",
        (instance_id, platform, person_key),
    ).fetchone()
    rel_id = row["id"] if row else "rel_" + uuid.uuid4().hex[:12]
    # 昵称为空时保留原显示名，避免一次无 sender_name 的消息把已有昵称覆盖成空串。
    existing_name = str(row["display_name"] or "") if row is not None else ""
    display_name = str(display_name or "").strip() or existing_name
    conn.execute(
        "INSERT INTO human_relations(id, instance_id, platform, person_key, display_name, "
        "anger, affection, familiarity, last_thread, last_seen, updated) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(instance_id, platform, person_key) DO UPDATE SET "
        "display_name=excluded.display_name, anger=excluded.anger, affection=excluded.affection, "
        "familiarity=excluded.familiarity, last_thread=excluded.last_thread, "
        "last_seen=excluded.last_seen, updated=excluded.updated",
        (rel_id, instance_id, platform, person_key, display_name,
         _clamp(anger, 0, 100), _clamp(affection, -100, 100),
         _clamp(familiarity, 0, 100), thread_key, now, now),
    )
    return _relation_row(conn.execute(
        "SELECT * FROM human_relations WHERE instance_id=? AND platform=? AND person_key=?",
        (instance_id, platform, person_key),
    ).fetchone()) or {}


def _current_rhythm(instance_id: str, db_path=None) -> dict:
    """读取节律状态；任何失败都返回空字典，心情注入不能因此中断。"""
    try:
        from . import rhythm as rhythm_mod
        return rhythm_mod.current(instance_id, db_path=db_path)
    except Exception:  # noqa: BLE001 - 节律只是附加状态
        return {}


def build_prompt_block(state: dict, relation: dict | None = None,
                       tone_hint: str = "", rhythm_state: dict | None = None) -> str:
    mood = state.get("mood") if state.get("mood") in MOODS else "calm"
    # 先按展示口径钳制，避免异常大数（如 1e12）把固定骨架撑爆、挤掉语气提示与内部说明。
    intensity = _clamp(_num(state.get("intensity")), 0, 100)
    energy = _clamp(_num(state.get("energy")), 0, 100)
    social = _clamp(_num(state.get("social")), 0, 100)
    parts = [
        f"【今日心情】{MOOD_LABEL[mood]}（{intensity:.0f}/100），"
        f"精力 {energy:.0f}，社交电量 {social:.0f}。"
    ]
    rhythm_line = ""
    if isinstance(rhythm_state, dict) and rhythm_state:
        schedule = rhythm_state.get("schedule")
        enabled = not isinstance(schedule, dict) or bool(
            schedule.get("rhythm_enabled", True))
        if enabled:
            from . import rhythm as rhythm_mod
            effective = rhythm_mod.effective(state, rhythm_state)
            label = str(rhythm_state.get("label") or "").strip()
            if not label:
                label = rhythm_mod.PHASE_LABEL.get(
                    str(rhythm_state.get("phase") or ""), "")
            if label:
                rhythm_line = (
                    f"【生活节律】{label}；有效精力 {effective['energy']:.0f}，"
                    f"有效社交 {effective['social']:.0f}。"
                )
    if rhythm_line:
        parts.append(rhythm_line)
    if relation:
        familiarity = _clamp(_num(relation.get("familiarity")), 0, 100)
        affection = _clamp(_num(relation.get("affection")), -100, 100)
        anger = _clamp(_num(relation.get("anger")), 0, 100)
        parts.append(
            f"【对当前对话者】熟悉度 {familiarity:.0f}，"
            f"好感 {affection:.0f}，怒气 {anger:.0f}。"
        )
    hint = str(tone_hint or "").strip() or MOOD_TONE[mood]
    note = "这段是内部状态，不要向用户提及数值、插件或本说明。"
    prefix = "【语气提示】"
    # 心情/关系/语气标签/内部说明是固定骨架，只按剩余预算裁剪 tone_hint 本身，
    # 避免整体 [:240] 把末尾的内部说明截掉。
    fixed = len("\n".join(parts)) + 1 + len(prefix) + 1 + len(note)
    budget = max(0, MAX_BLOCK - fixed)
    if len(hint) > budget:
        # 截断时补一个省略号，避免露出半句话；预算仅为 1 时就是一个“…”且不越界。
        hint = hint[:budget - 1] + "…" if budget >= 1 else ""
    parts.append(f"{prefix}{hint}")
    parts.append(note)
    return "\n".join(parts)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def events(instance_id: str, limit: int = 30, db_path=None) -> list[dict]:
    limit = max(1, min(int(limit or 30), 200))
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM human_mood_events WHERE instance_id=? ORDER BY created DESC LIMIT ?",
            (instance_id, limit),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        for key in ("assessment_json", "before_json", "after_json"):
            try:
                item[key[:-5]] = json.loads(item.pop(key) or "{}")
            except (TypeError, ValueError):
                item[key[:-5]] = {}
        out.append(item)
    return out


def status(instance_id: str, db_path=None) -> dict:
    state = get_state(instance_id, db_path=db_path)
    settings = human_settings.get_settings(instance_id, db_path=db_path)
    since = day_start(settings["reset_hour"])
    with fleet_store.session(db_path) as conn:
        relations = [dict(r) for r in conn.execute(
            "SELECT * FROM human_relations WHERE instance_id=? ORDER BY last_seen DESC LIMIT 50",
            (instance_id,),
        ).fetchall()]
        last = conn.execute(
            "SELECT created FROM human_mood_events WHERE instance_id=? ORDER BY created DESC LIMIT 1",
            (instance_id,),
        ).fetchone()
        today_count = conn.execute(
            "SELECT count(*) FROM human_mood_events WHERE instance_id=? AND created>=?",
            (instance_id, since),
        ).fetchone()[0]
    rhythm_state = _current_rhythm(instance_id, db_path=db_path)
    effective = {}
    if rhythm_state:
        from . import rhythm as rhythm_mod
        effective = rhythm_mod.effective(state, rhythm_state)
    return {
        "state": state,
        "relations": relations,
        "events": events(instance_id, 30, db_path=db_path),
        "settings": settings,
        "rhythm": rhythm_state,
        "effective": effective,
        "today_events": int(today_count or 0),
        "last_observe_at": float(last["created"]) if last else 0,
        "reset_hour": settings["reset_hour"],
    }


def adjust(payload: dict, db_path=None) -> dict:
    instance_id = str(payload.get("instance_id") or "").strip()
    if not instance_id:
        raise MoodError("instance_id 不能为空")
    scope = str(payload.get("scope") or "global")
    now = time.time()
    reset_hour = int(human_settings.get_settings(instance_id, db_path=db_path)["reset_hour"])
    with fleet_store.session(db_path) as conn:
        # 先结算当天状态：每日重置只作用在既有关系上，再累加本次调整，
        # 否则同一天内的调整会被后续 get_state 再衰减一次。
        state = _ensure_global(conn, instance_id, reset_hour, now)
        if scope == "global":
            mood = payload.get("mood", state["mood"])
            if mood not in MOODS:
                raise MoodError("心情取值无效")
            conn.execute(
                "UPDATE human_global SET mood=?, intensity=?, energy=?, social=?, source='manual', updated=? "
                "WHERE instance_id=?",
                (mood,
                 _clamp(payload.get("intensity", state["intensity"]), 0, 100),
                 _clamp(payload.get("energy", state["energy"]), 0, 100),
                 _clamp(payload.get("social", state["social"]), 0, 100),
                 now, instance_id),
            )
        elif scope == "relation":
            platform = str(payload.get("platform") or "qq").strip()
            person_key = str(payload.get("person_key") or "").strip()
            if not person_key:
                raise MoodError("关系级调整需要 person_key")
            rel = _relation_row(conn.execute(
                "SELECT * FROM human_relations WHERE instance_id=? AND platform=? AND person_key=?",
                (instance_id, platform, person_key),
            ).fetchone()) or {}
            _upsert_relation(
                conn, instance_id, platform, person_key,
                str(payload.get("display_name") or rel.get("display_name") or ""),
                payload.get("anger", rel.get("anger", 0)),
                payload.get("affection", rel.get("affection", 0)),
                payload.get("familiarity", rel.get("familiarity", 0)),
                str(payload.get("thread_key") or rel.get("last_thread") or ""), now)
        else:
            raise MoodError("scope 无效")
    return {"state": get_state(instance_id, db_path=db_path),
            "relation": get_relation(instance_id, str(payload.get("platform") or "qq"),
                                     str(payload.get("person_key") or ""), db_path=db_path)}


def reset(payload: dict, db_path=None) -> dict:
    instance_id = str(payload.get("instance_id") or "").strip()
    if not instance_id:
        raise MoodError("instance_id 不能为空")
    scope = str(payload.get("scope") or "global")
    now = time.time()
    reset_hour = int(human_settings.get_settings(instance_id, db_path=db_path)["reset_hour"])
    with fleet_store.session(db_path) as conn:
        # 与 adjust 一致，先结算当天：跨日后的手动重置不能跳过当天关系衰减。
        _ensure_global(conn, instance_id, reset_hour, now)
        if scope == "global":
            state = {"mood": "calm", "intensity": 40.0, "energy": 65.0,
                     "social": 55.0, "source": "manual"}
            conn.execute(
                "INSERT INTO human_global(instance_id, date, mood, intensity, energy, social, source, updated) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(instance_id) DO UPDATE SET "
                "date=excluded.date, mood=excluded.mood, intensity=excluded.intensity, "
                "energy=excluded.energy, social=excluded.social, source=excluded.source, updated=excluded.updated",
                (instance_id, mood_date(now, reset_hour), state["mood"], state["intensity"],
                 state["energy"], state["social"], state["source"], now),
            )
        elif scope == "relation":
            platform = str(payload.get("platform") or "qq").strip()
            person_key = str(payload.get("person_key") or "").strip()
            if not person_key:
                raise MoodError("关系级重置需要 person_key")
            conn.execute(
                "UPDATE human_relations SET anger=0, affection=0, familiarity=0, updated=? "
                "WHERE instance_id=? AND platform=? AND person_key=?",
                (now, instance_id, platform, person_key),
            )
        else:
            raise MoodError("scope 无效")
    return {"state": get_state(instance_id, db_path=db_path)}


APOLOGY_WORDS = ("对不起", "抱歉", "道歉", "原谅", "哄", "安慰", "别生气", "我错了",
                 "抱抱", "亲亲", "摸摸")
_RECENT_LIMIT = 6


def resolve_instance(payload: dict, instances=None) -> dict:
    items = instances or []
    inst_id = str(payload.get("instance_id") or "").strip()
    account_id = str(payload.get("account_id") or "").strip()
    platform_id = str(payload.get("platform_id") or "").strip()
    for item in items:
        if inst_id and item.get("id") == inst_id:
            return item
    for item in items:
        if account_id and item.get("id") == account_id:
            return item
    for item in items:
        if platform_id and str(item.get("platform_id") or "") == platform_id:
            return item
    # 插件传来的 platform_id 实际是 umo 前缀（等于实例名）；源数据 data/instances.json
    # 的 platform_id 可能为 null，因此真实 platform_id 匹配失败后再按实例名回退。
    for item in items:
        if platform_id and str(item.get("name") or "").strip() == platform_id:
            return item
    raise MoodError("未知实例，请检查插件 instance_id 或 platform_id")


def _pick_provider(inst: dict, settings: dict) -> str:
    provider_id = str(settings.get("provider_id") or "").strip()
    if provider_id:
        return provider_id
    try:
        profile = dashboard.call(inst, "GET", "config-profiles/default", timeout=10)
        config = (profile.get("data") or {}).get("config") or {}
        model = ((config.get("agent_runner") or {}).get("config") or {}).get("model") or {}
        provider_id = str(model.get("provider_id") or "").strip()
    except dashboard.DashboardError:
        provider_id = ""
    if provider_id:
        return provider_id
    try:
        data = dashboard.call(inst, "GET", "providers", timeout=10)
    except dashboard.DashboardError as exc:
        raise MoodError(f"读取模型失败：{exc.message}") from None
    items = data.get("data") or {}
    if isinstance(items, dict):
        items = items.get("providers") or items.get("items") or []
    for item in items:
        if isinstance(item, dict) and item.get("provider_type") == "chat_completion":
            return str(item.get("id") or "")
    raise MoodError("没有可用的对话模型")


def _parse_assessment(text: str) -> dict:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON")
    data = json.loads(raw[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是对象")
    return data


def _norm_assessment(data: dict, state: dict) -> dict:
    mood_value = str(data.get("mood") or state["mood"])
    if mood_value not in MOODS:
        mood_value = state["mood"]

    def delta(key, low, high):
        return _clamp(_num(data.get(key), 0), low, high)

    return {
        "mood": mood_value,
        "intensity_delta": delta("intensity_delta", -20, 20),
        "energy_delta": delta("energy_delta", -10, 10),
        "social_delta": delta("social_delta", -10, 10),
        "anger_delta": delta("anger_delta", -25, 25),
        "affection_delta": delta("affection_delta", -10, 10),
        "familiarity_delta": max(0.0, min(3.0, _num(data.get("familiarity_delta"), 0))),
        "reason": str(data.get("reason") or "")[:120],
        "tone_hint": str(data.get("tone_hint") or "")[:80],
    }


def _apply_assessment(conn, instance_id, platform, person_key, thread_key,
                      sender_name, state, relation, assessment, text,
                      now) -> tuple[dict, dict | None]:
    anger_delta = assessment["anger_delta"]
    if relation and relation["anger"] >= 80 and anger_delta < 0:
        # 只认用户原文里的道歉/安慰词；模型 reason 写“用户在道歉”不能作为放宽依据。
        allowed = 25.0 if any(w in str(text or "") for w in APOLOGY_WORDS) else 8.0
        anger_delta = max(anger_delta, -allowed)
    new_state = {
        "mood": assessment["mood"],
        "intensity": _clamp(state["intensity"] + assessment["intensity_delta"], 0, 100),
        "energy": _clamp(state["energy"] + assessment["energy_delta"], 0, 100),
        "social": _clamp(state["social"] + assessment["social_delta"], 0, 100),
        "source": "conversation",
    }
    conn.execute(
        "UPDATE human_global SET mood=?, intensity=?, energy=?, social=?, source=?, updated=? "
        "WHERE instance_id=?",
        (new_state["mood"], new_state["intensity"], new_state["energy"],
         new_state["social"], new_state["source"], now, instance_id),
    )
    new_rel = None
    if person_key:
        base = relation or {"anger": 0, "affection": 0, "familiarity": 0}
        new_rel = _upsert_relation(
            conn, instance_id, platform, person_key, sender_name,
            base["anger"] + anger_delta,
            base["affection"] + assessment["affection_delta"],
            base["familiarity"] + assessment["familiarity_delta"],
            thread_key, now)
    return new_state, new_rel


def _save_event(conn, instance_id, platform, person_key, thread_key, message_hash,
                assessment, before, after, error) -> None:
    conn.execute(
        "INSERT INTO human_mood_events(instance_id, platform, person_key, thread_key, created, "
        "message_hash, assessment_json, before_json, after_json, error) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (instance_id, platform, person_key, thread_key, time.time(), message_hash,
         _json(assessment or {}), _json(before), _json(after), str(error or "")[:300]),
    )


def observe(payload: dict, instances=None, db_path=None) -> dict:
    if not isinstance(payload, dict):
        raise MoodError("消息必须是对象")
    inst = resolve_instance(payload, instances)
    instance_id = str(inst.get("id") or "")
    platform = str(payload.get("platform") or "qq")
    person_key = str(payload.get("person_key") or "")
    thread_key = str(payload.get("thread_key") or "")
    sender_name = str(payload.get("sender_name") or "")
    text = str(payload.get("text") or "").strip()
    settings = human_settings.get_settings(instance_id, db_path=db_path)
    state = get_state(instance_id, db_path=db_path)
    relation = get_relation(instance_id, platform, person_key, db_path=db_path)
    rhythm_state = _current_rhythm(instance_id, db_path=db_path)
    effective = {}
    if rhythm_state:
        from . import rhythm as rhythm_mod
        effective = rhythm_mod.effective(state, rhythm_state)
    block = build_prompt_block(state, relation, rhythm_state=rhythm_state)
    base = {"state": state, "relation": relation, "prompt_block": block,
            "rhythm": rhythm_state, "effective": effective,
            "assessment": None, "latency_ms": 0, "error": "", "enabled": True}
    if not settings["mood_enabled"]:
        # 关闭后不但不评估，也不能把旧状态继续注入；插件收到 enabled=false 会清缓存。
        base.update({"prompt_block": "", "error": "心情评估已关闭", "enabled": False})
        return base
    if not text:
        return base
    provider_id = str(payload.get("provider_id") or "").strip()
    message_hash = hashlib.sha256(
        f"{instance_id}|{platform}|{thread_key}|{person_key}|{text}".encode("utf-8")
    ).hexdigest()
    started = time.time()
    try:
        provider_id = provider_id or _pick_provider(inst, settings)
        recent = payload.get("recent")
        if not isinstance(recent, list):
            recent = []
        recent = [
            {"speaker": str(x.get("speaker") or "")[:20],
             "text": str(x.get("text") or "")[:200]}
            for x in recent[-_RECENT_LIMIT:] if isinstance(x, dict)
        ]
        system = (
            "你是「牧鱼」的情绪观察器。只输出一个 JSON 对象，不要 Markdown、不要解释、不要思维链。\n"
            "字段：mood（calm/happy/low/annoyed/angry）、intensity_delta(-20..20)、"
            "energy_delta(-10..10)、social_delta(-10..10)、anger_delta(-25..25)、"
            "affection_delta(-10..10)、familiarity_delta(0..3)、reason（不超过 40 字）、"
            "tone_hint（不超过 30 字）。\n"
            "判断这条消息对机器人情绪和当前关系的影响。不要因为对方是主人就特殊加分。"
        )
        user = _json({
            "当前心情": state,
            "当前关系": relation,
            "是否主人": bool(payload.get("is_owner")),
            "最近对话": recent,
            "用户这条消息": text[:1000],
        })
        raw = llm.chat(inst, provider_id, [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=300, timeout=10)
        assessment = _norm_assessment(_parse_assessment(raw), state)
        latency = int((time.time() - started) * 1000)
        # 先补上本次调用信息再落库，保证事件列表里能看到耗时才与命中的 provider。
        assessment["latency_ms"] = latency
        assessment["provider_id"] = provider_id
        with fleet_store.session(db_path) as conn:
            before = {"state": state, "relation": relation}
            new_state, new_rel = _apply_assessment(
                conn, instance_id, platform, person_key, thread_key, sender_name,
                state, relation, assessment, text, time.time())
            after = {"state": new_state, "relation": new_rel}
            _save_event(conn, instance_id, platform, person_key, thread_key,
                        message_hash, assessment, before, after, "")
        if rhythm_state:
            from . import rhythm as rhythm_mod
            effective = rhythm_mod.effective(new_state, rhythm_state)
        return {
            "state": new_state, "relation": new_rel,
            "prompt_block": build_prompt_block(
                new_state, new_rel, assessment["tone_hint"],
                rhythm_state=rhythm_state),
            "rhythm": rhythm_state, "effective": effective,
            "assessment": assessment, "latency_ms": latency, "error": "",
            "enabled": True,
        }
    except Exception as exc:
        latency = int((time.time() - started) * 1000)
        try:
            with fleet_store.session(db_path) as conn:
                _save_event(conn, instance_id, platform, person_key, thread_key,
                            message_hash, {}, {"state": state, "relation": relation},
                            {"state": state, "relation": relation}, str(exc))
        except Exception:  # noqa: BLE001
            # 事件落库再失败也只丢审计记录，不能让心情评估接口变成 500。
            pass
        base["latency_ms"] = latency
        base["error"] = str(exc)[:200]
        return base
