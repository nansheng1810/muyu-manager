"""图片表情包管理：直接维护 meme_manager 的包目录、选包规则与发送设置。"""

from __future__ import annotations

import json
import mimetypes
import random
import re
import shutil
import sqlite3
import time
from pathlib import Path

from . import dashboard

PLUGIN_ID = "meme_manager"
DEFAULT_PACK_ID = "custom-20261116"
DEFAULT_PACK_NAME = "牧鱼自选表情包"
DEFAULT_SOURCE = Path(r"D:\驰风车队项目\表情包")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
CATEGORY_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
CATEGORY_DESCRIPTIONS = {
    "cat": "猫猫表情：可爱、撒娇、无语或日常反应。",
    "funny": "沙雕搞笑：接梗、吐槽、夸张反应。",
    "whale": "鲸鱼表情：大肥鱼/小鲸鱼相关的可爱反应。",
    "dog": "狗狗表情：搞怪、疑惑、开心或装可怜。",
    "panda": "熊猫头：经典斗图、反问和阴阳怪气。",
    "fish": "摸鱼表情：上班、偷懒、吃饭和摆烂。",
    "rabbit": "兔子表情：软萌、害羞、开心或委屈。",
    "worker": "打工人表情：加班、疲惫、发疯和自嘲。",
    "other": "其他表情：未归类但有梗的图片。",
}


class ImageMemeError(ValueError):
    pass


def _root(inst: dict) -> Path:
    raw = str(inst.get("root") or "").strip()
    if not raw:
        raise ImageMemeError("实例没有本地目录")
    root = Path(raw)
    if not root.is_dir():
        raise ImageMemeError("实例目录不存在")
    return root


def _base(inst: dict, create: bool = False) -> Path:
    path = _root(inst) / "data" / "plugin_data" / PLUGIN_ID
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(path)


def _pack_id(value: str | None, default: str = DEFAULT_PACK_ID) -> str:
    text = str(value or "").strip()
    if not text:
        text = default
    if not PACK_ID_RE.fullmatch(text):
        raise ImageMemeError("表情包 ID 只能使用小写字母、数字、点、下划线和短横线")
    return text


def _safe_segment(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ImageMemeError(f"{label}不合法")
    return text


def _pack_dir(inst: dict, pack_id: str) -> Path:
    return _base(inst) / "packs" / pack_id


def _manifest(inst: dict, pack_id: str) -> dict:
    data = _read_json(_pack_dir(inst, pack_id) / "manifest.json", {})
    return data if isinstance(data, dict) else {}


def _registry(inst: dict) -> dict:
    data = _read_json(_base(inst) / "registry.json", {})
    if not isinstance(data, dict):
        data = {}
    packs = data.get("installed_packs")
    if not isinstance(packs, list):
        packs = []
    data["installed_packs"] = [item for item in packs if isinstance(item, dict)]
    data.setdefault("schema_version", 1)
    return data


def _rules(inst: dict) -> dict:
    data = _read_json(_base(inst) / "selection_rules.json", {})
    if not isinstance(data, dict):
        data = {}
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
    data["rules"] = [item for item in rules if isinstance(item, dict)]
    data.setdefault("schema_version", 1)
    return data


def _default_rule(inst: dict) -> dict | None:
    for item in _rules(inst)["rules"]:
        if str(item.get("scope") or "") == "default":
            return item
    return None


def _default_pack_id(inst: dict) -> str:
    rule = _default_rule(inst) or {}
    ids = rule.get("pack_ids")
    if isinstance(ids, list) and ids:
        return str(ids[0])
    return str(rule.get("pack_id") or "")


def _scan_images(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.rglob("*")
         if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda path: (path.parent.name, path.name.casefold()),
    )


def _image_files(pack_dir: Path, category: str = "") -> list[Path]:
    memes = pack_dir / "memes"
    if not memes.is_dir():
        return []
    base = memes / category if category else memes
    if not base.is_dir():
        return []
    return _scan_images(base)


def _category_counts(pack_dir: Path) -> dict[str, int]:
    memes = pack_dir / "memes"
    if not memes.is_dir():
        return {}
    counts = {}
    for child in memes.iterdir():
        if not child.is_dir():
            continue
        count = sum(
            1 for path in child.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
        if count:
            counts[child.name] = count
    return dict(sorted(counts.items()))


def _pack_view(inst: dict, pack_id: str, registry_item: dict | None = None) -> dict:
    pack_dir = _pack_dir(inst, pack_id)
    manifest = _manifest(inst, pack_id)
    item = registry_item or {}
    categories = _category_counts(pack_dir)
    active = pack_id == _default_pack_id(inst)
    return {
        "id": pack_id,
        "name": str(item.get("name") or manifest.get("name") or pack_id),
        "version": str(item.get("version") or manifest.get("version") or "0.0.0"),
        "enabled": bool(item.get("enabled", True)),
        "active": active,
        "is_default": active,
        "image_count": sum(categories.values()),
        "category_count": len(categories),
        "categories": categories,
        "description": str(manifest.get("description") or ""),
    }


def _plugin_reload(inst: dict) -> dict:
    try:
        result = dashboard.call(
            inst, "POST", f"plugins/{PLUGIN_ID}/reload", timeout=120
        )
        return {"ok": True, "message": str(result.get("message") or "已重载")}
    except dashboard.DashboardError as exc:
        return {"ok": False, "message": exc.message}


def _plugin_ready(inst: dict) -> tuple[bool, str]:
    try:
        dashboard.call(
            inst, "GET", f"plugins/extensions/{PLUGIN_ID}/packs", timeout=15
        )
        return True, ""
    except dashboard.DashboardError as exc:
        return False, exc.message


def _settings_view(inst: dict) -> dict:
    path = _root(inst) / "data" / "config" / f"{PLUGIN_ID}_config.json"
    data = _read_json(path, {})
    generation = data.get("generation") if isinstance(data, dict) else {}
    generation = generation if isinstance(generation, dict) else {}
    emotion = generation.get("emotion") if isinstance(generation, dict) else {}
    emotion = emotion if isinstance(emotion, dict) else {}
    message = generation.get("message") if isinstance(generation, dict) else {}
    message = message if isinstance(message, dict) else {}
    try:
        probability = int(emotion.get("probability", 30))
    except (TypeError, ValueError):
        probability = 30
    return {
        "probability": max(0, min(100, probability)),
        "max_memes_per_message": int(emotion.get("max_memes_per_message", 1) or 1),
        "enable_mixed": bool(message.get("enable_mixed", False)),
        "mixed_probability": int(message.get("mixed_probability", 50) or 50),
    }


def _recent_groups(inst: dict, limit: int = 20) -> list[dict]:
    db = _root(inst) / "data" / "data_v4.db"
    if not db.is_file():
        return []
    found: dict[str, dict] = {}
    try:
        uri = f"file:{db.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=3)
        try:
            rows = con.execute(
                "select user_id, updated_at from conversations "
                "where user_id like '%:GroupMessage:%' "
                "order by updated_at desc limit 300"
            ).fetchall()
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return []
    for user_id, updated_at in rows:
        text = str(user_id or "")
        marker = ":GroupMessage:"
        if marker not in text:
            continue
        group_id = text.rsplit(marker, 1)[1].strip()
        if not group_id.isdigit():
            continue
        item = found.setdefault(
            group_id, {"group_id": group_id, "count": 0, "last_at": ""}
        )
        item["count"] += 1
        if str(updated_at or "") > item["last_at"]:
            item["last_at"] = str(updated_at or "")
    return sorted(
        found.values(), key=lambda item: item["last_at"], reverse=True
    )[:limit]


def overview(inst: dict) -> dict:
    base = _base(inst)
    registry = _registry(inst)
    by_id = {
        str(item.get("id") or ""): item
        for item in registry["installed_packs"]
        if str(item.get("id") or "")
    }
    packs = []
    for pack_dir in sorted((base / "packs").glob("*")):
        if not pack_dir.is_dir() or not (pack_dir / "manifest.json").is_file():
            continue
        pack_id = pack_dir.name
        if not PACK_ID_RE.fullmatch(pack_id):
            continue
        packs.append(_pack_view(inst, pack_id, by_id.get(pack_id)))
    ready, error = _plugin_ready(inst)
    source = DEFAULT_SOURCE
    return {
        "plugin_id": PLUGIN_ID,
        "plugin_ready": ready,
        "plugin_error": error,
        "packs": packs,
        "active_pack_id": _default_pack_id(inst),
        "settings": _settings_view(inst),
        "source_dir": str(source),
        "source_exists": source.is_dir(),
        "source_images": len(_scan_images(source)),
        "groups": _recent_groups(inst),
        "updated": time.time(),
    }


def list_images(inst: dict, pack_id: str = "", category: str = "") -> dict:
    pack = _pack_id(pack_id or _default_pack_id(inst))
    if not _pack_dir(inst, pack).is_dir():
        raise ImageMemeError("表情包不存在")
    if category and not CATEGORY_RE.fullmatch(category):
        raise ImageMemeError("分类不合法")
    files = _image_files(_pack_dir(inst, pack), category)
    items = []
    for path in files:
        try:
            relative = path.relative_to(_pack_dir(inst, pack) / "memes")
        except ValueError:
            continue
        items.append({
            "category": relative.parent.name,
            "name": path.name,
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
        })
    return {"pack_id": pack, "category": category, "items": items}


def image_path(inst: dict, pack_id: str, category: str, name: str) -> Path:
    pack = _pack_id(pack_id)
    if not CATEGORY_RE.fullmatch(str(category or "")):
        raise ImageMemeError("分类不合法")
    filename = _safe_segment(name, "文件名")
    if Path(filename).suffix.lower() not in IMAGE_SUFFIXES:
        raise ImageMemeError("不是支持的图片格式")
    root = (_pack_dir(inst, pack) / "memes").resolve()
    path = (root / category / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ImageMemeError("图片路径越界") from exc
    if not path.is_file():
        raise ImageMemeError("图片不存在")
    return path


def _category_from_name(name: str) -> str:
    stem = Path(name).stem.lower()
    match = re.search(r"_([a-z]+)$", stem)
    category = match.group(1) if match else "other"
    return category if category in CATEGORY_DESCRIPTIONS else "other"


def import_pack(
    inst: dict,
    source_dir: str = "",
    pack_id: str = "",
    pack_name: str = "",
) -> dict:
    source = Path(source_dir).expanduser() if source_dir else DEFAULT_SOURCE
    if not source.is_dir():
        raise ImageMemeError(f"来源目录不存在：{source}")
    pack = _pack_id(pack_id or DEFAULT_PACK_ID)
    target = _pack_dir(inst, pack)
    files = _scan_images(source)
    if not files:
        raise ImageMemeError("来源目录没有可用图片")
    if target.is_dir() and _image_files(target):
        return {**_pack_view(inst, pack), "imported": False, "reload": None}
    target.mkdir(parents=True, exist_ok=True)
    memes = target / "memes"
    memes.mkdir(parents=True, exist_ok=True)
    categories: dict[str, int] = {}
    for file in files:
        category = _category_from_name(file.name)
        dest_dir = memes / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / file.name
        shutil.copy2(file, dest)
        categories[category] = categories.get(category, 0) + 1
    manifest = {
        "schema_version": 1,
        "id": pack,
        "name": str(pack_name or DEFAULT_PACK_NAME)[:80],
        "version": "1.0.0",
        "description": f"牧鱼导入的本地表情包，共 {len(files)} 张。",
        "tags": ["local", "muyu"],
        "categories": {
            name: {"description": CATEGORY_DESCRIPTIONS.get(name, "其他表情。")}
            for name in sorted(categories)
        },
        "previews": [],
    }
    _write_json(target / "manifest.json", manifest)
    _write_json(target / "memes_data.json", {
        name: CATEGORY_DESCRIPTIONS.get(name, "其他表情。")
        for name in sorted(categories)
    })

    registry = _registry(inst)
    entries = [
        item for item in registry["installed_packs"]
        if str(item.get("id") or "") != pack
    ]
    entries.append({
        "id": pack,
        "name": manifest["name"],
        "version": "1.0.0",
        "enabled": True,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    registry["installed_packs"] = entries
    _write_json(_base(inst) / "registry.json", registry)

    rules = _rules(inst)
    others = [
        item for item in rules["rules"]
        if str(item.get("scope") or "") != "default"
    ]
    others.append({
        "id": "default",
        "scope": "default",
        "pack_id": pack,
        "pack_ids": [pack],
    })
    rules["rules"] = others
    _write_json(_base(inst) / "selection_rules.json", rules)
    return {
        **_pack_view(inst, pack),
        "imported": True,
        "files": len(files),
        "categories": categories,
        "reload": _plugin_reload(inst),
    }


def activate(inst: dict, pack_id: str) -> dict:
    pack = _pack_id(pack_id)
    if not _pack_dir(inst, pack).is_dir():
        raise ImageMemeError("表情包不存在")
    rules = _rules(inst)
    others = [
        item for item in rules["rules"]
        if str(item.get("scope") or "") != "default"
    ]
    others.append({
        "id": "default",
        "scope": "default",
        "pack_id": pack,
        "pack_ids": [pack],
    })
    rules["rules"] = others
    _write_json(_base(inst) / "selection_rules.json", rules)
    return {"pack_id": pack, "reload": _plugin_reload(inst)}


def delete_image(inst: dict, pack_id: str, category: str, name: str) -> dict:
    path = image_path(inst, pack_id, category, name)
    path.unlink()
    return {"pack_id": pack_id, "category": category, "name": name}


def save_settings(inst: dict, payload: dict) -> dict:
    path = _root(inst) / "data" / "config" / f"{PLUGIN_ID}_config.json"
    data = _read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    generation = data.setdefault("generation", {})
    if not isinstance(generation, dict):
        generation = data["generation"] = {}
    emotion = generation.setdefault("emotion", {})
    if not isinstance(emotion, dict):
        emotion = generation["emotion"] = {}
    message = generation.setdefault("message", {})
    if not isinstance(message, dict):
        message = generation["message"] = {}
    try:
        probability = max(0, min(100, int(payload.get("probability"))))
    except (TypeError, ValueError) as exc:
        raise ImageMemeError("概率必须是 0-100 的整数") from exc
    emotion["probability"] = probability
    if "max_memes_per_message" in payload:
        try:
            emotion["max_memes_per_message"] = max(
                1, min(9, int(payload.get("max_memes_per_message")))
            )
        except (TypeError, ValueError):
            pass
    if "enable_mixed" in payload:
        message["enable_mixed"] = bool(payload.get("enable_mixed"))
    if "mixed_probability" in payload:
        try:
            message["mixed_probability"] = max(
                0, min(100, int(payload.get("mixed_probability")))
            )
        except (TypeError, ValueError):
            pass
    _write_json(path, data)
    return {"settings": _settings_view(inst), "reload": _plugin_reload(inst)}


def random_send(
    inst: dict,
    group_id: str,
    pack_id: str = "",
    category: str = "",
    dry_run: bool = False,
) -> dict:
    group = str(group_id or "").strip()
    if not group.isdigit():
        raise ImageMemeError("群号必须是数字")
    pack = _pack_id(pack_id or _default_pack_id(inst))
    if not _pack_dir(inst, pack).is_dir():
        raise ImageMemeError("表情包不存在")
    if category and not CATEGORY_RE.fullmatch(category):
        raise ImageMemeError("分类不合法")
    try:
        result = dashboard.call(
            inst,
            "POST",
            f"plugins/extensions/{PLUGIN_ID}/random/send",
            {
                "group_id": group,
                "pack_id": pack,
                "category": category,
                "dry_run": bool(dry_run),
            },
            timeout=60,
        )
    except dashboard.DashboardError as exc:
        raise ImageMemeError(f"插件发送失败：{exc.message}") from exc
    data = result.get("data") if isinstance(result, dict) else None
    return data if isinstance(data, dict) else result


def mime_for(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"
