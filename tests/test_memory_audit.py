import json
import unittest

from server import memory_audit


class MemoryAuditTest(unittest.TestCase):
    def test_duplicates_privacy_and_conflicts(self):
        items = [
            {"id": 1, "text": "主人喜欢吃香菜"},
            {"id": 2, "text": "主人喜欢吃香菜"},
            {"id": 3, "text": "主人不喜欢吃香菜"},
            {"id": 4, "text": "联系我 13800138000 或者 test@example.com"},
            {"id": 5, "text": "今天天气不错"},
        ]
        result = memory_audit.audit_items(items)
        self.assertGreaterEqual(result["counts"]["duplicates"], 1)
        self.assertGreaterEqual(result["counts"]["privacy"], 1)
        self.assertGreaterEqual(result["counts"]["conflicts"], 1)
        self.assertTrue(any(item["type"] == "手机号" for item in result["privacy"]))
        self.assertTrue(any(item["type"] == "邮箱" for item in result["privacy"]))

    def test_clean_items_have_no_issues(self):
        result = memory_audit.audit_items([
            {"id": 1, "text": "今天天气不错"},
            {"id": 2, "text": "明天可能下雨"},
        ])
        self.assertEqual(result["counts"], {"duplicates": 0, "privacy": 0, "conflicts": 0})

    def test_collect_normalizes_memory_payload(self):
        calls = []

        def fake_call(inst, query):
            calls.append((inst.get("id"), query))
            return {"items": [{"id": 1, "text": "主人喜欢猫"}, {"id": 2, "text": "主人喜欢猫"}]}

        result = memory_audit.collect({"id": "i1", "name": "一号"}, fake_call)
        self.assertEqual(result["instance_id"], "i1")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["counts"]["duplicates"], 1)
        self.assertEqual(calls[0][0], "i1")

    def test_audit_tolerates_new_metadata_shape(self):
        items = [
            {
                "id": 1,
                "text": "",
                "metadata": {"canonical_summary": "主人喜欢香菜", "arousal": 0.4},
            },
            {
                "id": 2,
                "text": "",
                "metadata": json.dumps(
                    {"canonical_summary": "主人喜欢香菜", "salience": 0.5}
                ),
            },
            {"id": 3, "text": "今天天气不错", "metadata": None},
        ]
        result = memory_audit.audit_items(items)
        for key in ("total", "counts", "duplicates", "privacy", "conflicts"):
            self.assertIn(key, result)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["counts"]["duplicates"], 1)
        self.assertEqual(len(result["duplicates"][0]), 2)

    def test_merge_preserves_audit_fields_and_attaches_forgetting(self):
        audit = {
            "total": 2,
            "counts": {"duplicates": 1, "privacy": 0, "conflicts": 0},
            "duplicates": [{"id": 1}],
            "privacy": [],
            "conflicts": [],
            "instance_id": "i1",
        }
        forgetting = {"items": [{"memory_id": 3, "risk": 0.8}], "total": 1}
        merged = memory_audit.merge(audit, forgetting)
        self.assertEqual(merged["total"], 2)
        self.assertEqual(merged["counts"], audit["counts"])
        self.assertEqual(merged["duplicates"], audit["duplicates"])
        self.assertEqual(merged["privacy"], [])
        self.assertEqual(merged["conflicts"], [])
        self.assertEqual(merged["instance_id"], "i1")
        self.assertEqual(merged["forgetting"], [{"memory_id": 3, "risk": 0.8}])
        self.assertNotIn("forgetting", audit)

        unchanged = memory_audit.merge(audit, None)
        self.assertEqual(unchanged, audit)
        self.assertNotIn("forgetting", unchanged)

        listed = memory_audit.merge(
            audit, [{"memory_id": 4, "risk": 0.2}, "bad", None]
        )
        self.assertEqual(listed["forgetting"], [{"memory_id": 4, "risk": 0.2}])

    def test_collect_keeps_audit_shape_with_new_fields(self):
        def fake_call(inst, query):
            return {
                "items": [
                    {
                        "id": 1,
                        "text": "主人喜欢猫",
                        "metadata": {"arousal": 0.6, "salience": 0.7},
                    },
                    {
                        "id": 2,
                        "text": "主人喜欢猫",
                        "metadata": {"arousal": 0.2, "salience": 0.3},
                    },
                ],
                "total": 2,
            }

        result = memory_audit.collect({"id": "i1", "name": "一号"}, fake_call)
        self.assertEqual(
            set(result),
            {
                "total",
                "counts",
                "duplicates",
                "privacy",
                "conflicts",
                "instance_id",
                "instance_name",
            },
        )
        self.assertEqual(result["counts"]["duplicates"], 1)


if __name__ == "__main__":
    unittest.main()
