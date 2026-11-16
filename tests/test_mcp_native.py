import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from server import mcp_native


class NativeMCPTests(unittest.TestCase):
    def test_public_state_redacts_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            with mock.patch.object(mcp_native, "STATE_PATH", path):
                state = mcp_native.public_state()
                self.assertTrue(state["agents"]["dsh"]["token_saved"])
                self.assertTrue(state["agents"]["codex"]["token_saved"])
                self.assertTrue(state["bridge_token_saved"])
                self.assertNotIn(chr(34) + "token" + chr(34), json.dumps(state))
                self.assertNotIn(chr(34) + "bridge_token" + chr(34), json.dumps(state))

    def test_tool_specs_cover_core_plugins(self):
        names = {item["name"] for item in mcp_native.tool_specs()}
        for name in (
            "start_chat_session",
            "wait_chat_messages",
            "send_chat_reply",
            "stop_chat_session",
            "memory_search",
            "memory_relations",
            "style_profiles",
            "mood_state",
            "presence_state",
            "rhythm_state",
            "memes_state",
            "inbox_state",
        ):
            self.assertIn(name, names)

    def test_session_queue_ack_and_self_filter(self):
        core = mcp_native.NativeMCPCore()
        with mock.patch.object(
            mcp_native.hub, "send_command", return_value={"platform_id": "aiocqhttp"}
        ), mock.patch.object(mcp_native.hub, "get", return_value=object()):
            session = core.start_session("inst", "884218771", "群")
        core.ingest_event(
            "inst",
            {
                "group_id": "884218771",
                "sender_id": "123",
                "sender_name": "群友",
                "self_id": "999",
                "message_id": "m1",
                "text": "你好",
                "segments": [{"type": "text", "data": {"text": "你好"}}],
            },
        )
        core.ingest_event(
            "inst",
            {
                "group_id": "884218771",
                "sender_id": "999",
                "self_id": "999",
                "text": "自己",
            },
        )
        result = core.wait_messages(session["id"], timeout_seconds=0.1, limit=10)
        self.assertEqual(result["state"], "ok")
        self.assertEqual(len(result["messages"]), 1)
        self.assertEqual(result["messages"][0]["text"], "你好")
        again = core.wait_messages(
            session["id"],
            timeout_seconds=0.05,
            acknowledge_through_id=result["read_through_id"],
        )
        self.assertEqual(again["messages"], [])

    def test_send_reply_uses_bridge_and_clears_quote_after_first(self):
        core = mcp_native.NativeMCPCore()
        calls = []

        def fake_send(instance_id, action, data=None, timeout=30):
            calls.append((instance_id, action, data))
            return {"sent": True}

        with mock.patch.object(mcp_native.hub, "send_command", side_effect=fake_send), mock.patch.object(
            mcp_native.hub, "get", return_value=object()
        ):
            session = core.start_session("inst", "884218771")
            result = core.send_reply(session["id"], ["一", "二"], "mid", ["123"])
        self.assertEqual(result["sent"], 2)
        sends = [row for row in calls if row[1] == "send"]
        self.assertEqual(len(sends), 2)
        self.assertEqual(sends[0][2]["reply_to"], "mid")
        self.assertEqual(sends[0][2]["mention_user_ids"], ["123"])
        self.assertEqual(sends[1][2]["reply_to"], "")

    def test_scoped_endpoint_rejects_other_instance(self):
        with self.assertRaises(mcp_native.NativeMCPError):
            mcp_native.scoped_call_tool(
                "list_groups",
                {"instance_id": "f0e1e0b6"},
                "bot-339f",
                "Codex",
                lambda: {},
            )

    def test_endpoint_requires_own_token(self):
        from starlette.testclient import TestClient

        service = mcp_native.NativeMCPService("dsh", "f0e1e0b6", 18790, "dsh-token", "DSH")
        app = service._app(18790)
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        with TestClient(app, base_url="http://127.0.0.1:18790") as client:
            denied = client.post("/mcp", json=payload, headers=headers)
            self.assertEqual(denied.status_code, 401)
            allowed = client.post(
                "/mcp",
                json=payload,
                headers={**headers, "Authorization": "Bearer dsh-token"},
            )
            self.assertEqual(allowed.status_code, 200, allowed.text)
            self.assertEqual(allowed.json()["result"]["serverInfo"]["name"], "muyu-native-dsh")

    def test_codex_install_is_idempotent_and_redacts_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.toml").write_text('model = "gpt-6.1-sol"' + chr(10), encoding="utf-8")
            with mock.patch.object(
                mcp_native,
                "load_state",
                return_value={
                    "agents": {
                        "codex": {
                            "instance_id": "bot-339f",
                            "port": 18779,
                            "token": "native-secret",
                        }
                    }
                },
            ):
                first = mcp_native.install_codex(home)
                second = mcp_native.install_codex(home)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            text = (home / "config.toml").read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.muyu_native]", text)
            self.assertNotIn("native-secret", json.dumps(first))
            self.assertEqual(len(list((home / "backups").glob("*.toml"))), 1)


if __name__ == "__main__":
    unittest.main()
