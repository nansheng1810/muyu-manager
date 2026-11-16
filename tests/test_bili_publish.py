import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from server import bili_publish
from server import bili_cli


class BiliPublishHelperTests(unittest.TestCase):
    def test_safe_name_strips_paths_and_forces_video_suffix(self):
        self.assertEqual(bili_publish._safe_name("../../clip.mp4"), "clip.mp4")
        self.assertEqual(bili_publish._safe_name("clip.exe"), "clip.mp4")
        self.assertEqual(bili_publish._safe_name(""), "video.mp4")

    def test_history_merges_auto_and_legacy_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "data" / "plugin_data" / bili_publish.PLUGIN_ID
            base.mkdir(parents=True)
            (base / "video_publish_log.json").write_text(json.dumps([
                {"time": "2026-11-09 20:00", "title": "自动", "bvid": "BV2"},
            ], ensure_ascii=False), encoding="utf-8")
            (base / "creative_publish_log.json").write_text(json.dumps([
                {"published_at": "2026-11-08 10:00", "title": "旧创作", "bvid": "BV1"},
            ], ensure_ascii=False), encoding="utf-8")
            (base / "creative_pending.json").write_text(json.dumps({
                "title": "待发布", "video_path": str(base / "missing.mp4"),
                "publish_error": "601",
            }, ensure_ascii=False), encoding="utf-8")
            inst = {"id": "i1", "root": tmp}
            with mock.patch.object(bili_publish, "_instance", return_value=inst):
                result = bili_publish.bili_publish_history("i1", 30)["data"]
        self.assertEqual([item["title"] for item in result["items"]], ["自动", "旧创作"])
        self.assertEqual(result["items"][0]["source"], "自动发布")
        self.assertEqual(result["legacy_pending"]["title"], "待发布")
        self.assertFalse(result["legacy_pending"]["exists"])

    def test_status_reports_missing_binary(self):
        with mock.patch.object(
            bili_cli, "resolve_executable",
            side_effect=bili_cli.BiliCliError("not_installed", "未找到", "安装"),
        ):
            data = bili_publish._status_payload()
        self.assertFalse(data["installed"])
        self.assertIn("安装", data["hint"])


class BiliPublishJobTests(unittest.TestCase):
    def test_upload_job_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            video.write_bytes(b"x")
            with mock.patch.object(
                bili_publish.bili_cli, "upload",
                return_value={"bvid": "BV1xx", "aid": 1},
            ):
                job = bili_publish._start_job(
                    "i1", video, "标题", ["AI"], "", 47)
                deadline = time.time() + 3
                while job["status"] in ("queued", "running") and time.time() < deadline:
                    time.sleep(0.02)
        self.assertEqual(job["status"], "success")
        self.assertEqual(job["bvid"], "BV1xx")


class ProxyEnvTests(unittest.TestCase):
    def test_bracketed_ipv6_is_removed_from_no_proxy(self):
        env = {"NO_PROXY": "localhost,[::1],127.0.0.1"}
        bili_cli._sanitize_proxy_env(env)
        self.assertNotIn("[", env["NO_PROXY"])
        self.assertIn("localhost", env["NO_PROXY"])


if __name__ == "__main__":
    unittest.main()
