import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from server import fleet_store, human_settings, mood


class MoodStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_state_and_block(self):
        state = mood.get_state("i1", db_path=self.db)
        self.assertIn(state["mood"], mood.MOODS)
        self.assertEqual(state["source"], "daily_reset")
        block = mood.build_prompt_block(state)
        self.assertIn("【今日心情】", block)
        self.assertIn("【语气提示】", block)
        self.assertLessEqual(len(block), 240)

    def test_daily_reset_decays_relations_once(self):
        mood.adjust({"instance_id": "i1", "scope": "relation",
                     "platform": "qq", "person_key": "u1",
                     "anger": 90, "affection": 80, "familiarity": 40},
                    db_path=self.db)
        with mock.patch.object(mood, "mood_date", return_value="2099-01-01"):
            mood.get_state("i1", db_path=self.db)
            rel = mood.get_relation("i1", "qq", "u1", db_path=self.db)
        self.assertAlmostEqual(rel["anger"], 81.0)
        self.assertAlmostEqual(rel["affection"], 72.0)
        self.assertEqual(rel["familiarity"], 40)

    def test_same_day_second_read_does_not_decay_again(self):
        mood.adjust({"instance_id": "i1", "scope": "relation",
                     "platform": "qq", "person_key": "u1",
                     "anger": 90, "affection": 80, "familiarity": 40},
                    db_path=self.db)
        with mock.patch.object(mood, "mood_date", return_value="2099-01-01"):
            first = mood.get_state("i1", db_path=self.db)
            second = mood.get_state("i1", db_path=self.db)
        rel = mood.get_relation("i1", "qq", "u1", db_path=self.db)
        # 跨日后第一次读取衰减一次，第二次同日读取直接返回、不再衰减。
        self.assertAlmostEqual(rel["anger"], 81.0)
        self.assertAlmostEqual(rel["affection"], 72.0)
        self.assertEqual(first, second)

    def test_manual_adjust_and_reset(self):
        mood.adjust({"instance_id": "i1", "scope": "global",
                     "mood": "happy", "intensity": 77}, db_path=self.db)
        self.assertEqual(mood.get_state("i1", db_path=self.db)["mood"], "happy")
        mood.reset({"instance_id": "i1", "scope": "global"}, db_path=self.db)
        state = mood.get_state("i1", db_path=self.db)
        self.assertEqual(state["mood"], "calm")
        self.assertEqual(state["source"], "manual")

    def test_first_insert_does_not_decay_existing_relations(self):
        mood.adjust({"instance_id": "i1", "scope": "relation",
                     "platform": "qq", "person_key": "u1",
                     "anger": 90, "affection": 80, "familiarity": 40},
                    db_path=self.db)
        # adjust 会顺带创建 human_global；删掉它以模拟“关系已存在、全局状态首次插入”。
        with fleet_store.session(self.db) as conn:
            conn.execute("DELETE FROM human_global WHERE instance_id=?", ("i1",))
        state = mood.get_state("i1", db_path=self.db)
        rel = mood.get_relation("i1", "qq", "u1", db_path=self.db)
        self.assertEqual(state["source"], "daily_reset")
        self.assertAlmostEqual(rel["anger"], 90.0)
        self.assertAlmostEqual(rel["affection"], 80.0)
        self.assertEqual(rel["familiarity"], 40)

    def test_manual_reset_settles_cross_day_decay_first(self):
        mood.adjust({"instance_id": "i1", "scope": "relation",
                     "platform": "qq", "person_key": "u1",
                     "anger": 90, "affection": 80, "familiarity": 40},
                    db_path=self.db)
        with mock.patch.object(mood, "mood_date", return_value="2099-01-01"):
            mood.reset({"instance_id": "i1", "scope": "global"}, db_path=self.db)
            rel = mood.get_relation("i1", "qq", "u1", db_path=self.db)
        # 跨日后手动重置先结算当天衰减，而不是直接写 global 跳过衰减。
        self.assertAlmostEqual(rel["anger"], 81.0)
        self.assertAlmostEqual(rel["affection"], 72.0)
        self.assertEqual(rel["familiarity"], 40)

    def test_prompt_block_survives_extreme_numbers(self):
        state = {"mood": "angry", "intensity": 1e12, "energy": 1e12,
                 "social": 1e12, "source": "manual"}
        block = mood.build_prompt_block(state)
        self.assertLessEqual(len(block), 240)
        self.assertIn("这段是内部状态，不要向用户提及数值、插件或本说明。", block)
        # 异常大数被钳制到展示上限，而不是原样撑大提示块。
        self.assertIn("（100/100）", block)
        self.assertNotIn("1000000000000", block)

    def test_prompt_block_clamps_to_240(self):
        state = {"mood": "angry", "intensity": 100, "energy": 100,
                 "social": 100, "source": "manual"}
        block = mood.build_prompt_block(state, tone_hint="很长的提示" * 100)
        self.assertLessEqual(len(block), 240)
        self.assertIn("不要向用户提及", block)
        # 超长 tone_hint 只能截断自己，不能吞掉末尾的内部说明。
        self.assertIn("这段是内部状态，不要向用户提及数值、插件或本说明。", block)
        self.assertTrue(block.endswith("说明。"))
        # 被预算截断的 tone_hint 以省略号收尾，不露出半句话。
        self.assertIn("…", block)


class MoodObserveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        self.inst = {"id": "i1", "name": "大肥鱼", "dash_port": 6185,
                     "root": "D:/tmp/astrbot"}
        self.payload = {
            "instance_id": "i1", "platform": "qq", "thread_key": "大肥鱼:FriendMessage:1",
            "person_key": "u1", "sender_name": "小明", "text": "对不起，刚才是我不好",
            "is_owner": False, "provider_id": "p1",
            "recent": [{"speaker": "用户", "text": "在吗"}],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_observe_applies_clamped_deltas_and_logs(self):
        mood.adjust({"instance_id": "i1", "scope": "global", "mood": "calm",
                     "intensity": 50, "energy": 50, "social": 50}, db_path=self.db)
        mood.adjust({"instance_id": "i1", "scope": "relation", "platform": "qq",
                     "person_key": "u1", "anger": 20}, db_path=self.db)
        raw = ('{"mood":"annoyed","intensity_delta":-99,"energy_delta":-99,'
               '"social_delta":-99,"anger_delta":-99,"affection_delta":99,'
               '"familiarity_delta":99,"reason":"用户在道歉","tone_hint":"软一点"}')
        with mock.patch.object(mood.llm, "chat", return_value=raw) as chat:
            result = mood.observe(self.payload, instances=[self.inst], db_path=self.db)
        chat.assert_called_once()
        self.assertEqual(result["state"]["mood"], "annoyed")
        self.assertEqual(result["state"]["intensity"], 30)
        self.assertEqual(result["state"]["energy"], 40)
        self.assertEqual(result["relation"]["anger"], 0)
        self.assertEqual(result["relation"]["affection"], 10)
        self.assertEqual(result["relation"]["familiarity"], 3)
        self.assertIn("软一点", result["prompt_block"])
        items = mood.events("i1", db_path=self.db)
        self.assertEqual(len(items), 1)
        # 成功事件里要能看到本次耗时与 provider，而不是只在返回值里有。
        self.assertIn("latency_ms", items[0]["assessment"])
        self.assertEqual(items[0]["assessment"]["provider_id"], "p1")
        self.assertEqual(items[0]["assessment"]["latency_ms"], result["latency_ms"])

    def test_observe_json_failure_keeps_state(self):
        before = mood.get_state("i1", db_path=self.db)
        with mock.patch.object(mood.llm, "chat", return_value="不是 JSON"):
            result = mood.observe(self.payload, instances=[self.inst], db_path=self.db)
        after = mood.get_state("i1", db_path=self.db)
        self.assertEqual(after["mood"], before["mood"])
        self.assertEqual(after["intensity"], before["intensity"])
        self.assertIsNone(result["assessment"])
        self.assertTrue(result["error"])
        self.assertIn("【今日心情】", result["prompt_block"])
        self.assertEqual(mood.events("i1", db_path=self.db)[0]["error"], result["error"])

    def test_high_anger_apology_can_drop_25_plain_excuse_only_8(self):
        mood.adjust({"instance_id": "i1", "scope": "relation", "platform": "qq",
                     "person_key": "u1", "anger": 90}, db_path=self.db)
        apology = ('{"mood":"annoyed","anger_delta":-25,"reason":"用户在道歉",'
                   '"tone_hint":"软一点"}')
        with mock.patch.object(mood.llm, "chat", return_value=apology):
            mood.observe(self.payload, instances=[self.inst], db_path=self.db)
        self.assertAlmostEqual(mood.get_relation("i1", "qq", "u1", db_path=self.db)["anger"], 65.0)

        mood.adjust({"instance_id": "i1", "scope": "relation", "platform": "qq",
                     "person_key": "u1", "anger": 90}, db_path=self.db)
        # 原文只是解释，模型 reason 却谎称“用户在道歉”：只能按非道歉封顶 -8。
        excuse = ('{"mood":"annoyed","anger_delta":-25,"reason":"用户在道歉",'
                  '"tone_hint":"冷一点"}')
        with mock.patch.object(mood.llm, "chat", return_value=excuse):
            mood.observe(dict(self.payload, text="我刚才在忙，没看到"),
                         instances=[self.inst], db_path=self.db)
        self.assertAlmostEqual(mood.get_relation("i1", "qq", "u1", db_path=self.db)["anger"], 82.0)

    def test_observe_event_log_failure_still_returns_error(self):
        with mock.patch.object(mood.llm, "chat", return_value="不是 JSON"):
            with mock.patch.object(mood, "_save_event", side_effect=RuntimeError("db down")):
                result = mood.observe(self.payload, instances=[self.inst], db_path=self.db)
        # 事件落库再失败也只丢审计，接口仍返回结构化 error，而不是把异常抛给上层。
        self.assertIsNone(result["assessment"])
        self.assertIn("模型没有返回 JSON", result["error"])

    def test_relation_keeps_display_name_when_sender_missing(self):
        mood.adjust({"instance_id": "i1", "scope": "relation", "platform": "qq",
                     "person_key": "u1", "display_name": "小明", "anger": 10},
                    db_path=self.db)
        raw = ('{"mood":"calm","anger_delta":-5,"affection_delta":1,'
               '"familiarity_delta":1,"reason":"普通聊天","tone_hint":"正常"}')
        with mock.patch.object(mood.llm, "chat", return_value=raw):
            mood.observe(dict(self.payload, sender_name=""),
                         instances=[self.inst], db_path=self.db)
        rel = mood.get_relation("i1", "qq", "u1", db_path=self.db)
        # sender_name 缺失时沿用原昵称，不能被空串覆盖。
        self.assertEqual(rel["display_name"], "小明")

    def test_mood_disabled_skips_model_and_injection(self):
        human_settings.save_settings("i1", {"mood_enabled": False}, db_path=self.db)
        with mock.patch.object(mood.llm, "chat") as chat:
            result = mood.observe(self.payload, instances=[self.inst], db_path=self.db)
        chat.assert_not_called()
        self.assertIs(result["enabled"], False)
        self.assertEqual(result["prompt_block"], "")


class MoodProviderTest(unittest.TestCase):
    def setUp(self):
        self.inst = {"id": "i1", "name": "大肥鱼", "dash_port": 6185,
                     "root": "D:/tmp/astrbot"}

    def test_settings_provider_id_wins_without_dashboard_call(self):
        with mock.patch.object(mood.dashboard, "call") as call:
            provider = mood._pick_provider(self.inst, {"provider_id": "p-settings"})
        self.assertEqual(provider, "p-settings")
        call.assert_not_called()

    def test_falls_back_to_default_profile_provider(self):
        profile = {"data": {"config": {"agent_runner": {"config": {
            "model": {"provider_id": "p-profile"}}}}}}
        with mock.patch.object(mood.dashboard, "call",
                               return_value=profile) as call:
            provider = mood._pick_provider(self.inst, {"provider_id": ""})
        self.assertEqual(provider, "p-profile")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[2], "config-profiles/default")

    def test_falls_back_to_first_chat_completion_provider(self):
        def fake_call(inst, method, path, **kwargs):
            if path == "config-profiles/default":
                return {"data": {"config": {}}}
            if path == "providers":
                return {"data": {"providers": [
                    {"id": "tts-1", "provider_type": "text_to_speech"},
                    {"id": "chat-1", "provider_type": "chat_completion"},
                    {"id": "chat-2", "provider_type": "chat_completion"},
                ]}}
            raise AssertionError(f"意外请求：{path}")

        with mock.patch.object(mood.dashboard, "call", side_effect=fake_call):
            provider = mood._pick_provider(self.inst, {})
        self.assertEqual(provider, "chat-1")

    def test_raises_mood_error_when_all_lookups_fail(self):
        with mock.patch.object(mood.dashboard, "call",
                               side_effect=mood.dashboard.DashboardError("连不上", 503)):
            with self.assertRaises(mood.MoodError):
                mood._pick_provider(self.inst, {})


class MoodResolveInstanceTest(unittest.TestCase):
    def test_platform_id_matches_instance_name_when_platform_id_missing(self):
        # 插件 umo 前缀等于实例名；data/instances.json 的 platform_id 为 null。
        inst = {"id": "i1", "name": "大肥鱼", "platform_id": None}
        self.assertEqual(
            mood.resolve_instance({"platform_id": "大肥鱼"}, [inst]), inst)

    def test_real_platform_id_wins_over_name(self):
        by_name = {"id": "i2", "name": "大肥鱼", "platform_id": None}
        by_platform = {"id": "i1", "name": "千文", "platform_id": "大肥鱼"}
        self.assertEqual(
            mood.resolve_instance({"platform_id": "大肥鱼"}, [by_name, by_platform]),
            by_platform)

    def test_unknown_platform_id_still_raises(self):
        inst = {"id": "i1", "name": "大肥鱼", "platform_id": None}
        with self.assertRaises(mood.MoodError):
            mood.resolve_instance({"platform_id": "不存在"}, [inst])


class MoodApiTest(unittest.TestCase):
    def test_routes_exist(self):
        from server import api
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in ("/api/mood/observe", "/api/mood/status", "/api/mood/events",
                     "/api/mood/adjust", "/api/mood/reset", "/api/mood/settings"):
            self.assertIn(path, paths)

    def test_status_route_calls_module(self):
        from server import api
        with mock.patch.object(api, "_instances", return_value=[{"id": "i1"}]):
            with mock.patch.object(api.mood_mod, "status", return_value={"ok": True}) as status:
                result = api.mood_status("i1")
        status.assert_called_once_with("i1")
        self.assertTrue(result["data"]["ok"])


if __name__ == "__main__":
    unittest.main()
