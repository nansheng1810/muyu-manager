import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import creator, deploy


def make_source(root: Path) -> Path:
    source = root / "AstrBot"
    (source / "data").mkdir(parents=True, exist_ok=True)
    (source / "main.py").write_text("print('astrbot')\n", encoding="utf-8")
    (source / "data" / "cmd_config.json").write_text(
        json.dumps({"dashboard": {"port": 6185}, "provider": [{"id": "old"}]}),
        encoding="utf-8",
    )
    return source


def provider_config() -> dict:
    return {
        "id": "deploy-deepseek",
        "provider": "deepseek",
        "type": "openai_chat_completion",
        "provider_type": "chat_completion",
        "enable": True,
        "api_base": "https://api.deepseek.com/v1",
        "key": ["sk-test"],
        "model": "deepseek-chat",
    }


class DeployStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = make_source(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_reports_need_deploy_and_ready_env(self):
        settings = {
            "astrbot_source": str(self.source),
            "python_exe": sys.executable,
            "scan_dir": str(self.root),
        }
        with mock.patch.object(deploy.store, "load_instances", return_value=[]):
            data = deploy.status(settings)
        self.assertTrue(data["needed"])
        self.assertEqual(data["bots"], 0)
        self.assertTrue(data["env"]["source_ok"])
        self.assertTrue(data["env"]["python_ok"])
        self.assertTrue(data["env"]["ready"])
        self.assertEqual(len(data["vendors"]), 8)
        self.assertEqual(data["vendors"][-1]["id"], "custom")

    def test_status_is_not_needed_when_bot_exists(self):
        with mock.patch.object(deploy.store, "load_instances", return_value=[{"id": "a"}]):
            data = deploy.status({"astrbot_source": str(self.source)})
        self.assertFalse(data["needed"])
        self.assertEqual(data["bots"], 1)

    def test_env_detection_falls_back_to_scan_dir(self):
        settings = {"scan_dir": str(self.root)}
        self.assertEqual(deploy._find_source(settings), str(self.source.resolve()))

    def test_env_detection_returns_empty_without_source(self):
        empty = self.root / "empty"
        empty.mkdir()
        with mock.patch.object(deploy.store, "BASE_DIR", empty):
            self.assertEqual(deploy._find_source({"scan_dir": str(empty)}), "")


class DeployPrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = make_source(self.root)
        self.settings = {
            "astrbot_source": str(self.source),
            "python_exe": sys.executable,
            "instances_dir": str(self.root / "instances"),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_prepare_builds_provider_and_instance(self):
        with mock.patch.object(deploy, "_probe", return_value={"ok": True}) as probe:
            instance, provider = deploy.prepare(
                {
                    "name": "测试机器人",
                    "vendor": "deepseek",
                    "api_key": "sk-test",
                    "api_base": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat",
                    "qq": "10001",
                },
                self.settings,
                [],
            )
        probe.assert_called_once()
        self.assertEqual(provider["id"], "deploy-deepseek")
        self.assertEqual(provider["key"], ["sk-test"])
        self.assertEqual(instance["name"], "测试机器人")
        self.assertEqual(instance["qq"], "10001")
        self.assertEqual(instance["source"], "deployed")
        self.assertTrue(Path(instance["root"], "data", "cmd_config.json").exists())

        cfg = json.loads(Path(instance["root"], "data", "cmd_config.json").read_text("utf-8"))
        self.assertEqual(cfg["provider"][0]["id"], "deploy-deepseek")
        self.assertEqual(cfg["agent_runner"]["config"]["model"]["provider_id"], "deploy-deepseek")
        self.assertEqual(cfg["platform"][0]["type"], "aiocqhttp")
        self.assertEqual(cfg["admins_id"], ["10001"])
        self.assertIn("pbkdf2_sha256$600000$", cfg["dashboard"]["pbkdf2_password"])
        self.assertFalse(cfg["dashboard"]["password_change_required"])
        self.assertTrue(instance["dash_pass"])

    def test_prepare_requires_key_for_cloud_vendor(self):
        with self.assertRaises(deploy.DeployError):
            deploy.prepare(
                {"name": "x", "vendor": "deepseek", "api_key": ""},
                self.settings,
                [],
            )

    def test_prepare_accepts_custom_without_key(self):
        with mock.patch.object(deploy, "_probe", return_value={"ok": True}):
            instance, provider = deploy.prepare(
                {
                    "name": "本地",
                    "vendor": "custom",
                    "api_base": "http://127.0.0.1:11434/v1",
                    "model": "qwen3:8b",
                    "skip_probe": True,
                },
                self.settings,
                [],
            )
        self.assertEqual(provider["key"], [])
        self.assertEqual(instance["provider_id"], "deploy-custom")

    def test_prepare_rejects_unknown_vendor(self):
        with self.assertRaises(deploy.DeployError):
            deploy.prepare({"vendor": "nope"}, self.settings, [])

    def test_prepare_rejects_missing_source(self):
        settings = {**self.settings, "astrbot_source": str(self.root / "nope")}
        with mock.patch.object(deploy, "_probe", return_value={"ok": True}), \
             mock.patch.object(deploy, "_find_source", return_value=""):
            with self.assertRaises(deploy.DeployError):
                deploy.prepare({"vendor": "custom", "api_base": "http://x/v1", "model": "m"}, settings, [])


class DeployJobTest(unittest.TestCase):
    def test_job_snapshot_and_steps(self):
        with mock.patch.object(deploy, "_worker"):
            job = deploy.start({"id": "i1", "name": "n1", "root": "r1"}, {}, provider_config())
        self.assertEqual(job["state"], "running")
        self.assertEqual([step["key"] for step in job["steps"]],
                         ["create", "start", "dashboard", "persona"])
        self.assertEqual(job["steps"][0]["state"], "ok")
        found = deploy.job(job["id"])
        self.assertIsNotNone(found)
        self.assertEqual(found["instance_id"], "i1")
        self.assertIsNone(deploy.job("missing"))


class ModelPresetTest(unittest.TestCase):
    def test_presets_use_current_model_names(self):
        vendors = {item["id"]: item for item in deploy.VENDORS}
        self.assertEqual(vendors["deepseek"]["model"], "deepseek-v4-pro")
        self.assertIn("deepseek-v4-flash", vendors["deepseek"]["models"])
        self.assertEqual(vendors["dashscope"]["model"], "qwen3.8-max")
        self.assertEqual(vendors["openai"]["model"], "gpt-6.1-terra")
        self.assertEqual(vendors["moonshot"]["model"], "kimi-k3.1-pro")
        self.assertEqual(vendors["zhipu"]["model"], "glm-5.3")
        self.assertEqual(vendors["siliconflow"]["model"], "deepseek-ai/DeepSeek-V4.1-Flash")
        self.assertIn("qwen3.5:9b", vendors["ollama"]["models"])

    def test_models_url_normalizes_base(self):
        self.assertEqual(
            deploy._models_url("https://api.deepseek.com/v1"),
            "https://api.deepseek.com/v1/models",
        )
        self.assertEqual(
            deploy._models_url("https://x/v1/chat/completions"),
            "https://x/v1/models",
        )


class _FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self, _size=None):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ModelProbeTest(unittest.TestCase):
    def test_test_connection_returns_latency(self):
        with mock.patch.object(
            deploy, "_probe",
            return_value={"ok": True, "latency_ms": 128, "model": "deepseek-v4-pro", "reply": ""},
        ):
            data = deploy.test_connection(
                {"vendor": "deepseek", "api_key": "sk-test", "model": "deepseek-v4-pro"}
            )
        self.assertTrue(data["ok"])
        self.assertEqual(data["latency_ms"], 128)
        self.assertEqual(data["requested_model"], "deepseek-v4-pro")

    def test_list_models_reads_remote_list(self):
        payload = json.dumps({"data": [{"id": "m-b"}, {"id": "m-a"}, {"id": "m-a"}]}).encode()
        with mock.patch.object(deploy.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
            data = deploy.list_models(
                {"vendor": "deepseek", "api_key": "sk-test", "api_base": "https://api.deepseek.com/v1"}
            )
        self.assertEqual(data["source"], "remote")
        self.assertEqual(data["models"], ["m-a", "m-b"])

    def test_list_models_falls_back_to_preset(self):
        with mock.patch.object(
            deploy.urllib.request, "urlopen",
            side_effect=deploy.urllib.error.URLError("boom"),
        ):
            data = deploy.list_models(
                {"vendor": "deepseek", "api_key": "sk-test", "api_base": "https://api.deepseek.com/v1"}
            )
        self.assertEqual(data["source"], "preset")
        self.assertEqual(data["models"][0], "deepseek-v4-pro")
        self.assertIn("预设", data["message"])

    def test_list_models_requires_key_for_cloud_vendor(self):
        with self.assertRaises(deploy.DeployError):
            deploy.list_models({"vendor": "deepseek", "api_key": "", "api_base": "https://api.deepseek.com/v1"})


class BootstrapConfigTest(unittest.TestCase):
    def test_password_hashes_match_format(self):
        password = creator._new_dashboard_password()
        self.assertGreaterEqual(len(password), 16)
        self.assertTrue(any(ch.isupper() for ch in password))
        self.assertTrue(any(ch.islower() for ch in password))
        self.assertTrue(any(ch.isdigit() for ch in password))
        pbkdf2, md5 = creator._password_hashes(password)
        self.assertTrue(pbkdf2.startswith("pbkdf2_sha256$600000$"))
        self.assertEqual(len(md5), 32)


if __name__ == "__main__":
    unittest.main()
