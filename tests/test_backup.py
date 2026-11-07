import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import backup, fleet_store, store


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "manager-data"
        self.backups = self.data / "backups"
        self.inst_root = root / "instance-one"
        self.patch_data = mock.patch.object(store, "DATA_DIR", self.data)
        self.patch_backup = mock.patch.object(backup, "BACKUP_DIR", self.backups)
        self.patch_db = mock.patch.object(fleet_store, "DB_PATH", self.data / "fleet_ops.sqlite3")
        for patch in (self.patch_data, self.patch_backup, self.patch_db):
            patch.start()
        fleet_store._initialized.clear()
        self.data.mkdir(parents=True)
        (self.data / "settings.json").write_text('{"astrbot_source":"x"}', encoding="utf-8")
        (self.inst_root / "data" / "config").mkdir(parents=True)
        (self.inst_root / "data" / "config" / "a.txt").write_text("original", encoding="utf-8")
        self.instances = [{"id": "inst1", "root": str(self.inst_root), "name": "one"}]

    def tearDown(self):
        for patch in (self.patch_db, self.patch_backup, self.patch_data):
            patch.stop()
        self.tmp.cleanup()

    def test_create_verify_list(self):
        item = backup.create(["manager", "instances"], instances=self.instances)
        self.assertTrue(Path(item["path"]).is_file())
        check = backup.verify(item["path"])
        self.assertTrue(check["ok"])
        self.assertEqual(check["files"], item["files"])
        listed = backup.list_backups()
        self.assertEqual(listed[0]["name"], Path(item["path"]).name)

    def test_restore_writes_files_back(self):
        item = backup.create(["manager", "instances"], instances=self.instances)
        (self.inst_root / "data" / "config" / "a.txt").write_text("changed", encoding="utf-8")
        result = backup.restore(item["path"], "RESTORE", instances=self.instances)
        self.assertGreaterEqual(result["restored"], 2)
        self.assertEqual((self.inst_root / "data" / "config" / "a.txt").read_text(encoding="utf-8"), "original")
        self.assertTrue(Path(result["rollback"]["path"]).is_file())

    def test_rehearse_extracts_and_checks_json(self):
        item = backup.create(["manager", "instances"], instances=self.instances)
        result = backup.rehearse(item["path"])
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["files"], 2)
        self.assertGreaterEqual(result["json_checked"], 1)
        self.assertEqual(result["json_bad"], [])
        self.assertFalse(any(Path(self.tmp.name).glob("fleet-restore-drill-*")))

    def test_rehearse_rejects_corrupt_zip(self):
        item = backup.create(["manager"], instances=self.instances)
        Path(item["path"]).write_bytes(b"not a zip")
        with self.assertRaises(ValueError):
            backup.rehearse(item["path"])

    def test_restore_requires_confirmation(self):
        item = backup.create(["manager"], instances=self.instances)
        with self.assertRaises(ValueError):
            backup.restore(item["path"], "nope", instances=self.instances)

    def test_restore_rejects_outside_path(self):
        with self.assertRaises(ValueError):
            backup.verify(str(Path(self.tmp.name) / "outside.zip"))


if __name__ == "__main__":
    unittest.main()
