import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from server import fleet_store
from server import tasks as tasks_mod


class ScheduleTest(unittest.TestCase):
    def test_parse_forms(self):
        self.assertEqual(tasks_mod.parse_schedule("daily")["kind"], "daily")
        self.assertEqual(tasks_mod.parse_schedule("09:30")["times"], [570])
        self.assertEqual(tasks_mod.parse_schedule("09:30, 21:00")["times"], [570, 1260])
        self.assertEqual(tasks_mod.parse_schedule("weekly:mon,thu")["days"], [0, 3])
        self.assertEqual(tasks_mod.parse_schedule("every:45m")["minutes"], 45)
        self.assertEqual(tasks_mod.parse_schedule("every:6h")["minutes"], 360)
        self.assertEqual(tasks_mod.parse_schedule("09:30")["text"], "09:30")

    def test_rejects_bad_forms(self):
        for value in ("", "25:00", "weekly:xyz", "every:0m", "every:5x", "cron * * * *"):
            with self.assertRaises(tasks_mod.TaskError):
                tasks_mod.parse_schedule(value)

    def test_next_run_times(self):
        after = datetime(2026, 11, 3, 8, 0).timestamp()
        next_run = tasks_mod.next_run_at("09:30", after)
        self.assertEqual(datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M"), "2026-11-03 09:30")
        after = datetime(2026, 11, 3, 10, 0).timestamp()
        next_run = tasks_mod.next_run_at("09:30", after)
        self.assertEqual(datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M"), "2026-11-04 09:30")

    def test_next_run_every_and_weekly(self):
        after = datetime(2026, 11, 3, 10, 0).timestamp()
        self.assertEqual(
            int(tasks_mod.next_run_at("every:30m", after) - after), 1800
        )
        next_run = datetime.fromtimestamp(tasks_mod.next_run_at("weekly:mon", after))
        self.assertEqual(next_run.weekday(), 0)
        self.assertGreater(next_run.timestamp(), after)


class TaskStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "fleet.sqlite3"
        fleet_store.init(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed_defaults(self):
        items = tasks_mod.list_tasks(self.db)
        self.assertGreaterEqual(len(items), 7)
        ids = {item["id"] for item in items}
        self.assertIn("task_auto_health", ids)
        self.assertIn("task_daily_backup", ids)
        self.assertTrue(all(item["enabled"] for item in items))
        self.assertTrue(all(item["next_run"] > 0 for item in items))
        self.assertEqual(len(tasks_mod.list_tasks(self.db)), len(items))

    def test_seed_keeps_existing_custom_tasks_and_backfills(self):
        custom = tasks_mod.create("自定义", "digest", "daily", db_path=self.db)
        items = tasks_mod.list_tasks(self.db)
        self.assertIn(custom["id"], {item["id"] for item in items})
        self.assertIn("task_auto_health", {item["id"] for item in items})
        self.assertGreaterEqual(len(items), 8)

    def test_create_update_delete(self):
        item = tasks_mod.create("测试备份", "backup", "every:60m", {"label": "unit"}, enabled=True, db_path=self.db)
        self.assertTrue(item["enabled"])
        self.assertGreater(item["next_run"], 0)
        updated = tasks_mod.update(item["id"], {"enabled": False}, db_path=self.db)
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["next_run"], 0)
        self.assertTrue(tasks_mod.delete(item["id"], db_path=self.db))
        self.assertIsNone(tasks_mod._get(item["id"], self.db))

    def test_workflow_runs_steps_in_order(self):
        calls = []

        def fake_dispatch(task):
            calls.append((task["kind"], task["config"]))
            return {"summary": f"done {task['kind']}"}

        result = tasks_mod._dispatch_workflow(
            {"id": "wf", "name": "夜间链", "config": {"steps": [
                {"kind": "backup", "config": {"label": "night"}},
                {"kind": "digest", "config": {}},
            ]}},
            fake_dispatch,
        )
        self.assertEqual([row[0] for row in calls], ["backup", "digest"])
        self.assertEqual(calls[0][1]["label"], "night")
        self.assertEqual(result["summary"], "工作流完成 2 步")

    def test_workflow_rejects_nested_or_empty_steps(self):
        with self.assertRaises(tasks_mod.TaskError):
            tasks_mod._dispatch_workflow({"id": "wf", "config": {"steps": []}}, lambda task: {})
        with self.assertRaises(tasks_mod.TaskError):
            tasks_mod._dispatch_workflow(
                {"id": "wf", "config": {"steps": [{"kind": "workflow"}]}}, lambda task: {}
            )

    def test_workflow_stops_on_step_error(self):
        def fake_dispatch(task):
            if task["kind"] == "digest":
                raise RuntimeError("boom")
            return {"summary": "ok"}

        with self.assertRaises(tasks_mod.TaskError) as ctx:
            tasks_mod._dispatch_workflow(
                {"id": "wf", "config": {"steps": [{"kind": "backup"}, {"kind": "digest"}]}},
                fake_dispatch,
            )
        self.assertIn("第 2 步", str(ctx.exception))

    def test_invalid_kind(self):
        with self.assertRaises(tasks_mod.TaskError):
            tasks_mod.create("坏任务", "unknown", "daily", db_path=self.db)

    def test_automation_kinds_dispatch_guards(self):
        for kind in ("health_patrol", "resource_scan", "drift_scan", "canary_patrol", "dsh_prompt"):
            self.assertIn(kind, tasks_mod.KINDS)
        with self.assertRaises(tasks_mod.TaskError):
            tasks_mod._dispatch({"kind": "dsh_prompt", "config": {}})
        with self.assertRaises(tasks_mod.TaskError):
            tasks_mod._dispatch({"kind": "unknown", "config": {}})

    def test_run_success_and_failure_records(self):
        item = tasks_mod.create("单元任务", "digest", "daily", db_path=self.db)
        ok = tasks_mod.run_task(item, dispatch=lambda task: {"summary": "ok"}, db_path=self.db)
        self.assertEqual(ok["status"], "success")
        bad = tasks_mod.run_task(
            item, dispatch=lambda task: (_ for _ in ()).throw(RuntimeError("boom")),
            db_path=self.db,
        )
        self.assertEqual(bad["status"], "failed")
        runs = tasks_mod.list_runs(item["id"], db_path=self.db)
        self.assertEqual(len(runs), 2)
        self.assertEqual({row["status"] for row in runs}, {"success", "failed"})

    def test_scheduler_tick_applies_backoff(self):
        item = tasks_mod.create("定时失败", "digest", "every:60m", enabled=True, db_path=self.db)
        # 直接改成到期并观察失败退避
        with fleet_store.session(self.db) as conn:
            conn.execute("UPDATE tasks SET next_run=? WHERE id=?", (datetime(2026, 11, 3, 8, 0).timestamp(), item["id"]))
        scheduler = tasks_mod.Scheduler(interval=999, db_path=self.db)
        now = datetime(2026, 11, 3, 9, 0).timestamp()
        original_dispatch = tasks_mod._dispatch
        tasks_mod._dispatch = lambda task: (_ for _ in ()).throw(RuntimeError("fail"))
        try:
            runs = scheduler.tick(now)
        finally:
            tasks_mod._dispatch = original_dispatch
        self.assertEqual(len(runs), 1)
        fresh = tasks_mod._get(item["id"], self.db)
        self.assertEqual(fresh["config"]["_failures"], 1)
        self.assertAlmostEqual(fresh["next_run"], now + 60, delta=2)


if __name__ == "__main__":
    unittest.main()
