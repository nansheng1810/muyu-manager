const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");

test("Bilibili publish page is wired into the manager shell", () => {
  const page = fs.readFileSync(path.join(root, "web/assets/bili_publish.js"), "utf8");
  assert.match(page, /ManagerBiliPublish/);
  assert.match(page, /bili-publish/);
  assert.match(page, /\/status/);
  assert.match(page, /\/login/);
  assert.match(page, /\/publish/);
  assert.match(page, /扫码登录/);
  assert.match(page, /手动发布/);
  assert.match(page, /发布记录/);

  const app = fs.readFileSync(path.join(root, "web/assets/app.js"), "utf8");
  assert.match(app, /capBiliPublish/);
  assert.match(app, /viewBiliPublish/);

  const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  assert.match(html, /bili_publish\.js/);
  assert.match(html, /bili_publish\.css/);

  const ia = fs.readFileSync(path.join(root, "web/assets/ia.js"), "utf8");
  assert.match(ia, /"capBiliPublish"/);
});
