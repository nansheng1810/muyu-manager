const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const ia = require("../web/assets/ia.js");
const inbox = require("../web/assets/inbox.js");

const flush = () => new Promise((resolve) => setImmediate(resolve));
const escStub = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[ch]));

function makeDom() {
  const els = new Map();
  const ids = ["inbox-platform", "inbox-kind", "inbox-search", "inbox-unread", "inbox-refresh",
    "inbox-threads", "inbox-title", "inbox-takeover", "inbox-messages", "inbox-send-hint",
    "inbox-text", "inbox-send"];
  for (const id of ids) {
    els.set(id, {
      id,
      innerHTML: "",
      textContent: "",
      value: "",
      checked: false,
      disabled: false,
      isConnected: true,
      scrollTop: 0,
      scrollHeight: 300,
      clientHeight: 100,
      handlers: {},
      addEventListener(type, fn) { (this.handlers[type] || (this.handlers[type] = [])).push(fn); },
      dispatch(type, extra = {}) {
        const event = Object.assign({ target: this }, extra);
        for (const fn of this.handlers[type] || []) fn(event);
      },
      closest() { return null; },
      querySelector() { return null; },
      querySelectorAll() { return []; },
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
  let fn = null;
  global.setInterval = (callback) => { fn = callback; return 1; };
  global.clearInterval = () => { fn = null; };
  return {
    tick() { if (fn) fn(); },
    restore() {
      global.setInterval = realSetInterval;
      global.clearInterval = realClearInterval;
    },
  };
}

const readCalls = (calls) => calls.filter((call) => call.url.endsWith("/read"));
const messageCalls = (calls) => calls.filter((call) => call.url.includes("/messages"));

test("inbox page is wired into nav and scripts", () => {
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  assert.match(app, /inbox: \{ section: "bots"/);
  assert.match(app, /ManagerInbox/);
  assert.match(app, /function viewInbox\(view\)/);
  assert.match(html, /\/assets\/inbox\.js\?v=20261105d/);
  assert.match(html, /href="#\/hubBots"/);
  assert.match(html, /data-route="bots"/);
  assert.match(html, /id="i-inbox"/);
  assert.match(html, /v1\.23\.12 · 本地运行/);
  assert.ok(ia.KNOWN_ROUTES.has("inbox"));
  assert.deepEqual(ia.resolveRoute("#/inbox"), { route: "inbox", redirect: false });
});

test("inbox module calls the inbox API", () => {
  const js = fs.readFileSync(path.join(root, "web/assets/inbox.js"), "utf8");
  assert.match(js, /\/api\/inbox\/threads/);
  assert.match(js, /\/api\/inbox\/sync/);
  assert.match(js, /\/takeover/);
  assert.match(js, /confirm: "SEND"/);
  assert.match(js, /threadRow/);
  assert.match(js, /messageRow/);
});

test("inbox page syncs on enter and polls threads every ten seconds", () => {
  const js = fs.readFileSync(path.join(root, "web/assets/inbox.js"), "utf8");
  assert.match(js, /syncNow\(view\)/);
  assert.match(js, /skipped/);
  assert.match(js, /setInterval\([\s\S]*?10000\)/);
  assert.match(js, /disabled = !current\?\.takeover/);
});

test("inbox create exposes escaped row renderers", () => {
  const ui = inbox.create({
    api: async () => [],
    esc: (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch])),
    icon: () => "",
    toast: () => {},
    confirmDialog: async () => false,
  });
  const row = ui.threadRow({
    id: 'x" data-x="1',
    platform: "qq",
    display_name: "<img src=x onerror=alert(1)>",
    last_text: "<script>alert(1)</script>",
    account_name: '<b>千问</b>',
    unread: 3,
    takeover: 0,
  });
  assert.match(row, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(row, /<img/);
  assert.match(row, /&lt;script&gt;/);
  assert.match(row, /&lt;b&gt;千问&lt;\/b&gt;/, "account name must be rendered and escaped");
  assert.match(row, /QQ · &lt;b&gt;千问&lt;\/b&gt;/, "thread row shows platform and account");
  assert.match(row, /data-thread="x&quot; data-x=&quot;1"/);

  const message = ui.messageRow({
    direction: "in",
    sender_name: "<b>张三</b>",
    text: "<script>alert(1)</script>",
    ts: 1700000000,
  });
  assert.match(message, /&lt;b&gt;张三&lt;\/b&gt;/);
  assert.match(message, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(message, /<script>/);
});

test("inbox marks threads read only on explicit clicks and the unread filter never drains", async () => {
  const dom = makeDom();
  const calls = [];
  const thread = { id: "t1", platform: "qq", display_name: "甲", unread: 4, takeover: 0, last_message_at: 100 };
  let listData = [];
  const api = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || "GET" });
    if (url.startsWith("/api/inbox/threads?")) return listData;
    if (url.includes("/messages")) return [{ ts: 100, direction: "in", text: "你好" }];
    if (url.endsWith("/read")) return { ok: true };
    if (url === "/api/inbox/sync") return { skipped: true };
    return {};
  };
  const ui = inbox.create({ api, esc: escStub, icon: () => "", toast: () => {}, confirmDialog: async () => false });
  const timer = fakeTimer();
  try {
    ui.render(dom.view);
    await flush();
    assert.equal(readCalls(calls).length, 0, "entering the page must not mark threads read");
    assert.equal(dom.el("inbox-takeover").disabled, true, "takeover disabled without a current thread");

    listData = [thread];
    dom.el("inbox-unread").checked = true;
    dom.el("inbox-unread").dispatch("change");
    await flush();
    assert.ok(calls.some((call) => call.url.includes("unread=true")), "unread filter must reach the API");
    assert.equal(messageCalls(calls).length, 0, "unread filter must not auto-select a thread");
    assert.equal(readCalls(calls).length, 0, "unread filter must not auto-drain");
    assert.match(dom.el("inbox-threads").innerHTML, /甲/);

    dom.el("inbox-threads").dispatch("click", { target: { closest: () => ({ dataset: { thread: "t1" } }) } });
    await flush();
    assert.equal(messageCalls(calls).length, 1, "click loads messages");
    assert.equal(readCalls(calls).length, 1, "click marks read");
    assert.equal(readCalls(calls)[0].method, "POST");
    assert.match(dom.el("inbox-threads").innerHTML, /class="inbox-thread active"/);
    assert.equal(dom.el("inbox-takeover").disabled, false);
  } finally {
    ui.leave();
    timer.restore();
  }
});

test("inbox poll refreshes the open thread, rebinds takeover, and keeps filtered-out threads visible", async () => {
  const dom = makeDom();
  const calls = [];
  let listData = [{ id: "t1", platform: "qq", display_name: "甲", unread: 1, takeover: 0, last_message_at: 100 }];
  let messageData = [{ ts: 100, direction: "in", text: "第一条" }];
  const api = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || "GET" });
    if (url.startsWith("/api/inbox/threads?")) return listData;
    if (url.includes("/messages")) return messageData;
    if (url.endsWith("/read")) return { ok: true };
    if (url === "/api/inbox/sync") return { skipped: true };
    return {};
  };
  const ui = inbox.create({ api, esc: escStub, icon: () => "", toast: () => {}, confirmDialog: async () => false });
  const timer = fakeTimer();
  try {
    ui.render(dom.view);
    await flush();
    assert.match(dom.el("inbox-messages").innerHTML, /第一条/);
    assert.equal(dom.el("inbox-send").disabled, true);

    dom.el("inbox-messages").scrollTop = 0;
    dom.el("inbox-messages").scrollHeight = 400;
    listData = [{ id: "t1", platform: "qq", display_name: "甲", account_name: "千问", unread: 0, takeover: 1, last_message_at: 200 }];
    messageData = [{ ts: 100, direction: "in", text: "第一条" }, { ts: 200, direction: "in", text: "第二条" }];
    timer.tick();
    await flush();

    assert.equal(messageCalls(calls).length, 2, "poll refetches messages when last_message_at is newer");
    assert.equal(readCalls(calls).length, 0, "poll refresh must not mark the thread read");
    assert.match(dom.el("inbox-messages").innerHTML, /第二条/);
    assert.equal(dom.el("inbox-messages").scrollTop, 0, "scroll kept when the user is not near the bottom");
    assert.equal(dom.el("inbox-takeover").textContent, "取消接管");
    assert.equal(dom.el("inbox-takeover").disabled, false);
    assert.equal(dom.el("inbox-send").disabled, false);
    assert.match(dom.el("inbox-title").textContent, /甲/);
    assert.match(dom.el("inbox-title").textContent, /千问/, "header names the instance account");

    listData = [];
    timer.tick();
    await flush();
    assert.match(dom.el("inbox-messages").innerHTML, /第二条/, "filtered-out thread stays displayed");
    assert.match(dom.el("inbox-title").textContent, /甲/);

    listData = [{ id: "t1", platform: "qq", display_name: "甲", takeover: 1, last_message_at: 300 }];
    messageData = [...messageData, { ts: 300, direction: "in", text: "第三条" }];
    dom.el("inbox-messages").scrollTop = 300;
    timer.tick();
    await flush();
    assert.equal(dom.el("inbox-messages").scrollTop, 400, "near-bottom refresh follows the newest message");
  } finally {
    ui.leave();
    timer.restore();
  }
});

test("inbox syncs on enter, polls threads, and announces skipped sync only on manual refresh", async () => {
  const dom = makeDom();
  const calls = [];
  const toasts = [];
  const api = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || "GET" });
    if (url.startsWith("/api/inbox/threads?")) return [];
    if (url === "/api/inbox/sync") return { skipped: true };
    return {};
  };
  const ui = inbox.create({
    api, esc: escStub, icon: () => "",
    toast: (msg, kind) => toasts.push({ msg, kind }),
    confirmDialog: async () => false,
  });
  const timer = fakeTimer();
  try {
    ui.render(dom.view);
    await flush();
    assert.equal(calls.filter((call) => call.url === "/api/inbox/sync").length, 1);
    assert.deepEqual(toasts, [], "automatic skipped sync stays quiet");

    dom.el("inbox-refresh").dispatch("click");
    await flush();
    assert.equal(calls.filter((call) => call.url === "/api/inbox/sync").length, 2);
    assert.deepEqual(toasts.map((toast) => toast.msg), ["同步正在进行"]);

    const listsBefore = calls.filter((call) => call.url.startsWith("/api/inbox/threads?")).length;
    timer.tick();
    await flush();
    assert.ok(calls.filter((call) => call.url.startsWith("/api/inbox/threads?")).length > listsBefore, "poll reloads threads");
  } finally {
    ui.leave();
    timer.restore();
  }
});
