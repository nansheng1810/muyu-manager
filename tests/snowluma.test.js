const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
const ia = require("../web/assets/ia.js");
const mod = require("../web/assets/snowluma.js");

test("SnowLuma page is wired into capability, routing and shell", () => {
  assert.ok(ia.KNOWN_ROUTES.has("snowluma"));
  assert.match(app, /snowluma: \{ section: "capability"/);
  assert.match(app, /function viewSnowLuma\(view\)/);
  assert.match(app, /ManagerSnowLuma/);
  assert.match(app, /snowlumaUI\?\.leave\(\)/);
  assert.match(app, /SnowLuma 接管 QQ 进程/);
  assert.match(html, /\/assets\/snowluma\.js\?v=20261116i/);
  assert.match(html, /\/assets\/snowluma\.css\?v=20261116g/);
  assert.match(sw, /"\/assets\/snowluma\.js"/);
  assert.match(sw, /"\/assets\/snowluma\.css"/);
  const page = require("node:fs").readFileSync(path.join(root, "web/assets/snowluma.js"), "utf8");
  assert.match(page, /\/api\/snowluma\/bind/);
  assert.match(page, /\/api\/snowluma\/agent-mode/);
  assert.match(page, /\/api\/snowluma\/agent-group/);
  assert.match(page, /Agent 模式/);
  assert.match(page, /等待 AstrBot/);
  assert.match(page, /AstrBot 实例未运行/);
});

test("SnowLuma module exposes render and leave", () => {
  const ui = mod.create({
    api: async () => ({}),
    esc: (value) => String(value ?? ""),
    icon: () => "",
    toast: () => {},
    confirmDialog: async () => true,
    state: { instances: [] },
  });
  assert.equal(typeof ui.render, "function");
  assert.equal(typeof ui.leave, "function");
});
