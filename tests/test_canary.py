import os
import unittest

from server import canary, health, resources


class ResourcesTest(unittest.TestCase):
    def test_collect_returns_system_and_manager(self):
        data = resources.collect([])
        self.assertIn("cpu_percent", data["system"])
        self.assertIn("memory_percent", data["system"])
        self.assertIn("disk_free_gb", data["system"])
        self.assertEqual(data["manager"]["pid"], os.getpid())
        self.assertGreaterEqual(data["manager"]["processes"], 1)
        self.assertEqual(data["instances"], [])


class CanaryTest(unittest.TestCase):
    def test_run_checks_aggregates_status_and_latency(self):
        def ok_check():
            return health.component("manager", "管理器", "ok", "ready")

        def warn_check():
            return [health.component("dsh", "DSH", "warn", "未运行")]

        def instance_check(inst):
            return [health.component(f"astrbot:{inst['id']}", inst["name"], "ok", "ready")]

        result = canary.run_checks(
            instances=[{"id": "a", "name": "A"}],
            instance_check=instance_check,
            global_checks=[
                ("manager", "管理器", ok_check, "#/settings"),
                ("dsh", "DSH", warn_check, "#/dsh"),
            ],
        )
        self.assertEqual(result["overall"], "warn")
        self.assertEqual(result["counts"]["total"], 3)
        self.assertTrue(all(row["latency_ms"] >= 0 for row in result["checks"]))
        self.assertTrue(any(row["id"] == "astrbot:a" for row in result["checks"]))

    def test_run_checks_handles_exception_as_bad(self):
        def broken():
            raise RuntimeError("boom")

        result = canary.run_checks(
            instances=[],
            global_checks=[("broken", "坏检查", broken, "")],
        )
        self.assertEqual(result["overall"], "bad")
        self.assertEqual(result["checks"][0]["status"], "bad")
        self.assertIn("boom", result["checks"][0]["summary"])

    def test_bad_beats_warn(self):
        def bad_check():
            return health.component("x", "X", "bad", "down")

        def warn_check():
            return health.component("y", "Y", "warn", "slow")

        result = canary.run_checks(
            instances=[],
            global_checks=[("x", "X", bad_check, ""), ("y", "Y", warn_check, "")],
        )
        self.assertEqual(result["overall"], "bad")


if __name__ == "__main__":
    unittest.main()
