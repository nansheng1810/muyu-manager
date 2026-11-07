import tempfile
import time
import unittest
from pathlib import Path

from server import duet


def instances():
    return [
        {"id": "a", "name": "大肥鱼", "root": "D:/a", "dash_port": 6185},
        {"id": "b", "name": "千问", "root": "D:/b", "dash_port": 6186},
    ]


class FakeCall:
    def __init__(self, qqs=("111", "222")):
        self.qqs = qqs
        self.calls = []
        self.spoken = []
        self.human = []

    def __call__(self, inst, method, path, payload=None, query=None, timeout=60):
        self.calls.append((inst["id"], method, path, payload, query))
        if path.endswith("/status"):
            qq = self.qqs[0] if inst["id"] == "a" else self.qqs[1]
            return {"status": "ok", "data": {
                "status": "ok",
                "data": {
                    "self_qq": qq,
                    "nickname": inst["name"],
                    "platform_ready": True,
                    "filter_enabled": True,
                    "client_keys": [qq],
                    "groups": {"123456": {"last_ts": 0, "seq": 0}},
                },
            }}
        if path.endswith("/config"):
            return {"status": "ok", "data": {"status": "ok", "data": {}}}
        if path.endswith("/activity"):
            since = float((query or {}).get("since") or 0)
            event = self.human.pop(0) if self.human and since > 0 else None
            return {"status": "ok", "data": {
                "status": "ok",
                "data": {"events": [event] if event else [], "last_ts": event["ts"] if event else 0},
            }}
        if path.endswith("/speak"):
            self.spoken.append((inst["id"], payload))
            return {"status": "ok", "data": {
                "status": "ok",
                "data": {"text": f"我是{inst['name']}", "message_id": f"m{len(self.spoken)}"},
            }}
        if path.endswith("/cancel"):
            return {"status": "ok", "data": {"status": "ok", "data": {"cancelled": payload.get("scene_id")}}}
        raise AssertionError(f"unexpected path {path}")


class TempDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()


class NormalizeStartTest(unittest.TestCase):
    def test_rounds_defaults_and_clamps(self):
        config = duet.normalize_start({"mode": "rounds", "group_id": "123456"})
        self.assertEqual(config["rounds"], 6)
        self.assertEqual(config["interval"], 15)
        self.assertEqual(config["max_chars"], 80)
        self.assertEqual(config["duration_seconds"], 0)
        self.assertEqual(config["topic"], "随便聊聊最近发生的事")

        config = duet.normalize_start({
            "mode": "rounds", "group_id": 123456, "topic": " 周末 ",
            "rounds": 99, "interval": 1, "max_chars": 500,
        })
        self.assertEqual(config["rounds"], duet.MAX_ROUNDS)
        self.assertEqual(config["interval"], duet.MIN_INTERVAL)
        self.assertEqual(config["max_chars"], 200)
        self.assertEqual(config["topic"], "周末")

    def test_duration_blank_uses_safety_cap(self):
        config = duet.normalize_start({"mode": "duration", "group_id": "123456"})
        self.assertEqual(config["duration_seconds"], duet.MAX_SECONDS)
        config = duet.normalize_start({
            "mode": "duration", "group_id": "123456", "duration_seconds": 120,
        })
        self.assertEqual(config["duration_seconds"], 120)
        config = duet.normalize_start({
            "mode": "duration", "group_id": "123456", "duration_seconds": 99999,
        })
        self.assertEqual(config["duration_seconds"], duet.MAX_SECONDS)

    def test_rejects_bad_input(self):
        with self.assertRaises(duet.DuetError):
            duet.normalize_start({"mode": "auto", "group_id": "123456"})
        with self.assertRaises(duet.DuetError):
            duet.normalize_start({"mode": "rounds", "group_id": "abc"})
        with self.assertRaises(duet.DuetError):
            duet.normalize_start({
                "mode": "rounds", "group_id": "123456", "instance_ids": ["a"],
            })
        with self.assertRaises(duet.DuetError):
            duet.normalize_start({
                "mode": "rounds", "group_id": "123456", "instance_ids": ["a", "a"],
            })


class AutoConfigTest(unittest.TestCase):
    def test_enable_requires_group(self):
        with self.assertRaises(duet.DuetError):
            duet.normalize_auto({"enabled": True})

    def test_clamps_and_normalizes_clock(self):
        config = duet.normalize_auto({
            "enabled": True, "group_id": "123456",
            "silence_minutes": 1, "night_start": "7:5", "night_end": "25:00",
            "daily_limit": 99, "cooldown_minutes": 1, "rounds": 99,
        })
        self.assertEqual(config["silence_minutes"], 5)
        self.assertEqual(config["night_start"], "23:00")
        self.assertEqual(config["night_end"], "08:00")
        self.assertEqual(config["daily_limit"], 10)
        self.assertEqual(config["cooldown_minutes"], 10)
        self.assertEqual(config["rounds"], 12)

    def test_clock_window_wraps_midnight(self):
        self.assertTrue(duet.in_window("23:30", "23:00", "08:00"))
        self.assertTrue(duet.in_window("07:59", "23:00", "08:00"))
        self.assertFalse(duet.in_window("12:00", "23:00", "08:00"))
        self.assertTrue(duet.in_window("09:00", "08:00", "23:00"))
        self.assertFalse(duet.in_window("08:00", "08:00", "08:00"))


class AutoDecisionTest(unittest.TestCase):
    def auto(self, **patch):
        return {**duet.DEFAULT_AUTO, "enabled": True, "group_id": "123456", **patch}

    def test_disabled_and_missing_group(self):
        self.assertFalse(duet.auto_decision(duet.DEFAULT_AUTO, 0, 0, 0, 0, 0)[0])
        self.assertFalse(duet.auto_decision(self.auto(group_id=""), 0, 0, 0, 0, 0)[0])

    def test_night_daily_limit_and_cooldown(self):
        now = time.mktime((2026, 11, 3, 23, 30, 0, 0, 0, -1))
        ok, reason = duet.auto_decision(self.auto(), now, 0, 0, 0, 0)
        self.assertFalse(ok)
        self.assertIn("夜间", reason)

        now = time.mktime((2026, 11, 3, 12, 0, 0, 0, 0, -1))
        ok, reason = duet.auto_decision(self.auto(daily_limit=1), now, 0, 0, 0, 1)
        self.assertFalse(ok)
        self.assertIn("上限", reason)

        ok, reason = duet.auto_decision(self.auto(), now, now - 60, 0, 0, 0)
        self.assertFalse(ok)
        self.assertIn("冷却", reason)

    def test_recent_human_blocks_and_silence_allows(self):
        now = time.mktime((2026, 11, 3, 12, 0, 0, 0, 0, -1))
        ok, reason = duet.auto_decision(self.auto(), now, 0, 0, now - 60, 0)
        self.assertFalse(ok)
        self.assertIn("活跃", reason)
        ok, reason = duet.auto_decision(self.auto(), now, 0, 0, now - 31 * 60, 0)
        self.assertTrue(ok)


class SceneStoreTest(TempDb):
    def test_scene_and_turn_lifecycle(self):
        scene = duet.create_scene("rounds", "123456", "话题", {"rounds": 2}, db_path=self.db)
        self.assertEqual(scene["status"], "starting")
        duet.add_turn(scene["id"], "a", "你好", speaker_name="大肥鱼", message_id="m1", db_path=self.db)
        duet.add_turn(scene["id"], "human", "插话", status="human", speaker_name="群友", db_path=self.db)
        loaded = duet.get_scene(scene["id"], db_path=self.db, with_turns=True)
        self.assertEqual(len(loaded["turns"]), 2)
        self.assertEqual(loaded["turns"][0]["speaker_name"], "大肥鱼")
        self.assertEqual(loaded["turns"][1]["status"], "human")
        duet.update_scene(scene["id"], "stopped", "管理员结束", db_path=self.db)
        listed = duet.list_scenes(db_path=self.db)
        self.assertEqual(listed[0]["status"], "stopped")
        self.assertEqual(listed[0]["note"], "管理员结束")
        self.assertEqual(listed[0]["turn_count"], 2)

    def test_auto_config_roundtrip_and_stats(self):
        config = duet.normalize_auto({"enabled": True, "group_id": "123456"}, None)
        saved = duet.save_auto(config, db_path=self.db)
        self.assertTrue(saved["enabled"])
        self.assertEqual(duet.load_auto(db_path=self.db)["group_id"], "123456")
        duet.create_scene("auto", "123456", "自动", {}, db_path=self.db)
        stats = duet.auto_stats(db_path=self.db)
        self.assertEqual(stats["today_count"], 1)
        self.assertGreater(stats["last_started"], 0)


class PayloadTest(unittest.TestCase):
    def test_build_payload_maps_names_and_skips_errors(self):
        scene = {"id": "s1", "group_id": "123456", "topic": "话题"}
        config = {"max_chars": 60, "names": {"a": "大肥鱼", "b": "千问"}}
        speaker = {"id": "a", "name": "a"}
        peer = {"id": "b", "name": "b"}
        turns = [
            {"speaker": "a", "text": "第一句", "status": "sent"},
            {"speaker": "b", "text": "坏行", "status": "error"},
            {"speaker": "human", "text": "插话", "status": "human", "speaker_name": "群友"},
        ]
        payload = duet.build_speak_payload(scene, config, speaker, peer, turns, 3)
        self.assertEqual(payload["self_name"], "大肥鱼")
        self.assertEqual(payload["peer_name"], "千问")
        self.assertEqual(payload["turn"], 3)
        self.assertEqual([item["text"] for item in payload["transcript"]], ["第一句", "插话"])
        self.assertEqual(payload["transcript"][1]["speaker_name"], "群友")


class EngineTest(TempDb):
    def setUp(self):
        super().setUp()
        self._engines = []

    def tearDown(self):
        for engine in self._engines:
            engine.shutdown()
        super().tearDown()

    def make_engine(self, qqs=("111", "222")):
        fake = FakeCall(qqs=qqs)
        engine = duet.DuetEngine(
            instances=instances, call=fake, db_path=self.db,
        )
        self._engines.append(engine)
        return engine, fake

    def test_preflight_writes_peer_qq(self):
        engine, fake = self.make_engine()
        statuses = engine._preflight(instances())
        self.assertEqual([item["self_qq"] for item in statuses], ["111", "222"])
        configs = [call for call in fake.calls if call[2].endswith("/config")]
        self.assertEqual(configs[0][3], {"peer_qq": ["222"], "self_qq": "111", "filter_enabled": True})
        self.assertEqual(configs[1][3], {"peer_qq": ["111"], "self_qq": "222", "filter_enabled": True})

    def test_preflight_uses_instance_qq_and_rejects_disconnected_napcat(self):
        class EmptyQqCall(FakeCall):
            def __call__(self, inst, method, path, payload=None, query=None, timeout=60):
                result = super().__call__(inst, method, path, payload, query, timeout)
                if path.endswith("/status"):
                    result["data"]["data"]["self_qq"] = ""
                return result

        fake = EmptyQqCall()
        engine = duet.DuetEngine(instances=instances, call=fake, db_path=self.db)
        self._engines.append(engine)
        pairs = instances()
        pairs[0]["qq"] = "333333"
        pairs[1]["qq"] = "444444"
        statuses = engine._preflight(pairs)
        self.assertEqual([item["self_qq"] for item in statuses], ["333333", "444444"])
        configs = [call for call in fake.calls if call[2].endswith("/config")]
        self.assertEqual(configs[0][3]["self_qq"], "333333")

        class NoClientCall(EmptyQqCall):
            def __call__(self, inst, method, path, payload=None, query=None, timeout=60):
                result = super().__call__(inst, method, path, payload, query, timeout)
                if path.endswith("/status"):
                    result["data"]["data"]["client_keys"] = []
                return result

        engine2 = duet.DuetEngine(instances=instances, call=NoClientCall(), db_path=self.db)
        self._engines.append(engine2)
        with self.assertRaises(duet.DuetError) as raised:
            engine2._preflight(pairs)
        self.assertIn("NapCat", str(raised.exception))

    def test_preflight_rejects_same_qq(self):
        engine, fake = self.make_engine(qqs=("111", "111"))
        with self.assertRaises(duet.DuetError):
            engine._preflight(instances())

    def test_start_speaks_one_turn_then_stops(self):
        engine, fake = self.make_engine()
        engine._wait_interval = lambda *args: ("stop", None)
        scene = engine.start({"mode": "rounds", "group_id": "123456", "rounds": 2})
        engine._thread.join(timeout=3)
        loaded = duet.get_scene(scene["id"], db_path=self.db, with_turns=True)
        self.assertEqual(loaded["status"], "stopped")
        self.assertEqual(len(loaded["turns"]), 1)
        speaker, payload = fake.spoken[0]
        self.assertIn(speaker, {"a", "b"})
        self.assertEqual(payload["topic"], "随便聊聊最近发生的事")
        self.assertIn("self_name", payload)

    def test_human_message_pauses_scene(self):
        engine, fake = self.make_engine()
        fake.human.append({"ts": time.time(), "sender": "999", "name": "群友", "text": "你们在聊啥"})
        calls = {"n": 0}

        def wait(*args):
            calls["n"] += 1
            return ("human", fake.human[0]) if calls["n"] == 1 else ("stop", None)

        engine._wait_interval = wait
        scene = engine.start({"mode": "rounds", "group_id": "123456", "rounds": 3})
        deadline = time.time() + 3
        while time.time() < deadline:
            loaded = duet.get_scene(scene["id"], db_path=self.db, with_turns=True)
            if loaded["status"] == "paused":
                break
            time.sleep(0.05)
        self.assertEqual(loaded["status"], "paused")
        self.assertTrue(any(turn["speaker"] == "human" for turn in loaded["turns"]))
        engine.stop(scene["id"])
        self.assertEqual(duet.get_scene(scene["id"], db_path=self.db)["status"], "stopped")

    def test_auto_tick_start_and_stop(self):
        engine, fake = self.make_engine()
        config = duet.normalize_auto({
            "enabled": True, "group_id": "123456",
            "night_start": "00:00", "night_end": "00:00",
            "daily_limit": 3,
        }, None)
        # 当天没有历史场景时，跳过沿用测试库里的上次自动场景
        duet.save_auto(config, db_path=self.db)
        engine._wait_interval = lambda *args: ("stop", None)
        result = engine.auto_tick()
        self.assertTrue(result["started"], result)
        scene = result["scene"]
        self.assertEqual(scene["mode"], "auto")
        engine.stop(scene["id"])


if __name__ == "__main__":
    unittest.main()
