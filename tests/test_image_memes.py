import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import image_memes


class ImageMemesTests(unittest.TestCase):
    def _instance(self, root):
        return {"id": "i1", "name": "测试", "root": str(root)}

    def _source(self, root):
        source = Path(root) / "source"
        source.mkdir()
        (source / "meme_001_cat.png").write_bytes(b"cat")
        (source / "meme_002_whale.png").write_bytes(b"whale")
        return source

    def test_import_creates_pack_registry_and_active_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = self._instance(tmp)
            source = self._source(tmp)
            with mock.patch.object(
                image_memes, "_plugin_reload", return_value={"ok": True}
            ):
                result = image_memes.import_pack(
                    inst, str(source), "test-pack", "测试包"
                )
            self.assertTrue(result["imported"])
            self.assertEqual(result["image_count"], 2)
            pack = Path(tmp) / "data" / "plugin_data" / "meme_manager" / "packs" / "test-pack"
            self.assertTrue((pack / "memes" / "cat" / "meme_001_cat.png").is_file())
            manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["id"], "test-pack")
            self.assertIn("cat", manifest["categories"])
            rules = json.loads(
                (pack.parent.parent / "selection_rules.json").read_text(encoding="utf-8")
            )
            self.assertEqual(rules["rules"][0]["pack_ids"], ["test-pack"])
            registry = json.loads(
                (pack.parent.parent / "registry.json").read_text(encoding="utf-8")
            )
            self.assertEqual(registry["installed_packs"][0]["id"], "test-pack")

    def test_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = self._instance(tmp)
            source = self._source(tmp)
            with mock.patch.object(
                image_memes, "_plugin_reload", return_value={"ok": True}
            ):
                first = image_memes.import_pack(inst, str(source), "test-pack", "")
                second = image_memes.import_pack(inst, str(source), "test-pack", "")
            self.assertTrue(first["imported"])
            self.assertFalse(second["imported"])
            self.assertEqual(second["image_count"], 2)

    def test_images_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = self._instance(tmp)
            source = self._source(tmp)
            with mock.patch.object(
                image_memes, "_plugin_reload", return_value={"ok": True}
            ):
                image_memes.import_pack(inst, str(source), "test-pack", "")
            data = image_memes.list_images(inst, "test-pack")
            self.assertEqual(len(data["items"]), 2)
            path = image_memes.image_path(
                inst, "test-pack", "cat", "meme_001_cat.png"
            )
            self.assertTrue(path.is_file())
            with self.assertRaises(image_memes.ImageMemeError):
                image_memes.image_path(inst, "test-pack", "cat", "../manifest.json")

    def test_save_settings_and_random_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = self._instance(tmp)
            config = Path(tmp) / "data" / "config" / "meme_manager_config.json"
            config.parent.mkdir(parents=True)
            config.write_text(
                json.dumps({"generation": {"emotion": {"probability": 12}}}),
                encoding="utf-8",
            )
            with mock.patch.object(
                image_memes, "_plugin_reload", return_value={"ok": True}
            ):
                saved = image_memes.save_settings(inst, {"probability": 30})
            self.assertEqual(saved["settings"]["probability"], 30)
            data = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(data["generation"]["emotion"]["probability"], 30)

            source = self._source(tmp)
            with mock.patch.object(
                image_memes, "_plugin_reload", return_value={"ok": True}
            ):
                image_memes.import_pack(inst, str(source), "test-pack", "")
            with mock.patch.object(
                image_memes.dashboard,
                "call",
                return_value={"data": {"filename": "meme_001_cat.png"}},
            ) as call:
                result = image_memes.random_send(
                    inst, "884218771", "test-pack", "cat", dry_run=True
                )
            self.assertEqual(result["filename"], "meme_001_cat.png")
            method, path = call.call_args[0][1], call.call_args[0][2]
            self.assertEqual(method, "POST")
            self.assertEqual(
                path, "plugins/extensions/meme_manager/random/send"
            )

    def test_overview_counts_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = self._instance(tmp)
            source = self._source(tmp)
            with mock.patch.object(
                image_memes, "_plugin_reload", return_value={"ok": True}
            ):
                image_memes.import_pack(inst, str(source), "test-pack", "")
            with mock.patch.object(
                image_memes, "_plugin_ready", return_value=(True, "")
            ):
                data = image_memes.overview(inst)
            self.assertTrue(data["plugin_ready"])
            self.assertEqual(data["active_pack_id"], "test-pack")
            self.assertEqual(data["packs"][0]["image_count"], 2)


if __name__ == "__main__":
    unittest.main()
