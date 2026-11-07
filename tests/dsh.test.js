const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const dsh = require("../web/assets/dsh.js");

test("DSH tabs cover plugins, skills and AstrBot access", () => {
  assert.deepEqual(
    dsh.TABS.map((item) => item.id),
    ["plugins", "skills", "access"]
  );
});

test("safeUrl only accepts http(s)", () => {
  assert.equal(dsh.safeUrl("https://github.com/a/b"), "https://github.com/a/b");
  assert.equal(dsh.safeUrl("http://127.0.0.1:3080"), "http://127.0.0.1:3080");
  assert.equal(dsh.safeUrl("javascript:alert(1)"), "");
  assert.equal(dsh.safeUrl("file:///C:/secret"), "");
});

test("formatCount keeps market numbers compact", () => {
  assert.equal(dsh.formatCount(999), "999");
  assert.equal(dsh.formatCount(1331), "1.3k");
  assert.equal(dsh.formatCount(328295), "328.3k");
  assert.equal(dsh.formatCount(undefined), "—");
});

test("normalizePlugin preserves installability and upgrades category", () => {
  const row = dsh.normalizePlugin({
    owner: "owner",
    name: "demo",
    fullName: "owner/demo",
    description: "hello",
    stars: "12",
    categoryKey: "memory",
    installability: "verified",
    repositoryUrl: "https://github.com/owner/demo",
    installed: 1,
  });
  assert.equal(row.fullName, "owner/demo");
  assert.equal(row.stars, 12);
  assert.equal(row.categoryLabel, "记忆");
  assert.equal(row.installability, "verified");
  assert.equal(row.installed, true);
});

test("normalizeSkill accepts id fallback and rating", () => {
  const row = dsh.normalizeSkill({
    id: "@user/demo",
    slug: "demo",
    name: "Demo",
    downloads: 50205,
    stars: 32,
    rating: 4.6,
    categoryLabel: "办公效率",
    pageUrl: "https://skillhub.cn/skills/demo",
  });
  assert.equal(row.slug, "demo");
  assert.equal(row.category, "办公效率");
  assert.equal(row.downloads, 50205);
  assert.equal(row.rating, 4.6);
  assert.equal(row.pageUrl, "https://skillhub.cn/skills/demo");
});

test("installed plugin filter includes only local dsh rows", () => {
  const rows = dsh.filterInstalledPlugins(
    [
      { pkg: "@cocofhu/skillhub", name: "skillhub", dsh: true, spec: "^0.2.16" },
      { pkg: "left-pad", name: "left-pad", dsh: false },
    ],
    "skill"
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].pkg, "@cocofhu/skillhub");
  assert.equal(rows[0].spec, "^0.2.16");
});

test("connector summary defaults to the managed 3080 target", () => {
  assert.deepEqual(dsh.connectorSummary({}), {
    host: "127.0.0.1",
    port: 3080,
    sessionMode: "new",
    prompt: false,
    timeout: 900,
  });
  const custom = dsh.connectorSummary({
    dsh_host: "127.0.0.1",
    dsh_port: 3081,
    session_mode: "persistent",
    inject_prompt_enabled: true,
    request_timeout_seconds: 120,
  });
  assert.equal(custom.port, 3081);
  assert.equal(custom.sessionMode, "persistent");
  assert.equal(custom.prompt, true);
  assert.equal(custom.timeout, 120);
});

test("manager shell exposes the DSH capability routes and assets", () => {
  const root = path.resolve(__dirname, "..");
  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  assert.match(app, /capDshPlugins: \{ section: "capability"/);
  assert.match(app, /capDshSkills: \{ section: "capability"/);
  assert.match(app, /capDshAccess: \{ section: "capability"/);
  assert.match(app, /return dshUI\.render\(view, "plugins"\)/);
  assert.match(html, /href="#\/hubPlugin"/);
  assert.match(html, /\/assets\/dsh\.js\?v=/);
  assert.match(html, /\/assets\/dsh\.css\?v=/);
});
