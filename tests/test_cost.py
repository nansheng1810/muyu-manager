import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from server import cost


class CostTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir(parents=True)
        db = self.root / "data" / "data_v4.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE provider_stats("
            "provider_model TEXT, token_input_other INTEGER, token_input_cached INTEGER, "
            "token_output INTEGER, created_at TEXT)"
        )
        now = time.strftime("%Y-%m-%d 12:00:00")
        conn.executemany(
            "INSERT INTO provider_stats VALUES(?,?,?,?,?)",
            [
                ("deepseek-flash", 100000, 50000, 20000, now),
                ("deepseek-flash", 300000, 0, 40000, now),
                ("other-model", 10000, 0, 2000, now),
            ],
        )
        conn.commit()
        conn.close()
        self.inst = {"id": "i1", "name": "大肥鱼", "root": str(self.root)}
        self.config_path = self.root / "cost.json"
        self.patches = [
            mock.patch.object(cost, "CONFIG_PATH", self.config_path),
            mock.patch.object(cost.store, "load_instances", return_value=[self.inst]),
        ]
        for patch in self.patches:
            patch.start()
        cost.save_config({
            "prices": {"deepseek-flash": {"input": 2, "cached": 1, "output": 8}},
            "budget": {"daily": 10, "monthly": 100},
        })

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def test_collect_aggregates_tokens_and_cost(self):
        data = cost.collect(7)
        self.assertEqual(data["totals"]["input"], 410000)
        self.assertEqual(data["totals"]["cached"], 50000)
        self.assertEqual(data["totals"]["output"], 62000)
        expected = (400000 * 2 + 50000 * 1 + 60000 * 8) / 1_000_000
        self.assertAlmostEqual(data["totals"]["cost"], expected, places=6)
        self.assertEqual(data["today"]["calls"], 3)
        self.assertEqual(len(data["by_model"]), 2)
        self.assertEqual(data["by_instance"][0]["name"], "大肥鱼")

    def test_budget_alert_uses_daily_cost(self):
        cost.save_config({"budget": {"daily": 1, "monthly": 0}})
        data = cost.collect(7)
        self.assertTrue(data["alerts"])
        self.assertIn("今日", data["alerts"][0]["title"])

    def test_save_config_ignores_negative_numbers(self):
        saved = cost.save_config({"prices": {"m": {"input": -1, "output": 3}}})
        self.assertEqual(saved["prices"]["m"]["input"], 0)
        self.assertEqual(saved["prices"]["m"]["output"], 3)

    def test_missing_instance_is_tolerated(self):
        with mock.patch.object(cost.store, "load_instances", return_value=[]):
            data = cost.collect(7)
        self.assertEqual(data["totals"]["cost"], 0)


if __name__ == "__main__":
    unittest.main()
