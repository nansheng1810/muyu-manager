"""自动学习关键行为的回归测试（不联网、不写线上人格）。"""
import unittest
from unittest.mock import patch

from server import learn, learn_auto, persona


class BotFilterTests(unittest.TestCase):
    def test_sender_id_filters_all_fleet_bots(self):
        inst = {"name": "大肥鱼", "qq": "10001"}
        ids = frozenset({"10001", "10002"})
        with patch.object(learn, "bot_ids", return_value=ids):
            self.assertTrue(learn._is_bot_sender("另一个机器人", inst, "10002"))
            self.assertTrue(learn._is_bot_sender("AstrBot", inst, "10001"))
            self.assertFalse(learn._is_bot_sender("另一个机器人", inst, "10003"))
            # 普通群友的名字里带「大肥鱼」，不能按子串误杀
            self.assertFalse(learn._is_bot_sender("路人甲大肥鱼", inst, "10004"))

    def test_exact_name_fallback(self):
        inst = {"name": "大肥鱼", "qq": "10001"}
        with patch.object(learn, "bot_ids", return_value=frozenset()):
            self.assertTrue(learn._is_bot_sender("大肥鱼", inst))
            self.assertTrue(learn._is_bot_sender("AstrBot", inst))
            self.assertFalse(learn._is_bot_sender("另一个机器人", inst))


class NoteValidationTests(unittest.TestCase):
    def test_empty_or_truncated_note_rejected(self):
        bad = "> 说明：记录中未出现独立昵称「南笙」的发言。\n\n## 语言风格\n\n- **空"
        self.assertTrue(learn_auto.note_problem(bad))

    def test_complete_note_accepted(self):
        good = (
            "## 语言风格\n" + "- 短句、口语化、常带语气词。\n" * 12 +
            "\n## 口头禅与语气词\n- 哈哈哈、好耶、饿。\n" * 6 +
            "\n## 标点与表情习惯\n- 很少用句号，偶尔用问号。\n" * 6 +
            "\n## 话题偏好\n- 吃喝、游戏、日常。\n" * 6 +
            "\n## 情绪与互动方式\n- 先安抚再回应。\n" * 6 +
            "\n## 可直接用于风格档案的说明\n" + "说话短、轻快、具体，不要客服腔。" * 12
        )
        self.assertEqual(learn_auto.note_problem(good), "")

    def test_legacy_note_heading_still_accepted(self):
        good = (
            "## 语言风格\n" + "- 短句、口语化、常带语气词。\n" * 12 +
            "\n## 口头禅与语气词\n- 哈哈哈、好耶、饿。\n" * 6 +
            "\n## 标点与表情习惯\n- 很少用句号，偶尔用问号。\n" * 6 +
            "\n## 话题偏好\n- 吃喝、游戏、日常。\n" * 6 +
            "\n## 情绪与互动方式\n- 先安抚再回应。\n" * 6 +
            "\n## 可直接写入人格的风格说明\n" + "说话短、轻快、具体，不要客服腔。" * 12
        )
        self.assertEqual(learn_auto.note_problem(good), "")


class PersonaBlockTests(unittest.TestCase):
    def test_extract_and_strip(self):
        prompt = (
            "hello\n\n<!-- AUTO-LEARN:BEGIN -->\n"
            "## 自动学习到的说话风格\n- x\n<!-- AUTO-LEARN:END -->\n"
        )
        self.assertIn("AUTO-LEARN:BEGIN", persona.extract_auto_block(prompt))
        self.assertEqual(persona.strip_auto_block(prompt), "hello")

    def test_extract_auto_blocks_returns_all(self):
        prompt = (
            "hello\n\n<!-- AUTO-LEARN:BEGIN -->\n- 一\n<!-- AUTO-LEARN:END -->\n\n"
            "<!-- AUTO-LEARN:BEGIN -->\n- 二\n<!-- AUTO-LEARN:END -->"
        )
        blocks = persona.extract_auto_blocks(prompt)
        self.assertEqual(len(blocks), 2)
        self.assertIn("- 一", blocks[0])
        self.assertIn("- 二", blocks[1])
        self.assertEqual(persona.extract_auto_block(prompt), blocks[0])
        self.assertEqual(persona.strip_auto_block(prompt), "hello")

    def test_restore_drops_historical_auto_block(self):
        inst = {"id": "x", "name": "大肥鱼"}
        historical = "旧内容\n\n<!-- AUTO-LEARN:BEGIN -->\n- 旧脏笔记\n<!-- AUTO-LEARN:END -->"
        with patch.object(persona, "get_version", return_value=historical), \
             patch.object(persona, "current_prompt", return_value="当前内容"), \
             patch.object(persona, "snapshot"), \
             patch.object(persona, "_save_remote") as save:
            persona.restore(inst, "大肥鱼", 123)
            saved = save.call_args[0][2]
        self.assertNotIn("AUTO-LEARN", saved)
        self.assertIn("旧内容", saved)

    def test_restore_keeps_current_auto_block_only(self):
        inst = {"id": "x", "name": "大肥鱼"}
        historical = "旧内容\n\n<!-- AUTO-LEARN:BEGIN -->\n- 旧脏笔记\n<!-- AUTO-LEARN:END -->"
        current = "当前内容\n\n<!-- AUTO-LEARN:BEGIN -->\n- 当前有效笔记\n<!-- AUTO-LEARN:END -->"
        with patch.object(persona, "get_version", return_value=historical), \
             patch.object(persona, "current_prompt", return_value=current), \
             patch.object(persona, "snapshot"), \
             patch.object(persona, "_save_remote") as save:
            persona.restore(inst, "大肥鱼", 123)
            saved = save.call_args[0][2]
        self.assertIn("当前有效笔记", saved)
        self.assertNotIn("旧脏笔记", saved)

    def test_choose_persona_never_falls_back_to_default(self):
        inst = {"name": "小X"}
        people = [{"persona_id": "default"}, {"persona_id": "大肥鱼"}]
        self.assertEqual(persona.choose_persona_id(inst, people), "大肥鱼")
        self.assertEqual(
            persona.choose_persona_id(inst, [{"persona_id": "default"}]), ""
        )
        self.assertEqual(
            persona.choose_persona_id(
                inst, [{"persona_id": "default"}], allow_default=True
            ),
            "default",
        )
        self.assertEqual(
            persona.choose_persona_id({"name": "大肥鱼"}, people, "大肥鱼"), "大肥鱼"
        )


class AutoLearnStyleTest(unittest.TestCase):
    """自动学习只保存风格档案，任何情况下都不写人格。"""

    inst = {"id": "i1", "name": "大肥鱼"}
    messages = [
        {"sender": "A", "text": f"消息{i}", "time": f"2026-11-04 10:0{i}"}
        for i in range(8)
    ]

    def _run_patched(self, dry_run: bool):
        """带全部 IO 桩跑一轮学习，返回保存/记录/远程调用三个 mock。"""
        from contextlib import ExitStack
        from unittest import mock

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(learn_auto, "_load", return_value={}))
            stack.enter_context(
                mock.patch.object(
                    learn_auto, "_summarize_note", return_value="## 语言风格\n短句。"
                )
            )
            stack.enter_context(
                mock.patch.object(
                    learn_auto,
                    "_pick_sources",
                    return_value=[{"kind": "qq", "key": "k", "label": "QQ"}],
                )
            )
            stack.enter_context(
                mock.patch.object(learn_auto, "note_problem", return_value="")
            )
            stack.enter_context(
                mock.patch.object(learn_auto, "_current_provider", return_value="prov-1")
            )
            stack.enter_context(
                mock.patch.object(learn_auto.learn, "sample", return_value=self.messages)
            )
            save_style = stack.enter_context(
                mock.patch.object(learn_auto.styles, "save_auto_style")
            )
            record = stack.enter_context(
                mock.patch.object(learn_auto.AutoLearn, "_record")
            )
            stack.enter_context(mock.patch.object(learn_auto, "_trace"))
            dashboard_call = stack.enter_context(
                mock.patch.object(learn_auto.dashboard, "call")
            )
            learn_auto.AutoLearn()._run_once(self.inst, force=True, dry_run=dry_run)
        return save_style, record, dashboard_call

    def test_auto_learn_does_not_write_persona(self):
        save_style, record, dashboard_call = self._run_patched(dry_run=False)
        save_style.assert_called_once_with("i1", "自动学习", "## 语言风格\n短句。")
        dashboard_call.assert_not_called()
        self.assertNotIn("persona", record.call_args.kwargs)

    def test_dry_run_previews_without_saving_style(self):
        save_style, record, dashboard_call = self._run_patched(dry_run=True)
        save_style.assert_not_called()
        dashboard_call.assert_not_called()
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["status"], "preview")
        self.assertIn("风格档案", record.call_args.kwargs["message"])


if __name__ == "__main__":
    unittest.main()
