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
  for (const route of ["capMarket", "capInstalled", "capDshPlugins", "capDshSkills", "capBili", "capDouyin", "knowledge", "voice", "inbox", "approvals", "automationCenter", "tasks", "digest", "duet", "evals", "cost", "snapshots", "offsite"]) {
    assert.deepEqual(ia.resolveRoute(route), { route, redirect: false });
  }
});

test("unknown routes fall back to overview", () => {
  assert.deepEqual(ia.resolveRoute("missing"), { route: "overview", redirect: true });
  assert.deepEqual(ia.resolveRoute(""), { route: "overview", redirect: false });
});

test("bot workbench keeps route while carrying the instance id", () => {
  assert.equal(ia.routeKey("#/bot/abc"), "bot");
  assert.deepEqual(ia.resolveRoute("bot/abc"), { route: "bot", redirect: false });
  assert.equal(ia.routeKey("#/life?bot=abc"), "life");
  assert.deepEqual(ia.resolveRoute("functions"), { route: "functions", redirect: false });
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
  assert.match(html, /href="#\/functions"/);
  assert.match(html, /data-route="functions"/);
  assert.doesNotMatch(html, /href="#\/dsh"/);
  assert.match(html, /\/assets\/ia\.js\?v=/);
  assert.match(html, /href="#\/hubBots"/);
  assert.match(html, /data-route="bots"/);
  assert.match(app, /functions: \{ section: "functions"/);
  assert.match(app, /bot: \{ section: "bots"/);
  assert.match(html, /\/assets\/approvals\.js\?v=/);
  assert.match(app, /automationCenter: \{ section: "automation"/);
  assert.match(html, /\/assets\/automation_center\.js\?v=/);
  assert.match(app, /inbox: \{ section: "bots"/);
  assert.match(html, /\/assets\/inbox\.js\?v=/);
  assert.match(app, /life: \{ section: "presence"/);
  assert.match(app, /people: \{ section: "presence"/);
  assert.match(app, /memes: \{ section: "presence"/);
  assert.match(app, /vision: \{ section: "presence"/);
  assert.match(html, /\/assets\/knowledge\.js\?v=/);
  assert.match(html, /\/assets\/cost\.js\?v=/);
  assert.match(html, /\/assets\/snapshots\.js\?v=/);
  assert.match(html, /\/assets\/offsite\.js\?v=/);
  assert.match(html, /\/assets\/voice\.js\?v=/);
  assert.match(app, /knowledge: \{ section: "capability"/);
  assert.match(app, /voice: \{ section: "capability"/);
  assert.match(app, /cost: \{ section: "monitor"/);
  assert.match(app, /snapshots: \{ section: "monitor"/);
  assert.match(app, /offsite: \{ section: "monitor"/);
  assert.match(html, /\/assets\/hub\.js\?v=/);
  assert.match(html, /\/assets\/life\.js\?v=/);
  assert.match(html, /\/assets\/people\.js\?v=/);
  assert.match(html, /\/assets\/memes\.js\?v=/);
  assert.match(html, /\/assets\/vision\.js\?v=/);
});

test("voice page ships built-in voice presets", () => {
  const root = path.resolve(__dirname, "..");
  const voice = fs.readFileSync(path.join(root, "web/assets/voice.js"), "utf8");
  const css = fs.readFileSync(path.join(root, "web/assets/style.css"), "utf8");
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  assert.match(voice, /人声预设/);
  assert.match(voice, /data-preset=/);
  assert.match(voice, /presetCard/);
  assert.match(app, /voiceUI\.render/,);
  assert.match(css, /\.voice-preset/);
});

test("voice page can add, edit and pick connection endpoints", () => {
  const root = path.resolve(__dirname, "..");
  const voice = fs.readFileSync(path.join(root, "web/assets/voice.js"), "utf8");
  const css = fs.readFileSync(path.join(root, "web/assets/style.css"), "utf8");
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  assert.match(voice, /新增预设/);
  assert.match(voice, /openPresetEditor/);
  assert.match(voice, /preset \&\& preset\[key\] !== undefined/);
  assert.match(voice, /data-preset-edit/);
  assert.match(voice, /\/presets\//);
  assert.match(voice, /voice-endpoint/);
  assert.match(voice, /\/endpoints/);
  assert.match(voice, /cacheCard/);
  assert.match(voice, /v-cache-clear/);
  assert.match(voice, /cache_max_entries/);
  assert.match(css, /\.voice-cache-stats/);
  assert.match(css, /\.voice-endpoint\.active/);
  assert.match(app, /ManagerVoice\.create\(\{.*openModal.*closeModal/);
});

test("voice plugin falls back to text when audio send fails", () => {
  const root = path.resolve(__dirname, "..");
  const main = fs.readFileSync(
    path.join(root, "plugins_src/astrbot_plugin_breeze_tts/main.py"),
    "utf8",
  );
  assert.match(main, /on_decorating_result/);
  assert.match(main, /_record_text/);
  assert.match(main, /语音发送失败，自动改发文字/);
  assert.match(main, /Plain\(text\)/);
});

test("voice page links mood and emotion plugins to tone", () => {
  const root = path.resolve(__dirname, "..");
  const voice = fs.readFileSync(path.join(root, "web/assets/voice.js"), "utf8");
  const css = fs.readFileSync(path.join(root, "web/assets/style.css"), "utf8");
  assert.match(voice, /moodCard/);
  assert.match(voice, /情绪联动/);
  assert.match(voice, /data-mood-tone/);
  assert.match(voice, /v-mood-sync/);
  assert.match(voice, /v-mood-group/);
  assert.match(voice, /mood_group_enabled/);
  assert.match(voice, /url\("\/mood"\)/);
  assert.match(css, /\.voice-mood-grid/);
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

test("navigation hides pages whose plugin is not installed", () => {
  const root = path.resolve(__dirname, "..");
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const api = fs.readFileSync(path.join(root, "server/api.py"), "utf8");
  assert.match(app, /const PLUGIN_PAGES = \{/);
  assert.match(app, /hubLive: "astrbot_plugin_human_presence"/);
  assert.match(app, /hubMemory: "astrbot_plugin_livingmemory"/);
  assert.match(app, /function routeAvailable\(route\)/);
  assert.match(app, /function applyNavVisibility\(\)/);
  assert.match(app, /installed_plugins/);
  assert.match(app, /我的插件套装/);
  assert.match(api, /_installed_plugin_ids/);
  assert.match(api, /plugin-suite\/install/);
  assert.match(api, /plugin-suite\/uninstall/);
});
