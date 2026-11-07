"""群聊剧场：场景状态机、插件调用、自动模式与记录。"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any, Callable

from . import dashboard, fleet_store
from .store import load_instances

PLUGIN = "astrbot_plugin_fleet_duet"
MODES = {"rounds", "duration", "auto"}
ACTIVE_STATUSES = {"starting", "running", "paused"}
FINAL_STATUSES = {"completed", "stopped", "error"}
MIN_INTERVAL = 5
MAX_INTERVAL = 120
MAX_ROUNDS = 20
MIN_DURATION = 60
MAX_SECONDS = 3600
DEFAULT_ROUNDS = 6
DEFAULT_INTERVAL = 15
DEFAULT_MAX_CHARS = 80
STATUS_TTL = 5.0
ACTIVITY_POLL = 1.5
AUTO_TICK = 20.0

DEFAULT_AUTO = {
    "enabled": False,
    "group_id": "",
    "instance_ids": [],
    "topic": "随便聊聊最近发生的事",
    "silence_minutes": 30,
    "night_start": "23:00",
    "night_end": "08:00",
    "daily_limit": 1,
    "cooldown_minutes": 120,
    "rounds": 6,
    "interval": 15,
    "max_chars": 80,
}


class DuetError(Exception):
    pass


# ------------------------------------------------------------------ 校验


def _clamp_int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    return max(low, min(number, high))


def parse_group_id(value) -> str:
    text = str(value or "").strip()
    if not text.isdigit() or not 4 <= len(text) <= 13:
        raise DuetError("群号必须是 4-13 位数字")
    return text


def _clock_text(value, default):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
    if not match:
        return default
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return f"{hour:02d}:{minute:02d}"


def clock_minutes(value) -> int:
    hour, minute = str(value).split(":")
    return int(hour) * 60 + int(minute)


def in_window(now_text, start_text, end_text) -> bool:
    now, start, end = clock_minutes(now_text), clock_minutes(start_text), clock_minutes(end_text)
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def in_night(ts, start_text, end_text) -> bool:
    return in_window(time.strftime("%H:%M", time.localtime(ts)), start_text, end_text)


def _instance_ids(value) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
    else:
        items = []
    items = [item for item in items if item]
    if items and len(items) != 2:
        raise DuetError("群聊剧场需要正好两个机器人")
    if len(set(items)) != len(items):
        raise DuetError("两个机器人不能是同一个实例")
    return items


def normalize_start(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise DuetError("请求体应为 JSON 对象")
    mode = str(payload.get("mode") or "rounds").strip()
    if mode not in {"rounds", "duration"}:
        raise DuetError("模式只能是轮数（rounds）或时长（duration）")
    topic = str(payload.get("topic") or "").strip()[:120] or "随便聊聊最近发生的事"
    config = {
        "mode": mode,
        "group_id": parse_group_id(payload.get("group_id")),
        "topic": topic,
        "interval": _clamp_int(payload.get("interval"), DEFAULT_INTERVAL, MIN_INTERVAL, MAX_INTERVAL),
        "max_chars": _clamp_int(payload.get("max_chars"), DEFAULT_MAX_CHARS, 20, 200),
        "instance_ids": _instance_ids(payload.get("instance_ids")),
    }
    if mode == "rounds":
        config["rounds"] = _clamp_int(payload.get("rounds"), DEFAULT_ROUNDS, 1, MAX_ROUNDS)
        config["duration_seconds"] = 0
    else:
        raw = payload.get("duration_seconds")
        config["rounds"] = 0
        config["duration_seconds"] = (
            MAX_SECONDS
            if raw in (None, "", 0, "0")
            else _clamp_int(raw, 900, MIN_DURATION, MAX_SECONDS)
        )
    return config


def default_auto() -> dict:
    return dict(DEFAULT_AUTO)


def normalize_auto(patch: dict, current: dict | None = None) -> dict:
    if not isinstance(patch, dict):
        raise DuetError("请求体应为 JSON 对象")
    data = {**DEFAULT_AUTO, **(current or {})}
    if "enabled" in patch:
        data["enabled"] = bool(patch.get("enabled"))
    if "group_id" in patch:
        raw = str(patch.get("group_id") or "").strip()
        data["group_id"] = parse_group_id(raw) if raw else ""
    if "instance_ids" in patch:
        data["instance_ids"] = _instance_ids(patch.get("instance_ids"))
    if "topic" in patch:
        data["topic"] = str(patch.get("topic") or "").strip()[:120] or DEFAULT_AUTO["topic"]
    if "silence_minutes" in patch:
        data["silence_minutes"] = _clamp_int(patch.get("silence_minutes"), 30, 5, 1440)
    if "night_start" in patch:
        data["night_start"] = _clock_text(patch.get("night_start"), DEFAULT_AUTO["night_start"])
    if "night_end" in patch:
        data["night_end"] = _clock_text(patch.get("night_end"), DEFAULT_AUTO["night_end"])
    if "daily_limit" in patch:
        data["daily_limit"] = _clamp_int(patch.get("daily_limit"), 1, 0, 10)
    if "cooldown_minutes" in patch:
        data["cooldown_minutes"] = _clamp_int(patch.get("cooldown_minutes"), 120, 10, 1440)
    if "rounds" in patch:
        data["rounds"] = _clamp_int(patch.get("rounds"), 6, 2, 12)
    if "interval" in patch:
        data["interval"] = _clamp_int(patch.get("interval"), 15, MIN_INTERVAL, MAX_INTERVAL)
    if "max_chars" in patch:
        data["max_chars"] = _clamp_int(patch.get("max_chars"), 80, 20, 200)
    if data["enabled"] and not data.get("group_id"):
        raise DuetError("开启自动模式前请填写群号")
    return data


def auto_decision(auto: dict, now: float, last_auto_started: float,
                  last_scene_ended: float, last_human_ts: float,
                  today_count: int) -> tuple[bool, str]:
    if not auto.get("enabled"):
        return False, "自动模式未开启"
    if not auto.get("group_id"):
        return False, "没有配置群号"
    if in_night(now, auto.get("night_start", "23:00"), auto.get("night_end", "08:00")):
        return False, "夜间静默时段"
    if today_count >= int(auto.get("daily_limit") or 0):
        return False, f"今天已达上限（{auto.get('daily_limit')} 次）"
    cooldown = max(last_auto_started or 0, last_scene_ended or 0)
    if cooldown and now - cooldown < int(auto.get("cooldown_minutes") or 0) * 60:
        remain = int(auto.get("cooldown_minutes") or 0) - int((now - cooldown) / 60)
        return False, f"冷却中，约 {max(0, remain)} 分钟"
    silence = int(auto.get("silence_minutes") or 0) * 60
    if last_human_ts and now - last_human_ts < silence:
        remain = int((silence - (now - last_human_ts)) / 60) + 1
        return False, f"群内还活跃，约 {remain} 分钟后可判断静默"
    return True, "可以开始"


def build_speak_payload(scene: dict, config: dict, speaker: dict, peer: dict,
                        transcript: list[dict], turn: int) -> dict:
    names = config.get("names") or {}
    lines = []
    for item in transcript:
        if item.get("status") not in {"sent", "human"}:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        name = str(item.get("speaker_name") or "").strip()
        if item.get("speaker") == "human":
            name = name or "群友"
        if not name:
            name = names.get(str(item.get("speaker")), str(item.get("speaker"))[:8])
        lines.append({"speaker_name": name, "text": text})
    return {
        "scene_id": scene.get("id", ""),
        "group_id": scene.get("group_id", ""),
        "topic": scene.get("topic", ""),
        "transcript": lines,
        "turn": max(1, int(turn)),
        "max_chars": int(config.get("max_chars") or DEFAULT_MAX_CHARS),
        "self_name": names.get(str(speaker.get("id")), speaker.get("name") or speaker.get("id")),
        "peer_name": names.get(str(peer.get("id")), peer.get("name") or peer.get("id")),
    }


def transcript_for_prompt(turns: list[dict], limit: int = 12) -> list[dict]:
    return list(turns)[-max(1, int(limit)):]


# ------------------------------------------------------------------ 数据


def _scene(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    try:
        item["config"] = json.loads(item.pop("config_json") or "{}")
    except (TypeError, ValueError):
        item["config"] = {}
    return item


def create_scene(mode: str, group_id: str, topic: str, config: dict,
                 db_path=None) -> dict:
    scene_id = "duet_" + uuid.uuid4().hex[:12]
    now = time.time()
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO duet_scenes(id, mode, group_id, topic, status, config_json, note, created, updated) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (scene_id, mode, group_id, topic, "starting",
             json.dumps(config, ensure_ascii=False), "", now, now),
        )
    return get_scene(scene_id, db_path=db_path) or {}


def update_scene(scene_id: str, status: str, note: str | None = None,
                 db_path=None) -> dict | None:
    now = time.time()
    with fleet_store.session(db_path) as conn:
        if note is None:
            conn.execute(
                "UPDATE duet_scenes SET status=?, updated=? WHERE id=?",
                (status, now, scene_id),
            )
        else:
            conn.execute(
                "UPDATE duet_scenes SET status=?, note=?, updated=? WHERE id=?",
                (status, note, now, scene_id),
            )
    return get_scene(scene_id, db_path=db_path)


def get_scene(scene_id: str, db_path=None, with_turns: bool = False) -> dict | None:
    with fleet_store.session(db_path) as conn:
        row = conn.execute("SELECT * FROM duet_scenes WHERE id=?", (scene_id,)).fetchone()
    scene = _scene(row)
    if scene and with_turns:
        scene["turns"] = list_turns(scene_id, db_path=db_path)
    return scene


def list_scenes(limit: int = 20, db_path=None) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM duet_turns t WHERE t.scene_id=s.id) AS turn_count "
            "FROM duet_scenes s ORDER BY created DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_scene(row) for row in rows if row is not None]


def add_turn(scene_id: str, speaker: str, text: str, status: str = "sent",
             speaker_name: str = "", message_id: str = "", db_path=None) -> dict:
    turn_id = "turn_" + uuid.uuid4().hex[:12]
    now = time.time()
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO duet_turns(id, scene_id, speaker, speaker_name, text, "
            "platform_message_id, status, created) VALUES(?,?,?,?,?,?,?,?)",
            (turn_id, scene_id, speaker, speaker_name, str(text)[:500],
             message_id, status, now),
        )
        conn.execute("UPDATE duet_scenes SET updated=? WHERE id=?", (now, scene_id))
    return {
        "id": turn_id,
        "scene_id": scene_id,
        "speaker": speaker,
        "speaker_name": speaker_name,
        "text": str(text)[:500],
        "platform_message_id": message_id,
        "status": status,
        "created": now,
    }


def list_turns(scene_id: str, limit: int = 100, db_path=None) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    with fleet_store.session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM duet_turns WHERE scene_id=? ORDER BY created ASC, rowid ASC LIMIT ?",
            (scene_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def load_auto(db_path=None) -> dict:
    with fleet_store.session(db_path) as conn:
        row = conn.execute("SELECT json FROM duet_config WHERE id=1").fetchone()
    try:
        saved = json.loads(row["json"]) if row else {}
    except (TypeError, ValueError):
        saved = {}
    return {**DEFAULT_AUTO, **(saved if isinstance(saved, dict) else {})}


def save_auto(config: dict, db_path=None) -> dict:
    now = time.time()
    with fleet_store.session(db_path) as conn:
        conn.execute(
            "INSERT INTO duet_config(id, json, updated) VALUES(1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET json=excluded.json, updated=excluded.updated",
            (json.dumps(config, ensure_ascii=False), now),
        )
    return load_auto(db_path=db_path)


def auto_stats(db_path=None) -> dict:
    start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    with fleet_store.session(db_path) as conn:
        today = conn.execute(
            "SELECT COUNT(*) AS n FROM duet_scenes WHERE mode='auto' AND created>=?",
            (start,),
        ).fetchone()
        row = conn.execute(
            "SELECT MAX(created) AS started, MAX(updated) AS ended FROM duet_scenes WHERE mode='auto'"
        ).fetchone()
    return {
        "today_count": int(today["n"] if today else 0),
        "last_started": float(row["started"] or 0) if row else 0.0,
        "last_ended": float(row["ended"] or 0) if row else 0.0,
    }


# ------------------------------------------------------------------ 引擎


class DuetEngine:
    def __init__(self, instances: Callable[[], list[dict]] | None = None,
                 call: Callable | None = None, db_path: str | None = None,
                 clock: Callable[[], float] | None = None):
        self._instances = instances or load_instances
        self._call = call or dashboard.call
        self.db_path = db_path
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._scene_id = ""
        self._thread: threading.Thread | None = None
        self._status_cache: dict[str, tuple[float, dict]] = {}
        self._auto_thread: threading.Thread | None = None
        self._auto_stop = threading.Event()

    # -------------------------------------------------------- 插件通信

    def _plugin_call(self, inst: dict, method: str, suffix: str,
                     payload=None, query: dict | None = None,
                     timeout: float = 60.0) -> dict:
        path = f"plugins/extensions/{PLUGIN}/{suffix}"
        try:
            result = self._call(inst, method, path, payload, query=query, timeout=timeout)
        except dashboard.DashboardError as exc:
            raise DuetError(exc.message) from exc
        data = result.get("data") if isinstance(result, dict) else None
        if isinstance(data, dict):
            if data.get("status") == "error":
                raise DuetError(str(data.get("message") or "插件返回错误"))
            inner = data.get("data")
            if isinstance(inner, dict):
                return inner
            return data
        return result if isinstance(result, dict) else {}

    def _plugin_status(self, inst: dict, force: bool = False) -> dict:
        key = str(inst.get("id") or inst.get("root") or "")
        now = self.clock()
        with self._lock:
            cached = self._status_cache.get(key)
            if cached and not force and now - cached[0] < STATUS_TTL:
                return cached[1]
        try:
            data = self._plugin_call(inst, "GET", "status", query={}, timeout=15)
            data["reachable"] = True
            data["error"] = ""
        except Exception as exc:
            data = {
                "reachable": False,
                "error": str(exc),
                "self_qq": "",
                "platform_ready": False,
                "groups": {},
            }
        with self._lock:
            self._status_cache[key] = (now, data)
        return data

    def _activity(self, inst: dict, group_id: str, since: float = 0.0) -> dict:
        return self._plugin_call(
            inst, "GET", "activity",
            query={"group_id": group_id, "since": f"{float(since):.3f}"},
            timeout=15,
        )

    # -------------------------------------------------------- 实例与预检

    def _all_instances(self) -> list[dict]:
        return [item for item in self._instances() if item.get("id")]

    def _resolve_instances(self, ids: list[str]) -> list[dict]:
        all_items = self._all_instances()
        by_id = {str(item["id"]): item for item in all_items}
        if ids:
            missing = [item for item in ids if item not in by_id]
            if missing:
                raise DuetError(f"找不到机器人：{', '.join(missing)}")
            return [by_id[item] for item in ids]
        if len(all_items) < 2:
            raise DuetError("至少需要两个机器人才能开群聊剧场")
        return all_items[:2]

    def _preflight(self, instances: list[dict]) -> list[dict]:
        if len(instances) != 2:
            raise DuetError("群聊剧场需要正好两个机器人")
        statuses = []
        for inst in instances:
            name = inst.get("name") or inst.get("id")
            status = self._plugin_status(inst, force=True)
            if not status.get("reachable"):
                raise DuetError(
                    f"「{name}」的群聊剧场插件不可达：{status.get('error') or '请确认机器人已启动并安装插件'}"
                )
            if not status.get("platform_ready"):
                raise DuetError(f"「{name}」QQ 平台未连接")
            if not str(status.get("self_qq") or ""):
                fallback = str(inst.get("qq") or "").strip()
                if fallback.isdigit():
                    status["self_qq"] = fallback
            if not str(status.get("self_qq") or ""):
                raise DuetError(f"「{name}」还没读取到机器人 QQ 号，请确认登录后再试")
            if "client_keys" in status and not status.get("client_keys"):
                raise DuetError(f"「{name}」NapCat 未连接到 AstrBot（6199 没有反向 WebSocket）")
            statuses.append(status)
        if str(statuses[0].get("self_qq")) == str(statuses[1].get("self_qq")):
            raise DuetError("两个实例读到同一个机器人 QQ 号，请确认连的是不同账号")
        for idx, inst in enumerate(instances):
            other = str(statuses[1 - idx].get("self_qq") or "")
            name = inst.get("name") or inst.get("id")
            try:
                self._plugin_call(
                    inst, "POST", "config",
                    {
                        "peer_qq": [other],
                        "self_qq": str(statuses[idx].get("self_qq") or ""),
                        "filter_enabled": True,
                    },
                    timeout=15,
                )
            except DuetError as exc:
                raise DuetError(f"写入「{name}」防循环配置失败：{exc}") from exc
        with self._lock:
            for inst, status in zip(instances, statuses):
                key = str(inst.get("id") or inst.get("root") or "")
                self._status_cache[key] = (self.clock(), status)
        return statuses

    # -------------------------------------------------------- 场景控制

    def _active_scene(self) -> dict | None:
        with self._lock:
            scene_id = self._scene_id
            thread = self._thread
        if scene_id and thread and thread.is_alive():
            scene = get_scene(scene_id, db_path=self.db_path, with_turns=True)
            if scene and scene.get("status") in ACTIVE_STATUSES:
                return scene
        for scene in list_scenes(10, db_path=self.db_path):
            if scene.get("status") in ACTIVE_STATUSES:
                if scene_id == scene["id"]:
                    continue
                update_scene(scene["id"], "error", "管理器重启，场景已中断", db_path=self.db_path)
        return None

    def start(self, payload: dict) -> dict:
        config = normalize_start(payload)
        with self._lock:
            active = self._active_scene()
            if active:
                raise DuetError(f"已有场景在运行：「{active.get('topic') or active['id']}」")
            instances = self._resolve_instances(config.pop("instance_ids"))
            statuses = self._preflight(instances)
            config["instances"] = [str(inst["id"]) for inst in instances]
            config["names"] = {
                str(inst["id"]): str(inst.get("name") or inst["id"]) for inst in instances
            }
            config["qqs"] = {
                str(inst["id"]): str(status.get("self_qq") or "")
                for inst, status in zip(instances, statuses)
            }
            config["started_at"] = self.clock()
            scene = create_scene(
                config["mode"], config["group_id"], config["topic"], config,
                db_path=self.db_path,
            )
            self._scene_id = scene["id"]
            self._stop_event.clear()
            self._pause_event.clear()
            thread = threading.Thread(
                target=self._run, args=(scene["id"],),
                daemon=True, name=f"duet-{scene['id']}",
            )
            self._thread = thread
            thread.start()
        fleet_store.add_event(
            "duet", "manager", "info",
            f"群聊剧场开始：{scene['topic']}",
            {"scene_id": scene["id"], "mode": config["mode"], "group_id": config["group_id"]},
            scene["id"], self.db_path,
        )
        return get_scene(scene["id"], db_path=self.db_path, with_turns=True) or scene

    def _require_scene(self, scene_id: str) -> dict:
        scene = get_scene(scene_id, db_path=self.db_path)
        if not scene:
            raise DuetError("场景不存在")
        return scene

    def pause(self, scene_id: str) -> dict:
        with self._lock:
            scene = self._require_scene(scene_id)
            if scene.get("status") not in {"starting", "running"}:
                raise DuetError("只有运行中的场景可以暂停")
            self._pause_event.set()
            updated = update_scene(scene_id, "paused", db_path=self.db_path)
        fleet_store.add_event("duet", "manager", "info", "群聊剧场已暂停",
                              {"scene_id": scene_id}, scene_id, self.db_path)
        return get_scene(scene_id, db_path=self.db_path, with_turns=True) or updated or {}

    def resume(self, scene_id: str) -> dict:
        with self._lock:
            scene = self._require_scene(scene_id)
            if scene.get("status") != "paused":
                raise DuetError("只有暂停中的场景可以继续")
            self._pause_event.clear()
            update_scene(scene_id, "running", db_path=self.db_path)
        fleet_store.add_event("duet", "manager", "info", "群聊剧场继续",
                              {"scene_id": scene_id}, scene_id, self.db_path)
        return get_scene(scene_id, db_path=self.db_path, with_turns=True) or {}

    def stop(self, scene_id: str, note: str = "管理员结束") -> dict:
        with self._lock:
            scene = self._require_scene(scene_id)
            if scene.get("status") in FINAL_STATUSES:
                return get_scene(scene_id, db_path=self.db_path, with_turns=True) or scene
            self._stop_event.set()
            self._pause_event.clear()
            update_scene(scene_id, "stopped", note, db_path=self.db_path)
            thread = self._thread if self._scene_id == scene_id else None
        self._cancel_plugins(scene_id, (scene.get("config") or {}).get("instances") or [])
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        fleet_store.add_event("duet", "manager", "info", "群聊剧场结束",
                              {"scene_id": scene_id, "note": note}, scene_id, self.db_path)
        return get_scene(scene_id, db_path=self.db_path, with_turns=True) or {}

    def _cancel_plugins(self, scene_id: str, instance_ids: list[str]) -> None:
        try:
            instances = self._resolve_instances(list(instance_ids))
        except DuetError:
            return
        for inst in instances:
            try:
                self._plugin_call(
                    inst, "POST", "cancel", {"scene_id": scene_id}, timeout=3
                )
            except Exception:
                pass

    # -------------------------------------------------------- 执行线程

    def _finish(self, scene_id: str, status: str, note: str) -> None:
        scene = get_scene(scene_id, db_path=self.db_path)
        if not scene or scene.get("status") == "stopped":
            return
        update_scene(scene_id, status, note, db_path=self.db_path)
        fleet_store.add_event(
            "duet", "manager", "warn" if status == "error" else "info",
            f"群聊剧场{'失败' if status == 'error' else '结束'}：{note}",
            {"scene_id": scene_id, "status": status}, scene_id, self.db_path,
        )

    def _wait_interval(self, config: dict, instances: list[dict],
                       last_activity: float) -> tuple[str, dict | None]:
        deadline = self.clock() + float(config.get("interval") or DEFAULT_INTERVAL)
        next_poll = 0.0
        while self.clock() < deadline:
            if self._stop_event.is_set():
                return "stop", None
            if self._pause_event.is_set():
                return "paused", None
            if self.clock() >= next_poll:
                next_poll = self.clock() + ACTIVITY_POLL
                for inst in instances:
                    try:
                        data = self._activity(inst, config["group_id"], since=last_activity)
                    except Exception:
                        continue
                    events = data.get("events") or []
                    if events:
                        return "human", events[-1]
                    break
            self._stop_event.wait(0.25)
        return "ok", None

    def _run(self, scene_id: str) -> None:
        scene = get_scene(scene_id, db_path=self.db_path)
        if not scene:
            return
        config = scene.get("config") or {}
        names = config.get("names") or {}
        instances = self._resolve_instances(config.get("instances") or [])
        update_scene(scene_id, "running", db_path=self.db_path)
        started = self.clock()
        paused_total = 0.0
        pause_started: float | None = None
        turn = 0
        failures = 0
        last_activity = 0.0
        try:
            last_activity = float(
                self._activity(instances[0], scene["group_id"], since=0).get("last_ts") or 0
            )
        except Exception:
            pass
        try:
            while not self._stop_event.is_set():
                if self._pause_event.is_set():
                    if pause_started is None:
                        pause_started = self.clock()
                    self._stop_event.wait(0.25)
                    continue
                if pause_started is not None:
                    paused_total += self.clock() - pause_started
                    pause_started = None
                now = self.clock()
                if config.get("rounds") and turn >= int(config["rounds"]):
                    self._finish(scene_id, "completed", f"已完成 {turn} 轮")
                    return
                if config.get("duration_seconds") and now - started - paused_total >= int(
                    config["duration_seconds"]
                ):
                    self._finish(scene_id, "completed", "已到设定时长")
                    return
                if now - started >= MAX_SECONDS:
                    self._finish(scene_id, "completed", "达到 60 分钟安全上限")
                    return
                speaker = instances[turn % 2]
                peer = instances[1 - (turn % 2)]
                speaker_id = str(speaker["id"])
                speaker_name = names.get(speaker_id) or str(speaker.get("name") or speaker_id)
                turns = list_turns(scene_id, db_path=self.db_path)
                payload = build_speak_payload(
                    scene, config, speaker, peer,
                    transcript_for_prompt(turns), turn + 1,
                )
                try:
                    result = self._plugin_call(
                        speaker, "POST", "speak", payload, timeout=120
                    )
                    text = str(result.get("text") or "").strip()
                    if not text:
                        raise DuetError("插件返回空发言")
                except Exception as exc:
                    failures += 1
                    add_turn(
                        scene_id, speaker_id, f"生成失败：{exc}", status="error",
                        speaker_name=speaker_name, db_path=self.db_path,
                    )
                    if failures >= 2:
                        self._finish(scene_id, "error", f"连续两次生成失败：{exc}")
                        return
                else:
                    failures = 0
                    add_turn(
                        scene_id, speaker_id, text, status="sent",
                        speaker_name=speaker_name,
                        message_id=str(result.get("message_id") or ""),
                        db_path=self.db_path,
                    )
                    turn += 1
                action, activity = self._wait_interval(config, instances, last_activity)
                if action == "stop":
                    self._finish(scene_id, "stopped", "已停止")
                    return
                if action == "human" and activity:
                    last_activity = float(activity.get("ts") or 0)
                    human_name = str(activity.get("name") or activity.get("sender") or "群友")
                    human_text = str(activity.get("text") or "")[:200]
                    add_turn(
                        scene_id, "human", human_text, status="human",
                        speaker_name=human_name, db_path=self.db_path,
                    )
                    self._pause_event.set()
                    pause_started = self.clock()
                    update_scene(scene_id, "paused", db_path=self.db_path)
                    fleet_store.add_event(
                        "duet", "manager", "info", "群内有人发言，剧场自动暂停",
                        {"scene_id": scene_id, "name": human_name, "text": human_text},
                        scene_id, self.db_path,
                    )
            self._finish(scene_id, "stopped", "管理员结束")
        except Exception as exc:
            self._finish(scene_id, "error", f"{type(exc).__name__}: {exc}")

    # -------------------------------------------------------- 自动模式

    def auto_state(self, auto: dict | None = None) -> dict:
        auto = auto or load_auto(db_path=self.db_path)
        stats = auto_stats(db_path=self.db_path)
        last_human = 0.0
        instances = self._all_instances()
        if auto.get("instance_ids"):
            try:
                instances = self._resolve_instances(auto["instance_ids"])
            except DuetError:
                instances = []
        for inst in instances:
            status = self._plugin_status(inst)
            if not status.get("reachable"):
                continue
            groups = status.get("groups") or {}
            group = groups.get(auto.get("group_id")) or {}
            last_human = float(group.get("last_ts") or 0)
            break
        ok, reason = auto_decision(
            auto, self.clock(), stats["last_started"], stats["last_ended"],
            last_human, stats["today_count"],
        )
        return {
            "eligible": ok,
            "reason": reason,
            "within_night": in_night(
                self.clock(), auto.get("night_start", "23:00"), auto.get("night_end", "08:00")
            ),
            "last_human_ts": last_human,
            "today_count": stats["today_count"],
            "last_started": stats["last_started"],
            "last_ended": stats["last_ended"],
        }

    def auto_tick(self) -> dict:
        active = self._active_scene()
        if active:
            return {"started": False, "reason": "已有场景在运行"}
        auto = load_auto(db_path=self.db_path)
        state = self.auto_state(auto)
        if not state["eligible"]:
            return {"started": False, "reason": state["reason"], "state": state}
        instances = auto.get("instance_ids") or []
        try:
            if instances:
                resolved = self._resolve_instances(instances)
                ids = [str(item["id"]) for item in resolved]
            else:
                resolved = self._resolve_instances([])
                ids = [str(item["id"]) for item in resolved]
            scene = self.start(
                {
                    "mode": "rounds",
                    "group_id": auto.get("group_id"),
                    "topic": auto.get("topic"),
                    "rounds": auto.get("rounds"),
                    "interval": auto.get("interval"),
                    "max_chars": auto.get("max_chars"),
                    "instance_ids": ids,
                    "_auto": True,
                }
            )
        except Exception as exc:
            fleet_store.add_event(
                "duet", "manager", "warn", f"自动剧场启动失败：{exc}",
                {"auto": auto}, "", self.db_path,
            )
            return {"started": False, "reason": str(exc)}
        with fleet_store.session(self.db_path) as conn:
            conn.execute(
                "UPDATE duet_scenes SET mode='auto' WHERE id=?", (scene["id"],)
            )
        scene["mode"] = "auto"
        fleet_store.add_event(
            "duet", "manager", "info", "安静自动剧场开始",
            {"scene_id": scene["id"], "group_id": auto.get("group_id")}, scene["id"], self.db_path,
        )
        return {"started": True, "scene": scene}

    def start_auto(self) -> None:
        if self._auto_thread and self._auto_thread.is_alive():
            return
        self._auto_stop.clear()

        def loop():
            self._auto_stop.wait(3.0)
            while not self._auto_stop.is_set():
                try:
                    self.auto_tick()
                except Exception:
                    pass
                self._auto_stop.wait(AUTO_TICK)

        self._auto_thread = threading.Thread(target=loop, daemon=True, name="duet-auto")
        self._auto_thread.start()

    def shutdown(self) -> None:
        self._auto_stop.set()
        with self._lock:
            scene_id = self._scene_id
            thread = self._thread
            scene = get_scene(scene_id, db_path=self.db_path) if scene_id else None
        if scene_id and thread and thread.is_alive():
            self._stop_event.set()
            update_scene(scene_id, "stopped", "管理器退出", db_path=self.db_path)
            self._cancel_plugins(scene_id, (scene or {}).get("config", {}).get("instances") or [])
            thread.join(timeout=3.0)

    # -------------------------------------------------------- 状态视图

    def status(self) -> dict:
        scene = self._active_scene()
        if not scene:
            scenes = list_scenes(1, db_path=self.db_path)
            scene = scenes[0] if scenes else None
            if scene:
                scene["turns"] = list_turns(scene["id"], db_path=self.db_path)
        instances = []
        for inst in self._all_instances():
            status = self._plugin_status(inst)
            groups = status.get("groups") or {}
            instances.append({
                "id": str(inst.get("id")),
                "name": str(inst.get("name") or inst.get("id")),
                "reachable": bool(status.get("reachable")),
                "platform_ready": bool(status.get("platform_ready")),
                "qq_connected": bool(status.get("qq_connected", status.get("platform_ready"))),
                "self_qq": str(status.get("self_qq") or inst.get("qq") or ""),
                "nickname": str(status.get("nickname") or ""),
                "peer_qqs": status.get("peer_qqs") or [],
                "filter_enabled": bool(status.get("filter_enabled", True)),
                "groups": groups,
                "error": str(status.get("error") or ""),
            })
        auto = load_auto(db_path=self.db_path)
        return {
            "scene": scene,
            "instances": instances,
            "auto": auto,
            "auto_state": self.auto_state(auto),
            "limits": {
                "rounds": MAX_ROUNDS,
                "interval": [MIN_INTERVAL, MAX_INTERVAL],
                "duration": [MIN_DURATION, MAX_SECONDS],
                "max_chars": 200,
            },
        }

    def scenes(self, limit: int = 20) -> list[dict]:
        return list_scenes(limit, db_path=self.db_path)

    def scene(self, scene_id: str) -> dict:
        scene = get_scene(scene_id, db_path=self.db_path, with_turns=True)
        if not scene:
            raise DuetError("场景不存在")
        return scene

    def update_auto(self, patch: dict) -> dict:
        current = load_auto(db_path=self.db_path)
        config = normalize_auto(patch, current)
        saved = save_auto(config, db_path=self.db_path)
        fleet_store.add_event(
            "duet", "manager", "info",
            f"群聊剧场自动模式已{'开启' if saved.get('enabled') else '关闭'}",
            saved, "", self.db_path,
        )
        return saved


engine = DuetEngine()
