import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import offsite


CONFIG = {
    "offsite_enabled": True,
    "offsite_url": "https://dav.example.com/files",
    "offsite_user": "me",
    "offsite_password": "secret",
    "offsite_dir": "muyu",
    "offsite_keep": 2,
}


class OffsiteTest(unittest.TestCase):
    def test_auth_header_and_dir_url(self):
        self.assertEqual(
            offsite._dir_url(CONFIG), "https://dav.example.com/files/muyu",
        )
        header = offsite._auth(CONFIG)
        self.assertTrue(header.startswith("Basic "))

    def test_parse_propfind(self):
        xml = b"""<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
          <d:response><d:href>/files/muyu/fleet-backup-1.zip</d:href>
            <d:propstat><d:prop><d:getcontentlength>100</d:getcontentlength>
              <d:getlastmodified>Sat, 07 Nov 2026 10:00:00 GMT</d:getlastmodified>
            </d:prop></d:propstat></d:response>
          <d:response><d:href>/files/muyu/</d:href></d:response>
        </d:multistatus>"""
        items = offsite._parse_propfind(xml)
        self.assertEqual(items[0]["name"], "fleet-backup-1.zip")
        self.assertEqual(items[0]["bytes"], 100)

    def test_upload_puts_zip_to_webdav(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "fleet-backup-1.zip"
            path.write_bytes(b"zipdata")
            with mock.patch.object(offsite.backup, "BACKUP_DIR", root), \
                    mock.patch.object(offsite.store, "load_settings", return_value=CONFIG), \
                    mock.patch.object(offsite, "_ensure_dir") as ensure, \
                    mock.patch.object(offsite, "_request", return_value=(201, b"")) as request, \
                    mock.patch.object(offsite, "_record") as record, \
                    mock.patch.object(offsite, "prune_remote", return_value=1):
                result = offsite.upload(str(path))
        ensure.assert_called_once()
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "PUT")
        self.assertTrue(request.call_args.args[1].endswith("fleet-backup-1.zip"))
        self.assertEqual(result["bytes"], 7)
        self.assertEqual(result["pruned"], 1)
        record.assert_called_once()

    def test_status_masks_password(self):
        class _Conn:
            def execute(self, *args):
                return self

            def fetchall(self):
                return []

        from contextlib import contextmanager

        @contextmanager
        def fake_session():
            yield _Conn()

        with mock.patch.object(offsite.store, "load_settings", return_value=CONFIG), \
                mock.patch.object(offsite.fleet_store, "session", fake_session), \
                mock.patch.object(offsite.backup, "list_backups", return_value=[]):
            status = offsite.status()
        self.assertTrue(status["has_password"])
        self.assertEqual(status["password_masked"], "••••")
        self.assertNotIn("secret", str(status))

    def test_auto_upload_disabled_returns_none(self):
        with mock.patch.object(offsite.store, "load_settings",
                               return_value={**CONFIG, "offsite_enabled": False}):
            self.assertIsNone(offsite.auto_upload_latest())

    def test_delete_remote_rejects_non_zip(self):
        with mock.patch.object(offsite.store, "load_settings", return_value=CONFIG):
            with self.assertRaises(offsite.OffsiteError):
                offsite.delete_remote("notes.txt")


if __name__ == "__main__":
    unittest.main()
