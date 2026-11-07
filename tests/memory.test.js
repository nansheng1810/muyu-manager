const assert = require("assert");
const fs = require("fs");
const path = require("path");
const memory = require("../web/assets/memory.js");

assert.strictEqual(memory.fmtArousal(0.8), "0.80");
assert.strictEqual(memory.fmtArousal(undefined), "—");
assert.strictEqual(memory.fmtSalience(0.65), "0.65");
assert.strictEqual(memory.importanceLabel(0.65), "65%");
assert.strictEqual(memory.validateSleepTime("03:30"), true);
assert.strictEqual(memory.validateSleepTime("3:30"), false);
assert.strictEqual(memory.validateSleepTime("24:00"), false);
assert.strictEqual(memory.shortId(123), "#123");
assert.strictEqual(memory.memoryTypeLabel(undefined), "未分类");
assert.strictEqual(
  memory.buildMemoryQuery({
    keyword: "a b",
    status: "all",
    page: 1,
    page_size: 20,
    empty: "",
  }),
  "keyword=a+b&status=all&page=1&page_size=20"
);
assert.deepStrictEqual(memory.scoreRows([
  { key: "vector", value: 0.8 },
  { key: "bm25", value: 0.2 },
]), [
  { key: "vector", value: 0.8, percent: 80 },
  { key: "bm25", value: 0.2, percent: 20 },
]);
assert.strictEqual(memory.summarizeReport({
  trigger: "manual",
  consolidation: { merged: 2 },
  cleanup: { archived: 3 },
}), "manual · 整合 2 组 · 归档 3 条");
assert.deepStrictEqual(
  memory.serializeHumanConfig({ sleep: { time: "03:30" } }),
  { "human_memory.sleep.time": "03:30" }
);
assert.strictEqual(memory.formatBytes(1536), "1.5 KB");
assert.strictEqual(memory.formatConfigNumber(0.699999988079071, "0.01"), "0.7");
assert.strictEqual(memory.formatConfigNumber(3, "1"), "3");
assert.strictEqual(memory.scoreDisplay("days_old", 1.85), "1.85 天");
assert.strictEqual(memory.scoreDisplay("importance", 0.735), "73.5%");

assert.deepStrictEqual(memory.parseGroupAllowlist("123, 456\n789；123"), [
  "123",
  "456",
  "789",
]);
assert.deepStrictEqual(memory.parseGroupAllowlist(["123", " 456 ", "123"]), [
  "123",
  "456",
]);
assert.strictEqual(memory.formatGroupAllowlist(["123", "456"]), "123\n456");
assert.strictEqual(memory.formatGroupAllowlist("123"), "123");
assert.strictEqual(memory.estimateSalience(0.5, 1), 0.65);
assert.strictEqual(memory.estimateSalience(0.5, 0.5), 0.5);
assert.strictEqual(memory.estimateSalience(1, 1), 1);
assert.deepStrictEqual(
  memory.collectConfigValues([
    { dataset: { cfg: "human_memory.sleep.enabled" }, type: "checkbox", checked: true },
    { dataset: { cfg: "human_memory.sleep.time" }, type: "text", value: "03:30" },
    { dataset: { cfg: "human_memory.sleep.keep_reports" }, type: "number", value: "60" },
    {
      dataset: { cfg: "human_memory.reconsolidation.group_allowlist" },
      type: "textarea",
      value: "123, 456\n789",
    },
  ]),
  {
    "human_memory.sleep.enabled": true,
    "human_memory.sleep.time": "03:30",
    "human_memory.sleep.keep_reports": 60,
    "human_memory.reconsolidation.group_allowlist": "123\n456\n789",
  }
);
assert.throws(
  () =>
    memory.collectConfigValues([
      { dataset: { cfg: "human_memory.sleep.keep_reports" }, type: "number", value: "x" },
    ]),
  /不是数字/
);
assert.deepStrictEqual(
  memory.promptMissingScopes({
    prompt_status: {
      private: { has_arousal: true, has_salience_reason: false },
      group: { has_arousal: false, has_salience_reason: false },
    },
  }),
  ["private", "group"]
);
assert.deepStrictEqual(
  memory.promptMissingScopes({ prompt_has_arousal: { private: false, group: true } }),
  ["private"]
);
assert.deepStrictEqual(memory.promptMissingScopes(null), []);

const memorySource = fs.readFileSync(path.resolve(__dirname, "../web/assets/memory.js"), "utf8");
assert.ok(!/id: "graph"/.test(memorySource), "separate graph tab should be merged into brain");
assert.match(memorySource, /LEGACY_TABS = \{ graph: "brain", audit: "health" \}/);
assert.match(memorySource, /brainHealthHtml/);
assert.match(memorySource, /图谱与健康/);
assert.match(memorySource, /id: "health"/);
assert.match(memorySource, /\/audit/);
assert.match(memorySource, /记忆体检/);

// B2: tabs, working memory, relations/emotion, health and library upgrades.
assert.deepStrictEqual(memory.TABS.map((tab) => tab.id), [
  "library",
  "working",
  "relations",
  "brain",
  "sleep",
  "recall",
  "vector",
  "health",
]);
assert.strictEqual(memory.LEGACY_TABS.graph, "brain");
assert.strictEqual(memory.LEGACY_TABS.audit, "health");
assert.match(memorySource, /id: "working"/);
assert.match(memorySource, /id: "relations"/);
assert.match(memorySource, /LEGACY_TABS = \{ graph: "brain", audit: "health" \}/);
assert.match(memorySource, /\/working\?limit=30/);
assert.match(memorySource, /session_id=\$\{encodeURIComponent/);
assert.match(memorySource, /\/relations\?days=/);
assert.match(memorySource, /\/emotion\?identity_key=/);
assert.match(memorySource, /\/health\/forgetting\?limit=/);
assert.match(memorySource, /\/health\/review-preview/);
assert.match(memorySource, /id: "vector"/);
assert.match(memorySource, /\/vector\/status/);
assert.match(memorySource, /\/vector\/probe/);
assert.match(memorySource, /\/vector\/rebuild/);
assert.match(memorySource, /two_stage_vector_weight/);
assert.match(memorySource, /\/export\?/);
assert.match(memorySource, /data-lib-export/);
assert.match(memorySource, /data-lib-batch-archive/);
assert.match(memorySource, /data-lib-batch-restore/);
assert.match(memorySource, /batchUpdateStatus/);
assert.match(memorySource, /async function batchUpdateStatus[\s\S]{0,800}confirmDialog/);
assert.match(memorySource, /activeTab === "working"/);
assert.match(memorySource, /activeTab === "relations"/);
assert.match(memorySource, /activeTab === "health"/);
assert.match(memorySource, /批量归档/);
assert.match(memorySource, /批量恢复/);
assert.match(memorySource, /在记忆库中查看此人/);
assert.match(memorySource, /不进入模型上下文/);
assert.match(memorySource, /复习预览/);
assert.match(memorySource, /setHighlight/);
assert.match(memorySource, /data-brain-clear-highlight/);

assert.deepStrictEqual(
  memory.identityLabels({
    metadata: {
      participant_identities: [
        { display_name: "南笙", is_bot: false },
        { display_name: "大肥鱼", is_bot: true },
        { display_name: "南笙", is_bot: false },
        { display_name: "" },
      ],
    },
  }),
  ["南笙"]
);
const b2Rows = [
  {
    id: 1,
    text: "南笙提到周末去爬山",
    metadata: {
      memory_type: "FACTUAL",
      importance: 0.8,
      arousal: 0.6,
      status: "active",
      participant_identities: [
        { identity_key: "qq:1", platform: "qq", sender_id: "1", display_name: "南笙" },
      ],
    },
  },
  {
    id: 2,
    text: "阿岚的旧偏好",
    metadata: JSON.stringify({
      memory_type: "EPISODIC",
      importance: 0.2,
      arousal: 0.1,
      status: "archived",
      participant_identities: [
        { identity_key: "qq:2", platform: "qq", sender_id: "2", display_name: "阿岚" },
      ],
    }),
  },
];
assert.deepStrictEqual(
  memory.filterMemoryItems(b2Rows, { min_importance: 0.5 }).map((row) => row.id),
  [1]
);
assert.deepStrictEqual(
  memory.filterMemoryItems(b2Rows, { min_arousal: 0.5 }).map((row) => row.id),
  [1]
);
assert.deepStrictEqual(
  memory.filterMemoryItems(b2Rows, { status: "archived" }).map((row) => row.id),
  [2]
);
assert.deepStrictEqual(
  memory.filterMemoryItems(b2Rows, { type: "FACTUAL" }).map((row) => row.id),
  [1]
);
assert.deepStrictEqual(
  memory.filterMemoryItems(b2Rows, { person: "qq:2" }).map((row) => row.id),
  [2]
);
assert.deepStrictEqual(
  memory.filterMemoryItems(b2Rows, { person: "南笙" }).map((row) => row.id),
  [1]
);
assert.strictEqual(
  memory.buildExportQuery({ keyword: "记忆 a", type: "FACTUAL", status: "archived" }),
  "q=%E8%AE%B0%E5%BF%86+a&type=FACTUAL&status=archived"
);
assert.strictEqual(memory.formatDays(2.345), "2.3 天");
assert.strictEqual(memory.formatDays(undefined), "—");

// B1: arousal editor, prompt merge and completed sleep/reconsolidation form.
assert.match(memorySource, /data-arousal-range/);
assert.match(memorySource, /data-arousal-number/);
assert.match(memorySource, /data-arousal-preview/);
assert.match(memorySource, /\/arousal`/);
assert.match(memorySource, /将重算/);
assert.match(memorySource, /prompt\/preview/);
assert.match(memorySource, /prompt\/merge/);
assert.match(memorySource, /confirm: "MERGE"/);
assert.match(memorySource, /手动重载插件/);
assert.match(memorySource, /human_memory\.sleep\.archive_only/);
assert.match(memorySource, /human_memory\.sleep\.keep_reports/);
assert.match(memorySource, /memory_consolidation\.max_groups_per_run/);
assert.match(memorySource, /human_memory\.reconsolidation\.group_allowlist/);
assert.match(memorySource, /空名单不允许任何群/);

// Two-stage vector recall: config whitelist fields and recall lab breakdown.
assert.match(memorySource, /recall_engine\.two_stage_enabled/);
assert.match(memorySource, /recall_engine\.two_stage_candidates/);
assert.match(memorySource, /recall_engine\.two_stage_vector_weight/);
assert.match(memorySource, /recall_engine\.two_stage_fuzzy_weight/);
assert.match(memorySource, /recall_engine\.two_stage_vector_k/);
assert.match(memorySource, /两段式向量召回/);
assert.match(memorySource, /默认开启，失败回退现有混合检索/);
assert.match(
  memorySource,
  /numberField\("recall_engine\.two_stage_candidates"[^\n]*"1", 30, 1, 200\)/
);
assert.match(
  memorySource,
  /numberField\("recall_engine\.two_stage_vector_weight"[^\n]*"0\.01", 0\.6, 0, 1\)/
);
assert.match(
  memorySource,
  /numberField\("recall_engine\.two_stage_fuzzy_weight"[^\n]*"0\.01", 0\.4, 0, 1\)/
);
assert.match(
  memorySource,
  /numberField\("recall_engine\.two_stage_vector_k"[^\n]*"1", 8192, 1, 8192\)/
);
assert.match(
  memorySource,
  /async function saveConfig[\s\S]{0,2000}request\(inst, "\/config", \{ method: "PUT", body: \{ values \} \}\)/
);
// Cross-context recall: config fields, recall lab identity/scene and cross badge.
assert.match(memorySource, /bool\("cross_context_enabled"/);
assert.match(memorySource, /num\("cross_context_limit"/);
assert.match(memorySource, /bool\("cross_context_private_to_group"/);
assert.match(memorySource, /bool\("cross_context_group_to_private"/);
assert.match(memorySource, /data-recall="person_identity"/);
assert.match(memorySource, /data-recall="scene"/);
assert.match(memorySource, /body\.is_private = false/);
assert.match(memorySource, /body\.is_private = true/);
assert.match(memorySource, /跨会话记忆 · 来自/);
assert.deepStrictEqual(
  memory.scoreRows({
    two_stage_candidates: 12,
    two_stage_fuzzy_score: 0.4,
    two_stage_vector_score: 0.8,
  }).map((row) => row.key),
  ["two_stage_candidates", "two_stage_fuzzy_score", "two_stage_vector_score"]
);

// B3: dream reports, active recall and manual review.
assert.strictEqual(memory.dreamState({ text: "梦里又回到河边" }), "text");
assert.strictEqual(memory.dreamState({ enabled: false, skipped: true }), "disabled");
assert.strictEqual(memory.dreamState({ enabled: true, skipped: true }), "skipped");
assert.strictEqual(memory.dreamState({ error: "模型离线" }), "error");
assert.strictEqual(memory.dreamState(null), "empty");
assert.strictEqual(memory.dreamNarrative({ text: " 梦里又回到河边 " }), "梦里又回到河边");
assert.strictEqual(memory.dreamNarrative({ error: "模型离线" }), "");
assert.deepStrictEqual(memory.dreamMemoryIds({ memory_ids: [1, "2", 0, "x"] }), [1, 2]);
assert.deepStrictEqual(
  memory.replayTimelineRows(
    {
      summary: {
        dream: { memory_ids: [1, 2], created_at: 1700000000 },
        rehearsal: { candidates: 4, updated: 2 },
      },
    },
    [{ id: 1, content: "周末爬山", importance: 0.8, salience: 0.6 }]
  ),
  [
    { memory_id: 1, time: 1700000000, summary: "周末爬山", importance: 0.8, salience: 0.6 },
    { memory_id: 2, time: 1700000000, summary: "", importance: null, salience: null },
  ]
);
assert.deepStrictEqual(memory.replayTimelineRows(null, []), []);
assert.strictEqual(memory.activeRecallMode({ enabled: false, shadow: true }), "off");
assert.strictEqual(memory.activeRecallMode({ enabled: true, shadow: true }), "shadow");
assert.strictEqual(memory.activeRecallMode({ enabled: true, shadow: false }), "real");
assert.strictEqual(memory.activeRecallModeLabel({ enabled: true, shadow: false }), "真实");
assert.strictEqual(memory.activeRecallModeLabel({ enabled: true, shadow: true }), "影子");
assert.strictEqual(memory.activeRecallModeLabel(null), "关闭");
assert.strictEqual(memory.activeRecallBlockedLabel("cooldown"), "处于冷却期");
assert.strictEqual(memory.activeRecallBlockedLabel("no_candidates"), "没有达到阈值的候选");
assert.strictEqual(memory.activeRecallBlockedLabel(""), "");
assert.strictEqual(memory.formatDurationMs(950), "950 ms");
assert.strictEqual(memory.formatDurationMs(2500), "2.5 秒");
assert.strictEqual(memory.formatDurationMs(125000), "2.1 分钟");
assert.strictEqual(memory.formatDurationMs(undefined), "—");

assert.match(memorySource, /最近睡眠报告/);
assert.match(memorySource, /\/sleep\/reports\?limit=10/);
assert.match(memorySource, /梦境叙事/);
assert.match(memorySource, /重放记忆时间线/);
assert.match(memorySource, /human_memory\.sleep\.dream\.enabled/);
assert.match(memorySource, /human_memory\.sleep\.dream\.max_memories/);
assert.match(memorySource, /human_memory\.sleep\.dream\.max_chars/);
assert.match(memorySource, /默认关闭/);
assert.match(memorySource, /\/active-recall\/status/);
assert.match(memorySource, /\/active-recall\/events\?limit=50/);
assert.match(memorySource, /\/active-recall\/preview/);
assert.match(memorySource, /human_memory\.active_recall\.enabled/);
assert.match(memorySource, /human_memory\.active_recall\.shadow/);
assert.match(memorySource, /human_memory\.active_recall\.min_score/);
assert.match(memorySource, /human_memory\.active_recall\.daily_limit/);
assert.match(memorySource, /human_memory\.active_recall\.cooldown_minutes/);
assert.match(memorySource, /human_memory\.active_recall\.allow_group/);
assert.match(memorySource, /不会发送主动消息/);
assert.match(memorySource, /async function saveActiveRecallConfig[\s\S]{0,1600}confirmDialog/);
assert.match(memorySource, /补忆预览/);
assert.match(memorySource, /async function runActivePreview[\s\S]{0,1200}\/active-recall\/preview/);
assert.match(memorySource, /\/health\/review`/);
assert.match(memorySource, /confirm: "REVIEW"/);
assert.match(memorySource, /async function reviewMemory[\s\S]{0,1000}confirmDialog/);
assert.match(memorySource, /async function reviewMemory[\s\S]{0,1800}\/health\/review/);
assert.match(memorySource, /data-health-review/);
assert.match(memorySource, /不自动复习/);
assert.match(memorySource, /activeTab === "recall"/);
console.log("memory tests passed");
