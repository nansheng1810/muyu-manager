import time
import unittest

from server import health


class FleetHealthTests(unittest.TestCase):
    def setUp(self):
        health.reset_cache()

    def test_bili_stats_accepts_flat_plugin_payload(self):
        payload = {
            "running": True,
            "account_connected": True,
            "failed_today": 0,
            "private_replies_today": 2,
            "warnings": [],
        }
        stats = health.bili_stats(payload)
        self.assertTrue(stats["account_connected"])
        level, summary, detail = health.bili_health(stats)
        self.assertEqual(level, "ok")
        self.assertIn("B站已连接", summary)
        self.assertEqual(detail["private_replies_today"], 2)

    def test_bili_stats_accepts_nested_payload(self):
        payload = {"stats": {"running": True, "account_connected": True}}
        stats = health.bili_stats(payload)
        self.assertTrue(stats["account_connected"])

    def test_bili_stats_handles_missing_payload(self):
        self.assertEqual(health.bili_stats(None), {})
        self.assertEqual(health.bili_stats({}), {})

    def test_bili_health_ignores_success_warning(self):
        stats = {
            "account_connected": True,
            "running": True,
            "warnings": [
                {"level": "success", "title": "未发现重大问题", "detail": "一切正常"},
            ],
        }
        level, summary, detail = health.bili_health(stats)
        self.assertEqual(level, "ok")
        self.assertIn("B站已连接", summary)
        self.assertEqual(detail["warnings"], 0)

    def test_overall_status_uses_worst_component(self):
        self.assertEqual(
            health.overall_status(
                [
                    health.component("a", "A", "ok", "fine"),
                    health.component("b", "B", "warn", "degraded"),
                ]
            ),
            "warn",
        )
        self.assertEqual(
            health.overall_status(
                [
                    health.component("a", "A", "ok", "fine"),
                    health.component("b", "B", "bad", "down"),
                ]
            ),
            "bad",
        )

    def test_collect_health_flattens_checks(self):
        checks = [
            ("manager", lambda: health.component("manager", "管理器", "ok", "ready")),
            (
                "instances",
                lambda: [
                    health.component("astrbot:a", "AstrBot A", "ok", "ready"),
                    health.component("napcat:a", "NapCat A", "warn", "未登录"),
                ],
            ),
        ]
        data = health.collect_health(checks=checks, force=True)
        self.assertEqual(data["overall"], "warn")
        self.assertEqual(
            [row["id"] for row in data["components"]],
            ["manager", "astrbot:a", "napcat:a"],
        )
        self.assertEqual(data["cache_seconds"], health.HEALTH_CACHE_SECONDS)

    def test_check_exception_becomes_bad_component(self):
        def broken():
            raise RuntimeError("probe exploded")

        data = health.collect_health(checks=[("broken", broken)], force=True)
        self.assertEqual(data["overall"], "bad")
        self.assertEqual(data["components"][0]["id"], "broken")
        self.assertIn("probe exploded", data["components"][0]["summary"])

    def test_check_timeout_becomes_bad_component(self):
        def slow():
            time.sleep(0.2)

        started = time.monotonic()
        data = health.collect_health(
            checks=[("slow", slow)], force=True, timeout=0.05
        )
        self.assertLess(time.monotonic() - started, 0.18)
        self.assertEqual(data["overall"], "bad")
        self.assertEqual(data["components"][0]["status"], "bad")
        self.assertIn("超时", data["components"][0]["summary"])

    def test_douyin_health_states(self):
        level, summary, detail = health.douyin_health({})
        self.assertEqual(level, "warn")
        self.assertIn("未绑定", summary)
        self.assertEqual(detail["private_whitelist"], 0)

        level, summary, detail = health.douyin_health({
            "binding": {"peer": {"name": "中国驰风车队"}},
            "auto_reply_enabled": True,
            "browser_running": True,
            "state": "listening",
            "private_whitelist": ["key"],
        })
        self.assertEqual(level, "ok")
        self.assertIn("监听中", summary)
        self.assertEqual(detail["binding_peer"], "中国驰风车队")

        level, summary, _ = health.douyin_health({
            "binding": {"peer": {"name": "A"}},
            "auto_reply_enabled": True,
            "browser_running": False,
        })
        self.assertEqual(level, "warn")
        self.assertIn("浏览器未运行", summary)

    def test_bili_health_states(self):
        level, summary, _ = health.bili_health({"account_connected": False, "running": False})
        self.assertEqual(level, "bad")
        self.assertIn("未连接", summary)
        level, summary, detail = health.bili_health({
            "account_connected": True, "running": True, "private_replies_today": 3,
        })
        self.assertEqual(level, "ok")
        self.assertIn("私信回复 3", summary)
        self.assertEqual(detail["private_replies_today"], 3)

    def test_cache_reuses_snapshot_until_forced(self):
        calls = {"count": 0}

        def check():
            calls["count"] += 1
            return health.component("manager", "管理器", "ok", "ready")

        first = health.collect_health(checks=[("manager", check)])
        second = health.collect_health(checks=[("manager", check)])
        self.assertEqual(calls["count"], 1)
        self.assertEqual(first["generated_at"], second["generated_at"])
        health.collect_health(checks=[("manager", check)], force=True)
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
