import unittest
from unittest import mock

from server import notify


def alert(alert_id, severity="warning", title="标题", summary="摘要"):
    return {"id": alert_id, "severity": severity, "title": title, "summary": summary}


class NotifyTest(unittest.TestCase):
    def test_message_lists_alerts_and_truncates(self):
        result = {"counts": {"total": 3}, "overall": "warning", "alerts": [
            alert("a", "critical", "B站离线", "账号未连接"),
            alert("b", "warning", "磁盘", "可用 6%"),
            alert("c", "warning", "备份", "超过 48 小时"),
        ]}
        text = notify.message_for(result, limit=2)
        self.assertIn("3 项待处理", text)
        self.assertIn("[严重] B站离线：账号未连接", text)
        self.assertNotIn("备份", text)
        self.assertIn("还有 1 项", text)

    def test_filter_new_dedupes_until_ttl(self):
        state = {}
        result = {"alerts": [alert("a"), alert("b")]}
        fresh, state = notify.filter_new(result, state, now=1000)
        self.assertEqual([item["id"] for item in fresh], ["a", "b"])
        fresh, state = notify.filter_new(result, state, now=1001)
        self.assertEqual(fresh, [])
        fresh, state = notify.filter_new(result, state, now=1000 + notify.DEDUPE_SECONDS + 1)
        self.assertEqual([item["id"] for item in fresh], ["a", "b"])

    def test_deliver_reports_channels(self):
        calls = []

        def fake_post(url, payload, timeout=15):
            calls.append((url, payload))

        with mock.patch.object(notify, "_post_json", side_effect=fake_post):
            statuses = notify.deliver(
                "hello",
                {"overall": "warning", "alerts": [alert("a")]},
                {"webhook": "http://127.0.0.1/hook", "telegram_token": "t", "telegram_chat_id": "c"},
            )
        self.assertEqual(statuses, {"webhook": "ok", "telegram": "ok"})
        self.assertEqual(len(calls), 2)
        self.assertIn("text", calls[0][1])

    def test_channels_requires_both_telegram_fields(self):
        self.assertEqual(notify.channels({"webhook": "", "telegram_token": "t", "telegram_chat_id": ""}), [])
        self.assertEqual(notify.channels({"webhook": "http://x", "telegram_token": "t", "telegram_chat_id": "c"}), ["webhook", "telegram"])


if __name__ == "__main__":
    unittest.main()
