import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import agent_mode


class AgentModeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patches = [
            mock.patch.object(agent_mode, "STATE_PATH", root / "agent_mode.json"),
            mock.patch.object(agent_mode, "LOG_DIR", root / "logs"),
            mock.patch.object(agent_mode, "WORK_ROOT", root / "workspace"),
        ]
        for patch in self._patches:
            patch.start()
        agent_mode._runtime.clear()

    def tearDown(self):
        agent_mode._runtime.clear()
        for patch in reversed(self._patches):
            patch.stop()
        self._tmp.cleanup()

    def test_pick_group_prefers_explicit_then_saved_then_first(self):
        with mock.patch.object(agent_mode.mcp_mod, "core") as core:
            core.list_groups.return_value = {"groups": [{"group_id": "900", "group_name": "一群"}]}
            self.assertEqual(agent_mode._pick_group("x", "123", "目标"), ("123", "目标"))
            agent_mode._put("x", {"group_id": "456", "group_name": "上次"})
            self.assertEqual(agent_mode._pick_group("x", "", ""), ("456", "上次"))
            self.assertEqual(agent_mode._pick_group("y", "", ""), ("900", "一群"))
            core.list_groups.return_value = {"groups": []}
            with self.assertRaises(agent_mode.AgentError):
                agent_mode._pick_group("z", "", "")

    def test_set_group_persists_selection(self):
        result = agent_mode.set_group("x", "123", "测试群")
        self.assertEqual(result["group_id"], "123")
        self.assertEqual(result["group_name"], "测试群")
        self.assertFalse(result["enabled"])

    def test_enable_requires_bound_agent(self):
        agent_mode._put("x", {"group_id": "123", "group_name": "群"})
        with mock.patch.object(agent_mode, "_agent_for", return_value=""):
            with self.assertRaises(agent_mode.AgentError):
                agent_mode.enable("x")

    def test_enable_launches_agent_and_disable_cleans_up(self):
        session = {"id": "s1", "instance_id": "x", "group_id": "123", "active": True}
        core = mock.Mock()
        core.sessions_public.return_value = []
        core.start_session.return_value = session
        hub = mock.Mock()
        hub.get.return_value = object()
        service = mock.Mock()
        with mock.patch.object(agent_mode, "_agent_for", return_value="dsh"), mock.patch.object(
            agent_mode.mcp_mod, "services", {"dsh": service}
        ), mock.patch.object(agent_mode.mcp_mod, "hub", hub), mock.patch.object(
            agent_mode.mcp_mod, "core", core
        ), mock.patch.object(
            agent_mode, "_launch_dsh", return_value={"agent": "dsh", "session_id": "dsh-1"}
        ) as launch:
            result = agent_mode.enable("x", "123", "测试群")
        launch.assert_called_once_with("x", "123", "测试群", "s1", None)
        service.start.assert_called_once()
        self.assertTrue(result["enabled"])
        self.assertEqual(result["agent"], "dsh")
        self.assertTrue(agent_mode.status("x")["enabled"])

        core.sessions_public.side_effect = [[session], []]
        with mock.patch.object(agent_mode, "_stop_dsh") as stop_dsh, mock.patch.object(
            agent_mode.mcp_mod, "core", core
        ):
            status = agent_mode.disable("x")
        stop_dsh.assert_called_once_with("x")
        core.stop_session.assert_called_once_with("s1")
        self.assertFalse(status["enabled"])
        self.assertEqual(status["sessions"], [])

    def test_enable_passes_saved_dsh_model(self):
        agent_mode._put("x", {"dsh_model": {"provider": "mimo", "model": "mimo-v2.6-flash"}})
        session = {"id": "s1", "instance_id": "x", "group_id": "123", "active": True}
        core = mock.Mock()
        core.sessions_public.return_value = []
        core.start_session.return_value = session
        hub = mock.Mock()
        hub.get.return_value = object()
        with mock.patch.object(agent_mode, "_agent_for", return_value="dsh"), mock.patch.object(
            agent_mode.mcp_mod, "services", {"dsh": mock.Mock()}
        ), mock.patch.object(agent_mode.mcp_mod, "hub", hub), mock.patch.object(
            agent_mode.mcp_mod, "core", core
        ), mock.patch.object(
            agent_mode, "_launch_dsh", return_value={"agent": "dsh", "session_id": "dsh-1"}
        ) as launch:
            agent_mode.enable("x", "123", "测试群")
        self.assertEqual(
            launch.call_args.args[4], {"provider": "mimo", "model": "mimo-v2.6-flash"}
        )

    def test_set_dsh_model_persists_and_clears(self):
        with mock.patch.object(agent_mode, "_agent_for", return_value="dsh"):
            status = agent_mode.set_dsh_model("y", "mimo", "mimo-v2.6-flash")
        self.assertEqual(status["dsh_model"], {"provider": "mimo", "model": "mimo-v2.6-flash"})
        with mock.patch.object(agent_mode, "_agent_for", return_value="dsh"):
            status = agent_mode.set_dsh_model("y", "", "")
        self.assertEqual(status["dsh_model"], {})

    def test_status_labels_agent(self):
        with mock.patch.object(agent_mode, "_agent_for", return_value="codex"):
            status = agent_mode.status("x")
        self.assertEqual(status["agent_label"], "Codex")
        self.assertFalse(status["enabled"])

    def test_restore_all_reeanables_saved_modes(self):
        agent_mode._put("x", {"enabled": True, "group_id": "123", "group_name": "群", "agent": "dsh"})
        with mock.patch.object(agent_mode.time, "sleep"), mock.patch.object(
            agent_mode, "enable"
        ) as enable:
            agent_mode.restore_all()
        enable.assert_called_once_with("x", "123", "群")


if __name__ == "__main__":
    unittest.main()
