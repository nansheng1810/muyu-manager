import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from server import approvals, fleet_store


class ApprovalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "fleet_ops.sqlite3"
        self.patch = mock.patch.object(fleet_store, "DB_PATH", self.db)
        self.patch.start()
        fleet_store._initialized.clear()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_create_list_and_counts(self):
        item = approvals.create("bili_write", "点赞视频", target="BV1xx", payload={"action": "like"})
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["payload"]["action"], "like")
        self.assertEqual(approvals.summary()["pending"], 1)
        self.assertEqual(len(approvals.list_items("pending")), 1)

    def test_approve_then_list(self):
        item = approvals.create("douyin_write", "评论作品", target="https://v.douyin.com/x/")
        result = approvals.approve(item["id"], decided_by="owner")
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["decided_by"], "owner")
        self.assertEqual(approvals.list_items("pending"), [])
        self.assertEqual(approvals.summary()["pending"], 0)

    def test_deny(self):
        item = approvals.create("bili_write", "收藏视频")
        result = approvals.deny(item["id"], decided_by="owner", reason="不想收藏")
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["decision"], "不想收藏")

    def test_expired_cannot_be_approved(self):
        item = approvals.create("bili_write", "投币", ttl=60)
        with fleet_store.session() as conn:
            conn.execute("UPDATE approvals SET expires_at=? WHERE id=?", (time.time() - 1, item["id"]))
        self.assertEqual(approvals.get(item["id"])["status"], "expired")
        result = approvals.approve(item["id"])
        self.assertEqual(result["status"], "expired")

    def test_request_and_wait_returns_after_approval(self):
        result = {}

        def worker():
            time.sleep(0.6)
            pending = approvals.list_items("pending")
            approvals.approve(pending[0]["id"], decided_by="owner")

        thread = threading.Thread(target=worker)
        thread.start()
        result = approvals.request_and_wait(
            "douyin_write", "关注作者", target="作者A", timeout=5,
        )
        thread.join()
        self.assertEqual(result["status"], "approved")

    def test_request_and_wait_timeout_is_pending(self):
        result = approvals.request_and_wait("bili_write", "评论视频", timeout=1)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(result.get("timeout"))
        self.assertEqual(approvals.summary()["pending"], 1)


if __name__ == "__main__":
    unittest.main()
