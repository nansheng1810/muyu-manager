import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import matrix


def write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class MatrixTest(unittest.TestCase):
    def make_instance(self, root: Path, name="机器人"):
        for plugin, config, values in (
            ("astrbot_plugin_bilibili_ai_bot", "astrbot_plugin_bilibili_ai_bot_config.json", {
                "ENABLE_PRIVATE_MESSAGES": True,
                "PRIVATE_MESSAGE_AUTO_REPLY": True,
                "ENABLE_PROACTIVE": False,
                "APPROVAL_MODE": False,
            }),
            ("astrbot_plugin_douyin_dm", "astrbot_plugin_douyin_dm_config.json", {
                "enabled": True,
                "auto_reply_enabled": True,
                "allow_public_comments": True,
                "allow_like": True,
                "allow_favorite": True,
                "allow_follow": True,
                "interaction_dry_run": False,
                "approval_mode": False,
                "client_comment_enabled": False,
            }),
        ):
            (root / "data" / "plugins" / plugin).mkdir(parents=True, exist_ok=True)
            (root / "data" / "plugins" / plugin / "main.py").write_text("", encoding="utf-8")
            write(root / "data" / "config" / config, values)
        return {"id": name, "name": name, "root": str(root)}

    def test_instance_matrix_reads_write_switches(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = self.make_instance(Path(tmp))
            with mock.patch.object(matrix.runner_mod.runner, "status", return_value={"running": True}):
                item = matrix.instance_matrix(inst)
            self.assertTrue(item["online"])
            self.assertTrue(item["plugins"]["bili"]["installed"])
            self.assertTrue(item["values"]["bili.private"])
            self.assertTrue(item["values"]["douyin.auto_reply"])
            self.assertFalse(item["values"]["douyin.dry_run"])

    def test_missing_plugin_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = {"id": "a", "name": "A", "root": tmp}
            with mock.patch.object(matrix.runner_mod.runner, "status", return_value={"running": False}):
                item = matrix.instance_matrix(inst)
            self.assertFalse(item["plugins"]["douyin"]["installed"])
            self.assertIsNone(item["values"]["douyin.auto_reply"])

    def test_summary_counts_write_on_and_approval_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = self.make_instance(Path(tmp))
            with mock.patch.object(matrix.runner_mod.runner, "status", return_value={"running": True}):
                data = matrix.collect([inst])
            self.assertEqual(data["summary"]["instances"], 1)
            self.assertGreater(data["summary"]["write_on"], 0)
            self.assertEqual(data["summary"]["approval_off"], 1)
            self.assertEqual(data["summary"]["dry_run_off"], 1)


if __name__ == "__main__":
    unittest.main()
