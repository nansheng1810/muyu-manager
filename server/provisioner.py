"""一键补齐新用户本机缺少的 AstrBot 运行环境、NapCat 与插件套装。"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

from . import creator, deploy, fleet_store, runner, store

VERSION = "1.23.11"

RUNTIME_DIR = store.DATA_DIR / "runtime"
DOWNLOAD_DIR = store.DATA_DIR / "downloads"

ASTRBOT_ZIP_URLS = [
    "https://gh-proxy.com/https://github.com/AstrBotDevs/AstrBot/archive/refs/heads/master.zip",
    "https://ghproxy.net/https://github.com/AstrBotDevs/AstrBot/archive/refs/heads/master.zip",
    "https://github.com/AstrBotDevs/AstrBot/archive/refs/heads/master.zip",
    "https://github.com/AstrBotDevs/AstrBot/archive/refs/heads/main.zip",
]
PYTHON_VERSION = "3.12.8"
PYTHON_URLS = [
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-amd64.exe",
    f"https://mirrors.huaweicloud.com/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-amd64.exe",
]
NAPCAT_RELEASE_API = "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest"
_NAPCAT_ASSET = "https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.Windows.Node.zip"
NAPCAT_FALLBACK = [
    f"https://gh-proxy.com/{_NAPCAT_ASSET}",
    f"https://ghproxy.net/{_NAPCAT_ASSET}",
    _NAPCAT_ASSET,
]
PIP_MIRRORS = ["https://pypi.tuna.tsinghua.edu.cn/simple", ""]

# 管理器拥有对应页面、但全新 AstrBot 默认没有的插件套装。
SUITE = [
    {
        "id": "astrbot_plugin_human_presence",
        "label": "连续生活线 / 群梗库 / 看图接话",
        "note": "牧鱼活人感：关系活动、话题回访与人格外的生活线",
    },
    {
        "id": "astrbot_plugin_dafeiyu_clean",
        "label": "回复防护与记忆纠错",
        "note": "内部标签清理、敏感词闸门与说错话自检",
    },
    {
        "id": "astrbot_plugin_fleet_inbox",
        "label": "收件箱接管",
        "note": "管理器接管 QQ 会话时暂停自动回复",
    },
    {
        "id": "astrbot_plugin_fleet_duet",
        "label": "双机群聊剧场",
        "note": "两个机器人按话题轮流真实发言",
    },
    {
        "id": "astrbot_plugin_dsh_bridge",
        "label": "DSH 智能体桥接",
        "note": "把本机 DeepSeek Harness 接到机器人",
    },
    {
        "id": "astrbot_plugin_livingmemory",
        "label": "长期记忆 LivingMemory",
        "note": "记忆生命周期、检索与自动整理",
        "repo": "https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory",
    },
    {
        "id": "astrbot_plugin_proactive_chat",
        "label": "主动消息",
        "note": "私聊与群聊的主动开口",
        "repo": "https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat",
    },
    {
        "id": "astrbot_plugin_group_chat_plus",
        "label": "群聊增强 chat_plus",
        "note": "读空气、回复密度与并发合并",
        "repo": "https://github.com/Him666233/astrbot_plugin_group_chat_plus",
    },
    {
        "id": "astrbot_plugin_bilibili_ai_bot",
        "label": "B站 AI Bot",
        "note": "B站直播与私信接入，安装后需配置账号",
        "repo": "https://github.com/chenluQwQ/astrbot_plugin_bilibili_ai_bot",
    },
    {
        "id": "astrbot_plugin_douyin_dm",
        "label": "抖音私信",
        "note": "抖音私信自动回复，安装后需扫码登录",
        "repo": "https://github.com/lxy005tt-collab/astrbot_plugin_douyin_dm",
    },
    {
        "id": "astrbot_plugin_cloudmusic",
        "label": "网易云音乐点歌",
        "note": "点歌、搜索与音乐卡片",
        "repo": "https://github.com/AstrBot-Devs/astrbot_plugin_cloudmusic",
    },
    {
        "id": "astrbot_plugin_qzone",
        "label": "QQ 空间",
        "note": "自动浏览、点赞与发布说说，安装后需登录",
    },
    {
        "id": "astrbot_plugin_qqprofile",
        "label": "QQ 资料卡",
        "note": "查看群友资料卡与昵称信息",
    },
    {
        "id": "meme_manager",
        "label": "表情包管理器",
        "note": "表情包收藏、检索与自动配图",
        "repo": "https://github.com/anka-afk/astrbot_plugin_meme_manager",
    },
    {
        "id": "astrbot_plugin_dafeiyu_signature",
        "label": "签名档",
        "note": "群聊签名与身份尾巴",
    },
    {
        "id": "astrbot_plugin_daily_mood",
        "label": "每日心情",
        "note": "每天的心情状态与语气变化",
    },
    {
        "id": "astrbot_plugin_human_mode",
        "label": "人类模式",
        "note": "更像真人的打断与短句节奏",
    },
    {
        "id": "astrbot_plugin_owner_only",
        "label": "仅主人模式",
        "note": "只响应主人指令的静默开关",
    },
    {
        "id": "astrbot_plugin_think_bridge",
        "label": "思考桥接",
        "note": "把推理过程桥接给其他插件",
    },
]

_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()
_MAX_JOBS = 20


class InstallError(Exception):
    """一键安装的业务错误。"""


# ------------------------------------------------------------------ jobs


def _new_job(kind: str, title: str, steps: list[tuple[str, str]],
             instance_id: str = "") -> dict:
    job_id = "ip_" + uuid.uuid4().hex[:12]
    now = time.time()
    job = {
        "id": job_id,
        "kind": kind,
        "title": title,
        "state": "running",
        "message": "正在准备",
        "instance_id": instance_id,
        "created": now,
        "updated": now,
        "steps": [
            {"key": key, "label": label, "state": "pending", "detail": ""}
            for key, label in steps
        ],
        "error": "",
    }
    with _JOB_LOCK:
        _JOBS[job_id] = job
        if len(_JOBS) > _MAX_JOBS:
            for stale in sorted(_JOBS.values(), key=lambda item: item["created"])[: len(_JOBS) - _MAX_JOBS]:
                _JOBS.pop(stale["id"], None)
    return snapshot(job_id) or {}


def _update(job_id: str, **patch) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.update(patch)
            job["updated"] = time.time()


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


def snapshot(job_id: str) -> dict | None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        data = dict(job)
        data["steps"] = [dict(item) for item in job["steps"]]
        return data


def job(job_id: str) -> dict | None:
    return snapshot(job_id)


def _fail_rest(job_id: str, detail: str = "") -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        for item in job["steps"]:
            if item["state"] in ("pending", "running"):
                item["state"] = "fail"
                if detail and not item["detail"]:
                    item["detail"] = detail[:240]
        job.update({"state": "failed", "message": detail or "安装失败", "error": detail})
        job["updated"] = time.time()


def _ok_event(title: str, detail: dict) -> None:
    try:
        fleet_store.add_event("deploy", "runtime", "ok", title, detail)
    except Exception:
        pass


def _bad_event(title: str, detail: dict) -> None:
    try:
        fleet_store.add_event("deploy", "runtime", "bad", title, detail)
    except Exception:
        pass


# --------------------------------------------------------------- download


def _download(urls: list[str], timeout: float = 180.0,
              max_bytes: int = 256 * 1024 * 1024,
              on_progress=None) -> tuple[bytes, str]:
    """依次尝试下载地址；总时长超过 timeout 立即换下一个镜像。"""
    last_error = "未知错误"
    for url in urls:
        started = time.monotonic()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Moyu/1.23"})
            with urllib.request.urlopen(request, timeout=30.0) as response:
                total = int(response.headers.get("Content-Length") or 0)
                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise InstallError("安装包超过大小限制")
                    if time.monotonic() - started > timeout:
                        raise InstallError("下载超时")
                    chunks.append(chunk)
                    if on_progress:
                        on_progress(size, total)
            if not chunks:
                raise InstallError("下载内容为空")
            return b"".join(chunks), url
        except Exception as exc:  # noqa: BLE001 - 依次尝试镜像
            last_error = str(exc) or exc.__class__.__name__
    raise InstallError(f"下载失败：{last_error}")


def _download_to_file(urls: list[str], dest: Path, timeout: float = 300.0,
                      max_bytes: int = 512 * 1024 * 1024,
                      on_progress=None) -> tuple[Path, str]:
    """流式下载到磁盘，避免大安装包占用大量内存。"""
    last_error = "未知错误"
    for url in urls:
        started = time.monotonic()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Moyu/1.23"})
            dest.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(request, timeout=30.0) as response, \
                    open(dest, "wb") as handle:
                total = int(response.headers.get("Content-Length") or 0)
                size = 0
                while True:
                    chunk = response.read(512 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise InstallError("安装包超过大小限制")
                    if time.monotonic() - started > timeout:
                        raise InstallError("下载超时")
                    handle.write(chunk)
                    if on_progress:
                        on_progress(size, total)
            if dest.stat().st_size <= 0:
                raise InstallError("下载内容为空")
            return dest, url
        except Exception as exc:  # noqa: BLE001 - 依次尝试镜像
            dest.unlink(missing_ok=True)
            last_error = str(exc) or exc.__class__.__name__
    raise InstallError(f"下载失败：{last_error}")


def _extract_zip_file(archive_path: Path, target: Path) -> Path:
    """解压 zip，若压缩包只有一个顶层目录则剥离它。"""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="moyu_", dir=str(DOWNLOAD_DIR)))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    continue
                archive.extract(info, temp)
        entries = [item for item in temp.iterdir() if item.name != "__MACOSX"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if len(entries) == 1 and entries[0].is_dir():
            shutil.move(str(entries[0]), str(target))
        else:
            shutil.move(str(temp), str(target))
            temp = None
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
    return target


def _extract_zip(data: bytes, target: Path) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = DOWNLOAD_DIR / f"moyu_{uuid.uuid4().hex[:10]}.zip"
    temp_file.write_bytes(data)
    try:
        return _extract_zip_file(temp_file, target)
    finally:
        temp_file.unlink(missing_ok=True)


def _download_and_extract(urls: list[str], target: Path, timeout: float = 300.0) -> Path:
    data, _ = _download(urls, timeout=timeout)
    return _extract_zip(data, target)


# -------------------------------------------------------------- env worker


def _system_python() -> str:
    candidates: list[str] = []
    launcher = shutil.which("py")
    if launcher:
        try:
            out = subprocess.run(
                [launcher, "-3", "-c", "import sys;print(sys.executable)"],
                capture_output=True, text=True, timeout=30,
            )
            if out.returncode == 0 and out.stdout.strip():
                candidates.append(out.stdout.strip().splitlines()[-1])
        except Exception:
            pass
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for exe in candidates:
        try:
            out = subprocess.run(
                [exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                capture_output=True, text=True, timeout=30,
            )
            if out.returncode != 0:
                continue
            version = tuple(int(part) for part in out.stdout.strip().split(".")[:2])
            if version >= (3, 10):
                return exe
        except Exception:
            continue
    return ""


def _run(cmd: list[str], timeout: float, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=env,
        encoding="utf-8", errors="replace",
    )


def _ensure_python(source: str, job_id: str) -> str:
    venv_python = Path(source) / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    base = _system_python()
    if not base:
        if not sys.platform.startswith("win"):
            raise InstallError("未找到 Python 3.10+，请先安装后再试")
        _step(job_id, "python", "running", f"正在下载 Python {PYTHON_VERSION} 安装包")
        data, _ = _download(PYTHON_URLS, timeout=300)
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        installer = DOWNLOAD_DIR / f"python-{PYTHON_VERSION}-amd64.exe"
        installer.write_bytes(data)
        target = RUNTIME_DIR / "python"
        _step(job_id, "python", "running", "正在静默安装 Python")
        process = _run(
            [
                str(installer), "/quiet", "InstallAllUsers=0", "PrependPath=0",
                "Include_pip=1", "Include_launcher=0", "Include_test=0",
                f"TargetDir={target}",
            ],
            timeout=900,
        )
        if process.returncode not in (0, 3010):
            raise InstallError(f"Python 安装失败：{process.returncode}")
        base = str(target / "python.exe")
        if not Path(base).exists():
            raise InstallError("Python 安装完成但未找到解释器")
    _step(job_id, "python", "running", "正在创建虚拟环境")
    process = _run([base, "-m", "venv", str(Path(source) / ".venv")], timeout=600)
    if process.returncode != 0:
        raise InstallError(f"创建虚拟环境失败：{process.stderr[-400:] or process.returncode}")
    venv_python = Path(source) / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = Path(source) / ".venv" / "bin" / "python"
    if not venv_python.exists():
        raise InstallError("虚拟环境创建后未找到 Python")
    return str(venv_python)


def _pip_install(python: str, requirements: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    last_error = ""
    for mirror in PIP_MIRRORS:
        cmd = [python, "-m", "pip", "install", "-r", str(requirements),
               "--disable-pip-version-check", "--no-input"]
        if mirror:
            cmd += ["-i", mirror]
        process = _run(cmd, timeout=1800, env=env)
        if process.returncode == 0:
            return
        last_error = (process.stderr or process.stdout or "")[-600:]
    raise InstallError(f"依赖安装失败：{last_error or 'pip 返回非零状态'}")


def install_environment(settings: dict) -> dict:
    """后台安装 AstrBot 源码、Python 与依赖。"""
    job = _new_job(
        "env",
        "安装 AstrBot 运行环境",
        [
            ("source", "获取 AstrBot 源码"),
            ("python", "准备 Python 运行环境"),
            ("deps", "安装依赖"),
            ("save", "写入环境设置"),
        ],
    )
    threading.Thread(
        target=_env_worker, args=(job["id"], dict(settings)), name="install-env", daemon=True
    ).start()
    return job


def _env_worker(job_id: str, settings: dict) -> None:
    try:
        _update(job_id, message="正在检查运行环境")
        source = deploy._find_source(settings)
        if source:
            _step(job_id, "source", "ok", f"复用已有源码：{source}")
        else:
            _step(job_id, "source", "running", "正在下载 AstrBot 源码（约 20MB）")
            target = Path(settings.get("runtime_dir") or RUNTIME_DIR) / "AstrBot"
            source = str(_download_and_extract(ASTRBOT_ZIP_URLS, target))
            if not (Path(source) / "main.py").exists():
                raise InstallError("下载的 AstrBot 包缺少 main.py")
            _step(job_id, "source", "ok", f"已安装到 {source}")

        _update(job_id, message="正在准备 Python")
        python = deploy._find_python(settings, source)
        if python:
            _step(job_id, "python", "ok", f"复用已有解释器：{python}")
        else:
            python = _ensure_python(source, job_id)
            _step(job_id, "python", "ok", f"已准备：{python}")

        _update(job_id, message="正在安装依赖，首次可能需要几分钟")
        _step(job_id, "deps", "running", "正在安装 requirements.txt")
        requirements = Path(source) / "requirements.txt"
        if requirements.exists():
            _pip_install(python, requirements)
            _step(job_id, "deps", "ok", "依赖已就绪")
        else:
            _step(job_id, "deps", "ok", "未发现 requirements.txt，跳过")

        _step(job_id, "save", "running")
        store.save_settings({"astrbot_source": source, "python_exe": python})
        _step(job_id, "save", "ok", "环境设置已保存")

        _update(job_id, state="done", message="运行环境已就绪", error="")
        _ok_event("运行环境已安装", {"source": source, "python": python})
    except Exception as exc:  # noqa: BLE001 - 后台任务把错误交给前端
        message = str(exc) or "环境安装失败"
        _fail_rest(job_id, message)
        _bad_event("运行环境安装失败", {"error": message})


# ----------------------------------------------------------- napcat worker


def _napcat_asset() -> tuple[str, str]:
    request = urllib.request.Request(
        NAPCAT_RELEASE_API,
        headers={"User-Agent": "Moyu/1.23", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        assets = [item for item in data.get("assets") or [] if isinstance(item, dict)]
        for item in assets:
            name = str(item.get("name") or "")
            if name.lower().endswith(".zip") and "shell" in name.lower():
                return str(item.get("browser_download_url") or ""), name
        for item in assets:
            name = str(item.get("name") or "")
            if name.lower().endswith(".zip"):
                return str(item.get("browser_download_url") or ""), name
    except Exception:
        pass
    return NAPCAT_FALLBACK[0], "NapCat.Shell.zip"


def _find_instance(instance_id: str) -> dict:
    for item in store.load_instances():
        if item.get("id") == instance_id:
            return item
    raise InstallError("找不到目标机器人")


def _save_instance(instance: dict) -> None:
    instances = store.load_instances()
    for index, item in enumerate(instances):
        if item.get("id") == instance.get("id"):
            instances[index] = instance
            break
    else:
        instances.append(instance)
    store.save_instances(instances)


def install_napcat(instance_id: str, settings: dict, qq: str = "",
                   start: bool = False) -> dict:
    """下载 NapCat、解压到独立目录并写入反向 WS 配置。"""
    _find_instance(instance_id)
    job = _new_job(
        "napcat",
        "安装 QQ 登录环境（NapCat）",
        [
            ("download", "下载 NapCat 最新版"),
            ("extract", "解压到机器人目录"),
            ("configure", "写入反向 WS 配置"),
        ],
        instance_id=instance_id,
    )
    threading.Thread(
        target=_napcat_worker,
        args=(job["id"], instance_id, qq, start),
        name="install-napcat", daemon=True,
    ).start()
    return job


def _napcat_worker(job_id: str, instance_id: str, qq: str, start: bool) -> None:
    try:
        instance = _find_instance(instance_id)
        code = str(qq or "").strip()
        if code:
            instance["qq"] = code
        existing = Path(instance.get("napcat_dir") or "")
        if runner.find_napcat_bat(existing, str(instance.get("qq") or "")) is not None:
            _step(job_id, "download", "ok", "已安装，跳过下载")
            _step(job_id, "extract", "ok", f"复用目录：{existing}")
        else:
            _update(job_id, message="正在获取 NapCat 最新版本")
            _step(job_id, "download", "running", "正在查询 GitHub 最新发行版")
            url, name = _napcat_asset()

            def progress(size: int, total: int) -> None:
                if total:
                    _step(job_id, "download", "running",
                          f"已下载 {size // 1048576}MB / {total // 1048576}MB")
                else:
                    _step(job_id, "download", "running", f"已下载 {size // 1048576}MB")

            candidates = [f"https://gh-proxy.com/{url}", f"https://ghproxy.net/{url}", url]
            for extra in NAPCAT_FALLBACK:
                if extra not in candidates:
                    candidates.append(extra)
            archive = DOWNLOAD_DIR / f"napcat-{uuid.uuid4().hex[:8]}.zip"
            path, used = _download_to_file(
                candidates, archive, timeout=240,
                max_bytes=512 * 1024 * 1024, on_progress=progress,
            )
            _step(job_id, "download", "ok", f"已下载 {name}")
            _step(job_id, "extract", "running", "正在解压")
            target = Path(settings.get("runtime_dir") or RUNTIME_DIR) / "napcat" / instance_id
            try:
                _extract_zip_file(path, target)
            finally:
                path.unlink(missing_ok=True)
            instance["napcat_dir"] = str(target)
            _step(job_id, "extract", "ok", f"已解压到 {target}")

        _update(job_id, message="正在写入配置")
        _step(job_id, "configure", "running")
        napcat_dir = Path(instance["napcat_dir"])
        config_dir = napcat_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        conf = config_dir / "napcat.json"
        if not conf.exists():
            conf.write_text("{}", encoding="utf-8")
        changes = creator.sync_napcat(instance)
        instance["napcat_port"] = int(instance.get("napcat_port") or 0)
        _save_instance(instance)
        detail = "；".join(changes) if changes else (
            "已写入反向 WS 配置" if instance.get("qq") else "QQ 号未填写，登录后自动同步"
        )
        _step(job_id, "configure", "ok", detail)

        started = False
        if start:
            try:
                runner.start_napcat(instance)
                started = True
            except Exception as exc:  # noqa: BLE001 - 启动失败不覆盖安装结果
                _update(job_id, error=f"NapCat 已安装，但启动失败：{exc}")
        message = "NapCat 已就绪" + ("，已尝试启动" if started else "")
        _update(job_id, state="done", message=message)
        _ok_event("NapCat 安装完成", {"dir": instance["napcat_dir"], "qq": instance.get("qq", "")})
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "NapCat 安装失败"
        _fail_rest(job_id, message)
        _bad_event("NapCat 安装失败", {"error": message})


# ------------------------------------------------------------ plugin worker


def _bundle_path() -> Path:
    return store.WEB_DIR / "assets" / "plugin_suite.zip"


def _bundle_names() -> list[str]:
    path = _bundle_path()
    if not path.exists():
        return []
    try:
        with zipfile.ZipFile(path) as archive:
            return [name.replace("\\", "/") for name in archive.namelist()]
    except Exception:
        return []


def _extract_bundled(plugin_id: str, target: Path, names: list[str]) -> bool:
    prefix = plugin_id + "/"
    selected = [name for name in names if name.startswith(prefix)]
    if not selected:
        return False
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(_bundle_path()) as archive:
        for raw in archive.namelist():
            name = raw.replace("\\", "/")
            if not name.startswith(prefix):
                continue
            relative = name[len(prefix):]
            if not relative or relative.endswith("/"):
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(raw))
    return (target / "main.py").exists()


def _install_from_repo(repo: str, target: Path) -> None:
    base = repo.rstrip("/")
    branches = [
        f"{base}/archive/refs/heads/main.zip",
        f"{base}/archive/refs/heads/master.zip",
    ]
    urls = []
    for branch in branches:
        urls.append(f"https://gh-proxy.com/{branch}")
        urls.append(f"https://ghproxy.net/{branch}")
        urls.append(branch)
    data, _ = _download(urls, timeout=180)
    temp = _extract_zip(data, target.parent / (target.name + "_tmp"))
    if (temp / "main.py").exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(temp), str(target))
        return
    roots = [item for item in temp.iterdir() if item.is_dir()]
    if len(roots) == 1 and (roots[0] / "main.py").exists():
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(roots[0]), str(target))
    shutil.rmtree(temp, ignore_errors=True)


def _install_plugin(plugin: dict, dest: Path, reference: Path,
                    bundle_names: list[str]) -> str:
    if (dest / "main.py").exists():
        return "已存在"
    source_dir = reference / plugin["id"]
    if source_dir.is_dir() and (source_dir / "main.py").exists():
        shutil.copytree(source_dir, dest, dirs_exist_ok=True)
        return "从本机 AstrBot 复制"
    if _extract_bundled(plugin["id"], dest, bundle_names):
        return "从管理器内置套装安装"
    repo = str(plugin.get("repo") or "")
    if repo:
        _install_from_repo(repo, dest)
        if (dest / "main.py").exists():
            return "从 GitHub 下载安装"
    raise InstallError("未找到可用的安装包")


def install_plugins(instance_id: str, settings: dict,
                    plugin_ids: list[str] | None = None) -> dict:
    """把管理器同款插件套装安装到指定机器人。"""
    _find_instance(instance_id)
    chosen = [
        item for item in SUITE
        if not plugin_ids or item["id"] in set(plugin_ids)
    ]
    if not chosen:
        raise InstallError("没有选择要安装的插件")
    job = _new_job(
        "plugins",
        "安装插件套装",
        [(item["id"], item["label"]) for item in chosen] + [("finish", "收尾")],
        instance_id=instance_id,
    )
    threading.Thread(
        target=_plugins_worker,
        args=(job["id"], instance_id, settings, chosen),
        name="install-plugins", daemon=True,
    ).start()
    return job


def _plugins_worker(job_id: str, instance_id: str, settings: dict,
                    plugins: list[dict]) -> None:
    try:
        instance = _find_instance(instance_id)
        root = Path(instance.get("root") or "")
        if not root.is_dir():
            raise InstallError("机器人目录不存在，请先启动一次机器人")
        plugins_dir = root / "data" / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        reference = Path(settings.get("astrbot_source") or "") / "data" / "plugins"
        bundle_names = _bundle_names()
        installed = 0
        failed = 0
        for plugin in plugins:
            _step(job_id, plugin["id"], "running")
            dest = plugins_dir / plugin["id"]
            try:
                detail = _install_plugin(plugin, dest, reference, bundle_names)
                _step(job_id, plugin["id"], "ok", detail)
                installed += 1
            except Exception as exc:  # noqa: BLE001 - 单个插件失败不影响其他插件
                _step(job_id, plugin["id"], "fail", str(exc))
                failed += 1
        _step(job_id, "finish", "running")
        instance["copied_plugins"] = int(instance.get("copied_plugins") or 0) + installed
        _save_instance(instance)
        _step(job_id, "finish", "ok", f"成功 {installed} 个，失败 {failed} 个")
        if installed:
            _update(job_id, state="done",
                    message=f"插件套装已安装（成功 {installed} 个）")
            _ok_event("插件套装安装完成", {"instance": instance_id, "installed": installed})
        else:
            raise InstallError("所有插件都未能安装，请检查网络或本机 AstrBot 目录")
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "插件安装失败"
        _fail_rest(job_id, message)
        _bad_event("插件套装安装失败", {"error": message})


# ----------------------------------------------------------------- status


def runtime_status(settings: dict, instances: list[dict] | None = None) -> dict:
    """首屏展示用：环境、可安装套装与已有 NapCat 数量。"""
    source = deploy._find_source(settings)
    python = deploy._find_python(settings, source)
    reference = Path(settings.get("astrbot_source") or "") / "data" / "plugins"
    bundle_names = _bundle_names()
    suite = []
    for item in SUITE:
        available = (
            (reference / item["id"]).is_dir()
            or any(name.startswith(item["id"] + "/") for name in bundle_names)
            or bool(item.get("repo"))
        )
        suite.append({
            "id": item["id"],
            "label": item["label"],
            "note": item.get("note", ""),
            "available": available,
        })
    bots = store.load_instances() if instances is None else instances
    napcat_ready = sum(1 for item in bots if Path(item.get("napcat_dir") or "").is_dir())
    return {
        "env": {
            "source_ok": bool(source),
            "source": source,
            "python_ok": bool(python),
            "python": python,
            "ready": bool(source and python),
        },
        "runtime_dir": str(RUNTIME_DIR),
        "suite": suite,
        "napcat": {"installed": napcat_ready, "total": len(bots)},
    }
