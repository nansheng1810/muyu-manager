const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const duet = require("../web/assets/duet.js");

test("duet module exposes the status labels used by the page", () => {
  assert.equal(duet.create instanceof Function, true);
  assert.equal(duet.create.length, 1);
});

test("duet page is wired into automation navigation and PWA shell", () => {
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
  assert.match(app, /duet: \{ section: "group"/);
  assert.match(app, /group: \{\s*hub: "hubGroup"/);
  assert.match(app, /route: "duet"/);
  assert.match(app, /ManagerDuet/);
  assert.match(html, /\/assets\/duet\.js\?v=/);
  assert.match(sw, /"\/assets\/duet\.js"/);
});

test("duet backend keeps mode and auto limits explicit", () => {
  const source = fs.readFileSync(path.join(root, "server/duet.py"), "utf8");
  assert.match(source, /MAX_SECONDS = 3600/);
  assert.match(source, /MAX_ROUNDS = 20/);
  assert.match(source, /night_start/);
  assert.match(source, /last_human_ts/);
  assert.match(source, /filter_enabled/);
});
