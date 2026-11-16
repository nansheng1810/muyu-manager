const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
const ia = require("../web/assets/ia.js");
const mod = require("../web/assets/mcp_mode.js");

test("MCP mode page is wired into capability, routing and shell", () => {
  assert.ok(ia.KNOWN_ROUTES.has("mcpMode"));
  assert.match(app, /mcpMode: \{ section: "capability"/);
  assert.match(app, /function viewMcpMode\(view\)/);
  assert.match(app, /ManagerMcpMode/);
  assert.match(app, /mcpModeUI\?\.leave\(\)/);
  assert.match(html, /\/assets\/mcp_mode\.js\?v=20261116b/);
  assert.match(html, /\/assets\/mcp_mode\.css\?v=20261116b/);
  assert.match(sw, /"\/assets\/mcp_mode\.js"/);
  assert.match(sw, /"\/assets\/mcp_mode\.css"/);
  assert.match(sw, /fleet-shell-v1\.30\.8/);
});

test("MCP mode module exposes create", () => {
  assert.equal(typeof mod.create, "function");
});
