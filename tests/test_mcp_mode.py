import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import mcp_mode


class McpModeTests(unittest.TestCase):
    def test_managed_choice_blocks_napcat(self):
        row = mcp_mode._public_managed_choice(
            {
                "id": "c1",
                "pid": 123,
                "path": "D:/大肥鱼/NapCat3/QQ.exe",
                "account": "241899875",
            }
        )
        self.assertTrue(row["blocked"])
        self.assertIn("NapCat", row["reason"])
        safe = mcp_mode._public_managed_choice(
            {"id": "c2", "pid": 456, "path": "D:/qq/QQ.exe"}
        )
        self.assertFalse(safe["blocked"])

    def test_connection_body_keeps_persona_out_of_upstream_scope(self):
        body = mcp_mode._connection_body(
            "241899875:group:884218771",
            "little_whale_v2",
            "natural",
            {"chat_images": True, "chat_sticker_send": True},
        )
        self.assertNotIn("persona_preset", body)
        self.assertNotIn("participation", body)
        self.assertEqual(body["conversations"], [["qq", "241899875:group:884218771"]])
        self.assertTrue(body["chat"])
        self.assertTrue(body["send"])
        self.assertFalse(body["manage"])
        with self.assertRaises(mcp_mode.McpModeError):
            mcp_mode._connection_body("bad", "", "natural", {})

    def test_public_connection_removes_token(self):
        with mock.patch.object(
            mcp_mode,
            "load_state",
            return_value={"connection": {"id": "gid", "token": "secret", "conversation_id": "x"}},
        ):
            public = mcp_mode._public_connection()
        self.assertNotIn("token", public)
        self.assertTrue(public["token_saved"])

    def test_codex_install_is_idempotent_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.toml").write_text(
                'model = "gpt-6.1-sol"\n', encoding="utf-8"
            )
            with mock.patch.object(
                mcp_mode,
                "_connection_token",
                return_value=({"id": "gid"}, "token-value"),
            ), mock.patch.object(
                mcp_mode,
                "tulpa_status",
                return_value={"mcp": {"url": "http://127.0.0.1:18777/mcp"}},
            ):
                first = mcp_mode.install_codex(home, "muyu_qq")
                second = mcp_mode.install_codex(home, "muyu_qq")
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            text = (home / "config.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-6.1-sol"', text)
            self.assertIn("[mcp_servers.muyu_qq]", text)
            self.assertNotIn("secret", first)
            backups = list((home / "backups").glob("*.toml"))
            self.assertEqual(len(backups), 1)

    def test_dsh_install_replaces_only_its_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = Path(tmp) / "cordis.patch.yml"
            patch.write_text(
                "# keep me\n- insert:\n    - id: existing\n      name: demo\n",
                encoding="utf-8",
            )
            with mock.patch.object(mcp_mode, "dsh_patch_path", return_value=patch), mock.patch.object(
                mcp_mode,
                "_connection_token",
                return_value=({"id": "gid"}, "token-value"),
            ), mock.patch.object(
                mcp_mode,
                "tulpa_status",
                return_value={"mcp": {"url": "http://127.0.0.1:18777/mcp"}},
            ), mock.patch.object(
                mcp_mode,
                "load_state",
                return_value={"raw": {"enabled": False}},
            ), mock.patch.object(
                mcp_mode, "RAW_WRAPPER", Path(tmp) / "raw.mjs"
            ):
                first = mcp_mode.install_dsh()
                second = mcp_mode.install_dsh()
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            text = patch.read_text(encoding="utf-8")
            self.assertIn("# keep me", text)
            self.assertEqual(text.count("id: mcp-muyu-qq"), 1)
            self.assertIn("MUYU_MCP_TOKEN", text)
            self.assertNotIn("token-value", text)

    def test_source_onebot_config_shape(self):
        config = mcp_mode._source_onebot_config(6801, 6802, "abc")
        http = config["networks"]["httpServers"][0]
        ws = config["networks"]["wsServers"][0]
        self.assertEqual(http["host"], "127.0.0.1")
        self.assertEqual(http["port"], 6801)
        self.assertEqual(ws["port"], 6802)
        self.assertEqual(ws["role"], "Universal")
        self.assertEqual(ws["accessToken"], "abc")
        self.assertTrue(ws["reportSelfMessage"])

    def test_raw_wrapper_is_private_and_mode_gated(self):
        state = {
            "source": {"http_port": 6801, "ws_port": 6802, "token": "tok"},
            "raw": {"enabled": True, "write": True},
        }
        with mock.patch.object(
            mcp_mode, "source_root", return_value=Path("D:/SnowLuma")
        ):
            text = mcp_mode._raw_wrapper_text(state)
        self.assertIn("SNOWLUMA_MCP_MODE = \"write\"", text)
        self.assertIn("SNOWLUMA_MCP_ENDPOINT", text)
        self.assertIn("SNOWLUMA_MCP_TOKEN", text)


    def test_source_processes_blocks_napcat(self):
        rows = {
            "list": [
                {"pid": 1, "name": "QQ", "path": "D:/大肥鱼/NapCat3/QQ.exe", "status": "available"},
                {"pid": 2, "name": "QQ", "path": "D:/qq/QQ.exe", "status": "available", "account": {"uin": "123", "nickname": "x"}},
            ]
        }
        with mock.patch.object(mcp_mode, "_source_webui_token", return_value="t"), mock.patch.object(
            mcp_mode, "_source_webui_request", return_value=rows
        ):
            items = mcp_mode.source_processes()
        self.assertTrue(items[0]["blocked"])
        self.assertFalse(items[1]["blocked"])
        self.assertEqual(items[1]["account"], "123")

    def test_codex_raw_entry_is_added_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with mock.patch.object(
                mcp_mode, "_connection_token", return_value=({"id": "gid"}, "tok")
            ), mock.patch.object(
                mcp_mode, "tulpa_status", return_value={"mcp": {"url": "http://127.0.0.1:18777/mcp"}}
            ), mock.patch.object(
                mcp_mode, "load_state", return_value={"raw": {"enabled": True, "write": False}}
            ):
                result = mcp_mode.install_codex(home)
            self.assertTrue(result["installed"])
            text = (home / "config.toml").read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.muyu_raw]", text)
            self.assertIn("muyu_raw_snowluma.mjs", text)

    def test_public_status_redacts_tokens(self):
        connection = {
            "id": "gid",
            "token": "secret-token",
            "conversation_id": "241899875:group:884218771",
        }
        agents = {
            "codex": {"installed": True, "path": "x"},
            "dsh": {"installed": False, "error": "missing"},
        }
        with mock.patch.object(
            mcp_mode,
            "load_state",
            return_value={
                "backend": "managed",
                "connection": connection,
                "snowluma_source": "D:/SnowLuma",
                "raw": {"enabled": False, "write": False},
            },
        ), mock.patch.object(
            mcp_mode,
            "tulpa_status",
            return_value={
                "root": "D:/Tulpa",
                "version": "0.5.7",
                "url": "http://127.0.0.1:64879",
                "mcp": {"running": True, "url": "http://127.0.0.1:18777/mcp"},
            },
        ), mock.patch.object(
            mcp_mode,
            "tulpa_sl_status",
            return_value={"phase": "choosing", "choices": []},
        ), mock.patch.object(
            mcp_mode,
            "source_status",
            return_value={
                "root": "D:/SnowLuma",
                "built": False,
                "running": False,
                "ports": {},
                "onebot": {"ready": False},
            },
        ), mock.patch.object(
            mcp_mode, "agents_status", return_value=agents
        ), mock.patch.object(
            mcp_mode,
            "raw_status",
            return_value={"enabled": False, "write": False},
        ), mock.patch.object(
            mcp_mode, "_public_connection", wraps=mcp_mode._public_connection
        ):
            payload = mcp_mode.public_status()
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("secret-token", blob)
        self.assertIn("token_saved", blob)


if __name__ == "__main__":
    unittest.main()
