import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import styles


class StyleStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "fleet.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_list_update_delete(self):
        item = styles.save_style(
            "i1", "大肥鱼口吻", "## 语言风格\n短句、口语化。", db_path=self.db
        )
        self.assertEqual(item["name"], "大肥鱼口吻")
        self.assertEqual(item["enabled"], 1)
        listed = styles.list_styles("i1", db_path=self.db)
        self.assertEqual(len(listed), 1)
        updated = styles.update_style(item["id"], {"enabled": False, "name": "新名字"}, db_path=self.db)
        self.assertEqual(updated["enabled"], 0)
        self.assertEqual(updated["name"], "新名字")
        self.assertTrue(styles.delete_style(item["id"], db_path=self.db))
        self.assertEqual(styles.list_styles("i1", db_path=self.db), [])

    def test_relationship_scope_requires_person_key(self):
        with self.assertRaises(styles.StyleError):
            styles.save_style("i1", "x", "note", scope="relationship", db_path=self.db)

    def test_auto_style_appends_same_name(self):
        first = styles.save_auto_style("i1", "自动学习", "第一版", db_path=self.db)
        second = styles.save_auto_style("i1", "自动学习", "第二版", db_path=self.db)
        self.assertEqual(first["id"], second["id"])
        note = styles.get_style(first["id"], db_path=self.db)["note"]
        self.assertIn("第一版", note)
        self.assertIn("第二版", note)
        self.assertLess(note.index("第一版"), note.index("第二版"))
        self.assertIn("## 自动学习 · ", note)

    def test_auto_style_append_preserves_disabled(self):
        item = styles.save_style("i1", "自动学习", "第一版", source="auto", db_path=self.db)
        styles.update_style(item["id"], {"enabled": False}, db_path=self.db)
        updated = styles.save_auto_style("i1", "自动学习", "第二版", db_path=self.db)
        self.assertEqual(updated["id"], item["id"])
        self.assertIn("第一版", updated["note"])
        self.assertIn("第二版", updated["note"])
        self.assertEqual(updated["enabled"], 0)
        self.assertEqual(styles.style_prompt("i1", db_path=self.db), "")

    def test_append_note_trims_oldest_sections(self):
        item = styles.save_style("i1", "长档案", "开头", db_path=self.db)
        for index in range(30):
            item = styles.append_style_note(
                item["id"], f"第{index}版" + "长" * 500, label="自动学习",
                db_path=self.db)
        self.assertLessEqual(len(item["note"]), styles.MAX_NOTE)
        self.assertIn("第29版", item["note"])
        self.assertIn("开头", item["note"])

    def test_style_prompt_prefers_newest_appended_section(self):
        item = styles.save_style("i1", "长档案", "旧" * 2000, db_path=self.db)
        styles.append_style_note(item["id"], "最新观察" + "新" * 2000,
                                 label="自动学习", db_path=self.db)
        prompt = styles.style_prompt("i1", db_path=self.db)
        self.assertIn("最新观察", prompt)
        self.assertNotIn("旧旧旧旧旧", prompt)

    def test_style_prompt_prefers_relationship_then_instance(self):
        styles.save_style("i1", "实例风格", "实例内容", source="manual", db_path=self.db)
        styles.save_style("i1", "关系风格", "关系内容", scope="relationship",
                          person_key="p1", source="manual", db_path=self.db)
        prompt = styles.style_prompt("i1", "p1", db_path=self.db)
        self.assertIn("关系内容", prompt)
        self.assertIn("实例内容", prompt)
        self.assertLess(prompt.index("关系内容"), prompt.index("实例内容"))

    def test_style_prompt_caps_length(self):
        styles.save_style("i1", "长风格", "长" * 3000, db_path=self.db)
        prompt = styles.style_prompt("i1", db_path=self.db)
        self.assertTrue(prompt.startswith("【说话风格】"))
        self.assertLessEqual(len(prompt), 1200)

    def test_style_prompt_excludes_disabled(self):
        styles.save_style("i1", "关闭的风格", "不应出现", enabled=False, db_path=self.db)
        self.assertEqual(styles.style_prompt("i1", db_path=self.db), "")

    def test_style_prompt_excludes_other_or_empty_person_key(self):
        styles.save_style("i1", "甲关系", "甲内容", scope="relationship",
                          person_key="p1", db_path=self.db)
        styles.save_style("i1", "乙关系", "乙内容", scope="relationship",
                          person_key="p2", db_path=self.db)
        self.assertEqual(styles.style_prompt("i1", "", db_path=self.db), "")
        prompt = styles.style_prompt("i1", "p2", db_path=self.db)
        self.assertIn("乙内容", prompt)
        self.assertNotIn("甲内容", prompt)

    def test_style_prompt_isolated_per_instance(self):
        styles.save_style("i1", "实例一", "实例一内容", db_path=self.db)
        styles.save_style("i2", "实例二", "实例二内容", db_path=self.db)
        prompt = styles.style_prompt("i1", db_path=self.db)
        self.assertIn("实例一内容", prompt)
        self.assertNotIn("实例二内容", prompt)

    def test_update_missing_id_raises(self):
        with self.assertRaises(styles.StyleError):
            styles.update_style("sty_missing", {"name": "x"}, db_path=self.db)

    def test_delete_missing_returns_false(self):
        self.assertFalse(styles.delete_style("sty_missing", db_path=self.db))

    def test_oversized_note_rejected_on_save_and_update(self):
        with self.assertRaises(styles.StyleError):
            styles.save_style("i1", "超长", "长" * (styles.MAX_NOTE + 1), db_path=self.db)
        self.assertEqual(styles.list_styles("i1", db_path=self.db), [])
        item = styles.save_style("i1", "正常", "正常内容", db_path=self.db)
        with self.assertRaises(styles.StyleError):
            styles.update_style(item["id"], {"note": "长" * (styles.MAX_NOTE + 1)}, db_path=self.db)
        self.assertEqual(styles.get_style(item["id"], db_path=self.db)["note"], "正常内容")

    def test_update_rejects_non_string_and_empty_fields(self):
        item = styles.save_style("i1", "原名", "原内容", db_path=self.db)
        for patch in ({"name": None}, {"note": None}, {"name": 123},
                      {"name": "  "}, {"note": ""}, {"person_key": None}):
            with self.assertRaises(styles.StyleError, msg=str(patch)):
                styles.update_style(item["id"], patch, db_path=self.db)
        stored = styles.get_style(item["id"], db_path=self.db)
        self.assertEqual(stored["name"], "原名")
        self.assertEqual(stored["note"], "原内容")
        self.assertEqual(stored["person_key"], "")

    def test_update_enabled_rejects_non_bool(self):
        item = styles.save_style("i1", "开关", "内容", enabled=False, db_path=self.db)
        with self.assertRaises(styles.StyleError):
            styles.update_style(item["id"], {"enabled": "false"}, db_path=self.db)
        self.assertEqual(styles.get_style(item["id"], db_path=self.db)["enabled"], 0)
        self.assertEqual(styles.update_style(item["id"], {"enabled": 1}, db_path=self.db)["enabled"], 1)
        self.assertEqual(styles.update_style(item["id"], {"enabled": False}, db_path=self.db)["enabled"], 0)


class LearnApplyStyleTest(unittest.TestCase):
    def test_apply_note_saves_style_not_persona(self):
        from server import api
        inst = {"id": "i1", "name": "大肥鱼"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "list_styles", return_value=[]), \
             mock.patch.object(api.styles, "save_style",
                               return_value={"id": "sty_1", "name": "手动学习"}) as save, \
             mock.patch.object(api, "dashboard") as dashboard:
            result = api.learn_apply("i1", {"note": "## 语言风格\n短句。", "name": "手动学习"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["style"]["id"], "sty_1")
        save.assert_called_once()
        dashboard.call.assert_not_called()

    def test_apply_marks_persona_unchanged_and_passes_scope(self):
        from server import api
        inst = {"id": "i1", "name": "大肥鱼"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "list_styles", return_value=[]), \
             mock.patch.object(api.styles, "save_style",
                               return_value={"id": "sty_2"}) as save:
            result = api.learn_apply("i1", {"note": "内容", "scope": "relationship",
                                            "person_key": "p1"})
        self.assertTrue(result["data"]["persona_unchanged"])
        self.assertEqual(save.call_args.kwargs["scope"], "relationship")
        self.assertEqual(save.call_args.kwargs["person_key"], "p1")
        self.assertEqual(save.call_args.kwargs["source"], "manual")
        self.assertEqual(save.call_args.args[0], "i1")

    def test_apply_empty_note_rejected(self):
        from server import api
        inst = {"id": "i1", "name": "大肥鱼"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "save_style") as save:
            result = api.learn_apply("i1", {"note": "   "})
        self.assertEqual(result.status_code, 400)
        save.assert_not_called()

    def test_apply_style_error_becomes_400(self):
        from server import api
        inst = {"id": "i1", "name": "大肥鱼"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "list_styles", return_value=[]), \
             mock.patch.object(api.styles, "save_style",
                               side_effect=styles.StyleError("作用域无效")):
            result = api.learn_apply("i1", {"note": "内容", "scope": "bad"})
        self.assertEqual(result.status_code, 400)
        self.assertIn("作用域无效", result.body.decode("utf-8"))

    def test_apply_updates_existing_same_name_manual_style(self):
        from server import api
        inst = {"id": "i1", "name": "大肥鱼"}
        existing = {"id": "sty_old", "instance_id": "i1", "name": "手动学习",
                    "source": "manual", "scope": "relationship", "person_key": "p1"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "list_styles", return_value=[existing]) as listed, \
             mock.patch.object(api.styles, "append_style_note",
                               return_value={"id": "sty_old", "note": "新内容"}) as append, \
             mock.patch.object(api.styles, "save_style") as save:
            result = api.learn_apply("i1", {"note": "新内容", "name": "手动学习",
                                            "scope": "relationship", "person_key": "p1"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["style"]["id"], "sty_old")
        self.assertTrue(result["data"]["appended"])
        listed.assert_called_once_with("i1")
        # 同名只追加，保留原 scope/person_key/enabled，避免关系级档案被转成实例级
        self.assertEqual(append.call_args.args, ("sty_old", "新内容"))
        self.assertEqual(append.call_args.kwargs.get("label"), "手动学习")
        save.assert_not_called()

    def test_apply_same_name_never_overwrites_other_scope(self):
        from server import api
        inst = {"id": "i1", "name": "大肥鱼"}
        existing = [
            {"id": "sty_inst", "instance_id": "i1", "name": "手动学习",
             "source": "manual", "scope": "instance", "person_key": ""},
            {"id": "sty_a", "instance_id": "i1", "name": "手动学习",
             "source": "manual", "scope": "relationship", "person_key": "A"},
        ]
        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "list_styles", return_value=existing), \
             mock.patch.object(api.styles, "update_style") as update, \
             mock.patch.object(api.styles, "save_style",
                               return_value={"id": "sty_b"}) as save:
            result = api.learn_apply("i1", {"note": "B 的私聊笔记", "name": "手动学习",
                                            "scope": "relationship", "person_key": "B"})
        self.assertEqual(result["status"], "ok")
        # B 的私聊笔记既不能覆盖实例级档案，也不能覆盖 A 的关系级档案。
        update.assert_not_called()
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs["person_key"], "B")

        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "list_styles", return_value=existing), \
             mock.patch.object(api.styles, "append_style_note",
                               return_value={"id": "sty_a"}) as append, \
             mock.patch.object(api.styles, "save_style") as save:
            result = api.learn_apply("i1", {"note": "A 的笔记", "name": "手动学习",
                                            "scope": "relationship", "person_key": "A"})
        self.assertEqual(result["data"]["style"]["id"], "sty_a")
        # 只有 scope 与 person_key 都命中 A 时才追加到 A。
        self.assertEqual(append.call_args.args, ("sty_a", "A 的笔记"))
        save.assert_not_called()

    def test_apply_same_name_auto_style_does_not_dedupe(self):
        from server import api
        inst = {"id": "i1", "name": "大肥鱼"}
        auto = {"id": "sty_auto", "instance_id": "i1", "name": "手动学习",
                "source": "auto"}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "list_styles", return_value=[auto]), \
             mock.patch.object(api.styles, "update_style") as update, \
             mock.patch.object(api.styles, "save_style",
                               return_value={"id": "sty_new"}) as save:
            result = api.learn_apply("i1", {"note": "内容", "name": "手动学习"})
        self.assertEqual(result["status"], "ok")
        update.assert_not_called()
        save.assert_called_once()

    def test_apply_update_error_becomes_400(self):
        from server import api
        inst = {"id": "i1", "name": "大肥鱼"}
        existing = {"id": "sty_old", "instance_id": "i1", "name": "手动学习",
                    "source": "manual", "scope": "instance", "person_key": ""}
        with mock.patch.object(api, "_instances", return_value=[inst]), \
             mock.patch.object(api.styles, "list_styles", return_value=[existing]), \
             mock.patch.object(api.styles, "append_style_note",
                               side_effect=styles.StyleError("追加失败")):
            result = api.learn_apply("i1", {"note": "内容", "name": "手动学习"})
        self.assertEqual(result.status_code, 400)
        self.assertIn("追加失败", result.body.decode("utf-8"))


class LearnSummarizeAutoSaveTest(unittest.TestCase):
    inst = {"id": "i1", "name": "大肥鱼"}
    valid_note = (
        "## 语言风格\n" + "短句，口语化，偶尔反问。" * 10 + "\n"
        "## 口头禅与语气词\n" + "好家伙、行吧。" * 10 + "\n"
        "## 标点与表情习惯\n" + "常用省略号和问号。" * 10 + "\n"
        "## 话题偏好\n" + "车队、日常、游戏。" * 10 + "\n"
        "## 情绪与互动方式\n" + "先接话再表达观点。" * 10 + "\n"
        "## 可直接用于风格档案的说明\n" + "说话像朋友聊天，短句为主，别用客服腔。" * 10
    )

    def _call(self, note, save=True, existing=None, appended=None):
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.learn, "sample",
                               return_value=[{"sender": "A", "text": "你好"}]), \
             mock.patch.object(api.llm, "chat", return_value=note), \
             mock.patch.object(api.styles, "list_styles", return_value=existing or []), \
             mock.patch.object(api.styles, "save_style",
                               return_value={"id": "sty_new"}) as save_style, \
             mock.patch.object(api.styles, "append_style_note",
                               return_value=appended or {"id": "sty_old"}) as append:
            result = api.learn_summarize("i1", {
                "source": "qq", "key": "qq:10001", "speaker": "",
                "limit": 50, "provider_id": "p1", "save": save,
                "name": "手动学习", "scope": "relationship", "person_key": "10001",
            })
        return result, save_style, append

    def test_summarize_creates_first_style(self):
        result, save_style, append = self._call(self.valid_note)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["saved"])
        self.assertFalse(result["data"]["appended"])
        save_style.assert_called_once()
        append.assert_not_called()

    def test_summarize_appends_existing_style(self):
        existing = [{"id": "sty_old", "instance_id": "i1", "name": "手动学习",
                     "source": "manual", "scope": "relationship", "person_key": "10001"}]
        result, save_style, append = self._call(self.valid_note, existing=existing)
        self.assertTrue(result["data"]["saved"])
        self.assertTrue(result["data"]["appended"])
        append.assert_called_once()
        save_style.assert_not_called()

    def test_summarize_invalid_note_is_not_saved(self):
        result, save_style, append = self._call("太短了")
        self.assertFalse(result["data"]["saved"])
        self.assertIn("未通过校验", result["data"]["save_error"])
        save_style.assert_not_called()
        append.assert_not_called()

    def test_summarize_without_save_does_not_write(self):
        result, save_style, append = self._call(self.valid_note, save=False)
        self.assertFalse(result["data"]["saved"])
        save_style.assert_not_called()
        append.assert_not_called()


class MigrateTest(unittest.TestCase):
    """旧自动块迁移：先存风格档案，再清人格；失败回滚档案。"""

    inst = {"id": "i1", "name": "大肥鱼"}
    block = (
        "<!-- AUTO-LEARN:BEGIN -->\n"
        "## 自动学习到的说话风格\n- 短句、口语化。\n"
        "<!-- AUTO-LEARN:END -->"
    )

    def test_migrate_route_is_registered(self):
        from server import api
        routes = {
            (route.path, tuple(sorted(route.methods or [])))
            for route in api.app.routes
            if getattr(route, "path", "") == "/api/instances/{inst_id}/styles/migrate-persona"
        }
        self.assertIn(
            ("/api/instances/{inst_id}/styles/migrate-persona", ("POST",)), routes)

    def test_migrate_saves_style_then_clears_persona(self):
        from server import api
        order = []
        saved = {"id": "sty_1", "name": "旧人格自动学习"}
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt",
                               return_value="人格正文\n\n" + self.block) as current, \
             mock.patch.object(api.persona_mod, "extract_auto_blocks",
                               return_value=[self.block]) as extract, \
             mock.patch.object(api.persona_mod, "clear_auto_block",
                               side_effect=lambda *a, **k: order.append("clear") or {"removed": True}) as clear, \
             mock.patch.object(api.styles, "save_style",
                               side_effect=lambda *a, **k: order.append("save") or saved) as save, \
             mock.patch.object(api.styles, "delete_style") as delete:
            result = api.styles_migrate_persona("i1", {"persona_id": "大肥鱼"})
        self.assertEqual(result["status"], "ok")
        current.assert_called_once_with(self.inst, "大肥鱼")
        extract.assert_called_once()
        clear.assert_called_once_with(self.inst, "大肥鱼")
        save.assert_called_once()
        self.assertEqual(order, ["save", "clear"])
        self.assertEqual(order[0], "save")
        args, kwargs = save.call_args
        self.assertEqual(args[0], "i1")
        self.assertEqual(args[1], "旧人格自动学习")
        self.assertEqual(args[2], "- 短句、口语化。")
        self.assertEqual(kwargs["source"], "migration")
        delete.assert_not_called()
        self.assertIs(result["data"]["style"], saved)
        self.assertEqual(result["data"]["persona_id"], "大肥鱼")
        self.assertFalse(result["data"]["persona_unchanged"])
        self.assertTrue(result["data"]["auto_block_removed"])

    def test_migrate_reports_before_and_after_chars(self):
        from server import api
        prompt = "人格正文\n\n" + self.block
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt", return_value=prompt), \
             mock.patch.object(api.persona_mod, "extract_auto_blocks",
                               return_value=[self.block]), \
             mock.patch.object(api.persona_mod, "clear_auto_block",
                               return_value={"removed": True, "chars": 42}), \
             mock.patch.object(api.styles, "save_style",
                               return_value={"id": "sty_1"}), \
             mock.patch.object(api.styles, "delete_style"):
            result = api.styles_migrate_persona("i1", {"persona_id": "大肥鱼"})
        self.assertEqual(result["status"], "ok")
        # before_chars 是迁移前人格长度，after_chars 直接取清块后的返回值。
        self.assertEqual(result["data"]["before_chars"], len(prompt))
        self.assertEqual(result["data"]["after_chars"], 42)

    def test_migrate_merges_all_auto_blocks(self):
        from server import api
        prompt = (
            "人格正文\n\n"
            "<!-- AUTO-LEARN:BEGIN -->\n## 自动学习到的说话风格\n- 第一块。\n<!-- AUTO-LEARN:END -->\n\n"
            "<!-- AUTO-LEARN:BEGIN -->\n- 第二块。\n<!-- AUTO-LEARN:END -->"
        )
        saved = {"id": "sty_multi"}
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt", return_value=prompt), \
             mock.patch.object(api.persona_mod, "clear_auto_block",
                               return_value={"removed": True}) as clear, \
             mock.patch.object(api.styles, "save_style", return_value=saved) as save:
            result = api.styles_migrate_persona("i1", {"persona_id": "大肥鱼"})
        self.assertEqual(result["status"], "ok")
        note = save.call_args.args[2]
        self.assertIn("- 第一块。", note)
        self.assertIn("- 第二块。", note)
        self.assertNotIn("AUTO-LEARN", note)
        self.assertNotIn("## 自动学习到的说话风格", note)
        clear.assert_called_once_with(self.inst, "大肥鱼")
        self.assertTrue(result["data"]["auto_block_removed"])

    def test_migrate_rolls_back_style_when_block_not_removed(self):
        from server import api
        saved = {"id": "sty_stale"}
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt",
                               return_value="人格正文\n\n" + self.block), \
             mock.patch.object(api.persona_mod, "extract_auto_blocks",
                               return_value=[self.block]), \
             mock.patch.object(api.persona_mod, "clear_auto_block",
                               return_value={"removed": False}), \
             mock.patch.object(api.styles, "save_style", return_value=saved), \
             mock.patch.object(api.styles, "delete_style") as delete:
            result = api.styles_migrate_persona("i1", {"persona_id": "大肥鱼"})
        self.assertEqual(result.status_code, 400)
        self.assertIn("已撤销", result.body.decode("utf-8"))
        delete.assert_called_once_with("sty_stale")

    def test_migrate_rolls_back_style_when_clear_fails(self):
        from server import api
        saved = {"id": "sty_new", "name": "旧人格自动学习"}
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt",
                               return_value="人格正文\n\n" + self.block), \
             mock.patch.object(api.persona_mod, "extract_auto_blocks",
                               return_value=[self.block]), \
             mock.patch.object(api.persona_mod, "clear_auto_block",
                               side_effect=RuntimeError("清人格失败")), \
             mock.patch.object(api.styles, "save_style", return_value=saved), \
             mock.patch.object(api.styles, "delete_style") as delete:
            with self.assertRaises(RuntimeError):
                api.styles_migrate_persona("i1", {"persona_id": "大肥鱼"})
        delete.assert_called_once_with("sty_new")

    def test_migrate_requires_persona(self):
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt") as current, \
             mock.patch.object(api.styles, "save_style") as save:
            result = api.styles_migrate_persona("i1", {"persona_id": "   "})
        self.assertEqual(result.status_code, 400)
        current.assert_not_called()
        save.assert_not_called()

    def test_migrate_without_auto_block_rejected(self):
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt", return_value="人格正文"), \
             mock.patch.object(api.persona_mod, "extract_auto_blocks", return_value=[]), \
             mock.patch.object(api.persona_mod, "clear_auto_block") as clear, \
             mock.patch.object(api.styles, "save_style") as save:
            result = api.styles_migrate_persona("i1", {"persona_id": "大肥鱼"})
        self.assertEqual(result.status_code, 400)
        self.assertIn("没有自动学习块", result.body.decode("utf-8"))
        clear.assert_not_called()
        save.assert_not_called()

    def test_migrate_empty_block_rejected(self):
        from server import api
        empty = "<!-- AUTO-LEARN:BEGIN -->\n## 自动学习到的说话风格\n<!-- AUTO-LEARN:END -->"
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt", return_value=empty), \
             mock.patch.object(api.persona_mod, "extract_auto_blocks", return_value=[empty]), \
             mock.patch.object(api.persona_mod, "clear_auto_block") as clear, \
             mock.patch.object(api.styles, "save_style") as save:
            result = api.styles_migrate_persona("i1", {"persona_id": "大肥鱼"})
        self.assertEqual(result.status_code, 400)
        self.assertIn("自动学习块为空", result.body.decode("utf-8"))
        clear.assert_not_called()
        save.assert_not_called()

    def test_migrate_custom_name_and_dashboard_error(self):
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt",
                               return_value="人格正文\n\n" + self.block), \
             mock.patch.object(api.persona_mod, "extract_auto_blocks",
                               return_value=[self.block]), \
             mock.patch.object(api.persona_mod, "clear_auto_block",
                               return_value={"removed": True}), \
             mock.patch.object(api.styles, "save_style",
                               return_value={"id": "sty_2"}) as save:
            api.styles_migrate_persona("i1", {"persona_id": "大肥鱼", "name": "我的旧风格"})
        self.assertEqual(save.call_args.args[1], "我的旧风格")

        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             mock.patch.object(api.persona_mod, "current_prompt",
                               side_effect=api.dashboard.DashboardError("连不上", 502)), \
             mock.patch.object(api.styles, "save_style") as save2:
            result = api.styles_migrate_persona("i1", {"persona_id": "大肥鱼"})
        self.assertEqual(result.status_code, 400)
        self.assertIn("连不上", result.body.decode("utf-8"))
        save2.assert_not_called()


class StyleRoutesTest(unittest.TestCase):
    """路由层只验证鉴权/透传，DB 行为已由 StyleStoreTest 覆盖。"""

    inst = {"id": "i1", "name": "大肥鱼"}

    def _patched(self, name, **kwargs):
        from unittest import mock
        from server import api
        return mock.patch.object(api.styles, name, **kwargs)

    def test_list_returns_styles(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("list_styles", return_value=[{"id": "sty_1"}]) as listed:
            result = api.styles_list("i1")
        self.assertEqual(result["data"], [{"id": "sty_1"}])
        listed.assert_called_once_with("i1")

    def test_create_passes_bool_enabled(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("save_style", return_value={"id": "sty_1"}) as save:
            result = api.styles_create("i1", {"name": "口吻", "note": "内容", "enabled": False})
        self.assertEqual(result["status"], "ok")
        self.assertIs(save.call_args.kwargs["enabled"], False)
        self.assertEqual(save.call_args.kwargs["source"], "manual")

    def test_create_rejects_non_bool_enabled(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("save_style") as save:
            result = api.styles_create("i1", {"name": "口吻", "note": "内容",
                                              "enabled": "false"})
        self.assertEqual(result.status_code, 400)
        save.assert_not_called()

    def test_create_maps_style_error_to_400(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("save_style", side_effect=styles.StyleError("名称和内容不能为空")):
            result = api.styles_create("i1", {"name": "", "note": ""})
        self.assertEqual(result.status_code, 400)

    def test_patch_rejects_style_of_other_instance(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("get_style", return_value={"id": "sty_1", "instance_id": "i2"}), \
             self._patched("update_style") as update:
            result = api.styles_update("i1", "sty_1", {"name": "新"})
        self.assertEqual(result.status_code, 404)
        update.assert_not_called()

    def test_patch_rejects_missing_style(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("get_style", return_value=None), \
             self._patched("update_style") as update:
            result = api.styles_update("i1", "sty_missing", {"name": "新"})
        self.assertEqual(result.status_code, 404)
        update.assert_not_called()

    def test_patch_updates_owned_style(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("get_style", return_value={"id": "sty_1", "instance_id": "i1"}), \
             self._patched("update_style", return_value={"id": "sty_1", "name": "新"}) as update:
            result = api.styles_update("i1", "sty_1", {"name": "新"})
        self.assertEqual(result["data"]["name"], "新")
        update.assert_called_once_with("sty_1", {"name": "新"})

    def test_patch_maps_style_error_to_400(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("get_style", return_value={"id": "sty_1", "instance_id": "i1"}), \
             self._patched("update_style", side_effect=styles.StyleError("enabled 必须是布尔值或 0/1")):
            result = api.styles_update("i1", "sty_1", {"enabled": "false"})
        self.assertEqual(result.status_code, 400)

    def test_delete_rejects_style_of_other_instance(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("get_style", return_value={"id": "sty_1", "instance_id": "i2"}), \
             self._patched("delete_style") as delete:
            result = api.styles_delete("i1", "sty_1")
        self.assertEqual(result.status_code, 404)
        delete.assert_not_called()

    def test_delete_owned_style(self):
        from unittest import mock
        from server import api
        with mock.patch.object(api, "_instances", return_value=[self.inst]), \
             self._patched("get_style", return_value={"id": "sty_1", "instance_id": "i1"}), \
             self._patched("delete_style", return_value=True) as delete:
            result = api.styles_delete("i1", "sty_1")
        self.assertEqual(result["data"], {"deleted": True})
        delete.assert_called_once_with("sty_1")


if __name__ == "__main__":
    unittest.main()
