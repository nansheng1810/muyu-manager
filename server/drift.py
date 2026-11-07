"""只读的实例一致性巡检：插件、模型与人格在舰队内是否漂移。"""

from __future__ import annotations

import hashlib
import time

from . import backup as backup_mod, dashboard, store

MAX_ISSUES = 200


def _list_data(payload) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        for key in ("items", "list", "plugins", "providers", "personas"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def snapshot(inst: dict, call=dashboard.call) -> dict:
    item = {
        "id": str(inst.get("id") or inst.get("name") or ""),
        "name": str(inst.get("name") or inst.get("id") or ""),
        "reachable": False,
        "errors": {},
        "plugins": {},
        "providers": {},
        "personas": {},
    }
    try:
        plugins = _list_data(call(inst, "GET", "plugins", timeout=12))
        item["plugins"] = {
            str(row.get("id") or row.get("name")): {
                "name": str(row.get("display_name") or row.get("name") or row.get("id") or ""),
                "version": str(row.get("version") or ""),
                "enabled": bool(row.get("enabled", row.get("activated", True))),
            }
            for row in plugins
            if row.get("id") or row.get("name")
        }
        item["reachable"] = True
    except Exception as exc:  # noqa: BLE001
        item["errors"]["plugins"] = str(exc)[:240]

    try:
        providers = _list_data(call(inst, "GET", "providers", timeout=12))
        item["providers"] = {
            str(row.get("id")): {
                "model": str(row.get("model") or ""),
                "type": str(row.get("provider_type") or row.get("type") or ""),
                "enabled": bool(row.get("enable", True)),
            }
            for row in providers
            if row.get("id")
        }
        item["reachable"] = True
    except Exception as exc:  # noqa: BLE001
        item["errors"]["providers"] = str(exc)[:240]

    try:
        personas = _list_data(call(inst, "GET", "personas", timeout=12))
        item["personas"] = {
            str(row.get("persona_id") or row.get("id")): {
                "chars": len(str(row.get("system_prompt") or "")),
                "hash": _prompt_hash(row.get("system_prompt") or ""),
            }
            for row in personas
            if row.get("persona_id") or row.get("id")
        }
        item["reachable"] = True
    except Exception as exc:  # noqa: BLE001
        item["errors"]["personas"] = str(exc)[:240]
    return item


def _issue(kind: str, key: str, reference: dict, snapshots: list[dict], message: str) -> dict:
    values = {}
    for snap in snapshots:
        row = (snap.get(kind) or {}).get(key)
        values[snap["id"]] = row
    return {
        "kind": kind,
        "key": key,
        "severity": "warn",
        "message": message,
        "reference": snapshots[0]["id"] if snapshots else "",
        "reference_value": reference,
        "values": values,
    }


def compare(snapshots: list[dict]) -> dict:
    reachable = [snap for snap in snapshots if snap.get("reachable")]
    issues: list[dict] = []
    reference = reachable[0] if reachable else None
    if reference:
        others = reachable[1:]
        for kind, label, field in (
            ("plugins", "插件", "version"),
            ("providers", "模型", "model"),
            ("personas", "人格", "hash"),
        ):
            keys = sorted(set(reference.get(kind) or {}))
            for snap in others:
                keys.extend(key for key in (snap.get(kind) or {}) if key not in keys)
            for key in keys:
                ref_value = (reference.get(kind) or {}).get(key)
                for snap in others:
                    value = (snap.get(kind) or {}).get(key)
                    if ref_value is None:
                        issues.append(_issue(kind, key, value or {}, [snap, reference],
                                             f"{snap['name']} 多出{label}「{key}」，参考实例没有"))
                    elif value is None:
                        issues.append(_issue(kind, key, ref_value, [reference, snap],
                                             f"{snap['name']} 缺少{label}「{key}」"))
                    elif ref_value.get(field) != value.get(field):
                        issues.append(_issue(
                            kind, key, ref_value, [reference, snap],
                            f"{label}「{key}」的 {field} 不一致：{ref_value.get(field) or '—'} / {value.get(field) or '—'}",
                        ))
                    elif ref_value.get("enabled") != value.get("enabled"):
                        issues.append(_issue(
                            kind, key, ref_value, [reference, snap],
                            f"{label}「{key}」启用状态不一致",
                        ))
                    if len(issues) >= MAX_ISSUES:
                        break
                if len(issues) >= MAX_ISSUES:
                    break
            if len(issues) >= MAX_ISSUES:
                break
    counts = {"warn": len(issues)}
    return {
        "generated_at": time.time(),
        "reference": reference["id"] if reference else "",
        "instances": snapshots,
        "issues": issues,
        "counts": {**counts, "total": len(issues), "reachable": len(reachable), "instances": len(snapshots)},
        "overall": "warn" if issues else ("ok" if len(reachable) == len(snapshots) and reachable else "bad"),
    }


def collect(instances: list[dict] | None = None, call=dashboard.call) -> dict:
    items = list(instances if instances is not None else store.load_instances())
    snapshots = [snapshot(inst, call) for inst in items]
    return compare(snapshots)


def _persona_prompt(inst: dict, persona_id: str, call) -> str:
    detail = call(inst, "GET", "personas/by-id", query={"persona_id": persona_id}, timeout=20)
    data = detail.get("data") if isinstance(detail, dict) else {}
    persona = (data or {}).get("persona") if isinstance(data, dict) else {}
    prompt = (persona or {}).get("system_prompt") if isinstance(persona, dict) else ""
    if not prompt and isinstance(data, dict):
        prompt = data.get("system_prompt")
    if not str(prompt or "").strip():
        raise ValueError(f"参考实例的人格 {persona_id} 没有正文")
    return str(prompt)


def align(reference_id: str, target_ids: list[str] | None = None,
          kinds: list[str] | None = None, confirm: str = "",
          instances: list[dict] | None = None, call=dashboard.call,
          backup_func=backup_mod.create) -> dict:
    """备份后对齐插件启停与人格正文；不处理版本/密钥/模型配置。"""
    if str(confirm or "").upper() != "ALIGN":
        raise ValueError("对齐需要 confirm=ALIGN")
    selected = set(kinds or ["plugins", "personas"])
    selected &= {"plugins", "personas"}
    if not selected:
        raise ValueError("kinds 至少包含 plugins 或 personas")
    insts = list(instances if instances is not None else store.load_instances())
    by_id = {str(inst.get("id")): inst for inst in insts}
    reference = by_id.get(str(reference_id))
    if not reference:
        raise ValueError("参考实例不存在")
    targets = [by_id[item] for item in (target_ids or []) if item in by_id and item != reference_id]
    if not targets:
        targets = [inst for inst in insts if str(inst.get("id")) != str(reference_id)]
    data = collect(insts, call=call)
    reference_snap = next((snap for snap in data["instances"] if snap["id"] == reference_id), None)
    target_snaps = {snap["id"]: snap for snap in data["instances"] if snap["id"] in {str(i.get("id")) for i in targets}}
    if not reference_snap or not reference_snap.get("reachable"):
        raise ValueError("参考实例不可达")
    issues = [issue for issue in (data.get("issues") or []) if issue.get("kind") in selected]
    if not issues:
        return {
            "ok": True, "reference": reference_id,
            "targets": [str(inst.get("id")) for inst in targets],
            "actions": [], "skipped": [], "backup": None,
        }
    # 先备份再写入；备份失败时绝不继续。
    try:
        backup = backup_func(["manager", "instances"], include_login=False,
                             label="pre-align", instances=insts)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"对齐前备份失败，已停止：{exc}") from exc
    actions = []
    skipped = []
    for issue in issues:
        key = issue["key"]
        if issue["kind"] == "plugins":
            ref_value = (reference_snap.get("plugins") or {}).get(key)
            if not ref_value:
                skipped.append({"key": key, "reason": "参考实例没有该插件"})
                continue
            if not ref_value.get("version"):
                skipped.append({"key": key, "reason": "参考插件没有版本信息"})
                continue
            for target in targets:
                target_id = str(target.get("id"))
                current = (target_snaps.get(target_id, {}).get("plugins") or {}).get(key)
                if not current:
                    skipped.append({"target": target_id, "key": key, "reason": "目标未安装，不能自动安装"})
                    continue
                if current.get("version") != ref_value.get("version"):
                    skipped.append({"target": target_id, "key": key, "reason": "版本不同，不自动降级/升级"})
                    continue
                if bool(current.get("enabled")) == bool(ref_value.get("enabled")):
                    continue
                try:
                    call(target, "PATCH", "plugins/enabled",
                         {"plugin_id": key, "enabled": bool(ref_value.get("enabled"))}, timeout=20)
                    actions.append({"target": target_id, "kind": "plugin", "key": key,
                                    "enabled": bool(ref_value.get("enabled"))})
                except Exception as exc:  # noqa: BLE001
                    skipped.append({"target": target_id, "key": key, "reason": str(exc)[:200]})
        elif issue["kind"] == "personas":
            ref_value = (reference_snap.get("personas") or {}).get(key)
            if not ref_value:
                skipped.append({"key": key, "reason": "参考实例没有该人格"})
                continue
            for target in targets:
                target_id = str(target.get("id"))
                current = (target_snaps.get(target_id, {}).get("personas") or {}).get(key)
                if current and current.get("hash") == ref_value.get("hash"):
                    continue
                if key == "default":
                    skipped.append({"target": target_id, "key": key, "reason": "跳过通用 default 人格"})
                    continue
                try:
                    prompt = _persona_prompt(reference, key, call)
                    if current is None:
                        call(target, "POST", "personas",
                             {"persona_id": key, "system_prompt": prompt, "begin_dialogs": []}, timeout=30)
                        actions.append({"target": target_id, "kind": "persona", "key": key, "action": "create"})
                    else:
                        call(target, "PUT", "personas/by-id",
                             {"persona_id": key, "system_prompt": prompt}, timeout=30)
                        actions.append({"target": target_id, "kind": "persona", "key": key, "action": "update"})
                except Exception as exc:  # noqa: BLE001
                    skipped.append({"target": target_id, "key": key, "reason": str(exc)[:200]})
    return {
        "ok": not skipped,
        "reference": reference_id,
        "targets": [str(inst.get("id")) for inst in targets],
        "actions": actions,
        "skipped": skipped,
        "backup": backup,
    }
