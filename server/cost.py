"""用量与成本中心：聚合各实例 AstrBot 的 provider_stats。"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from . import store

CONFIG_PATH = store.DATA_DIR / "cost.json"
DEFAULT_CONFIG = {
    "currency": "CNY",
    "prices": {},
    "budget": {"daily": 0.0, "monthly": 0.0},
}
_DB_NAMES = ("data_v4.db", "astrbot.db", "data.db")


def _number(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def load_config() -> dict:
    data = store.read_json(CONFIG_PATH, {})
    merged = {
        "currency": str((data or {}).get("currency") or "CNY") if isinstance(data, dict) else "CNY",
        "prices": {},
        "budget": {"daily": 0.0, "monthly": 0.0},
    }
    if not isinstance(data, dict):
        return merged
    prices = data.get("prices")
    if isinstance(prices, dict):
        for model, item in prices.items():
            if not isinstance(item, dict):
                continue
            merged["prices"][str(model)] = {
                "input": _number(item.get("input")),
                "cached": _number(item.get("cached")),
                "output": _number(item.get("output")),
            }
    budget = data.get("budget")
    if isinstance(budget, dict):
        merged["budget"] = {
            "daily": _number(budget.get("daily")),
            "monthly": _number(budget.get("monthly")),
        }
    return merged


def save_config(payload: dict) -> dict:
    current = load_config()
    if "currency" in payload:
        currency = str(payload.get("currency") or "CNY").strip().upper()[:8]
        current["currency"] = currency or "CNY"
    if isinstance(payload.get("prices"), dict):
        prices = {}
        for model, item in payload["prices"].items():
            key = str(model or "").strip()
            if not key or not isinstance(item, dict):
                continue
            prices[key[:80]] = {
                "input": _number(item.get("input")),
                "cached": _number(item.get("cached")),
                "output": _number(item.get("output")),
            }
        current["prices"] = prices
    if isinstance(payload.get("budget"), dict):
        current["budget"] = {
            "daily": _number(payload["budget"].get("daily")),
            "monthly": _number(payload["budget"].get("monthly")),
        }
    store.write_json(CONFIG_PATH, current)
    return current


def _db_path(inst: dict) -> Path | None:
    root = Path(str(inst.get("root") or ""))
    for name in _DB_NAMES:
        path = root / "data" / name
        if path.is_file():
            return path
    return None


def _rows_for(inst: dict) -> list[dict]:
    path = _db_path(inst)
    if path is None:
        return []
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=3)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT strftime('%Y-%m-%d', created_at, 'localtime') AS day, "
            "provider_model AS model, COUNT(*) AS calls, "
            "COALESCE(SUM(token_input_other),0) AS input_other, "
            "COALESCE(SUM(token_input_cached),0) AS input_cached, "
            "COALESCE(SUM(token_output),0) AS output "
            "FROM provider_stats GROUP BY day, provider_model "
            "ORDER BY day DESC"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _price_for(config: dict, model: str) -> dict:
    prices = config.get("prices") or {}
    item = prices.get(model) or prices.get("*") or {}
    return {
        "input": _number(item.get("input")),
        "cached": _number(item.get("cached", item.get("input"))),
        "output": _number(item.get("output")),
    }


def _cost_for(tokens: dict, price: dict) -> float:
    return (
        _number(tokens.get("input_other")) * price["input"]
        + _number(tokens.get("input_cached")) * price["cached"]
        + _number(tokens.get("output")) * price["output"]
    ) / 1_000_000


def collect(days: int = 30) -> dict:
    days = max(1, min(int(days), 365))
    config = load_config()
    instances = store.load_instances()
    by_day: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_instance: dict[str, dict] = {}
    models: set[str] = set()
    for inst in instances:
        inst_id = str(inst.get("id") or "")
        name = str(inst.get("name") or inst_id)
        for row in _rows_for(inst):
            day = str(row.get("day") or "")
            model = str(row.get("model") or "未知模型")
            if not day:
                continue
            models.add(model)
            price = _price_for(config, model)
            cost = _cost_for(row, price)
            tokens = {
                "input": int(row.get("input_other") or 0),
                "cached": int(row.get("input_cached") or 0),
                "output": int(row.get("output") or 0),
            }
            calls = int(row.get("calls") or 0)

            entry = by_day.setdefault(day, {"date": day, "calls": 0, "input": 0,
                                            "cached": 0, "output": 0, "cost": 0.0})
            entry["calls"] += calls
            entry["input"] += tokens["input"]
            entry["cached"] += tokens["cached"]
            entry["output"] += tokens["output"]
            entry["cost"] += cost

            entry = by_model.setdefault(model, {"model": model, "calls": 0, "input": 0,
                                                "cached": 0, "output": 0, "cost": 0.0})
            entry["calls"] += calls
            entry["input"] += tokens["input"]
            entry["cached"] += tokens["cached"]
            entry["output"] += tokens["output"]
            entry["cost"] += cost

            entry = by_instance.setdefault(inst_id, {"id": inst_id, "name": name,
                                                     "calls": 0, "input": 0, "cached": 0,
                                                     "output": 0, "cost": 0.0})
            entry["calls"] += calls
            entry["input"] += tokens["input"]
            entry["cached"] += tokens["cached"]
            entry["output"] += tokens["output"]
            entry["cost"] += cost

    dated = sorted(by_day.values(), key=lambda item: item["date"])[-days:]
    keep = {item["date"] for item in dated}
    # 重新按保留日期聚合模型与实例，保证概览口径一致。
    by_model = {}
    by_instance = {}
    for inst in instances:
        inst_id = str(inst.get("id") or "")
        name = str(inst.get("name") or inst_id)
        for row in _rows_for(inst):
            day = str(row.get("day") or "")
            if day not in keep:
                continue
            model = str(row.get("model") or "未知模型")
            cost = _cost_for(row, _price_for(config, model))
            tokens = {
                "input": int(row.get("input_other") or 0),
                "cached": int(row.get("input_cached") or 0),
                "output": int(row.get("output") or 0),
            }
            calls = int(row.get("calls") or 0)
            entry = by_model.setdefault(model, {"model": model, "calls": 0, "input": 0,
                                                "cached": 0, "output": 0, "cost": 0.0})
            entry["calls"] += calls
            entry["input"] += tokens["input"]
            entry["cached"] += tokens["cached"]
            entry["output"] += tokens["output"]
            entry["cost"] += cost
            entry = by_instance.setdefault(inst_id, {"id": inst_id, "name": name,
                                                     "calls": 0, "input": 0, "cached": 0,
                                                     "output": 0, "cost": 0.0})
            entry["calls"] += calls
            entry["input"] += tokens["input"]
            entry["cached"] += tokens["cached"]
            entry["output"] += tokens["output"]
            entry["cost"] += cost

    totals = {"calls": 0, "input": 0, "cached": 0, "output": 0, "cost": 0.0}
    for item in dated:
        for key in totals:
            totals[key] += item[key]
    today = time.strftime("%Y-%m-%d")
    month = today[:7]
    today_entry = next((item for item in dated if item["date"] == today),
                       {"calls": 0, "input": 0, "cached": 0, "output": 0, "cost": 0.0})
    month_entries = [item for item in dated if item["date"].startswith(month)]
    month_cost = sum(item["cost"] for item in month_entries)
    month_calls = sum(item["calls"] for item in month_entries)
    month_tokens = sum(item["input"] + item["cached"] + item["output"] for item in month_entries)

    budget = config.get("budget") or {}
    daily_budget = _number(budget.get("daily"))
    monthly_budget = _number(budget.get("monthly"))
    alerts = []
    if daily_budget > 0:
        ratio = today_entry["cost"] / daily_budget
        if ratio >= 1:
            alerts.append({"level": "bad", "title": "今日预算已超限",
                           "detail": f"今日 ¥{today_entry['cost']:.2f} / 预算 ¥{daily_budget:.2f}"})
        elif ratio >= 0.8:
            alerts.append({"level": "warn", "title": "今日预算接近上限",
                           "detail": f"已用 {ratio * 100:.0f}%（¥{today_entry['cost']:.2f} / ¥{daily_budget:.2f}）"})
    if monthly_budget > 0:
        ratio = month_cost / monthly_budget
        if ratio >= 1:
            alerts.append({"level": "bad", "title": "本月预算已超限",
                           "detail": f"本月 ¥{month_cost:.2f} / 预算 ¥{monthly_budget:.2f}"})
        elif ratio >= 0.8:
            alerts.append({"level": "warn", "title": "本月预算接近上限",
                           "detail": f"已用 {ratio * 100:.0f}%（¥{month_cost:.2f} / ¥{monthly_budget:.2f}）"})

    return {
        "currency": config.get("currency") or "CNY",
        "days": days,
        "generated_at": time.time(),
        "totals": totals,
        "today": today_entry,
        "month": {"cost": month_cost, "calls": month_calls, "tokens": month_tokens},
        "by_day": dated,
        "by_model": sorted(by_model.values(), key=lambda item: item["cost"] + item["input"] + item["output"], reverse=True),
        "by_instance": sorted(by_instance.values(), key=lambda item: item["cost"] + item["input"] + item["output"], reverse=True),
        "budget": {"daily": daily_budget, "monthly": monthly_budget},
        "alerts": alerts,
        "models": sorted(models),
    }
