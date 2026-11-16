import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import codex_model


class CodexModelTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self._env.start()
        (self.home / "config.toml").write_text(
            'model_provider = "custom"\n'
            'model = "gpt-6.1-sol"\n'
            'model_catalog_json = "cc-switch-model-catalog.json"\n'
            "\n"
            "[features]\n"
            'model = "should-not-change"\n',
            encoding="utf-8",
        )
        (self.home / "cc-switch-model-catalog.json").write_text(
            json.dumps({
                "models": [
                    {"slug": "gpt-6.1-sol", "display_name": "GPT 6.1 Sol", "description": "default"},
                    {"slug": "gpt-6.1-terra", "display_name": "GPT 6.1 Terra", "description": "fast"},
                ]
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_catalog_reads_current_and_models(self):
        info = codex_model.catalog()
        self.assertEqual(info["current"], "gpt-6.1-sol")
        self.assertEqual([item["id"] for item in info["models"]], ["gpt-6.1-sol", "gpt-6.1-terra"])
        self.assertEqual(info["error"], "")

    def test_set_model_only_touches_top_level_value(self):
        codex_model.set_model("gpt-6.1-terra")
        text = (self.home / "config.toml").read_text(encoding="utf-8")
        self.assertIn('model = "gpt-6.1-terra"', text)
        self.assertIn('model = "should-not-change"', text)
        self.assertEqual(codex_model.current_model(), "gpt-6.1-terra")

    def test_unknown_model_is_rejected(self):
        with self.assertRaises(codex_model.CodexModelError):
            codex_model.set_model("not-in-catalog")
        self.assertEqual(codex_model.current_model(), "gpt-6.1-sol")

    def test_empty_model_is_rejected(self):
        with self.assertRaises(codex_model.CodexModelError):
            codex_model.set_model("  ")

    def test_missing_config_creates_model_line(self):
        (self.home / "config.toml").unlink()
        codex_model.set_model("gpt-6.1-sol")
        self.assertEqual(codex_model.current_model(), "gpt-6.1-sol")


if __name__ == "__main__":
    unittest.main()
