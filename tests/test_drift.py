import unittest

from server import drift


def fake_call_factory(plugins, providers, personas):
    def call(inst, method, path, timeout=12):
        inst_id = inst.get("id")
        data = {"plugins": plugins, "providers": providers, "personas": personas}[path]
        return {"data": [row for row in data if row.get("_inst", inst_id) == inst_id]}

    return call


class DriftSnapshotTest(unittest.TestCase):
    def test_snapshot_normalizes_plugin_provider_and_persona(self):
        def call(inst, method, path, timeout=12):
            if path == "plugins":
                return {"data": [{"id": "p1", "version": "1.0", "enabled": True}]}
            if path == "providers":
                return {"data": [{"id": "m1", "model": "deepseek", "enable": True}]}
            return {"data": [{"persona_id": "a", "system_prompt": "你好"}]}

        snap = drift.snapshot({"id": "i1", "name": "一号"}, call)
        self.assertTrue(snap["reachable"])
        self.assertEqual(snap["plugins"]["p1"]["version"], "1.0")
        self.assertEqual(snap["providers"]["m1"]["model"], "deepseek")
        self.assertEqual(snap["personas"]["a"]["chars"], 2)
        self.assertEqual(len(snap["personas"]["a"]["hash"]), 16)


class DriftAlignTest(unittest.TestCase):
    def test_align_backs_up_before_writes(self):
        events = []

        def call(inst, method, path, payload=None, query=None, timeout=12):
            inst_id = inst["id"]
            if method == "GET" and path == "plugins":
                return {"data": [{"id": "p1", "version": "1.0", "enabled": inst_id == "ref"}]}
            if method == "GET" and path == "providers":
                return {"data": []}
            if method == "GET" and path == "personas":
                prompt = "REF" if inst_id == "ref" else "OLD"
                return {"data": [{"persona_id": "alice", "system_prompt": prompt}]}
            if method == "GET" and path == "personas/by-id":
                return {"data": {"persona": {"persona_id": "alice", "system_prompt": "REF"}}}
            if method == "PATCH" and path == "plugins/enabled":
                events.append(("plugin", payload))
                return {"status": "ok"}
            if method in {"POST", "PUT"} and path.startswith("personas"):
                events.append(("persona", method, payload))
                return {"status": "ok"}
            raise AssertionError((inst_id, method, path))

        def fake_backup(*args, **kwargs):
            events.append(("backup", args, kwargs))
            return {"path": "pre-align.zip"}

        result = drift.align(
            "ref", ["target"], ["plugins", "personas"], "ALIGN",
            instances=[{"id": "ref"}, {"id": "target"}],
            call=call, backup_func=fake_backup,
        )
        self.assertEqual(result["backup"]["path"], "pre-align.zip")
        self.assertEqual(events[0][0], "backup")
        self.assertEqual(result["actions"][0]["kind"], "plugin")
        self.assertTrue(any(event[0] == "persona" for event in events))
        self.assertEqual(result["ok"], True)

    def test_align_requires_confirmation(self):
        with self.assertRaises(ValueError):
            drift.align("ref", ["target"], ["plugins"], "nope", instances=[], call=lambda *a, **k: {})

    def test_align_without_issues_skips_backup(self):
        def call(inst, method, path, payload=None, query=None, timeout=12):
            if path == "plugins":
                return {"data": [{"id": "p1", "version": "1.0", "enabled": True}]}
            if path == "providers":
                return {"data": []}
            if path == "personas":
                return {"data": [{"persona_id": "alice", "system_prompt": "SAME"}]}
            raise AssertionError((method, path))

        backup_calls = []
        result = drift.align(
            "ref", ["target"], ["plugins", "personas"], "ALIGN",
            instances=[{"id": "ref"}, {"id": "target"}],
            call=call, backup_func=lambda *a, **k: backup_calls.append((a, k)),
        )
        self.assertEqual(result["actions"], [])
        self.assertEqual(backup_calls, [])


class DriftCompareTest(unittest.TestCase):
    def base(self, inst_id, name, version="1.0", model="deepseek", enabled=True):
        return {
            "id": inst_id,
            "name": name,
            "reachable": True,
            "errors": {},
            "plugins": {"p1": {"name": "插件", "version": version, "enabled": enabled}},
            "providers": {"m1": {"model": model, "type": "chat", "enabled": True}},
            "personas": {"persona": {"chars": 10, "hash": "abcdef0123456789"}},
        }

    def test_identical_instances_have_no_issues(self):
        result = drift.compare([self.base("a", "A"), self.base("b", "B")])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["overall"], "ok")

    def test_version_and_model_and_persona_drift(self):
        second = self.base("b", "B", version="2.0", model="qwen")
        second["personas"]["persona"]["hash"] = "ffffffffffffffff"
        result = drift.compare([self.base("a", "A"), second])
        kinds = {issue["kind"] for issue in result["issues"]}
        self.assertEqual(kinds, {"plugins", "providers", "personas"})

    def test_missing_plugin_is_reported(self):
        second = self.base("b", "B")
        second["plugins"] = {}
        result = drift.compare([self.base("a", "A"), second])
        self.assertEqual(len(result["issues"]), 1)
        self.assertIn("缺少", result["issues"][0]["message"])

    def test_unreachable_instance_marks_overall_bad(self):
        second = {"id": "b", "name": "B", "reachable": False, "errors": {"plugins": "offline"}, "plugins": {}, "providers": {}, "personas": {}}
        result = drift.compare([self.base("a", "A"), second])
        self.assertEqual(result["overall"], "bad")
        self.assertEqual(result["counts"]["reachable"], 1)


if __name__ == "__main__":
    unittest.main()
