"""Codex 模型目录读取与 config.toml 顶层 model 写入。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

TOP_MODEL_LINE = re.compile(r'^model\s*=\s*"[^"]*"\s*$')


class CodexModelError(Exception):
    pass


def codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME")
    return Path(raw) if raw else Path.home() / ".codex"


def config_path() -> Path:
    return codex_home() / "config.toml"


def _read_config() -> str:
    path = config_path()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CodexModelError(f"读取 Codex 配置失败：{exc}") from exc


def _top_section(text: str) -> str:
    """返回第一个 [table] 之前的顶层片段。"""
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("["):
            break
        lines.append(line)
    return "\n".join(lines)


def current_model() -> str:
    for line in _top_section(_read_config()).splitlines():
        match = re.match(r'^model\s*=\s*"([^"]*)"\s*$', line)
        if match:
            return match.group(1)
    return ""


def _catalog_file(text: str) -> Path | None:
    for line in _top_section(text).splitlines():
        match = re.match(r'^model_catalog_json\s*=\s*"([^"]*)"\s*$', line)
        if match:
            value = match.group(1).strip()
            if not value:
                return None
            path = Path(value)
            return path if path.is_absolute() else codex_home() / path
    default = codex_home() / "cc-switch-model-catalog.json"
    return default if default.exists() else None


def catalog() -> dict:
    """返回 Codex 可用模型与当前模型；读不到目录时也要返回当前值。"""
    text = _read_config()
    current = ""
    for line in _top_section(text).splitlines():
        match = re.match(r'^model\s*=\s*"([^"]*)"\s*$', line)
        if match:
            current = match.group(1)
            break
    models = []
    error = ""
    path = _catalog_file(text)
    if path is not None and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("models") or []:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("slug") or item.get("id") or item.get("display_name") or "")
                if not model_id:
                    continue
                models.append({
                    "id": model_id,
                    "name": str(item.get("display_name") or model_id),
                    "description": str(item.get("description") or ""),
                })
        except (OSError, ValueError) as exc:
            error = f"读取 Codex 模型目录失败：{exc}"
    else:
        error = f"没有找到 Codex 模型目录：{path}" if path else "Codex 配置未指定 model_catalog_json"
    return {
        "current": current,
        "models": models,
        "config_path": str(config_path()),
        "catalog_path": str(path) if path else "",
        "error": error,
    }


def set_model(model_id: str) -> dict:
    model_id = str(model_id or "").strip()
    if not model_id:
        raise CodexModelError("请选择 Codex 模型。")
    if len(model_id) > 120 or any(ch in model_id for ch in '"\r\n'):
        raise CodexModelError("模型名称不合法。")
    info = catalog()
    ids = [item["id"] for item in info["models"]]
    if ids and model_id not in ids:
        raise CodexModelError(f"Codex 模型目录里没有：{model_id}")
    text = _read_config()
    lines = text.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("["):
            break
        if TOP_MODEL_LINE.match(line):
            lines[index] = f'model = "{model_id}"'
            replaced = True
            break
    if not replaced:
        insert_at = 0
        for index, line in enumerate(lines):
            if line.lstrip().startswith("["):
                break
            insert_at = index + 1
        lines.insert(insert_at, f'model = "{model_id}"')
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=".muyu-config-", dir=str(path.parent))
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
            out.write("\n".join(lines) + "\n")
        os.replace(temp_name, path)
    except OSError as exc:
        raise CodexModelError(f"写入 Codex 配置失败：{exc}") from exc
    return {"model": model_id, "config_path": str(path)}
