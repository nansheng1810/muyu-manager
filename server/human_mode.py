"""拟人表达行为：影子计划、真实沉默/分段/延迟与今日记录。"""

from __future__ import annotations

import hashlib
import random
import time

from . import fleet_store, human_settings, mood, styles

ACTIONS = ("reply", "short", "split", "delay", "silence")
_NEGATIVE_MOODS = ("low", "annoyed", "angry")


class HumanError(Exception):
    pass


def _cfg(instance_id: str, db_path=None) -> dict:
    return human_settings.get_settings(instance_id, db_path=db_path)


def _real_silence_stats(conn, instance_id: str, since: float) -> tuple[int, bool]:
    """当日真实沉默数与上一条真实行为是否为沉默；均由 SQL 聚合，不受历史条数上限影响。"""
    count_row = conn.execute(
        "SELECT count(*) FROM human_behavior_events WHERE instance_id=? AND created>=? "
        "AND action='silence' AND shadow=0", (instance_id, since),
    ).fetchone()
    last_row = conn.execute(
        "SELECT action FROM human_behavior_events WHERE instance_id=? AND created>=? "
        "AND shadow=0 ORDER BY created DESC LIMIT 1", (instance_id, since),
    ).fetchone()
    return int(count_row[0] if count_row else 0), bool(last_row and last_row[0] == "silence")


def _log_event(conn, instance_id, thread_key, action, reason, shadow, text_hash, now):
    conn.execute(
        "INSERT INTO human_behavior_events(instance_id, thread_key, action, reason, shadow, created, text_hash) "
        "VALUES(?,?,?,?,?,?,?)",
        (instance_id, thread_key, action, reason, 1 if shadow else 0, now, text_hash),
    )


OWNER_IDENTITY = (
    "【身份校准】当前说话的人是你爸爸本人（主人/管理员），不是在群里逗你的群友，也不是冒充者。"
    "群里的昵称显示成「南笙、」「南笙.」或带别的符号，也是他；不要用「我爸是南笙」这种话防着他。"
    "他让你叫爹、叫爸，是父子间的玩笑，直接叫，别翻昨天谁逗过你。"
)


def style_block(instance_id: str, person_key: str, is_owner: bool, db_path: str) -> str:
    base = styles.style_prompt(instance_id, person_key, db_path=db_path)
    if not is_owner:
        return base
    return "\n\n".join(x for x in (base, OWNER_IDENTITY) if x)


def behavior_hint(action: str, is_owner: bool) -> str:
    if is_owner:
        base = "【表达方式】对方是主人/管理员，认真正常回复，不要敷衍。"
        if action == "split":
            return base + "可以分两小段说，但别拖延。"
        if action == "delay":
            return base + "语气自然一点。"
        return base
    if action == "short":
        return "【表达方式】这轮短一点，一两句话就够，别展开。"
    if action == "split":
        return "【表达方式】可以分两小段说，像聊天一样，不要长篇。"
    if action == "delay":
        return "【表达方式】语气自然一点，不用急着收尾。"
    return ""


def _choose_action(settings, state, relation, payload, silence_count,
                   last_silence, rng, effective=None) -> tuple[str, str]:
    action = "reply"
    reason = "正常回复"
    # 身份不明（非 bool）按主人处理；命令/工具调用缺失按 True 处理，只有显式 false 才允许沉默。
    is_owner = payload.get("is_owner") is not False
    trigger = str(payload.get("trigger") or "").strip() or "group"
    command = payload.get("command") is not False
    tool_call = payload.get("tool_call") is not False

    if not settings["human_enabled"]:
        return "reply", "拟人行为未启用"
    if is_owner:
        if settings["split_enabled"] and len(str(payload.get("text") or "")) >= 16 and rng() < settings["split_probability"]:
            return "split", "主人/管理员优先，分段但不拖延"
        if settings["delay_enabled"] and rng() < settings["delay_probability"]:
            return "delay", "主人/管理员优先，短暂停顿"
        return "reply", "主人/管理员优先，正常回复"

    can_silence = (
        settings["silence_enabled"]
        and not command
        and not tool_call
        and trigger in ("private", "at")
        and silence_count < settings["silence_daily_limit"]
        and not last_silence
    )
    mood_value = str(state.get("mood") or "calm")
    # 精力/社交一律用节律叠加后的有效值；缺省回落到原始状态。
    effective = effective if isinstance(effective, dict) else {}
    energy = float(effective.get("energy", state.get("energy") or 0))
    social = float(effective.get("social", state.get("social") or 0))
    low_energy = energy < 45
    low_social = social < 35
    # 用户明确道歉/安慰时不能沉默：这句要先被心情评估，否则“哄好”永远送不进来。
    soothing = any(w in str(payload.get("text") or "") for w in mood.APOLOGY_WORDS)
    if soothing and (
        mood_value in ("annoyed", "angry")
        or float((relation or {}).get("anger") or 0) >= 40
    ):
        can_silence = False
    silence_prob = settings["silence_probability"]
    if mood_value in _NEGATIVE_MOODS or low_energy or low_social:
        silence_prob = min(0.3, silence_prob * 1.6)
    if can_silence and rng() < silence_prob:
        reason = "影子模式：本来会沉默" if settings["shadow"] else "心情/社交电量低，这次不回"
        return "silence", reason

    short_prob = settings["short_probability"]
    if low_energy or low_social or mood_value in _NEGATIVE_MOODS:
        short_prob = min(0.5, short_prob * 2)
    if rng() < short_prob:
        return "short", "心情一般，回复短一点"

    familiarity = float((relation or {}).get("familiarity") or 0)
    if settings["split_enabled"] and len(str(payload.get("text") or "")) >= 16 and rng() < settings["split_probability"]:
        return "split", "关系熟，分两段回复" if familiarity >= 30 else "分两段说，别一次说完"
    if settings["delay_enabled"] and rng() < settings["delay_probability"]:
        return "delay", "不急着回，稍微等一下"
    return action, reason


def _delays(action: str, settings: dict, is_owner: bool, rng) -> list[int]:
    cap = min(int(settings["max_delay_ms"]), 3000 if is_owner else 4000)
    if action == "delay":
        return [int(600 + rng() * max(0, cap - 600))] if cap > 600 else [0]
    if action == "split":
        count = max(0, int(settings["max_chunks"]) - 1)
        if not count:
            return []
        per = cap // count if cap > 0 else 0
        if per <= 0:
            return [0] * count
        # 每段至少 1ms 且不超过均摊额度，保证 sum(delays_ms) <= cap。
        return [min(per, max(1, int(rng() * (per + 1)))) for _ in range(count)]
    return []


def plan(payload: dict, instances=None, db_path=None, rng=None) -> dict:
    if not isinstance(payload, dict):
        raise HumanError("行为计划参数必须是对象")
    inst = mood.resolve_instance(payload, instances)
    instance_id = str(inst.get("id") or "")
    settings = _cfg(instance_id, db_path=db_path)
    state = mood.get_state(instance_id, db_path=db_path)
    person_key = str(payload.get("person_key") or "")
    platform = str(payload.get("platform") or "qq")
    relation = mood.get_relation(instance_id, platform, person_key, db_path=db_path)
    rng = rng or random.random
    since = mood.day_start(settings["reset_hour"])
    is_owner = payload.get("is_owner") is not False
    # 节律是只读状态；读失败时回落到原始心情，绝不阻断行为计划。
    from . import rhythm as rhythm_mod
    try:
        rhythm_state = rhythm_mod.current(instance_id, db_path=db_path)
        effective = rhythm_mod.effective(state, rhythm_state)
    except Exception:  # noqa: BLE001
        rhythm_state = {}
        effective = {
            "energy": round(float(state.get("energy") or 0), 1),
            "social": round(float(state.get("social") or 0), 1),
        }
    with fleet_store.session(db_path) as conn:
        # 先拿写锁再查日限：日限查询与本次事件插入必须在同一个写事务里，
        # 否则两个并发 plan 会同时读到旧计数、各自判定未超限，突破每日沉默上限。
        conn.execute("BEGIN IMMEDIATE")
        silence_count, last_silence = _real_silence_stats(conn, instance_id, since)
        action, reason = _choose_action(settings, state, relation, payload,
                                        silence_count, last_silence, rng,
                                        effective=effective)
        delays = _delays(action, settings, is_owner, rng)
        # 每条决策都落库：沉默“不能连续”需要看到中间的正常回复，
        # 页面只展示非 reply 的事件，统计仍能区分影子与真实。
        text_hash = hashlib.sha256(str(payload.get("text") or "").encode("utf-8")).hexdigest()
        _log_event(conn, instance_id, str(payload.get("thread_key") or ""), action,
                   reason, settings["shadow"], text_hash, time.time())
    return {
        "instance_id": instance_id,
        "action": action,
        "chunks": [],
        "delays_ms": delays,
        "reason": reason,
        "shadow": bool(settings["shadow"]),
        "max_chunks": int(settings["max_chunks"]),
        "chunk_max_chars": int(settings["chunk_max_chars"]),
        "max_delay_ms": min(int(settings["max_delay_ms"]), 3000 if is_owner else 4000),
        "style_block": style_block(instance_id, person_key, is_owner, db_path),
        "behavior_hint": behavior_hint(action, is_owner),
        "effective": effective,
        "rhythm": {
            key: rhythm_state.get(key)
            for key in ("phase", "label", "energy_mod", "social_mod", "auto_mod")
        } if rhythm_state else {},
        "mood": {k: state.get(k) for k in ("mood", "intensity", "energy", "social")},
        "relationship": {
            "anger": (relation or {}).get("anger", 0),
            "affection": (relation or {}).get("affection", 0),
            "familiarity": (relation or {}).get("familiarity", 0),
        },
    }


def status(instance_id: str, db_path=None) -> dict:
    settings = _cfg(instance_id, db_path=db_path)
    state = mood.get_state(instance_id, db_path=db_path)
    since = mood.day_start(settings["reset_hour"])
    with fleet_store.session(db_path) as conn:
        counts = {}
        for row in conn.execute(
            "SELECT action, shadow, count(*) FROM human_behavior_events "
            "WHERE instance_id=? AND created>=? GROUP BY action, shadow",
            (instance_id, since),
        ).fetchall():
            key = ("shadow_" if int(row[1] or 0) else "") + str(row[0])
            counts[key] = int(row[2])
        events = [dict(row) for row in conn.execute(
            "SELECT * FROM human_behavior_events WHERE instance_id=? AND created>=? "
            "AND action<>'reply' ORDER BY created DESC LIMIT 100",
            (instance_id, since),
        ).fetchall()]
        last = conn.execute(
            "SELECT created FROM human_behavior_events WHERE instance_id=? ORDER BY created DESC LIMIT 1",
            (instance_id,),
        ).fetchone()
    last_at = float(last["created"]) if last else 0
    return {
        "settings": settings,
        "state": state,
        "events": events,
        "counts": counts,
        "last_plan_at": last_at,
        "plugin_active": bool(last_at and time.time() - last_at < 600),
        "style_count": len([x for x in styles.list_styles(instance_id, db_path=db_path) if x.get("enabled")]),
        "owner_note": "主人/管理员永不沉默",
    }


def save_settings(payload: dict, db_path=None) -> dict:
    if not isinstance(payload, dict):
        raise HumanError("设置必须是对象")
    instance_id = str(payload.get("instance_id") or "").strip()
    if not instance_id:
        raise HumanError("instance_id 不能为空")
    patch = {k: v for k, v in payload.items() if k != "instance_id"}
    try:
        return human_settings.save_settings(instance_id, patch, db_path=db_path)
    except human_settings.SettingsError as exc:
        raise HumanError(str(exc)) from None
