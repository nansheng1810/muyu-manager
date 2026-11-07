import tempfile
import unittest
from pathlib import Path

from server import automation, fleet_store, tasks as tasks_mod


class AutomationRegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "fleet.sqlite3"
        fleet_store.init(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_builtin_ids_and_groups(self):
        automation.ensure_builtin(self.db)
        items = tasks_mod.list_tasks(self.db)
        ids = {item["id"] for item in items}
        for expected in automation.BUILTIN_IDS:
            self.assertIn(expected, ids)
        groups = {automation.BUILTIN_IDS[item["id"]]["group"] for item in items if item["id"] in automation.BUILTIN_IDS}
        self.assertEqual(groups, {"维护", "巡检"})

    def test_ensure_is_idempotent(self):
        automation.ensure_builtin(self.db)
        before = len(tasks_mod.list_tasks(self.db))
        automation.ensure_builtin(self.db)
        self.assertEqual(len(tasks_mod.list_tasks(self.db)), before)

    def test_overview_shape(self):
        data = automation.overview(self.db)
        self.assertEqual(data["version"], automation.VERSION)
        self.assertIn("stats", data)
        self.assertIn("tasks", data)
        self.assertIn("events", data)
        self.assertIn("dsh", data)
        self.assertGreaterEqual(data["stats"]["total"], len(automation.BUILTINS))
        self.assertTrue(all(task["group"] for task in data["tasks"]))
        self.assertTrue(data["stats"]["scheduler_alive"] in (True, False))

    def test_logs_cursor(self):
        first = fleet_store.add_event("task", "unit", "ok", "第一条", db_path=self.db)
        second = fleet_store.add_event("task", "unit", "bad", "第二条", {"x": 1}, db_path=self.db)
        payload = automation.logs(0, 10, self.db)
        self.assertEqual([row["id"] for row in payload["events"]], [first, second])
        self.assertEqual(payload["events"][1]["detail"], {"x": 1})
        self.assertEqual(payload["last_id"], second)
        tail = automation.logs(first, 10, self.db)
        self.assertEqual([row["id"] for row in tail["events"]], [second])


if __name__ == "__main__":
    unittest.main()
