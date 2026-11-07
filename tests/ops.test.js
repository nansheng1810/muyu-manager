const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const ops = require("../web/assets/ops.js");

test("monitor section contains alerts, drift, resources and canary", () => {
  assert.match(app, /monitor: \{\s*hub: "hubMonitor"/);
  assert.match(app, /route: "alerts"/);
  assert.match(app, /route: "drift"/);
  assert.match(app, /route: "resources"/);
  assert.match(app, /route: "canary"/);
  assert.match(app, /alerts: \{ section: "monitor"/);
  assert.match(app, /drift: \{ section: "monitor"/);
  assert.match(app, /resources: \{ section: "monitor"/);
  assert.match(app, /canary: \{ section: "monitor"/);
  assert.match(app, /capMatrix: \{ section: "group"/);
  assert.match(app, /ManagerOps/);
});

test("ops module calls read-only endpoints", () => {
  const source = fs.readFileSync(path.join(root, "web/assets/ops.js"), "utf8");
  assert.match(source, /\/api\/alerts/);
  assert.match(source, /\/api\/drift/);
  assert.match(source, /\/api\/matrix/);
  assert.match(source, /\/api\/resources/);
  assert.match(source, /\/api\/canary\/run/);
  assert.match(source, /\/api\/drift\/align/);
  assert.match(app, /\/api\/notify\/test/);
  assert.match(app, /\/api\/notify\/run/);
  assert.match(source, /只读汇总，不会自动修复/);
  assert.match(source, /对齐会先备份/);
  assert.match(source, /只处理插件启停与人格正文/);
});

test("shell loads ops module and routes are known", () => {
  const ia = require("../web/assets/ia.js");
  assert.match(html, /\/assets\/ops\.js\?v=/);
  for (const route of ["alerts", "drift", "resources", "canary", "capMatrix"]) {
    assert.deepEqual(ia.resolveRoute(route), { route, redirect: false });
  }
});

test("severity and time formatting", () => {
  assert.equal(ops.severityClass("critical"), "bad");
  assert.equal(ops.severityClass("warning"), "warn");
  assert.equal(ops.severityClass("ok"), "ok");
  assert.equal(ops.fmtTime(0), "—");
  const stamp = new Date(2026, 10, 3, 9, 5).getTime() / 1000;
  assert.equal(ops.fmtTime(stamp), "11-03 09:05");
});
