const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
const ia = require("../web/assets/ia.js");
const agent = require("../web/assets/probability.js");
const napcat = require("../web/assets/napcat_probability.js");

test("Agent and NapCat probability pages are wired into routing and shell", () => {
  assert.ok(ia.KNOWN_ROUTES.has("probability"));
  assert.ok(ia.KNOWN_ROUTES.has("probabilityNapcat"));
  assert.match(app, /probability: \{ section: "capability"/);
  assert.match(app, /probabilityNapcat: \{ section: "capability"/);
  assert.match(app, /function viewProbability\(view\)/);
  assert.match(app, /function viewNapcatProbability\(view\)/);
  assert.match(app, /ManagerProbability/);
  assert.match(app, /ManagerNapcatProbability/);
  assert.match(html, /\/assets\/probability\.js\?v=/);
  assert.match(html, /\/assets\/napcat_probability\.js\?v=/);
  assert.match(sw, /"\/assets\/probability\.js"/);
  assert.match(sw, /"\/assets\/napcat_probability\.js"/);
});

test("probability modules expose create", () => {
  assert.equal(typeof agent.create, "function");
  assert.equal(typeof napcat.create, "function");
});

test("Agent probability page only uses the agent API", () => {
  const source = fs.readFileSync(path.join(root, "web/assets/probability.js"), "utf8");
  assert.match(source, /\/api\/reply-probability/);
  assert.doesNotMatch(source, /presence\/group-config/);
  assert.match(source, /被 @ 到机器人时无视概率必定放行/);
});

test("NapCat probability page writes plugin config with confirm", () => {
  const source = fs.readFileSync(path.join(root, "web/assets/napcat_probability.js"), "utf8");
  assert.match(source, /\/api\/reply-probability\/napcat/);
  assert.match(source, /confirm: true/);
  assert.match(source, /initial_probability/);
  assert.match(source, /enable_dynamic_reply_probability/);
});
