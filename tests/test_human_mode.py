import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from server import fleet_store, human_mode, human_settings, mood, styles


class Rng:
    def __init__(self, *values):
        self.values = list(values)
        self.index = 0

    def __call__(self):
        if self.index < len(self.values):
            value = self.values[self.index]
            self.index += 1
            return value
        return 0.99


class HumanModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        self.inst = {"id": "i1", "name": "大肥鱼"}
        self.payload = {
            "instance_id": "i1", "platform": "qq",
            "thread_key": "大肥鱼:FriendMessage:1", "person_key": "u1",
            "sender_name": "小明", "text": "在吗", "is_owner": False,
            "trigger": "private", "command": False, "tool_call": False,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_shadow_mode_logs_silence_without_real_limit(self):
        human_settings.save_settings("i1", {
            "shadow": True, "silence_enabled": True, "silence_probability": 1.0,
            "split_probability": 0.0, "delay_probability": 0.0,
            "short_probability": 0.0,
        }, db_path=self.db)
        for _ in range(3):
            result = human_mode.plan(self.payload, instances=[self.inst],
                                     db_path=self.db, rng=Rng(0.0, 0.0, 0.0))
            self.assertEqual(result["action"], "silence")
            self.assertTrue(result["shadow"])
        # 影子沉默不占真实日限：切到真实模式后仍能立刻真实沉默。
        human_settings.save_settings("i1", {"shadow": False}, db_path=self.db)
        real = human_mode.plan(self.payload, instances=[self.inst],
                               db_path=self.db, rng=Rng(0.0, 0.0, 0.0))
        self.assertEqual(real["action"], "silence")
        self.assertFalse(real["shadow"])
        data = human_mode.status("i1", db_path=self.db)
        self.assertEqual(data["counts"].get("shadow_silence"), 3)
        self.assertEqual(data["counts"].get("silence"), 1)
        self.assertTrue(data["events"])
        self.assertTrue(all(x["action"] != "reply" for x in data["events"]))

    def test_soothing_message_is_not_silenced_when_angry(self):
        human_settings.save_settings("i1", {
            "shadow": False, "silence_enabled": True,
            "silence_probability": 1.0, "split_probability": 0.0,
            "delay_probability": 0.0, "short_probability": 0.0,
        }, db_path=self.db)
        mood.adjust({"instance_id": "i1", "scope": "global", "mood": "angry",
                     "intensity": 90, "energy": 40, "social": 40}, db_path=self.db)
        mood.adjust({"instance_id": "i1", "scope": "relation", "platform": "qq",
                     "person_key": "u1", "anger": 90}, db_path=self.db)
        soothing = dict(self.payload, text="对不起，我错了，别生气了")
        result = human_mode.plan(soothing, instances=[self.inst],
                                 db_path=self.db, rng=Rng(0.0, 0.0, 0.0))
        self.assertNotEqual(result["action"], "silence")
        # 同一状态下普通消息仍可沉默，证明豁免只针对道歉/安慰。
        plain = human_mode.plan(self.payload, instances=[self.inst],
                                db_path=self.db, rng=Rng(0.0, 0.0, 0.0))
        self.assertEqual(plain["action"], "silence")

    def test_owner_never_silenced(self):
        human_settings.save_settings("i1", {
            "shadow": False, "silence_enabled": True,
            "silence_probability": 1.0, "split_probability": 0.0,
            "delay_probability": 0.0, "short_probability": 0.0,
        }, db_path=self.db)
        payload = dict(self.payload, is_owner=True)
        result = human_mode.plan(payload, instances=[self.inst],
                                 db_path=self.db, rng=Rng(0.0, 0.0, 0.0))
        self.assertNotEqual(result["action"], "silence")

    def test_real_silence_daily_limit_and_no_consecutive(self):
        human_settings.save_settings("i1", {
            "shadow": False, "silence_enabled": True,
            "silence_probability": 1.0, "silence_daily_limit": 2,
            "split_probability": 0.0, "delay_probability": 0.0, "short_probability": 0.0,
        }, db_path=self.db)
        first = human_mode.plan(self.payload, instances=[self.inst],
                                db_path=self.db, rng=Rng(0.0, 0.0))
        self.assertEqual(first["action"], "silence")
        second = human_mode.plan(self.payload, instances=[self.inst],
                                 db_path=self.db, rng=Rng(0.0, 0.0))
        self.assertNotEqual(second["action"], "silence")
        third = human_mode.plan(self.payload, instances=[self.inst],
                                db_path=self.db, rng=Rng(0.0, 0.0))
        self.assertEqual(third["action"], "silence")
        fourth = human_mode.plan(self.payload, instances=[self.inst],
                                 db_path=self.db, rng=Rng(0.0, 0.0))
        self.assertNotEqual(fourth["action"], "silence")

    def test_split_and_delay_bounds(self):
        human_settings.save_settings("i1", {
            "shadow": False, "silence_enabled": False,
            "split_probability": 1.0, "delay_probability": 0.0,
            "short_probability": 0.0,
            "max_delay_ms": 500, "max_chunks": 3,
        }, db_path=self.db)
        payload = dict(self.payload, text="今天天气不错，我们一起出去走走吧")
        split = human_mode.plan(payload, instances=[self.inst],
                                db_path=self.db, rng=Rng(0.0, 0.0))
        self.assertEqual(split["action"], "split")
        self.assertEqual(len(split["delays_ms"]), 2)
        self.assertTrue(all(delay >= 1 for delay in split["delays_ms"]))
        self.assertLessEqual(sum(split["delays_ms"]), 500)
        self.assertLessEqual(split["chunk_max_chars"], 120)
        owner = human_mode.plan(dict(payload, is_owner=True), instances=[self.inst],
                                db_path=self.db, rng=Rng(0.0, 0.0, 0.0))
        self.assertEqual(owner["action"], "split")
        self.assertNotIn("沉默", owner["behavior_hint"])
        self.assertIn("两小段", owner["behavior_hint"])

    def test_owner_short_text_never_split(self):
        human_settings.save_settings("i1", {
            "shadow": False, "silence_enabled": False,
            "split_probability": 1.0, "delay_probability": 1.0,
            "short_probability": 0.0, "max_delay_ms": 4000,
        }, db_path=self.db)
        payload = dict(self.payload, is_owner=True, text="嗯")
        result = human_mode.plan(payload, instances=[self.inst],
                                 db_path=self.db, rng=Rng(0.0, 0.0))
        self.assertNotEqual(result["action"], "split")
        self.assertIn(result["action"], ("delay", "reply"))
        self.assertNotIn("沉默", result["behavior_hint"])
        self.assertEqual(result["max_delay_ms"], 3000)

    def test_status_counts_do_not_cap_at_200(self):
        now = time.time()
        with fleet_store.session(self.db) as conn:
            for _ in range(205):
                human_mode._log_event(conn, "i1", "t", "reply", "正常回复", False, "h", now)
            human_mode._log_event(conn, "i1", "t", "silence", "真实沉默", False, "h", now)
        data = human_mode.status("i1", db_path=self.db)
        self.assertEqual(data["counts"].get("reply"), 205)
        self.assertEqual(data["counts"].get("silence"), 1)
        self.assertEqual([x["action"] for x in data["events"]], ["silence"])

    def test_plan_reads_daily_limit_inside_write_transaction(self):
        human_settings.save_settings("i1", {
            "shadow": False, "silence_enabled": True,
            "silence_probability": 1.0, "silence_daily_limit": 2,
            "split_probability": 0.0, "delay_probability": 0.0, "short_probability": 0.0,
        }, db_path=self.db)
        statements = []
        real_session = fleet_store.session

        @contextmanager
        def traced(db_path=None):
            with real_session(db_path) as conn:
                conn.set_trace_callback(statements.append)
                yield conn

        with mock.patch.object(fleet_store, "session", traced):
            human_mode.plan(self.payload, instances=[self.inst],
                            db_path=self.db, rng=Rng(0.0, 0.0))
        # 日限查询必须发生在 BEGIN IMMEDIATE 之后、同一事务的插入之前，
        # 否则并发 plan 会同时读到旧计数、突破每日沉默上限。
        begin = statements.index("BEGIN IMMEDIATE")
        limit_read = next(
            i for i, sql in enumerate(statements)
            if "count(*)" in sql and "human_behavior_events" in sql
        )
        insert = next(
            i for i, sql in enumerate(statements)
            if "INSERT INTO human_behavior_events" in sql
        )
        self.assertLess(begin, limit_read)
        self.assertLess(limit_read, insert)

    def test_status_reports_owner_exemption_note(self):
        data = human_mode.status("i1", db_path=self.db)
        self.assertEqual(data["owner_note"], "主人/管理员永不沉默")

    def test_style_block_prefers_relationship(self):
        styles.save_style("i1", "实例", "实例内容", db_path=self.db)
        styles.save_style("i1", "关系", "关系内容", scope="relationship",
                          person_key="u1", db_path=self.db)
        result = human_mode.plan(self.payload, instances=[self.inst],
                                 db_path=self.db, rng=Rng(0.99))
        self.assertIn("关系内容", result["style_block"])
        self.assertIn("实例内容", result["style_block"])
        self.assertLess(result["style_block"].index("关系内容"),
                        result["style_block"].index("实例内容"))

    def test_owner_style_block_includes_identity_calibration(self):
        owner = human_mode.plan(dict(self.payload, is_owner=True),
                                instances=[self.inst], db_path=self.db, rng=Rng(0.99))
        self.assertIn(human_mode.OWNER_IDENTITY, owner["style_block"])
        guest = human_mode.plan(self.payload, instances=[self.inst],
                                db_path=self.db, rng=Rng(0.99))
        self.assertNotIn("身份校准", guest["style_block"])


class HumanApiTest(unittest.TestCase):
    def test_routes_exist(self):
        from server import api
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in ("/api/human/plan", "/api/human/status", "/api/human/settings",
                     "/api/human/styles"):
            self.assertIn(path, paths)


if __name__ == "__main__":
    unittest.main()
