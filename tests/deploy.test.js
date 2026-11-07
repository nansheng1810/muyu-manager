const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const read = (name) => fs.readFileSync(path.join(root, name), "utf8");

const deployJs = read("web/assets/deploy.js");
const deployCss = read("web/assets/deploy.css");
const appJs = read("web/assets/app.js");
const indexHtml = read("web/index.html");
const swJs = read("web/sw.js");
const deployPy = read("server/deploy.py");
const creatorPy = read("server/creator.py");
const provisionerPy = read("server/provisioner.py");

test("deploy module covers status, quick deploy and job polling", () => {
  assert.match(deployJs, /\/api\/deploy\/status/);
  assert.match(deployJs, /\/api\/deploy\/quick/);
  assert.match(deployJs, /\/api\/deploy\/jobs\//);
  assert.match(deployJs, /\/api\/deploy\/env/);
  assert.match(deployJs, /window\.ManagerDeploy = \{ create \}/);
});

test("deploy page offers preset vendors and custom input", () => {
  for (const vendor of ["deepseek", "dashscope", "siliconflow", "openai", "moonshot", "zhipu", "ollama", "custom"]) {
    assert.match(deployPy, new RegExp(`"id": "${vendor}"`));
  }
  assert.match(deployJs, /供应商|服务商/);
  assert.match(deployJs, /API Key/);
  assert.match(deployJs, /自定义/);
});

test("zero-bot state only renders onboarding and hides the shell", () => {
  assert.match(appJs, /if \(!state\.instances\.length\)/);
  assert.match(appJs, /renderOnboarding\(\)/);
  assert.match(appJs, /body\.classList\.add\("onboarding"\)/);
  assert.match(appJs, /body\.classList\.remove\("onboarding"\)/);
  assert.match(appJs, /finishOnboarding/);
  assert.match(deployCss, /body\.onboarding \.sidebar/);
  assert.match(deployCss, /body\.onboarding \.topbar/);
  assert.match(deployCss, /grid-template-columns: minmax\(0, 1fr\)/);
});

test("one-click deploy writes provider, dashboard password and platform", () => {
  assert.match(creatorPy, /def create_bootstrap_instance/);
  assert.match(creatorPy, /pbkdf2_sha256\$/);
  assert.match(creatorPy, /cfg\["provider"\] = \[dict\(provider\)\]/);
  assert.match(creatorPy, /cfg\["platform"\] = \[/);
  assert.match(creatorPy, /provider_id/);
});

test("model connection test and model discovery are wired", () => {
  assert.match(deployJs, /\/api\/deploy\/test/);
  assert.match(deployJs, /\/api\/deploy\/models/);
  assert.match(deployJs, /检测模型/);
  assert.match(deployJs, /测试连接/);
  assert.match(deployPy, /def test_connection/);
  assert.match(deployPy, /def list_models/);
  assert.match(deployPy, /deepseek-v4-pro/);
  assert.match(deployPy, /qwen3\.8-max/);
  assert.match(deployPy, /gpt-6\.1-terra/);
});

test("missing local capabilities can be installed in one click", () => {
  assert.match(deployJs, /\/api\/deploy\/install\/env/);
  assert.match(deployJs, /\/api\/deploy\/install\/napcat/);
  assert.match(deployJs, /\/api\/deploy\/install\/plugins/);
  assert.match(deployJs, /\/api\/deploy\/install\/jobs\//);
  assert.match(provisionerPy, /def install_environment/);
  assert.match(provisionerPy, /def install_napcat/);
  assert.match(provisionerPy, /def install_plugins/);
  assert.match(provisionerPy, /astrbot_plugin_human_presence/);
  assert.match(provisionerPy, /astrbot_plugin_daily_mood/);
  assert.match(provisionerPy, /meme_manager/);
  assert.match(provisionerPy, /astrbot_plugin_bilibili_ai_bot/);
  assert.match(indexHtml, /deploy\.js\?v=/);
  assert.ok(fs.existsSync(path.join(root, "web/assets/plugin_suite.zip")));
});

test("shell and service worker ship the new assets", () => {
  assert.match(indexHtml, /deploy\.css\?v=/);
  assert.match(indexHtml, /deploy\.js\?v=/);
  assert.match(swJs, /fleet-shell-v1\.23\.12/);
  assert.match(swJs, /\/assets\/deploy\.js/);
  assert.match(swJs, /\/assets\/deploy\.css/);
});
