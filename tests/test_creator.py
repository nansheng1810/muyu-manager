"""实例平台同步的回归测试：显示名可以改，平台 id 不能跟着改。"""
import json
import tempfile
import unittest
from pathlib import Path

from server import creator


class SyncPlatformTests(unittest.TestCase):
    def _write_cfg(self, root: Path, cfg: dict) -> Path:
        data = root / "data"
        data.mkdir(parents=True, exist_ok=True)
        path = data / "cmd_config.json"
        path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return path

    def test_keeps_existing_platform_id_when_display_name_changed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg_path = self._write_cfg(
                root,
                {
                    "platform": [
                        {
                            "id": "千文",
                            "type": "aiocqhttp",
                            "enable": True,
                            "ws_reverse_port": 6299,
                            "ws_reverse_token": "old",
                        }
                    ],
                    "platform_settings": {
                        "enable_id_white_list": True,
                        "id_whitelist": ["千文:FriendMessage:1"],
                    },
                },
            )
            inst = {
                "name": "千问",
                "root": str(root),
                "ws_port": 6299,
                "ws_token": "new-token",
            }
            creator.sync_platform(inst)
            saved = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(saved["platform"][0]["id"], "千文")
            self.assertEqual(saved["platform"][0]["ws_reverse_token"], "new-token")
            self.assertEqual(
                saved["platform_settings"]["id_whitelist"],
                ["千文:FriendMessage:1"],
            )
            self.assertEqual(inst["platform_id"], "千文")

    def test_new_instance_uses_display_name_as_platform_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg_path = self._write_cfg(
                root, {"platform": [], "platform_settings": {}}
            )
            inst = {
                "name": "新Bot",
                "root": str(root),
                "ws_port": 6201,
                "ws_token": "token",
            }
            changes = creator.sync_platform(inst)
            saved = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(saved["platform"][0]["id"], "新Bot")
            self.assertEqual(inst["platform_id"], "新Bot")
            self.assertTrue(any("新增" in item for item in changes))


if __name__ == "__main__":
    unittest.main()
