import unittest
from pathlib import Path
from unittest import mock

from server import dsh


class DshCoreTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(dsh.parse_version("0.1.1-rc.2\n"), "0.1.1-rc.2")
        self.assertEqual(dsh.parse_version("version 2.0.0"), "2.0.0")
        self.assertEqual(dsh.parse_version(""), "")

    def test_build_start_args_uses_loopback_and_overlay(self):
        args = dsh.build_start_args("C:/dsh/bin.js", Path("overlay.yml"), 3080)
        self.assertIn("--profile", args)
        self.assertIn("web", args)
        self.assertIn("--patch", args)
        self.assertIn("overlay.yml", args)
        self.assertEqual(args[-5:], ["--host", "127.0.0.1", "--port", "3080", "--no-open"])
        plain = dsh.build_start_args("C:/dsh/bin.js", None, 3080)
        self.assertNotIn("--patch", plain)

    def test_skillhub_rejects_unknown_method(self):
        with self.assertRaises(dsh.DshError) as ctx:
            dsh.skillhub("exec", {})
        self.assertEqual(ctx.exception.status, 400)

    def test_skillhub_uses_official_endpoint(self):
        seen = {}

        def fake_http(url, payload=None, timeout=20):
            seen.update({"url": url, "payload": payload, "timeout": timeout})
            return {"ok": True, "items": [{"slug": "demo"}]}

        with mock.patch.object(dsh, "_http_json", fake_http):
            data = dsh.skillhub("search", {"query": "pdf"}, timeout=11)
        self.assertEqual(seen["url"], "http://127.0.0.1:3080/skillhub")
        self.assertEqual(seen["payload"], {"method": "search", "query": "pdf"})
        self.assertEqual(seen["timeout"], 11)
        self.assertEqual(data["items"][0]["slug"], "demo")

    def test_rpc_011_builds_dotted_envelope(self):
        seen = {}

        def fake_http(url, payload=None, timeout=20):
            seen.update({"url": url, "payload": payload})
            return {
                "type": "server-response",
                "result": {"ok": True, "value": {"items": [1, 2]}},
            }

        with mock.patch.object(dsh, "_http_json", fake_http):
            value = dsh.rpc_011("session.list", {}, timeout=9)
        self.assertEqual(seen["url"], "http://127.0.0.1:3080/api/session.list")
        self.assertEqual(seen["payload"]["method"], "session.list")
        self.assertEqual(seen["payload"]["payload"], {})
        self.assertEqual(value["items"], [1, 2])

    def test_install_skill_rejects_traversal(self):
        for bad in ("", "../x", "a/b", ".."):
            with self.assertRaises(dsh.DshError):
                dsh.install_skill(bad)

    def test_install_skill_passes_version(self):
        seen = {}

        def fake_skillhub(method, payload=None, timeout=30):
            seen.update({"method": method, "payload": payload, "timeout": timeout})
            return {"ok": True}

        with mock.patch.object(dsh, "skillhub", fake_skillhub):
            dsh.install_skill("pdf-ocr-md", "1.2.3")
        self.assertEqual(seen["method"], "install")
        self.assertEqual(seen["payload"], {"slug": "pdf-ocr-md", "version": "1.2.3"})

    def test_plugin_job_rejects_second_install(self):
        with dsh._install_lock:
            dsh._install_job.update({"active": True})
        try:
            with self.assertRaises(dsh.DshError) as ctx:
                dsh.start_plugin_install("owner", "name")
            self.assertEqual(ctx.exception.status, 409)
        finally:
            with dsh._install_lock:
                dsh._install_job.clear()
                dsh._install_job.update(
                    {
                        "active": False,
                        "action": "",
                        "target": "",
                        "started_at": 0.0,
                        "finished_at": 0.0,
                        "message": "",
                        "error": "",
                        "result": None,
                    }
                )

    def test_merged_bridge_config_forces_011_target(self):
        merged = dsh._merged_bridge_config(
            {"dsh_port": 9999, "unrelated": True, "inject_prompt_enabled": False}
        )
        self.assertEqual(merged["dsh_host"], "127.0.0.1")
        self.assertEqual(merged["dsh_port"], 3080)
        self.assertTrue(merged["inject_prompt_enabled"])
        self.assertTrue(merged["unrelated"])

    def test_bridge_plugin_compatibility(self):
        self.assertTrue(
            dsh._bridge_view({"id": "astrbot_plugin_dsh_bridge", "version": "1.0.0"})[
                "compatible"
            ]
        )
        self.assertFalse(
            dsh._bridge_view(
                {"id": "astrbot_plugin_dsh_connector", "version": "2.1.1"}
            )["compatible"]
        )

    def test_auto_start_only_after_previous_managed_run(self):
        self.assertTrue(dsh.should_auto_start({"pid": 123}, False, True))
        self.assertFalse(dsh.should_auto_start({}, False, True))
        self.assertFalse(dsh.should_auto_start({"pid": 123}, True, True))
        self.assertFalse(dsh.should_auto_start({"pid": 123}, False, False))

    def test_public_status_can_read_without_writing_overlay(self):
        with (
            mock.patch.object(dsh, "resolve_bin_js", return_value=Path("C:/dsh/bin.js")),
            mock.patch.object(dsh, "read_version", return_value="0.1.0"),
            mock.patch.object(dsh, "ensure_overlay", side_effect=AssertionError("write")),
            mock.patch.object(dsh.runner_mod, "port_open", return_value=False),
        ):
            data = dsh.public_status(
                include_counts=False, log_lines=0, prepare_overlay=False
            )
        self.assertEqual(data["version"], "0.1.0")
        self.assertFalse(data["running"])


if __name__ == "__main__":
    unittest.main()
