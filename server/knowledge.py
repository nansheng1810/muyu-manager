"""知识库管理：代理 AstrBot Dashboard 的 knowledge-bases 接口。"""

from __future__ import annotations

import urllib.parse

from . import dashboard


class KnowledgeError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = str(message)
        self.status = int(status)


def _data(result) -> dict:
    if isinstance(result, dict) and result.get("status") == "error":
        raise KnowledgeError(result.get("message") or "知识库操作失败", 502)
    if isinstance(result, dict) and "data" in result:
        data = result.get("data")
        return data if isinstance(data, dict) else {"items": data}
    return result if isinstance(result, dict) else {"items": result}


def _kb_id(value: str) -> str:
    return urllib.parse.quote(str(value or ""), safe="")


def list_bases(inst: dict, page: int = 1, page_size: int = 50) -> dict:
    return _data(dashboard.call(
        inst, "GET", "knowledge-bases",
        query={"page": page, "page_size": page_size}, timeout=30,
    ))


def create_base(inst: dict, payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    embedding = str(payload.get("embedding_provider_id") or "").strip()
    if not name:
        raise KnowledgeError("请填写知识库名称")
    if not embedding:
        raise KnowledgeError("请选择向量模型（Embedding Provider）")
    body = {
        "name": name[:120],
        "description": str(payload.get("description") or "")[:400],
        "embedding_provider_id": embedding,
    }
    for key in ("rerank_provider_id", "chunk_size", "chunk_overlap",
                "top_k_dense", "top_k_sparse", "top_m_final"):
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            body[key] = int(value)
        except (TypeError, ValueError):
            raise KnowledgeError(f"{key} 需要是整数") from None
    return _data(dashboard.call(inst, "POST", "knowledge-bases", body, timeout=60))


def delete_base(inst: dict, kb_id: str) -> dict:
    return _data(dashboard.call(
        inst, "DELETE", f"knowledge-bases/{_kb_id(kb_id)}", timeout=60,
    ))


def base_stats(inst: dict, kb_id: str) -> dict:
    return _data(dashboard.call(
        inst, "GET", f"knowledge-bases/{_kb_id(kb_id)}/stats", timeout=30,
    ))


def list_documents(inst: dict, kb_id: str, search: str = "") -> dict:
    return _data(dashboard.call(
        inst, "GET", f"knowledge-bases/{_kb_id(kb_id)}/documents",
        query={"page": 1, "page_size": 100, "search": search or None}, timeout=30,
    ))


def upload_document(inst: dict, kb_id: str, body: bytes, content_type: str) -> dict:
    result = dashboard.upload_raw(
        inst, f"knowledge-bases/{_kb_id(kb_id)}/documents",
        body, content_type, timeout=600,
    )
    return _data(result)


def delete_document(inst: dict, kb_id: str, doc_id: str) -> dict:
    return _data(dashboard.call(
        inst, "DELETE",
        f"knowledge-bases/{_kb_id(kb_id)}/documents/{_kb_id(doc_id)}",
        timeout=60,
    ))


def retrieve(inst: dict, kb_id: str, payload: dict) -> dict:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise KnowledgeError("请输入检索问题")
    stats = base_stats(inst, kb_id)
    kb_name = str((stats or {}).get("kb_name") or "").strip()
    if not kb_name:
        raise KnowledgeError("知识库名称为空，无法检索", 404)
    body = {"query": query[:2000], "kb_names": [kb_name], "debug": False}
    if payload.get("top_k") not in (None, ""):
        try:
            body["top_k"] = max(1, min(int(payload.get("top_k")), 30))
        except (TypeError, ValueError):
            raise KnowledgeError("top_k 需要是整数") from None
    if payload.get("threshold") not in (None, ""):
        try:
            body["threshold"] = max(0.0, min(float(payload.get("threshold")), 1.0))
        except (TypeError, ValueError):
            raise KnowledgeError("threshold 需要是数字") from None
    if payload.get("rerank") is not None:
        body["rerank"] = bool(payload.get("rerank"))
    return _data(dashboard.call(
        inst, "POST", f"knowledge-bases/{_kb_id(kb_id)}/retrieve", body, timeout=60,
    ))


def import_urls(inst: dict, kb_id: str, payload: dict) -> dict:
    urls = payload.get("urls")
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list):
        urls = []
    cleaned = [str(item).strip() for item in urls if str(item or "").strip()]
    if not cleaned:
        raise KnowledgeError("请填写至少一个网页链接")
    body: dict = {"kb_id": kb_id, "urls": cleaned[:20], "url": cleaned[0]}
    for key in ("chunk_size", "chunk_overlap", "batch_size"):
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            body[key] = int(value)
        except (TypeError, ValueError):
            raise KnowledgeError(f"{key} 需要是整数") from None
    return _data(dashboard.call(
        inst, "POST", f"knowledge-bases/{_kb_id(kb_id)}/documents/import-url",
        body, timeout=120,
    ))


def embedding_providers(inst: dict) -> list[dict]:
    """从 AstrBot 的 Provider 列表中挑出向量模型。"""
    payload = dashboard.call(inst, "GET", "providers", timeout=30)
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = f"{item.get('provider_type') or ''} {item.get('type') or ''}".lower()
        if "embedding" not in kind:
            continue
        result.append({
            "id": str(item.get("id") or ""),
            "model": str(item.get("model") or ""),
            "type": str(item.get("type") or ""),
            "enable": bool(item.get("enable", True)),
        })
    return result
