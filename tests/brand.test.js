const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");

test("app identity uses the Muyu name", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "web/manifest.webmanifest"), "utf8"));
  assert.equal(manifest.name, "牧鱼");
  assert.equal(manifest.short_name, "牧鱼");
  assert.match(manifest.description, /AstrBot/);

  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  assert.match(html, /<title>牧鱼 · AstrBot 多机管理台<\/title>/);
  assert.match(html, /<strong>牧鱼<\/strong>/);
  assert.match(html, /<span>AstrBot 多机管理台<\/span>/);
  assert.match(html, /v1\.23\.11 · 本地运行/);

  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  assert.match(app, /牧鱼 v1\.23\.11/);

  const api = fs.readFileSync(path.join(root, "server/api.py"), "utf8");
  assert.match(api, /FastAPI\(title="牧鱼"/);

  const launcher = fs.readFileSync(path.join(root, "launcher.py"), "utf8");
  assert.match(launcher, /牧鱼/);

  const spec = fs.readFileSync(path.join(root, "manager.spec"), "utf8");
  assert.match(spec, /name="牧鱼"/);

  const bat = fs.readFileSync(path.join(root, "启动管理器.bat"), "utf8");
  assert.match(bat, /title 牧鱼/);
});

test("desktop shell uses a custom frameless titlebar", () => {
  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  assert.match(html, /class="app-titlebar"/);
  assert.match(html, /id="win-min"/);
  assert.match(html, /id="win-max"/);
  assert.match(html, /id="win-close"/);

  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  assert.match(app, /pywebviewready/);
  assert.match(app, /toggle_maximize/);

  const launcher = fs.readFileSync(path.join(root, "launcher.py"), "utf8");
  assert.match(launcher, /frameless=True/);
  assert.match(launcher, /easy_drag=False/);
  assert.match(launcher, /js_api=api/);

  const css = fs.readFileSync(path.join(root, "web/assets/style.css"), "utf8");
  assert.match(css, /html\.desktop-shell \.app-titlebar \{ display: flex; \}/);
});

test("new chubby-fish icon replaces the old blue-purple gradient mark", () => {
  const svg = fs.readFileSync(path.join(root, "web/assets/favicon.svg"), "utf8");
  for (const color of ["#0E1A17", "#F1E8D7", "#63B7A4"]) {
    assert.ok(svg.toLowerCase().includes(color.toLowerCase()), `missing ${color}`);
  }
  assert.doesNotMatch(svg, /#6ea8ff|#a78bfa/i);

  const ico = fs.readFileSync(path.join(root, "web/assets/app.ico"));
  assert.equal(ico.readUInt16LE(2), 1, "ico type");
  const count = ico.readUInt16LE(4);
  const sizes = [];
  for (let index = 0; index < count; index += 1) {
    const width = ico[6 + index * 16] || 256;
    sizes.push(width);
  }
  for (const size of [16, 32, 48, 256]) {
    assert.ok(sizes.includes(size), `ico missing ${size}px (got ${sizes.join(",")})`);
  }

  const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
  assert.match(sw, /fleet-shell-v1\.23/);
});
