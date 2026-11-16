"""本地配置与实例注册表。"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

if getattr(sys, "frozen", False):
    # 打包后：程序目录即 exe 所在目录，静态资源来自 PyInstaller 解压目录；
    # 运行数据统一放在 %LOCALAPPDATA%\AstrBot舰队管理器\data
    BASE_DIR = Path(sys.executable).resolve().parent
    _BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    _BUNDLE_DIR = BASE_DIR
WEB_DIR = _BUNDLE_DIR / "web"

_DATA_STATE_FILES = ("instances.json", "settings.json", "auto_learn.json")


def _legacy_data_candidates() -> list[Path]:
    """历史版本可能存放 data 的位置，按“谁可能有数据”列举。"""
    candidates = [BASE_DIR / "data"]
    if not getattr(sys, "frozen", False):
        # 开发态运行时，打包版（dist）可能才是日常在用的那份
        candidates.append(BASE_DIR / "dist" / "AstrBot舰队管理器" / "data")
        candidates.append(BASE_DIR / "dist_build" / "AstrBot舰队管理器" / "data")
    return candidates


def _newest_legacy_state() -> Path | None:
    """在候选目录中挑 instances.json 最新的那个作为迁移源（即最近实际在用的）。"""
    best: tuple[float, Path] | None = None
    for path in _legacy_data_candidates():
        state = path / "instances.json"
        if state.exists():
            try:
                mtime = state.stat().st_mtime
            except Exception:
                continue
            if best is None or mtime > best[0]:
                best = (mtime, path)
    return best[1] if best else None


def _time_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _migrate_legacy(canonical: Path, legacy: Path) -> bool:
    try:
        canonical.mkdir(parents=True, exist_ok=True)
        for item in legacy.iterdir():
            target = canonical / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            elif not target.exists():
                shutil.copy2(item, target)
        marker = canonical / "MIGRATED_FROM.txt"
        if not marker.exists():
            marker.write_text(
                f"数据于 {_time_str()} 由旧目录迁移而来：{legacy}\n"
                "旧目录保留作备份，确认无误后可手动删除。\n",
                encoding="utf-8",
            )
        return True
    except Exception:
        return False


def _resolve_data_dir() -> Path:
    """统一数据目录：无论从源码还是打包 exe 启动，都用同一个位置，
    避免“开发态 / 打包态各存一份 instances.json”的双数据源问题。"""
    appdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        canonical = Path(appdata) / "AstrBot舰队管理器" / "data"
        has_state = any((canonical / name).exists() for name in _DATA_STATE_FILES)
        if not has_state:
            legacy = _newest_legacy_state()
            if legacy is not None:
                _migrate_legacy(canonical, legacy)
        return canonical
    return BASE_DIR / "data"


DATA_DIR = _resolve_data_dir()
SETTINGS_PATH = DATA_DIR / "settings.json"
INSTANCES_PATH = DATA_DIR / "instances.json"
MARKET_CACHE_PATH = DATA_DIR / "market_index.json"

DEFAULT_SETTINGS = {
    "astrbot_source": "",
    "python_exe": "",
    "instances_dir": str(BASE_DIR / "instances"),
    "scan_dir": "",
    "default_proxy": "",
    "napcat_auto_relogin": True,
    "alert_push_enabled": False,
    "alert_webhook_url": "",
    "alert_telegram_token": "",
    "alert_telegram_chat_id": "",
    "alert_min_severity": "warning",
    "offsite_enabled": False,
    "offsite_url": "",
    "offsite_user": "",
    "offsite_password": "",
    "offsite_dir": "muyu-backups",
    "offsite_keep": 5,
}

PALETTE = [
    "#5b8cff",
    "#22d3ee",
    "#a78bfa",
    "#f472b6",
    "#34d399",
    "#fbbf24",
    "#fb7185",
    "#38bdf8",
]


def read_json(path: Path, default):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        return json.loads(text)
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


# ---------------------------------------------------------------- settings


def load_settings() -> dict:
    data = read_json(SETTINGS_PATH, {})
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        merged.update({k: v for k, v in data.items() if v is not None})
    return merged


def save_settings(patch: dict) -> dict:
    current = load_settings()
    for key in DEFAULT_SETTINGS:
        if key not in patch:
            continue
        value = patch[key]
        if isinstance(value, str):
            current[key] = value.strip()
        elif isinstance(value, bool):
            current[key] = value
        elif isinstance(value, int):
            current[key] = max(0, value)
    write_json(SETTINGS_PATH, current)
    return current


# --------------------------------------------------------------- instances


def load_instances() -> list[dict]:
    data = read_json(INSTANCES_PATH, [])
    if isinstance(data, dict):
        data = data.get("instances", [])
    if not isinstance(data, list):
        return []
    cleaned = []
    for item in data:
        if isinstance(item, dict) and item.get("id") and item.get("root"):
            item.setdefault("name", item["id"])
            item.setdefault("ws_port", 0)
            item.setdefault("dash_port", 6185)
            item.setdefault("color", PALETTE[len(cleaned) % len(PALETTE)])
            cleaned.append(item)
    return cleaned


def save_instances(items: list[dict]) -> None:
    write_json(INSTANCES_PATH, items)


def get_instance(instances: list[dict], inst_id: str) -> dict | None:
    for item in instances:
        if item.get("id") == inst_id:
            return item
    return None


def public_instance(item: dict) -> dict:
    """返回给前端的安全视图（不含密码与反向 WS Token）。"""
    out = {k: v for k, v in item.items() if k not in {"dash_pass", "pid", "ws_token"}}
    out["has_password"] = bool(item.get("dash_pass"))
    out["has_ws_token"] = bool(item.get("ws_token"))
    return out


# ---------------------------------------------------------------- discovery


def _read_dashboard_password(root: Path) -> str:
    """从旧版部署的 后台.txt 中读取管理面板密码（仅本机使用，不外传）。"""
    for name in ("后台.txt", "密码.txt", "accounts.txt"):
        path = root.parent / name
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except Exception:
                continue
            match = re.search(r"密码[:：]\s*(\S+)", text)
            if match:
                return match.group(1).strip()
    return ""


def _parse_cmd_config(root: Path) -> dict:
    cfg = read_json(root / "data" / "cmd_config.json", {})
    if not isinstance(cfg, dict):
        return {}
    dash = cfg.get("dashboard") or {}
    platforms = [
        p
        for p in (cfg.get("platform") or [])
        if isinstance(p, dict) and p.get("type") == "aiocqhttp"
    ]
    first = platforms[0] if platforms else {}
    name = str(first.get("id") or root.name)
    return {
        "name": name,
        "dash_port": int(dash.get("port") or 6185),
        "dash_user": str(dash.get("username") or "astrbot"),
        "ws_port": int(first.get("ws_reverse_port") or 0),
        "ws_token": str(first.get("ws_reverse_token") or ""),
        "platform_id": str(first.get("id") or ""),
        "platforms": [p.get("id") for p in platforms],
    }


def discover_roots(scan_dir: str, source_dir: str) -> list[Path]:
    roots: list[Path] = []
    base = Path(scan_dir) if scan_dir else None
    if base and base.exists():
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            if (child / "data" / "cmd_config.json").exists():
                roots.append(child.resolve())
    src = Path(source_dir)
    if src.exists() and (src / "data" / "cmd_config.json").exists():
        if src.resolve() not in roots:
            roots.insert(0, src.resolve())
    return roots


def seed_instances(settings: dict) -> list[dict]:
    """首次运行时自动发现本机已有的 AstrBot 实例。"""
    instances = load_instances()
    if instances:
        return instances

    used_names: set[str] = set()
    used_qqs: set[str] = set()
    for root in discover_roots(settings.get("scan_dir", ""), settings.get("astrbot_source", "")):
        info = _parse_cmd_config(root)
        if not info:
            continue
        name = next(
            (p for p in info.get("platforms", []) if p and p not in used_names),
            info["name"] or root.name,
        )
        used_names.add(name)
        napcat_dir, qq = _discover_napcat(root, used_qqs)
        if qq:
            used_qqs.add(qq)
        instances.append(
            {
                "id": uuid.uuid4().hex[:8],
                "name": name,
                "qq": qq,
                "root": str(root),
                "dash_port": info["dash_port"],
                "dash_user": info["dash_user"],
                "dash_pass": _read_dashboard_password(root),
                "ws_port": info["ws_port"],
                "ws_token": info["ws_token"],
                "platform_id": info.get("platform_id") or name,
                "napcat_dir": napcat_dir,
                "napcat_port": 0,
                "color": PALETTE[len(instances) % len(PALETTE)],
                "note": "自动发现",
                "created_at": "",
                "source": "discovered",
            }
        )
    if instances:
        save_instances(instances)
    return instances


def _discover_napcat(root: Path, used_qqs: set[str]) -> tuple[str, str]:
    """定位同级的 NapCat 目录，并尽量推断已登录的 QQ 号。"""
    base = root.parent
    candidates: list[Path] = []
    try:
        candidates = [
            child
            for child in base.iterdir()
            if child.is_dir() and child.name.lower().startswith("napcat")
        ]
    except Exception:
        return "", ""
    if not candidates:
        return "", ""
    candidates.sort(key=lambda p: p.name)
    # 优先同序号目录：AstrBot2 -> NapCat2
    suffix = re.sub(r"\D", "", root.name)
    napcat = next(
        (c for c in candidates if suffix and c.name.endswith(suffix)),
        candidates[0],
    )

    qqs: list[str] = []
    try:
        for file in napcat.rglob("napcat_*.json"):
            if "_protocol_" in file.name:
                continue
            match = re.fullmatch(r"napcat_(\d+)\.json", file.name)
            if match:
                qqs.append(match.group(1))
    except Exception:
        pass
    qqs.sort()
    qq = next((q for q in qqs if q not in used_qqs), qqs[0] if qqs else "")
    return str(napcat), qq


def next_port(used: set[int], start: int, limit: int = 200) -> int:
    port = start
    while port < start + limit:
        if port not in used:
            return port
        port += 1
    return start


def load_market_index() -> dict:
    data = read_json(MARKET_CACHE_PATH, {})
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return {}


def ensure_market_index(settings: dict) -> dict:
    index = load_market_index()
    source = Path(settings.get("astrbot_source", "")) / "data" / "plugins.json"
    # 源索引比本地缓存新（AstrBot 更新过插件市场）时，自动同步缓存
    if source.exists():
        try:
            cache_stale = (
                not MARKET_CACHE_PATH.exists()
                or source.stat().st_mtime > MARKET_CACHE_PATH.stat().st_mtime
            )
        except Exception:
            cache_stale = False
        if cache_stale:
            raw = read_json(source, {})
            if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
                write_json(MARKET_CACHE_PATH, raw)
                return raw["data"]
    if index:
        return index
    raw = read_json(source, {})
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        write_json(MARKET_CACHE_PATH, raw)
        return raw["data"]
    return {}
