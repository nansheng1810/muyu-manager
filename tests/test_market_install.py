import io
import json
import unittest
import zipfile
from unittest import mock

from server import api, market


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buf.getvalue()


class MarketMetadataRepairTest(unittest.TestCase):
    def test_inject_metadata_at_single_archive_root(self):
        raw = _zip({
            "astrbot_plugin_cloudmusic-abc/README.md": b"readme",
            "astrbot_plugin_cloudmusic-abc/main.py": b"print('ok')",
        })
        entry = {
            "name": "astrbot_plugin_cloudmusic",
            "display_name": "网易云音乐",
            "desc": "点歌与歌曲信息",
            "version": "1.0.0",
            "author": "mika",
            "repo": "https://github.com/AstrBot-Devs/astrbot_plugin_cloudmusic",
        }
        repaired = market.inject_metadata(raw, entry)
        with zipfile.ZipFile(io.BytesIO(repaired)) as archive:
            names = archive.namelist()
            meta_name = "astrbot_plugin_cloudmusic-abc/metadata.yaml"
            self.assertIn(meta_name, names)
            text = archive.read(meta_name).decode("utf-8")
        self.assertIn('name: "astrbot_plugin_cloudmusic"', text)
        self.assertIn('version: "1.0.0"', text)
        self.assertIn('author: "mika"', text)

    def test_inject_metadata_keeps_existing_metadata(self):
        raw = _zip({
            "plugin/metadata.yaml": b'name: "x"\ndesc: "y"\nversion: "1"\nauthor: "z"\n',
            "plugin/main.py": b"print('ok')",
        })
        self.assertEqual(market.inject_metadata(raw, {"name": "x"}), raw)

    def test_multipart_payload_contains_zip_file(self):
        body, content_type = market.multipart_payload(
            {"ignore_version_check": "true"}, "plugin.zip", b"ZIPDATA")
        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b'name="ignore_version_check"', body)
        self.assertIn(b'filename="plugin.zip"', body)
        self.assertIn(b"ZIPDATA", body)


class MarketInstallFallbackTest(unittest.TestCase):
    def test_market_install_retries_with_repaired_archive(self):
        raw = _zip({"plugin/main.py": b"print('ok')"})
        repaired = _zip({
            "plugin/metadata.yaml": b'name: "x"\ndesc: "y"\nversion: "1"\nauthor: "z"\n',
            "plugin/main.py": b"print('ok')",
        })
        entry = {
            "id": "owner/plugin", "name": "plugin", "author": "owner",
            "version": "1", "desc": "demo", "repo": "https://github.com/owner/plugin",
            "download_url": "https://example.test/plugin.zip",
        }
        # AstrBot 对旧包缺 metadata 回 HTTP 200 + status=error，管理器需自行下载确认。
        error = {"status": "error", "message": "插件操作失败，请查看服务端日志。",
                 "data": {}}
        with mock.patch.object(api, "_settings", return_value={}), \
                mock.patch.object(api, "_instances", return_value=[{"id": "i1"}]), \
                mock.patch.object(api.market, "find", return_value=entry), \
                mock.patch.object(api.dashboard, "call", return_value=error), \
                mock.patch.object(api.market, "download_archive", return_value=raw), \
                mock.patch.object(api.market, "inject_metadata", return_value=repaired), \
                mock.patch.object(api.dashboard, "upload_raw",
                                  return_value={"status": "ok", "message": "installed"}) as upload:
            result = api.market_install({
                "instance_id": "i1", "plugin_id": "owner/plugin"})
        self.assertEqual(result["status"], "ok")
        self.assertIn("metadata", result["message"])
        upload.assert_called_once()
        args = upload.call_args.args
        self.assertEqual(args[1], "plugins/install/upload")
        self.assertIn(b'filename="plugin.zip"', args[2])

    def test_market_install_keeps_error_when_archive_has_metadata(self):
        raw = _zip({
            "plugin/metadata.yaml": b'name: "x"\ndesc: "y"\nversion: "1"\nauthor: "z"\n',
            "plugin/main.py": b"print('ok')",
        })
        entry = {
            "id": "owner/plugin", "name": "plugin", "author": "owner",
            "version": "1", "desc": "demo", "repo": "https://github.com/owner/plugin",
            "download_url": "https://example.test/plugin.zip",
        }
        error = {"status": "error", "message": "插件操作失败，请查看服务端日志。",
                 "data": {}}
        with mock.patch.object(api, "_settings", return_value={}), \
                mock.patch.object(api, "_instances", return_value=[{"id": "i1"}]), \
                mock.patch.object(api.market, "find", return_value=entry), \
                mock.patch.object(api.dashboard, "call", return_value=error), \
                mock.patch.object(api.market, "download_archive", return_value=raw), \
                mock.patch.object(api.market, "inject_metadata", return_value=raw), \
                mock.patch.object(api.dashboard, "upload_raw") as upload:
            result = api.market_install({
                "instance_id": "i1", "plugin_id": "owner/plugin"})
        self.assertEqual(result.status_code, 502)
        self.assertIn("服务端日志", json.loads(result.body)["message"])
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()