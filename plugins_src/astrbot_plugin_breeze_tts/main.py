"""牧鱼语音插件：注册 Breeze TTS 提供商，并在语音发不出去时自动改发文字。

回复转语音的开关、触发概率、双输出等由 AstrBot 的
provider_tts_settings 控制，管理器「语音」页面会写好这些配置。
"""

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain, Record
from astrbot.api.star import Context, Star

from .provider import ensure_registered


def _record_text(chain) -> str:
    """取出语音消息段里带的原文，用于发送失败时改发文字。"""
    for comp in getattr(chain, "chain", chain) or []:
        if isinstance(comp, Record):
            text = str(getattr(comp, "text", "") or "").strip()
            if text:
                return text
    return ""


class BreezeTTSPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        ensure_registered()
        logger.info("[Breeze TTS] 语音发送失败自动转文字已启用")

    @filter.on_decorating_result()
    async def voice_text_fallback(self, event: AstrMessageEvent):
        """给本次消息的发送方法套一层：语音发送失败时改发对应文字。"""
        if getattr(event, "_breeze_voice_fallback", False):
            return
        original_send = event.send

        async def send_with_fallback(chain):
            try:
                return await original_send(chain)
            except Exception:
                text = _record_text(chain)
                if not text:
                    raise
                logger.warning(
                    "[Breeze TTS] 语音发送失败，自动改发文字：%s",
                    text[:40],
                )
                await original_send(MessageChain([Plain(text)]))
                return None

        event.send = send_with_fallback
        event._breeze_voice_fallback = True
