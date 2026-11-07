import unittest
from unittest import mock

from fastapi import HTTPException

from server import api, human_mode, mood, styles


class HumanApiRouteTest(unittest.TestCase):
    def setUp(self):
        self.inst = {"id": "i1", "name": "大肥鱼"}

    def test_routes_registered(self):
        paths = {getattr(route, "path", "") for route in api.app.routes}
        for path in ("/api/human/plan", "/api/human/status", "/api/human/settings",
                     "/api/human/styles", "/api/human/styles/{style_id}"):
            self.assertIn(path, paths)

    def test_plan_ok_and_errors(self):
        payload = {"instance_id": "i1", "text": "在吗"}
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.human_mode_mod, "plan",
                                  return_value={"action": "reply"}) as plan:
            result = api.human_plan(payload)
        plan.assert_called_once_with(payload, instances=[self.inst])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["action"], "reply")
        for exc in (human_mode.HumanError("坏参数"), mood.MoodError("未知实例")):
            with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                    mock.patch.object(api.human_mode_mod, "plan", side_effect=exc):
                failed = api.human_plan(payload)
            self.assertEqual(failed.status_code, 400)

    def test_status_requires_instance_and_wraps(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException) as ctx:
                api.human_status("nope")
        self.assertEqual(ctx.exception.status_code, 404)
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.human_mode_mod, "status",
                                  return_value={"events": []}) as status:
            result = api.human_status("i1")
        status.assert_called_once_with("i1")
        self.assertEqual(result["data"], {"events": []})

    def test_settings_requires_instance_and_maps_errors(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]):
            with self.assertRaises(HTTPException):
                api.human_settings_update({"instance_id": "nope"})
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.human_mode_mod, "save_settings",
                                  return_value={"shadow": True}) as save:
            result = api.human_settings_update({"instance_id": "i1", "shadow": False})
        save.assert_called_once_with({"instance_id": "i1", "shadow": False})
        self.assertEqual(result["status"], "ok")
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.human_mode_mod, "save_settings",
                                  side_effect=human_mode.HumanError("坏设置")):
            failed = api.human_settings_update({"instance_id": "i1"})
        self.assertEqual(failed.status_code, 400)

    def test_styles_list_ok(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.styles, "list_styles",
                                  return_value=[{"id": "s1"}]) as listed:
            result = api.human_styles("i1")
        listed.assert_called_once_with("i1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"], [{"id": "s1"}])

    def test_styles_create_success_passes_raw_enabled(self):
        payload = {"instance_id": "i1", "name": "n", "note": "内容"}
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.styles, "save_style",
                                  return_value={"id": "s1"}) as save:
            result = api.human_styles_create(payload)
        save.assert_called_once_with("i1", "n", "内容", scope="instance",
                                     person_key="", source="manual", enabled=True)
        self.assertEqual(result["status"], "ok")
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.styles, "save_style",
                                  return_value={"id": "s2"}) as save:
            api.human_styles_create({**payload, "enabled": False})
        self.assertIs(save.call_args.kwargs["enabled"], False)
        # 非法字符串必须原样下传，由 styles 抛 StyleError 映射为 400。
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.styles, "save_style",
                                  side_effect=styles.StyleError("enabled 必须是布尔值或 0/1")) as save:
            failed = api.human_styles_create({**payload, "enabled": "nope"})
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(save.call_args.kwargs["enabled"], "nope")

    def test_styles_create_maps_style_error(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.styles, "save_style",
                                  side_effect=styles.StyleError("内容为空")):
            failed = api.human_styles_create({"instance_id": "i1", "name": "n", "note": ""})
        self.assertEqual(failed.status_code, 400)

    def test_styles_delete_guards_instance(self):
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.styles, "get_style",
                                  return_value={"id": "s1", "instance_id": "other"}):
            failed = api.human_styles_delete("s1", "i1")
        self.assertEqual(failed.status_code, 404)
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
                mock.patch.object(api.styles, "get_style",
                                  return_value={"id": "s1", "instance_id": "i1"}), \
                mock.patch.object(api.styles, "delete_style", return_value=True) as delete:
            result = api.human_styles_delete("s1", "i1")
        delete.assert_called_once_with("s1")
        self.assertTrue(result["data"]["deleted"])


if __name__ == "__main__":
    unittest.main()
