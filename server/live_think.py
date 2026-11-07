"""实时思考中枢：接收机器人插件推送的模型流式分块，并广播给前端。"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections import OrderedDict

MAX_RUNS = 40
MAX_TEXT = 120_000
MAX_EVENT = 2_000
HEARTBEAT = 15.0


class LiveThinkHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: OrderedDict[str, dict] = OrderedDict()
        self._subs: set[queue.Queue] = set()

    # ------------------------------------------------------------ 内部
    def _trim(self) -> None:
        while len(self._runs) > MAX_RUNS:
            # 只淘汰已经结束的最旧记录，避免把正在生成的丢掉
            victim = next(
                (k for k, r in self._runs.items() if r["status"] != "running"), None
            )
            if victim is None:
                break
            self._runs.pop(victim, None)

    @staticmethod
    def _snapshot(run: dict) -> dict:
        return dict(run)

    def _publish(self, event: dict) -> None:
        for sub in list(self._subs):
            try:
                sub.put_nowait(event)
            except queue.Full:
                pass

    # ------------------------------------------------------------ 写入
    def ingest(self, payload: dict, instance_id: str = "", instance_name: str = "") -> dict:
        run_id = str(payload.get("run_id") or "").strip() or uuid.uuid4().hex[:12]
        reasoning_delta = str(payload.get("reasoning_delta") or "")
        content_delta = str(payload.get("content_delta") or "")
        done = bool(payload.get("done"))
        error = str(payload.get("error") or "").strip()
        now = time.time()

        with self._lock:
            run = self._runs.get(run_id)
            started = False
            if run is None:
                run = {
                    "run_id": run_id,
                    "source": str(payload.get("source") or ""),
                    "instance_id": instance_id,
                    "instance_name": instance_name,
                    "model": str(payload.get("model") or ""),
                    "conversation_id": str(payload.get("conversation_id") or ""),
                    "title": str(payload.get("title") or ""),
                    "status": "running",
                    "error": "",
                    "reasoning": "",
                    "content": "",
                    "truncated": False,
                    "started_at": now,
                    "updated_at": now,
                }
                self._runs[run_id] = run
                self._trim()
                started = True
            else:
                if instance_name and not run["instance_name"]:
                    run["instance_name"] = instance_name
                if instance_id and not run["instance_id"]:
                    run["instance_id"] = instance_id
                if payload.get("model") and not run["model"]:
                    run["model"] = str(payload.get("model"))
                if payload.get("conversation_id") and not run["conversation_id"]:
                    run["conversation_id"] = str(payload.get("conversation_id"))
                if payload.get("title") and not run["title"]:
                    run["title"] = str(payload.get("title"))

            if reasoning_delta and not run["truncated"]:
                merged = run["reasoning"] + reasoning_delta
                if len(merged) > MAX_TEXT:
                    run["reasoning"] = merged[:MAX_TEXT]
                    run["truncated"] = True
                else:
                    run["reasoning"] = merged
            if content_delta and not run["truncated"]:
                merged = run["content"] + content_delta
                if len(merged) > MAX_TEXT:
                    run["content"] = merged[:MAX_TEXT]
                    run["truncated"] = True
                else:
                    run["content"] = merged

            run["updated_at"] = now
            if done:
                run["status"] = "error" if error else "done"
                run["error"] = error
                run["updated_at"] = now

            snapshot = self._snapshot(run)

        if started:
            self._publish({"type": "run_start", "run": snapshot})
        if reasoning_delta or content_delta:
            self._publish(
                {
                    "type": "delta",
                    "run_id": run_id,
                    "reasoning": reasoning_delta,
                    "content": content_delta,
                }
            )
        if done:
            self._publish({"type": "run_done", "run": snapshot})
        return snapshot

    def clear(self) -> int:
        with self._lock:
            count = len(self._runs)
            self._runs.clear()
        self._publish({"type": "clear"})
        return count

    # ------------------------------------------------------------ 读取
    def recent(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit or 20), MAX_RUNS))
        with self._lock:
            runs = list(self._runs.values())[-limit:]
        return [self._snapshot(r) for r in reversed(runs)]

    def subscribe(self) -> queue.Queue:
        sub: queue.Queue = queue.Queue(maxsize=MAX_EVENT)
        with self._lock:
            self._subs.add(sub)
        if len(self._subs) > 8:
            # 保险：避免旧页面没断开导致订阅堆积
            with self._lock:
                for old in list(self._subs)[:-8]:
                    self._subs.discard(old)
        return sub

    def unsubscribe(self, sub: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(sub)

    def stream(self, sub: queue.Queue):
        yield f"data: {json.dumps({'type': 'hello', 'runs': self.recent(20)}, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    event = sub.get(timeout=HEARTBEAT)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                if event.get("type") == "delta":
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            self.unsubscribe(sub)


hub = LiveThinkHub()
