"""Read-only fleet health aggregation.

The manager's health surface deliberately does not repair anything.  Every
probe is bounded and an unavailable component is represented as data instead
of raising through the API.
"""

from __future__ import annotations

import concurrent.futures
import copy
import os
import shutil
import threading
import time
from typing import Callable

from . import (
    consoles,
    dsh as dsh_mod,
    memory,
    runner as runner_mod,
    store,
    watchdog as watchdog_mod,
)

HEALTH_CACHE_SECONDS = 5
CHECK_TIMEOUT = 8.0

_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}


def reset_cache() -> None:
    with _cache_lock:
        _cache["at"] = 0.0
        _cache["data"] = None


def component(
    component_id: str,
    label: str,
    status: str,
    summary: str,
    detail: dict | None = None,
    route: str = "",
    actions: list[dict] | None = None,
) -> dict:
    return {
        "id": str(component_id),
        "label": str(label),
        "status": status if status in {"ok", "warn", "bad"} else "warn",
        "summary": str(summary),
        "detail": detail or {},
        "route": route,
        "actions": actions or [],
    }


def overall_status(components: list[dict]) -> str:
    statuses = {str(row.get("status") or "warn") for row in components}
    if "bad" in statuses:
        return "bad"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _error_component(check_id: str, exc: BaseException) -> dict:
    return component(
        check_id,
        check_id,
        "bad",
        f"{type(exc).__name__}: {str(exc)[:240]}",
    )


def _normalize_rows(value) -> list[dict]:
    if value is None:
        return []
    rows = value if isinstance(value, list) else [value]
    return [row for row in rows if isinstance(row, dict) and row.get("id")]


def collect_health(
    force: bool = False,
    checks: list[tuple[str, Callable[[], dict | list[dict] | None]]] | None = None,
    timeout: float = CHECK_TIMEOUT,
) -> dict:
    now = time.time()
    if not force:
        with _cache_lock:
            cached = _cache["data"]
            if cached is not None and now - _cache["at"] < HEALTH_CACHE_SECONDS:
                return copy.deepcopy(cached)

    selected = list(checks if checks is not None else default_checks())
    components: list[dict] = []
    if selected:
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(8, max(1, len(selected))),
            thread_name_prefix="fleet-health",
        )
        futures = {
            executor.submit(check): index
            for index, (_check_id, check) in enumerate(selected)
        }
        done, not_done = concurrent.futures.wait(futures, timeout=timeout)
        by_index: dict[int, list[dict]] = {}
        for future in done:
            index = futures[future]
            check_id = selected[index][0]
            try:
                by_index[index] = _normalize_rows(future.result())
            except Exception as exc:  # noqa: BLE001
                by_index[index] = [_error_component(check_id, exc)]
        for future in not_done:
            index = futures[future]
            check_id = selected[index][0]
            by_index[index] = [
                component(
                    check_id,
                    check_id,
                    "bad",
                    f"检查超时（{timeout:g} 秒）",
                )
            ]
        for index in range(len(selected)):
            components.extend(by_index.get(index, []))
        executor.shutdown(wait=False, cancel_futures=True)

    data = {
        "overall": overall_status(components),
        "generated_at": now,
        "cache_seconds": HEALTH_CACHE_SECONDS,
        "components": components,
    }
    with _cache_lock:
        _cache["at"] = now
        _cache["data"] = copy.deepcopy(data)
    return data


def check_manager() -> dict:
    path = store.DATA_DIR
    writable = path.is_dir() and os.access(path, os.W_OK)
    return component(
        "manager",
        "管理器",
        "ok" if writable else "bad",
        "数据目录可写" if writable else f"数据目录不可写：{path}",
        {"data_dir": str(path), "writable": writable},
    )


def check_dsh() -> dict:
    try:
        status = dsh_mod.public_status(
            include_counts=False, log_lines=0, prepare_overlay=False
        )
    except Exception as exc:  # noqa: BLE001
        return _error_component("dsh", exc)
    installed = bool(status.get("installed"))
    running = bool(status.get("running"))
    ready = bool(status.get("ready"))
    if not installed:
        level, summary = "bad", "未检测到 DSH"
    elif running and ready:
        level, summary = "ok", f"v{status.get('version') or '?'} · {status.get('port')} ready"
    elif running:
        level, summary = "bad", "DSH 端口已占用但未就绪"
    else:
        level, summary = "warn", "DSH 未运行"
    return component(
        "dsh",
        "DSH",
        level,
        summary,
        {
            "version": status.get("version") or "",
            "port": status.get("port"),
            "managed": bool(status.get("managed")),
            "overlay_active": bool(status.get("overlay_active")),
            "error": status.get("error") or "",
        },
        route="#/dsh",
    )


def check_market() -> dict:
    path = store.MARKET_CACHE_PATH
    if not path.exists():
        return component(
            "market",
            "插件市场索引",
            "warn",
            "市场索引尚未生成",
            {"path": str(path)},
            route="#/market",
        )
    age_days = max(0.0, (time.time() - path.stat().st_mtime) / 86400)
    level = "ok" if age_days < 7 else "warn"
    return component(
        "market",
        "插件市场索引",
        level,
        f"{age_days:.1f} 天前更新",
        {"path": str(path), "age_days": round(age_days, 2)},
        route="#/market",
    )


def check_disk() -> dict:
    usage = shutil.disk_usage(store.DATA_DIR)
    free_ratio = usage.free / usage.total if usage.total else 0.0
    level = "ok" if free_ratio >= 0.10 else "warn"
    if free_ratio < 0.03:
        level = "bad"
    return component(
        "disk",
        "数据磁盘",
        level,
        f"可用 {usage.free / (1024 ** 3):.1f} GB（{free_ratio * 100:.1f}%）",
        {
            "total": usage.total,
            "free": usage.free,
            "percent_free": round(free_ratio * 100, 2),
        },
        route="#/settings",
    )


def _instance_identity(inst: dict) -> str:
    return str(inst.get("id") or inst.get("name") or "unknown")


def douyin_health(data: dict) -> tuple[str, str, dict]:
    binding = (data.get("binding") or {}).get("peer") or {}
    peer = str(binding.get("name") or "")
    last_error = str(data.get("last_error") or "")
    browser = bool(data.get("browser_running"))
    auto = bool(data.get("auto_reply_enabled"))
    whitelist = data.get("private_whitelist") or []
    if last_error:
        level, summary = "warn", f"插件错误：{last_error[:120]}"
    elif not binding:
        level, summary = "warn", "未绑定私信"
    elif auto and not browser:
        level, summary = "warn", "自动回复开启但浏览器未运行"
    elif auto:
        level, summary = "ok", f"监听中 · {peer or '已绑定'}"
    else:
        level, summary = "warn", f"已绑定 · 自动回复暂停（{peer or '未命名'}）"
    return level, summary, {
        "state": data.get("state"),
        "browser_running": browser,
        "auto_reply_enabled": auto,
        "binding_peer": peer,
        "private_whitelist": len(whitelist) if isinstance(whitelist, list) else 0,
        "last_error": last_error,
    }


def bili_stats(data: dict) -> dict:
    """兼容 B站插件两种返回：顶层字段，或包在 stats 里。"""
    if not isinstance(data, dict):
        return {}
    nested = data.get("stats")
    if isinstance(nested, dict) and (
        "account_connected" in nested or "running" in nested
    ):
        return nested
    return data


def bili_health(stats: dict) -> tuple[str, str, dict]:
    stats = stats or {}
    connected = bool(stats.get("account_connected"))
    running = bool(stats.get("running"))
    failed_today = int(stats.get("failed_today") or 0)
    private_replies = int(stats.get("private_replies_today") or 0)
    raw_warnings = stats.get("warnings") or []
    warnings = [
        item
        for item in (raw_warnings if isinstance(raw_warnings, list) else [])
        if not isinstance(item, dict)
        or str(item.get("level") or "").lower() not in {"success", "ok", "info"}
    ]
    if not connected:
        level, summary = "bad", "B站账号未连接"
    elif not running:
        level, summary = "warn", "B站账号已连接 · 后台任务未运行"
    elif failed_today:
        level, summary = "warn", f"B站今日失败 {failed_today} 次"
    elif warnings:
        level, summary = "warn", str((warnings[0] or {}).get("detail") or (warnings[0] or {}).get("title") or "插件告警")[:160]
    else:
        level, summary = "ok", f"B站已连接 · 私信回复 {private_replies} 条"
    return level, summary, {
        "account_connected": connected,
        "running": running,
        "failed_today": failed_today,
        "private_replies_today": private_replies,
        "warnings": len(warnings),
    }


def check_instance(inst: dict) -> list[dict]:
    iid = _instance_identity(inst)
    name = str(inst.get("name") or iid)
    rows: list[dict] = []
    status = runner_mod.runner.status(inst)
    running = bool(status.get("running"))
    dashboard_ready = bool(status.get("dashboard_ready"))
    if not running:
        level, summary = "bad", "AstrBot 未运行"
    elif dashboard_ready:
        level, summary = "ok", "AstrBot Dashboard 就绪"
    else:
        level, summary = "warn", "进程在运行但 Dashboard 未就绪"
    rows.append(
        component(
            f"astrbot:{iid}",
            f"AstrBot · {name}",
            level,
            summary,
            {
                "pid": status.get("pid"),
                "managed": bool(status.get("managed")),
                "dash_port": inst.get("dash_port"),
                "dashboard_ready": dashboard_ready,
            },
            route="#/bots",
        )
    )

    napcat = runner_mod.runner.napcat_status(inst)
    watch = (watchdog_mod.watchdog.snapshot() or {}).get(iid) or {}
    if not napcat.get("configured"):
        napcat_level, napcat_summary = "warn", "未配置 NapCat"
    elif napcat.get("clients"):
        napcat_level, napcat_summary = "ok", "NapCat 已连接"
    elif watch.get("stage") in {"relogin", "qrcode"}:
        napcat_level, napcat_summary = "warn", "NapCat 登录/扫码中"
    elif napcat.get("running"):
        napcat_level, napcat_summary = "warn", "NapCat 有进程但未连接 QQ"
    else:
        napcat_level, napcat_summary = "warn", "NapCat 未连接"
    rows.append(
        component(
            f"napcat:{iid}",
            f"NapCat · {name}",
            napcat_level,
            napcat_summary,
            {
                "running": bool(napcat.get("running")),
                "clients": int(napcat.get("clients") or 0),
                "watchdog": watch,
            },
            route="#/bots",
        )
    )

    if not running:
        return rows

    for kind, label, route in (
        ("bili", "B站控制台", "#/biliConsole"),
        ("douyin", "抖音控制台", "#/douyinConsole"),
    ):
        try:
            data = consoles.call_status(inst, kind)
            if kind == "douyin":
                level, summary, detail = douyin_health(data or {})
                proactive = (data or {}).get("proactive") or {}
                detail["proactive_enabled"] = bool(proactive.get("enabled"))
                if proactive.get("enabled") and not detail.get("browser_running") and not detail.get("last_error"):
                    level, summary = "warn", "主动刷已开启但浏览器未运行"
            else:
                stats = bili_stats(data)
                level, summary, detail = bili_health(stats)
            rows.append(
                component(f"{kind}:{iid}", f"{label} · {name}", level, summary, detail, route)
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                component(
                    f"{kind}:{iid}",
                    f"{label} · {name}",
                    "warn",
                    f"读取失败：{str(exc)[:160]}",
                    route=route,
                )
            )

    try:
        data = memory.call_status(inst)
        stats = (data or {}).get("stats") if isinstance(data, dict) else {}
        stats = stats or {}
        rows.append(
            component(
                f"memory:{iid}",
                f"记忆 · {name}",
                "ok",
                f"{stats.get('memory_count', '—')} 条记忆 / {stats.get('atom_count', '—')} 原子",
                stats,
                route="#/memory",
            )
        )
    except Exception as exc:  # noqa: BLE001
        rows.append(
            component(
                f"memory:{iid}",
                f"记忆 · {name}",
                "warn",
                f"读取失败：{str(exc)[:160]}",
                route="#/memory",
            )
        )
    return rows


def default_checks() -> list[tuple[str, Callable[[], dict | list[dict] | None]]]:
    checks: list[tuple[str, Callable[[], dict | list[dict] | None]]] = [
        ("manager", check_manager),
        ("dsh", check_dsh),
        ("market", check_market),
        ("disk", check_disk),
    ]
    for inst in store.load_instances():
        checks.append(
            (
                f"instance:{_instance_identity(inst)}",
                lambda inst=inst: check_instance(inst),
            )
        )
    return checks
