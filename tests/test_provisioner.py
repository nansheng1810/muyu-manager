import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from server import provisioner


def zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = mock.patch.object(provisioner, "DOWNLOAD_DIR", self.root / "downloads")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_extract_flattens_single_root(self):
        data = zip_bytes({"AstrBot-main/main.py": "print(1)\n"})
        target = self.root / "out"
        provisioner._extract_zip(data, target)
        self.assertTrue((target / "main.py").exists())

    def test_extract_ignores_path_traversal(self):
        data = zip_bytes({"../evil.txt": "x", "pkg/main.py": "print(1)\n"})
        target = self.root / "safe"
        provisioner._extract_zip(data, target)
        self.assertFalse((self.root / "evil.txt").exists())

    def test_bundled_suite_contains_manager_plugins(self):
        names = provisioner._bundle_names()
        ids = {name.split("/")[0] for name in names if "/" in name}
        self.assertIn("astrbot_plugin_human_presence", ids)
        self.assertIn("astrbot_plugin_fleet_inbox", ids)
        self.assertIn("astrbot_plugin_daily_mood", ids)
        self.assertIn("astrbot_plugin_think_bridge", ids)
        self.assertIn("astrbot_plugin_qzone", ids)
        self.assertIn("astrbot_plugin_qqprofile", ids)

    def test_suite_covers_all_local_plugins(self):
        self.assertEqual(len(provisioner.SUITE), 19)
        ids = {item["id"] for item in provisioner.SUITE}
        self.assertIn("meme_manager", ids)
        self.assertIn("astrbot_plugin_bilibili_ai_bot", ids)
        self.assertIn("astrbot_plugin_qzone", ids)

    def test_extract_bundled_installs_plugin(self):
        target = self.root / "plugins" / "astrbot_plugin_human_presence"
        ok = provisioner._extract_bundled(
            "astrbot_plugin_human_presence", target, provisioner._bundle_names()
        )
        self.assertTrue(ok)
        self.assertTrue((target / "main.py").exists())


class PluginInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_plugin_copies_reference(self):
        reference = self.root / "reference" / "astrbot_plugin_fleet_inbox"
        reference.mkdir(parents=True)
        (reference / "main.py").write_text("print(1)\n", encoding="utf-8")
        dest = self.root / "dest" / "astrbot_plugin_fleet_inbox"
        detail = provisioner._install_plugin(
            {"id": "astrbot_plugin_fleet_inbox", "label": "收件箱"},
            dest,
            self.root / "reference",
            [],
        )
        self.assertIn("复制", detail)
        self.assertTrue((dest / "main.py").exists())

    def test_install_plugin_reports_missing_source(self):
        with self.assertRaises(provisioner.InstallError):
            provisioner._install_plugin(
                {"id": "astrbot_plugin_none", "label": "x"},
                self.root / "dest",
                self.root / "reference",
                [],
            )


class InstallJobTest(unittest.TestCase):
    def tearDown(self):
        provisioner._JOBS.clear()

    def test_environment_job_registers_steps(self):
        with mock.patch.object(provisioner, "_env_worker") as worker:
            job = provisioner.install_environment({"astrbot_source": ""})
        self.assertEqual(job["kind"], "env")
        self.assertEqual([item["key"] for item in job["steps"]],
                         ["source", "python", "deps", "save"])
        worker.assert_called_once()
        self.assertEqual(provisioner.job(job["id"])["state"], "running")

    def test_napcat_job_requires_instance(self):
        with mock.patch.object(provisioner.store, "load_instances", return_value=[]):
            with self.assertRaises(provisioner.InstallError):
                provisioner.install_napcat("missing", {})

    def test_plugins_job_requires_instance(self):
        with mock.patch.object(provisioner.store, "load_instances", return_value=[]):
            with self.assertRaises(provisioner.InstallError):
                provisioner.install_plugins("missing", {})


class RuntimeStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "AstrBot"
        (self.source / "data" / "plugins").mkdir(parents=True)
        (self.source / "main.py").write_text("print(1)\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_runtime_status_lists_suite(self):
        settings = {"astrbot_source": str(self.source), "python_exe": sys.executable}
        with mock.patch.object(provisioner.store, "load_instances", return_value=[{"id": "a"}]):
            data = provisioner.runtime_status(settings)
        self.assertTrue(data["env"]["ready"])
        self.assertEqual(len(data["suite"]), len(provisioner.SUITE))
        self.assertTrue(all(item["available"] for item in data["suite"]))
        self.assertEqual(data["napcat"]["total"], 1)

    def test_suite_serializable(self):
        settings = {"astrbot_source": str(self.source), "python_exe": sys.executable}
        with mock.patch.object(provisioner.store, "load_instances", return_value=[]):
            data = provisioner.runtime_status(settings)
        json.dumps(data)


if __name__ == "__main__":
    unittest.main()
