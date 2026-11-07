import unittest

from server import alerts


def health_with(status="ok"):
    return {
        "overall": status,
        "components": [
            {"id": "manager", "label": "管理器", "status": "ok", "summary": "ok", "route": ""},
            {"id": "dsh", "label": "DSH", "status": status, "summary": "未运行", "route": "#/dsh"},
        ],
    }


class AlertsTest(unittest.TestCase):
    def test_healthy_fleet_has_no_alerts(self):
        now = 100000.0
        result = alerts.build(
            health_with("ok"),
            [],
            [],
            {},
            [{"name": "recent.zip", "created": now - 3600}],
            now=now,
        )
        self.assertEqual(result["overall"], "ok")
        self.assertEqual(result["alerts"], [])

    def test_health_and_stale_approval(self):
        now = 100000.0
        result = alerts.build(
            health_with("bad"),
            [{"id": "ap1", "status": "pending", "created": now - 2000, "title": "写操作", "target": "B站"}],
            [],
            {},
            [{"name": "recent.zip", "created": now - 3600}],
            now=now,
        )
        self.assertEqual(result["counts"]["critical"], 2)
        titles = [item["title"] for item in result["alerts"]]
        self.assertTrue(any("DSH" in title for title in titles))
        self.assertTrue(any("审批等待" in title for title in titles))

    def test_recent_approval_is_not_alerted(self):
        now = 100000.0
        result = alerts.build(
            health_with("ok"),
            [{"id": "ap1", "status": "pending", "created": now - 60, "title": "刚创建"}],
            [],
            {},
            [{"name": "recent.zip", "created": now - 3600}],
            now=now,
        )
        self.assertEqual(result["alerts"], [])

    def test_failed_task_and_missing_backup(self):
        now = 100000.0
        result = alerts.build(
            health_with("ok"),
            [],
            [{"task_id": "t1", "started": now - 100, "status": "failed", "summary": "boom"}],
            {"t1": "每日备份"},
            [],
            now=now,
        )
        kinds = {item["kind"] for item in result["alerts"]}
        self.assertEqual(kinds, {"task", "backup"})
        self.assertIn("每日备份", result["alerts"][0]["title"])

    def test_old_task_failure_is_ignored(self):
        now = 100000.0
        result = alerts.build(
            health_with("ok"),
            [],
            [{"task_id": "t1", "started": now - 90000, "status": "failed", "summary": "old"}],
            {"t1": "旧任务"},
            [{"name": "recent.zip", "created": now - 3600}],
            now=now,
        )
        self.assertEqual(result["alerts"], [])

    def test_stale_backup_is_alerted(self):
        now = 100000.0
        result = alerts.build(
            health_with("ok"), [], [], {},
            [{"name": "old.zip", "created": now - 72 * 3600}],
            now=now,
        )
        self.assertEqual(result["overall"], "warning")
        self.assertIn("备份", result["alerts"][0]["title"])


if __name__ == "__main__":
    unittest.main()
