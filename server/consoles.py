"""B站/抖音控制台的 Dashboard extension 代理；固定白名单。"""

from __future__ import annotations

import threading

from . import dashboard

EXTENSIONS = {
    "bili": {"plugin": "astrbot_plugin_bilibili_ai_bot", "status": "stats"},
    "douyin": {"plugin": "astrbot_plugin_douyin_dm", "status": "status"},
}
TIMEOUTS = {"status": 20, "bili_run": 60, "douyin_run": 600}
run_locks: dict[str, threading.Lock] = {}
run_locks_guard = threading.Lock()


class ConsoleError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def normalize(kind: str, payload: dict) -> dict:
    if isinstance(payload, dict) and payload.get("status") == "error":
        raise ConsoleError(str(payload.get("message") or "插件返回错误"), 502)
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        if data.get("status") == "error":
            raise ConsoleError(str(data.get("message") or "插件返回错误"), 502)
        inner = data.get("data")
        return inner if isinstance(inner, dict) else data
    return payload if isinstance(payload, dict) else {}


def _call(inst, method, path, body, timeout, call):
    try:
        result = call(inst, method, path, body, timeout=timeout)
    except dashboard.DashboardError as exc:
        raise ConsoleError(exc.message, exc.status if exc.status >= 400 else 502) from exc
    return normalize("", result)


def call_status(inst, kind, call=dashboard.call):
    if kind not in EXTENSIONS:
        raise ConsoleError("未知控制台类型", 400)
    meta = EXTENSIONS[kind]
    path = f"plugins/extensions/{meta['plugin']}/{meta['status']}"
    return _call(inst, "GET", path, None, TIMEOUTS["status"], call)


def _lock_for(inst, kind):
    key = f"{inst.get('id') or inst.get('root')}:{kind}"
    with run_locks_guard:
        return run_locks.setdefault(key, threading.Lock())


def call_run(inst, kind, call=dashboard.call):
    if kind not in EXTENSIONS:
        raise ConsoleError("未知控制台类型", 400)
    meta = EXTENSIONS[kind]
    lock = _lock_for(inst, kind)
    if not lock.acquire(blocking=False):
        raise ConsoleError("已有立即执行任务在运行。", 409)
    try:
        if kind == "bili":
            return _call(inst, "POST", f"plugins/extensions/{meta['plugin']}/proactive/run",
                         {}, TIMEOUTS["bili_run"], call)
        return _call(inst, "POST", f"plugins/extensions/{meta['plugin']}/control",
                     {"action": "proactive_run", "force": False}, TIMEOUTS["douyin_run"], call)
    finally:
        lock.release()
