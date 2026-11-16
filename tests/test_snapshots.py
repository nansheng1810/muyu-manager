import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import fleet_store, snapshots


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inst_root = self.root / "instance"
        (self.inst_root / "data" / "config" / "plugins").mkdir(parents=True)
        (self.inst_root / "data" / "cmd_config.json").write_text(
            json.dumps({"provider": "deepseek", "persona": "旧"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.inst_root / "data" / "config" / "plugins" / "guard.json").write_text(
            json.dumps({"enabled": True}, ensure_ascii=False), encoding="utf-8",
        )
        self.inst = {"id": "i1", "name": "大肥鱼", "root": str(self.inst_root)}
        self.snap_dir = self.root / "snapshots"
        self.db_path = self.root / "fleet.sqlite3"
        self.patches = [
            mock.patch.object(snapshots, "SNAP_DIR", self.snap_dir),
            mock.patch.object(fleet_store, "DB_PATH", self.db_path),
        ]
        for patch in self.patches:
            patch.start()
        fleet_store.init(self.db_path)

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def test_create_list_diff_restore(self):
        first = snapshots.create(self.inst, "改前")
        self.assertEqual(first["files"], 2)
        (self.inst_root / "data" / "cmd_config.json").write_text(
            json.dumps({"provider": "openai", "persona": "旧"}, ensure_ascii=False),
            encoding="utf-8",
        )
        second = snapshots.create(self.inst, "改后")
        items = snapshots.list_snapshots(self.inst)
        self.assertEqual([item["id"] for item in items], [second["id"], first["id"]])

        diff = snapshots.diff(self.inst, first["id"], second["id"])
        self.assertEqual(diff["changes"], 1)
        self.assertEqual(diff["files"][0]["file"], "data/cmd_config.json")
        self.assertEqual(diff["files"][0]["changes"][0]["path"], "provider")
        self.assertEqual(diff["files"][0]["changes"][0]["before"], "deepseek")

        result = snapshots.restore(self.inst, first["id"], confirm="RESTORE")
        self.assertEqual(result["restored"], 2)
        restored = json.loads((self.inst_root / "data" / "cmd_config.json").read_text(encoding="utf-8"))
        self.assertEqual(restored["provider"], "deepseek")
        self.assertTrue(any(item["id"] == result["rollback"] for item in snapshots.list_snapshots(self.inst)))

    def test_restore_requires_confirm(self):
        snap = snapshots.create(self.inst, "手动")
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.restore(self.inst, snap["id"], confirm="")

    def test_delete_removes_snapshot_and_file(self):
        snap = snapshots.create(self.inst, "临时")
        path = self.snap_dir / "i1" / f"{snap['id']}.json"
        self.assertTrue(path.exists())
        snapshots.delete(self.inst, snap["id"])
        self.assertFalse(path.exists())
        self.assertEqual(snapshots.list_snapshots(self.inst), [])

    def test_invalid_snapshot_path_is_rejected(self):
        snap = snapshots.create(self.inst, "手动")
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.restore(self.inst, snap["id"], files=["../outside.json"], confirm="RESTORE")


if __name__ == "__main__":
    unittest.main()
