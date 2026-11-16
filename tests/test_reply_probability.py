import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import agent_mode, reply_probability


class ReplyProbabilityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patch = mock.patch.object(
            reply_probability, "PROBABILITY_PATH", root / "reply_probability.json")
        self._patch.start()
        reply_probability._stats.clear()

    def tearDown(self):
        reply_probability._stats.clear()
        self._patch.stop()
        self._tmp.cleanup()

    def test_default_is_full_probability(self):
        self.assertEqual(reply_probability.get("unknown"), 1.0)

    def test_set_and_get_round_trip(self):
        self.assertEqual(reply_probability.set_probability("a", 0.02), 0.02)
        self.assertEqual(reply_probability.get("a"), 0.02)
        self.assertEqual(reply_probability.pct_to_ratio(2), 0.02)

    def test_probability_range_is_enforced(self):
        with self.assertRaises(reply_probability.ReplyProbabilityError):
            reply_probability.set_probability("a", 1.5)
        with self.assertRaises(reply_probability.ReplyProbabilityError):
            reply_probability.set_probability("", 0.5)
        with self.assertRaises(reply_probability.ReplyProbabilityError):
            reply_probability.pct_to_ratio(101)

    def test_zero_blocks_and_one_allows(self):
        reply_probability.set_probability("a", 0)
        self.assertFalse(reply_probability.should_deliver("a", "", []))
        reply_probability.set_probability("a", 1)
        self.assertTrue(reply_probability.should_deliver("a", "", []))

    def test_half_probability_uses_random(self):
        reply_probability.set_probability("a", 0.5)
        with mock.patch.object(reply_probability.random, "random", return_value=0.1):
            self.assertTrue(reply_probability.should_deliver("a", "", []))
        with mock.patch.object(reply_probability.random, "random", return_value=0.9):
            self.assertFalse(reply_probability.should_deliver("a", "", []))

    def test_mention_bypasses_probability(self):
        reply_probability.set_probability("a", 0.02)
        segments = [{"type": "at", "data": {"qq": "10001"}}]
        with mock.patch.object(reply_probability.random, "random", return_value=0.99):
            self.assertTrue(reply_probability.should_deliver("a", "10001", segments))
        flat = [{"type": "at", "qq": "10001"}]
        with mock.patch.object(reply_probability.random, "random", return_value=0.99):
            self.assertTrue(reply_probability.should_deliver("a", "10001", flat))
        other = [{"type": "at", "data": {"qq": "20002"}}]
        with mock.patch.object(reply_probability.random, "random", return_value=0.99):
            self.assertFalse(reply_probability.should_deliver("a", "10001", other))

    def test_zero_probability_ignores_mention(self):
        reply_probability.set_probability("a", 0)
        segments = [{"type": "at", "data": {"qq": "10001"}}]
        self.assertFalse(reply_probability.should_deliver("a", "10001", segments))

    def test_stats_count_decisions(self):
        reply_probability.set_probability("a", 0)
        reply_probability.should_deliver("a", "", [])
        reply_probability.set_probability("a", 1)
        reply_probability.should_deliver("a", "", [])
        row = reply_probability._stats["a"]
        self.assertEqual(row["delivered"], 1)
        self.assertEqual(row["dropped"], 1)

    def test_snapshot_degrades_when_agent_mode_fails(self):
        reply_probability.set_probability("a", 0.02)
        with mock.patch.object(agent_mode, "status", side_effect=RuntimeError("boom")):
            data = reply_probability.snapshot([{"id": "a", "name": "大肥鱼"}])
        self.assertEqual(len(data["instances"]), 1)
        row = data["instances"][0]
        self.assertEqual(row["agent_probability_pct"], 2.0)
        self.assertFalse(row["agent_mode"]["enabled"])
        self.assertEqual(row["stats"]["delivered"], 0)


if __name__ == "__main__":
    unittest.main()
