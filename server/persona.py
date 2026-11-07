"""人格工作台：版本快照、文件导入、结构大纲与自动学习块保护。"""

from __future__ import annotations

import difflib
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import dashboard, store

VERSIONS_DIR = store.DATA_DIR / "persona_versions"
CANDIDATES_PATH = store.DATA_DIR / "persona_candidates.json"
MAX_VERSIONS = 30
MAX_PREVIEW = 90

AUTO_BEGIN = "<!-- AUTO-LEARN:BEGIN -->"
AUTO_END = "<!-- AUTO-LEARN:END -->"
_AUTO_BLOCK_RE = re.compile(re.escape(AUTO_BEGIN) + r".*?" + re.escape(AUTO_END), re.S)

_SECTION_RE = re.compile(r"^\s*(#{1,3}\s*(?P<md>.+?)|【(?P<bracket>[^】]{1,40})】)\s*$")


class PersonaError(Exception):
    pass


def _dir(inst: dict, persona_id: str) -> Path:
    safe = re.sub(r'[\\/:*?"<>|]+', "_", str(persona_id or "default")).strip() or "default"
    return VERSIONS_DIR / str(inst.get("id") or "inst") / safe


def _write_version(inst: dict, persona_id: str, prompt: str, label: str) -> dict:
    directory = _dir(inst, persona_id)
    directory.mkdir(parents=True, exist_ok=True)
    ts = time.time()
    path = directory / f"{int(ts * 1000):013d}.md"
    header = f"<!-- label: {label} | time: {datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')} -->\n"
    path.write_text(header + (prompt or ""), encoding="utf-8")
    _prune(directory)
    return {"ts": int(ts), "path": str(path)}


def _prune(directory: Path) -> None:
    try:
        files = sorted(directory.glob("*.md"))
        for path in files[:-MAX_VERSIONS] if len(files) > MAX_VERSIONS else []:
            path.unlink(missing_ok=True)
    except Exception:
        pass


def current_prompt(inst: dict, persona_id: str) -> str:
    detail = dashboard.call(
        inst, "GET", "personas/by-id", query={"persona_id": persona_id}, timeout=20
    )
    data = detail.get("data") or {}
    persona = data.get("persona") if isinstance(data.get("persona"), dict) else data
    return str(persona.get("system_prompt") or "")


def list_personas(inst: dict) -> list[dict]:
    try:
        data = dashboard.call(inst, "GET", "personas", timeout=20)
    except dashboard.DashboardError:
        return []
    items = data.get("data") or {}
    if isinstance(items, dict):
        items = items.get("personas") or []
    return [
        {"persona_id": str(p.get("persona_id")), "chars": len(str(p.get("system_prompt") or ""))}
        for p in items
        if isinstance(p, dict) and p.get("persona_id")
    ]


def snapshot(inst: dict, persona_id: str, prompt: str, label: str = "手动快照") -> dict:
    """保存一份带时间戳的人格快照，供工作台恢复。"""
    return _write_version(inst, persona_id, prompt, label)


def choose_persona_id(
    inst: dict,
    personas: list[dict],
    configured: str = "",
    allow_default: bool = False,
) -> str:
    """选出要写学习笔记的人格：显式配置 > 实例同名 > 第一个非 default。

    allow_default=False 时绝不回退到 default，避免自动学习把笔记写进通用人格。
    """
    ids = [
        str(item.get("persona_id"))
        for item in personas
        if isinstance(item, dict) and item.get("persona_id")
    ]
    chosen = str(configured or "").strip()
    if chosen in ids:
        return chosen
    inst_name = str(inst.get("name") or "").strip()
    if inst_name in ids:
        return inst_name
    for persona_id in ids:
        if persona_id != "default":
            return persona_id
    return ids[0] if allow_default and ids else ""


def default_persona_id(inst: dict) -> str:
    """工作台展示用：允许回退到 default。"""
    return choose_persona_id(inst, list_personas(inst), allow_default=True)


def list_versions(inst: dict, persona_id: str) -> list[dict]:
    directory = _dir(inst, persona_id)
    out: list[dict] = []
    try:
        for path in sorted(directory.glob("*.md"), reverse=True):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            body = text.split("-->\n", 1)[-1]
            first_line = next(
                (line.strip() for line in body.splitlines() if line.strip()), ""
            )
            out.append(
                {
                    "ts": int(path.stem),
                    "time": datetime.fromtimestamp(int(path.stem) / 1000).strftime(
                        "%m-%d %H:%M"
                    ),
                    "chars": len(body.strip()),
                    "preview": first_line[:MAX_PREVIEW],
                }
            )
    except Exception:
        pass
    return out


def get_version(inst: dict, persona_id: str, ts_ms: int) -> str:
    path = _dir(inst, persona_id) / f"{int(ts_ms):013d}.md"
    if not path.exists():
        raise PersonaError("找不到该版本快照")
    text = path.read_text(encoding="utf-8")
    return text.split("-->\n", 1)[-1]


def extract_auto_blocks(prompt: str) -> list[str]:
    """返回人格里所有 AUTO-LEARN 块，避免迁移时只取第一块丢数据。"""
    return _AUTO_BLOCK_RE.findall(str(prompt or ""))


def extract_auto_block(prompt: str) -> str:
    blocks = extract_auto_blocks(prompt)
    return blocks[0] if blocks else ""


def strip_auto_block(prompt: str) -> str:
    return _AUTO_BLOCK_RE.sub("", str(prompt or "")).strip()


def auto_learn_state(prompt: str) -> dict:
    block = extract_auto_block(prompt)
    return {"present": bool(block), "chars": len(block)}


def outline(prompt: str) -> list[dict]:
    """解析人格结构：【章节】或 Markdown 标题，返回各小节的字数。"""
    sections: list[dict] = []
    current: dict | None = None
    base_chars = 0
    for line in str(prompt or "").splitlines(keepends=True):
        match = _SECTION_RE.match(line)
        if match:
            title = (match.group("md") or match.group("bracket") or "").strip()
            title = re.sub(r"^#{1,3}\s*", "", title).strip()
            if current:
                current["chars"] = base_chars - current["_start"]
                del current["_start"]
                sections.append(current)
            current = {"title": title[:40], "_start": 0, "chars": 0}
            current["_start"] = base_chars + len(line)
        base_chars += len(line)
    if current:
        current["chars"] = max(0, base_chars - current["_start"])
        del current["_start"]
        sections.append(current)
    return sections


def _save_remote(inst: dict, persona_id: str, prompt: str) -> None:
    dashboard.call(
        inst,
        "PUT",
        "personas/by-id",
        {"persona_id": persona_id, "system_prompt": prompt},
        timeout=60,
    )


def save(inst: dict, persona_id: str, prompt: str, label: str = "手动保存") -> dict:
    prompt = str(prompt or "").replace(AUTO_BEGIN, "").replace(AUTO_END, "").strip()
    old = current_prompt(inst, persona_id)
    kept = extract_auto_block(old)
    if kept:
        prompt = (prompt + "\n\n" + kept) if prompt else kept
    snapshot(inst, persona_id, old, "保存前自动快照")
    _save_remote(inst, persona_id, prompt)
    return {
        "chars": len(prompt),
        "auto_learn_kept": bool(kept),
        "outline": outline(prompt),
    }


def clear_auto_block(inst: dict, persona_id: str) -> dict:
    """删除人格里的自动学习块；先快照，失败则不写。"""
    old = current_prompt(inst, persona_id)
    if not extract_auto_block(old):
        return {"removed": False, "chars": len(old)}
    snapshot(inst, persona_id, old, "清除自动学习块前快照")
    prompt = strip_auto_block(old)
    _save_remote(inst, persona_id, prompt)
    return {"removed": True, "chars": len(prompt)}


def import_text(inst: dict, persona_id: str, text: str, preserve_auto: bool = True) -> dict:
    text = str(text or "").strip()
    if not text:
        raise PersonaError("导入的内容为空")
    old = current_prompt(inst, persona_id)
    snapshot(inst, persona_id, old, "导入前自动快照")
    kept = extract_auto_block(old) if preserve_auto else ""
    prompt = text
    if kept:
        prompt = prompt.rstrip() + "\n\n" + kept
    _save_remote(inst, persona_id, prompt)
    return {
        "chars": len(prompt),
        "auto_learn_kept": bool(kept),
        "outline": outline(prompt),
    }


def restore(inst: dict, persona_id: str, ts_ms: int) -> dict:
    # 历史版本里的自动学习块一律丢弃（往往是过时甚至失败的笔记）；
    # 只保留当前线上正在生效的那一块。
    prompt = strip_auto_block(get_version(inst, persona_id, ts_ms))
    if not prompt:
        raise PersonaError("该版本内容为空")
    old = current_prompt(inst, persona_id)
    snapshot(inst, persona_id, old, "恢复前自动快照")
    kept = extract_auto_block(old)
    if kept:
        prompt = prompt.rstrip() + "\n\n" + kept
    _save_remote(inst, persona_id, prompt)
    return {
        "chars": len(prompt),
        "auto_learn_kept": bool(kept),
        "outline": outline(prompt),
    }


# ------------------------------------------------------- persona 灰度/候选


def persona_prompts(inst: dict) -> list[dict]:
    """返回人格列表和完整提示词，供轨迹页匹配本轮注入的人格。"""
    try:
        data = dashboard.call(inst, "GET", "personas", timeout=20)
    except dashboard.DashboardError:
        return []
    items = data.get("data") or {}
    if isinstance(items, dict):
        items = items.get("personas") or []
    out: list[dict] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("persona_id"):
            continue
        prompt = str(item.get("system_prompt") or "")
        out.append(
            {
                "persona_id": str(item.get("persona_id")),
                "prompt": prompt,
                "chars": len(prompt),
            }
        )
    return out


def diff_texts(old_text: str, new_text: str) -> dict:
    """逐行 diff，给前端染色展示。"""
    old_lines = str(old_text or "").splitlines()
    new_lines = str(new_text or "").splitlines()
    entries = []
    added = removed = 0
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=1):
        if not line or line.startswith(("---", "+++", "@@")):
            continue
        prefix, body = line[0], line[1:]
        if prefix == "+":
            entries.append({"type": "add", "text": body})
            added += 1
        elif prefix == "-":
            entries.append({"type": "del", "text": body})
            removed += 1
        elif prefix == " ":
            entries.append({"type": "same", "text": body})
    return {
        "lines": entries,
        "added": added,
        "removed": removed,
        "old_chars": len(str(old_text or "")),
        "new_chars": len(str(new_text or "")),
    }


def version_diff(inst: dict, persona_id: str, ts_a: int, ts_b: int) -> dict:
    """0 表示当前线上版本，其它值为版本快照时间戳。"""
    a = get_version(inst, persona_id, int(ts_a)) if int(ts_a) else current_prompt(inst, persona_id)
    b = get_version(inst, persona_id, int(ts_b)) if int(ts_b) else current_prompt(inst, persona_id)
    return {
        "persona_id": persona_id,
        "a": int(ts_a),
        "b": int(ts_b),
        "diff": diff_texts(a, b),
    }


def apply_prompt(inst: dict, persona_id: str, prompt: str, label: str) -> dict:
    """把候选人格写到线上；先自动快照，返回回滚用的时间戳。"""
    prompt = str(prompt or "").replace(AUTO_BEGIN, "").replace(AUTO_END, "").strip()
    if not prompt:
        raise PersonaError("候选人格内容为空")
    old = current_prompt(inst, persona_id)
    kept = extract_auto_block(old)
    if kept:
        prompt = prompt.rstrip() + "\n\n" + kept
    snap = snapshot(inst, persona_id, old, f"{label}前自动快照")
    _save_remote(inst, persona_id, prompt)
    return {"chars": len(prompt), "snapshot_ts": snap["ts"], "auto_learn_kept": bool(kept)}


def _candidate_items() -> list[dict]:
    try:
        data = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def _write_candidates(items: list[dict]) -> None:
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CANDIDATES_PATH.with_name(CANDIDATES_PATH.name + ".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    tmp.replace(CANDIDATES_PATH)


def _candidate_public(item: dict) -> dict:
    return dict(item)


def list_candidates(persona_id: str = "") -> list[dict]:
    items = _candidate_items()
    if persona_id:
        items = [item for item in items if item.get("persona_id") == persona_id]
    return [_candidate_public(item) for item in items if isinstance(item, dict)]


def get_candidate(candidate_id: str) -> dict:
    for item in _candidate_items():
        if isinstance(item, dict) and item.get("id") == candidate_id:
            return item
    raise PersonaError("候选人格不存在")


def create_candidate(inst: dict, payload: dict) -> dict:
    persona_id = str(payload.get("persona_id") or "").strip()
    if not persona_id:
        personas = list_personas(inst)
        persona_id = str(personas[0].get("persona_id")) if personas else ""
    if not persona_id:
        raise PersonaError("请选择要对比的人格")
    prompt = str(payload.get("prompt") or "").strip()
    ts = int(payload.get("from_version") or 0)
    if not prompt and ts:
        prompt = get_version(inst, persona_id, ts)
    if not prompt:
        prompt = current_prompt(inst, persona_id)
    prompt = strip_auto_block(prompt)
    if not prompt:
        raise PersonaError("候选人格内容为空")
    now = time.time()
    item = {
        "id": uuid.uuid4().hex[:10],
        "name": str(payload.get("name") or "").strip()
        or f"候选人格 {datetime.fromtimestamp(now).strftime('%m-%d %H:%M')}",
        "persona_id": persona_id,
        "inst_id": str(inst.get("id") or ""),
        "inst_name": str(inst.get("name") or ""),
        "source": str(payload.get("source") or "copy"),
        "note": str(payload.get("note") or "")[:300],
        "prompt": prompt,
        "chars": len(prompt),
        "created": now,
        "updated": now,
        "status": "draft",
        "eval": None,
        "ab": None,
        "gray": None,
        "rollout": None,
    }
    items = _candidate_items()
    items.insert(0, item)
    _write_candidates(items[:60])
    return item


def update_candidate(candidate_id: str, payload: dict) -> dict:
    items = _candidate_items()
    target = None
    for item in items:
        if item.get("id") != candidate_id:
            continue
        target = item
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if name:
                item["name"] = name[:80]
        if "note" in payload:
            item["note"] = str(payload.get("note") or "")[:300]
        if "prompt" in payload:
            prompt = strip_auto_block(str(payload.get("prompt") or "")).strip()
            if not prompt:
                raise PersonaError("候选人格内容不能为空")
            item["prompt"] = prompt
            item["chars"] = len(prompt)
        item["updated"] = time.time()
        break
    if target is None:
        raise PersonaError("候选人格不存在")
    _write_candidates(items)
    return target


def delete_candidate(candidate_id: str) -> bool:
    items = _candidate_items()
    kept = [item for item in items if item.get("id") != candidate_id]
    if len(kept) == len(items):
        return False
    _write_candidates(kept)
    return True


def _candidate_prompt(inst: dict, candidate: dict) -> str:
    """候选内容 + 当前线上自动学习块，等价于上线后的实际提示词。"""
    prompt = str(candidate.get("prompt") or "").strip()
    kept = extract_auto_block(current_prompt(inst, str(candidate.get("persona_id") or "")))
    if kept:
        prompt = (prompt + "\n\n" + kept).strip() if prompt else kept
    return prompt


def _record_candidate(candidate_id: str, patch: dict) -> dict:
    items = _candidate_items()
    target = None
    for item in items:
        if item.get("id") == candidate_id:
            item.update(patch)
            item["updated"] = time.time()
            target = item
            break
    if target is None:
        raise PersonaError("候选人格不存在")
    _write_candidates(items)
    return target


def shadow_run(
    inst: dict,
    candidate_id: str,
    provider_id: str,
    fixture_ids: list[str] | None = None,
) -> dict:
    """候选人格影子跑分：只在评测里用候选提示词，不写线上。"""
    from . import eval as eval_mod

    candidate = get_candidate(candidate_id)
    persona_id = str(candidate.get("persona_id") or "")
    prompt = _candidate_prompt(inst, candidate)
    if not prompt:
        raise PersonaError("候选人格内容为空")
    batch = eval_mod.run(
        inst,
        provider_id,
        persona_id=f"candidate:{candidate_id}",
        fixture_ids=fixture_ids,
        system_prompt=prompt,
    )
    summary = {
        "batch": batch.get("batch"),
        "average": batch.get("average"),
        "passed": batch.get("passed"),
        "total": batch.get("total"),
        "model": provider_id,
        "at": time.time(),
        "results": [
            {
                "fixture": item.get("fixture"),
                "title": item.get("title"),
                "status": item.get("status"),
                "score": (item.get("score") or {}).get("score"),
                "reply": item.get("reply"),
            }
            for item in batch.get("results") or []
        ],
    }
    _record_candidate(candidate_id, {"eval": summary, "status": "scored"})
    return summary


def ab_run(
    inst: dict,
    candidate_id: str,
    provider_id: str,
    fixture_ids: list[str] | None = None,
) -> dict:
    """线上人格 vs 候选人格，同一模型同一批用例各跑一遍。"""
    from . import eval as eval_mod

    candidate = get_candidate(candidate_id)
    persona_id = str(candidate.get("persona_id") or "")
    base_prompt = current_prompt(inst, persona_id)
    cand_prompt = _candidate_prompt(inst, candidate)
    if not cand_prompt:
        raise PersonaError("候选人格内容为空")
    base = eval_mod.run(
        inst,
        provider_id,
        persona_id=persona_id,
        fixture_ids=fixture_ids,
        system_prompt=base_prompt,
    )
    cand = eval_mod.run(
        inst,
        provider_id,
        persona_id=f"candidate:{candidate_id}",
        fixture_ids=fixture_ids,
        system_prompt=cand_prompt,
    )
    base_items = {item.get("fixture"): item for item in base.get("results") or []}
    cand_items = {item.get("fixture"): item for item in cand.get("results") or []}
    fixtures = []
    for key in sorted(set(base_items) | set(cand_items), key=lambda item: str(item)):
        left = base_items.get(key) or {}
        right = cand_items.get(key) or {}
        left_score = int((left.get("score") or {}).get("score") or 0)
        right_score = int((right.get("score") or {}).get("score") or 0)
        fixtures.append(
            {
                "fixture": key,
                "title": left.get("title") or right.get("title") or key,
                "base": left_score,
                "candidate": right_score,
                "delta": right_score - left_score,
                "candidate_reply": right.get("reply") or "",
            }
        )
    delta = int(cand.get("average") or 0) - int(base.get("average") or 0)
    result = {
        "model": provider_id,
        "at": time.time(),
        "base": {
            "batch": base.get("batch"),
            "average": base.get("average"),
            "passed": base.get("passed"),
            "total": base.get("total"),
        },
        "candidate": {
            "batch": cand.get("batch"),
            "average": cand.get("average"),
            "passed": cand.get("passed"),
            "total": cand.get("total"),
        },
        "delta": delta,
        "winner": "candidate" if delta > 0 else "base" if delta < 0 else "tie",
        "fixtures": fixtures,
    }
    _record_candidate(candidate_id, {"ab": result})
    return result


def deploy_candidate(
    inst: dict,
    candidate_id: str,
    instances: list[dict],
    target_ids: list[str] | None = None,
    mode: str = "gray",
) -> dict:
    """灰度只写指定实例；全量写所有存在该人格的本地实例。"""
    candidate = get_candidate(candidate_id)
    persona_id = str(candidate.get("persona_id") or "")
    prompt = _candidate_prompt(inst, candidate)
    if not prompt:
        raise PersonaError("候选人格内容为空")
    mode = "full" if str(mode) == "full" else "gray"
    wanted = {str(item) for item in (target_ids or [])}
    by_id = {str(item.get("id")): item for item in instances if isinstance(item, dict)}
    targets: list[dict] = []
    failed: list[dict] = []
    if mode == "gray":
        chosen = [by_id[item] for item in wanted if item in by_id] or [inst]
        targets = chosen
    else:
        for item in instances:
            if not isinstance(item, dict) or not item.get("root"):
                continue
            try:
                ids = {p.get("persona_id") for p in list_personas(item)}
            except Exception:  # noqa: BLE001
                ids = set()
            if persona_id in ids:
                targets.append(item)
        if str(inst.get("id")) not in {str(item.get("id")) for item in targets}:
            targets.insert(0, inst)
    applied = []
    rollback: dict[str, int] = {}
    label = "灰度上线" if mode == "gray" else "全量上线"
    for item in targets:
        try:
            result = apply_prompt(
                item, persona_id, prompt, f"{label}「{candidate.get('name')}」"
            )
            applied.append(
                {
                    "inst_id": item.get("id"),
                    "inst_name": item.get("name") or item.get("id"),
                    "chars": result["chars"],
                    "snapshot_ts": result["snapshot_ts"],
                }
            )
            rollback[str(item.get("id"))] = result["snapshot_ts"]
        except Exception as exc:  # noqa: BLE001
            failed.append(
                {
                    "inst_id": item.get("id"),
                    "inst_name": item.get("name") or item.get("id"),
                    "error": str(exc)[:200],
                }
            )
    if not applied:
        raise PersonaError("没有任何实例上线成功：" + "；".join(i["error"] for i in failed))
    info = {"at": time.time(), "targets": applied, "rollback": rollback, "by": "manager"}
    if mode == "gray":
        patch = {"status": "gray", "gray": info}
    else:
        patch = {"status": "live", "rollout": info}
    _record_candidate(candidate_id, patch)
    return {"mode": mode, "applied": applied, "failed": failed, "candidate": get_candidate(candidate_id)}


def rollback_candidate(
    candidate_id: str, instances: list[dict], point: str = ""
) -> dict:
    """回滚到灰度/全量上线前的自动快照。"""
    candidate = get_candidate(candidate_id)
    by_id = {str(item.get("id")): item for item in instances if isinstance(item, dict)}
    sources = []
    for key in (point, "rollout", "gray"):
        if not key:
            continue
        info = candidate.get(key) or {}
        if isinstance(info, dict) and info.get("rollback"):
            sources.append((key, info))
    if not sources:
        raise PersonaError("该候选人格还没有上线记录，无法回滚")
    _, info = sources[0]
    persona_id = str(candidate.get("persona_id") or "")
    applied = []
    failed = []
    for inst_id, ts in (info.get("rollback") or {}).items():
        target = by_id.get(str(inst_id))
        if not target:
            failed.append({"inst_id": inst_id, "error": "实例已不存在"})
            continue
        try:
            restore(target, persona_id, int(ts))
            applied.append({"inst_id": inst_id, "inst_name": target.get("name") or inst_id, "ts": ts})
        except Exception as exc:  # noqa: BLE001
            failed.append({"inst_id": inst_id, "error": str(exc)[:200]})
    if not applied:
        raise PersonaError("回滚没有成功：" + "；".join(i["error"] for i in failed))
    _record_candidate(
        candidate_id,
        {"status": "rolled_back", "last_rollback": {"at": time.time(), "targets": applied}},
    )
    return {"applied": applied, "failed": failed, "candidate": get_candidate(candidate_id)}
