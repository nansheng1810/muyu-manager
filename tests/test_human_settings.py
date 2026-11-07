import tempfile
import unittest
from pathlib import Path

from server import human_settings


class HumanSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults(self):
        cfg = human_settings.get_settings("i1", db_path=self.db)
        self.assertTrue(cfg["mood_enabled"])
        self.assertTrue(cfg["human_enabled"])
        self.assertTrue(cfg["shadow"])
        self.assertFalse(cfg["silence_enabled"])
        self.assertEqual(cfg["reset_hour"], 5)
        self.assertEqual(cfg["max_delay_ms"], 3000)
        self.assertEqual(cfg["max_chunks"], 3)
        self.assertEqual(cfg["chunk_max_chars"], 120)

    def test_save_and_reload(self):
        human_settings.save_settings(
            "i1", {"shadow": False, "silence_enabled": True,
                   "silence_probability": 0.2, "reset_hour": 6},
            db_path=self.db)
        cfg = human_settings.get_settings("i1", db_path=self.db)
        self.assertFalse(cfg["shadow"])
        self.assertTrue(cfg["silence_enabled"])
        self.assertAlmostEqual(cfg["silence_probability"], 0.2)
        self.assertEqual(cfg["reset_hour"], 6)

    def test_rejects_bad_values(self):
        for patch in (
            {"reset_hour": 24},
            {"max_delay_ms": 5000},
            {"max_chunks": 4},
            {"chunk_max_chars": 200},
            {"silence_probability": 1.5},
            {"shadow": "yes"},
            {"unknown_key": 1},
        ):
            with self.subTest(patch=patch):
                with self.assertRaises(human_settings.SettingsError):
                    human_settings.save_settings("i1", patch, db_path=self.db)


if __name__ == "__main__":
    unittest.main()
