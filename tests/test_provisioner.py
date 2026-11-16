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


class PythonBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "AstrBot"
        self.source.mkdir()
        self.runtime = self.root / "runtime"
        self.downloads = self.root / "downloads"
        self.patches = [
            mock.patch.object(provisioner, "RUNTIME_DIR", self.runtime),
            mock.patch.object(provisioner, "DOWNLOAD_DIR", self.downloads),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def test_installer_1603_falls_back_to_embedded(self):
        embedded = str(self.root / "embed" / "python.exe")
        process = mock.Mock(returncode=1603, stderr="", stdout="")
        with mock.patch.object(provisioner, "_system_python", return_value=""), mock.patch.object(
            provisioner, "_download", return_value=(b"installer", "")
        ), mock.patch.object(provisioner, "_run", return_value=process), mock.patch.object(
            provisioner, "_embedded_python", return_value=embedded
        ) as embedded_python:
            result = provisioner._ensure_python(str(self.source), "job")
        embedded_python.assert_called_once_with("job")
        self.assertEqual(result, embedded)

    def test_embedded_python_enables_site_and_installs_pip(self):
        target = self.runtime / "python-embed"
        target.mkdir(parents=True)
        (target / "python.exe").write_bytes(b"")
        pth = target / "python312._pth"
        pth.write_text("python312.zip\n.\n#import site\n", encoding="utf-8")
        probe = mock.Mock(returncode=1, stderr="", stdout="")
        install = mock.Mock(returncode=0, stderr="", stdout="")
        with mock.patch.object(
            provisioner, "_run", side_effect=[probe, install]
        ) as run, mock.patch.object(
            provisioner, "_download", return_value=(b"get-pip", "")
        ):
            result = provisioner._embedded_python("job")
        self.assertEqual(result, str(target / "python.exe"))
        self.assertIn("import site", pth.read_text(encoding="utf-8"))
        self.assertEqual(run.call_count, 2)
        self.assertIn("get-pip.py", " ".join(run.call_args_list[1].args[0]))

    def test_system_python_scans_common_install_dirs(self):
        exe = self.root / "Programs" / "Python" / "Python312" / "python.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
        with mock.patch.object(
            provisioner.shutil, "which", return_value=None
        ), mock.patch.dict(
            provisioner.os.environ,
            {"LOCALAPPDATA": str(self.root), "PROGRAMFILES": "", "PROGRAMFILES(X86)": ""},
            clear=False,
        ), mock.patch.object(
            provisioner, "_python_version", return_value=(3, 12)
        ):
            result = provisioner._system_python()
        self.assertEqual(result, str(exe))


class PluginSuiteScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        plugins = self.root / "data" / "plugins"
        (plugins / "astrbot_plugin_fleet_inbox").mkdir(parents=True)
        (plugins / "astrbot_plugin_fleet_inbox" / "metadata.yaml").write_text(
            "name: astrbot_plugin_fleet_inbox\n", encoding="utf-8"
        )
        (plugins / "meme_manager").mkdir()
        (plugins / "meme_manager" / "main.py").write_text("print(1)\n", encoding="utf-8")
        (plugins / "not_a_plugin").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_lists_plugin_directories(self):
        from server import api

        ids = api._installed_plugin_ids({"root": str(self.root)})
        self.assertEqual(ids, ["astrbot_plugin_fleet_inbox", "meme_manager"])

    def test_suite_marks_installed_plugins(self):
        from server import api

        with mock.patch.object(api, "_settings", return_value={"astrbot_source": ""}):
            data = api._plugin_suite({"root": str(self.root)})
        by_id = {item["id"]: item for item in data["suite"]}
        self.assertTrue(by_id["astrbot_plugin_fleet_inbox"]["installed"])
        self.assertTrue(by_id["meme_manager"]["installed"])
        self.assertFalse(by_id["astrbot_plugin_daily_mood"]["installed"])
        self.assertEqual(
            data["installed"], ["astrbot_plugin_fleet_inbox", "meme_manager"]
        )


if __name__ == "__main__":
    unittest.main()
