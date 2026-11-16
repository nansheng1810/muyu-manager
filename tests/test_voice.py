import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import api, dashboard, human_settings, mood, voice


def _profile(tts=None):
    return {
        "status": "ok",
        "data": {"config": {"provider_tts_settings": tts or {}}},
    }


class VoiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.object(
            voice, "_preset_dir", return_value=Path(self._tmp.name) / "voice_presets"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        settings = mock.patch.object(
            human_settings, "get_settings", return_value={"mood_enabled": True, "reset_hour": 5}
        )
        settings.start()
        self.addCleanup(settings.stop)
        state = mock.patch.object(
            mood, "get_state", return_value={"mood": "happy", "intensity": 60}
        )
        state.start()
        self.addCleanup(state.stop)
        self.inst = {"id": "i1", "name": "大肥鱼", "root": ""}

    def test_routes_registered(self):
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in (
            "/api/instances/{inst_id}/voice",
            "/api/instances/{inst_id}/voice/install",
            "/api/instances/{inst_id}/voice/disable",
            "/api/instances/{inst_id}/voice/endpoints",
            "/api/instances/{inst_id}/voice/mood",
            "/api/instances/{inst_id}/voice/preview",
            "/api/instances/{inst_id}/voice/ref-audio",
            "/api/instances/{inst_id}/voice/cache",
            "/api/instances/{inst_id}/voice/presets",
            "/api/instances/{inst_id}/voice/presets/{preset_id}",
            "/api/instances/{inst_id}/voice/presets/{preset_id}/ref-audio",
        ):
            self.assertIn(path, paths)

    def test_endpoint_priority_order(self):
        values = [item["value"] for item in voice.API_ENDPOINTS]
        self.assertEqual(
            values,
            [voice.LOCAL_API_BASE, voice.TUNNEL_API_BASE, voice.PUBLIC_API_BASE],
        )
        self.assertEqual(voice.DEFAULT_API_BASE, voice.PUBLIC_API_BASE)
        self.assertEqual(voice.LOCAL_API_BASE, "http://127.0.0.1:7860")
        self.assertEqual(voice.TUNNEL_API_BASE, "http://127.0.0.1:17860")

    def test_probe_endpoints_reports_reachability(self):
        def fake_connect(address, timeout=0):
            if address[1] == 7860:
                raise OSError("refused")

            class Conn:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return Conn()

        with mock.patch.object(
            voice.socket, "create_connection", side_effect=fake_connect
        ):
            items = voice.probe_endpoints()
        self.assertEqual([item["id"] for item in items], ["local", "tunnel", "public"])
        self.assertFalse(items[0]["reachable"])
        self.assertIn("refused", items[0]["error"])
        self.assertTrue(items[1]["reachable"])
        self.assertTrue(items[2]["reachable"])

    def test_status_merges_plugin_provider_and_tts(self):
        calls = []

        def fake_call(inst, method, path, payload=None, query=None, timeout=60):
            calls.append((method, path))
            if path == "plugins":
                return {
                    "status": "ok",
                    "data": [{"id": voice.PLUGIN_ID, "activated": True, "version": "v0.1.0"}],
                }
            if path == "providers/by-id":
                return {
                    "status": "ok",
                    "data": {
                        "provider": {
                            "id": voice.PROVIDER_ID,
                            "enable": True,
                            "api_key": "xCbSaFNtR403aX7l",
                            "instruction": "温柔女声",
                            "cfg_scale": 4,
                            "seed": 42,
                        }
                    },
                }
            return _profile({"enable": True, "provider_id": voice.PROVIDER_ID, "dual_output": True})

        with mock.patch.object(voice.dashboard, "call", side_effect=fake_call):
            data = voice.status(self.inst)

        self.assertTrue(data["plugin"]["installed"])
        self.assertTrue(data["plugin"]["enabled"])
        self.assertTrue(data["provider"]["exists"])
        self.assertTrue(data["provider"]["has_key"])
        self.assertNotIn("xCbSaFNtR403aX7l", data["provider"]["key_masked"])
        self.assertTrue(data["tts"]["enabled"])
        self.assertEqual(len(data["endpoints"]), 3)
        self.assertEqual(data["endpoints"][0]["id"], "local")
        self.assertEqual(len(calls), 3)

    def test_status_handles_missing_provider(self):
        def fake_call(inst, method, path, payload=None, query=None, timeout=60):
            if path == "plugins":
                return {"status": "ok", "data": []}
            if path == "providers/by-id":
                raise dashboard.DashboardError("not found", status=404)
            return _profile()

        with mock.patch.object(voice.dashboard, "call", side_effect=fake_call):
            data = voice.status(self.inst)
        self.assertFalse(data["plugin"]["installed"])
        self.assertFalse(data["provider"]["exists"])
        self.assertFalse(data["tts"]["enabled"])

    def test_save_creates_provider_and_enables_tts(self):
        captured = {}
        state = {"provider": None, "profile": {"provider_tts_settings": {"enable": False}}}

        def fake_call(inst, method, path, payload=None, query=None, timeout=60):
            if path == "plugins":
                return {
                    "status": "ok",
                    "data": [{"id": voice.PLUGIN_ID, "activated": True, "version": "v0.1.0"}],
                }
            if path == "providers/by-id" and method == "GET":
                if not state["provider"]:
                    raise dashboard.DashboardError("not found", status=404)
                return {"status": "ok", "data": {"provider": state["provider"]}}
            if path == "providers" and method == "POST":
                captured["create"] = payload
                state["provider"] = payload["config"]
                return {"status": "ok", "data": {}}
            if path == "config-profiles/default" and method == "GET":
                return {"status": "ok", "data": {"config": state["profile"]}}
            if path == "config-profiles/default" and method == "PUT":
                captured["profile"] = payload
                state["profile"] = payload
                return {"status": "ok", "data": {}}
            raise AssertionError((method, path))

        with mock.patch.object(voice.dashboard, "call", side_effect=fake_call):
            data = voice.save(self.inst, {
                "api_key": "test-key",
                "instruction": "温柔女声",
                "cfg_scale": 4,
                "seed": 42,
                "dual_output": True,
                "trigger_probability": 1,
            })

        config = captured["create"]["config"]
        self.assertEqual(config["id"], voice.PROVIDER_ID)
        self.assertEqual(config["type"], voice.PROVIDER_ID)
        self.assertEqual(config["provider_type"], "text_to_speech")
        self.assertEqual(config["api_key"], "test-key")
        self.assertEqual(config["instruction"], "温柔女声")
        self.assertTrue(config["enable"])
        self.assertTrue(config["cache_enabled"])
        self.assertEqual(config["cache_max_entries"], 200)
        self.assertEqual(config["cache_max_mb"], 200)
        self.assertTrue(config["mood_sync_enabled"])
        self.assertEqual(config["mood_instance_id"], "i1")
        self.assertEqual(config["mood_cache_seconds"], 20)
        tones = json.loads(config["mood_tones"])
        self.assertEqual(tones["happy"], voice.DEFAULT_MOOD_TONES["happy"])
        self.assertTrue(captured["profile"]["provider_tts_settings"]["enable"])
        self.assertEqual(
            captured["profile"]["provider_tts_settings"]["provider_id"], voice.PROVIDER_ID
        )
        self.assertTrue(data["tts"]["enabled"])

    def test_save_keeps_existing_key_when_blank(self):
        with mock.patch.object(
            voice, "_provider",
            return_value={"id": voice.PROVIDER_ID, "api_key": "saved-key", "api_base": "https://tts.chifengvtc.com"},
        ):
            config = voice._provider_config(self.inst, {"instruction": "新音色"})
        self.assertEqual(config["api_key"], "saved-key")
        self.assertEqual(config["instruction"], "新音色")

    def test_save_rejects_missing_key(self):
        with mock.patch.object(voice, "_provider", return_value=None):
            with self.assertRaises(voice.VoiceError):
                voice._provider_config(self.inst, {})

    def test_install_uploads_zip_and_returns_status(self):
        with mock.patch.object(voice, "_plugin_item", return_value=None), mock.patch.object(
            voice.dashboard, "upload_raw",
        ) as upload, mock.patch.object(
            voice, "status",
            return_value={"plugin": {"installed": True, "enabled": True}},
        ):
            data = voice.install(self.inst)

        self.assertTrue(data["plugin"]["installed"])
        body = upload.call_args.args[2]
        self.assertIn(b"astrbot_plugin_breeze_tts/metadata.yaml", body)
        self.assertIn(b"astrbot_plugin_breeze_tts/provider.py", body)
        self.assertIn("multipart/form-data", upload.call_args.args[3])

    def test_preview_posts_multipart(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"RIFFfakewave"

        def fake_urlopen(request, timeout=0):
            captured["request"] = request
            return FakeResponse()

        with mock.patch.object(voice, "_provider", return_value=None), mock.patch.object(
            voice.urllib.request, "urlopen", side_effect=fake_urlopen,
        ):
            audio = voice.preview(self.inst, {"text": "你好", "api_key": "test-key"})

        self.assertEqual(audio, b"RIFFfakewave")
        request = captured["request"]
        self.assertEqual(request.full_url, "https://tts.chifengvtc.com/v1/audio/speech/wav")
        headers = {key.lower(): value for key, value in request.headers.items()}
        self.assertEqual(headers["x-api-key"], "test-key")
        self.assertIn(b'name="text"', request.data)
        self.assertIn("你好".encode("utf-8"), request.data)

    def test_mood_state_maps_daily_mood_to_tone(self):
        data = voice.mood_state(self.inst, {})
        self.assertTrue(data["available"])
        self.assertEqual(data["source"], "manager")
        self.assertEqual(data["mood"], "happy")
        self.assertEqual(data["label"], "开心")
        self.assertEqual(data["tone"], voice.DEFAULT_MOOD_TONES["happy"])
        self.assertEqual(data["instance_id"], "i1")
        self.assertIn("开心", data["tones"])

    def test_mood_state_reports_disabled_daily_mood(self):
        with mock.patch.object(
            human_settings, "get_settings", return_value={"mood_enabled": False}
        ):
            data = voice.mood_state(self.inst, {"mood_sync_enabled": True})
        self.assertTrue(data["enabled"])
        self.assertFalse(data["mood_enabled"])

    def test_preview_applies_mood_tone(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"RIFFfakewave"

        def fake_urlopen(request, timeout=0):
            captured["request"] = request
            return FakeResponse()

        with mock.patch.object(voice, "_provider", return_value=None), mock.patch.object(
            voice.urllib.request, "urlopen", side_effect=fake_urlopen,
        ), mock.patch.object(
            voice,
            "mood_state",
            return_value={"available": True, "mood_enabled": True, "tone": "语气轻快"},
        ):
            voice.preview(
                self.inst,
                {"text": "你好", "api_key": "test-key", "instruction": "温柔女声"},
            )
        self.assertIn("温柔女声\n语气轻快".encode("utf-8"), captured["request"].data)

    def test_preview_requires_text_and_key(self):
        with self.assertRaises(voice.VoiceError):
            voice.preview(self.inst, {"text": ""})
        with mock.patch.object(voice, "_provider", return_value=None):
            with self.assertRaises(voice.VoiceError):
                voice.preview(self.inst, {"text": "你好"})

    def test_ref_audio_save_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = {"id": "i1", "root": tmp}
            data = voice.save_ref_audio(inst, "参考.wav", b"RIFFdata")
            path = Path(data["path"])
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, "ref_audio.wav")
            self.assertIn("plugin_data", path.parts)
            removed = voice.delete_ref_audio(inst)
            self.assertEqual(removed["removed"], 1)
            self.assertFalse(path.exists())

    def test_ref_audio_rejects_bad_file(self):
        with self.assertRaises(voice.VoiceError):
            voice.save_ref_audio({"root": ""}, "a.txt", b"x")
        with self.assertRaises(voice.VoiceError):
            voice.save_ref_audio({"root": ""}, "a.wav", b"")

    def test_cache_status_and_clear(self):
        root = Path(self._tmp.name) / "AstrBot"
        folder = root / "data" / "plugin_data" / voice.PLUGIN_ID / "tts_cache"
        folder.mkdir(parents=True)
        (folder / "a.wav").write_bytes(b"x" * 100)
        (folder / "b.wav").write_bytes(b"y" * 200)
        (folder / ".stats.json").write_text(
            json.dumps({"hits": 3, "misses": 5}), encoding="utf-8"
        )
        inst = {"id": "i2", "root": str(root)}
        data = voice.cache_status(inst, {"cache_enabled": True})
        self.assertTrue(data["available"])
        self.assertTrue(data["enabled"])
        self.assertEqual(data["entries"], 2)
        self.assertEqual(data["bytes"], 300)
        self.assertEqual(data["hits"], 3)
        self.assertEqual(data["misses"], 5)

        cleared = voice.clear_cache(inst)
        self.assertEqual(cleared["removed"], 2)
        self.assertFalse((folder / ".stats.json").exists())
        self.assertEqual(voice.cache_status(inst, {})["entries"], 0)

        missing = voice.cache_status(
            {"id": "i3", "root": str(Path(self._tmp.name) / "nope")}, {}
        )
        self.assertFalse(missing["available"])

    def test_builtin_plugin_version_matches_bundle(self):
        self.assertEqual(voice._builtin_plugin_version(), "v0.2.1")

    def test_plugin_source_bundle_exists(self):
        source = voice._plugin_source()
        self.assertTrue((source / "metadata.yaml").is_file())
        self.assertTrue((source / "provider.py").is_file())

    def test_voice_preset_bundle_exists(self):
        builtin = voice._builtin_preset_dir()
        self.assertTrue((builtin / "dafeiyu.json").is_file())
        self.assertTrue((builtin / "dafeiyu.wav").is_file())
        presets = voice._presets()
        self.assertTrue(presets)
        item = presets[0]
        self.assertEqual(item["id"], "dafeiyu")
        self.assertGreater(item["duration"], 0)
        self.assertTrue(Path(item["ref_audio"]).is_file())

    def test_seed_copies_presets_to_writable_dir_once(self):
        first = voice._presets()
        self.assertTrue(first)
        folder = voice._preset_dir()
        self.assertTrue((folder / "dafeiyu.json").is_file())
        self.assertTrue((folder / ".seeded").is_file())
        # 删除后再次读取不会被重新播种
        (folder / "dafeiyu.json").unlink()
        (folder / "dafeiyu.wav").unlink()
        self.assertFalse(voice._presets())

    def test_create_update_delete_preset(self):
        source = voice._builtin_preset_dir() / "dafeiyu.wav"
        payload = {
            "name": "测试音色",
            "label": "自定义",
            "summary": "新的声音",
            "traits": "软，慢",
            "instruction": "十七岁少女，语速偏慢",
            "ref_text": "你好，我是测试。",
            "cfg_scale": 5,
            "seed": 42,
        }
        with mock.patch.object(
            voice, "_provider", return_value={"ref_audio": str(source)}
        ):
            created = voice.create_preset(self.inst, payload)
        self.assertEqual(created["name"], "测试音色")
        self.assertEqual(created["traits"], ["软", "慢"])
        folder = voice._preset_dir()
        self.assertTrue((folder / f"{created['id']}.json").is_file())
        self.assertTrue(any(folder.glob(f"{created['id']}.*")))

        updated = voice.update_preset(
            self.inst,
            created["id"],
            {"name": "改名后", "traits": "清亮、慵懒", "cfg_scale": 6},
        )
        self.assertEqual(updated["name"], "改名后")
        self.assertEqual(updated["traits"], ["清亮", "慵懒"])
        self.assertEqual(updated["cfg_scale"], 6)

        replaced = voice.save_preset_audio(
            self.inst, created["id"], "new.wav", source.read_bytes()
        )
        self.assertEqual(replaced["id"], created["id"])
        self.assertTrue((folder / f"{created['id']}.wav").is_file())

        removed = voice.delete_preset(self.inst, created["id"])
        self.assertEqual(removed["removed"], created["id"])
        self.assertFalse((folder / f"{created['id']}.json").exists())
        self.assertFalse((folder / f"{created['id']}.wav").exists())

    def test_create_preset_requires_reference(self):
        with mock.patch.object(voice, "_provider", return_value={}):
            with self.assertRaises(voice.VoiceError):
                voice.create_preset(self.inst, {"name": "空", "ref_text": "你好"})
        with self.assertRaises(voice.VoiceError):
            voice.update_preset(self.inst, "missing", {"name": "x"})
        with self.assertRaises(voice.VoiceError):
            voice.delete_preset(self.inst, "missing")

    def test_status_lists_presets(self):
        def fake_call(inst, method, path, payload=None, query=None, timeout=60):
            if path == "plugins":
                return {"status": "ok", "data": []}
            if path == "providers/by-id":
                raise dashboard.DashboardError("not found", status=404)
            return _profile()

        with mock.patch.object(voice.dashboard, "call", side_effect=fake_call):
            data = voice.status(self.inst)
        self.assertTrue(data["presets"])
        self.assertFalse(data["presets"][0]["applied"])

    def test_apply_preset_writes_reference_and_provider(self):
        captured = {}

        def fake_call(inst, method, path, payload=None, query=None, timeout=60):
            if path == "plugins":
                return {
                    "status": "ok",
                    "data": [{"id": voice.PLUGIN_ID, "activated": True}],
                }
            if path == "providers/by-id" and method == "GET":
                return {
                    "status": "ok",
                    "data": {
                        "provider": {
                            "id": voice.PROVIDER_ID,
                            "api_key": "saved-key",
                            "api_base": "https://tts.chifengvtc.com",
                            "timeout": 300,
                        }
                    },
                }
            if path == "providers/by-id" and method == "PUT":
                captured["config"] = payload["config"]
                return {"status": "ok", "data": {}}
            raise AssertionError((method, path))

        preset = voice._presets()[0]
        with tempfile.TemporaryDirectory() as tmp:
            inst = {"id": "i1", "root": tmp}
            with mock.patch.object(
                voice.dashboard, "call", side_effect=fake_call
            ), mock.patch.object(voice, "status", return_value={"ok": True}):
                data = voice.apply_preset(inst, preset["id"])

            saved = Path(tmp) / "data" / "plugin_data" / voice.PLUGIN_ID / "ref_audio.wav"
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.stat().st_size, Path(preset["ref_audio"]).stat().st_size)

        self.assertEqual(data, {"ok": True})
        self.assertEqual(captured["config"]["instruction"], preset["instruction"])
        self.assertEqual(captured["config"]["ref_text"], preset["ref_text"])
        self.assertEqual(captured["config"]["api_key"], "saved-key")
        self.assertTrue(captured["config"]["ref_audio"].endswith("ref_audio.wav"))

    def test_apply_preset_rejects_unknown(self):
        with self.assertRaises(voice.VoiceError):
            voice.apply_preset(self.inst, "missing")


if __name__ == "__main__":
    unittest.main()
