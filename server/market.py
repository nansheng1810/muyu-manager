"""插件市场：本地索引加载、搜索、分类与旧包兼容修复。"""

from __future__ import annotations

import io
import json
import posixpath
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

from . import store

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024

_cache: dict = {"items": None, "ts": 0.0}


def _normalize(plugin_id: str, raw: dict) -> dict:
    name = str(raw.get("name") or plugin_id.split("/")[-1])
    display = str(raw.get("display_name") or name)
    desc = str(raw.get("desc") or "").replace("\r", "").strip()
    return {
        "id": plugin_id,
        "name": name,
        "display_name": display,
        "desc": desc,
        "author": str(raw.get("author") or plugin_id.split("/")[0]),
        "version": str(raw.get("version") or ""),
        "repo": str(raw.get("repo") or f"https://github.com/{plugin_id}"),
        "download_url": str(raw.get("download_url") or ""),
        "logo": str(raw.get("logo") or ""),
        "category": str(raw.get("category") or "其他"),
        "platforms": raw.get("support_platforms") if isinstance(raw.get("support_platforms"), list) else [],
        "astrbot_version": str(raw.get("astrbot_version") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "stars": int(raw.get("stars") or 0),
        "_haystack": f"{name} {display} {desc} {raw.get('author') or ''} {plugin_id}".lower(),
    }


def load_items(settings: dict, force: bool = False) -> list[dict]:
    now = time.time()
    if not force and _cache["items"] is not None and now - _cache["ts"] < 600:
        return _cache["items"]
    data = store.ensure_market_index(settings)
    items = []
    for plugin_id, raw in data.items():
        if plugin_id.startswith("$") or not isinstance(raw, dict):
            continue
        items.append(_normalize(str(plugin_id), raw))
    items.sort(key=lambda x: (x["display_name"].lower(), x["name"]))
    _cache["items"] = items
    _cache["ts"] = now
    return items


def refresh(settings: dict) -> dict:
    source = Path(settings.get("astrbot_source", "")) / "data" / "plugins.json"
    if not source.exists():
        raise FileNotFoundError(f"未找到市场索引缓存：{source}")
    store.write_json(store.MARKET_CACHE_PATH, store.read_json(source, {}))
    items = load_items(settings, force=True)
    return {"count": len(items), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def categories(settings: dict) -> list[dict]:
    items = load_items(settings)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"name": name, "count": count} for name, count in ordered]


def search(settings: dict, query: str = "", category: str = "", page: int = 1, size: int = 24) -> dict:
    items = load_items(settings)
    query = (query or "").strip().lower()
    category = (category or "").strip()

    filtered = items
    if query:
        tokens = [t for t in query.split() if t]
        filtered = [i for i in filtered if all(t in i["_haystack"] for t in tokens)]
    if category and category not in {"全部", "all"}:
        filtered = [i for i in filtered if i["category"] == category]

    total = len(filtered)
    page = max(1, int(page))
    size = min(60, max(1, int(size)))
    start = (page - 1) * size
    slice_ = filtered[start : start + size]
    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, (total + size - 1) // size),
        "items": [
            {k: v for k, v in item.items() if k != "_haystack"} for item in slice_
        ],
    }


def _metadata_yaml(entry: dict) -> str:
    plugin_id = str(entry.get("id") or "")
    fields = {
        "name": str(entry.get("name") or plugin_id.split("/")[-1]
                    or "astrbot_plugin_unknown"),
        "display_name": str(entry.get("display_name") or entry.get("name")
                            or plugin_id.split("/")[-1] or "未命名插件"),
        "desc": str(entry.get("desc") or "").replace("\r", " ").replace("\n", " "),
        "version": str(entry.get("version") or "1.0.0"),
        "author": str(entry.get("author") or plugin_id.split("/")[0] or "unknown"),
        "repo": str(entry.get("repo") or ""),
    }
    if not fields["desc"].strip():
        fields["desc"] = "来自 AstrBot 插件市场的旧版插件"
    lines = [
        f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in fields.items() if value
    ]
    return "\n".join(lines) + "\n"


def _archive_root(names: list[str]) -> str:
    """返回压缩包唯一的顶层目录前缀；根目录直放文件时返回空串。"""
    files = [
        name.replace("\\", "/")
        for name in names
        if name and not name.replace("\\", "/").endswith("/")
    ]
    parents = []
    for name in files:
        parent = name.rsplit("/", 1)[0] if "/" in name else ""
        parents.append(parent)
    if not parents:
        return ""
    try:
        root = posixpath.commonpath(parents)
    except ValueError:
        return ""
    if root in ("", "."):
        return ""
    return root.rstrip("/") + "/"


def inject_metadata(raw: bytes, entry: dict) -> bytes:
    """给缺少 metadata.yaml 的旧市场包补一份元数据，返回新的 zip 字节。

    压缩包已有 metadata.yaml/metadata.yml 时原样返回；顶层目录保持不变，
    这样 AstrBot 的归档根目录解析仍能找到 main.py 与新增的 metadata.yaml。
    """
    try:
        source = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError("插件压缩包格式错误") from exc
    with source:
        names = source.namelist()
        prefix = _archive_root(names)
        if prefix + "metadata.yaml" in names or prefix + "metadata.yml" in names:
            return raw
        metadata = _metadata_yaml(entry).encode("utf-8")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                target.writestr(info, source.read(info.filename))
            target.writestr(prefix + "metadata.yaml", metadata)
    return output.getvalue()


def download_archive(url: str, timeout: float = 120.0,
                     max_bytes: int = MAX_ARCHIVE_BYTES) -> bytes:
    """下载市场插件包，限制体积，供 metadata 修复后上传安装。"""
    request = urllib.request.Request(
        str(url), headers={"User-Agent": "Moyu/1.22"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("插件包超过 64MB，拒绝自动修复")
    return data


def multipart_payload(fields: dict, filename: str, data: bytes,
                      content_type: str = "application/zip") -> tuple[bytes, str]:
    """构造插件上传所需的最小 multipart 请求体。"""
    boundary = "----MoyuBoundary" + uuid.uuid4().hex
    lines: list[str] = []
    for key, value in fields.items():
        lines.extend([
            f"--{boundary}",
            f'Content-Disposition: form-data; name="{key}"',
            "",
            str(value),
        ])
    lines.extend([
        f"--{boundary}",
        f'Content-Disposition: form-data; name="file"; filename="{filename}"',
        f"Content-Type: {content_type}",
        "",
    ])
    head = "\r\n".join(lines).encode("utf-8") + b"\r\n"
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + data + tail, f"multipart/form-data; boundary={boundary}"


def find(settings: dict, plugin_id: str) -> dict | None:
    for item in load_items(settings):
        if item["id"] == plugin_id:
            return {k: v for k, v in item.items() if k != "_haystack"}
    return None
