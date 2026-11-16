import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher


class LauncherLoggingTests(unittest.TestCase):
    def test_redirect_stdio_writes_to_file(self):
        old_out, old_err = sys.stdout, sys.stderr
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with patch.object(launcher, "ROOT", Path(tmp)):
                    launcher.redirect_stdio()
                    print("hello-stdio")
                    sys.stdout.flush()
                    target = Path(tmp) / "data" / "logs" / "server.log"
                    self.assertTrue(target.exists())
                    self.assertIn(
                        "hello-stdio", target.read_text(encoding="utf-8"))
                    stream = sys.stdout
                    sys.stdout, sys.stderr = old_out, old_err
                    stream.close()
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def test_write_runtime_exposes_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                path = launcher.write_runtime(7312)
                self.assertEqual(
                    path,
                    Path(tmp) / "AstrBot舰队管理器" / "data" / "manager_runtime.json",
                )
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["port"], 7312)
                self.assertEqual(data["url"], "http://127.0.0.1:7312")


if __name__ == "__main__":
    unittest.main()
