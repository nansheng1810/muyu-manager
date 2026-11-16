"""牧鱼原生 MCP 的 AstrBot 侧薄桥。

职责只有三件事：
1. 把接管群的新消息推给管理器；
2. 在接管群暂停 AstrBot 默认 LLM 回复，但保留其他插件的事件钩子；
3. 执行管理器的纯文本发送/接管/释放命令。

默认 LLM 是通过 event.should_call_llm(False) 关闭的，不调用 stop_event，
因此 LivingMemory、心情、拟人、在场等插件仍能观察到消息。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain, Reply
from astrbot.api.star import Context, Star
from astrbot.core.message.message_event_result import MessageChain

PLUGIN_ID = "muyu_mcp_bridge"
MANAGER_DEFAULT = "http://127.0.0.1:7311"


class MuyuMCPBridge(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context, config)
        self.root = Path(__file__).resolve().parents[3]
        self.config_path = self.root / "data" / "plugin_data" / PLUGIN_ID / "config.json"
        self.active: dict[str, str] = {}
        self.umos: dict[str, str] = {}
        self.platform_ids: dict[str, str] = {}
        self.ws = None
        self.task: asyncio.Task | None = None
        self._last_hello = ""
        try:
            self.task = asyncio.get_running_loop().create_task(self._run())
        except RuntimeError:
            pass

    def _config(self) -> dict:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _ws_url(self, manager_url: str) -> str:
        base = str(manager_url or MANAGER_DEFAULT).rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        return base + "/api/mcp-native/bridge/ws"

    async def _run(self) -> None:
        delay = 3
        while True:
            cfg = self._config()
            token = str(cfg.get("bridge_token") or "")
            instance_id = str(cfg.get("instance_id") or "")
            manager_url = str(cfg.get("manager_url") or MANAGER_DEFAULT)
            connected = False
            if not token or not instance_id:
                await asyncio.sleep(3)
                continue
            hello = f"{manager_url}|{instance_id}|{token[:8]}"
            try:
                async with websockets.connect(
                    self._ws_url(manager_url),
                    additional_headers={"Authorization": "Bearer " + token},
                    ping_interval=20,
                    ping_timeout=20,
                    open_timeout=6,
                    max_size=8 * 1024 * 1024,
                ) as ws:
                    self.ws = ws
                    platform_id = self._platform_id()
                    await ws.send(
                        json.dumps(
                            {
                                "type": "hello",
                                "instance_id": instance_id,
                                "platform_id": platform_id,
                                "self_id": self._self_id(),
                                "nickname": "",
                            },
                            ensure_ascii=False,
                        )
                    )
                    self._last_hello = hello
                    connected = True
                    delay = 3
                    logger.info("[muyu_mcp_bridge] 已连接管理器 %s", manager_url)
                    async for raw in ws:
                        try:
                            payload = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(payload, dict) and payload.get("type") == "command":
                            await self._command(ws, payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if delay <= 3:
                    logger.warning("[muyu_mcp_bridge] 连接管理器失败：%s", exc)
                delay = min(30, max(3, delay * 2))
            finally:
                self.ws = None
                # 管理器断线时立即恢复 AstrBot 默认回复，避免机器人变哑。
                if self.active:
                    logger.warning("[muyu_mcp_bridge] 与管理器断开，恢复默认回复")
                self.active.clear()
                self.umos.clear()
            await asyncio.sleep(3 if connected else delay)

    def _platform_id(self) -> str:
        fallback = ""
        try:
            for platform in self.context.platform_manager.platform_insts:
                meta = platform.meta()
                if not meta or not meta.id:
                    continue
                if not fallback:
                    fallback = str(meta.id)
                try:
                    client = platform.get_client()
                except Exception:
                    client = None
                if client is not None and hasattr(client, "call_action"):
                    return str(meta.id)
                name = str(getattr(meta, "name", "") or "").lower()
                if name == "aiocqhttp" or "onebot" in name:
                    return str(meta.id)
        except Exception:  # noqa: BLE001
            pass
        return fallback or "aiocqhttp"

    def _self_id(self) -> str:
        try:
            for platform in self.context.platform_manager.platform_insts:
                meta = platform.meta()
                name = str(getattr(meta, "name", "") or "").lower() if meta else ""
                if name != "aiocqhttp" and "onebot" not in name:
                    continue
                client = platform.get_client()
                value = getattr(client, "self_id", None)
                if isinstance(value, (str, int)) and str(value).isdigit():
                    return str(value)
        except Exception:  # noqa: BLE001
            pass
        return ""

    async def _command(self, ws, payload: dict) -> None:
        request_id = str(payload.get("request_id") or "")
        action = str(payload.get("action") or "")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        result: dict = {}
        ok = True
        error = ""
        try:
            if action == "takeover":
                group_id = str(data.get("group_id") or "")
                platform_id = self._platform_id()
                if not group_id:
                    raise ValueError("group_id 不能为空")
                self.active[group_id] = platform_id
                self.platform_ids[group_id] = platform_id
                result = {"group_id": group_id, "platform_id": platform_id}
            elif action == "release":
                group_id = str(data.get("group_id") or "")
                self.active.pop(group_id, None)
                self.umos.pop(group_id, None)
                result = {"group_id": group_id, "released": True}
            elif action == "send":
                result = await self._send(data)
            elif action == "list_groups":
                result = {"groups": await self._list_groups()}
            elif action == "ping":
                result = {"time": time.time()}
            else:
                raise ValueError("未知命令")
        except Exception as exc:  # noqa: BLE001
            ok = False
            error = str(exc) or exc.__class__.__name__
        try:
            await ws.send(
                json.dumps(
                    {
                        "type": "response",
                        "request_id": request_id,
                        "ok": ok,
                        "data": result,
                        "error": error,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass

    async def _send(self, data: dict) -> dict:
        group_id = str(data.get("group_id") or "")
        text = str(data.get("text") or "").strip()
        reply_to = str(data.get("reply_to") or "")
        mentions = data.get("mention_user_ids") if isinstance(data.get("mention_user_ids"), list) else []
        if not group_id or not text:
            raise ValueError("群号或正文为空")
        platform_id = self._platform_id()
        umo = self.umos.get(group_id) or f"{platform_id}:GroupMessage:{group_id}"
        chain = []
        if reply_to:
            chain.append(Reply(id=reply_to))
        for uid in mentions[:5]:
            uid = str(uid).strip()
            if uid.isdigit():
                chain.append(At(qq=uid))
        chain.append(Plain(text[:4000]))
        sent = await self.context.send_message(umo, MessageChain(chain=chain))
        if sent is False:
            raise RuntimeError("AstrBot 平台没有找到目标会话")
        return {"group_id": group_id, "umo": umo, "sent": True}

    async def _list_groups(self) -> list[dict]:
        rows: list[dict] = []
        seen: set[str] = set()
        for platform in self.context.platform_manager.platform_insts:
            try:
                meta = platform.meta()
                client = platform.get_client()
                groups = await asyncio.wait_for(client.call_action("get_group_list"), timeout=12)
            except Exception:
                continue
            platform_id = str(getattr(meta, "id", "") or "")
            for item in groups or []:
                if not isinstance(item, dict):
                    continue
                gid = str(item.get("group_id") or "")
                if not gid or gid in seen:
                    continue
                seen.add(gid)
                rows.append(
                    {
                        "group_id": gid,
                        "group_name": str(item.get("group_name") or gid),
                        "member_count": item.get("member_count") or 0,
                        "platform_id": platform_id,
                    }
                )
        return rows

    @filter.on_astrbot_loaded()
    async def on_loaded(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())
            logger.info("[muyu_mcp_bridge] 后台连接任务已启动")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize)
    async def on_message(self, event: AstrMessageEvent) -> None:
        if not self.active or self.ws is None:
            return
        group_id = str(event.get_group_id() or "")
        if group_id not in self.active:
            return
        try:
            await self._forward(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[muyu_mcp_bridge] 转发消息失败：%s", exc)
        # 只关默认 LLM；插件钩子继续跑，记忆/心情/拟人仍能观察消息。
        event.should_call_llm(False)

    async def _forward(self, event: AstrMessageEvent) -> None:
        ws = self.ws
        if ws is None:
            return
        self.umos[str(event.get_group_id() or "")] = event.unified_msg_origin
        segments = []
        for seg in event.get_messages() or []:
            try:
                item = await seg.to_dict()
                if isinstance(item, dict):
                    segments.append(item)
            except Exception:
                continue
        payload = {
            "kind": "message",
            "group_id": str(event.get_group_id() or ""),
            "sender_id": str(event.get_sender_id() or ""),
            "sender_name": str(event.get_sender_name() or ""),
            "self_id": str(event.get_self_id() or ""),
            "message_id": str(getattr(event.message_obj, "message_id", "") or ""),
            "text": str(event.message_str or ""),
            "segments": segments[:20],
            "time": float(getattr(event, "created_at", time.time()) or time.time()),
        }
        await ws.send(json.dumps({"type": "event", "event": payload}, ensure_ascii=False))

    async def terminate(self) -> None:
        task = self.task
        self.task = None
        ws = self.ws
        self.ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if task is not None:
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2)
            except Exception:
                pass
        self.active.clear()
