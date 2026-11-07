const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ia = require("../web/assets/ia.js");

test("legacy plugin routes redirect to capability", () => {
  assert.deepEqual(ia.resolveRoute("#/market"), { route: "capMarket", redirect: true });
  assert.deepEqual(ia.resolveRoute("plugins"), { route: "capInstalled", redirect: true });
  assert.deepEqual(ia.resolveRoute("dsh"), { route: "capDshPlugins", redirect: true });
  assert.deepEqual(ia.resolveRoute("dshSkills"), { route: "capDshSkills", redirect: true });
  assert.deepEqual(ia.resolveRoute("dshAccess"), { route: "capDshAccess", redirect: true });
  assert.deepEqual(ia.resolveRoute("biliConsole"), { route: "capBili", redirect: true });
  assert.deepEqual(ia.resolveRoute("douyinConsole"), { route: "capDouyin", redirect: true });
});

test("current capability routes stay put", () => {
  for (const route of ["capMarket", "capInstalled", "capDshPlugins", "capDshSkills", "capBili", "capDouyin", "inbox", "approvals", "automationCenter", "tasks", "digest", "duet", "evals"]) {
    assert.deepEqual(ia.resolveRoute(route), { route, redirect: false });
  }
});

test("unknown routes fall back to overview", () => {
  assert.deepEqual(ia.resolveRoute("missing"), { route: "overview", redirect: true });
  assert.deepEqual(ia.resolveRoute(""), { route: "overview", redirect: false });
});

test("manager shell groups same-type pages into hubs", () => {
  const root = path.resolve(__dirname, "..");
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  assert.match(app, /const IA_GROUPS = \{/);
  assert.match(app, /capability: \{\s*hub: "hubPlugin"/);
  assert.match(app, /presence: \{\s*hub: "hubLive"/);
  assert.match(app, /group: \{\s*hub: "hubGroup"/);
  assert.match(app, /LEGACY_ROUTES|ManagerIA/);
  assert.match(html, /href="#\/hubPlugin"/);
  assert.match(html, /data-route="capability"/);
  assert.doesNotMatch(html, /href="#\/dsh"/);
  assert.match(html, /\/assets\/ia\.js\?v=/);
  assert.match(html, /href="#\/hubAuto"/);
  assert.match(html, /data-route="automation"/);
  assert.match(html, /\/assets\/approvals\.js\?v=/);
  assert.match(app, /automationCenter: \{ section: "automation"/);
  assert.match(html, /\/assets\/automation_center\.js\?v=/);
  assert.match(app, /inbox: \{ section: "bots"/);
  assert.match(html, /\/assets\/inbox\.js\?v=/);
  assert.match(app, /life: \{ section: "presence"/);
  assert.match(app, /people: \{ section: "presence"/);
  assert.match(app, /memes: \{ section: "presence"/);
  assert.match(app, /vision: \{ section: "presence"/);
  assert.match(html, /\/assets\/hub\.js\?v=/);
  assert.match(html, /\/assets\/life\.js\?v=/);
  assert.match(html, /\/assets\/people\.js\?v=/);
  assert.match(html, /\/assets\/memes\.js\?v=/);
  assert.match(html, /\/assets\/vision\.js\?v=/);
});

test("bot detail drawer absorbs plugins, permissions, access and logs", () => {
  const root = path.resolve(__dirname, "..");
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const css = fs.readFileSync(path.join(root, "web/assets/style.css"), "utf8");
  assert.match(app, /function openBotDetail\(instId, tab = "runtime"\)/);
  for (const tab of ["runtime", "plugins", "permissions", "access", "logs"]) {
    assert.match(app, new RegExp(`\\["${tab}",`));
  }
  assert.match(app, /loadPlugins\(body, inst, "#bot-detail-plugins"\)/);
  assert.match(app, /loadToolPermissionsInto/);
  assert.match(app, /renderBotAccessTab/);
  assert.match(app, /logLinesHtml/);
  assert.match(app, /data-detail="\$\{inst\.id\}"/);
  assert.match(css, /\.drawer-root/);
  assert.doesNotMatch(app, /id="s-tools"/);
  assert.doesNotMatch(app, /s-tool-inst/);
});
