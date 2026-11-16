const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
const ia = require("../web/assets/ia.js");
const mod = require("../web/assets/native_mcp.js");

test("native MCP page is wired into capability, routing and shell", () => {
  assert.ok(ia.KNOWN_ROUTES.has("nativeMcp"));
  assert.match(app, /nativeMcp: \{ section: "capability"/);
  assert.match(app, /function viewNativeMcp\(view\)/);
  assert.match(app, /ManagerNativeMcp/);
  assert.match(app, /nativeMcpUI\?\.leave\(\)/);
  assert.match(html, /\/assets\/native_mcp\.js\?v=20261116e/);
  assert.match(html, /\/assets\/native_mcp\.css\?v=20261116e/);
  assert.match(sw, /"\/assets\/native_mcp\.js"/);
  assert.match(sw, /"\/assets\/native_mcp\.css"/);
});

test("native MCP module exposes create", () => {
  assert.equal(typeof mod.create, "function");
});
