import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import snowluma


def sample_config():
    return {
        "networks": {
            "httpServers": [
                {"name": "http-default", "host": "127.0.0.1", "port": 3000, "path": "/", "accessToken": "x"},
                {"name": "custom-http", "host": "127.0.0.1", "port": 3999, "path": "/", "accessToken": "y"},
                {"name": snowluma.HTTP_NAME, "host": "127.0.0.1", "port": 6900, "path": "/", "accessToken": "old"},
            ],
            "httpClients": [],
            "wsServers": [
                {"name": "ws-default", "host": "127.0.0.1", "port": 3001, "path": "/", "accessToken": "x"},
                {"name": "custom-ws", "host": "127.0.0.1", "port": 3998, "path": "/", "accessToken": "y"},
            ],
            "wsClients": [
                {"name": "other", "url": "ws://127.0.0.1:9000/", "accessToken": "z"},
                {"name": snowluma.WS_NAME, "url": "ws://old/", "accessToken": "old"},
            ],
        },
        "statusCommand": {"enabled": False},
        "historySync": {"enabled": False},
        "notifications": {"channelIds": []},
    }


class SnowLumaConfigTests(unittest.TestCase):
    def test_merge_binding_config_replaces_factory_and_manager_nodes(self):
        merged = snowluma.merge_binding_config(
            sample_config(),
            http_port=6911,
            http_token="manager-token",
            astrbot_url="ws://127.0.0.1:6200/ws",
            astrbot_token="astrbot-token",
        )
        networks = merged["networks"]
        http_names = [item["name"] for item in networks["httpServers"]]
        self.assertNotIn("http-default", http_names)
        self.assertIn("custom-http", http_names)
        self.assertEqual(http_names.count(snowluma.HTTP_NAME), 1)
        manager_http = next(item for item in networks["httpServers"] if item["name"] == snowluma.HTTP_NAME)
        self.assertEqual(manager_http["port"], 6911)
        self.assertEqual(manager_http["accessToken"], "manager-token")
        ws_names = [item["name"] for item in networks["wsClients"]]
        self.assertEqual(ws_names.count(snowluma.WS_NAME), 1)
        self.assertIn("other", ws_names)
        client = next(item for item in networks["wsClients"] if item["name"] == snowluma.WS_NAME)
        self.assertEqual(client["url"], "ws://127.0.0.1:6200/ws")
        self.assertEqual(client["accessToken"], "astrbot-token")
        self.assertNotIn("ws-default", [item["name"] for item in networks["wsServers"]])

    def test_merge_binding_config_is_idempotent(self):
        first = snowluma.merge_binding_config(
            sample_config(), http_port=6911, http_token="t", astrbot_url="ws://127.0.0.1:6200/ws", astrbot_token=""
        )
        second = snowluma.merge_binding_config(
            first, http_port=6911, http_token="t", astrbot_url="ws://127.0.0.1:6200/ws", astrbot_token=""
        )
        self.assertEqual(
            [item["name"] for item in second["networks"]["httpServers"]].count(snowluma.HTTP_NAME), 1
        )
        self.assertEqual(
            [item["name"] for item in second["networks"]["wsClients"]].count(snowluma.WS_NAME), 1
        )

    def test_remove_binding_config_keeps_user_nodes(self):
        merged = snowluma.merge_binding_config(
            sample_config(), http_port=6911, http_token="t", astrbot_url="ws://127.0.0.1:6200/ws", astrbot_token=""
        )
        cleaned = snowluma.remove_binding_config(merged)
        self.assertEqual(
            [item["name"] for item in cleaned["networks"]["httpServers"]], ["custom-http"]
        )
        self.assertEqual(
            [item["name"] for item in cleaned["networks"]["wsClients"]], ["other"]
        )

    def test_astrbot_target_matches_instance_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            payload = {
                "platform": [
                    {"id": "other", "type": "aiocqhttp", "ws_reverse_port": 6100, "ws_reverse_token": "a"},
                    {"id": "龙娘", "type": "aiocqhttp", "ws_reverse_port": 6200, "ws_reverse_token": "b"},
                    {"id": "web", "type": "webchat", "ws_reverse_port": 1},
                ]
            }
            (root / "data" / "cmd_config.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig"
            )
            target = snowluma.astrbot_target({"root": str(root), "platform_id": "龙娘"})
            self.assertEqual(target["port"], 6200)
            self.assertEqual(target["_token"], "b")
            self.assertEqual(target["url"], "ws://127.0.0.1:6200/ws")
            self.assertTrue(target["token_set"])
            self.assertNotIn("_token", snowluma._public_target(target))

    def test_pick_process_and_validate_account(self):
        rows = [
            {"pid": 1, "uin": "111", "blocked": False, "logged_in": True, "status": "running"},
            {"pid": 2, "uin": "222", "blocked": True, "logged_in": True, "status": "running"},
            {"pid": 3, "uin": "222", "blocked": False, "logged_in": False, "status": "idle"},
        ]
        chosen = snowluma._pick_process(rows, "111")
        self.assertEqual(chosen["pid"], 1)
        self.assertEqual(snowluma._pick_process(rows, "222")["pid"], 3)
        with self.assertRaises(snowluma.SnowLumaError):
            snowluma._pick_process(rows, "333")
        with self.assertRaises(snowluma.SnowLumaError):
            snowluma._validate_process(rows[1], "222")
        with self.assertRaises(snowluma.SnowLumaError):
            snowluma._validate_process(rows[0], "222")
        snowluma._validate_process(rows[0], "111")



    def test_binding_enabled_reads_instance_flag(self):
        with mock.patch.object(
            snowluma, "load_state", return_value={"bindings": {"x": {"enabled": True}, "y": {"enabled": False}}}
        ):
            self.assertTrue(snowluma.binding_enabled("x"))
            self.assertFalse(snowluma.binding_enabled("y"))
            self.assertFalse(snowluma.binding_enabled("missing"))

    def test_start_flow_skips_napcat_when_snowluma_is_bound(self):
        from server import api

        inst = {"id": "x", "name": "X", "root": "D:/x", "napcat_dir": "D:/napcat"}
        with mock.patch.object(api.creator, "sync_platform", return_value=[]), mock.patch.object(
            api, "_settings", return_value={}
        ), mock.patch.object(api.runner, "start") as start, mock.patch.object(
            api, "_persist"
        ), mock.patch.object(api, "_spawn_provision"), mock.patch.object(
            api, "_decorate", return_value={}
        ), mock.patch.object(
            api.snowluma_mod, "binding_enabled", return_value=True
        ), mock.patch.object(
            api.runner, "napcat_status"
        ) as napcat_status, mock.patch.object(
            api.runner, "start_napcat"
        ) as start_napcat:
            _view, message = api._start_flow(inst)
        start.assert_called_once_with(inst, {})
        napcat_status.assert_not_called()
        start_napcat.assert_not_called()
        self.assertIn("SnowLuma", message)

    def test_bind_instance_writes_astrbot_ws_client(self):
        state = {"root": "D:/x", "source": {"pid": 1, "webui_port": 6800, "webui_password": "pw"}, "bindings": {}}
        saved = {}
        rows = [
            {
                "pid": 123,
                "name": "QQ",
                "uin": "241899875",
                "blocked": False,
                "logged_in": True,
                "status": "running",
                "path": "C:/QQ/QQ.exe",
            }
        ]
        with mock.patch.object(snowluma.store, "load_instances", return_value=[
            {"id": "bot-339f", "name": "龙娘", "qq": "241899875", "root": "D:/astrbot", "ws_port": 6200, "napcat_dir": "D:/napcat"}
        ]), mock.patch.object(snowluma, "load_state", side_effect=lambda: json.loads(json.dumps(state))), mock.patch.object(
            snowluma, "save_state"
        ), mock.patch.object(snowluma, "_source_running", return_value=True), mock.patch.object(
            snowluma, "_napcat_process", return_value=False
        ), mock.patch.object(snowluma, "_processes", return_value=rows), mock.patch.object(
            snowluma, "_port_open", return_value=False
        ), mock.patch.object(
            snowluma, "astrbot_target", return_value={"platform_id": "龙娘", "port": 6200, "token_set": True, "url": "ws://127.0.0.1:6200/ws", "_token": "astrbot-token"}
        ), mock.patch.object(
            snowluma, "_load_account_config", return_value=sample_config()
        ), mock.patch.object(
            snowluma, "_save_account_config", side_effect=lambda uin, cfg: saved.update({"uin": uin, "cfg": cfg}) or {"saved": True, "applied": True, "online": True, "message": ""}
        ), mock.patch.object(
            snowluma, "_wait_binding", return_value=(True, "241899875")
        ), mock.patch.object(
            snowluma, "_wait_astrbot", return_value=True
        ):
            result = snowluma.bind_instance("bot-339f")
        self.assertTrue(result["onebot"]["ready"])
        self.assertTrue(result["astrbot_connected"])
        self.assertEqual(saved["uin"], "241899875")
        client = next(item for item in saved["cfg"]["networks"]["wsClients"] if item["name"] == snowluma.WS_NAME)
        self.assertEqual(client["url"], "ws://127.0.0.1:6200/ws")
        self.assertEqual(client["accessToken"], "astrbot-token")
        self.assertEqual(result["binding"]["instance_id"], "bot-339f")
        self.assertNotIn("http_token", json.dumps(result["binding"]))

    def test_public_binding_does_not_leak_tokens(self):
        data = snowluma._public_binding(
            {
                "instance_id": "bot-339f",
                "enabled": True,
                "uin": "241899875",
                "http_token": "secret-http",
                "astrbot_url": "ws://127.0.0.1:6200/ws",
            }
        )
        self.assertNotIn("secret-http", json.dumps(data))
        self.assertEqual(data["http_port"], 0)
        self.assertEqual(data["instance_id"], "bot-339f")

    def test_webui_secret_redacts_nothing_but_separates_from_status(self):
        with mock.patch.object(
            snowluma,
            "load_state",
            return_value={
                "source": {"webui_port": 6800, "webui_password": "pw"},
                "bindings": {},
            },
        ):
            runtime = snowluma.runtime_status()
            secret = snowluma.webui_secret()
        self.assertNotIn("pw", json.dumps(runtime))
        self.assertEqual(secret["password"], "pw")


if __name__ == "__main__":
    unittest.main()
