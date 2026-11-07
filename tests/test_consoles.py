import threading
import unittest

from server import consoles
from server.dashboard import DashboardError


class ConsoleProxyTests(unittest.TestCase):
    def setUp(self):
        consoles.run_locks.clear()

    def test_normalize_ok_and_error(self):
        self.assertEqual(
            consoles.normalize("douyin", {"status": "ok", "data": {"proactive": {"used_today": 1}}}),
            {"proactive": {"used_today": 1}},
        )
        with self.assertRaises(consoles.ConsoleError) as ctx:
            consoles.normalize("bili", {"status": "error", "message": "未找到该路由"})
        self.assertEqual(ctx.exception.status, 502)
        self.assertIn("未找到该路由", ctx.exception.message)

    def test_status_routes_to_whitelisted_extension(self):
        calls = []

        def fake_call(inst, method, path, body=None, timeout=60):
            calls.append((method, path, body, timeout))
            return {"status": "ok", "data": {"proactive_used": 2}}

        inst = {"id": "i1", "dash_port": 1}
        self.assertEqual(consoles.call_status(inst, "bili", fake_call), {"proactive_used": 2})
        self.assertEqual(consoles.call_status(inst, "douyin", fake_call), {"proactive_used": 2})
        self.assertEqual(
            calls,
            [
                ("GET", "plugins/extensions/astrbot_plugin_bilibili_ai_bot/stats", None, 20),
                ("GET", "plugins/extensions/astrbot_plugin_douyin_dm/status", None, 20),
            ],
        )
        with self.assertRaises(consoles.ConsoleError):
            consoles.call_status(inst, "unknown", fake_call)

    def test_run_routes_and_payloads(self):
        calls = []

        def fake_call(inst, method, path, body=None, timeout=60):
            calls.append((method, path, body, timeout))
            return {"status": "ok", "data": {"started": True}}

        inst = {"id": "i2", "dash_port": 1}
        consoles.call_run(inst, "bili", fake_call)
        consoles.call_run(inst, "douyin", fake_call)
        self.assertEqual(
            calls,
            [
                ("POST", "plugins/extensions/astrbot_plugin_bilibili_ai_bot/proactive/run", {}, 60),
                ("POST", "plugins/extensions/astrbot_plugin_douyin_dm/control",
                 {"action": "proactive_run", "force": False}, 600),
            ],
        )

    def test_run_lock_rejects_second_run(self):
        inst = {"id": "i3", "dash_port": 1}
        lock = consoles._lock_for(inst, "douyin")
        lock.acquire()
        try:
            with self.assertRaises(consoles.ConsoleError) as ctx:
                consoles.call_run(inst, "douyin", lambda *a, **k: {})
            self.assertEqual(ctx.exception.status, 409)
            self.assertIn("已有立即执行任务", ctx.exception.message)
        finally:
            lock.release()

    def test_dashboard_error_is_wrapped(self):
        def fake_call(*args, **kwargs):
            raise DashboardError("Dashboard 登录失败", 401)

        with self.assertRaises(consoles.ConsoleError) as ctx:
            consoles.call_status({"id": "i4"}, "douyin", fake_call)
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("登录失败", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
