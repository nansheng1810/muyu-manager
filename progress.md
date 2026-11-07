# 进度记录

## Final review fix（2026-11-05）

按最终审查结论修复 Critical C1、Important I1–I3 与 Spec §9（M2、主人豁免）；未部署、未重启、未提交。

### 修复点

- **C1 `server/mood.py`**：`resolve_instance` 在真实 `platform_id` 匹配失败后，按实例 `name` 回退匹配。
  插件的 umo 前缀等于实例名，且 `data/instances.json` 的 `platform_id` 为 null；真实 `platform_id` 命中仍优先。
- **I1 `server/human_mode.py`**：`plan` 的会话第一句执行 `BEGIN IMMEDIATE`，让当日真实沉默计数查询与行为事件插入处于
  同一写事务，避免并发请求同时读到旧计数而突破每日沉默上限（未改动 `fleet_store`）。
- **I2 `server/api.py`**：`/api/instances/{id}/learn/apply` 的同名手动档案去重条件增加 `scope` 与 `person_key` 相等，
  B 的私聊笔记不会再覆盖 A 的关系级档案或实例级档案；仅完全命中时才 `update_style`。
- **I3 `web/assets/human.js`**：保存行为设置时，若当前为影子模式且用户取消勾选，先弹出
  `confirmDialog("关闭影子模式", "请确认已查看今日行为记录。关闭后沉默、分段、延迟会真实生效。继续？")`；
  取消则恢复勾选并直接返回，不保存。
- **M2 `server/api.py` + `web/assets/human.js`**：迁移接口返回 `before_chars`（原人格长度）与
  `after_chars`（`cleared["chars"]`）；迁移成功后把“人格 X → Y 字，风格已保存”写入迁移卡片内的
  `#human-migrate-result`，并保留简短 toast。
- **Spec §9 `web/assets/human.js`**：今日行为卡新增主人豁免只读显示 `#human-owner-note`，取值
  `/api/human/status` 的 `owner_note`，缺失时默认“主人/管理员永不沉默”。

### 测试

- 定向：`python -m unittest tests.test_mood tests.test_human_mode tests.test_human_api tests.test_styles`，**83 passed**。
- 全量 Python：`python -m unittest discover -s tests -p "test_*.py"`，**261 passed**。
- 全量 JS：`node --test tests/*.test.js`，**75 passed**。

新增用例：`tests/test_mood.py` 3 条（C1 回退与优先级）、`tests/test_human_mode.py` 2 条（I1 写事务顺序、owner_note）、
`tests/test_styles.py` 2 条（I2 跨 scope 不覆盖、M2 字数）、`tests/human.test.js` 3 条（I3 确认文案、M2 卡片、主人豁免）。
