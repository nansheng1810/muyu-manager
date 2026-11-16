const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const sw = fs.readFileSync(path.join(root, "web/sw.js"), "utf8");
const ia = require("../web/assets/ia.js");
const mod = require("../web/assets/image_memes.js");

test("image meme page is wired into routing and shell", () => {
  assert.ok(ia.KNOWN_ROUTES.has("imageMemes"));
  assert.match(app, /imageMemes: \{ section: "presence"/);
  assert.match(app, /function viewImageMemes\(view\)/);
  assert.match(app, /ManagerImageMemes/);
  assert.match(html, /\/assets\/image_memes\.js\?v=20261116a/);
  assert.match(html, /\/assets\/image_memes\.css\?v=20261116a/);
  assert.match(sw, /"\/assets\/image_memes\.js"/);
  assert.match(sw, /"\/assets\/image_memes\.css"/);
});

test("image meme module exposes create", () => {
  assert.equal(typeof mod.create, "function");
});
