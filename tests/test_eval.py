import json
import tempfile
import unittest
from pathlib import Path

from server import eval as eval_mod
from server import fleet_store


class EvalScoreTest(unittest.TestCase):
    def setUp(self):
        self.fixture = eval_mod._clean_fixture(
            {
                "id": "demo",
                "title": "演示",
                "prompt": "你好",
                "expect_any": [["车队", "助手"], ["B站", "抖音"]],
                "forbid": ["作为AI"],
                "min_chars": 5,
                "max_chars": 50,
            },
            0,
        )

    def test_full_score(self):
        result = eval_mod.score_reply("我是车队助手，主要在B站和抖音活动。", self.fixture)
        self.assertEqual(result["score"], 100)
        self.assertTrue(all(item["ok"] for item in result["checks"]))

    def test_missing_group_and_forbidden(self):
        result = eval_mod.score_reply("作为AI，我什么都不知道。", self.fixture)
        self.assertLess(result["score"], 50)
        bad = {item["name"]: item["ok"] for item in result["checks"]}
        self.assertFalse(bad["关键词组 1"])
        self.assertFalse(bad["关键词组 2"])
        self.assertFalse(bad["禁用表达"])

    def test_empty_reply(self):
        result = eval_mod.score_reply("", self.fixture)
        self.assertEqual(result["score"], 0)

    def test_length_bounds(self):
        result = eval_mod.score_reply("车队助手 B站 " + "很长" * 40, self.fixture)
        checks = {item["name"]: item["ok"] for item in result["checks"]}
        self.assertFalse(checks["长度"])


class EvalFixturesTest(unittest.TestCase):
    def test_default_fixtures_are_valid(self):
        fixtures = eval_mod.load_fixtures()
        self.assertGreaterEqual(len(fixtures), 6)
        ids = [item["id"] for item in fixtures]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(item["prompt"] for item in fixtures))

    def test_custom_fixtures_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixtures.json"
            path.write_text(json.dumps({"fixtures": [{
                "id": "custom", "prompt": "测试", "expect_any": ["x"],
                "min_chars": 1, "max_chars": 10,
            }]}), encoding="utf-8")
            fixtures = eval_mod.load_fixtures(path)
            self.assertEqual(fixtures[0]["id"], "custom")

    def test_invalid_fixture_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixtures.json"
            path.write_text(json.dumps([{"id": "", "prompt": ""}]), encoding="utf-8")
            with self.assertRaises(eval_mod.EvalError):
                eval_mod.load_fixtures(path)


class EvalRunTest(unittest.TestCase):
    def test_run_records_and_average(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fleet.sqlite3"
            fleet_store.init(db_path)

            def fake_chat(inst, provider, messages, max_tokens=600, timeout=120):
                return "我是车队助手，主要在B站活动。"

            fixtures_path = Path(tmp) / "fixtures.json"
            fixtures_path.write_text(json.dumps([{
                "id": "one", "title": "用例", "prompt": "介绍自己",
                "expect_any": [["车队"], ["B站"]], "forbid": [],
                "min_chars": 5, "max_chars": 100,
            }]), encoding="utf-8")
            result = eval_mod.run(
                {"id": "a"}, "deepseek", fixture_ids=["one"],
                fixtures_path=fixtures_path, db_path=db_path, chat=fake_chat,
            )
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["results"][0]["status"], "ok")
            self.assertGreaterEqual(result["average"], 90)
            rows = eval_mod.list_runs(db_path=db_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["fixture"], "one")
            self.assertEqual(rows[0]["score"]["score"], result["results"][0]["score"]["score"])

    def test_trend_aggregates_daily_and_flags_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fleet.sqlite3"
            fleet_store.init(db_path)
            rows = [
                ("ev_a_identity", 1793600000, "identity", "m", "", 90),
                ("ev_b_identity", 1793686400, "identity", "m", "", 96),
                ("ev_c_identity", 1793686500, "identity", "m", "", 70),
            ]
            with fleet_store.session(db_path) as conn:
                for run_id, created, fixture, model, persona, score in rows:
                    conn.execute(
                        "INSERT INTO eval_runs(id, created, fixture, model, persona, score_json, status) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (run_id, created, fixture, model, persona,
                         json.dumps({"score": score}), "ok"),
                    )
            data = eval_mod.trend(db_path=db_path)
            self.assertEqual(data["runs"], 3)
            self.assertGreaterEqual(len(data["daily"]), 2)
            self.assertGreaterEqual(data["average"], 80)
            self.assertEqual(len(data["regressions"]), 1)
            self.assertEqual(data["regressions"][0]["from"], 96)
            self.assertEqual(data["regressions"][0]["to"], 70)

    def test_run_records_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fleet.sqlite3"
            fleet_store.init(db_path)

            def bad_chat(*args, **kwargs):
                raise RuntimeError("模型不可用")

            result = eval_mod.run(
                {"id": "a"}, "model", fixtures_path=eval_mod.FIXTURES_PATH,
                db_path=db_path, chat=bad_chat,
            )
            self.assertTrue(all(item["status"] == "error" for item in result["results"]))
            self.assertEqual(result["average"], 0)
            self.assertEqual(len(eval_mod.list_runs(db_path=db_path)), len(eval_mod.load_fixtures()))


if __name__ == "__main__":
    unittest.main()
