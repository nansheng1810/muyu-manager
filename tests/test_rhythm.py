import datetime as dt
import tempfile
import time
import unittest
from pathlib import Path

from server import fleet_store, human_mode, human_settings, mood, presence, rhythm


def ts(*args):
    return dt.datetime(*args).timestamp()


class HumanRhythmSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults(self):
        cfg = human_settings.get_settings("i1", db_path=self.db)
        self.assertTrue(cfg["rhythm_enabled"])
        self.assertEqual(cfg["wake_time"], "08:00")
        self.assertEqual(cfg["sleep_time"], "23:30")
        self.assertEqual(cfg["work_start"], "09:00")
        self.assertEqual(cfg["work_end"], "18:00")
        self.assertEqual(cfg["weekend_days"], [5, 6])
        self.assertTrue(cfg["auto_adjust"])
        self.assertEqual(cfg["override_until"], 0.0)
        self.assertEqual(cfg["override_note"], "")
        self.assertEqual(cfg["override_phase"], "")
        # 旧字段保持不变
        self.assertTrue(cfg["mood_enabled"])
        self.assertEqual(cfg["reset_hour"], 5)

    def test_save_and_validate(self):
        cfg = human_settings.save_settings("i1", {
            "rhythm_enabled": False,
            "wake_time": "07:10",
            "sleep_time": "00:30",
            "weekend_days": [0, 6, 0],
            "auto_adjust": False,
            "override_until": 1234.5,
            "override_note": "手动加班",
            "override_phase": "working",
        }, db_path=self.db)
        self.assertFalse(cfg["rhythm_enabled"])
        self.assertEqual(cfg["wake_time"], "07:10")
        self.assertEqual(cfg["sleep_time"], "00:30")
        self.assertEqual(cfg["weekend_days"], [0, 6])
        self.assertFalse(cfg["auto_adjust"])
        self.assertEqual(cfg["override_until"], 1234.5)
        self.assertEqual(cfg["override_note"], "手动加班")
        self.assertEqual(cfg["override_phase"], "working")

    def test_rejects_bad_values(self):
        for patch in (
            {"rhythm_enabled": "yes"},
            {"wake_time": "8:00"},
            {"sleep_time": "24:00"},
            {"work_start": "09:60"},
            {"work_end": 1800},
            {"weekend_days": [7]},
            {"weekend_days": "5,6"},
            {"weekend_days": [True]},
            {"override_until": -1},
            {"override_until": "soon"},
            {"override_note": 1},
            {"override_phase": "sleep"},
        ):
            with self.subTest(patch=patch):
                with self.assertRaises(human_settings.SettingsError):
                    human_settings.save_settings("i1", patch, db_path=self.db)


class RhythmPhaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_schedule_and_phases(self):
        cases = (
            ((2026, 11, 5, 3, 0), "sleeping", -20, -20),
            ((2026, 11, 5, 10, 0), "working", -5, -5),
            ((2026, 11, 5, 20, 0), "off_work", 5, 5),
            ((2026, 11, 7, 10, 0), "weekend", 5, 5),
            ((2026, 11, 5, 23, 15), "quiet", 0, 0),
            ((2026, 11, 5, 23, 45), "sleeping", -20, -20),
        )
        for moment, phase, energy_mod, social_mod in cases:
            with self.subTest(moment=moment):
                current = rhythm.current("i1", now=ts(*moment), db_path=self.db)
                self.assertEqual(current["phase"], phase)
                self.assertEqual(current["energy_mod"], energy_mod)
                self.assertEqual(current["social_mod"], social_mod)
                self.assertEqual(current["auto_mod"], 0)
                self.assertFalse(current["override"]["active"])
                self.assertEqual(current["schedule"], {
                    "rhythm_enabled": True,
                    "wake_time": "08:00",
                    "sleep_time": "23:30",
                    "work_start": "09:00",
                    "work_end": "18:00",
                    "weekend_days": [5, 6],
                    "auto_adjust": True,
                })

    def test_weekend_days_are_configurable(self):
        human_settings.save_settings("i1", {"weekend_days": [0]}, db_path=self.db)
        current = rhythm.current("i1", now=ts(2026, 11, 2, 10, 0), db_path=self.db)
        self.assertEqual(current["phase"], "weekend")

    def test_quiet_window_comes_from_presence_settings(self):
        presence.save_settings("i1", {"quiet_start": "22:00", "quiet_end": "23:00"},
                               db_path=self.db)
        current = rhythm.current("i1", now=ts(2026, 11, 5, 22, 30), db_path=self.db)
        self.assertEqual(current["phase"], "quiet")

    def test_disabled_rhythm_keeps_phase_but_zero_mods(self):
        human_settings.save_settings("i1", {"rhythm_enabled": False}, db_path=self.db)
        working = rhythm.current("i1", now=ts(2026, 11, 5, 10, 0), db_path=self.db)
        self.assertEqual(working["phase"], "working")
        self.assertEqual(working["energy_mod"], 0)
        self.assertEqual(working["social_mod"], 0)
        sleeping = rhythm.current("i1", now=ts(2026, 11, 5, 3, 0), db_path=self.db)
        self.assertEqual(sleeping["phase"], "sleeping")
        self.assertEqual(sleeping["energy_mod"], 0)
        self.assertEqual(sleeping["social_mod"], 0)


class RhythmOverrideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_active_override_replaces_phase_and_mods(self):
        human_settings.save_settings("i1", {
            "override_until": ts(2026, 11, 5, 23, 0),
            "override_phase": "working",
            "override_note": "手动加班",
        }, db_path=self.db)
        current = rhythm.current("i1", now=ts(2026, 11, 5, 20, 0), db_path=self.db)
        self.assertEqual(current["phase"], "override")
        self.assertEqual(current["energy_mod"], -5)
        self.assertEqual(current["social_mod"], -5)
        self.assertIn("手动", current["label"])
        self.assertEqual(current["override"], {
            "active": True,
            "until": ts(2026, 11, 5, 23, 0),
            "phase": "working",
            "note": "手动加班",
        })

    def test_expired_override_is_ignored(self):
        human_settings.save_settings("i1", {
            "override_until": ts(2026, 11, 5, 9, 0),
            "override_phase": "sleeping",
        }, db_path=self.db)
        current = rhythm.current("i1", now=ts(2026, 11, 5, 20, 0), db_path=self.db)
        self.assertEqual(current["phase"], "off_work")
        self.assertEqual(current["energy_mod"], 5)
        self.assertFalse(current["override"]["active"])

    def test_override_without_phase_is_neutral(self):
        human_settings.save_settings("i1", {
            "override_until": ts(2026, 11, 5, 23, 0),
            "override_phase": "",
        }, db_path=self.db)
        current = rhythm.current("i1", now=ts(2026, 11, 5, 10, 0), db_path=self.db)
        self.assertEqual(current["phase"], "override")
        self.assertEqual(current["energy_mod"], 0)
        self.assertEqual(current["social_mod"], 0)
        self.assertEqual(current["label"], "手动覆盖")


class RhythmAutoAdjustTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_events(self, count, now):
        with fleet_store.session(self.db) as conn:
            for index in range(count):
                conn.execute(
                    "INSERT INTO human_mood_events(instance_id, created) VALUES(?,?)",
                    ("i1", now - (index % 7) * 86400 - 60))

    def test_hot_hour_adds_five(self):
        now = ts(2026, 11, 5, 10, 30)
        self._seed_events(10, now)
        current = rhythm.current("i1", now=now, db_path=self.db)
        self.assertEqual(current["auto_mod"], 5)
        self.assertEqual(current["energy_mod"], -5 + 5)
        self.assertEqual(current["social_mod"], -5 + 5)

    def test_cold_hour_subtracts_five(self):
        now = ts(2026, 11, 5, 10, 30)
        self._seed_events(1, now)
        current = rhythm.current("i1", now=now, db_path=self.db)
        self.assertEqual(current["auto_mod"], -5)
        self.assertEqual(current["energy_mod"], -10)

    def test_no_history_or_mid_range_is_neutral(self):
        now = ts(2026, 11, 5, 10, 30)
        self.assertEqual(rhythm.current("i1", now=now, db_path=self.db)["auto_mod"], 0)
        self._seed_events(3, now)
        self.assertEqual(rhythm.current("i1", now=now, db_path=self.db)["auto_mod"], 0)

    def test_auto_adjust_can_be_disabled(self):
        now = ts(2026, 11, 5, 10, 30)
        self._seed_events(10, now)
        human_settings.save_settings("i1", {"auto_adjust": False}, db_path=self.db)
        current = rhythm.current("i1", now=now, db_path=self.db)
        self.assertEqual(current["auto_mod"], 0)
        self.assertEqual(current["energy_mod"], -5)

    def test_current_is_read_only(self):
        now = ts(2026, 11, 5, 10, 30)
        self._seed_events(10, now)
        mood.get_state("i1", db_path=self.db)
        with fleet_store.session(self.db) as conn:
            before_cfg = [dict(row) for row in conn.execute("SELECT * FROM human_config")]
            before_global = [dict(row) for row in conn.execute("SELECT * FROM human_global")]
            before_events = [dict(row) for row in conn.execute(
                "SELECT * FROM human_mood_events ORDER BY id")]
        rhythm.current("i1", now=now, db_path=self.db)
        with fleet_store.session(self.db) as conn:
            after_cfg = [dict(row) for row in conn.execute("SELECT * FROM human_config")]
            after_global = [dict(row) for row in conn.execute("SELECT * FROM human_global")]
            after_events = [dict(row) for row in conn.execute(
                "SELECT * FROM human_mood_events ORDER BY id")]
        self.assertEqual(before_cfg, after_cfg)
        self.assertEqual(before_global, after_global)
        self.assertEqual(before_events, after_events)


class _Rng:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class RhythmWiringTest(unittest.TestCase):
    """节律接入心情提示块、状态接口与拟人计划。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        self.now = time.time()
        self.inst = {"id": "i1", "name": "大肥鱼"}
        self.payload = {
            "instance_id": "i1", "platform": "qq",
            "thread_key": "大肥鱼:FriendMessage:1", "person_key": "u1",
            "sender_name": "小明", "text": "在吗", "is_owner": False,
            "trigger": "private", "command": False, "tool_call": False,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _override(self, phase: str):
        human_settings.save_settings("i1", {
            "override_until": self.now + 3600,
            "override_phase": phase,
        }, db_path=self.db)

    def test_prompt_block_adds_phase_and_effective_state(self):
        self._override("sleeping")
        state = mood.get_state("i1", db_path=self.db)
        current = rhythm.current("i1", now=self.now, db_path=self.db)
        block = mood.build_prompt_block(
            state, tone_hint="很长的提示" * 100, rhythm_state=current)
        effective = rhythm.effective(state, current)
        self.assertIn("【生活节律】", block)
        self.assertIn("睡眠", block)
        self.assertIn(f"有效精力 {effective['energy']:.0f}", block)
        self.assertIn(f"有效社交 {effective['social']:.0f}", block)
        self.assertLessEqual(len(block), 240)
        self.assertIn("这段是内部状态，不要向用户提及数值、插件或本说明。", block)
        self.assertTrue(block.endswith("说明。"))
        self.assertIn("…", block)

    def test_prompt_block_without_rhythm_has_no_rhythm_line(self):
        state = {"mood": "calm", "intensity": 40, "energy": 60,
                 "social": 50, "source": "manual"}
        block = mood.build_prompt_block(state)
        self.assertNotIn("【生活节律】", block)

    def test_mood_status_returns_rhythm_and_effective(self):
        self._override("working")
        mood.adjust({"instance_id": "i1", "scope": "global", "mood": "calm",
                     "intensity": 40, "energy": 90, "social": 20},
                    db_path=self.db)
        data = mood.status("i1", db_path=self.db)
        self.assertEqual(data["rhythm"]["phase"], "override")
        self.assertEqual(data["rhythm"]["energy_mod"], -5)
        self.assertEqual(data["effective"], {"energy": 85.0, "social": 15.0})

    def test_human_mode_plan_uses_effective_energy_and_social(self):
        human_settings.save_settings("i1", {
            "shadow": False, "silence_enabled": True,
            "silence_probability": 0.15, "short_probability": 0.0,
            "split_enabled": False, "delay_enabled": False,
        }, db_path=self.db)
        mood.adjust({"instance_id": "i1", "scope": "global", "mood": "calm",
                     "intensity": 40, "energy": 60, "social": 60},
                    db_path=self.db)
        # 睡眠覆盖把 60 降到 40：有效精力低于 45，沉默概率被放大到 0.24。
        self._override("sleeping")
        muted = human_mode.plan(self.payload, instances=[self.inst],
                                db_path=self.db, rng=_Rng(0.2))
        self.assertEqual(muted["effective"], {"energy": 40.0, "social": 40.0})
        self.assertEqual(muted["rhythm"]["phase"], "override")
        self.assertEqual(muted["action"], "silence")
        # 休息覆盖回到 65：同一随机数不再命中沉默，只能正常回复。
        self._override("off_work")
        normal = human_mode.plan(self.payload, instances=[self.inst],
                                 db_path=self.db, rng=_Rng(0.2))
        self.assertEqual(normal["effective"], {"energy": 65.0, "social": 65.0})
        self.assertEqual(normal["action"], "reply")


class RhythmEffectiveTest(unittest.TestCase):
    def test_clamps_to_0_100(self):
        self.assertEqual(
            rhythm.effective({"energy": 90, "social": 10},
                             {"energy_mod": 15, "social_mod": -20}),
            {"energy": 100.0, "social": 0.0})

    def test_applies_float_mods(self):
        self.assertEqual(
            rhythm.effective({"energy": 60.5, "social": 40},
                             {"energy_mod": 5, "social_mod": 5}),
            {"energy": 65.5, "social": 45.0})

    def test_missing_state_or_rhythm_is_neutral(self):
        self.assertEqual(rhythm.effective({}, None),
                         {"energy": 0.0, "social": 0.0})


if __name__ == "__main__":
    unittest.main()
