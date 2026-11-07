const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const digest = require("../web/assets/digest.js");
const tasks = require("../web/assets/tasks.js");
const center = require("../web/assets/automation_center.js");

test("automation section contains center, approvals, tasks and digest", () => {
  assert.match(app, /automation: \{\s*hub: "hubAuto"/);
  assert.match(app, /route: "automationCenter"/);
  assert.match(app, /automationCenter: \{ section: "automation"/);
  assert.match(app, /route: "approvals"/);
  assert.match(app, /route: "tasks"/);
  assert.match(app, /route: "digest"/);
  assert.match(app, /tasks: \{ section: "automation"/);
  assert.match(app, /digest: \{ section: "automation"/);
  assert.match(app, /personas: \{\s*hub: "hubPersona"/);
  assert.match(app, /route: "evals"/);
  assert.match(app, /evals: \{ section: "personas"/);
});

test("frontend shell loads new modules with cache query", () => {
  for (const name of ["tasks.js", "digest.js", "eval.js", "automation.css", "automation_center.js", "deploy.js", "deploy.css"]) {
    assert.match(html, new RegExp(`/assets/${name.replace(".", "\\.")}\\?v=`));
  }
  assert.match(html, /v1\.23\.11/);
});

test("automation center calls monitoring APIs", () => {
  const source = fs.readFileSync(path.join(root, "web/assets/automation_center.js"), "utf8");
  assert.match(source, /\/api\/automation\/overview/);
  assert.match(source, /\/api\/automation\/logs\?since=/);
  assert.match(source, /\/api\/tasks/);
  assert.match(source, /setInterval\(poll, POLL_MS\)/);
  assert.match(source, /leave/);
});

test("automation center groups tasks in stable order", () => {
  const grouped = center.groupTasks([
    { name: "a", group: "DSH 技能" },
    { name: "b", group: "巡检" },
    { name: "c", group: "维护" },
    { name: "d", group: "自定义" },
    { name: "e", group: "巡检" },
  ]);
  assert.deepEqual(grouped.map((item) => item.name), ["维护", "巡检", "DSH 技能", "自定义"]);
  assert.equal(grouped[1].items.length, 2);
  assert.equal(center.KIND_LABEL.health_patrol, "健康巡检");
  assert.equal(center.fmtTime(0), "—");
  assert.equal(center.fmtClock(0), "--:--:--");
});

test("new modules call their APIs", () => {
  const digestJs = fs.readFileSync(path.join(root, "web/assets/digest.js"), "utf8");
  const tasksJs = fs.readFileSync(path.join(root, "web/assets/tasks.js"), "utf8");
  const evalJs = fs.readFileSync(path.join(root, "web/assets/eval.js"), "utf8");
  assert.match(digestJs, /\/api\/digest\?date=/);
  assert.match(tasksJs, /\/api\/tasks/);
  assert.match(tasksJs, /\/run`/);
  assert.match(evalJs, /\/api\/evals\/run/);
  assert.match(evalJs, /\/api\/evals\/fixtures/);
  assert.match(evalJs, /\/api\/evals\/trend/);
  assert.match(app, /\/api\/backups\/rehearse/);
});

test("digest and task time formatting is stable", () => {
  assert.equal(digest.fmtTime(0), "—");
  assert.equal(digest.fmtBytes(1024), "1.0 KB");
  assert.equal(tasks.fmtTime(0), "—");
  const date = new Date(2026, 10, 3, 9, 5).getTime() / 1000;
  assert.equal(digest.fmtTime(date), "11-03 09:05");
});

test("digest module escapes untrusted text in rendered rows", () => {
  const source = fs.readFileSync(path.join(root, "web/assets/digest.js"), "utf8");
  assert.match(source, /function escSafe/);
  assert.match(source, /esc\(item\.title\)/);
});
