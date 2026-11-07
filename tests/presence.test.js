const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const ia = require("../web/assets/ia.js");
const presence = require("../web/assets/presence.js");

const LEAVES = ["presenceLoops", "presenceRelations", "presenceRhythm", "presenceRadar", "presenceDiary"];
const flush = () => new Promise((resolve) => setImmediate(resolve));
const escStub = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[ch]));

async function settle() {
  for (let index = 0; index < 16; index += 1) await flush();
}

function makeEl(id) {
  return {
    id,
    innerHTML: "",
    textContent: "",
    value: "",
    checked: false,
    disabled: false,
    hidden: false,
    style: {},
    handlers: {},
    addEventListener(type, fn) { (this.handlers[type] || (this.handlers[type] = [])).push(fn); },
    dispatch(type, extra = {}) {
      const event = Object.assign({ target: this }, extra);
      let result;
      for (const fn of this.handlers[type] || []) result = fn(event);
      return result;
    },
    closest() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}

function makeDom(ids) {
  const els = new Map();
  for (const id of ids) els.set(id, makeEl(id));
  return {
    el: (id) => els.get(id),
    view: {
      innerHTML: "",
      isConnected: true,
      querySelector(sel) { return sel.startsWith("#") ? els.get(sel.slice(1)) || null : null; },
      querySelectorAll() { return []; },
    },
  };
}

function fakeTimer() {
  const realSetInterval = global.setInterval;
  const realClearInterval = global.clearInterval;
  let fn = null;
  global.setInterval = (callback) => { fn = callback; return 1; };
  global.clearInterval = () => { fn = null; };
  return {
    tick() { if (fn) fn(); },
    stop() { fn = null; },
    restore() {
      global.setInterval = realSetInterval;
      global.clearInterval = realClearInterval;
    },
  };
}

function makeContext(api, options = {}) {
  const toasts = [];
  const confirmations = [];
  return {
    toasts,
    confirmations,
    ctx: {
      api,
      esc: escStub,
      icon: () => "",
      toast: (message, kind) => toasts.push({ message, kind }),
      confirmDialog: async (title, text) => {
        confirmations.push({ title, text });
        return options.confirm === undefined ? true : options.confirm;
      },
    },
  };
}

// ---------------------------------------------------------------- wiring

test("presence pages are wired into router, nav, IA and PWA shell", () => {
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
  const js = fs.readFileSync(path.join(root, "web/assets/presence.js"), "utf8");

  assert.match(js, /root\.ManagerPresence = api/);
  assert.equal(presence.create instanceof Function, true);
  assert.equal(presence.create.length, 1);
  assert.match(js, /return \{ render, leave \};/);

  assert.match(app, /SECTION_NAME = \{[^}]*presence: "活人感"/);
  assert.match(app, /presence: \{\s*hub: "hubLive"/);
  assert.match(app, /items: \[\s*\{ route: "life", icon: "sun" \}/);
  assert.match(app, /items: \[\s*\{ route: "memes", icon: "model" \},?\s*\{ route: "vision"/);
  assert.match(app, /items: \[\s*\{ route: "people", icon: "bots" \},?\s*\{ route: "presenceRelations"/);
  assert.match(app, /ManagerPresence/);
  assert.match(app, /presenceUI\?\.leave\(\)/);

  const titles = {
    presenceLoops: "话题回访",
    presenceRelations: "关系里程碑",
    presenceRhythm: "生活节律",
    presenceRadar: "群聊读空气",
    presenceDiary: "自我日记",
  };
  for (const leaf of LEAVES) {
    assert.match(app, new RegExp(`${leaf}: \\{ section: "presence", title: "${titles[leaf]}"`), leaf);
    const view = `view${leaf[0].toUpperCase()}${leaf.slice(1)}`;
    assert.match(app, new RegExp(`function ${view}\\(view\\)`), view);
    assert.ok(ia.KNOWN_ROUTES.has(leaf), leaf);
    assert.deepEqual(ia.resolveRoute(`#/${leaf}`), { route: leaf, redirect: false });
  }

  assert.match(html, /\/assets\/presence\.js\?v=20261105d/);
  assert.match(html, /href="#\/hubLive"/);
  assert.match(html, /data-route="presence"/);
  assert.match(html, /活人感/);
  assert.match(sw, /"\/assets\/presence\.js"/);
});

test("presence pages only call the implemented page APIs", () => {
  const js = fs.readFileSync(path.join(root, "web/assets/presence.js"), "utf8");
  const required = [
    "/api/presence/loops",
    "/preview",
    "/send",
    "/api/presence/relations",
    "/api/presence/milestones",
    "/api/presence/rhythm",
    "/api/presence/radar",
    "/api/presence/group-config",
    "/api/presence/diaries",
    "/api/presence/diaries/generate",
    "/api/presence/settings",
    "/api/mood/status",
  ];
  for (const fragment of required) assert.ok(js.includes(fragment), fragment);
  // 插件专用上报/扫描接口不属于页面；页面也不允许读人格全文。
  for (const forbidden of ["/api/presence/scan", "/api/presence/activity",
    "/api/presence/context", "/api/presence/followups"]) {
    assert.ok(!js.includes(forbidden), forbidden);
  }
  assert.doesNotMatch(js, /personas\/by-id/);
});

test("real sends, config writes and deletes ask for confirmation", () => {
  const js = fs.readFileSync(path.join(root, "web/assets/presence.js"), "utf8");
  assert.ok((js.match(/confirmDialog\(/g) || []).length >= 3);
  assert.match(js, /confirm: true/);
  assert.match(js, /confirm=true/);
  assert.match(js, /followup_shadow/);
  assert.match(js, /allow_memory/);
  assert.match(js, /followup_enabled/);
});

test("list pages poll every 3-5s, protect focus and leave clears the timer", () => {
  const js = fs.readFileSync(path.join(root, "web/assets/presence.js"), "utf8");
  assert.match(js, /POLL_MS = 4000/);
  assert.match(js, /setInterval/);
  assert.match(js, /clearInterval/);
  assert.match(js, /document\.activeElement/);
  assert.match(js, /function leave\(\)[\s\S]*?clearInterval\(timer\)/);
  // 节律页不是列表页，不参与轮询。
  assert.match(js, /scope === "rhythm"/);
});

// ---------------------------------------------------------------- loops

const LOOP_IDS = ["presence-inst", "presence-loop-status", "presence-error", "presence-loop-list",
  "presence-loop-person", "presence-loop-topic", "presence-loop-detail", "presence-loop-hours",
  "presence-loop-add", "presence-set-enabled", "presence-set-shadow", "presence-set-threshold",
  "presence-set-daily", "presence-set-weekly", "presence-set-quiet-start", "presence-set-quiet-end",
  "presence-set-save"];

function loopFixture() {
  return {
    id: "lp1", instance_id: "i1", platform: "qq", person_key: '10001" <b>',
    thread_key: "qq:Friend:10001", topic: "周末去哪里", detail: "上次说到一半",
    status: "open", confidence: 0.8, source: "auto", created: 1700000000,
    last_seen: 1700000000, follow_up_after: 1700100000, follow_up_count: 0,
    last_follow_up_at: 0, follow_up_text: "", follow_up_generated_at: 0,
  };
}

function loopServer() {
  const calls = [];
  const control = { items: [loopFixture()], confirm: true };
  async function api(url, opts = {}) {
    calls.push({ url, method: opts.method || "GET", body: opts.body });
    if (url === "/api/instances") return [{ id: "i1", name: "一号机" }];
    if (url.startsWith("/api/presence/loops?")) return control.items;
    if (url.startsWith("/api/presence/settings") && (opts.method || "GET") === "GET") {
      return {
        followup_enabled: true, followup_shadow: true, familiarity_threshold: 30,
        daily_limit: 1, weekly_limit: 3, quiet_start: "23:00", quiet_end: "08:00",
      };
    }
    if (url.endsWith("/preview")) {
      return { loop: { ...control.items[0], follow_up_text: "周末定的地方还去吗" }, shadow: true };
    }
    if (url.endsWith("/send")) {
      return { ...control.items[0], follow_up_count: 1, follow_up_text: "周末定的地方还去吗" };
    }
    if (url.startsWith("/api/presence/loops/")) return { ...control.items[0], status: "resolved" };
    if (url === "/api/presence/loops") return { ...control.items[0], id: "lp2" };
    return {};
  }
  return { api, calls, control };
}

test("loop page renders escaped rows, previews in shadow mode and sends only after confirm", async () => {
  const dom = makeDom(LOOP_IDS);
  const server = loopServer();
  const { ctx, confirmations } = makeContext(server.api);
  const timer = fakeTimer();
  const realDocument = global.document;
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view);
    await settle();
    const list = dom.el("presence-loop-list").innerHTML;
    assert.match(list, /周末去哪里/);
    assert.match(list, /&lt;b&gt;/, "person key must be escaped");
    assert.doesNotMatch(list, /<b>10001/);
    assert.match(list, /未完成/);
    assert.equal(dom.el("presence-set-threshold").value, 30);
    assert.equal(dom.el("presence-set-shadow").checked, true);

    dom.el("presence-loop-list").dispatch("click", {
      target: { closest: (sel) => (sel.includes("[data-preview]") ? { dataset: { preview: "lp1" } } : null) },
    });
    await settle();
    assert.ok(server.calls.some((call) => call.url.endsWith("/preview") && call.method === "POST"));
    assert.match(dom.el("presence-loop-list").innerHTML, /周末定的地方还去吗/);
    assert.match(dom.el("presence-loop-list").innerHTML, /影子预览/);

    dom.el("presence-loop-list").dispatch("click", {
      target: { closest: (sel) => (sel.includes("[data-send]") ? { dataset: { send: "lp1" } } : null) },
    });
    await settle();
    assert.equal(confirmations.length, 1);
    assert.equal(confirmations[0].title, "立即发送回访");
    const send = server.calls.find((call) => call.url.endsWith("/send"));
    assert.equal(send.method, "POST");
    assert.equal(send.body.confirm, true);

    const before = server.calls.filter((call) => call.url.startsWith("/api/presence/loops?")).length;
    dom.el("presence-loop-status").value = "resolved";
    dom.el("presence-loop-status").dispatch("change");
    await settle();
    const after = server.calls.filter((call) => call.url.startsWith("/api/presence/loops?"));
    assert.equal(after.length, before + 1);
    assert.match(after.at(-1).url, /status=resolved/);

    // 用户正在填写新增表单时，轮询不得覆盖输入。
    const loopsBefore = server.calls.filter((call) => call.url.startsWith("/api/presence/loops?")).length;
    global.document.activeElement = dom.el("presence-loop-person");
    timer.tick();
    await settle();
    assert.equal(
      server.calls.filter((call) => call.url.startsWith("/api/presence/loops?")).length,
      loopsBefore, "focused form pauses the list poll");
    global.document.activeElement = null;

    dom.el("presence-loop-person").value = "10002";
    dom.el("presence-loop-topic").value = "约好的车赛";
    dom.el("presence-loop-hours").value = "12";
    dom.el("presence-loop-add").dispatch("click");
    await settle();
    const create = server.calls.find((call) => call.url === "/api/presence/loops" && call.method === "POST");
    assert.equal(create.body.person_key, "10002");
    assert.equal(create.body.topic, "约好的车赛");
    assert.equal(create.body.follow_up_after_hours, 12);

    dom.el("presence-set-save").dispatch("click");
    await settle();
    const savedSettings = server.calls.find((call) => call.url === "/api/presence/settings" && call.method === "PUT");
    assert.equal(savedSettings.body.followup_shadow, true);
    assert.equal(savedSettings.body.quiet_start, "23:00");
  } finally {
    ui.leave();
    timer.restore();
    global.document = realDocument;
  }
});

test("loop polling stops after leave", async () => {
  const dom = makeDom(LOOP_IDS);
  const server = loopServer();
  const { ctx } = makeContext(server.api);
  const timer = fakeTimer();
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view);
    await settle();
    const before = server.calls.length;
    ui.leave();
    timer.tick();
    await settle();
    assert.equal(server.calls.length, before, "leave clears the interval");
    assert.equal(dom.el("presence-loop-list").innerHTML.includes("周末"), true);
  } finally {
    ui.leave();
    timer.restore();
    delete global.document;
  }
});

test("instance selection is preserved when moving between presence pages", async () => {
  const dom = makeDom(LOOP_IDS);
  const calls = [];
  const api = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || "GET", body: opts.body });
    if (url === "/api/instances") return [{ id: "i1", name: "一号机" }, { id: "i2", name: "二号机" }];
    if (url.startsWith("/api/presence/loops?")) return [];
    if (url.startsWith("/api/presence/settings")) return { followup_shadow: true };
    return {};
  };
  const { ctx } = makeContext(api);
  const timer = fakeTimer();
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view, "loops");
    await settle();
    assert.equal(dom.el("presence-inst").value, "i1");

    dom.el("presence-inst").value = "i2";
    await dom.el("presence-inst").dispatch("change");
    await settle();
    assert.ok(calls.some((call) => call.url.includes("instance_id=i2")));

    ui.render(dom.view, "loops");
    await settle();
    assert.equal(dom.el("presence-inst").value, "i2", "重新进入页面保留实例选择");
    assert.ok(calls.some((call) => call.url.includes("instance_id=i2")));
  } finally {
    ui.leave();
    timer.restore();
    delete global.document;
  }
});

test("turning off shadow asks for confirmation before enabling real follow-ups", async () => {
  const dom = makeDom(LOOP_IDS);
  const server = loopServer();
  const { ctx, confirmations } = makeContext(server.api, { confirm: false });
  const timer = fakeTimer();
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view, "loops");
    await settle();
    dom.el("presence-set-shadow").checked = false;
    dom.el("presence-set-save").dispatch("click");
    await settle();
    assert.equal(confirmations.at(-1).title, "关闭影子模式");
    assert.equal(
      server.calls.filter((call) => call.url === "/api/presence/settings" && call.method === "PUT").length,
      0, "取消后不得写入真实回访开关");
    assert.equal(dom.el("presence-set-shadow").checked, true, "取消后影子开关回到开启");
  } finally {
    ui.leave();
    timer.restore();
    delete global.document;
  }
});

// ------------------------------------------------------------ relations

const REL_IDS = ["presence-inst", "presence-error", "presence-rel-list", "presence-rel-detail",
  "presence-ms-title", "presence-ms-detail", "presence-ms-add", "presence-ms-list",
  "presence-rel-nickname", "presence-rel-stage", "presence-rel-notes", "presence-rel-allow",
  "presence-rel-followup", "presence-rel-meta", "presence-rel-save"];

function relationServer() {
  const calls = [];
  const relation = {
    id: "r1", instance_id: "i1", platform: "qq", person_key: "10001",
    display_name: "张三", nickname: "", stage: "familiar", allow_memory: 1,
    followup_enabled: 1, message_count: 42, first_seen: 1690000000,
    last_seen: 1700000000, familiarity: 55, affection: 12, anger: 3, notes: "",
  };
  const milestone = {
    id: "m1", instance_id: "i1", platform: "qq", person_key: "10001",
    kind: "first_contact", title: "第一次聊天", detail: "", occurred_at: 1690000000,
    source: "auto", created: 1690000000,
  };
  async function api(url, opts = {}) {
    calls.push({ url, method: opts.method || "GET", body: opts.body });
    if (url === "/api/instances") return [{ id: "i1", name: "一号机" }];
    if (url.startsWith("/api/presence/relations?")) return [relation];
    if (url.startsWith("/api/presence/relations/")) return { ...relation, ...(opts.body || {}) };
    if (url.startsWith("/api/presence/milestones?")) return [milestone];
    if (url === "/api/presence/milestones" && opts.method === "POST") {
      return { ...milestone, id: "m2", title: opts.body.title, source: "manual" };
    }
    if (url.startsWith("/api/presence/milestones") && opts.method === "DELETE") return { deleted: true };
    return {};
  }
  return { api, calls };
}

test("relation page edits nickname/stage/notes and manages milestones", async () => {
  const dom = makeDom(REL_IDS);
  const server = relationServer();
  const { ctx, confirmations } = makeContext(server.api);
  const timer = fakeTimer();
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view, "relations");
    await settle();
    assert.match(dom.el("presence-rel-list").innerHTML, /张三/);
    assert.match(dom.el("presence-rel-list").innerHTML, /熟悉/);
    assert.match(dom.el("presence-rel-list").innerHTML, /55/);
    assert.match(dom.el("presence-rel-detail").innerHTML, /昵称/);
    assert.match(dom.el("presence-ms-list").innerHTML, /第一次聊天/);

    dom.el("presence-rel-nickname").value = "三哥";
    dom.el("presence-rel-stage").value = "close";
    dom.el("presence-rel-notes").value = "喜欢跑夜路";
    dom.el("presence-rel-allow").checked = false;
    dom.el("presence-rel-followup").checked = true;
    dom.el("presence-rel-save").dispatch("click");
    await settle();
    const patch = server.calls.find((call) => call.method === "PATCH");
    assert.equal(patch.body.nickname, "三哥");
    assert.equal(patch.body.stage, "close");
    assert.equal(patch.body.notes, "喜欢跑夜路");
    assert.equal(patch.body.allow_memory, false);
    assert.equal(patch.body.followup_enabled, true);

    dom.el("presence-ms-list").dispatch("click", {
      target: { closest: (sel) => (sel === "[data-ms-del]" ? { dataset: { msDel: "m1" } } : null) },
    });
    await settle();
    assert.equal(confirmations.at(-1).title, "删除里程碑");
    const del = server.calls.find((call) => call.method === "DELETE");
    assert.match(del.url, /milestone_id=m1/);
    assert.match(del.url, /instance_id=i1/);

    dom.el("presence-ms-title").value = "一起跑完长途";
    dom.el("presence-ms-add").dispatch("click");
    await settle();
    const create = server.calls.find((call) => call.url === "/api/presence/milestones" && call.method === "POST");
    assert.equal(create.body.title, "一起跑完长途");
    assert.equal(create.body.kind, "custom");
    assert.equal(create.body.person_key, "10001");
    assert.equal(create.body.platform, "qq");
  } finally {
    ui.leave();
    timer.restore();
    delete global.document;
  }
});

// -------------------------------------------------------------- rhythm

const RHYTHM_IDS = ["presence-inst", "presence-error", "presence-rt-now", "presence-rt-curve",
  "presence-rt-total", "presence-rt-enabled", "presence-rt-wake", "presence-rt-sleep",
  "presence-rt-work-start", "presence-rt-work-end", "presence-rt-auto", "presence-rt-save",
  "presence-rt-refresh", "presence-ov-phase", "presence-ov-note", "presence-ov-hours",
  "presence-ov-apply", "presence-ov-clear",
  "presence-week-0", "presence-week-1", "presence-week-2", "presence-week-3",
  "presence-week-4", "presence-week-5", "presence-week-6"];

function rhythmServer() {
  const calls = [];
  const hour = (h, m) => Math.floor(new Date(2026, 10, 5, h, m, 0).getTime() / 1000);
  const rhythm = {
    phase: "working", label: "工作", energy_mod: -5, social_mod: -5, auto_mod: 0,
    override: { active: false, until: 0, phase: "", note: "" },
    schedule: {
      rhythm_enabled: true, wake_time: "08:00", sleep_time: "23:30",
      work_start: "09:00", work_end: "18:00", weekend_days: [5, 6], auto_adjust: true,
    },
  };
  async function api(url, opts = {}) {
    calls.push({ url, method: opts.method || "GET", body: opts.body });
    if (url === "/api/instances") return [{ id: "i1", name: "一号机" }];
    if (url.startsWith("/api/presence/rhythm?")) return rhythm;
    if (url === "/api/presence/rhythm" && opts.method === "PUT") return rhythm;
    if (url.startsWith("/api/mood/status")) {
      return {
        state: { energy: 60, social: 40, mood: "calm", intensity: 50 },
        settings: {}, events: [
          { created: hour(10, 0), assessment: {} },
          { created: hour(10, 30), assessment: {} },
          { created: hour(12, 0), assessment: {} },
        ], today_events: 3,
      };
    }
    return {};
  }
  return { api, calls, rhythm };
}

test("rhythm page shows effective energy, 24h curve and saves schedule/override", async () => {
  const dom = makeDom(RHYTHM_IDS);
  const server = rhythmServer();
  const { ctx } = makeContext(server.api);
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view, "rhythm");
    await settle();
    const now = dom.el("presence-rt-now").innerHTML;
    assert.match(now, /工作/);
    assert.match(now, /55/, "effective energy = 60 - 5");
    assert.match(now, /35/, "effective social = 40 - 5");
    const curve = dom.el("presence-rt-curve").innerHTML;
    assert.match(curve, /title="10:00 · 2 条"/);
    assert.match(curve, /title="12:00 · 1 条"/);
    assert.match(dom.el("presence-rt-total").textContent, /3/);
    assert.equal(dom.el("presence-rt-wake").value, "08:00");
    assert.equal(dom.el("presence-week-5").checked, true);
    assert.equal(dom.el("presence-week-6").checked, true);
    assert.equal(dom.el("presence-week-0").checked, false);

    dom.el("presence-rt-wake").value = "07:30";
    dom.el("presence-week-0").checked = true;
    dom.el("presence-rt-auto").checked = false;
    dom.el("presence-rt-save").dispatch("click");
    await settle();
    const save = server.calls.find((call) => call.url === "/api/presence/rhythm" && call.method === "PUT");
    assert.equal(save.body.wake_time, "07:30");
    assert.deepEqual(save.body.weekend_days, [0, 5, 6]);
    assert.equal(save.body.auto_adjust, false);

    dom.el("presence-ov-phase").value = "sleeping";
    dom.el("presence-ov-note").value = "通宵补觉";
    dom.el("presence-ov-hours").value = "3";
    dom.el("presence-ov-apply").dispatch("click");
    await settle();
    const applyCalls = server.calls.filter((call) => call.url === "/api/presence/rhythm" && call.method === "PUT");
    const apply = applyCalls.at(-1);
    assert.equal(apply.body.override_phase, "sleeping");
    assert.equal(apply.body.override_note, "通宵补觉");
    assert.ok(apply.body.override_until > Math.floor(Date.now() / 1000));

    dom.el("presence-ov-clear").dispatch("click");
    await settle();
    const clearCalls = server.calls.filter((call) => call.url === "/api/presence/rhythm" && call.method === "PUT");
    assert.equal(clearCalls.at(-1).body.override_until, 0);
    assert.equal(clearCalls.at(-1).body.override_phase, "");
  } finally {
    ui.leave();
    delete global.document;
  }
});

// --------------------------------------------------------------- radar

const RADAR_IDS = ["presence-inst", "presence-error", "presence-radar-summary",
  "presence-radar-groups", "presence-radar-events", "presence-radar-refresh",
  "presence-gc-form", "presence-gc-hint", "presence-gc-save",
  "presence-gc-enabled_groups", "presence-gc-initial_probability",
  "presence-gc-proactive_quiet_start", "presence-gc-proactive_quiet_end"];

function radarServer() {
  const calls = [];
  async function api(url, opts = {}) {
    calls.push({ url, method: opts.method || "GET", body: opts.body });
    if (url === "/api/instances") return [{ id: "i1", name: "一号机" }];
    if (url.startsWith("/api/presence/radar?")) {
      return {
        window_days: 7, reply: 12, silent: 30, total: 42,
        groups: [{ group_id: "123456", reply: 10, silent: 20 }],
        recent: [{ kind: "radar_reply", group_id: "123456", person_key: "10001",
          created: 1700000000, payload: {} }],
      };
    }
    if (url.startsWith("/api/presence/group-config") && opts.method !== "PUT") {
      return {
        plugin_id: "astrbot_plugin_group_chat_plus",
        allowed_keys: ["enabled_groups", "initial_probability",
          "proactive_quiet_start", "proactive_quiet_end"],
        config: { enabled_groups: ["123456"], initial_probability: 0.2,
          proactive_quiet_start: "23:00", proactive_quiet_end: "08:00" },
      };
    }
    if (url === "/api/presence/group-config" && opts.method === "PUT") {
      return { plugin_id: "astrbot_plugin_group_chat_plus", allowed_keys: [], config: opts.body.config };
    }
    return {};
  }
  return { api, calls };
}

test("radar page shows shadow stats and writes GC config only after confirm", async () => {
  const dom = makeDom(RADAR_IDS);
  const server = radarServer();
  const { ctx, confirmations } = makeContext(server.api);
  const timer = fakeTimer();
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view, "radar");
    await settle();
    assert.match(dom.el("presence-radar-summary").innerHTML, /接话 12/);
    assert.match(dom.el("presence-radar-summary").innerHTML, /沉默 30/);
    assert.match(dom.el("presence-radar-groups").innerHTML, /123456/);
    assert.match(dom.el("presence-radar-events").innerHTML, /接话/);
    assert.equal(dom.el("presence-gc-enabled_groups").value, "123456");
    assert.equal(Number(dom.el("presence-gc-initial_probability").value), 0.2);

    dom.el("presence-gc-enabled_groups").value = "123456\n654321";
    dom.el("presence-gc-initial_probability").value = "0.35";
    dom.el("presence-gc-proactive_quiet_start").value = "22:30";
    dom.el("presence-gc-save").dispatch("click");
    await settle();
    assert.equal(confirmations.length, 1);
    assert.equal(confirmations[0].title, "写入群聊配置");
    const put = server.calls.find((call) => call.url === "/api/presence/group-config" && call.method === "PUT");
    assert.equal(put.body.confirm, true);
    assert.deepEqual(put.body.config, {
      enabled_groups: ["123456", "654321"], initial_probability: 0.35,
      proactive_quiet_start: "22:30", proactive_quiet_end: "08:00",
    });
  } finally {
    ui.leave();
    timer.restore();
    delete global.document;
  }
});

test("cancelled GC write never reaches the API", async () => {
  const dom = makeDom(RADAR_IDS);
  const server = radarServer();
  const { ctx } = makeContext(server.api, { confirm: false });
  const timer = fakeTimer();
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view, "radar");
    await settle();
    dom.el("presence-gc-save").dispatch("click");
    await settle();
    assert.equal(server.calls.filter((call) => call.method === "PUT").length, 0);
  } finally {
    ui.leave();
    timer.restore();
    delete global.document;
  }
});

// --------------------------------------------------------------- diary

const DIARY_IDS = ["presence-inst", "presence-error", "presence-diary-list",
  "presence-diary-editor", "presence-diary-date", "presence-diary-summary",
  "presence-diary-text", "presence-diary-save", "presence-diary-delete",
  "presence-diary-generate", "presence-set-diary-enabled", "presence-set-diary-time",
  "presence-set-diary-inject", "presence-set-diary-save"];

function diaryServer() {
  const calls = [];
  const diary = {
    id: "d1", instance_id: "i1", date: "2026-11-04", text: "今天的日记正文",
    summary: "心情还行", model_id: "deepseek-chat", created: 1700000000, updated: 1700000000,
  };
  async function api(url, opts = {}) {
    calls.push({ url, method: opts.method || "GET", body: opts.body });
    if (url === "/api/instances") return [{ id: "i1", name: "一号机" }];
    if (url.startsWith("/api/presence/diaries/generate")) {
      return { skipped: true, date: "2026-11-05", reason: "当天事件不足" };
    }
    if (url.startsWith("/api/presence/diaries?") || url.startsWith("/api/presence/diaries?")) {
      return [diary];
    }
    if (url.startsWith("/api/presence/diaries/") && opts.method === "PATCH") return { ...diary, ...opts.body };
    if (url.startsWith("/api/presence/diaries/") && opts.method === "DELETE") return { deleted: true };
    if (url.startsWith("/api/presence/settings") && opts.method !== "PUT") {
      return { diary_enabled: true, diary_time: "23:30", diary_inject_next_day: true };
    }
    if (url === "/api/presence/settings" && opts.method === "PUT") return { ...opts.body };
    return {};
  }
  return { api, calls };
}

test("diary page edits, deletes with confirm, generates and saves auto settings", async () => {
  const dom = makeDom(DIARY_IDS);
  const server = diaryServer();
  const { ctx, confirmations, toasts } = makeContext(server.api);
  const timer = fakeTimer();
  global.document = { activeElement: null };
  const ui = presence.create(ctx);
  try {
    ui.render(dom.view, "diary");
    await settle();
    assert.match(dom.el("presence-diary-list").innerHTML, /2026-11-04/);
    assert.equal(dom.el("presence-diary-text").value, "今天的日记正文");
    assert.match(dom.el("presence-diary-editor").innerHTML, /心情还行/);
    assert.equal(dom.el("presence-set-diary-time").value, "23:30");
    assert.equal(dom.el("presence-set-diary-inject").checked, true);

    dom.el("presence-diary-text").value = "改过的日记";
    dom.el("presence-diary-text").dispatch("input");
    dom.el("presence-diary-save").dispatch("click");
    await settle();
    const patch = server.calls.find((call) => call.url === "/api/presence/diaries/d1" && call.method === "PATCH");
    assert.equal(patch.body.text, "改过的日记");

    dom.el("presence-diary-delete").dispatch("click");
    await settle();
    assert.equal(confirmations.at(-1).title, "删除日记");
    const del = server.calls.find((call) => call.method === "DELETE");
    assert.match(del.url, /confirm=true/);
    assert.match(del.url, /instance_id=i1/);

    dom.el("presence-diary-generate").dispatch("click");
    await settle();
    assert.ok(server.calls.some((call) => call.url === "/api/presence/diaries/generate"));
    assert.ok(toasts.some((item) => /当天事件不足/.test(item.message)));

    dom.el("presence-set-diary-time").value = "22:45";
    dom.el("presence-set-diary-enabled").checked = false;
    dom.el("presence-set-diary-inject").checked = false;
    dom.el("presence-set-diary-save").dispatch("click");
    await settle();
    const save = server.calls.find((call) => call.url === "/api/presence/settings" && call.method === "PUT");
    assert.equal(save.body.diary_time, "22:45");
    assert.equal(save.body.diary_enabled, false);
    assert.equal(save.body.diary_inject_next_day, false);
  } finally {
    ui.leave();
    timer.restore();
    delete global.document;
  }
});
