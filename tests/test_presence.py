import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from server import fleet_store, presence


class PresenceSchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_tables_columns_and_indexes(self):
        with fleet_store.session(self.db) as conn:
            tables = {row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            indexes = {row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
        for name in ("presence_relations", "presence_milestones", "presence_loops",
                     "presence_diaries", "presence_events", "presence_settings"):
            self.assertIn(name, tables)
        for name in ("idx_presence_relations_instance", "idx_presence_milestones_person",
                     "idx_presence_loops_due", "idx_presence_events_instance"):
            self.assertIn(name, indexes)
        with fleet_store.session(self.db) as conn:
            rel_cols = {row["name"] for row in conn.execute(
                "PRAGMA table_info(presence_relations)")}
            loop_cols = {row["name"] for row in conn.execute(
                "PRAGMA table_info(presence_loops)")}
            diary_cols = {row["name"] for row in conn.execute(
                "PRAGMA table_info(presence_diaries)")}
        self.assertIn("followup_enabled", rel_cols)
        self.assertIn("first_seen", rel_cols)
        self.assertIn("follow_up_text", loop_cols)
        self.assertIn("follow_up_generated_at", loop_cols)
        self.assertIn("memory_ids_json", diary_cols)

    def test_relation_unique_key(self):
        now = time.time()
        sql = ("INSERT INTO presence_relations(id, instance_id, platform, person_key, updated) "
               "VALUES(?,?,?,?,?)")
        with fleet_store.session(self.db) as conn:
            conn.execute(sql, ("pr_1", "i1", "qq", "u1", now))
        with self.assertRaises(sqlite3.IntegrityError):
            with fleet_store.session(self.db) as conn:
                conn.execute(sql, ("pr_2", "i1", "qq", "u1", now))

    def test_diary_unique_key(self):
        now = time.time()
        sql = ("INSERT INTO presence_diaries(id, instance_id, date, text, created, updated) "
               "VALUES(?,?,?,?,?,?)")
        with fleet_store.session(self.db) as conn:
            conn.execute(sql, ("d1", "i1", "2026-11-05", "a", now, now))
        with self.assertRaises(sqlite3.IntegrityError):
            with fleet_store.session(self.db) as conn:
                conn.execute(sql, ("d2", "i1", "2026-11-05", "b", now, now))


class PresenceSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults(self):
        cfg = presence.get_settings("i1", db_path=self.db)
        self.assertEqual(cfg, {
            "followup_enabled": True,
            "followup_shadow": True,
            "familiarity_threshold": 30,
            "daily_limit": 1,
            "weekly_limit": 3,
            "quiet_start": "23:00",
            "quiet_end": "08:00",
            "quiet_after_hours": 6,
            "scan_min_messages": 6,
            "scan_min_hours": 6,
            "radar_window_seconds": 5,
            "radar_retention_days": 7,
            "diary_enabled": True,
            "diary_time": "23:30",
            "diary_inject_next_day": True,
            "diary_max_chars": 500,
        })

    def test_save_and_reload_keeps_other_defaults(self):
        saved = presence.save_settings("i1", {
            "followup_shadow": False,
            "daily_limit": 2,
            "quiet_start": "22:30",
            "diary_time": "22:45",
        }, db_path=self.db)
        self.assertFalse(saved["followup_shadow"])
        cfg = presence.get_settings("i1", db_path=self.db)
        self.assertFalse(cfg["followup_shadow"])
        self.assertEqual(cfg["daily_limit"], 2)
        self.assertEqual(cfg["quiet_start"], "22:30")
        self.assertEqual(cfg["diary_time"], "22:45")
        self.assertEqual(cfg["weekly_limit"], 3)
        self.assertTrue(cfg["followup_enabled"])

    def test_rejects_bad_values(self):
        for patch in (
            {"unknown_key": 1},
            {"followup_shadow": "yes"},
            {"familiarity_threshold": True},
            {"familiarity_threshold": 101},
            {"daily_limit": -1},
            {"weekly_limit": 101},
            {"quiet_after_hours": 169},
            {"scan_min_messages": 0},
            {"scan_min_hours": -1},
            {"radar_window_seconds": 0},
            {"radar_retention_days": 0},
            {"diary_max_chars": 10},
            {"quiet_start": "8:00"},
            {"quiet_end": "24:00"},
            {"diary_time": "23:60"},
            {"diary_time": 2330},
        ):
            with self.subTest(patch=patch):
                with self.assertRaises(presence.PresenceError):
                    presence.save_settings("i1", patch, db_path=self.db)


class PresenceRelationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_keeps_first_seen_and_accumulates_messages(self):
        first = presence.upsert_relation(
            "i1", "qq", "u1", display_name="小明", nickname="明明",
            stage="familiar", first_seen=500.0, last_seen=1000.0,
            message_count=2, db_path=self.db)
        self.assertEqual(first["first_seen"], 500.0)
        self.assertEqual(first["last_seen"], 1000.0)
        self.assertEqual(first["message_count"], 2)
        self.assertTrue(first["allow_memory"])
        self.assertTrue(first["followup_enabled"])
        second = presence.upsert_relation(
            "i1", "qq", "u1", stage="close", allow_memory=False,
            followup_enabled=False, message_count=3, db_path=self.db)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["first_seen"], 500.0)
        self.assertEqual(second["message_count"], 5)
        self.assertEqual(second["display_name"], "小明")
        self.assertEqual(second["nickname"], "明明")
        self.assertEqual(second["stage"], "close")
        self.assertFalse(second["allow_memory"])
        self.assertFalse(second["followup_enabled"])
        self.assertGreaterEqual(second["last_seen"], 1000.0)

    def test_upsert_rejects_bad_stage(self):
        with self.assertRaises(presence.PresenceError):
            presence.upsert_relation("i1", "qq", "u1", stage="lover", db_path=self.db)

    def test_list_merges_human_relations_read_only(self):
        presence.upsert_relation("i1", "qq", "u1", display_name="小明", db_path=self.db)
        with fleet_store.session(self.db) as conn:
            conn.execute(
                "INSERT INTO human_relations(id, instance_id, platform, person_key, "
                "display_name, familiarity, affection, anger, updated) VALUES(?,?,?,?,?,?,?,?,?)",
                ("r1", "i1", "qq", "u1", "情绪档案名", 42.0, 7.0, 3.0, time.time()),
            )
        merged = presence.list_relations("i1", db_path=self.db)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["display_name"], "小明")
        self.assertEqual(merged[0]["familiarity"], 42.0)
        self.assertEqual(merged[0]["affection"], 7.0)
        self.assertEqual(merged[0]["anger"], 3.0)
        raw = presence.list_relations("i1", merge=False, db_path=self.db)
        self.assertNotIn("familiarity", raw[0])
        self.assertNotIn("affection", raw[0])

    def test_list_returns_empty_mood_values_when_missing(self):
        presence.upsert_relation("i1", "qq", "u2", db_path=self.db)
        item = presence.list_relations("i1", db_path=self.db)[0]
        self.assertEqual(item["familiarity"], 0.0)
        self.assertEqual(item["affection"], 0.0)
        self.assertEqual(item["anger"], 0.0)


class PresenceMilestoneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_list_delete(self):
        first = presence.add_milestone(
            "i1", "qq", "u1", "first_contact", "第一次见面",
            occurred_at=1000.0, db_path=self.db)
        second = presence.add_milestone(
            "i1", "qq", "u1", "custom", "一起听歌", detail="周杰伦",
            occurred_at=2000.0, db_path=self.db)
        other = presence.add_milestone(
            "i1", "qq", "u2", "first_private", "首次私聊",
            occurred_at=500.0, db_path=self.db)
        self.assertEqual(first["source"], "manual")
        items = presence.list_milestones("i1", db_path=self.db)
        self.assertEqual([item["id"] for item in items],
                         [second["id"], first["id"], other["id"]])
        self.assertEqual(presence.list_milestones(
            "i1", person_key="u1", db_path=self.db)[0]["detail"], "周杰伦")
        self.assertTrue(presence.delete_milestone(first["id"], db_path=self.db))
        self.assertFalse(presence.delete_milestone(first["id"], db_path=self.db))
        self.assertEqual(len(presence.list_milestones("i1", db_path=self.db)), 2)

    def test_rejects_missing_fields(self):
        with self.assertRaises(presence.PresenceError):
            presence.add_milestone("i1", "qq", "u1", "", "标题", db_path=self.db)
        with self.assertRaises(presence.PresenceError):
            presence.add_milestone("i1", "qq", "u1", "custom", " ", db_path=self.db)


class PresenceLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_update_resolve_ignore_and_filter(self):
        loop = presence.add_loop(
            "i1", "qq", "u1", "说好周末去骑车", thread_key="t1",
            detail="周六上午", confidence=0.8, follow_up_after_hours=24,
            db_path=self.db)
        self.assertEqual(loop["status"], "open")
        self.assertEqual(loop["source"], "auto")
        self.assertAlmostEqual(loop["follow_up_after"],
                               loop["created"] + 24 * 3600, delta=2)
        updated = presence.update_loop(loop["id"], {
            "follow_up_text": "上次说周末去骑车，去了吗？",
            "follow_up_generated_at": 1234.0,
            "detail": "改到周日",
        }, db_path=self.db)
        self.assertEqual(updated["follow_up_text"], "上次说周末去骑车，去了吗？")
        self.assertEqual(updated["follow_up_generated_at"], 1234.0)
        self.assertEqual(updated["detail"], "改到周日")
        resolved = presence.resolve_loop(loop["id"], db_path=self.db)
        self.assertEqual(resolved["status"], "resolved")
        other = presence.add_loop("i1", "qq", "u2", "下次再聊", db_path=self.db)
        ignored = presence.ignore_loop(other["id"], db_path=self.db)
        self.assertEqual(ignored["status"], "ignored")
        self.assertEqual(presence.list_loops("i1", status="open", db_path=self.db), [])
        self.assertEqual(
            [item["id"] for item in presence.list_loops("i1", status="resolved",
                                                        db_path=self.db)],
            [loop["id"]])

    def test_update_rejects_unknown_or_bad_status(self):
        loop = presence.add_loop("i1", "qq", "u1", "话题", db_path=self.db)
        with self.assertRaises(presence.PresenceError):
            presence.update_loop(loop["id"], {"status": "done"}, db_path=self.db)
        with self.assertRaises(presence.PresenceError):
            presence.update_loop(loop["id"], {"unknown": 1}, db_path=self.db)
        with self.assertRaises(presence.PresenceError):
            presence.update_loop("missing", {"topic": "x"}, db_path=self.db)

    def test_add_rejects_bad_confidence_and_missing_topic(self):
        with self.assertRaises(presence.PresenceError):
            presence.add_loop("i1", "qq", "u1", "话题", confidence=1.5, db_path=self.db)
        with self.assertRaises(presence.PresenceError):
            presence.add_loop("i1", "qq", "u1", " ", db_path=self.db)


class PresenceDiaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_list_get_update_delete(self):
        older = presence.upsert_diary(
            "i1", "2026-11-04", "今天有点累", mood={"mood": "low"},
            memory_ids=["m1", "m2"], model_id="p1", db_path=self.db)
        self.assertEqual(older["mood"], {"mood": "low"})
        self.assertEqual(older["memory_ids"], ["m1", "m2"])
        newer = presence.upsert_diary("i1", "2026-11-05", "今天还行", db_path=self.db)
        self.assertEqual(newer["mood"], {})
        self.assertEqual(newer["memory_ids"], [])
        self.assertEqual([item["date"] for item in presence.list_diaries(
            "i1", db_path=self.db)], ["2026-11-05", "2026-11-04"])
        self.assertEqual(presence.get_diary(
            "i1", "2026-11-04", db_path=self.db)["text"], "今天有点累")
        updated = presence.update_diary(older["id"], {
            "text": "今天其实还行", "memory_ids": ["m3"]}, db_path=self.db)
        self.assertEqual(updated["text"], "今天其实还行")
        self.assertEqual(updated["memory_ids"], ["m3"])
        self.assertEqual(updated["created"], older["created"])
        self.assertGreaterEqual(updated["updated"], older["updated"])
        self.assertTrue(presence.delete_diary(newer["id"], db_path=self.db))
        self.assertFalse(presence.delete_diary(newer["id"], db_path=self.db))
        self.assertIsNone(presence.get_diary("i1", "2026-11-05", db_path=self.db))

    def test_upsert_same_date_overwrites_without_duplicate(self):
        presence.upsert_diary("i1", "2026-11-05", "第一版", db_path=self.db)
        presence.upsert_diary("i1", "2026-11-05", "第二版", db_path=self.db)
        items = presence.list_diaries("i1", db_path=self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "第二版")

    def test_rejects_bad_date(self):
        with self.assertRaises(presence.PresenceError):
            presence.upsert_diary("i1", "2026-13-01", "文本", db_path=self.db)
        with self.assertRaises(presence.PresenceError):
            presence.upsert_diary("i1", "2026-11-05", " ", db_path=self.db)


class PresenceEventTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_list_decode_and_prune(self):
        event_id = presence.add_event(
            "i1", "radar_silent", group_id="g1", person_key="u1",
            payload={"window": 5}, db_path=self.db)
        presence.add_event("i2", "radar_reply", group_id="g2", db_path=self.db)
        items = presence.list_events("i1", db_path=self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], event_id)
        self.assertEqual(items[0]["payload"], {"window": 5})
        self.assertEqual(len(presence.list_events("i1", kind="radar_reply",
                                                  db_path=self.db)), 0)
        with fleet_store.session(self.db) as conn:
            conn.execute("UPDATE presence_events SET created=? WHERE id=?",
                         (time.time() - 8 * 86400, event_id))
        self.assertEqual(presence.prune_events(
            "i1", retention_days=7, db_path=self.db), 1)
        self.assertEqual(presence.list_events("i1", db_path=self.db), [])
        self.assertEqual(len(presence.list_events("i2", db_path=self.db)), 1)

    def test_rejects_empty_instance_or_kind(self):
        with self.assertRaises(presence.PresenceError):
            presence.add_event("", "radar_reply", db_path=self.db)
        with self.assertRaises(presence.PresenceError):
            presence.add_event("i1", " ", db_path=self.db)


class PresenceValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_instance_rejected(self):
        for call in (
            lambda: presence.get_settings("", db_path=self.db),
            lambda: presence.list_relations("", db_path=self.db),
            lambda: presence.list_milestones("", db_path=self.db),
            lambda: presence.list_loops("", db_path=self.db),
            lambda: presence.list_diaries("", db_path=self.db),
            lambda: presence.get_diary("", "2026-11-05", db_path=self.db),
        ):
            with self.assertRaises(presence.PresenceError):
                call()

    def test_get_relation_roundtrip(self):
        presence.upsert_relation("i1", "qq", "u1", nickname="小明", db_path=self.db)
        rel = presence.get_relation("i1", "qq", "u1", db_path=self.db)
        self.assertEqual(rel["nickname"], "小明")
        self.assertIsNone(presence.get_relation("i1", "qq", "missing", db_path=self.db))


if __name__ == "__main__":
    unittest.main()
