import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from server import digest


def sample_health():
    return {
        "overall": "warn",
        "generated_at": 1790000000,
        "counts": {"ok": 1, "warn": 1, "bad": 0},
        "components": [
            {"id": "manager", "label": "管理器", "status": "ok", "summary": "可写", "route": ""},
            {"id": "dsh", "label": "DSH", "status": "warn", "summary": "未运行", "route": "#/dsh"},
        ],
    }


class DigestTest(unittest.TestCase):
    def test_day_bounds_default_and_explicit(self):
        now = datetime(2026, 11, 3, 14, 35).timestamp()
        start, end, label = digest.day_bounds(now=now)
        self.assertEqual(label, "2026-11-03")
        self.assertEqual(end - start, 86400)
        self.assertEqual(datetime.fromtimestamp(start).hour, 0)
        start2, end2, label2 = digest.day_bounds("2026-10-31", now=now)
        self.assertEqual(label2, "2026-10-31")
        self.assertEqual(end2 - start2, 86400)

    def test_day_bounds_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            digest.day_bounds("2026/11/03")

    def test_build_and_markdown(self):
        data = digest.build(
            "2026-11-03",
            sample_health(),
            [
                {"id": "a", "name": "大肥鱼", "running": True, "dashboard_ready": True},
                {"id": "b", "name": "千问", "running": False, "dashboard_ready": False},
            ],
            [{"ts": 1790000000, "title": "任务完成：每日备份", "severity": "info"}],
            {"total": 2, "counts": {"approved": 1, "pending": 1}, "pending_total": 3, "items": []},
            {"total": 1, "counts": {"success": 1}, "items": [
                {"task_name": "每日备份", "status": "success", "summary": "备份完成", "started": 1790000000},
            ]},
            {"total": 1, "items": []},
            generated_at=1790000000,
        )
        self.assertEqual(data["fleet"]["online"], 1)
        self.assertEqual(data["counts"]["task_runs"], 1)
        text = digest.markdown(data)
        self.assertIn("# 舰队日报 · 2026-11-03", text)
        self.assertIn("1 / 2 在线", text)
        self.assertIn("每日备份", text)
        self.assertIn("DSH", text)

    def test_markdown_empty_sections(self):
        data = digest.build(
            "2026-11-03", sample_health(), [], [], {"total": 0, "items": []},
            {"total": 0, "items": []}, {"total": 0, "items": []},
        )
        text = digest.markdown(data)
        self.assertIn("未接入实例", text)
        self.assertIn("今日没有审批记录", text)
        self.assertIn("今日没有任务运行", text)
        self.assertIn("暂无事件", text)


if __name__ == "__main__":
    unittest.main()
