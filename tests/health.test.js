const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const health = require("../web/assets/health.js");

test("health status labels are explicit", () => {
  assert.equal(health.statusLabel("ok"), "正常");
  assert.equal(health.statusLabel("warn"), "警告");
  assert.equal(health.statusLabel("bad"), "异常");
  assert.equal(health.statusLabel("unknown"), "未知");
});

test("health summary counts every component", () => {
  assert.deepEqual(
    health.summarize([
      { status: "ok" },
      { status: "warn" },
      { status: "warn" },
      { status: "bad" },
      { status: "other" },
    ]),
    { ok: 1, warn: 2, bad: 1, other: 1, total: 5 }
  );
});

test("health overall class never invents a status", () => {
  assert.equal(health.overallClass("ok"), "ok");
  assert.equal(health.overallClass("warn"), "warn");
  assert.equal(health.overallClass("bad"), "bad");
  assert.equal(health.overallClass("weird"), "warn");
});

test("health timestamp formatting is stable", () => {
  const text = health.formatGenerated(1790000000);
  assert.match(text, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  assert.equal(health.formatGenerated(0), "—");
});

test("overview uses the shared health module and drops duplicate cards", () => {
  const app = fs.readFileSync(path.resolve(__dirname, "../web/assets/app.js"), "utf8");
  const html = fs.readFileSync(path.resolve(__dirname, "../web/index.html"), "utf8");
  assert.match(app, /ManagerHealth/);
  assert.match(app, /renderFleet/);
  assert.doesNotMatch(app, /<h2>运行环境<\/h2>/);
  assert.doesNotMatch(app, /<h2>快捷入口<\/h2>/);
  assert.match(html, /\/assets\/health\.js\?v=/);
  assert.match(html, /\/assets\/health\.css\?v=/);
});
