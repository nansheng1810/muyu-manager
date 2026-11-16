const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const api = fs.readFileSync(path.join(root, "server/api.py"), "utf8");

test("PWA shell has manifest, theme and service worker registration", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "web/manifest.webmanifest"), "utf8"));
  assert.equal(manifest.name, "牧鱼");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.display, "standalone");
  assert.ok(manifest.icons.length >= 1);
  assert.match(html, /rel="manifest" href="\/manifest\.webmanifest"/);
  assert.match(html, /theme-color/);
  assert.match(html, /navigator\.serviceWorker\.register\("\/sw\.js"\)/);
  assert.match(api, /\/manifest\.webmanifest/);
  assert.match(api, /\/sw\.js/);
});

test("service worker caches shell but leaves API on network", () => {
  const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
  assert.match(sw, /fleet-shell-v1\.30\.8/);
  assert.match(sw, /"\/assets\/human\.js"/);
  assert.match(sw, /url\.pathname\.startsWith\("\/api\/"\)/);
  assert.match(sw, /request\.mode === "navigate"/);
  assert.match(sw, /caches\.keys\(\)/);
});
