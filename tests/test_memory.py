import json
import unittest
from unittest import mock

from fastapi import HTTPException

from server import api, memory
from server.dashboard import DashboardError


class MemoryProxyTests(unittest.TestCase):
    def setUp(self):
        memory._locks.clear()

    def test_normalize_ok_and_error(self):
        self.assertEqual(
            memory.normalize({"status": "ok", "data": {"total": 2}}),
            {"total": 2},
        )
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.normalize({"status": "error", "message": "未找到该路由"})
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(
            memory.normalize(
                {"status": "ok", "data": {"status": "ok", "data": [1, 2]}}
            ),
            [1, 2],
        )
        self.assertEqual(memory.normalize({"status": "ok", "data": [3, 4]}), [3, 4])

    def test_status_and_items_paths(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"ok": True}}

        inst = {"id": "m1"}
        self.assertEqual(memory.call_status(inst, fake_call), {"ok": True})
        memory.call_memories(inst, {"keyword": "地址", "page": 1}, fake_call)
        self.assertEqual(
            calls[0][:2],
            ("GET", "plugins/extensions/astrbot_plugin_livingmemory/page/human/status"),
        )
        self.assertEqual(
            calls[1][:2],
            ("GET", "plugins/extensions/astrbot_plugin_livingmemory/page/memories"),
        )
        self.assertEqual(calls[1][3], {"keyword": "地址", "page": 1})

    def test_update_payload_and_invalid_id(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, timeout))
            return {"status": "ok", "data": {"memory_id": 7}}

        memory.call_update({"id": "m2"}, 7, "importance", 0.8, "手动调整", fake_call)
        self.assertEqual(calls[0][2]["memory_id"], 7)
        self.assertEqual(calls[0][2]["field"], "importance")
        with self.assertRaises(memory.MemoryError):
            memory.call_detail({"id": "m2"}, "bad", fake_call)

    def test_sleep_lock_rejects_second_run(self):
        inst = {"id": "m3"}
        lock = memory.lock_for(inst, "sleep")
        lock.acquire()
        try:
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_sleep_run(inst, lambda *a, **k: {})
            self.assertEqual(ctx.exception.status, 409)
        finally:
            lock.release()

    def test_vector_proxy_paths_and_timeouts(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"ok": True}}

        inst = {"id": "v1"}
        self.assertEqual(memory.call_vector_status(inst, fake_call), {"ok": True})
        self.assertEqual(memory.call_vector_probe(inst, fake_call), {"ok": True})
        self.assertEqual(memory.call_vector_rebuild(inst, fake_call), {"ok": True})
        prefix = "plugins/extensions/astrbot_plugin_livingmemory/page/human/vector"
        self.assertEqual(
            [call[:2] for call in calls],
            [
                ("GET", f"{prefix}/status"),
                ("POST", f"{prefix}/probe"),
                ("POST", f"{prefix}/rebuild"),
            ],
        )
        self.assertEqual(calls[0][4], memory.TIMEOUTS["vector"])
        self.assertEqual(calls[1][4], memory.TIMEOUTS["vector_probe"])
        self.assertEqual(calls[2][4], memory.TIMEOUTS["vector_rebuild"])

    def test_config_filter_rejects_non_human_paths(self):
        with self.assertRaises(memory.MemoryError):
            memory.filter_config_values({"provider_settings.llm_provider_id": "x"})
        with self.assertRaises(memory.MemoryError):
            memory.filter_config_values({"memory_consolidation.keep_original": "archive"})
        self.assertEqual(
            memory.filter_config_values(
                {"human_memory.sleep.time": "03:30"}
            ),
            {"human_memory.sleep.time": "03:30"},
        )

    def test_config_filter_allows_sleep_and_allowlist_fields(self):
        values = {
            "human_memory.sleep.archive_only": True,
            "human_memory.sleep.keep_reports": 60,
            "human_memory.reconsolidation.group_allowlist": "123\n456",
            "memory_consolidation.max_groups_per_run": 5,
        }
        self.assertEqual(memory.filter_config_values(values), values)

    def test_config_filter_allows_two_stage_recall_fields(self):
        values = {
            "recall_engine.two_stage_enabled": True,
            "recall_engine.two_stage_candidates": 30,
            "recall_engine.two_stage_vector_weight": 0.6,
            "recall_engine.two_stage_fuzzy_weight": 0.4,
            "recall_engine.two_stage_vector_k": 8192,
            "recall_engine.cross_context_enabled": True,
            "recall_engine.cross_context_limit": 3,
            "recall_engine.cross_context_private_to_group": True,
            "recall_engine.cross_context_group_to_private": True,
        }
        self.assertEqual(memory.filter_config_values(values), values)

    def test_config_filter_rejects_other_recall_engine_fields(self):
        for path in (
            "recall_engine.top_k",
            "recall_engine.rerank_enabled",
            "recall_engine.two_stage_top_k",
            "recall_engine.cross_context_extra",
        ):
            with self.assertRaises(memory.MemoryError):
                memory.filter_config_values({path: 1})

    def test_arousal_proxy_path_payload_and_validation(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {
                "status": "ok",
                "data": {
                    "memory_id": 136,
                    "before": {"arousal": 0.3, "salience": 0.5},
                    "after": {"arousal": 0.55, "salience": 0.64},
                    "status": "active",
                },
            }

        result = memory.call_arousal_update(
            {"id": "m5"}, 136, 0.55, "  管理员校正  ", fake_call
        )
        self.assertEqual(
            calls[0][:3],
            (
                "POST",
                "plugins/extensions/astrbot_plugin_livingmemory/page/human/memory/arousal",
                {"memory_id": 136, "arousal": 0.55, "reason": "管理员校正"},
            ),
        )
        self.assertEqual(result["after"]["salience"], 0.64)
        self.assertEqual(len(calls), 1)

        for bad in (-0.01, 1.01, float("nan"), float("inf"), "x", None):
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_arousal_update({"id": "m5"}, 136, bad, "", fake_call)
            self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_arousal_update({"id": "m5"}, 136, 0.4, "x" * 121, fake_call)
        self.assertEqual(ctx.exception.status, 400)
        for bad_id in (0, -3, "bad"):
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_arousal_update({"id": "m5"}, bad_id, 0.4, "", fake_call)
            self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 1)

    def test_prompt_preview_proxy(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"needs_merge": True}}

        self.assertEqual(
            memory.call_prompt_preview({"id": "m6"}, "group", fake_call),
            {"needs_merge": True},
        )
        self.assertEqual(
            calls[0][:4],
            (
                "GET",
                "plugins/extensions/astrbot_plugin_livingmemory/page/human/prompt/preview",
                None,
                {"scope": "group"},
            ),
        )
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_prompt_preview({"id": "m6"}, "world", fake_call)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 1)

    def test_prompt_merge_proxy_confirm_and_lock(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"merged": True, "backup_path": "b.txt"}}

        inst = {"id": "m7"}
        self.assertEqual(
            memory.call_prompt_merge(inst, "private", "MERGE", fake_call),
            {"merged": True, "backup_path": "b.txt"},
        )
        self.assertEqual(
            calls[0][:3],
            (
                "POST",
                "plugins/extensions/astrbot_plugin_livingmemory/page/human/prompt/merge",
                {"scope": "private", "confirm": "MERGE"},
            ),
        )
        for confirm in ("", "merge", "MERGE!"):
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_prompt_merge(inst, "private", confirm, fake_call)
            self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(memory.MemoryError):
            memory.call_prompt_merge(inst, "world", "MERGE", fake_call)
        self.assertEqual(len(calls), 1)

        lock = memory.lock_for(inst, "prompt_merge")
        lock.acquire()
        try:
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_prompt_merge(inst, "group", "MERGE", fake_call)
            self.assertEqual(ctx.exception.status, 409)
        finally:
            lock.release()

    def test_working_proxy_path_query_and_clamp(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"sessions": []}}

        inst = {"id": "w1"}
        self.assertEqual(
            memory.call_working(inst, "", 20, fake_call), {"sessions": []}
        )
        memory.call_working(inst, "  s1  ", 500, fake_call)
        memory.call_working(inst, "s2", 0, fake_call)
        self.assertEqual(
            calls[0][:4],
            ("GET", f"{memory.PREFIX}/human/working", None, {"limit": 20}),
        )
        self.assertEqual(calls[1][3], {"limit": 100, "session_id": "s1"})
        self.assertEqual(calls[2][3], {"limit": 1, "session_id": "s2"})
        self.assertEqual(calls[0][4], memory.TIMEOUTS["working"])
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_working(inst, "", "bad", fake_call)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 3)

    def test_relations_proxy_merges_mood_by_platform_and_person_key(self):
        calls = []
        relation_calls = []
        event_calls = []
        cards = [
            {
                "identity_key": "qq:123",
                "platform": "qq",
                "sender_id": "123",
                "display_name": "小明",
                "memory_count": 3,
                "last_seen": 1700000000.0,
                "mean_arousal": 0.5,
                "mean_salience": 0.6,
                "top_types": ["FACT"],
                "sample_memory_ids": [1, 2],
            },
            {
                "identity_key": "telegram:123",
                "platform": "telegram",
                "sender_id": "123",
                "display_name": "TG",
                "memory_count": 1,
                "last_seen": 1.0,
                "mean_arousal": None,
                "mean_salience": None,
                "top_types": [],
                "sample_memory_ids": [9],
            },
            {
                "identity_key": "discord:5",
                "platform": "discord",
                "sender_id": "5",
                "display_name": "DC",
                "memory_count": 1,
            },
        ]

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"relations": cards}}

        def relation_lookup(instance_id, platform, person_key):
            relation_calls.append((instance_id, platform, person_key))
            if (platform, person_key) == ("qq", "123"):
                return {
                    "anger": 12,
                    "affection": -3,
                    "familiarity": 40,
                    "display_name": "小明",
                    "last_seen": 1700000000.0,
                    "updated": 1700000001.0,
                    "last_thread": "qq:1",
                }
            return None

        def events_lookup(instance_id, limit=30):
            event_calls.append((instance_id, limit))
            return [
                {
                    "platform": "qq",
                    "person_key": "123",
                    "created": 1700000002.0,
                    "assessment": {
                        "mood": "annoyed",
                        "reason": "被催促",
                        "tone_hint": "短一点",
                        "anger_delta": 5,
                        "affection_delta": -1,
                        "familiarity_delta": 0,
                    },
                    "after": {
                        "state": {
                            "mood": "annoyed",
                            "intensity": 55,
                            "energy": 60,
                            "social": 50,
                        },
                        "relation": {
                            "anger": 12,
                            "affection": -3,
                            "familiarity": 40,
                        },
                    },
                    "error": "",
                },
                {
                    "platform": "qq",
                    "person_key": "123",
                    "created": 1700000001.0,
                    "assessment": {
                        "mood": "calm",
                        "reason": "闲聊",
                        "tone_hint": "",
                        "anger_delta": 0,
                        "affection_delta": 1,
                        "familiarity_delta": 1,
                    },
                    "after": {
                        "state": {
                            "mood": "calm",
                            "intensity": 45,
                            "energy": 70,
                            "social": 60,
                        },
                        "relation": {
                            "anger": 7,
                            "affection": -2,
                            "familiarity": 40,
                        },
                    },
                    "error": "",
                },
                {
                    "platform": "qq",
                    "person_key": "999",
                    "created": 1700000003.0,
                    "assessment": {"mood": "angry"},
                    "after": {},
                    "error": "",
                },
                {
                    "platform": "telegram",
                    "person_key": "123",
                    "created": 1700000004.0,
                    "assessment": {"mood": "happy"},
                    "after": {},
                    "error": "",
                },
            ]

        result = memory.call_relations(
            {"id": "i1"},
            90,
            100,
            fake_call,
            relation_lookup=relation_lookup,
            events_lookup=events_lookup,
        )
        merged = result["relations"]
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0]["memory_count"], 3)
        self.assertEqual(merged[0]["mood"]["anger"], 12.0)
        self.assertEqual(merged[0]["mood"]["affection"], -3.0)
        self.assertEqual(merged[0]["mood"]["familiarity"], 40.0)
        self.assertEqual(merged[0]["mood"]["display_name"], "小明")
        self.assertEqual(merged[0]["mood"]["thread_key"], "qq:1")
        self.assertEqual(merged[0]["mood"]["current"]["mood"], "annoyed")
        self.assertEqual(merged[0]["mood"]["current"]["label"], "烦躁")
        self.assertEqual(merged[0]["mood"]["current"]["intensity"], 55.0)
        self.assertEqual(len(merged[0]["mood"]["events"]), 2)
        self.assertEqual(merged[0]["mood"]["events"][0]["reason"], "被催促")
        self.assertEqual(merged[0]["mood"]["events"][0]["anger_delta"], 5.0)
        self.assertEqual(merged[0]["mood"]["events"][0]["anger"], 12.0)
        self.assertEqual(merged[1]["mood"]["events"][0]["mood"], "happy")
        self.assertEqual(merged[1]["mood"]["anger"], 0.0)
        self.assertIsNone(merged[2]["mood"])
        self.assertEqual(
            relation_calls,
            [("i1", "qq", "123"), ("i1", "telegram", "123"), ("i1", "discord", "5")],
        )
        self.assertEqual(event_calls, [("i1", 200)])
        self.assertNotIn("mood", cards[0])
        self.assertEqual(
            calls[0][:4],
            ("GET", f"{memory.PREFIX}/human/relations", None, {"days": 90, "limit": 100}),
        )
        self.assertEqual(calls[0][4], memory.TIMEOUTS["relations"])

    def test_relations_merge_normalizes_aiocqhttp_to_qq(self):
        relation_calls = []
        cards = [{
            "identity_key": "aiocqhttp:10003",
            "platform": "aiocqhttp",
            "sender_id": "10003",
            "display_name": "群友甲、",
            "memory_count": 77,
            "last_seen": 1793937612.5,
        }]

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            return {"status": "ok", "data": {"relations": cards}}

        def relation_lookup(instance_id, platform, person_key):
            relation_calls.append((platform, person_key))
            if (platform, person_key) == ("qq", "10003"):
                return {"anger": 2.6, "affection": 13.43, "familiarity": 11.0,
                        "display_name": "群友甲、", "last_seen": 1793964020.0}
            return None

        def events_lookup(instance_id, limit=200):
            return [{
                "platform": "qq", "person_key": "10003",
                "created": 1793964020.0,
                "assessment": {"mood": "calm"},
                "after": {"state": {"mood": "calm", "intensity": 52.5}},
                "error": "",
            }]

        result = memory.call_relations(
            {"id": "i1"}, 90, 100, fake_call,
            relation_lookup=relation_lookup, events_lookup=events_lookup)
        item = result["relations"][0]
        self.assertEqual(item["platform"], "aiocqhttp")
        self.assertEqual(relation_calls, [("qq", "10003")])
        self.assertEqual(item["mood"]["affection"], 13.43)
        self.assertEqual(item["mood"]["familiarity"], 11.0)
        self.assertEqual(item["mood"]["current"]["mood"], "calm")

    def test_relations_merge_degrades_when_mood_store_unavailable(self):
        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            return {
                "status": "ok",
                "data": {
                    "relations": [
                        {"identity_key": "qq:1", "platform": "qq", "sender_id": "1"}
                    ]
                },
            }

        def boom(*args, **kwargs):
            raise RuntimeError("database is locked")

        result = memory.call_relations(
            {"id": "i1"},
            30,
            10,
            fake_call,
            relation_lookup=boom,
            events_lookup=boom,
        )
        self.assertIsNone(result["relations"][0]["mood"])

    def test_emotion_proxy_requires_identity_and_clamps(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"items": []}}

        inst = {"id": "e1"}
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_emotion(inst, "   ", 90, 200, fake_call)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(calls, [])
        memory.call_emotion(inst, " qq:123 ", 99999, 9999, fake_call)
        self.assertEqual(
            calls[0][:4],
            (
                "GET",
                f"{memory.PREFIX}/human/emotion",
                None,
                {"identity_key": "qq:123", "days": 3650, "limit": 500},
            ),
        )
        for bad in ("x", "1.5"):
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_emotion(inst, "qq:1", bad, 200, fake_call)
            self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 1)

    def test_forgetting_proxy_status_and_clamp(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"items": []}}

        inst = {"id": "f1"}
        memory.call_forgetting(inst, call=fake_call)
        memory.call_forgetting(inst, 9999, "ARCHIVED", fake_call)
        self.assertEqual(
            calls[0][:4],
            (
                "GET",
                f"{memory.PREFIX}/human/health/forgetting",
                None,
                {"limit": 50, "status": "active"},
            ),
        )
        self.assertEqual(calls[1][3], {"limit": 200, "status": "archived"})
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_forgetting(inst, 50, "deleted", fake_call)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 2)

    def test_review_preview_proxy_is_read_only_and_lock_free(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"writes": False}}

        inst = {"id": "r1"}
        # A held write lock must not block the read-only preview.
        lock = memory.lock_for(inst, "sleep")
        lock.acquire()
        try:
            self.assertEqual(
                memory.call_review_preview(inst, 42, fake_call), {"writes": False}
            )
        finally:
            lock.release()
        self.assertFalse(lock.locked())
        self.assertEqual(set(memory._locks), {"r1:sleep"})
        self.assertEqual(
            calls[0][:3],
            (
                "POST",
                f"{memory.PREFIX}/human/health/review-preview",
                {"memory_id": 42},
            ),
        )
        self.assertEqual(calls[0][4], memory.TIMEOUTS["review_preview"])
        for bad in (0, -2, "x", None):
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_review_preview(inst, bad, fake_call)
            self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 1)

    def test_export_fetches_filtered_pages_without_embeddings(self):
        calls = []
        pages = {
            1: {
                "items": [
                    {
                        "id": 1,
                        "text": "主人喜欢猫",
                        "created_at": "2026-11-01T00:00:00",
                        "metadata": {
                            "memory_type": "PREFERENCE",
                            "embedding": [0.1, 0.2],
                            "nested": {"vector": [3], "ok": 1},
                        },
                    },
                    {
                        "id": 2,
                        "text": "",
                        "created_at": "2026-11-02T00:00:00",
                        "metadata": json.dumps(
                            {"canonical_summary": "猫", "embedding": [9]}
                        ),
                    },
                ],
                "has_more": True,
                "total": 3,
            },
            2: {
                "items": [
                    {
                        "id": 3,
                        "text": "狗",
                        "created_at": "2026-11-03T00:00:00",
                        "metadata": {"embeddings": [1], "importance": 0.4},
                    }
                ],
                "has_more": False,
                "total": 3,
            },
        }

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, dict(query or {}), timeout))
            return {"status": "ok", "data": pages[int(query["page"])]}

        result = memory.export_memories(
            {"id": "i1", "name": "大肥鱼"},
            {"q": " 猫 ", "type": "FACT", "status": "active"},
            fake_call,
        )
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["total"], 3)
        self.assertFalse(result["truncated"])
        self.assertEqual([row["id"] for row in result["items"]], [1, 2, 3])
        for row in result["items"]:
            self.assertEqual(set(row), {"id", "text", "metadata", "created_at"})
        self.assertNotIn("embedding", result["items"][0]["metadata"])
        self.assertNotIn("vector", result["items"][0]["metadata"]["nested"])
        self.assertEqual(result["items"][0]["metadata"]["nested"]["ok"], 1)
        self.assertEqual(result["items"][1]["metadata"], {"canonical_summary": "猫"})
        self.assertNotIn("embeddings", result["items"][2]["metadata"])
        self.assertEqual(result["items"][2]["metadata"]["importance"], 0.4)
        self.assertEqual(result["filters"], {"q": "猫", "type": "FACT", "status": "active"})
        self.assertEqual(calls[0][:2], ("GET", f"{memory.PREFIX}/memories"))
        self.assertEqual(
            calls[0][3],
            {
                "keyword": "猫",
                "type": "FACT",
                "status": "active",
                "sort": "created_desc",
                "page": 1,
                "page_size": 200,
            },
        )
        self.assertEqual([call[3]["page"] for call in calls], [1, 2])
        self.assertEqual({call[0] for call in calls}, {"GET"})
        self.assertRegex(
            result["filename"], r"^memory-[A-Za-z0-9_-]+-\d{8}-\d{6}\.json$"
        )

    def test_export_rejects_bad_status_and_marks_truncation(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {
                "status": "ok",
                "data": {"items": [{"id": 1, "text": "x"}], "has_more": True, "total": 9},
            }

        with self.assertRaises(memory.MemoryError) as ctx:
            memory.export_memories({"id": "i1"}, {"status": "deleted"}, fake_call)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(calls, [])
        result = memory.export_memories(
            {"id": "i1"}, {"status": "all"}, fake_call, max_pages=1
        )
        self.assertTrue(result["truncated"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total"], 9)
        self.assertEqual(len(calls), 1)

    def test_export_filename_is_header_safe(self):
        filename = memory.export_filename(
            {"id": "i1", "name": '大肥鱼"\r\nX'}, now=1700000000
        )
        self.assertRegex(filename, r"^memory-i1-\d{8}-\d{6}\.json$")
        for bad in ('"', "\r", "\n", "/", "\\", " "):
            self.assertNotIn(bad, filename)
        fallback = memory.export_filename({"id": "", "name": "大肥鱼"}, now=1700000000)
        self.assertRegex(fallback, r"^memory-instance-\d{8}-\d{6}\.json$")
        injected = memory.export_filename(
            {"id": "", "name": 'evil; filename="x" y'}, now=1700000000
        )
        self.assertRegex(injected, r"^memory-evil-filename-x-y-\d{8}-\d{6}\.json$")
        self.assertNotIn('"', injected)

    def test_active_recall_status_and_events_proxy(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"items": [], "count": 0}}

        inst = {"id": "ar1"}
        memory.call_active_recall_status(inst, fake_call)
        memory.call_active_recall_events(inst, call=fake_call)
        memory.call_active_recall_events(inst, 999, fake_call)
        memory.call_active_recall_events(inst, 0, fake_call)
        self.assertEqual(
            calls[0][:2],
            (
                "GET",
                "plugins/extensions/astrbot_plugin_livingmemory/page/human/active-recall/status",
            ),
        )
        self.assertIsNone(calls[0][3])
        self.assertEqual(calls[0][4], memory.TIMEOUTS["active_recall"])
        self.assertEqual(
            calls[1][:2],
            (
                "GET",
                "plugins/extensions/astrbot_plugin_livingmemory/page/human/active-recall/events",
            ),
        )
        self.assertEqual(calls[1][3], {"limit": 50})
        self.assertEqual(calls[2][3], {"limit": 200})
        self.assertEqual(calls[3][3], {"limit": 1})
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_active_recall_events(inst, "many", fake_call)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 4)

    def test_active_recall_preview_proxy_body_and_validation(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"selected": []}}

        inst = {"id": "ar2"}
        memory.call_active_recall_preview(inst, "  猫  ", " s1 ", fake_call)
        memory.call_active_recall_preview(inst, "猫", "", fake_call)
        self.assertEqual(
            calls[0][:3],
            (
                "POST",
                "plugins/extensions/astrbot_plugin_livingmemory/page/human/active-recall/preview",
                {"query": "猫", "session_id": "s1"},
            ),
        )
        self.assertEqual(calls[0][4], memory.TIMEOUTS["active_recall_preview"])
        self.assertEqual(calls[1][2], {"query": "猫"})
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_active_recall_preview(inst, "   ", call=fake_call)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 2)

    def test_review_proxy_requires_review_confirm_and_locks(self):
        calls = []

        def fake_call(inst, method, path, body=None, query=None, timeout=60):
            calls.append((method, path, body, query, timeout))
            return {"status": "ok", "data": {"memory_id": 42, "status": "reviewed"}}

        inst = {"id": "rv1"}
        for confirm in ("", "review", "yes"):
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_review(inst, 42, confirm, fake_call)
            self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_review(inst, 0, "REVIEW", fake_call)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(calls, [])

        self.assertEqual(
            memory.call_review(inst, 42, "REVIEW", fake_call),
            {"memory_id": 42, "status": "reviewed"},
        )
        self.assertEqual(
            calls[0][:3],
            (
                "POST",
                "plugins/extensions/astrbot_plugin_livingmemory/page/human/health/review",
                {"memory_id": 42, "confirm": "REVIEW"},
            ),
        )
        self.assertEqual(calls[0][4], memory.TIMEOUTS["review"])

        lock = memory.lock_for(inst, "review")
        lock.acquire()
        try:
            with self.assertRaises(memory.MemoryError) as ctx:
                memory.call_review(inst, 42, "REVIEW", fake_call)
            self.assertEqual(ctx.exception.status, 409)
        finally:
            lock.release()
        # A finished review releases the lock for the next confirmation.
        memory.call_review(inst, 42, "REVIEW", fake_call)
        self.assertEqual(len(calls), 2)

    def test_config_filter_allows_active_recall_fields(self):
        values = {
            "human_memory.active_recall.enabled": True,
            "human_memory.active_recall.shadow": True,
            "human_memory.active_recall.min_score": 0.6,
        }
        self.assertEqual(memory.filter_config_values(values), values)
        with self.assertRaises(memory.MemoryError):
            memory.filter_config_values({"active_recall.enabled": True})

    def test_offline_instance_surfaces_503(self):
        def fake_call(*args, **kwargs):
            raise DashboardError(
                "无法连接 Dashboard（http://127.0.0.1:6185）：连接被拒绝", 503
            )

        for action in (
            lambda: memory.call_working({"id": "o1"}, "", 20, fake_call),
            lambda: memory.call_relations({"id": "o1"}, 90, 100, fake_call),
            lambda: memory.call_emotion({"id": "o1"}, "qq:1", 90, 200, fake_call),
            lambda: memory.call_forgetting({"id": "o1"}, 50, "active", fake_call),
            lambda: memory.call_review_preview({"id": "o1"}, 1, fake_call),
            lambda: memory.call_active_recall_status({"id": "o1"}, fake_call),
            lambda: memory.call_active_recall_events({"id": "o1"}, 50, fake_call),
            lambda: memory.call_active_recall_preview({"id": "o1"}, "猫", "", fake_call),
            lambda: memory.call_review({"id": "o1"}, 1, "REVIEW", fake_call),
            lambda: memory.export_memories({"id": "o1"}, {}, fake_call),
        ):
            with self.assertRaises(memory.MemoryError) as ctx:
                action()
            self.assertEqual(ctx.exception.status, 503)

    def test_dashboard_error_is_wrapped(self):
        def fake_call(*args, **kwargs):
            raise DashboardError("Dashboard 登录失败", 401)

        with self.assertRaises(memory.MemoryError) as ctx:
            memory.call_status({"id": "m4"}, fake_call)
        self.assertEqual(ctx.exception.status, 401)


class MemoryApiRouteTest(unittest.TestCase):
    def setUp(self):
        memory._locks.clear()
        self.inst = {"id": "i1", "name": "大肥鱼"}

    def test_routes_registered(self):
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in (
            "/api/instances/{inst_id}/memory/items/{memory_id}/arousal",
            "/api/instances/{inst_id}/memory/prompt/preview",
            "/api/instances/{inst_id}/memory/prompt/merge",
        ):
            self.assertIn(path, paths)

    def test_arousal_route_400_404_409_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException) as ctx:
                api.memory_arousal("nope", 136, {"arousal": 0.5})
            self.assertEqual(ctx.exception.status_code, 404)
            failed = api.memory_arousal("i1", 136, {})
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_arousal("i1", 136, {"arousal": -0.1})
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_arousal("i1", 136, {"arousal": 0.4, "reason": "x" * 121})
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(
                api.memory,
                "call_arousal_update",
                side_effect=memory.MemoryError("已有睡眠任务在运行", 409),
            ):
                failed = api.memory_arousal("i1", 136, {"arousal": 0.5})
            self.assertEqual(failed.status_code, 409)
            with mock.patch.object(
                api.memory,
                "call_arousal_update",
                return_value={"after": {"salience": 0.7}},
            ) as updater:
                result = api.memory_arousal(
                    "i1", 136, {"arousal": 0.5, "reason": "校正"}
                )
        updater.assert_called_once_with(self.inst, 136, 0.5, "校正")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["after"]["salience"], 0.7)

    def test_prompt_preview_route_400_404_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException):
                api.memory_prompt_preview("nope")
            failed = api.memory_prompt_preview("i1", "world")
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(
                api.memory, "call_prompt_preview", return_value={"needs_merge": True}
            ) as preview:
                result = api.memory_prompt_preview("i1", "group")
        preview.assert_called_once_with(self.inst, "group")
        self.assertEqual(result["data"], {"needs_merge": True})

    def test_prompt_merge_route_400_404_409_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException):
                api.memory_prompt_merge("nope", {"scope": "private", "confirm": "MERGE"})
            failed = api.memory_prompt_merge("i1", {"scope": "private", "confirm": "yes"})
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_prompt_merge("i1", {"scope": "world", "confirm": "MERGE"})
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(
                api.memory,
                "call_prompt_merge",
                side_effect=memory.MemoryError("已有提示词合并任务在运行", 409),
            ):
                failed = api.memory_prompt_merge(
                    "i1", {"scope": "group", "confirm": "MERGE"}
                )
            self.assertEqual(failed.status_code, 409)
            with mock.patch.object(
                api.memory, "call_prompt_merge", return_value={"merged": True}
            ) as merge:
                result = api.memory_prompt_merge(
                    "i1", {"scope": "group", "confirm": "MERGE"}
                )
        merge.assert_called_once_with(self.inst, "group", "MERGE")
        self.assertEqual(result["data"], {"merged": True})

    def test_b2_routes_registered(self):
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in (
            "/api/instances/{inst_id}/memory/working",
            "/api/instances/{inst_id}/memory/relations",
            "/api/instances/{inst_id}/memory/emotion",
            "/api/instances/{inst_id}/memory/health/forgetting",
            "/api/instances/{inst_id}/memory/health/review-preview",
            "/api/instances/{inst_id}/memory/export",
            "/api/instances/{inst_id}/memory/vector/status",
            "/api/instances/{inst_id}/memory/vector/probe",
            "/api/instances/{inst_id}/memory/vector/rebuild",
        ):
            self.assertIn(path, paths)

    def test_working_route_404_offline_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException) as ctx:
                api.memory_working("nope")
            self.assertEqual(ctx.exception.status_code, 404)
            with mock.patch.object(
                api.memory,
                "call_working",
                side_effect=memory.MemoryError("实例离线", 503),
            ):
                failed = api.memory_working("i1")
            self.assertEqual(failed.status_code, 503)
            with mock.patch.object(
                api.memory, "call_working", return_value={"sessions": []}
            ) as worker:
                result = api.memory_working("i1", " s1 ", 500)
        worker.assert_called_once_with(self.inst, " s1 ", 500)
        self.assertEqual(result["data"], {"sessions": []})

    def test_relations_route_passes_days_and_limit(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with mock.patch.object(
                api.memory, "call_relations", return_value={"relations": []}
            ) as relations:
                result = api.memory_relations("i1", 120, 50)
        relations.assert_called_once_with(self.inst, 120, 50)
        self.assertEqual(result["data"], {"relations": []})

    def test_emotion_route_400_404_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException):
                api.memory_emotion("nope", "qq:1")
            failed = api.memory_emotion("i1", "   ")
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(
                api.memory, "call_emotion", return_value={"items": []}
            ) as emotion:
                result = api.memory_emotion("i1", "qq:1", 30, 10)
        emotion.assert_called_once_with(self.inst, "qq:1", 30, 10)
        self.assertEqual(result["data"], {"items": []})

    def test_forgetting_route_400_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with mock.patch.object(
                api.memory,
                "call_forgetting",
                side_effect=memory.MemoryError("status 必须是 active、archived 或 all", 400),
            ):
                failed = api.memory_health_forgetting("i1", 50, "deleted")
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(
                api.memory, "call_forgetting", return_value={"items": []}
            ) as forgetting:
                result = api.memory_health_forgetting("i1", 20, "archived")
        forgetting.assert_called_once_with(self.inst, 20, "archived")
        self.assertEqual(result["data"], {"items": []})

    def test_review_preview_route_400_404_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException):
                api.memory_health_review_preview("nope", {"memory_id": 12})
            failed = api.memory_health_review_preview("i1", {})
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_health_review_preview("i1", {"memory_id": "x"})
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_health_review_preview("i1", {"memory_id": 0})
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(
                api.memory,
                "call_review_preview",
                side_effect=memory.MemoryError("记忆不存在", 404),
            ):
                failed = api.memory_health_review_preview("i1", {"memory_id": 99})
            self.assertEqual(failed.status_code, 404)
            with mock.patch.object(
                api.memory, "call_review_preview", return_value={"writes": False}
            ) as preview:
                result = api.memory_health_review_preview("i1", {"memory_id": 12})
        preview.assert_called_once_with(self.inst, 12)
        self.assertEqual(result["data"], {"writes": False})

    def test_b3_routes_registered(self):
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in (
            "/api/instances/{inst_id}/memory/active-recall/status",
            "/api/instances/{inst_id}/memory/active-recall/events",
            "/api/instances/{inst_id}/memory/active-recall/preview",
            "/api/instances/{inst_id}/memory/health/review",
        ):
            self.assertIn(path, paths)

    def test_active_recall_status_and_events_routes(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException) as ctx:
                api.memory_active_recall_status("nope")
            self.assertEqual(ctx.exception.status_code, 404)
            with mock.patch.object(
                api.memory,
                "call_active_recall_status",
                side_effect=memory.MemoryError("主动回忆未初始化", 409),
            ):
                failed = api.memory_active_recall_status("i1")
            self.assertEqual(failed.status_code, 409)
            with mock.patch.object(
                api.memory,
                "call_active_recall_status",
                return_value={"enabled": False},
            ) as status:
                result = api.memory_active_recall_status("i1")
        status.assert_called_once_with(self.inst)
        self.assertEqual(result["data"], {"enabled": False})
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with mock.patch.object(
                api.memory,
                "call_active_recall_events",
                side_effect=memory.MemoryError("limit 必须是整数", 400),
            ):
                failed = api.memory_active_recall_events("i1", 500)
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(
                api.memory,
                "call_active_recall_events",
                return_value={"items": [], "count": 0},
            ) as events:
                result = api.memory_active_recall_events("i1", 20)
        events.assert_called_once_with(self.inst, 20)
        self.assertEqual(result["data"]["count"], 0)

    def test_active_recall_preview_route_400_404_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException):
                api.memory_active_recall_preview("nope", {"query": "猫"})
            failed = api.memory_active_recall_preview("i1", {})
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_active_recall_preview("i1", {"query": "   "})
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(
                api.memory,
                "call_active_recall_preview",
                side_effect=memory.MemoryError("主动回忆未初始化", 409),
            ):
                failed = api.memory_active_recall_preview("i1", {"query": "猫"})
            self.assertEqual(failed.status_code, 409)
            with mock.patch.object(
                api.memory,
                "call_active_recall_preview",
                return_value={"selected": []},
            ) as preview:
                result = api.memory_active_recall_preview(
                    "i1", {"query": " 猫 ", "session_id": " s1 "}
                )
        preview.assert_called_once_with(self.inst, "猫", " s1 ")
        self.assertEqual(result["data"], {"selected": []})

    def test_health_review_route_400_404_409_and_success(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException) as ctx:
                api.memory_health_review("nope", {"memory_id": 42, "confirm": "REVIEW"})
            self.assertEqual(ctx.exception.status_code, 404)
            failed = api.memory_health_review("i1", {"confirm": "REVIEW"})
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_health_review(
                "i1", {"memory_id": "x", "confirm": "REVIEW"}
            )
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_health_review(
                "i1", {"memory_id": 0, "confirm": "REVIEW"}
            )
            self.assertEqual(failed.status_code, 400)
            failed = api.memory_health_review(
                "i1", {"memory_id": 42, "confirm": "yes"}
            )
            self.assertEqual(failed.status_code, 400)
            with mock.patch.object(api.memory, "call_review") as review:
                failed = api.memory_health_review("i1", {"memory_id": 42, "confirm": ""})
            self.assertEqual(failed.status_code, 400)
            review.assert_not_called()
            with mock.patch.object(
                api.memory,
                "call_review",
                side_effect=memory.MemoryError("已有复习任务在运行", 409),
            ):
                failed = api.memory_health_review(
                    "i1", {"memory_id": 42, "confirm": "REVIEW"}
                )
            self.assertEqual(failed.status_code, 409)
            with mock.patch.object(
                api.memory, "call_review", return_value={"memory_id": 42}
            ) as review:
                result = api.memory_health_review(
                    "i1", {"memory_id": 42, "confirm": "REVIEW"}
                )
        review.assert_called_once_with(self.inst, 42, "REVIEW")
        self.assertEqual(result["data"], {"memory_id": 42})

    def test_export_route_sets_safe_attachment_headers(self):
        payload = {
            "filename": "memory-i1-20261105-120000.json",
            "count": 1,
            "items": [
                {
                    "id": 1,
                    "text": "猫",
                    "metadata": {},
                    "created_at": "2026-11-01",
                }
            ],
        }
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException):
                api.memory_export("nope")
            with mock.patch.object(
                api.memory, "export_memories", return_value=payload
            ) as exporter:
                response = api.memory_export("i1", " 猫 ", "FACT", "active")
        exporter.assert_called_once_with(
            self.inst, {"q": "猫", "type": "FACT", "status": "active"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="memory-i1-20261105-120000.json"',
        )
        body = json.loads(response.body)
        self.assertEqual(body["data"]["items"][0]["id"], 1)
        self.assertEqual(body["data"]["count"], 1)

    def test_audit_route_attaches_forgetting_read_only(self):
        audit = {
            "total": 2,
            "counts": {"duplicates": 1, "privacy": 0, "conflicts": 0},
            "duplicates": [{"id": 1}],
            "privacy": [],
            "conflicts": [],
            "instance_id": "i1",
        }
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with mock.patch.object(api.memory_audit, "collect", return_value=dict(audit)):
                with mock.patch.object(
                    api.memory,
                    "call_forgetting",
                    return_value={"items": [{"memory_id": 3, "risk": 0.8}]},
                ) as forgetting:
                    result = api.memory_audit_get("i1", include_forgetting=True)
            forgetting.assert_called_once_with(self.inst)
        data = result["data"]
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["counts"], audit["counts"])
        self.assertEqual(data["duplicates"], audit["duplicates"])
        self.assertEqual(data["privacy"], [])
        self.assertEqual(data["conflicts"], [])
        self.assertEqual(data["forgetting"], [{"memory_id": 3, "risk": 0.8}])
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with mock.patch.object(api.memory_audit, "collect", return_value=dict(audit)):
                with mock.patch.object(
                    api.memory,
                    "call_forgetting",
                    side_effect=memory.MemoryError("未找到该路由", 502),
                ):
                    result = api.memory_audit_get("i1", include_forgetting=True)
        self.assertEqual(result["data"]["total"], 2)
        self.assertNotIn("forgetting", result["data"])
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with mock.patch.object(api.memory_audit, "collect", return_value=dict(audit)):
                with mock.patch.object(api.memory, "call_forgetting") as forgetting:
                    result = api.memory_audit_get("i1")
        forgetting.assert_not_called()
        self.assertNotIn("forgetting", result["data"])


class RecallRouteTests(unittest.TestCase):
    def _run(self, payload, call):
        with mock.patch.object(api, "_memory_instance", return_value={"id": "m1"}), \
                mock.patch.object(api.memory, "call_recall", call):
            return api.memory_recall("m1", payload)

    def test_recall_forwards_identity_and_infers_group_scene(self):
        calls = []

        def fake_call(inst, body):
            calls.append(body)
            return {"results": []}

        result = self._run({
            "query": "周末骑车",
            "k": 5,
            "session_id": "大肥鱼:GroupMessage:20001",
            "person_identity": "aiocqhttp:10003",
        }, fake_call)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls[0]["person_identity"], "aiocqhttp:10003")
        self.assertIs(calls[0]["is_private"], False)

    def test_recall_infers_private_scene_and_keeps_explicit_scene(self):
        calls = []

        def fake_call(inst, body):
            calls.append(body)
            return {"results": []}

        self._run({
            "query": "群聊里聊的电脑",
            "session_id": "大肥鱼:FriendMessage:10003",
        }, fake_call)
        self.assertIs(calls[0]["is_private"], True)
        self._run({
            "query": "指定场景",
            "session_id": "大肥鱼:GroupMessage:20001",
            "is_private": True,
        }, fake_call)
        self.assertIs(calls[1]["is_private"], True)

    def test_recall_omits_scene_without_session(self):
        calls = []

        def fake_call(inst, body):
            calls.append(body)
            return {"results": []}

        self._run({"query": "无会话"}, fake_call)
        self.assertNotIn("is_private", calls[0])
        self.assertNotIn("person_identity", calls[0])


if __name__ == "__main__":
    unittest.main()
