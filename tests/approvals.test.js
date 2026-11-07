const test = require("node:test");
const assert = require("node:assert/strict");
const approvals = require("../web/assets/approvals.js");

test("approval labels are human readable", () => {
  assert.equal(approvals.categoryLabel("bili_write"), "B站写入");
  assert.equal(approvals.categoryLabel("douyin_write"), "抖音写入");
  assert.equal(approvals.categoryLabel("unknown"), "其它");
  assert.equal(approvals.statusLabel("pending"), "待审批");
  assert.equal(approvals.statusLabel("approved"), "已批准");
  assert.equal(approvals.statusLabel("denied"), "已拒绝");
});

test("approval time formatting handles invalid values", () => {
  assert.equal(approvals.fmtTime(0), "—");
  assert.equal(approvals.fmtTime("bad"), "—");
  assert.match(approvals.fmtTime(1790000000), /^\d{2}-\d{2} \d{2}:\d{2}$/);
});
