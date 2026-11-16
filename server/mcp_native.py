"""Manager-native MCP for QQ chat and local AstrBot plugin data.

The manager hosts the MCP endpoint. A small AstrBot plugin forwards group
messages over a local WebSocket and sends replies through the existing platform
adapter. Default LLM replies are paused while a session owns the group, but the
other plugin event hooks keep running so LivingMemory and human-like plugins can
observe the conversation.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import itertools
import json
import os
import re
import secrets
import shutil
import threading
import time
import tomllib
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import uvicorn
from fastapi import APIRouter, Body, HTTPException, Request, WebSocket, WebSocketDisconnect
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import bili, consoles, dashboard, image_memes, inbox, memory, mood, presence, reply_probability, rhythm, store, styles

router = APIRouter()

PLUGIN_ID = "muyu_mcp_bridge"
SERVER_NAME = "muyu_native"
DEFAULT_PORT = 18778
STATE_PATH = store.DATA_DIR / "mcp_native.json"
LOG_DIR = store.DATA_DIR / "logs"
PLUGIN_SOURCE = Path(getattr(store, "_BUNDLE_DIR", store.BASE_DIR)) / "plugins_src" / PLUGIN_ID
CODEX_BEGIN = "# === muyu native mcp BEGIN ==="
CODEX_END = "# === muyu native mcp END ==="
DSH_BEGIN = "# === muyu native mcp BEGIN ==="
DSH_END = "# === muyu native mcp END ==="
DSH_PROFILE = "web"

AGENT_LABELS = {"dsh": "DSH", "codex": "Codex"}
DEFAULT_AGENTS = {
    "dsh": {"instance_id": "f0e1e0b6", "port": 18778, "token": ""},
    "codex": {"instance_id": "bot-339f", "port": 18779, "token": ""},
}

DEFAULT_STATE = {
    "enabled": True,
    "bridge_token": "",
    "agents": {name: dict(value) for name, value in DEFAULT_AGENTS.items()},
    "permissions": {
        "chat": True,
        "memory": True,
        "human": True,
        "memes": True,
        "inbox": True,
    },
    "updated_at": "",
}


class NativeMCPError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(str(message))
        self.status = int(status)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ok(data=None, message: str = "") -> dict:
    return {"status": "ok", "message": message, "data": data}


def _fail(message: str, code: int = 400):
    return JSONResponse(
        {"status": "error", "message": message, "data": None}, status_code=code
    )


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


_state_lock = threading.RLock()


def load_state() -> dict:
    data = store.read_json(STATE_PATH, {})
    state = _deep_merge(DEFAULT_STATE, data if isinstance(data, dict) else {})
    changed = False
    if not state.get("bridge_token"):
        state["bridge_token"] = secrets.token_urlsafe(32)
        changed = True
    for name, value in DEFAULT_AGENTS.items():
        cfg = state.setdefault("agents", {}).setdefault(name, dict(value))
        if not cfg.get("instance_id"):
            cfg["instance_id"] = value["instance_id"]
            changed = True
        if not cfg.get("port"):
            cfg["port"] = value["port"]
            changed = True
        if not cfg.get("token"):
            cfg["token"] = secrets.token_urlsafe(32)
            changed = True
    if changed:
        with _state_lock:
            state["updated_at"] = _now()
            store.write_json(STATE_PATH, state)
    return state


def save_state(patch: dict) -> dict:
    with _state_lock:
        state = _deep_merge(load_state(), patch)
        state["updated_at"] = _now()
        store.write_json(STATE_PATH, state)
        return state


def agent_config(agent: str) -> dict:
    state = load_state()
    name = str(agent or "").lower()
    cfg = (state.get("agents") or {}).get(name)
    if not isinstance(cfg, dict):
        raise NativeMCPError("未知 Agent。", 404)
    port = int(cfg.get("port") or DEFAULT_AGENTS[name]["port"])
    return {
        "agent": name,
        "label": AGENT_LABELS[name],
        "instance_id": str(cfg.get("instance_id") or ""),
        "port": port,
        "url": f"http://127.0.0.1:{port}/mcp",
        "token": str(cfg.get("token") or ""),
    }


def public_state() -> dict:
    state = load_state()
    agents = {}
    for name in DEFAULT_AGENTS:
        cfg = agent_config(name)
        agents[name] = {
            "label": cfg["label"],
            "instance_id": cfg["instance_id"],
            "port": cfg["port"],
            "url": cfg["url"],
            "token_saved": bool(cfg["token"]),
        }
    return {
        "enabled": bool(state.get("enabled")),
        "bridge_token_saved": bool(state.get("bridge_token")),
        "agents": agents,
        "permissions": state.get("permissions") or {},
        "updated_at": state.get("updated_at") or "",
    }


def set_config(enabled: bool, port: int | None = None) -> dict:
    save_state({"enabled": bool(enabled)})
    if enabled:
        return start_all()
    return stop_all()


def rotate_tokens() -> dict:
    state = load_state()
    agents = state.get("agents") or {}
    for name in DEFAULT_AGENTS:
        agents.setdefault(name, dict(DEFAULT_AGENTS[name]))["token"] = secrets.token_urlsafe(32)
    save_state({"agents": agents, "bridge_token": secrets.token_urlsafe(32)})
    stop_all()
    if load_state().get("enabled"):
        start_all()
    return public_state()


# --------------------------------------------------------------- bridge hub


@dataclass
class BridgeConnection:
    instance_id: str
    websocket: WebSocket
    loop: asyncio.AbstractEventLoop
    self_id: str = ""
    platform_id: str = ""
    nickname: str = ""
    groups: list[dict] = field(default_factory=list)
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "self_id": self.self_id,
            "platform_id": self.platform_id,
            "nickname": self.nickname,
            "groups": self.groups,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
        }


class BridgeHub:
    def __init__(self):
        self._lock = threading.RLock()
        self._connections: dict[str, BridgeConnection] = {}
        self._pending: dict[str, concurrent.futures.Future] = {}

    def register(self, conn: BridgeConnection) -> None:
        with self._lock:
            old = self._connections.get(conn.instance_id)
            self._connections[conn.instance_id] = conn
        if old is not None and old.websocket is not conn.websocket:
            try:
                old.loop.call_soon_threadsafe(lambda: asyncio.create_task(old.websocket.close()))
            except Exception:
                pass

    def unregister(self, instance_id: str, websocket: WebSocket | None = None) -> None:
        with self._lock:
            current = self._connections.get(instance_id)
            if current is not None and (websocket is None or current.websocket is websocket):
                self._connections.pop(instance_id, None)

    def get(self, instance_id: str) -> BridgeConnection | None:
        with self._lock:
            return self._connections.get(instance_id)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [item.public() for item in self._connections.values()]

    def resolve(self, request_id: str, payload: dict) -> None:
        with self._lock:
            future = self._pending.pop(str(request_id), None)
        if future is not None and not future.done():
            future.set_result(payload)

    def send_command(self, instance_id: str, action: str, data: dict | None = None, timeout: int = 30) -> dict:
        conn = self.get(instance_id)
        if conn is None:
            raise NativeMCPError("AstrBot 桥插件未连接；请先安装并启用 muyu_mcp_bridge。", 409)
        request_id = uuid.uuid4().hex
        future: concurrent.futures.Future = concurrent.futures.Future()
        with self._lock:
            self._pending[request_id] = future
        payload = {
            "type": "command",
            "request_id": request_id,
            "action": action,
            "data": data or {},
        }
        try:
            asyncio.run_coroutine_threadsafe(conn.websocket.send_json(payload), conn.loop).result(5)
            result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise NativeMCPError("桥插件响应超时。", 504) from None
        except Exception as exc:  # noqa: BLE001
            raise NativeMCPError(f"桥插件通信失败：{exc}", 502) from None
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        if not isinstance(result, dict) or not result.get("ok"):
            message = result.get("error") if isinstance(result, dict) else "桥插件返回失败"
            raise NativeMCPError(str(message or "桥插件返回失败"), 409)
        return result.get("data") if isinstance(result.get("data"), dict) else {"result": result.get("data")}


hub = BridgeHub()


# ------------------------------------------------------------------ sessions


@dataclass
class ChatSession:
    id: str
    instance_id: str
    group_id: str
    group_name: str
    platform_id: str
    active: bool = True
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    cursor: int = 0
    messages: list[dict] = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition)

    def public(self) -> dict:
        return {
            "id": self.id,
            "instance_id": self.instance_id,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "platform_id": self.platform_id,
            "active": bool(self.active),
            "created": self.created,
            "updated": self.updated,
            "pending": max(0, len([m for m in self.messages if m["id"] > self.cursor])),
        }


class NativeMCPCore:
    def __init__(self):
        self._lock = threading.RLock()
        self.sessions: dict[str, ChatSession] = {}
        self._seq = itertools.count(1)

    def _session(self, session_id: str) -> ChatSession:
        with self._lock:
            session = self.sessions.get(str(session_id))
        if session is None or not session.active:
            raise NativeMCPError("聊天会话不存在或已停止。", 404)
        return session

    def sessions_public(self) -> list[dict]:
        with self._lock:
            return [item.public() for item in self.sessions.values()]

    def active_for(self, instance_id: str) -> list[dict]:
        with self._lock:
            return [
                {"session_id": item.id, "group_id": item.group_id, "platform_id": item.platform_id}
                for item in self.sessions.values()
                if item.active and item.instance_id == instance_id
            ]

    def start_session(self, instance_id: str, group_id: str, group_name: str = "", platform_id: str = "") -> dict:
        instance_id = str(instance_id or "").strip()
        group_id = str(group_id or "").strip()
        if not instance_id or not group_id:
            raise NativeMCPError("instance_id 和 group_id 不能为空。")
        conn = hub.get(instance_id)
        if conn is None:
            raise NativeMCPError("AstrBot 桥插件未连接。", 409)
        platform = platform_id or getattr(conn, "platform_id", "")
        data = hub.send_command(
            instance_id,
            "takeover",
            {"group_id": group_id, "platform_id": platform, "group_name": group_name},
        )
        session = ChatSession(
            id=uuid.uuid4().hex,
            instance_id=instance_id,
            group_id=group_id,
            group_name=group_name or group_id,
            platform_id=str(data.get("platform_id") or platform),
        )
        with self._lock:
            self.sessions[session.id] = session
        return session.public()

    def stop_session(self, session_id: str) -> dict:
        session = self._session(session_id)
        try:
            hub.send_command(
                session.instance_id,
                "release",
                {"group_id": session.group_id},
                timeout=12,
            )
        except NativeMCPError:
            pass
        with self._lock:
            session.active = False
            self.sessions.pop(session.id, None)
            with session.cond:
                session.cond.notify_all()
        return {"stopped": True, "session_id": session.id}

    def restore_takeover(self, instance_id: str) -> None:
        for item in self.active_for(instance_id):
            try:
                hub.send_command(
                    instance_id,
                    "takeover",
                    {"group_id": item["group_id"], "platform_id": item["platform_id"]},
                    timeout=12,
                )
            except NativeMCPError:
                break

    def ingest_event(self, instance_id: str, event: dict) -> None:
        if not isinstance(event, dict):
            return
        group_id = str(event.get("group_id") or "")
        sender_id = str(event.get("sender_id") or "")
        self_id = str(event.get("self_id") or "")
        if not group_id or (self_id and sender_id == self_id):
            return
        with self._lock:
            matches = [
                item
                for item in self.sessions.values()
                if item.active and item.instance_id == instance_id and item.group_id == group_id
            ]
        if not matches:
            return
        segments = event.get("segments") if isinstance(event.get("segments"), list) else []
        if not reply_probability.should_deliver(instance_id, self_id, segments):
            return
        for session in matches:
            item = {
                "id": next(self._seq),
                "instance_id": instance_id,
                "group_id": group_id,
                "sender_id": sender_id,
                "sender_name": str(event.get("sender_name") or ""),
                "message_id": str(event.get("message_id") or ""),
                "text": str(event.get("text") or ""),
                "segments": event.get("segments") if isinstance(event.get("segments"), list) else [],
                "time": float(event.get("time") or time.time()),
                "kind": str(event.get("kind") or "message"),
            }
            with session.cond:
                session.messages.append(item)
                if len(session.messages) > 400:
                    del session.messages[:100]
                session.updated = time.time()
                session.cond.notify_all()

    def wait_messages(
        self,
        session_id: str,
        timeout_seconds: float = 150,
        acknowledge_through_id: int | None = None,
        limit: int = 30,
    ) -> dict:
        session = self._session(session_id)
        timeout = max(1.0, min(float(timeout_seconds or 150), 180.0))
        limit = max(1, min(int(limit or 30), 50))
        deadline = time.time() + timeout
        if acknowledge_through_id is not None:
            try:
                ack = int(acknowledge_through_id)
            except (TypeError, ValueError):
                raise NativeMCPError("acknowledge_through_id 必须是整数。")
            with session.cond:
                session.cursor = max(session.cursor, ack)
        with session.cond:
            while time.time() < deadline:
                rows = [m for m in session.messages if m["id"] > session.cursor]
                if rows:
                    rows = rows[:limit]
                    last = rows[-1]["id"]
                    return {
                        "state": "ok",
                        "messages": rows,
                        "read_through_id": last,
                        "has_more": any(m["id"] > last for m in session.messages),
                    }
                session.cond.wait(min(1.0, max(0.05, deadline - time.time())))
        if hub.get(session.instance_id) is None:
            return {"state": "bridge_offline", "messages": [], "read_through_id": session.cursor, "has_more": False}
        return {"state": "idle", "messages": [], "read_through_id": session.cursor, "has_more": False}

    def send_reply(
        self,
        session_id: str,
        texts: list[str],
        reply_to: str = "",
        mention_user_ids: list[str] | None = None,
    ) -> dict:
        session = self._session(session_id)
        cleaned = [str(text).strip() for text in (texts or []) if str(text).strip()]
        cleaned = [text for text in cleaned if text][:3]
        if not cleaned:
            raise NativeMCPError("回复正文不能为空。")
        mentions = [str(item).strip() for item in (mention_user_ids or []) if str(item).strip()][:5]
        results = []
        for text in cleaned:
            data = hub.send_command(
                session.instance_id,
                "send",
                {
                    "group_id": session.group_id,
                    "text": text[:4000],
                    "reply_to": str(reply_to or ""),
                    "mention_user_ids": mentions,
                },
                timeout=45,
            )
            results.append(data)
            mentions = []
            reply_to = ""
        return {"sent": len(results), "results": results}

    # ---------------------------------------------------------- plugin tools

    def _inst(self, instance_id: str) -> dict:
        for item in store.load_instances():
            if str(item.get("id")) == str(instance_id):
                return item
        raise NativeMCPError("实例不存在。", 404)

    def memory_search(self, instance_id: str, query: str, k: int = 8, session_id: str = "", person_identity: str = "") -> dict:
        inst = self._inst(instance_id)
        query = str(query or "").strip()
        if not query:
            raise NativeMCPError("query 不能为空。")
        payload = {"query": query, "k": max(1, min(int(k or 8), 50))}
        if session_id:
            payload["session_id"] = str(session_id)
        if person_identity:
            payload["person_identity"] = str(person_identity)
        return memory.call_recall(inst, payload)

    def memory_relations(self, instance_id: str, limit: int = 40) -> dict:
        inst = self._inst(instance_id)
        return memory.call_relations(inst, limit=max(1, min(int(limit or 40), 200)))

    def styles_state(self, instance_id: str, person_key: str = "") -> dict:
        instance_id = str(instance_id or "")
        self._inst(instance_id)
        rows = styles.list_styles(instance_id)
        return {
            "styles": [
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "scope": row.get("scope"),
                    "person_key": row.get("person_key"),
                    "enabled": bool(row.get("enabled")),
                    "note": str(row.get("note") or "")[:2000],
                    "updated": row.get("updated"),
                }
                for row in rows
            ],
            "prompt": styles.style_prompt(instance_id, person_key) if person_key else "",
        }

    def mood_state(self, instance_id: str, person_key: str = "", platform: str = "qq") -> dict:
        instance_id = str(instance_id or "")
        self._inst(instance_id)
        data = mood.status(instance_id)
        if person_key:
            relation = mood.get_relation(instance_id, platform or "qq", str(person_key))
            data["relation"] = relation
        return data

    def presence_state(self, instance_id: str, person_key: str = "", limit: int = 20) -> dict:
        instance_id = str(instance_id or "")
        self._inst(instance_id)
        limit = max(1, min(int(limit or 20), 60))
        data = {
            "relations": presence.list_relations(instance_id, limit=limit),
            "loops": presence.list_loops(instance_id, limit=limit),
            "diaries": presence.list_diaries(instance_id, limit=min(limit, 20)),
            "rhythm": rhythm.current(instance_id),
        }
        if person_key:
            data["context"] = presence.context(instance_id, "qq", str(person_key))
        return data

    def rhythm_state(self, instance_id: str) -> dict:
        instance_id = str(instance_id or "")
        self._inst(instance_id)
        return rhythm.current(instance_id)

    def memes_state(self, instance_id: str) -> dict:
        inst = self._inst(instance_id)
        data = image_memes.overview(inst)
        return {
            "plugin_ready": data.get("plugin_ready"),
            "active_pack_id": data.get("active_pack_id"),
            "settings": data.get("settings"),
            "packs": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "image_count": item.get("image_count"),
                    "categories": item.get("categories"),
                    "active": item.get("active"),
                }
                for item in data.get("packs", [])
            ],
        }

    def inbox_state(self, platform: str = "", limit: int = 30, thread_id: str = "") -> dict:
        if thread_id:
            return {
                "thread": inbox.get_thread(thread_id),
                "messages": inbox.thread_messages(thread_id, limit=max(1, min(int(limit or 30), 100))),
            }
        return {
            "threads": inbox.list_threads(platform=platform, limit=max(1, min(int(limit or 30), 100))),
            "status": inbox.status(),
        }

    def bili_state(self, instance_id: str) -> dict:
        inst = self._inst(instance_id)
        return bili.status(inst)

    def douyin_state(self, instance_id: str) -> dict:
        inst = self._inst(instance_id)
        return consoles.call_status(inst, "douyin")

    def list_groups(self, instance_id: str) -> dict:
        data = hub.send_command(instance_id, "list_groups", timeout=25)
        groups = data.get("groups") if isinstance(data, dict) else []
        return {"instance_id": instance_id, "groups": groups or []}

    def status(self) -> dict:
        return status_all()


core = NativeMCPCore()


# -------------------------------------------------------------- tool schemas


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def tool_specs() -> list[dict]:
    sid = {"type": "string", "description": "session id，原样复制返回值。"}
    iid = {"type": "string", "description": "牧鱼实例 id。"}
    return [
        {
            "name": "native_status",
            "description": "查看管理器原生 MCP、AstrBot 桥和聊天会话状态。",
            "inputSchema": _schema({}),
        },
        {
            "name": "list_instances",
            "description": "列出可用的 AstrBot 实例。",
            "inputSchema": _schema({}),
        },
        {
            "name": "list_groups",
            "description": "通过指定实例的 AstrBot 平台读取 QQ 群列表。",
            "inputSchema": _schema({"instance_id": iid}, ["instance_id"]),
        },
        {
            "name": "start_chat_session",
            "description": "接管指定实例的指定 QQ 群：暂停 AstrBot 默认 LLM 回复，开始把群消息送入会话队列。",
            "inputSchema": _schema(
                {
                    "instance_id": iid,
                    "group_id": {"type": "string", "description": "QQ 群号。"},
                    "group_name": {"type": "string", "description": "可选群名。"},
                },
                ["instance_id", "group_id"],
            ),
        },
        {
            "name": "wait_chat_messages",
            "description": "等待接管群的新消息。处理完一批后，下次调用传 acknowledge_through_id=read_through_id。",
            "inputSchema": _schema(
                {
                    "session_id": sid,
                    "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 180, "default": 150},
                    "acknowledge_through_id": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 30},
                },
                ["session_id"],
            ),
        },
        {
            "name": "send_chat_reply",
            "description": "在接管群中发送 1–3 条纯文本气泡，可引用一条消息并 @ 群成员。",
            "inputSchema": _schema(
                {
                    "session_id": sid,
                    "texts": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                    "reply_to": {"type": "string", "description": "要引用的 QQ 消息 id，可为空。"},
                    "mention_user_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                },
                ["session_id", "texts"],
            ),
        },
        {
            "name": "stop_chat_session",
            "description": "停止接管并恢复该群的 AstrBot 默认回复。",
            "inputSchema": _schema({"session_id": sid}, ["session_id"]),
        },
        {
            "name": "memory_search",
            "description": "检索 LivingMemory 长期记忆。",
            "inputSchema": _schema(
                {
                    "instance_id": iid,
                    "query": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
                    "session_id": {"type": "string"},
                    "person_identity": {"type": "string"},
                },
                ["instance_id", "query"],
            ),
        },
        {
            "name": "memory_relations",
            "description": "读取 LivingMemory 参与人关系卡与情绪摘要。",
            "inputSchema": _schema(
                {"instance_id": iid, "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 40}},
                ["instance_id"],
            ),
        },
        {
            "name": "style_profiles",
            "description": "读取风格档案；传 person_key 时返回关系级风格提示。",
            "inputSchema": _schema(
                {"instance_id": iid, "person_key": {"type": "string"}},
                ["instance_id"],
            ),
        },
        {
            "name": "mood_state",
            "description": "读取每日心情、精力、社交电量和指定人的关系态度。",
            "inputSchema": _schema(
                {
                    "instance_id": iid,
                    "person_key": {"type": "string"},
                    "platform": {"type": "string", "default": "qq"},
                },
                ["instance_id"],
            ),
        },
        {
            "name": "presence_state",
            "description": "读取关系、未完成话题、日记和生活节律；可传 person_key 读取个人上下文。",
            "inputSchema": _schema(
                {
                    "instance_id": iid,
                    "person_key": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 60, "default": 20},
                },
                ["instance_id"],
            ),
        },
        {
            "name": "rhythm_state",
            "description": "读取当前生活节律、阶段和有效精力。",
            "inputSchema": _schema({"instance_id": iid}, ["instance_id"]),
        },
        {
            "name": "memes_state",
            "description": "读取表情包安装、分类和回复配图设置。",
            "inputSchema": _schema({"instance_id": iid}, ["instance_id"]),
        },
        {
            "name": "bili_status",
            "description": "读取该实例的 B 站账号、私信和主动行为状态。",
            "inputSchema": _schema({"instance_id": iid}, ["instance_id"]),
        },
        {
            "name": "douyin_status",
            "description": "读取该实例的抖音私信、监听和主动刷状态。",
            "inputSchema": _schema({"instance_id": iid}, ["instance_id"]),
        },
        {
            "name": "inbox_state",
            "description": "读取统一收件箱会话和最近消息。",
            "inputSchema": _schema(
                {
                    "platform": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
                    "thread_id": {"type": "string"},
                },
                [],
            ),
        },
    ]


def call_tool(name: str, args: dict) -> dict:
    args = args if isinstance(args, dict) else {}
    if name == "native_status":
        return core.status()
    if name == "list_instances":
        rows = []
        for item in store.load_instances():
            rows.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "running": bool(item.get("pid")),
                    "root": item.get("root"),
                }
            )
        return {"instances": rows}
    if name == "list_groups":
        return core.list_groups(str(args.get("instance_id") or ""))
    if name == "start_chat_session":
        return core.start_session(
            str(args.get("instance_id") or ""),
            str(args.get("group_id") or ""),
            str(args.get("group_name") or ""),
        )
    if name == "wait_chat_messages":
        return core.wait_messages(
            str(args.get("session_id") or ""),
            float(args.get("timeout_seconds") or 150),
            args.get("acknowledge_through_id"),
            int(args.get("limit") or 30),
        )
    if name == "send_chat_reply":
        return core.send_reply(
            str(args.get("session_id") or ""),
            args.get("texts") if isinstance(args.get("texts"), list) else [],
            str(args.get("reply_to") or ""),
            args.get("mention_user_ids") if isinstance(args.get("mention_user_ids"), list) else [],
        )
    if name == "stop_chat_session":
        return core.stop_session(str(args.get("session_id") or ""))
    if name == "memory_search":
        return core.memory_search(
            str(args.get("instance_id") or ""),
            str(args.get("query") or ""),
            int(args.get("k") or 8),
            str(args.get("session_id") or ""),
            str(args.get("person_identity") or ""),
        )
    if name == "memory_relations":
        return core.memory_relations(str(args.get("instance_id") or ""), int(args.get("limit") or 40))
    if name == "style_profiles":
        return core.styles_state(str(args.get("instance_id") or ""), str(args.get("person_key") or ""))
    if name == "mood_state":
        return core.mood_state(
            str(args.get("instance_id") or ""),
            str(args.get("person_key") or ""),
            str(args.get("platform") or "qq"),
        )
    if name == "presence_state":
        return core.presence_state(
            str(args.get("instance_id") or ""),
            str(args.get("person_key") or ""),
            int(args.get("limit") or 20),
        )
    if name == "rhythm_state":
        return core.rhythm_state(str(args.get("instance_id") or ""))
    if name == "memes_state":
        return core.memes_state(str(args.get("instance_id") or ""))
    if name == "bili_status":
        return core.bili_state(str(args.get("instance_id") or ""))
    if name == "douyin_status":
        return core.douyin_state(str(args.get("instance_id") or ""))
    if name == "inbox_state":
        return core.inbox_state(
            str(args.get("platform") or ""),
            int(args.get("limit") or 30),
            str(args.get("thread_id") or ""),
        )
    raise NativeMCPError(f"未知工具：{name}", 404)


INSTANCE_TOOLS = {
    "list_groups",
    "start_chat_session",
    "memory_search",
    "memory_relations",
    "style_profiles",
    "mood_state",
    "presence_state",
    "rhythm_state",
    "memes_state",
    "bili_status",
    "douyin_status",
}
SESSION_TOOLS = {"wait_chat_messages", "send_chat_reply", "stop_chat_session"}


def scoped_call_tool(name: str, args: dict, instance_id: str, label: str, service_status) -> dict:
    args = dict(args or {})
    if name == "native_status":
        return {
            "agent": label,
            "instance_id": instance_id,
            "service": service_status(),
            "bridges": [item for item in hub.snapshot() if item.get("instance_id") == instance_id],
            "sessions": [item for item in core.sessions_public() if item.get("instance_id") == instance_id],
            "tools": [item["name"] for item in tool_specs()],
        }
    if name == "list_instances":
        item = core._inst(instance_id)
        return {
            "instances": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "running": bool(item.get("pid")),
                    "root": item.get("root"),
                }
            ],
            "fixed": True,
        }
    if name in INSTANCE_TOOLS:
        requested = str(args.get("instance_id") or "")
        if requested and requested != instance_id:
            raise NativeMCPError(f"本端点固定绑定实例 {instance_id}，不能访问 {requested}。", 403)
        args["instance_id"] = instance_id
    if name in SESSION_TOOLS:
        session = core._session(str(args.get("session_id") or ""))
        if session.instance_id != instance_id:
            raise NativeMCPError("该聊天会话不属于本端点绑定的实例。", 403)
    return call_tool(name, args)


# ---------------------------------------------------------------- MCP server


class NativeMCPService:
    def __init__(self, agent: str, instance_id: str, port: int, token: str, label: str):
        self.agent = agent
        self.instance_id = instance_id
        self.port = int(port)
        self.token = token
        self.label = label
        self._lock = threading.RLock()
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.error = ""

    def _protocol(self, port: int) -> Server:
        protocol = Server(
            f"muyu-native-{self.agent}",
            version="1.0",
            instructions=(
                f"牧鱼原生 MCP（{self.label}）。本端点固定绑定实例 {self.instance_id}，"
                "不能读取或接管其他实例。你可以接管这个实例的 QQ 群并持续聊天；"
                "也可以读取该实例的 LivingMemory、风格档案、心情、关系、节律、日记、表情包、收件箱、B站和抖音数据。"
                "接管期间 AstrBot 默认 LLM 回复暂停，但它的插件事件钩子继续运行。"
                "每批消息处理完后，下次 wait_chat_messages 传 acknowledge_through_id=read_through_id。"
            ),
        )

        @protocol.list_tools()
        async def list_tools():
            return [
                types.Tool(
                    name=item["name"],
                    description=item["description"],
                    inputSchema=item["inputSchema"],
                )
                for item in tool_specs()
            ]

        @protocol.call_tool(validate_input=False)
        async def call(name: str, arguments: dict):
            try:
                if name == "wait_chat_messages":
                    result = await anyio.to_thread.run_sync(
                        lambda: scoped_call_tool(name, arguments, self.instance_id, self.label, self.status),
                    )
                else:
                    result = await anyio.to_thread.run_sync(
                        scoped_call_tool, name, arguments, self.instance_id, self.label, self.status
                    )
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                    structuredContent=result if isinstance(result, dict) else {"result": result},
                    isError=False,
                )
            except Exception as exc:
                payload = {"error": str(exc) or exc.__class__.__name__}
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
                    structuredContent=payload,
                    isError=True,
                )

        return protocol

    def _app(self, port: int):
        manager = StreamableHTTPSessionManager(
            self._protocol(port),
            json_response=True,
            stateless=True,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[f"127.0.0.1:{port}", f"localhost:{port}"],
                allowed_origins=[f"http://127.0.0.1:{port}", f"http://localhost:{port}"],
            ),
        )

        token = self.token

        class Endpoint:
            async def __call__(self, scope, receive, send):
                request = StarletteRequest(scope, receive)
                host = request.headers.get("host", "")
                if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                    return await JSONResponse({"error": "MCP host denied"}, status_code=403)(scope, receive, send)
                client = request.client.host if request.client else ""
                if client not in ("127.0.0.1", "::1", "testclient"):
                    return await JSONResponse({"error": "MCP local only"}, status_code=403)(scope, receive, send)
                auth = request.headers.get("authorization", "")
                expected = "Bearer " + token
                if not auth or not secrets.compare_digest(auth, expected):
                    return await JSONResponse({"error": "MCP unauthorized"}, status_code=401)(scope, receive, send)
                await manager.handle_request(scope, receive, send)

        @asynccontextmanager
        async def lifespan(app):
            async with manager.run():
                yield

        app = Starlette(routes=[Route("/mcp", endpoint=Endpoint())], lifespan=lifespan)
        return app

    def status(self) -> dict:
        running = bool(
            self.thread
            and self.thread.is_alive()
            and self.server is not None
            and not self.server.should_exit
        )
        return {
            "agent": self.agent,
            "label": self.label,
            "instance_id": self.instance_id,
            "port": self.port,
            "url": f"http://127.0.0.1:{self.port}/mcp",
            "token_saved": bool(self.token),
            "running": running,
            "error": self.error,
            "bridges": [item for item in hub.snapshot() if item.get("instance_id") == self.instance_id],
            "sessions": len([s for s in core.sessions_public() if s["instance_id"] == self.instance_id]),
        }

    def start(self) -> dict:
        with self._lock:
            if self.thread and self.thread.is_alive():
                return self.status()
            import socket

            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind(("127.0.0.1", self.port))
            except OSError:
                self.error = f"端口 {self.port} 已被占用。"
                return self.status()
            finally:
                probe.close()
            app = self._app(self.port)
            self.server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=self.port,
                    log_level="warning",
                    access_log=False,
                    lifespan="on",
                )
            )
            self.thread = threading.Thread(
                target=self.server.run,
                daemon=True,
                name=f"muyu-native-mcp-{self.agent}",
            )
            self.thread.start()
            self.error = ""
            deadline = time.time() + 8
            while time.time() < deadline:
                if self.thread.is_alive():
                    try:
                        with socket.create_connection(("127.0.0.1", self.port), timeout=0.3):
                            return self.status()
                    except OSError:
                        pass
                time.sleep(0.2)
            self.error = "MCP 服务未在 8 秒内监听端口。"
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            server = self.server
            thread = self.thread
            if server is not None:
                server.should_exit = True
            if thread is not None and thread.is_alive():
                thread.join(timeout=4)
            self.server = None
            self.thread = None
            self.error = ""
            return self.status()


services: dict[str, NativeMCPService] = {}


def rebuild_services() -> dict[str, NativeMCPService]:
    global services
    stop_all()
    built = {}
    for name in DEFAULT_AGENTS:
        cfg = agent_config(name)
        built[name] = NativeMCPService(
            name,
            cfg["instance_id"],
            cfg["port"],
            cfg["token"],
            cfg["label"],
        )
    services = built
    return services


def start_all() -> dict:
    for service in services.values():
        service.start()
    return status_all()


def stop_all() -> dict:
    for service in list(services.values()):
        service.stop()
    return status_all()


def status_all() -> dict:
    return {
        **public_state(),
        "services": {name: service.status() for name, service in services.items()},
        "bridges": hub.snapshot(),
        "sessions": core.sessions_public(),
    }



# --------------------------------------------------------------- agent setup


def _codex_block(url: str, token: str) -> str:
    return (
        CODEX_BEGIN
        + "\n"
        + "[mcp_servers.muyu_native]\n"
        + f"url = {json.dumps(url)}\n"
        + f"http_headers = {{ Authorization = {json.dumps('Bearer ' + token)} }}\n"
        + "tool_timeout_sec = 240\n"
        + CODEX_END
        + "\n"
    )


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()


def install_codex(home: Path | None = None) -> dict:
    cfg = agent_config("codex")
    block = _codex_block(cfg["url"], cfg["token"])
    home = Path(home) if home is not None else codex_home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.toml"
    with _state_lock:
        original = path.read_bytes() if path.exists() else b""
        text = original.decode("utf-8-sig").replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))
        start = text.find(CODEX_BEGIN)
        if start >= 0:
            end = text.find(CODEX_END, start)
            if end < 0:
                raise NativeMCPError("Codex 配置中的原生 MCP 标记不完整。", 409)
            end += len(CODEX_END)
            if text[start:end].strip() == block.strip():
                return {"installed": True, "changed": False, "path": str(path)}
            base = text[:start].rstrip() + chr(10) + text[end:].lstrip(chr(10))
        else:
            if "[mcp_servers.muyu_native]" in text:
                raise NativeMCPError("Codex 已有 muyu_native 但没有牧鱼标记，未覆盖。", 409)
            base = text
        try:
            before = tomllib.loads(base) if base.strip() else {}
        except (ValueError, UnicodeError):
            raise NativeMCPError("Codex 配置无法解析，未修改。", 409) from None
        updated = ((base.rstrip() + chr(10) + chr(10)) if base.strip() else "") + block
        try:
            after = tomllib.loads(updated)
        except (ValueError, UnicodeError):
            raise NativeMCPError("生成的 Codex 配置无法解析。", 409) from None
        entry = tomllib.loads(block)["mcp_servers"]["muyu_native"]
        expected = dict(before)
        expected["mcp_servers"] = dict(before.get("mcp_servers") or {})
        expected["mcp_servers"]["muyu_native"] = entry
        if after != expected:
            raise NativeMCPError("无法安全合并 Codex 配置。", 409)
        if original:
            backup = home / "backups" / f"config-before-muyu-native-{time.time_ns()}.toml"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(original)
        tmp = path.with_suffix(".toml.muyu.tmp")
        tmp.write_bytes(updated.encode("utf-8"))
        os.replace(tmp, path)
    return {"installed": True, "changed": True, "path": str(path)}


def dsh_home() -> Path:
    return Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh")).expanduser()


def dsh_patch_path() -> Path:
    return dsh_home() / "profiles" / DSH_PROFILE / "cordis.patch.yml"


def _dsh_block(url: str) -> str:
    return "\n".join(
        [
            DSH_BEGIN,
            "- insert:",
            "    - id: mcp-muyu-native",
            "      name: '@deepseek-ai/dsh-mcp-client'",
            "      config:",
            "        serverName: muyu_native",
            "        transport: streamable-http",
            f"        url: {json.dumps(url)}",
            "        headers:",
            "          Authorization: !!js '`Bearer ${process.env.MUYU_NATIVE_MCP_TOKEN}`'",
            "        toolCallTimeoutMs: 240000",
            "        failOnStartupError: true",
            DSH_END,
            "",
        ]
    )


def install_dsh() -> dict:
    cfg = agent_config("dsh")
    block = _dsh_block(cfg["url"])
    path = dsh_patch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _state_lock:
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        start = original.find(DSH_BEGIN)
        if start >= 0:
            end = original.find(DSH_END, start)
            if end < 0:
                raise NativeMCPError("DSH 配置中的原生 MCP 标记不完整。", 409)
            end += len(DSH_END)
            updated = original[:start].rstrip() + "\n\n" + block + original[end:].lstrip("\n")
        else:
            if "id: mcp-muyu-native" in original:
                raise NativeMCPError("DSH 已有 muyu_native 但没有牧鱼标记。", 409)
            updated = original.rstrip() + "\n\n" + block
        if updated == original:
            return {"installed": True, "changed": False, "path": str(path), "restart_required": True}
        backup = path.parent / "backups" / f"cordis.patch.before-muyu-native-{time.time_ns()}.yml"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(original, encoding="utf-8")
        tmp = path.with_suffix(".yml.muyu.tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, path)
    return {"installed": True, "changed": True, "path": str(path), "restart_required": True}


def dsh_env() -> dict:
    cfg = agent_config("dsh")
    return {
        "MUYU_NATIVE_MCP_TOKEN": cfg["token"],
        "MUYU_NATIVE_MCP_URL": cfg["url"],
    }


def agent_status() -> dict:
    codex_path = codex_home() / "config.toml"
    codex_text = ""
    try:
        codex_text = codex_path.read_text(encoding="utf-8-sig") if codex_path.exists() else ""
    except OSError:
        pass
    dsh_path = dsh_patch_path()
    dsh_text = ""
    try:
        dsh_text = dsh_path.read_text(encoding="utf-8") if dsh_path.exists() else ""
    except OSError:
        pass
    codex_cfg = agent_config("codex")
    dsh_cfg = agent_config("dsh")
    return {
        "codex": {
            "installed": "[mcp_servers.muyu_native]" in codex_text,
            "path": str(codex_path),
            "instance_id": codex_cfg["instance_id"],
            "url": codex_cfg["url"],
            "label": "Codex",
        },
        "dsh": {
            "installed": "id: mcp-muyu-native" in dsh_text,
            "path": str(dsh_path),
            "instance_id": dsh_cfg["instance_id"],
            "url": dsh_cfg["url"],
            "label": "DSH",
        },
    }


# ---------------------------------------------------------- bridge install


def _bridge_config_path(inst: dict) -> Path:
    return Path(inst["root"]) / "data" / "plugin_data" / PLUGIN_ID / "config.json"


def bridge_installed(inst: dict) -> bool:
    root = Path(inst["root"])
    return (root / "data" / "plugins" / PLUGIN_ID / "main.py").is_file()


def install_bridge(instance_id: str, manager_url: str) -> dict:
    inst = core._inst(instance_id)
    if not PLUGIN_SOURCE.is_dir():
        raise NativeMCPError("管理器缺少 muyu_mcp_bridge 插件源。", 500)
    dest = Path(inst["root"]) / "data" / "plugins" / PLUGIN_ID
    if dest.exists():
        pycache = dest / "__pycache__"
        if pycache.exists():
            shutil.rmtree(pycache, ignore_errors=True)
        shutil.copytree(
            PLUGIN_SOURCE,
            dest,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    else:
        shutil.copytree(
            PLUGIN_SOURCE,
            dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    config = {
        "instance_id": instance_id,
        "manager_url": str(manager_url).rstrip("/"),
        "bridge_token": load_state().get("bridge_token", ""),
        "updated_at": _now(),
    }
    config_path = _bridge_config_path(inst)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    store.write_json(config_path, config)
    return {
        "installed": True,
        "instance_id": instance_id,
        "path": str(dest),
        "config": {
            "manager_url": config["manager_url"],
            "bridge_token_saved": bool(config["bridge_token"]),
        },
        "reload_required": True,
    }


def reload_bridge(instance_id: str) -> dict:
    inst = core._inst(instance_id)
    try:
        result = dashboard.call(
            inst,
            "POST",
            f"plugins/{PLUGIN_ID}/reload",
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        raise NativeMCPError(f"重载桥插件失败：{exc}。可重启该 AstrBot 实例后再试。", 502) from None
    return {"reloaded": True, "instance_id": instance_id, "result": result}


def bridge_status() -> dict:
    rows = []
    for inst in store.load_instances():
        rows.append(
            {
                "instance_id": inst.get("id"),
                "name": inst.get("name"),
                "installed": bridge_installed(inst),
                "config": str(_bridge_config_path(inst)),
                "connected": hub.get(str(inst.get("id") or "")) is not None,
            }
        )
    return {"instances": rows, "connected": hub.snapshot()}


# --------------------------------------------------------------- bridge WS


@router.websocket("/api/mcp-native/bridge/ws")
async def bridge_ws(websocket: WebSocket, instance_id: str = ""):
    state = load_state()
    token = websocket.headers.get("authorization", "")
    if not token.startswith("Bearer ") or not secrets.compare_digest(
        token[7:], state.get("bridge_token", "")
    ):
        await websocket.close(code=4401)
        return
    if websocket.client and websocket.client.host not in ("127.0.0.1", "::1"):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    instance_id = str(instance_id or "").strip()
    conn = BridgeConnection(
        instance_id=instance_id,
        websocket=websocket,
        loop=asyncio.get_running_loop(),
    )
    if instance_id:
        hub.register(conn)
    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                continue
            kind = payload.get("type")
            conn.last_seen = time.time()
            if kind == "hello":
                instance_id = str(payload.get("instance_id") or instance_id).strip()
                conn.instance_id = instance_id
                conn.self_id = str(payload.get("self_id") or "")
                conn.platform_id = str(payload.get("platform_id") or "")
                conn.nickname = str(payload.get("nickname") or "")
                if instance_id:
                    hub.register(conn)
                await websocket.send_json({"type": "hello_ack", "instance_id": instance_id})
                if instance_id:
                    asyncio.create_task(asyncio.to_thread(core.restore_takeover, instance_id))
            elif kind == "event":
                core.ingest_event(conn.instance_id, payload.get("event") or {})
            elif kind == "response":
                hub.resolve(str(payload.get("request_id") or ""), payload)
            elif kind == "groups":
                conn.groups = payload.get("groups") if isinstance(payload.get("groups"), list) else conn.groups
            elif kind == "ping":
                await websocket.send_json({"type": "pong", "time": time.time()})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.unregister(conn.instance_id, websocket)


# ---------------------------------------------------------------- API routes


def _guard(fn, *args, **kwargs):
    try:
        return _ok(fn(*args, **kwargs))
    except NativeMCPError as exc:
        return _fail(str(exc), getattr(exc, "status", 400))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"原生 MCP 处理失败：{exc}", 500)


@router.get("/api/mcp-native/status")
def api_status():
    return _ok({"services": status_all(), "bridge": bridge_status(), "agents": agent_status()})


@router.post("/api/mcp-native/config")
def api_config(payload: dict = Body(...)):
    try:
        return _ok(set_config(bool(payload.get("enabled")), int(payload.get("port") or DEFAULT_PORT)))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), 400)


@router.post("/api/mcp-native/service/start")
def api_start():
    return _ok(start_all())


@router.post("/api/mcp-native/service/stop")
def api_stop():
    return _ok(stop_all())


@router.post("/api/mcp-native/tokens/rotate")
def api_rotate():
    return _ok(rotate_tokens())


@router.get("/api/mcp-native/tools")
def api_tools():
    return _ok({"tools": tool_specs()})


@router.get("/api/mcp-native/bridge")
def api_bridge():
    return _ok(bridge_status())


@router.post("/api/mcp-native/bridge/install")
def api_bridge_install(request: Request, payload: dict = Body(...)):
    instance_id = str(payload.get("instance_id") or "")
    manager_url = str(payload.get("manager_url") or "")
    if not manager_url and request is not None:
        manager_url = str(request.base_url).rstrip("/")
    return _guard(install_bridge, instance_id, manager_url)


@router.post("/api/mcp-native/bridge/reload")
def api_bridge_reload(payload: dict = Body(...)):
    return _guard(reload_bridge, str(payload.get("instance_id") or ""))


@router.get("/api/mcp-native/sessions")
def api_sessions():
    return _ok({"sessions": core.sessions_public()})


@router.post("/api/mcp-native/sessions/start")
def api_session_start(payload: dict = Body(...)):
    return _guard(
        core.start_session,
        str(payload.get("instance_id") or ""),
        str(payload.get("group_id") or ""),
        str(payload.get("group_name") or ""),
        str(payload.get("platform_id") or ""),
    )


@router.post("/api/mcp-native/sessions/{session_id}/stop")
def api_session_stop(session_id: str):
    return _guard(core.stop_session, session_id)


@router.get("/api/mcp-native/groups")
def api_groups(instance_id: str = ""):
    return _guard(core.list_groups, instance_id)


@router.get("/api/mcp-native/agents")
def api_agents():
    return _ok(agent_status())


@router.post("/api/mcp-native/agents/install")
def api_agent_install(payload: dict = Body(...)):
    agent = str(payload.get("agent") or "")
    if agent == "codex":
        return _guard(install_codex)
    if agent == "dsh":
        return _guard(install_dsh)
    return _fail("未知 Agent。", 400)


def agent_prompt(agent: str = "") -> str:
    name = str(agent or "").strip().lower()
    if name in ("dsh", "codex"):
        cfg = agent_config(name)
        return (
            f"你是 {cfg['label']}，通过牧鱼原生 MCP 接管实例 {cfg['instance_id']} 的 QQ 群。"
            "这个端点是固定绑定的，不要尝试访问其他实例。"
            "先 list_instances 和 list_groups，再 start_chat_session。"
            "循环 wait_chat_messages；处理完一批后下次等待传 acknowledge_through_id=read_through_id。"
            "回复前可按需调用 memory_search、style_profiles、mood_state、presence_state、rhythm_state，"
            "把长期记忆、人物关系、心情和风格当成上下文，不要把工具字段原样发到群里。"
            "用 send_chat_reply 发送 1–3 条短气泡；用户停止时 stop_chat_session。"
            "idle 不是结束，继续等待；接管期间 AstrBot 默认 LLM 回复暂停，但插件钩子继续运行。"
        )
    dsh = agent_config("dsh")
    codex = agent_config("codex")
    return (
        f"DSH 固定接大肥鱼实例 {dsh['instance_id']}（{dsh['url']}）；"
        f"Codex 固定接龙娘实例 {codex['instance_id']}（{codex['url']}）。"
        "各端点已做服务端实例锁定，不能跨实例。"
    )


@router.get("/api/mcp-native/prompt")
def api_prompt(agent: str = ""):
    return _ok({"prompt": agent_prompt(agent), "dsh": agent_prompt("dsh"), "codex": agent_prompt("codex")})

services = rebuild_services()
