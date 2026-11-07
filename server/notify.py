"""告警推送：Webhook 与 Telegram，本地去重，后台定时。"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

from . import alerts as alerts_mod, store

STATE_PATH = store.DATA_DIR / "alert_push_state.json"
DEDUPE_SECONDS = 6 * 3600
TICK_SECONDS = 60
MIN_SEVERITY = {"warning": {"critical", "warning"}, "critical": {"critical"}}


def _config() -> dict:
    settings = store.load_settings()
    return {
        "enabled": bool(settings.get("alert_push_enabled", False)),
        "webhook": str(settings.get("alert_webhook_url") or "").strip(),
        "telegram_token": str(settings.get("alert_telegram_token") or "").strip(),
        "telegram_chat_id": str(settings.get("alert_telegram_chat_id") or "").strip(),
        "min_severity": str(settings.get("alert_min_severity") or "warning"),
    }


def channels(cfg: dict | None = None) -> list[str]:
    cfg = cfg or _config()
    found = []
    if cfg["webhook"]:
        found.append("webhook")
    if cfg["telegram_token"] and cfg["telegram_chat_id"]:
        found.append("telegram")
    return found


def message_for(result: dict, limit: int = 20) -> str:
    alerts = result.get("alerts") or []
    if not alerts:
        return "舰队告警：当前没有待处理异常。"
    lines = [f"舰队告警：{result.get('counts', {}).get('total', len(alerts))} 项待处理"]
    for item in alerts[:limit]:
        lines.append(f"[{'严重' if item.get('severity') == 'critical' else '警告'}] {item.get('title')}：{item.get('summary')}")
    if len(alerts) > limit:
        lines.append(f"……还有 {len(alerts) - limit} 项")
    return "\n".join(lines)


def filter_new(result: dict, state: dict, now: float | None = None, ttl: int = DEDUPE_SECONDS) -> tuple[list[dict], dict]:
    current = time.time() if now is None else float(now)
    sent = state.get("sent") if isinstance(state.get("sent"), dict) else {}
    sent = {str(key): float(value) for key, value in sent.items() if value}
    fresh = []
    for item in result.get("alerts") or []:
        key = f"{item.get('id')}:{item.get('severity')}"
        if key not in sent or current - sent[key] >= ttl:
            fresh.append(item)
            sent[key] = current
    sent = {key: value for key, value in sent.items() if current - value < ttl * 2}
    return fresh, {**state, "sent": sent, "updated_at": current}


def _post_json(url: str, payload: dict, timeout: float = 15) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def _post_telegram(token: str, chat_id: str, text: str) -> None:
    _post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": text},
    )


def deliver(text: str, result: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or _config()
    statuses = {}
    if cfg["webhook"]:
        try:
            _post_json(cfg["webhook"], {"text": text, "overall": result.get("overall"), "alerts": result.get("alerts") or []})
            statuses["webhook"] = "ok"
        except Exception as exc:  # noqa: BLE001
            statuses["webhook"] = str(exc)[:240]
    if cfg["telegram_token"] and cfg["telegram_chat_id"]:
        try:
            _post_telegram(cfg["telegram_token"], cfg["telegram_chat_id"], text)
            statuses["telegram"] = "ok"
        except Exception as exc:  # noqa: BLE001
            statuses["telegram"] = str(exc)[:240]
    return statuses


def _load_state() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> None:
    store.DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def run(force: bool = False) -> dict:
    cfg = _config()
    if not channels(cfg):
        return {"sent": False, "reason": "未配置 Webhook 或 Telegram", "statuses": {}}
    result = alerts_mod.collect(force_health=force)
    allowed = MIN_SEVERITY.get(cfg["min_severity"], MIN_SEVERITY["warning"])
    selected = {
        **result,
        "alerts": [item for item in result.get("alerts") or [] if item.get("severity") in allowed],
    }
    state = _load_state()
    fresh, next_state = filter_new(selected, state)
    if not fresh:
        return {"sent": False, "reason": "没有新的告警", "statuses": {}, "counts": selected.get("counts", {})}
    selected["alerts"] = fresh
    statuses = deliver(message_for(selected), selected, cfg)
    next_state.update({"last_at": time.time(), "last_statuses": statuses, "last_error": ""})
    if any(value == "ok" for value in statuses.values()):
        _save_state(next_state)
        return {"sent": True, "statuses": statuses, "count": len(fresh)}
    next_state["last_error"] = "; ".join(f"{key}: {value}" for key, value in statuses.items())[:400]
    _save_state(next_state)
    return {"sent": False, "statuses": statuses, "error": next_state["last_error"]}


def test() -> dict:
    cfg = _config()
    if not channels(cfg):
        return {"ok": False, "error": "请先配置 Webhook 或 Telegram 并保存"}
    statuses = deliver("AstrBot 舰队管理器测试消息：告警推送已连通。", {"overall": "ok", "alerts": []}, cfg)
    return {"ok": any(value == "ok" for value in statuses.values()), "statuses": statuses}


def status() -> dict:
    cfg = _config()
    state = _load_state()
    return {
        "enabled": cfg["enabled"],
        "channels": channels(cfg),
        "telegram_token_set": bool(cfg["telegram_token"]),
        "min_severity": cfg["min_severity"],
        "last_at": state.get("last_at"),
        "last_statuses": state.get("last_statuses") or {},
        "last_error": state.get("last_error") or "",
    }


class Pusher:
    def __init__(self, interval: float = TICK_SECONDS):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="fleet-alert-push")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if _config()["enabled"]:
                    run()
            except Exception:  # noqa: BLE001
                continue


pusher = Pusher()
