import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import napcat


class NapCatConfigTest(unittest.TestCase):
    def test_token_hash_matches_napcat_webui(self):
        expected = hashlib.sha256(b"test-token.napcat").hexdigest()
        self.assertEqual(napcat.token_hash("test-token"), expected)

    def test_find_webui_config_direct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            target = root / "config" / "webui.json"
            target.write_text(json.dumps({"port": 6099, "token": "t"}), encoding="utf-8")

            self.assertEqual(napcat.find_webui_config(root), target)
            config = napcat.webui_config(root)
            self.assertEqual(config["port"], 6099)
            self.assertEqual(config["token"], "t")

    def test_find_webui_config_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "NapCat.Shell" / "versions" / "v" / "resources" / "app" / "napcat" / "config"
            nested.mkdir(parents=True)
            target = nested / "webui.json"
            target.write_text(json.dumps({"port": 6100, "token": "x"}), encoding="utf-8")

            self.assertEqual(napcat.find_webui_config(root), target)
            self.assertEqual(napcat.webui_config(root)["port"], 6100)

    def test_local_qrcode_image_reads_cached_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "NapCat.Shell" / "versions" / "v" / "resources" / "app" / "napcat" / "cache"
            cache.mkdir(parents=True)
            (cache / "qrcode.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

            qrcode = napcat._local_qrcode_image(root)
            self.assertTrue(qrcode.startswith("data:image/png;base64,"))
            raw = base64.b64decode(qrcode.split(",", 1)[1])
            self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_local_qrcode_image_direct_versions_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "versions" / "v" / "resources" / "app" / "napcat" / "cache"
            cache.mkdir(parents=True)
            (cache / "qrcode.png").write_bytes(b"\x89PNG\r\n\x1a\ndirect")

            qrcode = napcat._local_qrcode_image(root)
            self.assertTrue(qrcode.startswith("data:image/png;base64,"))
            raw = base64.b64decode(qrcode.split(",", 1)[1])
            self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_login_state_without_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = napcat.login_state({"napcat_dir": tmp})
            self.assertFalse(state["running"])
            self.assertFalse(state["logged_in"])
            self.assertIn("webui.json", state["message"])

    def test_login_state_when_port_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "webui.json").write_text(
                json.dumps({"port": 6099, "token": "x"}), encoding="utf-8"
            )
            with mock.patch.object(napcat, "port_open", return_value=False):
                state = napcat.login_state({"napcat_dir": tmp})
            self.assertFalse(state["running"])
            self.assertIn("未运行", state["message"])


if __name__ == "__main__":
    unittest.main()
