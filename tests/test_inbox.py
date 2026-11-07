import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from server import inbox


def make_livingmemory(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT,
        sender_id TEXT, sender_name TEXT, group_id TEXT, platform TEXT, timestamp REAL)""")
    conn.executemany("INSERT INTO messages(session_id,role,content,sender_id,sender_name,group_id,platform,timestamp) "
                     "VALUES(?,?,?,?,?,?,?,?)", rows)
    conn.commit(); conn.close()


class InboxStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_thread_and_unread(self):
        thread = inbox.upsert_thread(
            "qq", "inst1", "大肥鱼:FriendMessage:1", "private", "小明", db_path=self.db
        )
        self.assertEqual(thread["display_name"], "小明")
        self.assertTrue(inbox.add_message(
            thread["id"], "qq", "inst1", "in", "1", "小明", "你好", 100.0,
            "lm:1", "livingmemory", db_path=self.db,
        ))
        self.assertFalse(inbox.add_message(
            thread["id"], "qq", "inst1", "in", "1", "小明", "你好", 100.0,
            "lm:1", "livingmemory", db_path=self.db,
        ))
        inbox.add_message(
            thread["id"], "qq", "inst1", "out", "bot", "牧鱼", "在", 101.0,
            "lm:2", "livingmemory", db_path=self.db,
        )
        listed = inbox.list_threads(db_path=self.db)
        self.assertEqual(listed[0]["unread"], 1)
        inbox.mark_read(thread["id"], db_path=self.db)
        self.assertEqual(inbox.list_threads(db_path=self.db)[0]["unread"], 0)
        self.assertEqual(inbox.thread_messages(thread["id"], db_path=self.db)[1]["text"], "在")

    def test_filters_and_search(self):
        a = inbox.upsert_thread("qq", "inst1", "a", "private", "小明", db_path=self.db)
        inbox.add_message(a["id"], "qq", "inst1", "in", "1", "小明", "hello", 1, "x1", "livingmemory", db_path=self.db)
        b = inbox.upsert_thread("bilibili", "inst1", "bili:2", "private", "B站用户", db_path=self.db)
        inbox.add_message(b["id"], "bilibili", "inst1", "in", "2", "B站用户", "另一个", 2, "x2", "bili_events", db_path=self.db)
        self.assertEqual(len(inbox.list_threads(platform="qq", db_path=self.db)), 1)
        self.assertEqual(len(inbox.list_threads(query="B站", db_path=self.db)), 1)
        self.assertEqual(len(inbox.list_threads(unread_only=True, db_path=self.db)), 2)

    def test_duplicate_external_id_dedupes_per_account_only(self):
        a = inbox.upsert_thread("qq", "inst1", "dedupe", "private", "小明", db_path=self.db)
        self.assertTrue(inbox.add_message(
            a["id"], "qq", "inst1", "in", "1", "小明", "hi", 10.0, "dup:1", "livingmemory", db_path=self.db,
        ))
        self.assertFalse(inbox.add_message(
            a["id"], "qq", "inst1", "in", "1", "小明", "hi", 10.0, "dup:1", "livingmemory", db_path=self.db,
        ))
        # same external_id under another account is a different message, not a conflict
        b = inbox.upsert_thread("qq", "inst2", "dedupe", "private", "小明", db_path=self.db)
        self.assertTrue(inbox.add_message(
            b["id"], "qq", "inst2", "in", "1", "小明", "hi", 10.0, "dup:1", "livingmemory", db_path=self.db,
        ))
        self.assertEqual(len(inbox.thread_messages(a["id"], db_path=self.db)), 1)
        self.assertEqual(len(inbox.thread_messages(b["id"], db_path=self.db)), 1)
        # only the dedupe conflict is ignored; other constraint errors still surface
        with self.assertRaises(sqlite3.IntegrityError):
            inbox.add_message(
                a["id"], "qq", "inst1", "in", "1", "小明", "boom", 11.0, "dup:2", None, db_path=self.db,
            )

    def test_add_message_requires_existing_thread(self):
        with self.assertRaises(inbox.InboxError):
            inbox.add_message(
                "in_missing", "qq", "inst1", "in", "1", "小明", "hi", 1.0, "orphan:1", "livingmemory",
                db_path=self.db,
            )

    def test_same_timestamp_paging_with_rowid_cursor(self):
        t = inbox.upsert_thread("qq", "inst1", "page", "private", "小明", db_path=self.db)
        for i, ts in enumerate([10.0, 20.0, 20.0, 20.0, 30.0]):
            inbox.add_message(t["id"], "qq", "inst1", "in", "1", "小明", f"m{i}", ts, f"page:{i}",
                              "livingmemory", db_path=self.db)
        first = inbox.thread_messages(t["id"], limit=3, db_path=self.db)
        self.assertEqual([m["text"] for m in first], ["m2", "m3", "m4"])
        second = inbox.thread_messages(
            t["id"], before=first[0]["ts"], before_rowid=first[0]["row_id"], limit=3, db_path=self.db,
        )
        self.assertEqual([m["text"] for m in second], ["m0", "m1"])
        self.assertEqual(len({m["id"] for m in first + second}), 5)
        # before without before_rowid is inclusive, so same-ts rows repeat instead of disappearing
        boundary = inbox.thread_messages(t["id"], before=20.0, limit=10, db_path=self.db)
        self.assertEqual([m["text"] for m in boundary], ["m0", "m1", "m2", "m3"])

    def test_query_treats_like_wildcards_literally(self):
        a = inbox.upsert_thread("qq", "inst1", "pct", "private", "优惠100%", db_path=self.db)
        inbox.add_message(a["id"], "qq", "inst1", "in", "1", "小明", "全场 100% 正品", 1.0, "pct:1",
                          "livingmemory", db_path=self.db)
        inbox.upsert_thread("qq", "inst1", "plain", "private", "普通人", db_path=self.db)
        self.assertEqual([t["display_name"] for t in inbox.list_threads(query="100%", db_path=self.db)], ["优惠100%"])
        self.assertEqual(len(inbox.list_threads(query="%", db_path=self.db)), 1)

    def test_list_threads_resolves_account_name(self):
        a = inbox.upsert_thread("qq", "inst1", "same", "private", "甲", db_path=self.db)
        b = inbox.upsert_thread("qq", "inst2", "same", "private", "乙", db_path=self.db)
        rows = inbox.list_threads(db_path=self.db, instances=[
            {"id": "inst1", "name": "大肥鱼"}, {"id": "inst2", "name": "千问"},
        ])
        names = {row["id"]: row["account_name"] for row in rows}
        self.assertEqual(names[a["id"]], "大肥鱼")
        self.assertEqual(names[b["id"]], "千问")
        # 实例已从 store 删除时退回 account_id，页面不会显示空账号名
        fallback = inbox.list_threads(db_path=self.db, instances=[])
        self.assertEqual({row["account_name"] for row in fallback}, {"inst1", "inst2"})


class LivingMemorySyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        self.lm = str(Path(self.tmp.name) / "conversations.db")
        make_livingmemory(self.lm, [
            ("大肥鱼:FriendMessage:1", "user", "你好", "1", "小明", None, "aiocqhttp", 10),
            ("大肥鱼:FriendMessage:1", "assistant", "在", "bot", "牧鱼", None, "aiocqhttp", 11),
            ("大肥鱼:GroupMessage:9", "user", "群里好", "2", "小红", "9", "aiocqhttp", 12),
            ("mimi-douyin:FriendMessage:p1", "user", "抖音私信", "p1", "抖音用户", None, "douyin_dm", 13),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_qq_sync_dedupe_and_cursor(self):
        inst = {"id": "i1", "root": "D:/x"}
        first = inbox.sync_livingmemory(inst, "qq", self.lm, db_path=self.db)
        self.assertEqual(first["inserted"], 3)
        second = inbox.sync_livingmemory(inst, "qq", self.lm, db_path=self.db)
        self.assertEqual(second["inserted"], 0)
        threads = inbox.list_threads(platform="qq", db_path=self.db)
        self.assertEqual({item["kind"] for item in threads}, {"private", "group"})

    def test_douyin_sync_only_memory_platform(self):
        inst = {"id": "i1", "root": "D:/x"}
        result = inbox.sync_livingmemory(inst, "douyin", self.lm, db_path=self.db)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(inbox.list_threads(platform="douyin", db_path=self.db)[0]["last_text"], "抖音私信")

    def test_same_second_message_is_not_lost(self):
        source = str(Path(self.tmp.name) / "same_second.db")
        make_livingmemory(source, [
            ("大肥鱼:FriendMessage:1", "user", "第一条", "1", "小明", None, "aiocqhttp", 100),
        ])
        inst = {"id": "i1"}
        self.assertEqual(inbox.sync_livingmemory(inst, "qq", source, db_path=self.db)["inserted"], 1)
        conn = sqlite3.connect(source)
        conn.execute("INSERT INTO messages(session_id,role,content,sender_id,sender_name,group_id,platform,timestamp) "
                     "VALUES('大肥鱼:FriendMessage:1','user','同一秒','1','小明',NULL,'aiocqhttp',100)")
        conn.commit(); conn.close()
        self.assertEqual(inbox.sync_livingmemory(inst, "qq", source, db_path=self.db)["inserted"], 1)
        thread = inbox.list_threads(platform="qq", db_path=self.db)[0]
        self.assertEqual([m["text"] for m in inbox.thread_messages(thread["id"], db_path=self.db)],
                         ["第一条", "同一秒"])

    def test_private_display_name_keeps_human_name(self):
        inbox.sync_livingmemory({"id": "i1"}, "qq", self.lm, db_path=self.db)
        names = {t["thread_key"]: t["display_name"] for t in inbox.list_threads(platform="qq", db_path=self.db)}
        self.assertEqual(names["大肥鱼:FriendMessage:1"], "小明")

    def test_private_outbound_only_falls_back_to_peer_segment(self):
        source = str(Path(self.tmp.name) / "outbound_only.db")
        make_livingmemory(source, [
            ("大肥鱼:FriendMessage:77", "assistant", "只有机器人", "bot", "牧鱼", None, "aiocqhttp", 5),
        ])
        inbox.sync_livingmemory({"id": "i1"}, "qq", source, db_path=self.db)
        self.assertEqual(inbox.list_threads(platform="qq", db_path=self.db)[0]["display_name"], "77")

    def test_group_display_name_uses_last_colon_segment(self):
        source = str(Path(self.tmp.name) / "groups.db")
        make_livingmemory(source, [
            ("大肥鱼:GroupMessage:9", "user", "群一", "2", "小红", "9", "aiocqhttp", 20),
            ("大肥鱼:GroupMessage:20001", "user", "群二", "3", "小刚", "大肥鱼:GroupMessage:20001",
             "aiocqhttp", 21),
            ("大肥鱼:GroupMessage:555", "user", "群三", "4", "小美", None, "aiocqhttp", 22),
        ])
        inbox.sync_livingmemory({"id": "i1"}, "qq", source, db_path=self.db)
        names = {t["thread_key"]: t["display_name"] for t in inbox.list_threads(platform="qq", db_path=self.db)}
        self.assertEqual(names["大肥鱼:GroupMessage:9"], "群 9")
        self.assertEqual(names["大肥鱼:GroupMessage:20001"], "群 20001")
        self.assertEqual(names["大肥鱼:GroupMessage:555"], "群 555")


def make_bili_plugin(path):
    path.mkdir(parents=True)
    conn = sqlite3.connect(path / "bilibot.sqlite3")
    conn.execute("""CREATE TABLE events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT, actor_name TEXT,
        content TEXT, created_at REAL, source_type TEXT)""")
    conn.executemany("INSERT INTO events(actor_id,actor_name,content,created_at,source_type) VALUES(?,?,?,?,?)",
                     [("bili:42", "B站用户", "在吗", 20, "dm")])
    conn.commit(); conn.close()
    (path / "reply_log.json").write_text(json.dumps([
        {"time": "2026-11-04 12:00", "mid": "42", "username": "B站用户",
         "content": "在吗", "reply": "在的", "channel": "private"}
    ], ensure_ascii=False), encoding="utf-8")


class BiliSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        self.plugin = Path(self.tmp.name) / "bili"
        make_bili_plugin(self.plugin)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bili_in_and_out_dedupe(self):
        inst = {"id": "i1", "root": "D:/x"}
        first = inbox.sync_bili(inst, self.plugin, db_path=self.db)
        self.assertEqual(first["inserted"], 2)
        second = inbox.sync_bili(inst, self.plugin, db_path=self.db)
        self.assertEqual(second["inserted"], 0)
        thread = inbox.list_threads(platform="bilibili", db_path=self.db)[0]
        self.assertEqual(thread["thread_key"], "bili:42")
        self.assertEqual(thread["last_text"], "在的")

    def test_reply_timestamp_does_not_skip_later_event(self):
        plugin = Path(self.tmp.name) / "future-reply"
        plugin.mkdir()
        source = plugin / "bilibot.sqlite3"
        conn = sqlite3.connect(source)
        conn.execute("""CREATE TABLE events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT, actor_name TEXT,
            content TEXT, created_at REAL, source_type TEXT)""")
        conn.execute("INSERT INTO events(actor_id,actor_name,content,created_at,source_type) "
                     "VALUES('bili:42','B站用户','第一条',100,'dm')")
        conn.commit(); conn.close()
        (plugin / "reply_log.json").write_text(json.dumps([
            {"time": "2027-01-01 00:00", "mid": "42", "username": "B站用户",
             "content": "第一条", "reply": "在的", "channel": "private"}
        ], ensure_ascii=False), encoding="utf-8")
        first = inbox.sync_bili({"id": "i1"}, plugin, db_path=self.db)
        self.assertEqual(first["inserted"], 2)
        # The reply time is far in the future; it must not move the events cursor.
        self.assertEqual(first["cursor"], 100.0)
        conn = sqlite3.connect(source)
        conn.execute("INSERT INTO events(actor_id,actor_name,content,created_at,source_type) "
                     "VALUES('bili:42','B站用户','第二条',200,'dm')")
        conn.commit(); conn.close()
        second = inbox.sync_bili({"id": "i1"}, plugin, db_path=self.db)
        self.assertEqual(second["inserted"], 1)
        thread = inbox.list_threads(platform="bilibili", db_path=self.db)[0]
        messages = inbox.thread_messages(thread["id"], db_path=self.db)
        self.assertEqual([(m["direction"], m["text"]) for m in messages],
                         [("in", "第一条"), ("in", "第二条"), ("out", "在的")])

    def test_non_dict_reply_log_entries_are_skipped(self):
        plugin = Path(self.tmp.name) / "odd-log"
        plugin.mkdir()
        (plugin / "reply_log.json").write_text(json.dumps(
            [None, "oops", ["nested"], {"channel": "private"}, {"channel": "comment", "mid": "42"}],
            ensure_ascii=False), encoding="utf-8")
        result = inbox.sync_bili({"id": "i1"}, plugin, db_path=self.db)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["scanned"], 1)  # only the private-channel dict reaches row validation


def make_real_bili_plugin(path):
    """Fixture with the plugin's real events schema (core/storage/schema.sql).

    Real inbound DMs are written with `source_type='private'` and every NOT NULL
    column populated; comment events share the table and must be ignored.
    """
    path.mkdir(parents=True)
    conn = sqlite3.connect(path / "bilibot.sqlite3")
    conn.execute("""CREATE TABLE events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id TEXT NOT NULL, source_type TEXT NOT NULL,
        source_event_id TEXT NOT NULL, actor_id TEXT NOT NULL,
        actor_name TEXT NOT NULL DEFAULT '', session_id TEXT NOT NULL,
        target_id TEXT NOT NULL DEFAULT '', thread_id TEXT NOT NULL DEFAULT '',
        priority INTEGER NOT NULL DEFAULT 50, ignore_level TEXT NOT NULL DEFAULT 'normal',
        state TEXT NOT NULL DEFAULT 'received', content TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}',
        attempts INTEGER NOT NULL DEFAULT 0, draft TEXT NOT NULL DEFAULT '',
        send_fingerprint TEXT NOT NULL DEFAULT '', verify_state TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
        updated_at REAL NOT NULL, claimed_at REAL, sent_at REAL,
        UNIQUE (account_id, source_type, source_event_id))""")
    conn.executemany(
        "INSERT INTO events(account_id,source_type,source_event_id,actor_id,actor_name,"
        "session_id,content,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        [
            ("30001", "comment", "40002", "bili:30003", "评论用户",
             "30001!bili_comment!40001", "视频评论", 1793498072.0, 1793498072.0),
            ("30001", "private", "40003", "bili:30002", "UID 30002",
             "30001!bili_dm!private:30002", "在吗", 1793281465.0, 1793281465.0),
        ],
    )
    conn.commit(); conn.close()


class BiliRealSchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        self.plugin = Path(self.tmp.name) / "bili-real"
        make_real_bili_plugin(self.plugin)

    def tearDown(self):
        self.tmp.cleanup()

    def test_private_source_type_inbound_is_collected(self):
        result = inbox.sync_bili({"id": "i1"}, self.plugin, db_path=self.db)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["cursor"], 1793281465.0)
        thread = inbox.list_threads(platform="bilibili", db_path=self.db)[0]
        self.assertEqual(thread["thread_key"], "bili:30002")
        self.assertEqual(thread["display_name"], "UID 30002")
        messages = inbox.thread_messages(thread["id"], db_path=self.db)
        self.assertEqual([(m["direction"], m["sender_id"], m["text"], m["source"]) for m in messages],
                         [("in", "30002", "在吗", "bili_events")])


class InboxSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        self.root = Path(self.tmp.name) / "AstrBot"
        lm = self.root / "data" / "plugin_data" / "astrbot_plugin_livingmemory"
        lm.mkdir(parents=True)
        make_livingmemory(lm / "conversations.db", [
            ("大肥鱼:FriendMessage:1", "user", "你好", "1", "小明", None, "aiocqhttp", 10),
        ])
        self.inst = {"id": "i1", "name": "大肥鱼", "root": str(self.root), "platform_id": "大肥鱼"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingest_maps_platform_id(self):
        result = inbox.ingest_message({
            "platform": "qq", "platform_id": "大肥鱼",
            "thread_key": "大肥鱼:FriendMessage:1", "kind": "private",
            "sender_id": "1", "sender_name": "小明", "text": "插件上报",
            "ts": 20, "external_id": "plugin:1",
        }, db_path=self.db, instances=[self.inst])
        self.assertEqual(result["thread"]["display_name"], "小明")
        self.assertEqual(result["message"]["text"], "插件上报")

    def test_takeover_pushes_plugin(self):
        thread = inbox.upsert_thread("qq", "i1", "大肥鱼:FriendMessage:1", "private", "小明", db_path=self.db)
        calls = []
        result = inbox.set_takeover(thread["id"], True, db_path=self.db,
                                    instances=[self.inst],
                                    call=lambda inst, method, path, payload, timeout=30: calls.append((path, payload)) or {"status": "ok", "data": {}})
        self.assertTrue(result["thread"]["takeover"])
        self.assertIn(("plugins/extensions/astrbot_plugin_fleet_inbox/takeover",
                       {"umos": ["大肥鱼:FriendMessage:1"], "account_id": "i1"}), calls)

    def test_group_ingest_uses_group_label_not_sender(self):
        result = inbox.ingest_message({
            "platform": "qq", "platform_id": "大肥鱼",
            "thread_key": "大肥鱼:GroupMessage:20001", "kind": "group",
            "sender_id": "2", "sender_name": "小红", "text": "群里好",
            "ts": 30, "external_id": "plugin:group:1",
        }, db_path=self.db, instances=[self.inst])
        self.assertEqual(result["thread"]["kind"], "group")
        self.assertEqual(result["thread"]["display_name"], "群 20001")

    def test_takeover_requires_existing_instance(self):
        thread = inbox.upsert_thread("qq", "ghost", "大肥鱼:FriendMessage:9", "private", "小明",
                                     db_path=self.db)
        with self.assertRaisesRegex(inbox.InboxError, "实例不存在"):
            inbox.set_takeover(thread["id"], True, db_path=self.db, instances=[self.inst],
                               call=lambda *args, **kwargs: self.fail("插件不应被调用"))
        # 未推送插件就不落库，避免 UI 显示一个假的暂停
        self.assertFalse(inbox.get_thread(thread["id"], db_path=self.db)["takeover"])

    def test_non_numeric_ts_raises_inbox_error(self):
        with self.assertRaisesRegex(inbox.InboxError, "ts 无效"):
            inbox.ingest_message({
                "platform": "qq", "platform_id": "大肥鱼",
                "thread_key": "大肥鱼:FriendMessage:1", "kind": "private",
                "sender_id": "1", "sender_name": "小明", "text": "坏时间",
                "ts": "昨天", "external_id": "plugin:bad-ts",
            }, db_path=self.db, instances=[self.inst])
        self.assertEqual(inbox.list_threads(db_path=self.db), [])

    def test_blank_platform_id_matches_no_instance(self):
        inst = {"id": "i2", "name": "未配置平台", "root": str(self.root), "platform_id": ""}
        for blank in ("", "  "):
            with self.assertRaisesRegex(inbox.InboxError, "platform_id 缺失"):
                inbox.ingest_message({
                    "platform": "qq", "platform_id": blank,
                    "thread_key": "大肥鱼:FriendMessage:1", "kind": "private",
                    "sender_id": "1", "sender_name": "小明", "text": "没有平台",
                    "ts": 20, "external_id": f"plugin:blank:{len(blank)}",
                }, db_path=self.db, instances=[inst])
        self.assertEqual(inbox.list_threads(db_path=self.db), [])

    def test_sync_instance_empty_root_does_not_scan_cwd(self):
        cwd = Path(self.tmp.name) / "cwd"
        lm = cwd / "data" / "plugin_data" / "astrbot_plugin_livingmemory"
        lm.mkdir(parents=True)
        make_livingmemory(lm / "conversations.db", [
            ("大肥鱼:FriendMessage:1", "user", "工作目录里的库", "1", "小明", None, "aiocqhttp", 10),
        ])
        previous = os.getcwd()
        os.chdir(cwd)
        try:
            result = inbox.sync_instance({"id": "i3", "root": ""}, db_path=self.db)
        finally:
            os.chdir(previous)
        self.assertEqual(result["instance_id"], "i3")
        self.assertEqual([source["source"] for source in result["sources"]], ["root:i3"])
        self.assertIn("error", result["sources"][0])
        self.assertEqual(inbox.list_threads(db_path=self.db), [])

    def test_sync_takeover_unknown_platform_is_reported(self):
        calls = []
        result = inbox.sync_takeover(self.inst, "wechat", db_path=self.db,
                                     call=lambda *args, **kwargs: calls.append(args))
        self.assertEqual(result, [{"platform": "wechat", "ok": False, "error": "平台无效", "keys": []}])
        self.assertEqual(calls, [])

    def test_sync_takeover_plugin_error_body_is_failure(self):
        # AstrBot 路由缺失时仍回 HTTP 200 + {"status":"error"}，不能记成接管成功
        thread = inbox.upsert_thread("qq", "i1", "大肥鱼:FriendMessage:1", "private", "小明", db_path=self.db)
        inbox.set_takeover(thread["id"], True, db_path=self.db, instances=[self.inst],
                           call=lambda *a, **k: {"status": "ok", "data": {}})
        result = inbox.sync_takeover(
            self.inst, "qq", db_path=self.db,
            call=lambda *a, **k: {"status": "error", "message": "未找到该路由"},
        )
        self.assertEqual(result[0]["platform"], "qq")
        self.assertFalse(result[0]["ok"])
        self.assertEqual(result[0]["error"], "未找到该路由")
        self.assertEqual(result[0]["keys"], ["大肥鱼:FriendMessage:1"])
        # 嵌套 data.status=error 同样是失败
        nested = inbox.sync_takeover(
            self.inst, "qq", db_path=self.db,
            call=lambda *a, **k: {"status": "ok", "data": {"status": "error", "message": "接管未开启"}},
        )
        self.assertFalse(nested[0]["ok"])
        self.assertEqual(nested[0]["error"], "接管未开启")
        # 无 message 的 error 体给默认文案
        blank = inbox.sync_takeover(
            self.inst, "qq", db_path=self.db, call=lambda *a, **k: {"status": "error"},
        )
        self.assertEqual(blank[0]["error"], "插件拒绝接管")

    def test_set_takeover_rolls_back_when_plugin_rejects(self):
        thread = inbox.upsert_thread("qq", "i1", "大肥鱼:FriendMessage:1", "private", "小明", db_path=self.db)
        with self.assertRaisesRegex(inbox.InboxError, "插件未确认接管：qq: 未找到该路由"):
            inbox.set_takeover(thread["id"], True, db_path=self.db, instances=[self.inst],
                               call=lambda *a, **k: {"status": "error", "message": "未找到该路由"})
        self.assertFalse(inbox.get_thread(thread["id"], db_path=self.db)["takeover"])

        # 关闭接管被拒时同样回滚：保持原来的 takeover=1，UI 不会谎报已恢复自动回复
        inbox.set_takeover(thread["id"], True, db_path=self.db, instances=[self.inst],
                           call=lambda *a, **k: {"status": "ok", "data": {}})
        with self.assertRaisesRegex(inbox.InboxError, "插件未确认接管"):
            inbox.set_takeover(thread["id"], False, db_path=self.db, instances=[self.inst],
                               call=lambda *a, **k: {"status": "error", "message": "未找到该路由"})
        self.assertTrue(inbox.get_thread(thread["id"], db_path=self.db)["takeover"])

    def test_push_all_takeovers_logs_plugin_failure_once_per_error(self):
        inbox._push_failures.clear()
        self.addCleanup(inbox._push_failures.clear)

        def down(*args, **kwargs):
            raise RuntimeError("plugin down")

        def events():
            conn = sqlite3.connect(self.db)
            try:
                return conn.execute(
                    "SELECT source, severity, title, ref, detail_json FROM events WHERE kind='inbox' ORDER BY id"
                ).fetchall()
            finally:
                conn.close()

        results = inbox.push_all_takeovers(instances=[self.inst], db_path=self.db, call=down)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(not item["ok"] for item in results))
        rows = events()
        self.assertEqual(len(rows), 3)
        self.assertEqual({row[0] for row in rows}, {"manager"})
        self.assertEqual({row[1] for row in rows}, {"warn"})
        self.assertEqual({row[2] for row in rows}, {"收件箱接管推送失败"})
        self.assertEqual({row[3] for row in rows}, {"i1"})
        self.assertEqual({json.loads(row[4])["platform"] for row in rows}, {"qq", "bilibili", "douyin"})
        self.assertEqual(json.loads(rows[0][4])["error"], "plugin down")

        # 同一失败不重复刷事件；错误变化时重新记录
        inbox.push_all_takeovers(instances=[self.inst], db_path=self.db, call=down)
        self.assertEqual(len(events()), 3)
        inbox.push_all_takeovers(
            instances=[self.inst], db_path=self.db,
            call=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("another error")),
        )
        self.assertEqual(len(events()), 6)
        # 恢复成功后清掉去重状态，下一次故障会重新留痕
        inbox.push_all_takeovers(
            instances=[self.inst], db_path=self.db,
            call=lambda *a, **k: {"status": "ok", "data": {}},
        )
        inbox.push_all_takeovers(instances=[self.inst], db_path=self.db, call=down)
        self.assertEqual(len(events()), 9)

    def test_takeover_pushes_are_serialized(self):
        # 后台 push_all 持锁推送时 set_takeover 必须等待，最后一次 qq 推送要带新开启的会话
        thread = inbox.upsert_thread("qq", "i1", "大肥鱼:FriendMessage:1", "private", "小明", db_path=self.db)
        calls = []
        started = threading.Event()
        release = threading.Event()

        def push_call(inst, method, path, payload, timeout=15):
            calls.append(("push", path, list(payload.get("umos") or [])))
            if not release.is_set():
                started.set()
                release.wait(5)
            return {"status": "ok", "data": {}}

        def set_call(inst, method, path, payload, timeout=15):
            calls.append(("set", path, list(payload.get("umos") or [])))
            return {"status": "ok", "data": {}}

        worker = threading.Thread(
            target=inbox.push_all_takeovers,
            kwargs={"instances": [self.inst], "db_path": self.db, "call": push_call},
        )
        setter = threading.Thread(
            target=inbox.set_takeover,
            args=(thread["id"], True),
            kwargs={"db_path": self.db, "instances": [self.inst], "call": set_call},
        )
        worker.start()
        try:
            self.assertTrue(started.wait(5), "push_all must reach the plugin")
            setter.start()
            time.sleep(0.1)
            self.assertTrue(setter.is_alive(), "set_takeover must wait for the in-flight push")
            self.assertEqual([kind for kind, _path, _keys in calls if kind == "set"], [])
            release.set()
            setter.join(5)
            worker.join(5)
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(setter.is_alive())
        umos_pushes = [(kind, keys) for kind, path, keys in calls if path.endswith("fleet_inbox/takeover")]
        self.assertEqual(umos_pushes[0], ("push", []))
        self.assertEqual(umos_pushes[-1], ("set", ["大肥鱼:FriendMessage:1"]))
        self.assertTrue(inbox.get_thread(thread["id"], db_path=self.db)["takeover"])


class InboxSendTest(unittest.TestCase):
    """Manual send: confirm/takeover/text guards, per-platform payloads, no retry."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")
        self.inst = {"id": "i1", "platform_id": "大肥鱼", "root": "D:/x"}
        self.thread = inbox.upsert_thread("qq", "i1", "大肥鱼:FriendMessage:1", "private", "小明", db_path=self.db)
        inbox.set_takeover(self.thread["id"], True, db_path=self.db, instances=[self.inst],
                           call=lambda *a, **k: {"status": "ok", "data": {}})

    def tearDown(self):
        self.tmp.cleanup()

    def _events(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "SELECT source, severity, title, ref, detail_json FROM events WHERE kind='inbox' ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

    def test_requires_takeover_and_confirm(self):
        with self.assertRaises(inbox.InboxError):
            inbox.send_message(self.thread["id"], "你好", "nope", db_path=self.db, instances=[self.inst])
        inbox.set_takeover(self.thread["id"], False, db_path=self.db, instances=[self.inst],
                           call=lambda *a, **k: {"status": "ok", "data": {}})
        with self.assertRaises(inbox.InboxError):
            inbox.send_message(self.thread["id"], "你好", "SEND", db_path=self.db, instances=[self.inst])

    def test_qq_send_records_outbound(self):
        calls = []
        def fake(inst, method, path, payload, timeout=30):
            calls.append((path, payload))
            return {"status": "ok", "data": {}}
        result = inbox.send_message(self.thread["id"], "你好", "SEND", db_path=self.db,
                                    instances=[self.inst], call=fake)
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0], "im/messages")
        self.assertEqual(calls[0][1]["umo"], self.thread["thread_key"])
        self.assertEqual(calls[0][1]["message"], [{"type": "plain", "text": "你好"}])
        messages = inbox.thread_messages(self.thread["id"], db_path=self.db)
        self.assertEqual(messages[-1]["direction"], "out")

    def test_bili_send_strips_prefix(self):
        thread = inbox.upsert_thread("bilibili", "i1", "bili:42", "private", "B站用户", db_path=self.db)
        inbox.set_takeover(thread["id"], True, db_path=self.db, instances=[self.inst],
                           call=lambda *a, **k: {"status": "ok", "data": {}})
        calls = []
        result = inbox.send_message(
            thread["id"], "在的", "SEND", db_path=self.db, instances=[self.inst],
            call=lambda inst, method, path, payload, timeout=30:
            calls.append((inst, method, path, payload, timeout)) or {"status": "ok", "data": {}},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0]["id"], "i1")
        self.assertEqual(calls[0][1], "POST")
        self.assertEqual(calls[0][2], "plugins/extensions/astrbot_plugin_bilibili_ai_bot/inbox/send")
        self.assertEqual(calls[0][3], {"mid": "42", "text": "在的"})
        self.assertEqual(calls[0][4], 30)
        last = inbox.thread_messages(thread["id"], db_path=self.db)[-1]
        self.assertEqual((last["direction"], last["source"], last["sender_name"], last["text"]),
                         ("out", "manager_send", "牧鱼", "在的"))

    def test_douyin_send_uses_peer_segment_and_name(self):
        thread = inbox.upsert_thread("douyin", "i1", "mimi-douyin:FriendMessage:peer_9", "private",
                                     "抖音用户", db_path=self.db)
        inbox.set_takeover(thread["id"], True, db_path=self.db, instances=[self.inst],
                           call=lambda *a, **k: {"status": "ok", "data": {}})
        calls = []
        inbox.send_message(
            thread["id"], "在的", "SEND", db_path=self.db, instances=[self.inst],
            call=lambda inst, method, path, payload, timeout=30:
            calls.append((path, payload)) or {"status": "ok", "data": {}},
        )
        self.assertEqual(calls[0][0], "plugins/extensions/astrbot_plugin_douyin_dm/inbox/send")
        self.assertEqual(calls[0][1], {"peer_key": "peer_9", "name": "抖音用户", "text": "在的"})

    def test_failure_raises_without_outbound_or_retry(self):
        paths = []
        def boom(inst, method, path, payload, timeout=30):
            paths.append(path)
            raise RuntimeError("plugin down")
        with self.assertRaisesRegex(inbox.InboxError, "发送失败：plugin down"):
            inbox.send_message(self.thread["id"], "你好", "SEND", db_path=self.db,
                               instances=[self.inst], call=boom)
        self.assertEqual(paths, ["im/messages"])  # one attempt only, no retry
        self.assertEqual(inbox.thread_messages(self.thread["id"], db_path=self.db), [])
        self.assertEqual([row[1] for row in self._events()], ["warn"])

    def test_plugin_error_body_is_failure(self):
        # 插件 HTTP 200 + {"status":"error"} 属于拒发，不能记成成功发送
        with self.assertRaisesRegex(inbox.InboxError, "发送失败：接管未开启"):
            inbox.send_message(
                self.thread["id"], "你好", "SEND", db_path=self.db, instances=[self.inst],
                call=lambda *a, **k: {"status": "error", "message": "接管未开启"},
            )
        self.assertEqual(inbox.thread_messages(self.thread["id"], db_path=self.db), [])
        rows = self._events()
        self.assertEqual([row[1] for row in rows], ["warn"])
        detail = json.loads(rows[0][4])
        self.assertEqual((detail["thread_id"], detail["platform"], detail["account_id"]),
                         (self.thread["id"], "qq", "i1"))
        self.assertEqual(detail["error"], "接管未开启")
        # 没有 message 的 error 体用默认文案，且大小写不敏感
        with self.assertRaisesRegex(inbox.InboxError, "发送失败：插件拒绝发送"):
            inbox.send_message(self.thread["id"], "你好", "SEND", db_path=self.db,
                               instances=[self.inst], call=lambda *a, **k: {"status": "ERROR"})
        self.assertEqual(inbox.thread_messages(self.thread["id"], db_path=self.db), [])
        self.assertEqual([row[1] for row in self._events()], ["warn", "warn"])
        # 失败事件只留 200 字错误摘要
        with self.assertRaises(inbox.InboxError):
            inbox.send_message(
                self.thread["id"], "你好", "SEND", db_path=self.db, instances=[self.inst],
                call=lambda *a, **k: {"status": "error", "message": "错" * 260},
            )
        self.assertEqual(len(json.loads(self._events()[-1][4])["error"]), 200)

    def test_clean_text_strips_control_chars(self):
        calls = []
        result = inbox.send_message(
            self.thread["id"], "你\t好\x00 \x1b世\x7f界", "SEND", db_path=self.db, instances=[self.inst],
            call=lambda inst, method, path, payload, timeout=30:
            calls.append(payload) or {"status": "ok", "data": {}},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0]["message"], [{"type": "plain", "text": "你好 世界"}])
        self.assertEqual(inbox.thread_messages(self.thread["id"], db_path=self.db)[-1]["text"], "你好 世界")

    def test_text_guards(self):
        def fail_call(*args, **kwargs):
            self.fail("校验失败时不应调用平台")
        for bad in ("", "   ", "\r\n\t ", None):
            with self.assertRaisesRegex(inbox.InboxError, "发送内容为空"):
                inbox.send_message(self.thread["id"], bad, "SEND", db_path=self.db,
                                   instances=[self.inst], call=fail_call)
        with self.assertRaisesRegex(inbox.InboxError, "500"):
            inbox.send_message(self.thread["id"], "长" * 501, "SEND", db_path=self.db,
                               instances=[self.inst], call=fail_call)
        calls = []
        result = inbox.send_message(
            self.thread["id"], "第一行\n第二行\r", "SEND", db_path=self.db, instances=[self.inst],
            call=lambda inst, method, path, payload, timeout=30:
            calls.append(payload) or {"status": "ok", "data": {}},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0]["message"], [{"type": "plain", "text": "第一行 第二行"}])
        self.assertEqual(inbox.thread_messages(self.thread["id"], db_path=self.db)[-1]["text"], "第一行 第二行")
        self.assertTrue(inbox.send_message(self.thread["id"], "长" * 500, "SEND", db_path=self.db,
                                           instances=[self.inst],
                                           call=lambda *a, **k: {"status": "ok", "data": {}})["ok"])

    def test_requires_existing_thread_and_instance(self):
        def fail_call(*args, **kwargs):
            self.fail("发送失败前不应调用平台")
        with self.assertRaisesRegex(inbox.InboxError, "会话不存在"):
            inbox.send_message("in_missing", "你好", "SEND", db_path=self.db,
                               instances=[self.inst], call=fail_call)
        ghost = inbox.upsert_thread("qq", "ghost", "大肥鱼:FriendMessage:9", "private", "小明",
                                    db_path=self.db)
        # set_takeover needs a real instance, so flip the flag directly to reach the instance guard
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE inbox_threads SET takeover=1 WHERE id=?", (ghost["id"],))
        conn.commit(); conn.close()
        with self.assertRaisesRegex(inbox.InboxError, "实例不存在"):
            inbox.send_message(ghost["id"], "你好", "SEND", db_path=self.db,
                               instances=[self.inst], call=fail_call)
        self.assertEqual(inbox.thread_messages(ghost["id"], db_path=self.db), [])

    def test_success_writes_info_event(self):
        inbox.send_message(self.thread["id"], "你好", "SEND", db_path=self.db, instances=[self.inst],
                           call=lambda *a, **k: {"status": "ok", "data": {}})
        rows = self._events()
        self.assertEqual([(row[0], row[1], row[2]) for row in rows],
                         [("manager", "info", "收件箱人工发送")])
        self.assertEqual(rows[0][3], self.thread["id"])
        detail = json.loads(rows[0][4])
        self.assertEqual((detail["thread_id"], detail["platform"], detail["account_id"], detail["chars"]),
                         (self.thread["id"], "qq", "i1", 2))
        self.assertEqual(detail["text"], "你好")


class InboxApiTest(unittest.TestCase):
    """Manager HTTP surface: routes exist and status never triggers a sync."""

    def test_api_routes_exist(self):
        from server import api
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in (
            "/api/inbox/status",
            "/api/inbox/threads",
            "/api/inbox/threads/{thread_id}/messages",
            "/api/inbox/threads/{thread_id}/read",
            "/api/inbox/threads/{thread_id}/takeover",
            "/api/inbox/threads/{thread_id}/send",
            "/api/inbox/sync",
            "/api/inbox/ingest",
        ):
            self.assertIn(path, paths)

    def test_status_is_cached_and_never_syncs(self):
        from server import api
        calls = []

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return []

        with mock.patch.object(inbox, "sync_all", spy), mock.patch.object(inbox, "sync_once", spy):
            snapshot = inbox.status()
            response = api.inbox_status()
        self.assertEqual(calls, [])
        self.assertEqual(response["status"], "ok")
        self.assertEqual(set(response["data"]), {"last_sync", "sources", "syncing", "error"})
        self.assertEqual(response["data"], snapshot)
        # 每次 status() 都返回副本，调用方改不动缓存
        self.assertIsNot(snapshot, inbox.status())

    def test_sync_once_skips_while_another_sync_is_running(self):
        with mock.patch.object(inbox, "sync_all") as sync_all, \
                mock.patch.object(inbox, "push_all_takeovers") as push:
            inbox._sync_lock.acquire()
            try:
                result = inbox.sync_once(instances=[])
            finally:
                inbox._sync_lock.release()
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "同步正在进行")
        sync_all.assert_not_called()
        push.assert_not_called()

    def test_takeover_endpoint_only_treats_boolean_true_as_enabled(self):
        from server import api
        seen = []

        def fake_set(thread_id, enabled, instances=None):
            seen.append((thread_id, enabled))
            return {"thread": {}, "sync": []}

        with mock.patch.object(inbox, "set_takeover", fake_set), \
                mock.patch.object(api, "_instances", lambda: []):
            for value in (True, "true", "false", "0", 1, None, []):
                response = api.inbox_takeover("in_x", {"enabled": value})
                self.assertEqual(response["status"], "ok")
        # 只有布尔 True 开启接管；字符串 "false"/"0" 和 1 都不能开启
        self.assertEqual([enabled for _thread, enabled in seen], [True, False, False, False, False, False, False])
        self.assertEqual({thread for thread, _enabled in seen}, {"in_x"})


if __name__ == "__main__":
    unittest.main()
