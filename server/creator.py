"""从模板实例创建新的机器人实例（ASTRBOT_ROOT 隔离）。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import string
import time
import uuid
from pathlib import Path

from . import dashboard
from .store import PALETTE, next_port, read_json, write_json

DEFAULT_PERSONA = """你是{name}，一位在QQ群里陪着大家聊天、也偶尔冒个泡的AI伙伴。

性格：松弛、有点幽默，不端着。遇到不懂的会直接说不懂，不硬编。
说话风格：中文短句，口语化，偶尔用一点语气词；不要用"作为一个AI模型"这类开头，不要长篇大论地列要点。
边界：不主动惹事、不参与人身攻击、不输出违规内容；被问到敏感问题时温和转移话题。"""


class CreateError(Exception):
    pass


def _slugify(name: str) -> str:
    """实例目录/ID 只用 ASCII，避免 URL 与命令行编码问题。"""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    return slug or f"bot-{uuid.uuid4().hex[:4]}"


def _unique_id(base: str, instances: list[dict]) -> str:
    existing = {item.get("id") for item in instances}
    if base not in existing:
        return base
    idx = 2
    while f"{base}-{idx}" in existing:
        idx += 1
    return f"{base}-{idx}"


def _template(payload: dict, instances: list[dict]) -> dict:
    template_id = payload.get("template_id")
    if template_id:
        for item in instances:
            if item.get("id") == template_id:
                return item
        raise CreateError("所选模板机器人不存在")
    if not instances:
        raise CreateError("还没有任何可用实例，请先接入一个已有的 AstrBot")
    return instances[0]


def _used_ports(instances: list[dict]) -> tuple[set[int], set[int]]:
    dash = {int(i.get("dash_port") or 0) for i in instances}
    ws = {int(i.get("ws_port") or 0) for i in instances}
    return dash, ws


def create_instance(payload: dict, settings: dict, instances: list[dict]) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise CreateError("请填写机器人名称")
    if len(name) > 24:
        raise CreateError("机器人名称过长（最多 24 个字符）")

    template = _template(payload, instances)
    tpl_data = Path(template["root"]) / "data"
    tpl_cfg_path = tpl_data / "cmd_config.json"
    if not tpl_cfg_path.exists():
        raise CreateError(f"模板实例缺少配置文件：{tpl_cfg_path}")

    dash_used, ws_used = _used_ports(instances)
    dash_port = int(payload.get("dash_port") or 0) or next_port(dash_used, 6187)
    ws_port = int(payload.get("ws_port") or 0) or next_port(ws_used, 6200)
    if dash_port in dash_used:
        raise CreateError(f"Dashboard 端口 {dash_port} 已被占用")
    if ws_port in ws_used:
        raise CreateError(f"QQ 反向 WS 端口 {ws_port} 已被占用")

    inst_id = _unique_id(_slugify(name), instances)
    root = Path(
        str(payload.get("root") or "").strip()
        or Path(settings.get("instances_dir", str(Path.home()))) / inst_id
    )
    data_dir = root / "data"
    if root.exists() and any(root.iterdir()):
        raise CreateError(f"目录已存在且不为空：{root}")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)

    # 1. Dashboard 静态资源（离线可用）
    tpl_dist = tpl_data / "dist"
    if tpl_dist.exists():
        shutil.copytree(tpl_dist, data_dir / "dist", dirs_exist_ok=True)
    for extra in ("plugins.json", "skills.json"):
        if (tpl_data / extra).exists():
            shutil.copy2(tpl_data / extra, data_dir / extra)

    # 2. 可选：克隆插件与插件配置
    copied_plugins = 0
    if payload.get("copy_plugins"):
        tpl_plugins = tpl_data / "plugins"
        if tpl_plugins.exists():
            shutil.copytree(tpl_plugins, data_dir / "plugins", dirs_exist_ok=True)
            copied_plugins = len([p for p in (data_dir / "plugins").iterdir() if p.is_dir()])
        tpl_conf = tpl_data / "config"
        if tpl_conf.exists():
            shutil.copytree(tpl_conf, data_dir / "config", dirs_exist_ok=True)

    # 3. 生成 cmd_config.json
    cfg = read_json(tpl_cfg_path, {})
    if not isinstance(cfg, dict) or not cfg:
        raise CreateError("模板配置读取失败")
    dash = cfg.setdefault("dashboard", {})
    dash["enable"] = True
    dash["host"] = "127.0.0.1"
    dash["port"] = dash_port
    dash["jwt_secret"] = secrets.token_hex(32)

    qq = str(payload.get("qq") or "").strip()
    token = secrets.token_urlsafe(12)
    cfg["platform"] = [
        {
            "id": name,
            "type": "aiocqhttp",
            "enable": True,
            "ws_reverse_host": "127.0.0.1",
            "ws_reverse_port": ws_port,
            "ws_reverse_token": token,
        }
    ]

    ps = cfg.setdefault("platform_settings", {})
    ps["id_whitelist"] = []
    ps["enable_id_white_list"] = False
    ps["unique_session"] = False

    cfg["admins_id"] = [qq] if qq else []
    agent = cfg.setdefault("agent_runner", {})
    agent_cfg = agent.setdefault("config", {})
    agent_cfg.setdefault("persona", {})["persona_id"] = name
    provider_id = str(payload.get("provider_id") or "").strip()
    if provider_id:
        agent_cfg.setdefault("model", {})["provider_id"] = provider_id

    write_json(data_dir / "cmd_config.json", cfg)

    instance = {
        "id": inst_id,
        "name": name,
        "qq": qq,
        "root": str(root),
        "dash_port": dash_port,
        "dash_user": str(template.get("dash_user") or "astrbot"),
        "dash_pass": str(template.get("dash_pass") or ""),
        "ws_port": ws_port,
        "ws_token": token,
        "platform_id": name,
        "napcat_dir": str(payload.get("napcat_dir") or ""),
        "napcat_port": int(payload.get("napcat_port") or 0),
        "persona_prompt": str(payload.get("persona_prompt") or DEFAULT_PERSONA.format(name=name)),
        "color": PALETTE[len(instances) % len(PALETTE)],
        "note": str(payload.get("note") or ""),
        "template": template.get("id"),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "copied_plugins": copied_plugins,
        "source": "created",
        "provisioned": False,
    }
    return instance


def _new_dashboard_password() -> str:
    """生成满足 AstrBot 复杂度要求的管理面板密码。"""
    alphabet = string.ascii_letters + string.digits
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        *(secrets.choice(alphabet) for _ in range(13)),
    ]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _password_hashes(password: str) -> tuple[str, str]:
    """按 AstrBot 的存储格式生成 PBKDF2 与 MD5 两套哈希。"""
    iterations = 600000
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    ).hex()
    pbkdf2 = f"pbkdf2_sha256${iterations}${salt}${digest}"
    md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
    return pbkdf2, md5


def create_bootstrap_instance(
    payload: dict,
    settings: dict,
    instances: list[dict],
    source: str | Path,
) -> dict:
    """没有任何模板实例时，直接基于 AstrBot 源码生成第一个机器人。"""
    name = str(payload.get("name") or "我的机器人").strip()
    if not name:
        raise CreateError("请填写机器人名称")
    if len(name) > 24:
        raise CreateError("机器人名称过长（最多 24 个字符）")

    provider = payload.get("provider_config")
    if not isinstance(provider, dict) or not provider.get("id"):
        raise CreateError("缺少模型配置，无法创建机器人")

    dash_used, ws_used = _used_ports(instances)
    dash_port = int(payload.get("dash_port") or 0) or next_port(dash_used, 6187)
    ws_port = int(payload.get("ws_port") or 0) or next_port(ws_used, 6200)
    if dash_port in dash_used:
        raise CreateError(f"Dashboard 端口 {dash_port} 已被占用")
    if ws_port in ws_used:
        raise CreateError(f"QQ 反向 WS 端口 {ws_port} 已被占用")

    inst_id = _unique_id(_slugify(name), instances)
    root = Path(
        str(payload.get("root") or "").strip()
        or Path(settings.get("instances_dir", str(Path.home()))) / inst_id
    )
    data_dir = root / "data"
    if root.exists() and any(root.iterdir()):
        raise CreateError(f"目录已存在且不为空：{root}")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)

    src_data = Path(source) / "data"
    tpl_dist = src_data / "dist"
    if tpl_dist.exists():
        shutil.copytree(tpl_dist, data_dir / "dist", dirs_exist_ok=True)
    for extra in ("plugins.json", "skills.json"):
        if (src_data / extra).exists():
            shutil.copy2(src_data / extra, data_dir / extra)

    base_cfg = read_json(src_data / "cmd_config.json", {}) if src_data.exists() else {}
    cfg = dict(base_cfg) if isinstance(base_cfg, dict) else {}

    password = _new_dashboard_password()
    pbkdf2, md5 = _password_hashes(password)
    dash = cfg.setdefault("dashboard", {})
    dash.update(
        {
            "enable": True,
            "host": "127.0.0.1",
            "port": dash_port,
            "username": "astrbot",
            "jwt_secret": secrets.token_hex(32),
            "pbkdf2_password": pbkdf2,
            "password": md5,
            "password_storage_upgraded": True,
            "password_change_required": False,
        }
    )

    qq = str(payload.get("qq") or "").strip()
    token = secrets.token_urlsafe(12)
    cfg["platform"] = [
        {
            "id": name,
            "type": "aiocqhttp",
            "enable": True,
            "ws_reverse_host": "127.0.0.1",
            "ws_reverse_port": ws_port,
            "ws_reverse_token": token,
        }
    ]
    ps = cfg.setdefault("platform_settings", {})
    ps["id_whitelist"] = []
    ps["enable_id_white_list"] = False
    ps["unique_session"] = False
    cfg["admins_id"] = [qq] if qq else []

    agent = cfg.setdefault("agent_runner", {})
    agent_cfg = agent.setdefault("config", {})
    agent_cfg.setdefault("persona", {})["persona_id"] = name
    agent_cfg.setdefault("model", {})["provider_id"] = str(provider["id"])

    cfg["provider"] = [dict(provider)]
    cfg["provider_sources"] = []
    psettings = cfg.setdefault("provider_settings", {})
    psettings["provider_pool"] = ["*"]
    psettings["web_search"] = False

    write_json(data_dir / "cmd_config.json", cfg)

    instance = {
        "id": inst_id,
        "name": name,
        "qq": qq,
        "root": str(root),
        "dash_port": dash_port,
        "dash_user": "astrbot",
        "dash_pass": password,
        "ws_port": ws_port,
        "ws_token": token,
        "platform_id": name,
        "napcat_dir": "",
        "napcat_port": 0,
        "persona_prompt": str(
            payload.get("persona_prompt") or DEFAULT_PERSONA.format(name=name)
        ),
        "color": PALETTE[len(instances) % len(PALETTE)],
        "note": "一键部署",
        "template": None,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "copied_plugins": 0,
        "source": "deployed",
        "provider_id": str(provider["id"]),
        "provisioned": False,
    }
    return instance


def sync_platform(inst: dict) -> list[str]:
    """启动前把实例根目录里的 QQ 适配器对齐到实例配置，清理重复适配器。"""
    changes: list[str] = []
    root = Path(inst.get("root") or "")
    cfg_path = root / "data" / "cmd_config.json"
    if not cfg_path.exists():
        return changes
    cfg = read_json(cfg_path, {})
    if not isinstance(cfg, dict):
        return changes
    name = str(inst.get("name") or "").strip() or "Bot"
    port = int(inst.get("ws_port") or 0)
    token = str(inst.get("ws_token") or "")
    if not port:
        return changes

    items = [p for p in (cfg.get("platform") or []) if isinstance(p, dict)]
    aiocq = [p for p in items if p.get("type") == "aiocqhttp"]
    # 显示名可以改，平台 id 不能跟着改：白名单和各插件里写死的 UMO 都依赖它。
    keep = next(
        (p for p in aiocq if p.get("id") == str(inst.get("platform_id") or name)),
        None,
    )
    if keep is None:
        keep = next((p for p in aiocq if p.get("id") == name), None)
    if keep is None and aiocq:
        keep = aiocq[0]
    platform_id = str(inst.get("platform_id") or keep.get("id") if keep else name).strip() or name
    inst["platform_id"] = platform_id
    if keep is None:
        keep = {"id": platform_id, "type": "aiocqhttp", "enable": True}
        items.append(keep)
        aiocq.append(keep)
        changes.append("新增 QQ 适配器")
    expected = {
        "id": platform_id,
        "type": "aiocqhttp",
        "enable": True,
        "ws_reverse_host": "127.0.0.1",
        "ws_reverse_port": port,
        "ws_reverse_token": token,
    }
    if any(keep.get(k) != v for k, v in expected.items()):
        keep.update(expected)
        changes.append("修正 QQ 适配器参数")
    duplicates = [p for p in aiocq if p is not keep]
    if duplicates:
        items = [p for p in items if not any(p is dup for dup in duplicates)]
        changes.append(f"清理重复 QQ 适配器 {len(duplicates)} 个")

    # 白名单：修正会话 ID 的平台前缀，避免复制来的配置把消息全部拦掉
    ps = cfg.get("platform_settings")
    if isinstance(ps, dict):
        allow = ps.get("id_whitelist")
        if isinstance(allow, list) and allow:
            fixed: list[str] = []
            for item in allow:
                text = str(item)
                if ":" in text:
                    prefix, rest = text.split(":", 1)
                    if prefix != platform_id:
                        text = f"{platform_id}:{rest}"
                if text not in fixed:
                    fixed.append(text)
            if fixed != allow:
                ps["id_whitelist"] = fixed
                changes.append("修正白名单会话前缀")
        elif ps.get("enable_id_white_list"):
            ps["enable_id_white_list"] = False
            changes.append("关闭空白名单")

    if changes:
        cfg["platform"] = items
        write_json(cfg_path, cfg)
    return changes


def sync_napcat(inst: dict) -> list[str]:
    """把 NapCat 的 OneBot11 反向 WS 客户端对齐到实例的 WS 端口与 token。"""
    changes: list[str] = []
    napcat = Path(inst.get("napcat_dir") or "")
    qq = str(inst.get("qq") or "").strip()
    port = int(inst.get("ws_port") or 0)
    token = str(inst.get("ws_token") or "")
    if not napcat.is_dir() or not qq or not port:
        return changes

    targets = sorted(napcat.rglob(f"onebot11_{qq}.json"))
    if targets:
        target = targets[0]
        data = read_json(target, {})
    else:
        conf_dirs = [p.parent for p in napcat.rglob("napcat.json")]
        if not conf_dirs:
            return changes
        target = conf_dirs[0] / f"onebot11_{qq}.json"
        data = {}
    if not isinstance(data, dict):
        data = {}
    network = data.get("network")
    if not isinstance(network, dict):
        network = data["network"] = {}
    clients = network.get("websocketClients")
    if not isinstance(clients, list):
        clients = network["websocketClients"] = []
    entry = next(
        (c for c in clients if isinstance(c, dict) and c.get("name") == "AstrBot"), None
    )
    if entry is None:
        entry = next(
            (
                c
                for c in clients
                if isinstance(c, dict) and str(c.get("url", "")).endswith("/ws")
            ),
            None,
        )
    if entry is None:
        entry = {
            "name": "AstrBot",
            "messagePostFormat": "array",
            "reportSelfMessage": False,
            "reconnectInterval": 1000,
            "debug": False,
            "heartInterval": 1000,
        }
        clients.append(entry)
        changes.append("新增 NapCat 反向 WS 客户端")

    expected = {"url": f"ws://127.0.0.1:{port}/ws", "token": token, "enable": True}
    if any(entry.get(k) != v for k, v in expected.items()):
        entry.update(expected)
        changes.append("修正 NapCat 反向 WS 参数")
    for other in clients:
        if other is entry or not isinstance(other, dict):
            continue
        if other.get("enable") and str(other.get("url", "")) == expected["url"]:
            other["enable"] = False
            changes.append("禁用重复的反向 WS 客户端")

    if changes:
        write_json(target, data)
    return changes


def provision(inst: dict, timeout: float = 180.0) -> dict:
    """实例首次启动后：等待 Dashboard 就绪，创建人格并绑定默认配置档。"""
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            dashboard.login(inst, force=True)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2.0)
    else:
        return {"ok": False, "message": f"Dashboard 未就绪：{last_error}"}

    result: dict = {"ok": True, "steps": []}
    persona_id = inst.get("name") or "默认人格"
    prompt = inst.get("persona_prompt") or ""
    persona_ready = False

    try:
        existing = dashboard.call(inst, "GET", "personas")
        names = {p.get("persona_id") for p in (existing.get("data") or []) if isinstance(p, dict)}
        if persona_id in names:
            persona_ready = True
            result["steps"].append("人格已存在")
        elif prompt:
            dashboard.call(
                inst,
                "POST",
                "personas",
                {"persona_id": persona_id, "system_prompt": prompt, "begin_dialogs": []},
            )
            persona_ready = True
            result["steps"].append("已创建人格")
        else:
            result["steps"].append("缺少人格提示词，跳过人格创建")
    except Exception as exc:  # noqa: BLE001
        result["steps"].append(f"人格创建失败：{exc}")

    if not persona_ready:
        return result

    try:
        profile = dashboard.call(inst, "GET", "config-profiles/default")
        config = (profile.get("data") or {}).get("config")
        if isinstance(config, dict):
            agent = config.setdefault("agent_runner", {})
            persona_cfg = agent.setdefault("config", {}).setdefault("persona", {})
            if persona_cfg.get("persona_id") == persona_id:
                result["steps"].append("默认配置档已绑定")
            else:
                persona_cfg["persona_id"] = persona_id
                # Dashboard 的 PUT 接口 body 即为配置本体（不包一层 config）
                dashboard.call(inst, "PUT", "config-profiles/default", config)
                result["steps"].append("已绑定默认配置档")
    except Exception as exc:  # noqa: BLE001
        result["steps"].append(f"配置档绑定失败：{exc}")

    return result
