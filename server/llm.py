"""直接调用对话模型（OpenAI 兼容接口），仅供学习笔记使用。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import dashboard


class LLMError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _http_message(code: int, detail: str) -> str:
    if code in (401, 403):
        reason = "模型鉴权失败（API Key 无效或无权限）"
    elif code == 404:
        reason = "模型接口不存在（请检查 api_base 是否正确）"
    elif code == 429:
        reason = "模型接口限流或额度不足，请稍后重试"
    elif code >= 500:
        reason = "模型服务端异常"
    else:
        reason = "模型调用失败"
    text = f"{reason}（HTTP {code}）"
    if detail:
        text += f"：{detail}"
    return text


def _extract_error(raw: str) -> str:
    try:
        data = json.loads(raw)
    except Exception:
        return raw.strip()[:300]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            for key in ("message", "msg", "detail"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key in ("message", "detail", "msg"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _custom_headers(provider: dict) -> dict[str, str]:
    """转发 provider 的 custom_headers；跳过换行与空值。"""
    raw = provider.get("custom_headers")
    if not isinstance(raw, dict):
        return {}
    headers = {}
    for name, value in raw.items():
        name = str(name or "").strip()
        value = str(value or "").strip()
        if not name or not value or "\r" in name + value or "\n" in name + value:
            continue
        headers[name] = value
    return headers


def _apply_headers(request, key: str, headers: dict[str, str],
                   accept: str = "") -> None:
    for name, value in headers.items():
        request.add_header(name, value)
    request.add_header("Content-Type", "application/json")
    if accept:
        request.add_header("Accept", accept)
    if key:
        request.add_header("Authorization", f"Bearer {key}")


def _post(
    url: str,
    key: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    timeout: float,
    extra_body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[str, str]:
    """返回 (正文, 思考内容)。"""
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": int(max_tokens),
    }
    if isinstance(extra_body, dict):
        body.update(extra_body)
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    _apply_headers(request, key, headers or {})

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise LLMError(_http_message(exc.code, _extract_error(raw))) from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"调用模型失败：无法连接 {url}（{exc}）") from exc

    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise LLMError("模型返回的不是合法 JSON，无法解析") from exc

    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        message = _extract_error(raw) if isinstance(payload, dict) else ""
        raise LLMError(f"模型没有返回内容{('：' + message) if message else ''}")

    message = (choices[0] or {}).get("message") or {}
    content = _content_text(message.get("content")).strip()
    reasoning = _content_text(message.get("reasoning_content")).strip()
    return content, reasoning


def _load_provider(inst: dict, provider_id: str) -> dict:
    try:
        detail = dashboard.call(
            inst,
            "GET",
            "providers/by-id",
            query={"provider_id": provider_id, "merged": "true"},
            timeout=30,
        )
    except dashboard.DashboardError as exc:
        raise LLMError(f"读取模型配置失败：{exc.message}") from exc
    data = detail.get("data") if isinstance(detail, dict) else None
    provider = (data or {}).get("provider") or {}
    provider_type = str(provider.get("provider_type") or "")
    if provider_type != "chat_completion":
        raise LLMError(
            f"「{provider_id}」不是对话模型（当前类型：{provider_type or '未知'}），无法调用"
        )
    model = str(provider.get("model") or "").strip()
    if not model:
        raise LLMError(f"「{provider_id}」没有配置模型名称")
    api_base = str(provider.get("api_base") or "").strip()
    if not api_base:
        raise LLMError(f"「{provider_id}」没有配置 api_base，无法调用")
    return provider


def _credentials(provider: dict) -> tuple[str, str, str, dict]:
    """返回 (url, key, model, custom_extra_body)。"""
    api_base = str(provider.get("api_base") or "").strip()
    model = str(provider.get("model") or "").strip()
    key = provider.get("key")
    if isinstance(key, list):
        key = key[0] if key else ""
    key = str(key or "").strip()
    extra = provider.get("custom_extra_body")
    if not isinstance(extra, dict):
        extra = {}
    return api_base.rstrip("/") + "/chat/completions", key, model, dict(extra)


def chat(
    inst: dict,
    provider_id: str,
    messages: list[dict],
    max_tokens: int = 2000,
    timeout: float = 180.0,
) -> str:
    provider = _load_provider(inst, provider_id)
    url, key, model, extra = _credentials(provider)
    headers = _custom_headers(provider)

    content, reasoning = _post(
        url, key, model, messages, max_tokens, timeout, extra_body=extra,
        headers=headers,
    )
    if not content and reasoning and max_tokens < 8192:
        # 思考模型可能把 token 预算吃光，翻倍重试一次
        retry_budget = min(max_tokens * 2, 8192)
        content, reasoning = _post(
            url, key, model, messages, retry_budget, timeout, extra_body=extra,
            headers=headers,
        )
    if content:
        return content
    if reasoning:
        raise LLMError(
            "模型只输出了思考内容（reasoning_content），没有返回正文。可在「模型与人格」中降低深度思考强度，或换一个模型后重试"
        )
    raise LLMError("模型返回内容为空，请稍后重试或换一个模型")


def _stream_payloads(response):
    """逐行产出 SSE data 负载；非流式 JSON 响应整体产出。"""
    content_type = str(response.headers.get("Content-Type") or "").lower()
    if "text/event-stream" not in content_type:
        raw = response.read().decode("utf-8", "replace").strip()
        if raw:
            yield raw
        return
    for raw_line in response:
        line = raw_line.decode("utf-8", "replace").strip()
        if not line or line.startswith(":"):
            continue
        payload = line[5:].strip() if line.startswith("data:") else line
        if payload:
            yield payload


def chat_stream(
    inst: dict,
    provider_id: str,
    messages: list[dict],
    max_tokens: int = 4000,
    timeout: float = 300.0,
    extra_body: dict | None = None,
):
    """流式调用对话模型，逐个 yield 思考/正文增量事件。

    HTTP 与鉴权错误在调用时同步抛出 LLMError，便于接口层直接返回错误。
    """
    provider = _load_provider(inst, provider_id)
    url, key, model, extra = _credentials(provider)
    if extra_body:
        extra = {**extra, **extra_body}
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": int(max_tokens),
        "stream": True,
    }
    if extra:
        body.update(extra)
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    _apply_headers(
        request, key, _custom_headers(provider), accept="text/event-stream"
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise LLMError(_http_message(exc.code, _extract_error(raw))) from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"调用模型失败：无法连接 {url}（{exc}）") from exc

    def events():
        reasoning_parts: list[str] = []
        reply_parts: list[str] = []
        try:
            for payload in _stream_payloads(response):
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except Exception:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if not chunk.get("choices"):
                    message = _extract_error(payload)
                    if message and chunk.get("error"):
                        raise LLMError(f"模型返回错误：{message}")
                    continue
                choice = chunk["choices"][0] or {}
                delta = choice.get("delta") or choice.get("message") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                content = _content_text(delta.get("content"))
                if isinstance(reasoning, str) and reasoning:
                    reasoning_parts.append(reasoning)
                    yield {"type": "reasoning", "text": reasoning}
                if content:
                    reply_parts.append(content)
                    yield {"type": "content", "text": content}
        finally:
            response.close()
        yield {
            "type": "done",
            "reasoning": "".join(reasoning_parts).strip(),
            "reply": "".join(reply_parts).strip(),
            "model": model,
        }

    return events()
