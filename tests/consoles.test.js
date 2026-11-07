const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("../web/assets/consoles.js");

test("parseTimes sorts, dedupes and rejects invalid values", () => {
  const ok = C.parseTimes("20:30, 12:30, 20:30", 3);
  assert.equal(ok.error, "");
  assert.deepEqual(ok.times, ["12:30", "20:30"]);
  assert.match(C.parseTimes("25:00", 3).error, /HH:MM/);
  assert.match(C.parseTimes(["10:00", "11:00", "12:00", "13:00"], 3).error, /最多 3/);
});

test("parseWindows validates order and format", () => {
  const ok = C.parseWindows("19:00-21:00\n10:00-11:30", 2);
  assert.equal(ok.error, "");
  assert.deepEqual(ok.windows, ["10:00-11:30", "19:00-21:00"]);
  assert.match(C.parseWindows("11:00-10:00", 2).error, /早于/);
  assert.match(C.parseWindows("10:00~11:00", 2).error, /HH:MM-HH:MM/);
});

test("deriveBiliMode follows autonomous/windows/times precedence", () => {
  assert.equal(C.deriveBiliMode({ ENABLE_AUTONOMOUS_DAILY_PLAN: true }), "auto");
  assert.equal(C.deriveBiliMode({
    ENABLE_AUTONOMOUS_DAILY_PLAN: false,
    FIXED_PROACTIVE_WINDOWS: ["10:00-11:30"],
    FIXED_PROACTIVE_TIMES: ["10:30"],
  }), "windows");
  assert.equal(C.deriveBiliMode({
    ENABLE_AUTONOMOUS_DAILY_PLAN: false,
    FIXED_PROACTIVE_WINDOWS: [],
    FIXED_PROACTIVE_TIMES: ["10:30"],
  }), "times");
});

test("nextDouyinSlot handles today and tomorrow", () => {
  assert.equal(C.nextDouyinSlot(["12:30", "20:30"], new Date(2026, 10, 1, 13, 0)), "今天 20:30");
  assert.equal(C.nextDouyinSlot(["12:30", "20:30"], new Date(2026, 10, 1, 21, 0)), "明天 12:30");
});

test("validateDouyin blocks bad time/limit and warns on missing UMO", () => {
  const values = {
    qq_proactive_enabled: true,
    OWNER_QQ_UMO: "",
    qq_proactive_times: ["12:30"],
    qq_proactive_daily_limit: 5,
    qq_proactive_max_seconds: 180,
    interaction_dry_run: true,
  };
  const result = C.validateDouyin(values);
  assert.ok(result.errors.qq_proactive_daily_limit);
  assert.ok(result.warnings.OWNER_QQ_UMO);
  assert.ok(result.warnings.interaction_dry_run);
  const bad = C.validateDouyin({ ...values, qq_proactive_times: ["25:00"], qq_proactive_daily_limit: 2 });
  assert.ok(bad.errors.qq_proactive_times);
});

test("validateBili blocks empty active schedule and warns on truncation", () => {
  const base = {
    ENABLE_PROACTIVE: true,
    PROACTIVE_TIMES_COUNT: 1,
    PROACTIVE_VIDEO_COUNT: 3,
    PROACTIVE_DAILY_LIMIT: 0,
    ENABLE_AUTONOMOUS_DAILY_PLAN: false,
    FIXED_PROACTIVE_WINDOWS: [],
    FIXED_PROACTIVE_TIMES: [],
    AUTONOMOUS_ACTIVITY_LEVEL: 55,
    SLEEP_START: 2,
    SLEEP_END: 8,
    AUTONOMOUS_MIN_ACTION_GAP_MINUTES: 45,
  };
  assert.ok(C.validateBili(base).errors.FIXED_PROACTIVE_TIMES);
  const windows = C.validateBili({
    ...base,
    FIXED_PROACTIVE_WINDOWS: ["10:00-11:30", "19:00-21:00"],
    FIXED_PROACTIVE_TIMES: ["10:30"],
  });
  assert.equal(windows.mode, "windows");
  assert.ok(windows.warnings.FIXED_PROACTIVE_WINDOWS);
  assert.ok(windows.warnings.FIXED_PROACTIVE_TIMES);
});

test("buildConfigPayload preserves unknown fields and coerces types", () => {
  const original = { UNKNOWN: "keep", SESSDATA: "secret", ENABLE_PROACTIVE: false };
  const values = {
    ENABLE_PROACTIVE: true,
    PROACTIVE_TIMES_COUNT: "3",
    FIXED_PROACTIVE_TIMES: ["19:30", "10:30"],
  };
  const schema = {
    ENABLE_PROACTIVE: { type: "bool" },
    PROACTIVE_TIMES_COUNT: { type: "int" },
    FIXED_PROACTIVE_TIMES: { type: "list" },
  };
  const payload = C.buildConfigPayload(original, values, schema);
  assert.equal(payload.UNKNOWN, "keep");
  assert.equal(payload.SESSDATA, "secret");
  assert.equal(payload.ENABLE_PROACTIVE, true);
  assert.equal(payload.PROACTIVE_TIMES_COUNT, 3);
  assert.deepEqual(payload.FIXED_PROACTIVE_TIMES, ["10:30", "19:30"]);
});

test("countDirty counts changed curated fields only", () => {
  assert.equal(C.countDirty({ A: 1, B: "x" }, { A: 1, B: "x" }), 0);
  assert.equal(C.countDirty({ A: 2, B: "x", C: ["1"] }, { A: 1, B: "x", C: ["1"] }), 1);
});
