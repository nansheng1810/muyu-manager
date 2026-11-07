const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const mood = require("../web/assets/mood.js");

const flush = () => new Promise((resolve) => setImmediate(resolve));
const notFound = () => new Error("Not Found");

const MOOD_IDS = ["mood-inst", "mood-error", "mood-state", "mood-relations", "mood-events",
  "mood-manual-mood", "mood-intensity", "mood-intensity-v", "mood-energy", "mood-energy-v",
  "mood-social", "mood-social-v", "mood-apply", "mood-reset", "mood-enabled", "mood-reset-hour",
  "mood-provider", "mood-save", "mood-silence-prob", "mood-silence-limit", "mood-delay-ms",
  "mood-silence", "mood-save-behavior"];

function makeDom() {
  const els = new Map();
  for (const id of MOOD_IDS) {
    els.set(id, {
      id,
      innerHTML: "",
      textContent: "",
      value: "",
      checked: false,
      hidden: false,
      style: { setProperty() {} },
      handlers: {},
      addEventListener(type, fn) { (this.handlers[type] || (this.handlers[type] = [])).push(fn); },
      // 返回最后一个处理函数的返回值，便于 await 异步的点击/切换处理。
      dispatch(type, extra = {}) {
        const event = Object.assign({ target: this }, extra);
        let result;
        for (const fn of this.handlers[type] || []) result = fn(event);
        return result;
      },
    });
  }
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
  global.setInterval = () => 1;
  global.clearInterval = () => {};
  return {
    restore() {
      global.setInterval = realSetInterval;
      global.clearInterval = realClearInterval;
    },
  };
}

// 模拟后端：GET 返回当前 settings，PUT /api/human/settings 按 control.humanSettingsError 抛错。
function makeServer() {
  const control = { humanSettingsError: null, humanStatusError: notFound() };
  const calls = [];
  const toasts = [];
  const settings = {
    mood_enabled: true, reset_hour: 5, provider_id: "",
    silence_enabled: false, silence_probability: 0.08, silence_daily_limit: 2, max_delay_ms: 3000,
  };
  const snapshot = () => Object.assign({}, settings);
  async function api(url, opts = {}) {
    calls.push({ url, method: opts.method || "GET", body: opts.body });
    if (url === "/api/instances") return [{ id: "inst-1", name: "一号机" }];
    if (url.startsWith("/api/instances/")) return { providers: [{ id: "p1", model: "m" }], current: "p1" };
    if (url.startsWith("/api/mood/status")) {
      return {
        state: { mood: "calm", intensity: 50, energy: 50, social: 50, date: "2026-11-04" },
        settings: snapshot(),
        relations: [],
        events: [],
        today_events: 0,
        reset_hour: settings.reset_hour,
      };
    }
    if (url.startsWith("/api/human/status")) {
      if (control.humanStatusError) throw control.humanStatusError;
      return { settings: snapshot() };
    }
    if (url === "/api/human/settings") {
      if (control.humanSettingsError) throw control.humanSettingsError;
      Object.assign(settings, opts.body);
      return snapshot();
    }
    if (url === "/api/mood/settings") {
      Object.assign(settings, opts.body);
      return snapshot();
    }
    throw new Error(`unexpected url ${url}`);
  }
  return { api, calls, toasts, settings, control };
}

async function openMood() {
  const dom = makeDom();
  const server = makeServer();
  const timer = fakeTimer();
  const realDocument = global.document;
  global.document = { activeElement: null };
  const ui = mood.create({
    api: server.api,
    esc: (value) => String(value ?? ""),
    icon: () => "",
    toast: (message, kind) => server.toasts.push({ message, kind }),
  });
  ui.render(dom.view);
  await flush();
  return {
    dom,
    server,
    ui,
    close() {
      ui.leave();
      timer.restore();
      global.document = realDocument;
    },
  };
}

test("mood page is wired into personas nav", () => {
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  const ia = fs.readFileSync(path.join(root, "web/assets/ia.js"), "utf8");
  assert.match(app, /mood: \{ section: "personas"/);
  assert.match(app, /ManagerMood/);
  assert.match(html, /\/assets\/mood\.js\?v=/);
  assert.match(ia, /"mood"/);
});

test("mood page calls mood and behavior APIs", () => {
  const js = fs.readFileSync(path.join(root, "web/assets/mood.js"), "utf8");
  assert.match(js, /\/api\/mood\/status/);
  assert.match(js, /\/api\/mood\/adjust/);
  assert.match(js, /\/api\/mood\/reset/);
  assert.match(js, /\/api\/mood\/settings/);
  assert.match(js, /\/api\/human\/settings/);
  assert.doesNotMatch(js, /personas\/by-id/);
});

test("mood page throttles refresh errors and leaves on route change", () => {
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const js = fs.readFileSync(path.join(root, "web/assets/mood.js"), "utf8");
  assert.match(app, /moodUI\?\.leave\(\)/);
  assert.match(js, /lastErrorAt/);
  assert.match(js, /ERROR_TOAST_GAP_MS\s*=\s*30000/);
  assert.match(js, /id="mood-error"/);
  assert.match(js, /document\.activeElement !== toggle/);
  assert.match(js, /data-reset-platform/);
  assert.doesNotMatch(js, /data-reset-rel/);
});

test("saving behavior refreshes status before refilling the form", async () => {
  const session = await openMood();
  try {
    const { dom, server } = session;
    assert.equal(Number(dom.el("mood-silence-prob").value), 0.08);
    dom.el("mood-silence").checked = true;
    dom.el("mood-silence-prob").value = "0.33";
    dom.el("mood-silence-limit").value = "4";
    dom.el("mood-delay-ms").value = "1500";
    const start = server.calls.length;
    await dom.el("mood-save-behavior").dispatch("click");
    const after = server.calls.slice(start);
    assert.equal(after[0].url, "/api/human/settings");
    const statusAt = after.findIndex((call) => call.url.startsWith("/api/mood/status"));
    const behaviorAt = after.findIndex((call) => call.url.startsWith("/api/human/status"));
    assert.ok(statusAt > 0, "保存后必须重新拉取 /api/mood/status");
    assert.ok(behaviorAt > statusAt, "回填必须发生在刷新之后");
    assert.equal(Number(dom.el("mood-silence-prob").value), 0.33);
    assert.equal(Number(dom.el("mood-silence-limit").value), 4);
    assert.equal(Number(dom.el("mood-delay-ms").value), 1500);
    assert.equal(dom.el("mood-silence").checked, true);
  } finally {
    session.close();
  }
});

test("behavior refill keeps the control the user is editing", async () => {
  const session = await openMood();
  try {
    const { dom } = session;
    // 数字输入正在编辑：刷新不得覆盖；复选框未聚焦仍按服务端回填。
    dom.el("mood-silence-prob").value = "0.9";
    dom.el("mood-silence").checked = true;
    global.document.activeElement = dom.el("mood-silence-prob");
    dom.el("mood-inst").value = "inst-1";
    await dom.el("mood-inst").dispatch("change");
    assert.equal(dom.el("mood-silence-prob").value, "0.9");
    assert.equal(dom.el("mood-silence").checked, false);

    // 复选框正在编辑：同样不得覆盖，其它控件照常回填。
    dom.el("mood-silence").checked = true;
    global.document.activeElement = dom.el("mood-silence");
    await dom.el("mood-inst").dispatch("change");
    assert.equal(dom.el("mood-silence").checked, true);
    assert.equal(Number(dom.el("mood-silence-prob").value), 0.08);
    assert.equal(Number(dom.el("mood-delay-ms").value), 3000);
  } finally {
    global.document.activeElement = null;
    session.close();
  }
});

test("behavior save falls back to /api/mood/settings only on 404", async () => {
  const session = await openMood();
  try {
    const { dom, server } = session;
    const save = async () => {
      const start = server.calls.length;
      server.toasts.length = 0;
      await dom.el("mood-save-behavior").dispatch("click");
      return server.calls.slice(start);
    };

    server.control.humanSettingsError = new Error("请求失败（HTTP 400）");
    let after = await save();
    assert.ok(!after.some((call) => call.url === "/api/mood/settings"), "400 不能回退");
    assert.ok(!after.some((call) => call.url.startsWith("/api/mood/status")), "400 不能继续刷新");
    assert.equal(server.toasts.at(-1).kind, "err");
    assert.match(server.toasts.at(-1).message, /HTTP 400/);

    server.control.humanSettingsError = new Error("请求失败（HTTP 500）");
    after = await save();
    assert.ok(!after.some((call) => call.url === "/api/mood/settings"), "500 不能回退");

    server.control.humanSettingsError = Object.assign(new Error("接口异常"), { status: 404 });
    after = await save();
    assert.ok(after.some((call) => call.url === "/api/mood/settings"), "404 必须回退");

    server.control.humanSettingsError = notFound();
    after = await save();
    assert.ok(after.some((call) => call.url === "/api/mood/settings"), "未找到必须回退");
    assert.ok(server.toasts.some((item) => item.message === "行为参数已保存"));
  } finally {
    session.close();
  }
});
