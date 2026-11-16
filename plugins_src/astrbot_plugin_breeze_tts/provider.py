"""驰风 Breeze TTS 的 AstrBot 提供商适配器。

Breeze 接口使用 multipart/form-data 和 X-API-Key，和内置 OpenAI TTS
（JSON + Bearer）不兼容，所以这里单独实现一个 text_to_speech 适配器。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import httpx

from astrbot import logger
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import TTSProvider
from astrbot.core.provider.register import provider_cls_map, register_provider_adapter
from astrbot.core.utils.astrbot_path import get_astrbot_data_path, get_astrbot_temp_path
from astrbot.core.utils.datetime_utils import generate_timestamp_id

PROVIDER_ID = "breeze_tts"
DEFAULT_API_BASE = "https://tts.chifengvtc.com"
DEFAULT_CACHE_ENTRIES = 200
DEFAULT_CACHE_MB = 200
DEFAULT_MOOD_MANAGER = "http://127.0.0.1:7311"
MOOD_DECAY_LIMIT = 300
MOOD_LABELS = {
    "calm": "平静",
    "happy": "开心",
    "low": "低落",
    "annoyed": "烦躁",
    "angry": "生气",
}
# 每日心情用 calm/happy/low/annoyed/angry；
# group_chat_plus 用中文情绪名。两套都映射成一句语气提示。
DEFAULT_MOOD_TONES = {
    "calm": "用平常、放松的语气说话，像平时聊天一样。",
    "happy": "语气轻快、明亮，带一点笑意，句尾可以微微上扬。",
    "low": "语气低落、柔软，语速慢一点，不要强行热情。",
    "annoyed": "语气有点不耐烦，句子短一些，语速稍快。",
    "angry": "语气冷淡、克制，不要讨好对方。",
    "开心": "语气轻快、明亮，带一点笑意。",
    "难过": "语气低沉、柔软，语速慢一点。",
    "生气": "语气偏冷、有压迫感，句子短。",
    "惊讶": "语气上扬，带一点吃惊。",
    "疑惑": "语气带疑问，尾音微微上扬。",
    "无语": "语气平淡，略带无奈。",
    "兴奋": "语气高扬、有活力，节奏快一点。",
}


def _cache_dir() -> Path:
    """语音缓存目录，和方案里的插件数据目录保持一致，便于管理器统计。"""
    return (
        Path(get_astrbot_data_path())
        / "plugin_data"
        / "astrbot_plugin_breeze_tts"
        / "tts_cache"
    )

_ERROR_HINTS = {
    401: "语音服务鉴权失败：请检查 API Key 是否填写正确",
    429: "语音服务忙碌：上一次语音还在生成，或已超过 60 次/分钟，请稍后重试",
    502: "语音服务隧道未启动（502）：请在服务器重新运行 start.cmd",
}


def ensure_registered() -> None:
    """注册提供商适配器；插件被重复加载时保持幂等。"""
    if PROVIDER_ID in provider_cls_map:
        return
    register_provider_adapter(
        PROVIDER_ID,
        "驰风 Breeze 语音",
        provider_type=ProviderType.TEXT_TO_SPEECH,
        provider_display_name="驰风 Breeze 语音",
    )(ProviderBreezeTTS)


class ProviderBreezeTTS(TTSProvider):
    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)
        self.api_base = str(
            provider_config.get("api_base") or DEFAULT_API_BASE
        ).rstrip("/")
        self.api_key = str(provider_config.get("api_key") or "").strip()
        self.instruction = str(provider_config.get("instruction") or "").strip()
        self.ref_audio = str(provider_config.get("ref_audio") or "").strip()
        self.ref_text = str(provider_config.get("ref_text") or "").strip()
        self.cfg_scale = _number(provider_config.get("cfg_scale"), 4.0)
        self.seed = int(_number(provider_config.get("seed"), 42))
        self.timeout = int(_number(provider_config.get("timeout"), 300))
        self.cache_enabled = _truthy(provider_config.get("cache_enabled"), True)
        self.cache_max_entries = max(
            1, int(_number(provider_config.get("cache_max_entries"), DEFAULT_CACHE_ENTRIES))
        )
        self.cache_max_mb = max(
            10, int(_number(provider_config.get("cache_max_mb"), DEFAULT_CACHE_MB))
        )
        self.mood_sync_enabled = _truthy(
            provider_config.get("mood_sync_enabled"), False
        )
        self.mood_group_enabled = _truthy(
            provider_config.get("mood_group_enabled"), True
        )
        self.mood_manager_url = str(
            provider_config.get("mood_manager_url") or DEFAULT_MOOD_MANAGER
        ).rstrip("/")
        self.mood_instance_id = str(
            provider_config.get("mood_instance_id") or ""
        ).strip()
        self.mood_cache_seconds = max(
            5, int(_number(provider_config.get("mood_cache_seconds"), 20))
        )
        self.mood_tones = _mood_tones(provider_config.get("mood_tones"))
        self._mood_cache: tuple[float, dict] | None = None
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=max(30, self.timeout))
        self.set_model(str(provider_config.get("model") or "breeze-tts"))
        if not self.api_key:
            logger.warning("[Breeze TTS] 尚未配置 API Key，语音请求会失败")

    async def get_audio(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            raise ValueError("Breeze TTS 收到空文本")

        instruction = await self._effective_instruction()
        cached = self._cache_lookup(text, instruction)
        if cached:
            path = self._emit_cache(cached)
            if path:
                return path

        if not self.api_key:
            raise ValueError("Breeze TTS 尚未配置 API Key")

        data = {"text": text}
        if instruction:
            data["instruction"] = instruction
        if self.ref_text:
            data["ref_text"] = self.ref_text
        data["cfg_scale"] = str(self.cfg_scale)
        data["seed"] = str(self.seed)

        files = None
        if self.ref_audio:
            path = Path(self.ref_audio).expanduser()
            if path.is_file():
                files = {
                    "ref_audio": (
                        path.name,
                        path.read_bytes(),
                        "application/octet-stream",
                    )
                }
            else:
                logger.warning("[Breeze TTS] 参考音频不存在：%s", path)

        async with self._lock:
            cached = self._cache_lookup(text, instruction)
            if cached:
                path = self._emit_cache(cached)
                if path:
                    return path
            try:
                response = await self._client.post(
                    f"{self.api_base}/v1/audio/speech/wav",
                    headers={"X-API-Key": self.api_key},
                    data=data,
                    files=files,
                )
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"语音生成超时（{self.timeout} 秒）：长文本可稍后再试"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"无法连接语音服务：{exc}") from exc

        if response.status_code != 200:
            hint = _ERROR_HINTS.get(response.status_code, "")
            detail = response.text.strip()[:160]
            message = f"Breeze TTS HTTP {response.status_code}"
            if hint:
                message += f"：{hint}"
            if detail:
                message += f"（{detail}）"
            raise RuntimeError(message)

        audio = response.content
        if not audio:
            raise RuntimeError("Breeze TTS 返回了空音频")

        temp_dir = get_astrbot_temp_path()
        os.makedirs(temp_dir, exist_ok=True)
        path = os.path.join(temp_dir, f"breeze_tts_{generate_timestamp_id()}.wav")
        with open(path, "wb") as file:
            file.write(audio)
        self._store_cache(text, audio, instruction)
        logger.info("[Breeze TTS] 已生成语音（%s 字节）：%s", len(audio), path)
        return path

    async def _effective_instruction(self) -> str:
        """基础音色描述 + 当前心情/情绪的语气提示。"""
        if not self.mood_sync_enabled:
            return self.instruction
        mood = await self._current_mood()
        tone = str((mood or {}).get("tone") or "").strip()
        if not tone:
            return self.instruction
        logger.info(
            "[Breeze TTS] 情绪联动：%s（%s）",
            mood.get("label") or mood.get("mood") or "",
            mood.get("source") or "",
        )
        return "\n".join(part for part in (self.instruction, tone) if part)

    async def _current_mood(self) -> dict:
        """优先读群聊情绪，其次读每日心情；结果短时缓存，避免每条语音都等接口。"""
        now = time.time()
        if self._mood_cache and self._mood_cache[0] > now:
            return self._mood_cache[1]
        mood = self._group_mood() or await self._manager_mood()
        if mood:
            self._mood_cache = (now + self.mood_cache_seconds, mood)
            return mood
        # 没读到心情也短暂缓存，避免管理器不可用时每条语音都等超时
        self._mood_cache = (now + min(self.mood_cache_seconds, 10), {})
        return {}

    def _group_mood(self) -> dict | None:
        """读取 group_chat_plus 的 MoodTracker（同进程，取最近活跃的非平静情绪）。"""
        if not self.mood_group_enabled:
            return None
        try:
            from astrbot.core.star import star_registry
        except Exception:
            return None
        try:
            stars = list(star_registry)
        except Exception:
            return None
        for star in stars:
            if str(getattr(star, "name", "")) != "astrbot_plugin_group_chat_plus":
                continue
            tracker = getattr(getattr(star, "star_cls", None), "mood_tracker", None)
            moods = getattr(tracker, "moods", None)
            if not isinstance(moods, dict):
                return None
            now = time.time()
            latest = None
            for item in list(moods.values()):
                if not isinstance(item, dict):
                    continue
                label = str(item.get("mood") or "").strip()
                if label in ("", "平静"):
                    continue
                try:
                    updated = float(item.get("last_update") or 0)
                except (TypeError, ValueError):
                    continue
                if now - updated > MOOD_DECAY_LIMIT:
                    continue
                if latest is None or updated > latest[0]:
                    latest = (updated, label, item.get("intensity"))
            if not latest:
                return None
            tone = self.mood_tones.get(latest[1], "")
            if not tone:
                return None
            return {
                "source": "group",
                "mood": latest[1],
                "label": latest[1],
                "intensity": _number(latest[2], 0),
                "tone": tone,
            }
        return None

    async def _manager_mood(self) -> dict | None:
        """从牧鱼管理器读取该实例的每日心情。"""
        if not self.mood_instance_id:
            return None
        try:
            response = await self._client.get(
                f"{self.mood_manager_url}/api/mood/status",
                params={"instance_id": self.mood_instance_id},
                timeout=2.5,
            )
        except Exception:  # noqa: BLE001 - 读不到心情不能影响语音
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        settings = data.get("settings")
        if isinstance(settings, dict) and settings.get("mood_enabled") is False:
            return None
        state = data.get("state")
        if not isinstance(state, dict):
            return None
        mood = str(state.get("mood") or "")
        tone = self.mood_tones.get(mood, "")
        if not tone:
            return None
        return {
            "source": "manager",
            "mood": mood,
            "label": MOOD_LABELS.get(mood, mood),
            "intensity": _number(state.get("intensity"), 0),
            "tone": tone,
        }

    def _cache_key(self, text: str, instruction: str) -> str:
        """文本 + 音色参数 + 当前语气共同决定缓存键；换情绪不会串音。"""
        ref_meta = ""
        if self.ref_audio:
            try:
                stat = Path(self.ref_audio).expanduser().stat()
                ref_meta = f"{stat.st_size}:{stat.st_mtime_ns}"
            except OSError:
                ref_meta = self.ref_audio
        signature = "\x1f".join(
            [
                self.api_base,
                instruction,
                self.ref_text,
                ref_meta,
                str(self.cfg_scale),
                str(self.seed),
                text,
            ]
        )
        return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, key: str) -> Path:
        return _cache_dir() / f"{key}.wav"

    def _cache_lookup(self, text: str, instruction: str) -> Path | None:
        if not self.cache_enabled:
            return None
        path = self._cache_path(self._cache_key(text, instruction))
        try:
            if path.is_file() and path.stat().st_size > 0:
                os.utime(path, None)
                self._bump_stat("hits")
                return path
        except OSError:
            return None
        return None

    def _emit_cache(self, cached: Path) -> str | None:
        """复制一份交给 AstrBot，避免下游发送后删掉缓存原件。"""
        try:
            temp_dir = get_astrbot_temp_path()
            os.makedirs(temp_dir, exist_ok=True)
            path = os.path.join(
                temp_dir, f"breeze_tts_cache_{uuid.uuid4().hex[:12]}.wav"
            )
            shutil.copyfile(cached, path)
        except OSError as exc:
            logger.warning("[Breeze TTS] 读取语音缓存失败：%s", exc)
            return None
        logger.info(
            "[Breeze TTS] 命中语音缓存（%s 字节）：%s",
            os.path.getsize(path),
            cached.name,
        )
        return path

    def _store_cache(self, text: str, audio: bytes, instruction: str) -> None:
        if not self.cache_enabled:
            return
        folder = _cache_dir()
        key = self._cache_key(text, instruction)
        path = folder / f"{key}.wav"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            temp = folder / f"{key}.{uuid.uuid4().hex[:6]}.tmp"
            temp.write_bytes(audio)
            os.replace(temp, path)
        except OSError as exc:
            logger.warning("[Breeze TTS] 写入语音缓存失败：%s", exc)
            return
        self._bump_stat("misses")
        self._trim()

    def _trim(self) -> None:
        """超出条数或容量上限时，淘汰最久未使用的缓存。"""
        folder = _cache_dir()
        try:
            entries = sorted(
                (path for path in folder.glob("*.wav") if path.is_file()),
                key=lambda path: path.stat().st_mtime,
            )
            total = sum(path.stat().st_size for path in entries)
        except OSError:
            return
        limit_bytes = self.cache_max_mb * 1024 * 1024
        while entries and (
            len(entries) > self.cache_max_entries or total > limit_bytes
        ):
            old = entries.pop(0)
            try:
                total -= old.stat().st_size
                old.unlink()
            except OSError:
                continue

    def _bump_stat(self, key: str) -> None:
        folder = _cache_dir()
        path = folder / ".stats.json"
        try:
            stats = (
                json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            )
            if not isinstance(stats, dict):
                stats = {}
        except (OSError, ValueError):
            stats = {}
        stats[key] = int(stats.get(key) or 0) + 1
        stats["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            temp = folder / f".stats.{uuid.uuid4().hex[:6]}.tmp"
            temp.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            pass

    async def test(self) -> None:
        """Dashboard/管理器测试按钮用：合成一句短语音后立即删除。"""
        path = await self.get_audio("欢迎来到驰风车队，语音连接正常。")
        try:
            os.remove(path)
        except OSError:
            pass

    async def terminate(self) -> None:
        await self._client.aclose()


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _truthy(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "是", "开"}


def _mood_tones(value) -> dict[str, str]:
    """心情/情绪 → 语气提示；支持 JSON 字符串或字典，缺省用内置文案。"""
    tones = dict(DEFAULT_MOOD_TONES)
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return tones
        try:
            raw = json.loads(text)
        except ValueError:
            return tones
    if isinstance(raw, dict):
        for key, item in raw.items():
            name = str(key)
            if name in tones and isinstance(item, str) and item.strip():
                tones[name] = item.strip()
    return tones


ensure_registered()
