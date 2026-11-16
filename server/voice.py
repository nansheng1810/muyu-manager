"""语音（Breeze TTS）接入：安装插件、写入提供商配置、试听。"""

from __future__ import annotations

import io
import json
import re
import shutil
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import dashboard, human_settings, mood as mood_mod, store

PROVIDER_ID = "breeze_tts"
PLUGIN_ID = "astrbot_plugin_breeze_tts"
# 按“离 TTS 越近越快”排列：同机直连 → 服务器隧道 → 公网域名
LOCAL_API_BASE = "http://127.0.0.1:7860"
TUNNEL_API_BASE = "http://127.0.0.1:17860"
PUBLIC_API_BASE = "https://tts.chifengvtc.com"
DEFAULT_API_BASE = PUBLIC_API_BASE
API_ENDPOINTS = [
    {
        "id": "local",
        "label": "同机直连",
        "value": LOCAL_API_BASE,
        "hint": "机器人与 TTS 在同一台 Windows 机器，缓存命中约 0.02 秒",
    },
    {
        "id": "tunnel",
        "label": "服务器隧道",
        "value": TUNNEL_API_BASE,
        "hint": "机器人在 103.52.153.17 服务器，走服务器本地隧道",
    },
    {
        "id": "public",
        "label": "公网域名",
        "value": PUBLIC_API_BASE,
        "hint": "机器人或 TTS 在其他电脑，走公网",
    },
]
MAX_REF_AUDIO = 20 * 1024 * 1024
MAX_PRESET_AUDIO = 20 * 1024 * 1024
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
_PRESET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MOOD_MANAGER_URL = "http://127.0.0.1:7311"
MOOD_LABELS = {
    "calm": "平静",
    "happy": "开心",
    "low": "低落",
    "annoyed": "烦躁",
    "angry": "生气",
}
# 每日心情（calm/happy/low/annoyed/angry）与群聊情绪（中文）两套文案
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

_ERROR_HINTS = {
    401: "Key 没填、填错或没带 X-API-Key",
    429: "上一个请求还在生成，或超过 60 次/分钟",
    502: "本机 API 或隧道窗口被关了，重新运行 start.cmd",
}


class VoiceError(Exception):
    pass


def _plugin_source() -> Path:
    base = Path(getattr(sys, "_MEIPASS", store.BASE_DIR))
    return base / "plugins_src" / PLUGIN_ID


def _builtin_plugin_version() -> str:
    """管理器自带插件版本，用来提示实例更新。"""
    try:
        text = (_plugin_source() / "metadata.yaml").read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        if line.strip().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return ""


def _list_data(payload) -> list:
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "list", "plugins"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _plugin_item(inst: dict) -> dict | None:
    payload = dashboard.call(inst, "GET", "plugins", timeout=30)
    for item in _list_data(payload):
        if not isinstance(item, dict):
            continue
        if (item.get("id") or item.get("name")) == PLUGIN_ID:
            return item
    return None


def _provider(inst: dict) -> dict | None:
    try:
        payload = dashboard.call(
            inst,
            "GET",
            "providers/by-id",
            query={"provider_id": PROVIDER_ID, "merged": "true"},
            timeout=20,
        )
    except dashboard.DashboardError as exc:
        if exc.status in (400, 404):
            return None
        raise
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    provider = data.get("provider") if isinstance(data.get("provider"), dict) else data
    return provider if isinstance(provider, dict) and provider.get("id") else None


def _profile(inst: dict) -> dict:
    payload = dashboard.call(inst, "GET", "config-profiles/default", timeout=20)
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    config = data.get("config") if isinstance(data, dict) else None
    if not isinstance(config, dict):
        raise VoiceError("读取 AstrBot 配置失败")
    return config


def _mask(key: str) -> str:
    key = str(key or "")
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def _builtin_preset_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", store.BASE_DIR))
    return base / "voice_presets"


def _preset_dir() -> Path:
    """用户可写的人声预设库，所有实例共享。"""
    return store.DATA_DIR / "voice_presets"


def _seed_presets() -> None:
    """把安装包里的人声预设播种到可写目录；删掉的预设不会在下次启动时复活。"""
    folder = _preset_dir()
    marker = folder / ".seeded"
    seeded: list[str] = []
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(data, list):
                seeded = [str(name) for name in data]
        except (OSError, ValueError):
            pass
    builtin = _builtin_preset_dir()
    if not builtin.is_dir():
        return
    folder.mkdir(parents=True, exist_ok=True)
    added = False
    for path in sorted(builtin.iterdir()):
        if not path.is_file() or path.name in seeded:
            continue
        target = folder / path.name
        if not target.exists():
            shutil.copy2(path, target)
        seeded.append(path.name)
        added = True
    if added:
        store.write_json(marker, seeded)


def _presets() -> list[dict]:
    """读取可写预设库；缺少音频或元数据的预设会被跳过。"""
    _seed_presets()
    folder = _preset_dir()
    if not folder.is_dir():
        return []
    items = []
    for meta_path in sorted(folder.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        preset_id = str(meta.get("id") or "").strip()
        if not _PRESET_ID_RE.match(preset_id):
            continue
        ref = folder / Path(str(meta.get("ref_file") or "")).name
        if not ref.is_file():
            continue
        duration = 0.0
        try:
            with wave.open(str(ref), "rb") as stream:
                duration = round(stream.getnframes() / max(stream.getframerate(), 1), 1)
        except (OSError, wave.Error):
            pass
        items.append(
            {
                "id": preset_id,
                "name": str(meta.get("name") or preset_id).strip(),
                "label": str(meta.get("label") or "").strip(),
                "summary": str(meta.get("summary") or "").strip(),
                "traits": [
                    str(tag).strip()
                    for tag in (meta.get("traits") or [])
                    if str(tag).strip()
                ],
                "instruction": str(meta.get("instruction") or "").strip(),
                "ref_text": str(meta.get("ref_text") or "").strip(),
                "ref_audio": str(ref),
                "ref_file": ref.name,
                "cfg_scale": _float(meta.get("cfg_scale"), 4.0),
                "seed": int(_float(meta.get("seed"), 42)),
                "duration": duration,
            }
        )
    return items


def _preset_view(preset: dict) -> dict:
    return {
        "id": preset["id"],
        "name": preset["name"],
        "label": preset["label"],
        "summary": preset["summary"],
        "traits": preset["traits"],
        "duration": preset["duration"],
        "instruction": preset["instruction"],
        "ref_text": preset["ref_text"],
        "cfg_scale": preset["cfg_scale"],
        "seed": preset["seed"],
    }


def _preset_item(preset_id: str) -> dict | None:
    return next((item for item in _presets() if item["id"] == preset_id), None)


def _preset_record(preset_id: str) -> tuple[Path, dict] | None:
    _seed_presets()
    folder = _preset_dir()
    if not folder.is_dir():
        return None
    for meta_path in sorted(folder.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and str(meta.get("id") or "").strip() == preset_id:
            return meta_path, meta
    return None


def _preset_payload(payload: dict) -> dict:
    """校验并整理人声预设表单字段。"""
    name = str(payload.get("name") or "").strip()
    if not name:
        raise VoiceError("请填写人声预设名称")
    ref_text = str(payload.get("ref_text") or "").strip()
    if not ref_text:
        raise VoiceError("请填写参考音频逐字稿，克隆需要它来对齐音色")
    traits = payload.get("traits") or []
    if isinstance(traits, str):
        traits = re.split(r"[，,、\s]+", traits)
    traits = [str(tag).strip() for tag in traits if str(tag).strip()][:6]
    cfg_scale = _float(payload.get("cfg_scale"), 4.0)
    if cfg_scale < 0 or cfg_scale > 30:
        raise VoiceError("cfg_scale 需要在 0 到 30 之间")
    return {
        "name": name[:40],
        "label": str(payload.get("label") or "").strip()[:12],
        "summary": str(payload.get("summary") or "").strip()[:200],
        "traits": traits,
        "instruction": str(payload.get("instruction") or "").strip()[:500],
        "ref_text": ref_text[:2000],
        "cfg_scale": cfg_scale,
        "seed": int(_float(payload.get("seed"), 42)),
    }


def _instance_ref_audio(inst: dict) -> Path:
    provider = _provider(inst) or {}
    ref = str(provider.get("ref_audio") or "").strip()
    if not ref:
        raise VoiceError("当前实例还没有参考音频，请先上传或应用一个人声预设")
    path = Path(ref).expanduser()
    if not path.is_absolute():
        path = Path(inst.get("root") or "") / path
    if not path.is_file():
        raise VoiceError(f"找不到当前实例的参考音频：{ref}")
    return path


def create_preset(inst: dict, payload: dict) -> dict:
    """用当前实例的参考音频创建一条新的可编辑人声预设。"""
    meta = _preset_payload(payload)
    source = _instance_ref_audio(inst)
    folder = _preset_dir()
    folder.mkdir(parents=True, exist_ok=True)
    preset_id = uuid.uuid4().hex[:8]
    suffix = source.suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        suffix = ".wav"
    audio = folder / f"{preset_id}{suffix}"
    shutil.copy2(source, audio)
    meta.update({"id": preset_id, "ref_file": audio.name})
    store.write_json(folder / f"{preset_id}.json", meta)
    return _preset_view(_preset_item(preset_id))


def update_preset(inst: dict, preset_id: str, payload: dict) -> dict:
    """修改预设的文案、音色描述和生成参数；参考音频用单独接口替换。"""
    record = _preset_record(preset_id)
    if not record:
        raise VoiceError("没有找到这个人声预设")
    meta_path, meta = record
    merged = dict(meta)
    merged.update({key: value for key, value in payload.items() if value is not None})
    meta.update(_preset_payload(merged))
    store.write_json(meta_path, meta)
    return _preset_view(_preset_item(preset_id))


def save_preset_audio(inst: dict, preset_id: str, filename: str, body: bytes) -> dict:
    """替换预设自带的参考音频。"""
    record = _preset_record(preset_id)
    if not record:
        raise VoiceError("没有找到这个人声预设")
    meta_path, meta = record
    if not body:
        raise VoiceError("参考音频为空")
    if len(body) > MAX_PRESET_AUDIO:
        raise VoiceError("参考音频超过 20MB")
    name = Path(str(filename or "reference.wav")).name
    suffix = Path(name).suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        raise VoiceError("参考音频只支持 wav / mp3 / m4a / flac / ogg")
    folder = meta_path.parent
    audio = folder / f"{preset_id}{suffix}"
    audio.write_bytes(body)
    old = folder / Path(str(meta.get("ref_file") or "")).name
    if old != audio and old.is_file():
        try:
            old.unlink()
        except OSError:
            pass
    meta["ref_file"] = audio.name
    store.write_json(meta_path, meta)
    return _preset_view(_preset_item(preset_id))


def delete_preset(inst: dict, preset_id: str) -> dict:
    record = _preset_record(preset_id)
    if not record:
        raise VoiceError("没有找到这个人声预设")
    meta_path, meta = record
    folder = meta_path.parent
    removed = []
    for target in (meta_path, folder / Path(str(meta.get("ref_file") or "")).name):
        if target.is_file():
            try:
                target.unlink()
                removed.append(target.name)
            except OSError:
                pass
    return {"removed": preset_id, "files": removed}


def probe_endpoints() -> list[dict]:
    """从管理器所在机器探测三档地址是否可连；只做 TCP 握手，不发业务请求。"""

    def probe(item: dict) -> dict:
        parsed = urllib.parse.urlparse(item["value"])
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        started = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=2.5):
                pass
        except OSError as exc:
            return {**item, "reachable": False, "ms": 0, "error": str(exc)[:120]}
        return {
            **item,
            "reachable": True,
            "ms": max(1, round((time.perf_counter() - started) * 1000)),
        }

    with ThreadPoolExecutor(max_workers=len(API_ENDPOINTS)) as pool:
        return list(pool.map(probe, API_ENDPOINTS))


def _mood_tones(value=None) -> dict:
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


def mood_state(inst: dict, provider: dict | None = None) -> dict:
    """读取实例当前每日心情，并给出该心情对应的语音语气。"""
    if provider is None:
        try:
            provider = _provider(inst) or {}
        except dashboard.DashboardError:
            provider = {}
    tones = _mood_tones(provider.get("mood_tones"))
    result = {
        "enabled": _bool(provider.get("mood_sync_enabled"), False),
        "available": False,
        "mood_enabled": True,
        "source": "",
        "mood": "",
        "label": "",
        "intensity": 0.0,
        "tone": "",
        "tones": tones,
        "manager_url": str(provider.get("mood_manager_url") or MOOD_MANAGER_URL),
        "instance_id": str(provider.get("mood_instance_id") or inst.get("id") or ""),
        "error": "",
    }
    instance_id = str(inst.get("id") or "").strip()
    if not instance_id:
        result["error"] = "实例缺少 id"
        return result
    try:
        settings = human_settings.get_settings(instance_id)
        state = mood_mod.get_state(instance_id)
    except Exception as exc:  # noqa: BLE001 - 心情读取失败不能影响语音页
        result["error"] = str(exc)[:120]
        return result
    mood_key = str(state.get("mood") or "")
    result.update(
        {
            "available": True,
            "mood_enabled": bool(settings.get("mood_enabled", True)),
            "source": "manager",
            "mood": mood_key,
            "label": MOOD_LABELS.get(mood_key, mood_key),
            "intensity": round(_float(state.get("intensity"), 0), 1),
            "tone": tones.get(mood_key, ""),
        }
    )
    return result


def status(inst: dict) -> dict:
    plugin = _plugin_item(inst)
    builtin_version = _builtin_plugin_version()
    plugin_view = {
        "id": PLUGIN_ID,
        "installed": bool(plugin),
        "enabled": bool(plugin and (plugin.get("activated") or plugin.get("enabled"))),
        "version": str((plugin or {}).get("version") or ""),
        "builtin_version": builtin_version,
        "update_available": bool(
            plugin and builtin_version and str(plugin.get("version") or "") != builtin_version
        ),
    }
    try:
        provider = _provider(inst)
    except dashboard.DashboardError as exc:
        provider = None
        provider_error = exc.message
    else:
        provider_error = ""
    config = _profile(inst)
    tts = config.get("provider_tts_settings") or {}
    if not isinstance(tts, dict):
        tts = {}
    provider_view = {
        "exists": bool(provider),
        "enabled": bool((provider or {}).get("enable", False)),
        "api_base": str((provider or {}).get("api_base") or DEFAULT_API_BASE),
        "has_key": bool(str((provider or {}).get("api_key") or "").strip()),
        "key_masked": _mask((provider or {}).get("api_key") or ""),
        "instruction": str((provider or {}).get("instruction") or ""),
        "cfg_scale": _float((provider or {}).get("cfg_scale"), 4.0),
        "seed": int(_float((provider or {}).get("seed"), 42)),
        "ref_audio": str((provider or {}).get("ref_audio") or ""),
        "ref_text": str((provider or {}).get("ref_text") or ""),
        "timeout": int(_float((provider or {}).get("timeout"), 300)),
        "cache_enabled": bool((provider or {}).get("cache_enabled", True)),
        "cache_max_entries": int(
            _float((provider or {}).get("cache_max_entries"), 200)
        ),
        "cache_max_mb": int(_float((provider or {}).get("cache_max_mb"), 200)),
        "mood_sync_enabled": bool((provider or {}).get("mood_sync_enabled", False)),
        "mood_group_enabled": bool((provider or {}).get("mood_group_enabled", True)),
        "mood_manager_url": str(
            (provider or {}).get("mood_manager_url") or MOOD_MANAGER_URL
        ),
        "mood_instance_id": str(
            (provider or {}).get("mood_instance_id") or inst.get("id") or ""
        ),
        "mood_cache_seconds": int(
            _float((provider or {}).get("mood_cache_seconds"), 20)
        ),
        "mood_tones": _mood_tones((provider or {}).get("mood_tones")),
    }
    presets_view = []
    for preset in _presets():
        view = _preset_view(preset)
        view["applied"] = bool(
            provider_view["ref_audio"]
            and provider_view["instruction"] == preset["instruction"]
            and provider_view["ref_text"] == preset["ref_text"]
        )
        presets_view.append(view)
    return {
        "plugin": plugin_view,
        "provider": provider_view,
        "provider_error": provider_error,
        "presets": presets_view,
        "endpoints": [dict(item) for item in API_ENDPOINTS],
        "cache": cache_status(inst, provider),
        "mood": mood_state(inst, provider),
        "tts": {
            "enabled": bool(tts.get("enable"))
            and str(tts.get("provider_id") or "") == PROVIDER_ID,
            "provider_id": str(tts.get("provider_id") or ""),
            "dual_output": bool(tts.get("dual_output")),
            "trigger_probability": _float(tts.get("trigger_probability"), 1.0),
            "use_file_service": bool(tts.get("use_file_service")),
        },
    }


def install(inst: dict, force: bool = False) -> dict:
    plugin = _plugin_item(inst)
    if plugin and not force:
        if not (plugin.get("activated") or plugin.get("enabled")):
            dashboard.call(
                inst,
                "PATCH",
                f"plugins/{PLUGIN_ID}/enabled",
                {"enabled": True},
                timeout=60,
            )
            dashboard.call(inst, "POST", f"plugins/{PLUGIN_ID}/reload", timeout=120)
        return status(inst)

    source = _plugin_source()
    if not source.is_dir():
        raise VoiceError("管理器里缺少语音插件文件，请重新安装管理器")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            zf.write(path, f"{PLUGIN_ID}/{path.relative_to(source).as_posix()}")
    body = archive.getvalue()
    boundary = "----MoyuVoice" + uuid.uuid4().hex
    parts = [
        f"--{boundary}",
        'Content-Disposition: form-data; name="ignore_version_check"',
        "",
        "true",
        f"--{boundary}",
        'Content-Disposition: form-data; name="file"; filename="astrbot_plugin_breeze_tts.zip"',
        "Content-Type: application/zip",
        "",
    ]
    head = "\r\n".join(parts).encode("utf-8") + b"\r\n"
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    dashboard.upload_raw(
        inst,
        "plugins/install/upload",
        head + body + tail,
        f"multipart/form-data; boundary={boundary}",
        timeout=600,
    )
    if plugin:
        # 覆盖安装后让 AstrBot 重新加载新代码
        try:
            dashboard.call(inst, "POST", f"plugins/{PLUGIN_ID}/reload", timeout=120)
        except dashboard.DashboardError:
            pass
    result = status(inst)
    if not result["plugin"]["installed"] or not result["plugin"]["enabled"]:
        raise VoiceError("插件上传完成，但 AstrBot 还没有启用它，请稍后重试")
    return result


def _api_base(value) -> str:
    base = str(value or DEFAULT_API_BASE).strip().rstrip("/")
    if not (base.startswith("http://") or base.startswith("https://")):
        raise VoiceError("语音 API 地址必须以 http:// 或 https:// 开头")
    return base


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _provider_config(inst: dict, payload: dict) -> dict:
    existing = _provider(inst) or {}
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        api_key = str(existing.get("api_key") or "").strip()
    if not api_key:
        raise VoiceError("请填写 Breeze API Key")

    cfg_scale = _float(payload.get("cfg_scale"), _float(existing.get("cfg_scale"), 4.0))
    if cfg_scale < 0 or cfg_scale > 30:
        raise VoiceError("cfg_scale 需要在 0 到 30 之间")
    seed = int(_float(payload.get("seed"), _float(existing.get("seed"), 42)))
    timeout = int(_float(payload.get("timeout"), _float(existing.get("timeout"), 300)))
    timeout = max(30, min(900, timeout))
    ref_audio = str(
        payload.get("ref_audio")
        if payload.get("ref_audio") is not None
        else existing.get("ref_audio") or ""
    ).strip()
    ref_text = str(
        payload.get("ref_text")
        if payload.get("ref_text") is not None
        else existing.get("ref_text") or ""
    ).strip()
    instruction = str(
        payload.get("instruction")
        if payload.get("instruction") is not None
        else existing.get("instruction") or ""
    ).strip()
    cache_enabled = _bool(
        payload.get("cache_enabled")
        if payload.get("cache_enabled") is not None
        else existing.get("cache_enabled"),
        True,
    )
    cache_entries = int(
        _float(
            payload.get("cache_max_entries"),
            _float(existing.get("cache_max_entries"), 200),
        )
    )
    cache_entries = max(1, min(2000, cache_entries))
    cache_mb = int(
        _float(payload.get("cache_max_mb"), _float(existing.get("cache_max_mb"), 200))
    )
    cache_mb = max(10, min(2000, cache_mb))

    mood_sync_enabled = _bool(
        payload.get("mood_sync_enabled")
        if payload.get("mood_sync_enabled") is not None
        else existing.get("mood_sync_enabled"),
        True,
    )
    mood_group_enabled = _bool(
        payload.get("mood_group_enabled")
        if payload.get("mood_group_enabled") is not None
        else existing.get("mood_group_enabled"),
        True,
    )
    mood_manager_url = str(
        payload.get("mood_manager_url")
        or existing.get("mood_manager_url")
        or MOOD_MANAGER_URL
    ).strip().rstrip("/")
    if not mood_manager_url.startswith(("http://", "https://")):
        mood_manager_url = MOOD_MANAGER_URL
    mood_instance_id = str(
        payload.get("mood_instance_id")
        or existing.get("mood_instance_id")
        or inst.get("id")
        or ""
    ).strip()
    mood_cache_seconds = int(
        _float(
            payload.get("mood_cache_seconds"),
            _float(existing.get("mood_cache_seconds"), 20),
        )
    )
    mood_cache_seconds = max(5, min(300, mood_cache_seconds))
    mood_tones = _mood_tones(existing.get("mood_tones"))
    overrides = payload.get("mood_tones")
    if isinstance(overrides, str) and overrides.strip():
        try:
            overrides = json.loads(overrides)
        except ValueError:
            overrides = None
    if isinstance(overrides, dict):
        for key, text in overrides.items():
            name = str(key)
            if name in mood_tones and isinstance(text, str) and text.strip():
                mood_tones[name] = text.strip()

    return {
        **existing,
        "id": PROVIDER_ID,
        "type": PROVIDER_ID,
        "provider_type": "text_to_speech",
        "enable": True,
        "api_base": _api_base(payload.get("api_base") or existing.get("api_base")),
        "api_key": api_key,
        "instruction": instruction[:500],
        "cfg_scale": cfg_scale,
        "seed": seed,
        "timeout": timeout,
        "ref_audio": ref_audio,
        "ref_text": ref_text[:2000],
        "model": str(existing.get("model") or "breeze-tts"),
        "cache_enabled": cache_enabled,
        "cache_max_entries": cache_entries,
        "cache_max_mb": cache_mb,
        "mood_sync_enabled": mood_sync_enabled,
        "mood_group_enabled": mood_group_enabled,
        "mood_manager_url": mood_manager_url,
        "mood_instance_id": mood_instance_id,
        "mood_cache_seconds": mood_cache_seconds,
        "mood_tones": json.dumps(mood_tones, ensure_ascii=False),
    }


def _write_provider(inst: dict, config: dict) -> None:
    if _provider(inst):
        dashboard.call(
            inst,
            "PUT",
            "providers/by-id",
            {"provider_id": PROVIDER_ID, "config": config},
            timeout=60,
        )
        return
    try:
        dashboard.call(inst, "POST", "providers", {"config": config}, timeout=60)
    except dashboard.DashboardError:
        # 并发保存时可能已经创建，再更新一次。
        dashboard.call(
            inst,
            "PUT",
            "providers/by-id",
            {"provider_id": PROVIDER_ID, "config": config},
            timeout=60,
        )


def save(inst: dict, payload: dict) -> dict:
    """保存提供商并开启全局 TTS；插件不存在时自动安装。"""
    plugin = _plugin_item(inst)
    if not plugin or not (plugin.get("activated") or plugin.get("enabled")):
        install(inst)

    config = _provider_config(inst, payload)
    _write_provider(inst, config)

    profile = _profile(inst)
    tts = profile.get("provider_tts_settings")
    if not isinstance(tts, dict):
        tts = {}
    tts.update(
        {
            "enable": True,
            "provider_id": PROVIDER_ID,
            "dual_output": bool(
                payload.get("dual_output", tts.get("dual_output", False))
            ),
            "trigger_probability": min(
                1.0,
                max(
                    0.0,
                    _float(
                        payload.get(
                            "trigger_probability",
                            tts.get("trigger_probability", 1.0),
                        ),
                        1.0,
                    ),
                ),
            ),
        }
    )
    if "use_file_service" in payload:
        tts["use_file_service"] = bool(payload.get("use_file_service"))
    profile["provider_tts_settings"] = tts
    dashboard.call(inst, "PUT", "config-profiles/default", profile, timeout=60)
    return status(inst)


def disable(inst: dict) -> dict:
    profile = _profile(inst)
    tts = profile.get("provider_tts_settings")
    if not isinstance(tts, dict):
        tts = {}
    tts["enable"] = False
    profile["provider_tts_settings"] = tts
    dashboard.call(inst, "PUT", "config-profiles/default", profile, timeout=60)
    return status(inst)


def apply_preset(inst: dict, preset_id: str) -> dict:
    """应用人声预设：复制参考音频并写入提供商，不改变语音回复开关。"""
    preset = _preset_item(preset_id)
    if not preset:
        raise VoiceError("没有找到这个人声预设")
    plugin = _plugin_item(inst)
    if not plugin or not (plugin.get("activated") or plugin.get("enabled")):
        install(inst)
    try:
        body = Path(preset["ref_audio"]).read_bytes()
    except OSError as exc:
        raise VoiceError("预设参考音频读取失败，请重新安装管理器") from exc
    saved = save_ref_audio(inst, preset["ref_file"], body)
    existing = _provider(inst) or {}
    config = _provider_config(
        inst,
        {
            "api_base": existing.get("api_base") or DEFAULT_API_BASE,
            "instruction": preset["instruction"],
            "cfg_scale": preset["cfg_scale"],
            "seed": preset["seed"],
            "timeout": existing.get("timeout") or 300,
            "ref_audio": saved["path"],
            "ref_text": preset["ref_text"],
        },
    )
    _write_provider(inst, config)
    return status(inst)


# ---------------------------------------------------------------- ref audio


def _ref_dir(inst: dict) -> Path:
    root = Path(inst.get("root") or "")
    if not root.is_dir():
        raise VoiceError("该实例没有本地目录，无法保存参考音频")
    return root / "data" / "plugin_data" / PLUGIN_ID


def save_ref_audio(inst: dict, filename: str, body: bytes) -> dict:
    if not body:
        raise VoiceError("参考音频为空")
    if len(body) > MAX_REF_AUDIO:
        raise VoiceError("参考音频超过 20MB")
    name = Path(str(filename or "reference.wav")).name
    suffix = Path(name).suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        raise VoiceError("参考音频只支持 wav / mp3 / m4a / flac / ogg")
    folder = _ref_dir(inst)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("ref_audio*"):
        try:
            old.unlink()
        except OSError:
            pass
    path = folder / f"ref_audio{suffix}"
    path.write_bytes(body)
    return {"path": str(path), "bytes": len(body), "name": path.name}


def delete_ref_audio(inst: dict) -> dict:
    folder = _ref_dir(inst)
    removed = 0
    if folder.is_dir():
        for old in folder.glob("ref_audio*"):
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
    return {"removed": removed}


# ---------------------------------------------------------------- voice cache


def _cache_dir(inst: dict) -> Path | None:
    root = Path(inst.get("root") or "")
    if not root.is_dir():
        return None
    return root / "data" / "plugin_data" / PLUGIN_ID / "tts_cache"


def cache_status(inst: dict, provider: dict | None = None) -> dict:
    """统计插件生成的语音缓存；命中后相同文本不再请求 TTS。"""
    if provider is None:
        try:
            provider = _provider(inst) or {}
        except dashboard.DashboardError:
            provider = {}
    enabled = _bool(provider.get("cache_enabled"), True)
    max_entries = int(_float(provider.get("cache_max_entries"), 200))
    max_mb = int(_float(provider.get("cache_max_mb"), 200))
    folder = _cache_dir(inst)
    result = {
        "available": bool(folder),
        "enabled": enabled,
        "entries": 0,
        "bytes": 0,
        "hits": 0,
        "misses": 0,
        "max_entries": max_entries,
        "max_mb": max_mb,
        "updated_at": "",
    }
    if not folder or not folder.is_dir():
        return result
    entries = 0
    size = 0
    for path in folder.glob("*.wav"):
        try:
            if path.is_file():
                entries += 1
                size += path.stat().st_size
        except OSError:
            continue
    stats_path = folder / ".stats.json"
    try:
        stats = (
            json.loads(stats_path.read_text(encoding="utf-8"))
            if stats_path.is_file()
            else {}
        )
        if not isinstance(stats, dict):
            stats = {}
    except (OSError, ValueError):
        stats = {}
    result.update(
        {
            "entries": entries,
            "bytes": size,
            "hits": int(_float(stats.get("hits"), 0)),
            "misses": int(_float(stats.get("misses"), 0)),
            "updated_at": str(stats.get("updated_at") or ""),
        }
    )
    return result


def clear_cache(inst: dict) -> dict:
    folder = _cache_dir(inst)
    if not folder or not folder.is_dir():
        return {"removed": 0}
    removed = 0
    for path in folder.glob("*.wav"):
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError:
            continue
    stats_path = folder / ".stats.json"
    try:
        if stats_path.is_file():
            stats_path.unlink()
    except OSError:
        pass
    return {"removed": removed}


# ------------------------------------------------------------------ preview


def _multipart(fields: dict, files: dict | None = None) -> tuple[bytes, str]:
    boundary = "----MoyuVoice" + uuid.uuid4().hex
    body = bytearray()
    for key, value in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
        ).encode("utf-8")
        body += str(value).encode("utf-8") + b"\r\n"
    for key, (filename, content) in (files or {}).items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def preview(inst: dict, payload: dict) -> bytes:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise VoiceError("请先输入要试听的文字")
    if len(text) > 1200:
        raise VoiceError("试听文字请控制在 1200 字以内")
    merged = _provider_config(inst, payload)
    api_base = merged["api_base"]
    api_key = merged["api_key"]
    instruction = merged["instruction"]
    if _bool(merged.get("mood_sync_enabled"), False):
        state = mood_state(inst, merged)
        if state.get("available") and state.get("mood_enabled"):
            tone = str(state.get("tone") or "").strip()
            if tone:
                instruction = f"{instruction}\n{tone}".strip()
    cfg_scale = merged["cfg_scale"]
    seed = merged["seed"]
    timeout = merged["timeout"]
    ref_audio = merged["ref_audio"]
    ref_text = merged["ref_text"]

    fields = {"text": text, "cfg_scale": cfg_scale, "seed": seed}
    if instruction:
        fields["instruction"] = instruction
    if ref_text:
        fields["ref_text"] = ref_text
    files = {}
    if ref_audio:
        path = Path(ref_audio).expanduser()
        if not path.is_absolute():
            path = Path(inst.get("root") or "") / path
        if path.is_file():
            files["ref_audio"] = (path.name, path.read_bytes())
        else:
            raise VoiceError(f"参考音频不存在：{ref_audio}")
    body, content_type = _multipart(fields, files)
    request = urllib.request.Request(
        f"{api_base}/v1/audio/speech/wav",
        data=body,
        method="POST",
        headers={"X-API-Key": api_key, "Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=max(30, timeout)) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        hint = _ERROR_HINTS.get(exc.code, "")
        message = f"语音服务返回 HTTP {exc.code}"
        if hint:
            message += f"：{hint}"
        detail = _json_message(raw)
        if detail:
            message += f"（{detail}）"
        raise VoiceError(message) from exc
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(f"无法连接语音服务：{exc}") from exc
    if not audio:
        raise VoiceError("语音服务返回了空音频")
    return audio


def _json_message(raw: str) -> str:
    try:
        data = json.loads(raw)
    except Exception:
        return raw.strip()[:160]
    if isinstance(data, dict):
        for key in ("message", "detail", "error", "msg"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:160]
    return ""
