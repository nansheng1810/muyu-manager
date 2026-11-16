"""一键部署：机器上没有任何机器人时，引导用户创建第一个 AstrBot 实例。"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import creator, dashboard, fleet_store, runner, store

VERSION = "1.30.8"

# 预设厂商：全部走 OpenAI 兼容接口，AstrBot 侧统一使用 openai 提供器。
# 模型名为 2026 年当前在线的型号；填入 Key 后可用「检测模型」拉取账号真实可用列表。
VENDORS = [
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "provider": "deepseek",
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
        "key_required": True,
        "note": "官方直连，V4 系列中文对话与推理性价比高",
    },
    {
        "id": "dashscope",
        "label": "通义千问",
        "provider": "openai",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.8-max",
        "models": [
            "qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus", "qwen3.6-plus",
            "qwen3.5-plus", "qwen-plus", "qwen-flash",
        ],
        "key_required": True,
        "note": "阿里云百炼，OpenAI 兼容模式",
    },
    {
        "id": "siliconflow",
        "label": "硅基流动",
        "provider": "openai",
        "api_base": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V4.1-Flash",
        "models": [
            "deepseek-ai/DeepSeek-V4.1-Flash", "Qwen/Qwen3.6-35B-A3B",
            "deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-7B-Instruct",
        ],
        "key_required": True,
        "note": "聚合多家开源模型，按量计费",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "provider": "openai",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-6.1-terra",
        "models": ["gpt-6.1-terra", "gpt-6", "gpt-5.6", "gpt-5.5"],
        "key_required": True,
        "note": "官方接口，需要可用的网络环境",
    },
    {
        "id": "moonshot",
        "label": "月之暗面 Kimi",
        "provider": "openai",
        "api_base": "https://api.moonshot.cn/v1",
        "model": "kimi-k3.1-pro",
        "models": ["kimi-k3.1-pro", "kimi-k3", "kimi-k2.7-code", "kimi-k2.6"],
        "key_required": True,
        "note": "长上下文，K3 系列中文体验好",
    },
    {
        "id": "zhipu",
        "label": "智谱 GLM",
        "provider": "openai",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.3",
        "models": ["glm-5.3", "glm-5.3-flash", "glm-5.1", "glm-5"],
        "key_required": True,
        "note": "国内直连，有免费额度模型",
    },
    {
        "id": "ollama",
        "label": "Ollama 本地",
        "provider": "openai",
        "api_base": "http://127.0.0.1:11434/v1",
        "model": "qwen3.5:9b",
        "models": ["qwen3.5:9b", "qwen3.5:4b", "deepseek-v4-flash", "deepseek-v4-pro"],
        "key_required": False,
        "note": "本机运行，无需 API Key，需先安装 Ollama（可自动检测本机已下载模型）",
    },
    {
        "id": "custom",
        "label": "自定义",
        "provider": "openai",
        "api_base": "",
        "model": "",
        "models": [],
        "key_required": False,
        "note": "任何 OpenAI 兼容接口，自行填写地址与模型",
    },
]
VENDOR_MAP = {item["id"]: item for item in VENDORS}


class DeployError(Exception):
    """一键部署的业务错误。"""


_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()
_SAVE_LOCK = threading.Lock()
_MAX_JOBS = 20

STEPS = [
    {"key": "create", "label": "创建实例与模型配置"},
    {"key": "start", "label": "启动 AstrBot"},
    {"key": "dashboard", "label": "等待管理面板就绪"},
    {"key": "persona", "label": "创建人格与默认配置"},
]


def presets() -> list[dict]:
    """返回可安全展示的厂商预设。"""
    return [dict(item) for item in VENDORS]


def _find_source(settings: dict) -> str:
    candidates = [
        settings.get("astrbot_source") or "",
        str(Path(settings.get("scan_dir") or "") / "AstrBot"),
        str(store.BASE_DIR / "AstrBot"),
        str(Path.cwd() / "AstrBot"),
    ]
    for raw in candidates:
        if raw and (Path(raw) / "main.py").exists():
            return str(Path(raw).resolve())
    return ""


def _find_python(settings: dict, source: str) -> str:
    candidates = [settings.get("python_exe") or ""]
    if source:
        base = Path(source)
        candidates.append(str(base / ".venv" / "Scripts" / "python.exe"))
        candidates.append(str(base / ".venv" / "bin" / "python"))
    candidates.append(str(store.BASE_DIR / ".venv" / "Scripts" / "python.exe"))
    for raw in candidates:
        if raw and Path(raw).exists():
            return str(Path(raw).resolve())
    return ""


def status(settings: dict, instances: list[dict] | None = None) -> dict:
    """首屏状态：是否需要部署、环境是否就绪、可选厂商。"""
    bots = store.load_instances() if instances is None else instances
    source = _find_source(settings)
    python = _find_python(settings, source)
    return {
        "needed": len(bots) == 0,
        "bots": len(bots),
        "env": {
            "source_ok": bool(source),
            "source": source,
            "python_ok": bool(python),
            "python": python,
            "ready": bool(source and python),
        },
        "vendors": presets(),
    }


def save_env(payload: dict, settings: dict) -> dict:
    """保存用户手动指定的 AstrBot 源码目录与 Python 解释器。"""
    source = str(payload.get("astrbot_source") or "").strip()
    python = str(payload.get("python_exe") or "").strip()
    if source and not (Path(source) / "main.py").exists():
        raise DeployError("AstrBot 源码目录无效：找不到 main.py")
    if python and not Path(python).exists():
        raise DeployError("Python 解释器路径无效")
    patch = {}
    if source:
        patch["astrbot_source"] = source
    if python:
        patch["python_exe"] = python
    if patch:
        store.save_settings(patch)
    return status({**settings, **patch})


def _provider_config(vendor: dict, payload: dict) -> dict:
    api_base = str(payload.get("api_base") or vendor["api_base"]).strip().rstrip("/")
    model = str(payload.get("model") or vendor["model"]).strip()
    key = str(payload.get("api_key") or "").strip()
    if not api_base:
        raise DeployError("请填写模型接口地址")
    if not model:
        raise DeployError("请填写模型名称")
    if vendor.get("key_required") and not key:
        raise DeployError(f"{vendor['label']} 需要填写 API Key")
    return {
        "id": f"deploy-{vendor['id']}",
        "provider": vendor["provider"],
        "type": "openai_chat_completion",
        "provider_type": "chat_completion",
        "enable": True,
        "api_base": api_base,
        "key": [key] if key else [],
        "model": model,
        "timeout": 120,
        "proxy": "",
        "custom_headers": {},
        "custom_extra_body": {},
    }


def _http_error_text(exc: urllib.error.HTTPError) -> str:
    """把模型接口的 HTTP 错误翻译成用户能看懂的中文。"""
    hint = ""
    try:
        raw = exc.read().decode("utf-8", "replace")
        data = json.loads(raw)
        hint = str(
            (data.get("error") or {}).get("message")
            if isinstance(data.get("error"), dict)
            else data.get("error") or data.get("message") or ""
        )
    except Exception:
        hint = ""
    friendly = {
        401: "API Key 无效或已过期",
        403: "API Key 没有访问该模型的权限",
        404: "接口地址或模型名称不正确",
        429: "请求过于频繁或额度不足",
    }.get(exc.code, f"模型接口返回 HTTP {exc.code}")
    return f"{friendly}{('：' + hint) if hint else ''}"


def _chat_url(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _models_url(api_base: str) -> str:
    base = api_base.rstrip("/")
    for suffix in ("/chat/completions", "/models"):
        if base.endswith(suffix):
            return base[: -len(suffix)].rstrip("/") + "/models"
    return base + "/models"


def _probe(provider: dict, timeout: float = 20.0) -> dict:
    """用最小请求验证 API Key 与接口地址是否可用。"""
    body = json.dumps(
        {
            "model": provider["model"],
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(_chat_url(provider["api_base"]), data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    keys = provider.get("key") or []
    if keys:
        request.add_header("Authorization", f"Bearer {keys[0]}")
    started = time.time()
    reply = ""
    data: dict = {}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise DeployError(_http_error_text(exc)) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise DeployError(f"无法连接模型接口：{reason}") from exc
    except TimeoutError as exc:
        raise DeployError("连接模型接口超时，请检查地址与网络") from exc
    try:
        data = json.loads(raw)
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            reply = str((choices[0].get("message") or {}).get("content") or "")
    except Exception:
        reply = ""
    return {
        "ok": True,
        "latency_ms": int((time.time() - started) * 1000),
        "model": str((data.get("model") if isinstance(data, dict) else "") or provider["model"]),
        "reply": reply[:80],
    }


def test_connection(payload: dict) -> dict:
    """测试模型接口连通性，返回延迟与模型回显。"""
    vendor_id = str(payload.get("vendor") or "custom")
    vendor = VENDOR_MAP.get(vendor_id)
    if not vendor:
        raise DeployError("未知的模型厂商")
    provider = _provider_config(vendor, payload)
    result = _probe(provider)
    return {
        "vendor": vendor_id,
        "api_base": provider["api_base"],
        "requested_model": provider["model"],
        **result,
    }


def list_models(payload: dict) -> dict:
    """用 API Key 查询服务商真实可用的模型列表；失败时回退到预设清单。"""
    vendor_id = str(payload.get("vendor") or "custom")
    vendor = VENDOR_MAP.get(vendor_id)
    if not vendor:
        raise DeployError("未知的模型厂商")
    api_base = str(payload.get("api_base") or vendor["api_base"]).strip().rstrip("/")
    key = str(payload.get("api_key") or "").strip()
    if not api_base:
        raise DeployError("请填写模型接口地址")
    if vendor.get("key_required") and not key:
        raise DeployError(f"{vendor['label']} 需要填写 API Key")

    preset = [str(item) for item in vendor.get("models") or []]
    request = urllib.request.Request(_models_url(api_base), method="GET")
    request.add_header("Accept", "application/json")
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=20.0) as response:
            raw = response.read(512 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return {
            "ok": bool(preset),
            "source": "preset",
            "models": preset,
            "message": f"无法读取模型列表（{_http_error_text(exc)}），已展示预设模型",
        }
    except Exception as exc:  # noqa: BLE001 - 网络失败一律回退预设
        return {
            "ok": bool(preset),
            "source": "preset",
            "models": preset,
            "message": f"无法读取模型列表（{exc}），已展示预设模型",
        }
    try:
        data = json.loads(raw)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            items = data if isinstance(data, list) else []
        models = []
        for item in items:
            model_id = item.get("id") if isinstance(item, dict) else item
            if model_id and str(model_id) not in models:
                models.append(str(model_id))
    except Exception:
        models = []
    if not models:
        return {
            "ok": bool(preset),
            "source": "preset",
            "models": preset,
            "message": "服务商未返回模型列表，已展示预设模型",
        }
    models.sort()
    return {
        "ok": True,
        "source": "remote",
        "models": models,
        "message": f"已从服务商读取 {len(models)} 个可用模型",
    }


def prepare(payload: dict, settings: dict, instances: list[dict]) -> tuple[dict, dict]:
    """校验并创建实例（不启动），返回 (实例, 模型配置)。"""
    vendor_id = str(payload.get("vendor") or "deepseek")
    vendor = VENDOR_MAP.get(vendor_id)
    if not vendor:
        raise DeployError("未知的模型厂商")
    provider = _provider_config(vendor, payload)
    if not payload.get("skip_probe"):
        _probe(provider)
    source = _find_source(settings)
    if not source:
        raise DeployError("未找到 AstrBot 源码目录，请先设置源码路径")
    python = _find_python(settings, source)
    if not python:
        raise DeployError("未找到可用的 Python 解释器，请先设置")
    try:
        instance = creator.create_bootstrap_instance(
            {**payload, "provider_config": provider}, settings, instances, source
        )
    except creator.CreateError as exc:
        raise DeployError(str(exc)) from exc
    return instance, provider


def _job_update(job_id: str, **patch) -> dict:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return {}
        job.update(patch)
        job["updated"] = time.time()
        return dict(job)


def _step(job_id: str, key: str, state: str, detail: str = "") -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        for item in job["steps"]:
            if item["key"] == key:
                item["state"] = state
                if detail:
                    item["detail"] = detail[:240]
                break
        job["updated"] = time.time()


def _persist(instance: dict) -> None:
    with _SAVE_LOCK:
        instances = store.load_instances()
        for index, item in enumerate(instances):
            if item.get("id") == instance.get("id"):
                instances[index] = instance
                break
        else:
            instances.append(instance)
        store.save_instances(instances)


def start(instance: dict, settings: dict, provider: dict) -> dict:
    """登记后台部署任务并立即返回任务快照。"""
    job_id = "dp_" + uuid.uuid4().hex[:12]
    now = time.time()
    job = {
        "id": job_id,
        "state": "running",
        "message": "正在启动 AstrBot",
        "instance_id": instance.get("id", ""),
        "instance_name": instance.get("name", ""),
        "provider": provider.get("id", ""),
        "created": now,
        "updated": now,
        "steps": [
            {"key": item["key"], "label": item["label"],
             "state": "ok" if item["key"] == "create" else "pending", "detail": ""}
            for item in STEPS
        ],
        "error": "",
    }
    with _JOB_LOCK:
        _JOBS[job_id] = job
        if len(_JOBS) > _MAX_JOBS:
            for stale in sorted(_JOBS.values(), key=lambda item: item["created"])[: len(_JOBS) - _MAX_JOBS]:
                _JOBS.pop(stale["id"], None)
        snapshot = dict(job)
        snapshot["steps"] = [dict(item) for item in job["steps"]]
    thread = threading.Thread(
        target=_worker, args=(job_id, instance, settings), name="deploy-worker", daemon=True
    )
    thread.start()
    return snapshot


def job(job_id: str) -> dict | None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        snapshot = dict(job)
        snapshot["steps"] = [dict(item) for item in job["steps"]]
        return snapshot


def _worker(job_id: str, instance: dict, settings: dict) -> None:
    try:
        _step(job_id, "start", "running")
        runner.start(instance, settings)
        _persist(instance)
        _step(job_id, "start", "ok")
        _job_update(job_id, message="等待管理面板就绪")

        _step(job_id, "dashboard", "running")
        deadline = time.time() + 180
        last_error = ""
        while time.time() < deadline:
            try:
                dashboard.login(instance, force=True)
                break
            except Exception as exc:  # noqa: BLE001 - 启动过程中持续重试
                last_error = str(exc)
                time.sleep(2)
        else:
            raise DeployError(f"管理面板启动超时：{last_error or '请查看实例日志'}")
        _step(job_id, "dashboard", "ok")

        _step(job_id, "persona", "running")
        result = creator.provision(instance, timeout=90)
        detail = "；".join(str(item) for item in (result.get("steps") or []))
        _step(
            job_id,
            "persona",
            "ok" if result.get("ok") else "fail",
            detail,
        )
        _persist(instance)

        _job_update(job_id, state="done", message="部署完成，机器人已启动", error="")
        fleet_store.add_event(
            "deploy",
            instance.get("id", ""),
            "ok",
            f"一键部署完成：{instance.get('name')}",
            {"provider": instance.get("provider_id", ""), "root": instance.get("root", "")},
            ref=instance.get("id", ""),
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务需要把错误交给前端
        message = str(exc) or "部署失败"
        _job_update(job_id, state="failed", message=message, error=message)
        for key in ("start", "dashboard", "persona"):
            _step(job_id, key, "fail")
        try:
            fleet_store.add_event(
                "deploy",
                instance.get("id", ""),
                "bad",
                f"一键部署失败：{instance.get('name')}",
                {"error": message},
                ref=instance.get("id", ""),
            )
        except Exception:
            pass
