"""全自动聊天记录学习：周期性采样 -> 总结说话风格 -> 追加到同名风格档案。

状态持久化在 data/auto_learn.json；每轮学到的新笔记会覆盖同名
「自动学习」风格档案，不再写入人格提示词。
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path

from . import dashboard, learn, llm, store, styles
from .runner import runner

STATE_PATH = store.DATA_DIR / "auto_learn.json"
LOG_PATH = store.DATA_DIR / "auto_learn.log"

CHECK_INTERVAL = 30.0
MIN_SOURCE_COUNT = 5
MIN_MESSAGES = 8
MAX_SOURCES = 3
MAX_HISTORY = 20
MAX_NOTE = 6000
MAX_TRANSCRIPT = 6000
DEFAULT_INTERVAL = 120

BEGIN = "<!-- AUTO-LEARN:BEGIN -->"
END = "<!-- AUTO-LEARN:END -->"

SUMMARY_SYSTEM = "你是语言风格分析助手，只根据聊天记录做归纳，不要编造。"


def _trace(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 512 * 1024:
            LOG_PATH.write_text("", encoding="utf-8")
        stamp = datetime.now().strftime("%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def _fmt_ts(value) -> str:
    try:
        ts = float(value or 0)
    except Exception:
        return ""
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _defaults() -> dict:
    return {
        "enabled": False,
        "interval_min": DEFAULT_INTERVAL,
        "limit": 200,
        "persona_id": "",
        "provider_id": "",
        "note": "",
        "last_run_at": 0,
        "last_source_at": "",
        "last_status": "",
        "last_message": "",
        "last_error": "",
        "last_sampled": 0,
        "last_sources": [],
        "last_persona": "",
        "history": [],
    }


def _merge(data: dict) -> dict:
    cfg = _defaults()
    if isinstance(data, dict):
        for key, value in data.items():
            if key in cfg and value is not None:
                cfg[key] = value
    if not isinstance(cfg["history"], list):
        cfg["history"] = []
    return cfg


def _load() -> dict:
    raw = store.read_json(STATE_PATH, {})
    return raw if isinstance(raw, dict) else {}


def _save(data: dict) -> None:
    store.write_json(STATE_PATH, data)


_NOTE_FINAL = "## 可直接用于风格档案的说明"
_NOTE_FINAL_LEGACY = "## 可直接写入人格的风格说明"
_NOTE_TOPICS = ("## 语言风格", "## 口头禅", "## 标点", "## 话题", "## 情绪")


def _summarize_note(inst: dict, provider_id: str, prompt: str) -> str:
    """生成并校验学习笔记；不合格时用更高 token 预算重试一次。"""
    last_problem = ""
    for attempt in (1, 2):
        text = prompt
        if attempt == 2:
            text += (
                "\n\n上次输出没有通过校验（缺少完整小节或被截断）。请重新输出完整六个小节，"
                "最后一节「## 可直接用于风格档案的说明」必须完整写出，不要只写标题，不要截断。"
            )
        note = llm.chat(
            inst,
            provider_id,
            [
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": text},
            ],
            max_tokens=6000 if attempt == 1 else 9000,
            timeout=240,
        )
        note = note.replace(BEGIN, "").replace(END, "").strip()
        if len(note) > MAX_NOTE:
            note = note[:MAX_NOTE].rstrip()
        last_problem = note_problem(note)
        if not last_problem:
            return note
        _trace(f"学习笔记第 {attempt} 次未通过：{last_problem}")
    raise RuntimeError(f"学习笔记不合格：{last_problem}")


def note_problem(note: str) -> str:
    """检查模型返回的学习笔记是否完整；返回空字符串表示可用。"""
    text = str(note or "").strip()
    if len(text) < 200:
        return "笔记太短（少于 200 字）"
    if not re.search(r"[\u4e00-\u9fff]", text):
        return "笔记没有中文内容"
    if _NOTE_FINAL not in text and _NOTE_FINAL_LEGACY not in text:
        return "缺少「可直接用于风格档案的说明」小节"
    if not any(section in text for section in _NOTE_TOPICS):
        return "缺少语言风格/口头禅/标点/话题/情绪小节"
    if re.fullmatch(r"[\s\->*#、。，,.!?！？:：`~\-]*空[\s\->*#、。，,.!?！？:：`~\-]*", text):
        return "笔记只有空内容"
    return ""


def _current_provider(inst: dict) -> str:
    try:
        profile = dashboard.call(inst, "GET", "config-profiles/default", timeout=20)
        config = (profile.get("data") or {}).get("config") or {}
        model = ((config.get("agent_runner") or {}).get("config") or {}).get("model") or {}
        return str(model.get("provider_id") or "")
    except dashboard.DashboardError:
        return ""


def _chat_providers(inst: dict) -> list[dict]:
    try:
        data = dashboard.call(inst, "GET", "providers", timeout=20)
    except dashboard.DashboardError:
        return []
    items = (data.get("data") or {})
    if isinstance(items, dict):
        items = items.get("providers") or items.get("items") or []
    return [
        p
        for p in items
        if isinstance(p, dict) and p.get("provider_type") == "chat_completion"
    ]


def _pick_sources(inst: dict) -> list[dict]:
    sources = learn.list_sources(inst)
    merged: list[dict] = []
    for item in sources.get("qq") or []:
        merged.append(
            {
                "kind": "qq",
                "key": item.get("key"),
                "label": item.get("label") or item.get("key"),
                "count": int(item.get("count") or 0),
                "last_at": str(item.get("last_at") or ""),
            }
        )
    for item in sources.get("bili") or []:
        merged.append(
            {
                "kind": "bili",
                "key": item.get("key"),
                "label": item.get("label") or "B站私信",
                "count": int(item.get("count") or 0),
                "last_at": str(item.get("last_at") or ""),
            }
        )
    merged = [s for s in merged if s.get("key") and s["count"] >= MIN_SOURCE_COUNT]
    merged.sort(key=lambda s: s.get("last_at") or "", reverse=True)
    return merged[:MAX_SOURCES]


class AutoLearn:
    """定时对每个启用实例做一轮聊天记录学习。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running: set[str] = set()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- api

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="auto-learn"
        )
        self._thread.start()

    def snapshot(self) -> dict:
        data = _load()
        out: dict[str, dict] = {}
        with self._lock:
            running = set(self._running)
        for inst in store.load_instances():
            iid = inst["id"]
            cfg = _merge(data.get(iid))
            interval = int(cfg.get("interval_min") or DEFAULT_INTERVAL)
            due_at = float(cfg.get("last_run_at") or 0) + interval * 60
            cfg["running"] = iid in running
            cfg["next_run_in"] = (
                max(0, int(due_at - time.time())) if cfg.get("enabled") else None
            )
            cfg["last_run_text"] = _fmt_ts(cfg.get("last_run_at"))
            out[iid] = cfg
        return out

    def update(self, inst_id: str, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise ValueError("参数格式不正确")
        with self._lock:
            data = _load()
            cfg = _merge(data.get(inst_id))
            if "enabled" in patch:
                cfg["enabled"] = bool(patch.get("enabled"))
            if "interval_min" in patch:
                try:
                    cfg["interval_min"] = max(10, min(int(patch.get("interval_min")), 1440))
                except Exception:
                    raise ValueError("周期必须是 10-1440 之间的整数")
            if "limit" in patch:
                try:
                    cfg["limit"] = max(20, min(int(patch.get("limit")), 500))
                except Exception:
                    raise ValueError("抽样条数必须是 20-500 之间的整数")
            if "persona_id" in patch:
                cfg["persona_id"] = str(patch.get("persona_id") or "").strip()[:64]
            if "provider_id" in patch:
                cfg["provider_id"] = str(patch.get("provider_id") or "").strip()[:64]
            data[inst_id] = cfg
            _save(data)
        return cfg

    def trigger(self, inst_id: str, force: bool = True, dry_run: bool = False) -> bool:
        inst = next(
            (i for i in store.load_instances() if i.get("id") == inst_id), None
        )
        if not inst:
            return False
        with self._lock:
            if inst_id in self._running:
                return False
            self._running.add(inst_id)
        threading.Thread(
            target=self._work,
            args=(inst, force, dry_run),
            daemon=True,
            name=f"auto-learn-{inst_id}",
        ).start()
        return True

    def reset_note(self, inst_id: str) -> None:
        """清除自动学习的旧笔记，避免下一次学习继续拿脏笔记当基础。"""
        with self._lock:
            data = _load()
            cfg = _merge(data.get(inst_id))
            cfg["note"] = ""
            cfg["last_status"] = "cleared"
            cfg["last_message"] = "已清除自动学习笔记"
            data[inst_id] = cfg
            _save(data)

    # ------------------------------------------------------------ internals

    def _loop(self) -> None:
        _trace("全自动学习已启动")
        while True:
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                _trace(f"调度异常：{exc}")
            time.sleep(CHECK_INTERVAL)

    def tick(self) -> None:
        data = _load()
        now = time.time()
        with self._lock:
            running = set(self._running)
        for inst in store.load_instances():
            iid = inst.get("id")
            if not iid:
                continue
            cfg = _merge(data.get(iid))
            if not cfg.get("enabled") or iid in running:
                continue
            interval = int(cfg.get("interval_min") or DEFAULT_INTERVAL)
            if now < float(cfg.get("last_run_at") or 0) + interval * 60:
                continue
            self.trigger(iid, force=False)

    def _work(self, inst: dict, force: bool, dry_run: bool = False) -> None:
        iid = inst["id"]
        name = inst.get("name") or iid
        try:
            if not runner.status(inst).get("running"):
                self._record(
                    iid,
                    status="wait",
                    message="机器人未运行，等待下次再试",
                    bump=False,
                )
                return
            self._run_once(inst, force, dry_run)
        except Exception as exc:  # noqa: BLE001
            _trace(f"[{name}] 自动学习失败：{exc}")
            self._record(iid, status="error", message=f"自动学习失败：{exc}")
        finally:
            with self._lock:
                self._running.discard(iid)

    def _run_once(self, inst: dict, force: bool, dry_run: bool = False) -> None:
        iid = inst["id"]
        cfg = _merge(_load().get(iid))

        sources = _pick_sources(inst)
        latest = max((s.get("last_at") or "" for s in sources), default="")
        if not force and cfg.get("last_source_at") and latest and latest <= cfg["last_source_at"]:
            self._record(iid, status="skip", message="没有新的聊天记录，等下次再试")
            return
        if not sources:
            self._record(iid, status="skip", message="没有可学习的聊天记录（需至少几条消息）")
            return

        limit = int(cfg.get("limit") or 200)
        per_limit = max(30, limit // len(sources))
        messages: list[dict] = []
        for item in sources:
            try:
                batch = learn.sample(inst, item["kind"], item["key"], "", per_limit)
            except Exception:
                batch = []
            for msg in batch:
                messages.append(
                    {"time": msg.get("time") or "", "sender": msg.get("sender") or "未知", "text": msg.get("text") or ""}
                )
        seen: set[tuple[str, str]] = set()
        unique: list[dict] = []
        for msg in messages:
            key = (msg["sender"], msg["text"])
            if not msg["text"] or key in seen:
                continue
            seen.add(key)
            unique.append(msg)
        unique.sort(key=lambda m: m.get("time") or "")
        unique = unique[:limit]

        if len(unique) < MIN_MESSAGES:
            self._record(
                iid,
                status="skip",
                message=f"聊天记录太少（{'、'.join(s['label'] for s in sources)} 共 {len(unique)} 条），本次跳过",
                sampled=len(unique),
                sources=[s["label"] for s in sources],
            )
            return

        provider_id = str(cfg.get("provider_id") or "").strip() or _current_provider(inst)
        if not provider_id:
            providers = _chat_providers(inst)
            provider_id = str(providers[0].get("id") or "") if providers else ""
        if not provider_id:
            raise RuntimeError("没有可用的对话模型，请先在「模型与人格」设置默认模型")

        counts: dict[str, int] = {}
        for msg in unique:
            counts[msg["sender"]] = counts.get(msg["sender"], 0) + 1
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:6]
        target = "、".join(name for name, _ in top) or "该会话中的成员"

        transcript = "\n".join(f"{m['sender']}：{m['text']}" for m in unique)
        if len(transcript) > MAX_TRANSCRIPT:
            transcript = transcript[:MAX_TRANSCRIPT]
        previous = str(cfg.get("note") or "").strip()
        prompt = (
            f"目标：从聊天记录里学习「{target}」的说话风格，供另一个 AI 模仿。\n"
            f"以下是最近抽到的聊天记录（每行「昵称：内容」）：\n{transcript}\n\n"
            f"上次的总结（请在它基础上更新：保留仍然准确的要点，补充新观察，"
            f"删掉已经不准的内容）：\n{previous or '（还没有）'}\n\n"
            "要求：只依据上述记录与上次总结，输出 Markdown，包含以下六个小节：\n"
            "## 语言风格\n## 口头禅与语气词\n## 标点与表情习惯\n## 话题偏好\n"
            "## 情绪与互动方式\n## 可直接用于风格档案的说明\n"
            "六个小节都要完整写出，特别是最后一节，不要只写标题，不要截断。"
            "最后一节用 150-250 字，写成可以直接作为风格档案使用的中文说明。"
        )
        note = _summarize_note(inst, provider_id, prompt)
        if not note:
            raise RuntimeError("模型没有返回学习笔记")

        style_name = "自动学习"
        if dry_run:
            self._record(
                iid,
                status="preview",
                message=f"试学完成（仅预览，未保存）：{len(unique)} 条 -> 风格档案「{style_name}」",
                sampled=len(unique),
                sources=[s["label"] for s in sources],
                note=note,
                source_at=latest,
                bump=False,
            )
            _trace(
                f"[{inst.get('name') or iid}] 自动学习试跑：{len(unique)} 条 -> 风格档案「{style_name}」（未写入）"
            )
            return

        styles.save_auto_style(iid, style_name, note)
        self._record(
            iid,
            status="ok",
            message=f"已学习 {len(unique)} 条消息，追加到风格档案",
            sampled=len(unique),
            sources=[s["label"] for s in sources],
            note=note,
            source_at=latest,
        )
        _trace(
            f"[{inst.get('name') or iid}] 自动学习完成：{len(unique)} 条 -> 风格档案「{style_name}」"
        )

    def _record(
        self,
        iid: str,
        *,
        status: str,
        message: str,
        sampled: int = 0,
        sources: list[str] | None = None,
        note: str = "",
        source_at: str = "",
        bump: bool = True,
    ) -> None:
        with self._lock:
            data = _load()
            cfg = _merge(data.get(iid))
            if bump:
                cfg["last_run_at"] = time.time()
            cfg["last_status"] = status
            cfg["last_error"] = message if status == "error" else ""
            cfg["last_message"] = message
            if sampled:
                cfg["last_sampled"] = sampled
            if sources:
                cfg["last_sources"] = list(sources)
            if note:
                cfg["note"] = note
            if source_at:
                cfg["last_source_at"] = source_at
            history = cfg.get("history") if isinstance(cfg.get("history"), list) else []
            history.insert(
                0,
                {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status": status,
                    "message": message,
                    "sampled": sampled,
                    "sources": list(sources or []),
                },
            )
            cfg["history"] = history[:MAX_HISTORY]
            data[iid] = cfg
            _save(data)


auto_learn = AutoLearn()
