import datetime as dt
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from server import api, fleet_store, mood, presence


def _local_ts(hour, minute=0, day=None):
    today = day or dt.date.today()
    return dt.datetime.combine(today, dt.time(hour, minute)).timestamp()


class _DbCase(unittest.TestCase):
    """临时库基类：直接调用 presence 函数时统一传 db_path。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        # 固定本地白天，避免夜间跑测试时命中回访安静时段（23:00-08:00）。
        self.now = _local_ts(14, 0)
        self.inst = {"id": "i1", "name": "大肥鱼"}

    def tearDown(self):
        self.tmp.cleanup()

    def relation(self, platform="qq", person="u1", familiarity=50.0,
                 followup_enabled=1, last_seen=None, display_name="小明"):
        if last_seen is None:
            last_seen = self.now - 7 * 3600
        presence.upsert_relation(
            "i1", platform, person, display_name=display_name,
            stage="familiar", followup_enabled=followup_enabled,
            first_seen=self.now - 40 * 86400, last_seen=last_seen,
            message_count=5, db_path=self.db)
        with fleet_store.session(self.db) as conn:
            conn.execute(
                "INSERT INTO human_relations(id, instance_id, platform, person_key, "
                "display_name, familiarity, last_seen, updated) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(instance_id, platform, person_key) DO UPDATE SET "
                "familiarity=excluded.familiarity, last_seen=excluded.last_seen",
                ("hr_" + person, "i1", platform, person, display_name, familiarity,
                 last_seen, self.now))

    def loop(self, person="u1", topic="周末去骑车", thread_key="t1",
             hours=0, text="上次说周末去骑车，去了吗？"):
        item = presence.add_loop("i1", "qq", person, topic, thread_key=thread_key,
                                 confidence=0.8, follow_up_after_hours=hours,
                                 db_path=self.db)
        # add_loop 用真实时钟算到期；测试统一按固定基准时间，避免早晚跑结果不同。
        patch = {"follow_up_after": self.now + hours * 3600}
        if text:
            patch.update({"follow_up_text": text,
                          "follow_up_generated_at": self.now - 60})
        item = presence.update_loop(item["id"], patch, db_path=self.db)
        return item

    def takeover(self, thread_key="t1", kind="private", active=1):
        with fleet_store.session(self.db) as conn:
            conn.execute(
                "INSERT INTO inbox_threads(id, platform, account_id, thread_key, kind, "
                "takeover, created, updated) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(platform, account_id, thread_key) DO UPDATE SET "
                "takeover=excluded.takeover, kind=excluded.kind",
                ("th_" + thread_key, "qq", "i1", thread_key, kind, active,
                 self.now, self.now))

    def sent_event(self, person="u1", created=None):
        event_id = presence.add_event(
            "i1", "followup_sent", person_key=person,
            payload={"loop_id": "lp_old"}, db_path=self.db)
        if created is not None:
            with fleet_store.session(self.db) as conn:
                conn.execute("UPDATE presence_events SET created=? WHERE id=?",
                             (created, event_id))
        return event_id


class PresenceRoutesTest(unittest.TestCase):
    def test_design_routes_registered(self):
        routes = {}
        for route in api.app.routes:
            path = getattr(route, "path", "")
            routes.setdefault(path, set()).update(getattr(route, "methods", set()))
        expected = {
            "/api/presence/activity": {"POST"},
            "/api/presence/scan": {"POST"},
            "/api/presence/context": {"GET"},
            "/api/presence/followups/due": {"GET"},
            "/api/presence/followups/{loop_id}/sent": {"POST"},
            "/api/presence/radar": {"GET", "POST"},
            "/api/presence/loops": {"GET", "POST"},
            "/api/presence/loops/{loop_id}": {"PATCH"},
            "/api/presence/loops/{loop_id}/preview": {"POST"},
            "/api/presence/loops/{loop_id}/send": {"POST"},
            "/api/presence/relations": {"GET"},
            "/api/presence/relations/{relation_id}": {"PATCH"},
            "/api/presence/milestones": {"GET", "POST", "DELETE"},
            "/api/presence/rhythm": {"GET", "PUT"},
            "/api/presence/group-config": {"GET", "PUT"},
            "/api/presence/diaries": {"GET"},
            "/api/presence/diaries/generate": {"POST"},
            "/api/presence/diaries/{diary_id}": {"PATCH", "DELETE"},
            "/api/presence/settings": {"GET", "PUT"},
        }
        for path, methods in expected.items():
            self.assertIn(path, routes, path)
            self.assertTrue(methods <= routes[path], f"{path} 缺少方法 {methods - routes[path]}")

    def test_activity_and_context_wrap_errors(self):
        inst = {"id": "i1", "name": "大肥鱼", "platform_id": "aiocqhttp"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
                mock.patch.object(api.presence_mod, "record_activity",
                                  return_value={"relation": {"id": "r1"}}) as record:
            result = api.presence_activity({"instance_id": "i1", "person_key": "u1"})
        record.assert_called_once_with({"instance_id": "i1", "person_key": "u1"},
                                       instances=[inst])
        self.assertEqual(result["status"], "ok")
        with mock.patch.object(api, "_instances", return_value=[inst]), \
                mock.patch.object(api.presence_mod, "record_activity",
                                  side_effect=presence.PresenceError("缺字段")):
            failed = api.presence_activity({"instance_id": "i1"})
        self.assertEqual(failed.status_code, 400)
        with mock.patch.object(api, "_instances", return_value=[inst]), \
                mock.patch.object(api.presence_mod, "record_activity",
                                  side_effect=mood.MoodError("未知实例")):
            failed = api.presence_activity({"instance_id": "nope"})
        self.assertEqual(failed.status_code, 400)

    def test_context_resolves_platform_and_returns_400(self):
        inst = {"id": "i1", "name": "大肥鱼", "platform_id": "aiocqhttp"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
                mock.patch.object(api.presence_mod, "context",
                                  return_value={"nickname": "小明"}) as ctx:
            result = api.presence_context(instance_id="", platform="qq",
                                          person_key="u1", platform_id="aiocqhttp")
        ctx.assert_called_once_with("i1", "qq", "u1", "")
        self.assertEqual(result["data"], {"nickname": "小明"})
        with mock.patch.object(api, "_instances", return_value=[inst]):
            failed = api.presence_context(instance_id="", platform="qq",
                                          person_key="u1", platform_id="missing")
        self.assertEqual(failed.status_code, 400)

    def test_send_delete_and_group_config_need_confirm(self):
        with mock.patch.object(api, "_instances", return_value=[{"id": "i1"}]), \
                mock.patch.object(api.presence_mod, "send_now") as send:
            failed = api.presence_loop_send("lp1", {"confirm": False})
        self.assertEqual(failed.status_code, 400)
        send.assert_not_called()
        with mock.patch.object(api, "_instances", return_value=[{"id": "i1"}]):
            failed = api.presence_diaries_delete("dy1", "i1", False)
        self.assertEqual(failed.status_code, 400)
        with mock.patch.object(api, "_instances", return_value=[{"id": "i1"}]):
            failed = api.presence_group_config_update(
                {"instance_id": "i1", "config": {"enabled_groups": []}})
        self.assertEqual(failed.status_code, 400)

    def test_due_and_settings_wrap_presence_errors(self):
        inst = {"id": "i1", "name": "大肥鱼"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
                mock.patch.object(api.presence_mod, "due_followups",
                                  return_value={"loops": [], "shadow": True,
                                                "blocked_reason": ""}) as due:
            result = api.presence_followups_due(instance_id="i1", platform_id="")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(due.call_args.kwargs["inst"] is inst)
        with mock.patch.object(api, "_instances", return_value=[inst]), \
                mock.patch.object(api.presence_mod, "save_settings",
                                  side_effect=presence.PresenceError("未知设置项")):
            failed = api.presence_settings_update({"instance_id": "i1", "bad": 1})
        self.assertEqual(failed.status_code, 400)


class PresenceActivityTest(_DbCase):
    def test_first_contact_private_and_no_duplicate(self):
        first = presence.record_activity({
            "instance_id": "i1", "platform": "qq", "person_key": "u1",
            "display_name": "小明", "message_count": 1, "is_private": True,
            "occurred_at": self.now,
        }, instances=[self.inst], db_path=self.db)
        self.assertEqual(first["relation"]["display_name"], "小明")
        self.assertEqual(first["relation"]["message_count"], 1)
        kinds = {item["kind"] for item in first["milestones"]}
        self.assertEqual(kinds, {"first_contact", "first_private"})
        second = presence.record_activity({
            "instance_id": "i1", "person_key": "u1", "message_count": 9,
            "is_private": True, "occurred_at": self.now + 10,
        }, instances=[self.inst], db_path=self.db)
        self.assertEqual(second["relation"]["message_count"], 10)
        self.assertEqual({item["kind"] for item in second["milestones"]},
                         {"message_10"})
        third = presence.record_activity({
            "instance_id": "i1", "person_key": "u1", "message_count": 0,
            "is_private": True, "occurred_at": self.now + 20,
        }, instances=[self.inst], db_path=self.db)
        self.assertEqual(third["milestones"], [])
        all_kinds = [item["kind"] for item in presence.list_milestones(
            "i1", db_path=self.db)]
        self.assertEqual(all_kinds.count("first_contact"), 1)
        self.assertEqual(all_kinds.count("first_private"), 1)

    def test_group_activity_no_private_milestone_and_30_days(self):
        presence.record_activity({
            "instance_id": "i1", "person_key": "u2", "message_count": 1,
            "is_private": False, "occurred_at": self.now - 31 * 86400,
        }, instances=[self.inst], db_path=self.db)
        result = presence.record_activity({
            "instance_id": "i1", "person_key": "u2", "message_count": 99,
            "is_private": False, "occurred_at": self.now,
        }, instances=[self.inst], db_path=self.db)
        kinds = {item["kind"] for item in result["milestones"]}
        self.assertNotIn("first_private", kinds)
        self.assertIn("message_100", kinds)
        self.assertIn("days_30", kinds)
        again = presence.record_activity({
            "instance_id": "i1", "person_key": "u2", "message_count": 0,
            "occurred_at": self.now + 5,
        }, instances=[self.inst], db_path=self.db)
        self.assertEqual(again["milestones"], [])

    def test_unknown_instance_rejected(self):
        with self.assertRaises(mood.MoodError):
            presence.record_activity({"instance_id": "nope", "person_key": "u1"},
                                     instances=[self.inst], db_path=self.db)


class PresenceContextTest(_DbCase):
    def test_empty_without_relation(self):
        ctx = presence.context("i1", "qq", "missing", db_path=self.db)
        self.assertIsNone(ctx["relation"])
        self.assertEqual(ctx["nickname"], "")
        self.assertEqual(ctx["milestones"], [])
        self.assertFalse(ctx["allow_memory"])

    def test_nickname_stage_milestones_and_diary_summary(self):
        presence.upsert_relation("i1", "qq", "u1", display_name="小明",
                                 nickname="明明", stage="close",
                                 allow_memory=False, db_path=self.db)
        for index, title in enumerate(("第一次私聊", "一起听歌", "认识 30 天")):
            presence.add_milestone("i1", "qq", "u1", "custom", title,
                                   occurred_at=self.now - index * 100,
                                   db_path=self.db)
        presence.upsert_diary("i1", "2026-11-05", "正文",
                              mood={"summary": "昨天很开心"}, db_path=self.db)
        ctx = presence.context("i1", "qq", "u1", db_path=self.db)
        self.assertEqual(ctx["nickname"], "明明")
        self.assertEqual(ctx["stage"], "close")
        self.assertFalse(ctx["allow_memory"])
        self.assertEqual([item["title"] for item in ctx["milestones"]],
                         ["第一次私聊", "一起听歌"])
        self.assertEqual(ctx["diary_summary"], "昨天很开心")

    def test_takeover_thread_has_no_injection(self):
        presence.upsert_relation("i1", "qq", "u1", display_name="小明",
                                 nickname="明明", stage="close",
                                 db_path=self.db)
        presence.upsert_diary("i1", "2026-11-05", "正文",
                              mood={"summary": "昨天很开心"}, db_path=self.db)
        self.takeover("t1", active=1)
        ctx = presence.context("i1", "qq", "u1", thread_key="t1",
                               db_path=self.db)
        self.assertTrue(ctx["takeover"])
        self.assertIsNone(ctx["relation"])
        self.assertEqual(ctx["nickname"], "")
        self.assertEqual(ctx["stage"], "")
        self.assertEqual(ctx["milestones"], [])
        self.assertEqual(ctx["diary_summary"], "")
        self.assertFalse(ctx["allow_memory"])
        # 接管解除后同一关系立即恢复注入。
        self.takeover("t1", active=0)
        normal = presence.context("i1", "qq", "u1", thread_key="t1",
                                  db_path=self.db)
        self.assertFalse(normal["takeover"])
        self.assertEqual(normal["nickname"], "明明")


class PresenceScanTest(_DbCase):
    def _scan(self, content, payload=None):
        payload = payload or {
            "platform": "qq", "person_key": "u1", "thread_key": "t1",
            "is_private": True,
            "messages": [{"speaker": "小明", "text": "周末去骑车吧"},
                         {"speaker": "bot", "text": "好啊，周六？"}],
        }
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat", return_value=content):
            return presence.scan_loops(self.inst, payload, db_path=self.db)

    def test_scan_filters_dedupes_and_caps(self):
        presence.add_loop("i1", "qq", "u1", "周末去骑车", db_path=self.db)
        content = json.dumps({"loops": [
            {"topic": "周末去骑车", "detail": "重复", "confidence": 0.9,
             "follow_up_after_hours": 24},
            {"topic": "生日礼物", "detail": "她说想要书", "confidence": 0.8,
             "follow_up_after_hours": 1000},
            {"topic": "考试", "detail": "下月考试", "confidence": 0.6,
             "follow_up_after_hours": 0},
            {"topic": "低置信", "detail": "x", "confidence": 0.3,
             "follow_up_after_hours": 24},
            {"topic": "生日礼物", "detail": "批次内重复", "confidence": 0.9,
             "follow_up_after_hours": 24},
        ]}, ensure_ascii=False)
        result = self._scan(content)
        self.assertEqual(result["error"], "")
        topics = [item["topic"] for item in result["loops"]]
        self.assertEqual(topics, ["生日礼物", "考试"])
        self.assertAlmostEqual(result["loops"][0]["follow_up_after"],
                               time.time() + 720 * 3600, delta=5)
        self.assertAlmostEqual(result["loops"][1]["follow_up_after"],
                               time.time() + 3600, delta=5)
        self.assertGreaterEqual(result["skipped"], 2)

    def test_scan_model_failure_returns_error(self):
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat",
                                  side_effect=RuntimeError("模型超时")):
            result = presence.scan_loops(self.inst, {
                "person_key": "u1", "messages": [{"text": "在吗"}]},
                db_path=self.db)
        self.assertEqual(result["loops"], [])
        self.assertIn("模型超时", result["error"])
        self.assertEqual(presence.list_loops("i1", db_path=self.db), [])

    def test_scan_malformed_json_and_group_rejected(self):
        result = self._scan("不是 JSON")
        self.assertEqual(result["loops"], [])
        self.assertTrue(result["error"])
        with self.assertRaises(presence.PresenceError):
            presence.scan_loops(self.inst, {
                "person_key": "u1", "is_private": False,
                "messages": [{"text": "群消息"}]}, db_path=self.db)

    def test_takeover_thread_is_not_scanned(self):
        self.takeover("t1", active=1)
        with mock.patch.object(presence.llm, "chat") as chat:
            result = self._scan(json.dumps({"loops": []}, ensure_ascii=False))
        chat.assert_not_called()
        self.assertEqual(result["loops"], [])
        self.assertIn("接管", result["error"])
        self.assertEqual(presence.list_loops("i1", db_path=self.db), [])

    def test_scan_uses_read_only_memory_summary(self):
        captured = {}

        def chat(inst, provider, messages, **kwargs):
            captured["user"] = messages[-1]["content"]
            return json.dumps({"loops": []}, ensure_ascii=False)

        with mock.patch.object(presence, "_memory_context",
                               return_value=(["聊了骑车", "晚安"], ["m1"], [])), \
                mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat", side_effect=chat):
            result = presence.scan_loops(self.inst, {
                "platform": "qq", "person_key": "u1", "thread_key": "t1",
                "is_private": True,
                "messages": [{"speaker": "小明", "text": "周末去骑车吧"}]},
                db_path=self.db)
        self.assertEqual(result["error"], "")
        self.assertIn("记忆摘要", captured["user"])
        self.assertIn("聊了骑车", captured["user"])


class PresenceFollowupTest(_DbCase):
    def _due(self, now=None, inst=None, call=None):
        return presence.due_followups("i1", now=now or self.now,
                                       inst=inst, db_path=self.db, call=call)

    def test_shadow_returns_empty(self):
        self.relation()
        self.loop()
        result = self._due()
        self.assertEqual(result["loops"], [])
        self.assertTrue(result["shadow"])
        self.assertEqual(result["blocked_reason"], "")

    def test_real_mode_conditions(self):
        presence.save_settings("i1", {"followup_shadow": False}, db_path=self.db)
        self.relation()
        item = self.loop()
        result = self._due()
        self.assertEqual([loop["id"] for loop in result["loops"]], [item["id"]])
        self.assertFalse(result["shadow"])

        # 熟悉度不足
        with fleet_store.session(self.db) as conn:
            conn.execute("UPDATE human_relations SET familiarity=10 WHERE person_key='u1'")
        self.assertEqual(self._due()["loops"], [])

    def test_relation_switch_takeover_quiet_and_recent_interaction(self):
        presence.save_settings("i1", {"followup_shadow": False}, db_path=self.db)
        self.relation(followup_enabled=0)
        item = self.loop()
        self.assertEqual(self._due()["loops"], [])

        self.relation(followup_enabled=1)
        with fleet_store.session(self.db) as conn:
            conn.execute(
                "INSERT INTO inbox_threads(id, platform, account_id, thread_key, kind, "
                "takeover, created, updated) VALUES(?,?,?,?,?,?,?,?)",
                ("th1", "qq", "i1", "t1", "private", 1, self.now, self.now))
        self.assertEqual(self._due()["loops"], [])
        with fleet_store.session(self.db) as conn:
            conn.execute("UPDATE inbox_threads SET takeover=0 WHERE id='th1'")
        self.assertEqual(len(self._due()["loops"]), 1)

        quiet_now = _local_ts(23, 30)
        presence.update_loop(item["id"],
                             {"follow_up_after": quiet_now - 3600}, db_path=self.db)
        self.assertEqual(self._due(now=quiet_now)["loops"], [])

        recent = self.now - 3600
        self.relation(last_seen=recent)
        self.assertEqual(self._due()["loops"], [])
        self.assertEqual(presence.list_loops("i1", status="open",
                                             db_path=self.db).__len__(), 1)

    def test_daily_and_weekly_limits(self):
        presence.save_settings("i1", {"followup_shadow": False}, db_path=self.db)
        self.relation()
        self.loop()
        self.sent_event(created=self.now - 60)
        self.assertEqual(self._due()["loops"], [])

        with fleet_store.session(self.db) as conn:
            conn.execute("DELETE FROM presence_events")
        presence.save_settings("i1", {"followup_shadow": False, "daily_limit": 5,
                                      "weekly_limit": 3}, db_path=self.db)
        for days in (2, 3, 4):
            self.sent_event(created=self.now - days * 86400)
        self.assertEqual(self._due()["loops"], [])

    def test_one_loop_per_person_per_call(self):
        presence.save_settings("i1", {"followup_shadow": False}, db_path=self.db)
        self.relation()
        self.loop(topic="话题一")
        self.loop(topic="话题二")
        self.assertEqual(len(self._due()["loops"]), 1)

    def test_due_generates_at_most_one_text_per_call(self):
        presence.save_settings("i1", {"followup_shadow": False}, db_path=self.db)
        self.relation()
        self.relation(person="u2", display_name="小红")
        self.loop(person="u1", topic="话题一", thread_key="t1", text="")
        self.loop(person="u2", topic="话题二", thread_key="t2", text="")
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat",
                                  return_value="上次说的事怎么样了？") as chat:
            first = self._due(inst=self.inst)
            self.assertEqual(len(first["loops"]), 1)
            self.assertEqual(chat.call_count, 1)
            second = self._due(inst=self.inst)
            self.assertEqual(len(second["loops"]), 2)
            self.assertEqual(chat.call_count, 2)

    def test_proactive_chat_conflict_and_dashboard_failure(self):
        presence.save_settings("i1", {"followup_shadow": False}, db_path=self.db)
        self.relation()
        self.loop()

        def call(inst, method, path, payload=None, query=None, timeout=60):
            if path == "plugins":
                return {"data": [{"id": "astrbot_plugin_proactive_chat",
                                  "activated": True}]}
            if path == "plugins/config":
                return {"data": {"config": {"friend_settings": {"enable": True}}}}
            return {}

        blocked = self._due(inst=self.inst, call=call)
        self.assertEqual(blocked["loops"], [])
        self.assertEqual(blocked["blocked_reason"], "proactive_chat_conflict")

        def broken(*args, **kwargs):
            raise RuntimeError("dashboard down")

        # 读配置失败按“不冲突”处理，仍返回到期回访。
        self.assertEqual(len(self._due(inst=self.inst, call=broken)["loops"]), 1)

    def test_send_now_blocks_takeover_thread(self):
        self.relation()
        item = self.loop()
        self.takeover("t1", active=1)
        with mock.patch.object(presence.dashboard, "call") as call:
            with self.assertRaises(presence.PresenceError) as caught:
                presence.send_now(self.inst, item["id"], db_path=self.db)
        call.assert_not_called()
        self.assertIn("接管", str(caught.exception))
        self.assertEqual(presence.get_loop(item["id"], db_path=self.db)["follow_up_count"], 0)
        with mock.patch.object(presence, "_pick_provider") as provider:
            with self.assertRaises(presence.PresenceError) as preview:
                presence.generate_follow_up(self.inst, item["id"], db_path=self.db)
        provider.assert_not_called()
        self.assertIn("接管", str(preview.exception))

    def test_generate_and_mark_sent(self):
        item = self.loop(text="")
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat",
                                  return_value="「上次说周末去骑车，去了吗？」"):
            generated = presence.generate_follow_up(self.inst, item["id"],
                                                    db_path=self.db)
        self.assertLessEqual(len(generated["follow_up_text"]), 40)
        self.assertTrue(generated["follow_up_text"])
        self.assertGreater(generated["follow_up_generated_at"], 0)
        marked = presence.mark_sent(item["id"], db_path=self.db)
        self.assertEqual(marked["follow_up_count"], 1)
        self.assertGreater(marked["last_follow_up_at"], 0)
        events = presence.list_events("i1", kind="followup_sent", db_path=self.db)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["person_key"], "u1")

        broken = self.loop(text="", topic="另一个话题")
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat",
                                  side_effect=RuntimeError("超时")):
            with self.assertRaises(presence.PresenceError):
                presence.generate_follow_up(self.inst, broken["id"], db_path=self.db)


class PresenceDiaryTest(_DbCase):
    def _events(self, count=2):
        for index in range(count):
            with fleet_store.session(self.db) as conn:
                conn.execute(
                    "INSERT INTO human_mood_events(instance_id, platform, person_key, "
                    "thread_key, created, assessment_json, before_json, after_json) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    ("i1", "qq", "u1", "t1", time.time() - index,
                     json.dumps({"mood": "happy", "reason": "聊天"},
                                ensure_ascii=False), "{}", "{}"))

    def test_skipped_without_events_and_force_generates(self):
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat") as chat:
            skipped = presence.generate_diary(self.inst, db_path=self.db)
        self.assertTrue(skipped["skipped"])
        chat.assert_not_called()
        self.assertIsNone(presence.get_diary(
            "i1", time.strftime("%Y-%m-%d"), db_path=self.db))

        payload = json.dumps({"text": "今天" + "很平静。" * 100,
                              "summary": "今天比较平静。"}, ensure_ascii=False)
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat", return_value=payload), \
                mock.patch.object(presence.memory, "call_working",
                                  return_value={}):
            forced = presence.generate_diary(self.inst, force=True, db_path=self.db)
        self.assertFalse(forced["skipped"])
        self.assertLessEqual(len(forced["diary"]["text"]), 500)
        self.assertEqual(forced["diary"]["summary"], "今天比较平静。")

    def test_upsert_by_instance_and_date_and_memory_failure_skipped(self):
        self._events(2)
        first = json.dumps({"text": "第一版日记。" * 40, "summary": "第一版"},
                           ensure_ascii=False)
        second = json.dumps({"text": "第二版日记。" * 40, "summary": "第二版"},
                            ensure_ascii=False)
        date = time.strftime("%Y-%m-%d")
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat", return_value=first), \
                mock.patch.object(presence.memory, "call_working",
                                  side_effect=RuntimeError("插件未装")):
            presence.generate_diary(self.inst, date=date, db_path=self.db)
        with mock.patch.object(presence, "_pick_provider", return_value="p1"), \
                mock.patch.object(presence.llm, "chat", return_value=second), \
                mock.patch.object(presence.memory, "call_working",
                                  return_value={"sessions": [
                                      {"id": "s1", "summary": "聊了骑车"}]}):
            result = presence.generate_diary(self.inst, date=date, db_path=self.db)
        items = presence.list_diaries("i1", db_path=self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["summary"], "第二版")
        self.assertEqual(result["diary"]["memory_ids"], ["s1"])
        self.assertEqual(result["diary"]["model_id"], "p1")


class PresenceRadarTest(_DbCase):
    def test_events_stats_and_prune(self):
        old = presence.add_event("i1", "radar_reply", group_id="g0", db_path=self.db)
        with fleet_store.session(self.db) as conn:
            conn.execute("UPDATE presence_events SET created=? WHERE id=?",
                         (time.time() - 9 * 86400, old))
        result = presence.radar_events({
            "instance_id": "i1",
            "events": [
                {"kind": "radar_reply", "group_id": "g1", "person_key": "u1"},
                {"kind": "radar_silent", "group_id": "g1", "person_key": "u2"},
                {"kind": "radar_silent", "group_id": "g2", "person_key": "u3"},
            ],
        }, instances=[self.inst], db_path=self.db)
        self.assertEqual(result["saved"], 3)
        self.assertEqual(result["pruned"], 1)
        stats = presence.radar_stats("i1", db_path=self.db)
        self.assertEqual(stats["reply"], 1)
        self.assertEqual(stats["silent"], 2)
        self.assertEqual(stats["total"], 3)
        groups = {item["group_id"]: item for item in stats["groups"]}
        self.assertEqual(groups["g1"], {"group_id": "g1", "reply": 1, "silent": 1})
        with self.assertRaises(presence.PresenceError):
            presence.radar_events({"instance_id": "i1",
                                   "kind": "unknown"}, instances=[self.inst],
                                  db_path=self.db)


class PresenceGroupConfigTest(_DbCase):
    SCHEMA = {
        "enabled_groups": {}, "initial_probability": {},
        "after_reply_probability": {}, "proactive_quiet_start": {},
        "not_allowed": {},
    }

    def test_whitelist_intersection(self):
        self.assertEqual(
            presence.gc_allowed_keys(self.SCHEMA),
            ["enabled_groups", "initial_probability", "after_reply_probability",
             "proactive_quiet_start"])

    def test_schema_is_read_from_instance_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = (Path(tmp) / "data" / "plugins" / "astrbot_plugin_group_chat_plus")
            target.mkdir(parents=True)
            (target / "_conf_schema.json").write_text(json.dumps({
                "enabled_groups": {}, "initial_probability": {},
                "reply_time_periods": {}, "not_allowed": {},
            }), encoding="utf-8")
            inst = {"id": "i1", "root": tmp}
            self.assertEqual(
                presence.gc_allowed_keys(inst=inst),
                ["enabled_groups", "initial_probability", "reply_time_periods"])

    def test_get_filters_and_put_merges_only_whitelisted(self):
        calls = []

        def call(inst, method, path, payload=None, query=None, timeout=60):
            calls.append((method, path, payload, query))
            if method == "GET":
                return {"data": {"config": {
                    "enabled_groups": ["1"], "initial_probability": 0.1,
                    "decision_ai_provider_id": "secret", "extra": 1}}}
            return {"data": {"saved": True}}

        cfg = presence.gc_config(self.inst, call=call, schema=self.SCHEMA)
        self.assertEqual(cfg["config"], {"enabled_groups": ["1"],
                                         "initial_probability": 0.1})
        self.assertNotIn("decision_ai_provider_id", cfg["config"])
        with self.assertRaises(presence.PresenceError):
            presence.save_gc_config(self.inst, {"decision_ai_provider_id": "x"},
                                    call=call, schema=self.SCHEMA)
        saved = presence.save_gc_config(
            self.inst, {"enabled_groups": ["1", "2"]}, call=call,
            schema=self.SCHEMA)
        self.assertEqual(saved["config"]["enabled_groups"], ["1", "2"])
        sent = calls[-1][2]["config"]
        self.assertEqual(sent["decision_ai_provider_id"], "secret")
        self.assertEqual(sent["extra"], 1)


if __name__ == "__main__":
    unittest.main()
