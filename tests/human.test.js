const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");

// 截取一个具名函数的函数体，避免用脆弱的整行匹配。
function functionBody(source, name) {
  const start = source.search(new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`));
  if (start < 0) return "";
  const rest = source.slice(start + 1);
  const next = rest.search(/\n\s*(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\(/);
  return next < 0 ? source.slice(start) : source.slice(start, start + 1 + next);
}

test("human style page is wired into personas nav", () => {
  const app = read("web/assets/app.js");
  const html = read("web/index.html");
  const ia = require("../web/assets/ia.js");

  assert.match(app, /human: \{ section: "personas", title: "拟人模式"/);
  assert.match(app, /personas: \{\s*hub: "hubPersona"/);
  assert.match(app, /route: "human"/);
  assert.match(app, /window\.ManagerHuman/);
  assert.match(app, /function viewHuman/);
  assert.match(app, /humanUI\?\.leave\(\)/);
  assert.match(html, /\/assets\/human\.js\?v=/);
  assert.ok(
    html.indexOf("/assets/human.js") < html.indexOf("/assets/app.js"),
    "human.js must load before app.js",
  );
  assert.deepEqual(ia.resolveRoute("human"), { route: "human", redirect: false });
  assert.equal(typeof require("../web/assets/human.js").create, "function");
});

test("human page calls style and migration APIs without reading persona by id", () => {
  const js = read("web/assets/human.js");

  assert.match(js, /\/api\/instances\/\$\{instId\}\/styles/);
  assert.match(js, /method: "PATCH"/);
  assert.match(js, /method: "DELETE"/);
  assert.match(js, /enabled: !item\.enabled/);
  assert.match(js, /migrate-persona/);
  assert.match(js, /\/personas\/workbench/);
  assert.match(js, /confirmDialog\(\s*"剥离自动学习块"/);
  assert.match(js, /先保存风格档案，再从人格删除自动学习块/);
  assert.doesNotMatch(js, /会先从人格中删除自动学习块/);
  assert.doesNotMatch(js, /personas\/by-id/);
  const styleWrites = js.slice(js.indexOf("async function toggleStyle"), js.indexOf("function bind"));
  assert.ok(styleWrites.length > 0, "style toggle/delete section exists");
  assert.doesNotMatch(styleWrites, /method: "PUT"/);
  const confirmAt = js.search(/confirmDialog\(\s*"剥离自动学习块"/);
  assert.ok(
    confirmAt >= 0 && confirmAt < js.indexOf("migrate-persona"),
    "migration must confirm before calling the API",
  );
});

test("human page renders list/create/toggle/delete with escaped text", () => {
  const js = read("web/assets/human.js");

  assert.match(js, /id="human-style-list"/);
  assert.match(js, /data-toggle="/);
  assert.match(js, /data-delete="/);
  assert.match(js, /id="human-create"/);
  assert.match(js, /id="human-migrate"/);
  assert.match(js, /esc\(item\.name\)/);
  assert.match(js, /esc\(String\(item\.note/);
  assert.match(js, /esc\(sourceLabel\(item\.source\)\)/);
  assert.match(js, /esc\(item\.person_key/);
  assert.match(js, /esc\(x\.name \|\| x\.id\)/);
  assert.match(js, /esc\(p\.persona_id\)/);
});

test("manual and auto learning only save style profiles", () => {
  const app = read("web/assets/app.js");
  const api = read("server/api.py");

  assert.match(app, /id="ln-style-name"/);
  assert.match(app, /已追加到风格档案/);
  assert.match(api, /已新建风格档案（不写人格）/);
  assert.doesNotMatch(app, /id="ln-persona"/);
  assert.doesNotMatch(app, /id="al-persona"/);
  assert.doesNotMatch(app, /已写入人格/);
  assert.doesNotMatch(app, /写回人格/);
  assert.doesNotMatch(app, /写入人格/);
  assert.doesNotMatch(api, /写回人格/);
  assert.doesNotMatch(api, /写入人格/);
  assert.match(api, /追加到风格档案（不写人格）/);
  assert.match(api, /styles_migrate_persona/);
});

test("learnApply posts relationship scope for QQ private and never a persona id", () => {
  const app = read("web/assets/app.js");
  const start = app.indexOf("async function learnApply");
  assert.ok(start >= 0, "learnApply function exists");
  const end = app.indexOf("\nasync function ", start + 1);
  const body = app.slice(start, end > start ? end : start + 1600);
  assert.match(body, /ln-style-name/);
  assert.match(body, /learnTarget\(noteKey\)/);
  assert.match(app, /entry\.key\.startsWith\("qq:"\) && !entry\.is_group/);
  assert.match(body, /scope: target\.scope/);
  assert.match(body, /person_key: target\.personKey/);
  assert.match(body, /data\.appended \? "已追加到" : "已新建"/);
  assert.doesNotMatch(body, /persona_id/);
  assert.doesNotMatch(body, /ln-persona/);
});

test("human page exposes behavior settings and shadow log", () => {
  const js = read("web/assets/human.js");
  assert.match(js, /\/api\/human\/status/);
  assert.match(js, /\/api\/human\/settings/);
  assert.match(js, /shadow/);
  assert.match(js, /silence_enabled/);
  assert.match(js, /今日行为/);
  assert.match(js, /id="human-plugin-state"/);
  assert.match(js, /id="human-shadow-state"/);
  assert.match(js, /id="human-stats"/);
  assert.match(js, /id="human-events"/);
  assert.match(js, /document\.activeElement/);
  assert.match(js, /esc\(e\.reason/);
  assert.match(js, /method: "PUT"/);
});

test("human page can create relationship styles", () => {
  const js = read("web/assets/human.js");
  assert.match(js, /human-scope/);
  assert.match(js, /human-person-key/);
  assert.match(js, /scope: scope/);
  assert.match(js, /person_key: scope === "relationship" \? personKey : ""/);
  assert.match(js, /关系 ID/);
  assert.match(js, /关系级风格需要填写对方 ID/);
});

test("human page polls behavior status every 3 seconds and clears on leave", () => {
  const js = read("web/assets/human.js");
  assert.match(js, /STATUS_POLL_MS = 3000/);
  assert.match(js, /setInterval\(\(\) => refreshStatus\(view\), STATUS_POLL_MS\)/);
  assert.match(js, /clearInterval\(humanTimer\)/);
});

test("learn page explains QQ private relationship scope", () => {
  const app = read("web/assets/app.js");
  assert.match(app, /QQ 私聊来源会追加到关系级档案，只对那个 QQ 生效；群聊\/B站保持实例级。/);
});

test("human shadow summary counts only non-normal behaviors", () => {
  const js = read("web/assets/human.js");
  const paint = functionBody(js, "paintStatus");
  assert.ok(paint.length > 0, "paintStatus function exists");
  assert.match(js, /SHADOW_COUNT_KEYS = \["shadow_silence", "shadow_split", "shadow_delay", "shadow_short"\]/);
  assert.match(paint, /SHADOW_COUNT_KEYS/);
  assert.doesNotMatch(paint, /startsWith\("shadow_"\)/);
  assert.doesNotMatch(js, /"shadow_reply"/);
});

test("human load snapshots the instance and drops late responses", () => {
  const js = read("web/assets/human.js");
  const load = functionBody(js, "load");
  const personas = functionBody(js, "loadPersonas");
  assert.ok(load.length > 0, "load function exists");
  assert.ok(personas.length > 0, "loadPersonas function exists");
  assert.match(load, /const requestInst = instId/);
  assert.match(load, /\$\{encodeURIComponent\(requestInst\)\}\/styles/);
  assert.match(load, /if \(requestInst !== instId\) return/);
  assert.match(load, /loadPersonas\(view, requestInst\)/);
  assert.match(personas, /if \(instanceId !== instId\) return/);
});

test("human settings save repaints status and guards instance switches", () => {
  const js = read("web/assets/human.js");
  const save = functionBody(js, "saveSettings");
  assert.ok(save.length > 0, "saveSettings function exists");
  assert.match(save, /const requestInst = instId/);
  assert.match(save, /instance_id: requestInst/);
  assert.match(save, /if \(requestInst !== instId\) return/);
  assert.match(save, /paintStatus\(view\)/);
});

test("human settings confirm before leaving shadow mode", () => {
  const js = read("web/assets/human.js");
  const save = functionBody(js, "saveSettings");
  assert.ok(save.length > 0, "saveSettings function exists");
  assert.match(save, /关闭影子模式/);
  assert.match(save, /请确认已查看今日行为记录。关闭后沉默、分段、延迟会真实生效。继续？/);
  assert.match(save, /await confirmDialog\(/);
  // 取消后恢复勾选并直接返回，不写设置。
  assert.match(save, /if \(!ok\) \{/);
  assert.match(save, /human-shadow"\)\.checked = true/);
  assert.ok(
    save.indexOf("confirmDialog") < save.indexOf("/api/human/settings"),
    "confirm must happen before saving behavior settings",
  );
});

test("human migration writes persona char delta into the card", () => {
  const js = read("web/assets/human.js");
  const migrate = functionBody(js, "migrate");
  assert.ok(migrate.length > 0, "migrate function exists");
  assert.match(js, /id="human-migrate-result"/);
  assert.match(migrate, /#human-migrate-result/);
  assert.match(migrate, /before_chars/);
  assert.match(migrate, /after_chars/);
  assert.match(migrate, /字，风格已保存/);
  assert.match(migrate, /toast\("已剥离并保存为风格档案"\)/);
});

test("today behavior card shows owner exemption note", () => {
  const js = read("web/assets/human.js");
  const paint = functionBody(js, "paintStatus");
  assert.ok(paint.length > 0, "paintStatus function exists");
  assert.match(js, /id="human-owner-note"/);
  assert.match(js, /主人\/管理员永不沉默/);
  assert.match(paint, /owner_note/);
  assert.match(paint, /#human-owner-note/);
});

test("manual learning auto-appends and only re-appends edited notes", () => {
  const app = read("web/assets/app.js");
  const summarize = functionBody(app, "learnSummarize");
  const apply = functionBody(app, "learnApply");
  assert.match(app, /learnSavedNote: ""/);
  assert.match(app, /function syncLearnApply/);
  assert.match(summarize, /save: true/);
  assert.match(summarize, /state\.learnSavedNote = data\.saved/);
  assert.match(summarize, /已自动追加到/);
  assert.match(apply, /state\.learnSavedNote = note/);
  assert.match(apply, /syncLearnApply\(view\)/);
  assert.match(app, /已追加到风格档案/);
  assert.match(app, /追加编辑后的内容/);
});

test("learning note stays pinned to the source that generated it", () => {
  const app = read("web/assets/app.js");
  const summarize = functionBody(app, "learnSummarize");
  const apply = functionBody(app, "learnApply");
  assert.ok(summarize.length > 0, "learnSummarize function exists");
  assert.ok(apply.length > 0, "learnApply function exists");
  assert.match(app, /learnNoteKey: ""/);
  assert.match(summarize, /state\.learnNoteKey = state\.learnKey/);
  assert.match(apply, /const noteKey = state\.learnNoteKey \|\| state\.learnKey/);
  assert.match(apply, /if \(state\.learnNoteKey && state\.learnKey !== state\.learnNoteKey\)/);
  assert.match(apply, /学习笔记来自另一个来源，请重新生成后再保存/);
  assert.match(apply, /learnTarget\(noteKey\)/);
  assert.doesNotMatch(apply, /findLearnSource\(state\.learnKey\)/);
  assert.ok(
    apply.indexOf("学习笔记来自另一个来源") < apply.indexOf("/learn/apply"),
    "source mismatch must be rejected before saving",
  );
});
