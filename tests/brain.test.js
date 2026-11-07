const assert = require("assert");
const brain = require("../web/assets/brain.js");

const memories = [
  {
    id: 141,
    text: "大肥鱼在 2026-11-01 给自己的长期记忆升级了 v1.3",
    metadata: {
      memory_type: "FACTUAL",
      importance: 0.6,
      arousal: 0.45,
      salience: 0.555,
      key_facts: ["a", "b", "c"],
      session_id: "test",
    },
  },
  {
    id: 140,
    text: "群里聊本地大模型",
    metadata: {
      memory_type: "EPISODIC",
      importance: 0.65,
      arousal: 0.4,
      salience: 0.57,
      key_facts: ["x", "y"],
      session_id: "test",
    },
  },
  {
    id: 139,
    text: "内存条价格",
    metadata: {
      memory_type: "PREFERENCE",
      importance: 0.55,
      arousal: 0.9,
      salience: 0.65,
      key_facts: [],
      session_id: "test",
    },
  },
];

const graph = {
  snapshot: {
    nodes: [
      { id: 1, label: "本地大模型", type: "fact", degree: 8, weight: 9 },
      { id: 2, label: "南笙", type: "participant", degree: 5, weight: 4 },
      { id: 3, label: "记忆 v1.3", type: "fact", degree: 3, weight: 6 },
    ],
    edges: [
      { id: 11, source: 1, target: 2, memory_id: 140, weight: 1 },
      { id: 12, source: 3, target: 1, memory_id: 141, weight: 1 },
      { id: 13, source: 2, target: 3, memory_id: 999, weight: 1 },
      { id: 14, source: 3, target: 999, memory_id: 141, weight: 1 },
    ],
  },
};

const model = brain.buildModel(memories, graph, { width: 900, height: 520 });
assert.strictEqual(model.memories.length, 3);
assert.strictEqual(model.graphNodes.length, 3);
assert.strictEqual(model.graphEdges.length, 3);
assert.strictEqual(model.memoryLinks.length, 2);
assert.ok(model.particles.length >= 6);
for (const mem of model.memories) {
  assert.ok(mem.x >= 0 && mem.x <= 900, `memory x out of bounds: ${mem.x}`);
  assert.ok(mem.y >= 0 && mem.y <= 520, `memory y out of bounds: ${mem.y}`);
}
for (const node of model.graphNodes) {
  assert.ok(node.x >= 0 && node.x <= 900);
  assert.ok(node.y >= 0 && node.y <= 520);
}
const hit = brain.hitTest(model, model.memories[0].x, model.memories[0].y);
assert.strictEqual(hit.kind, "memory");
assert.strictEqual(hit.id, model.memories[0].id);
assert.strictEqual(brain.hitTest(model, -100, -100), null);

const points = brain.hexPoints(50, 50, 30);
assert.strictEqual(points.length, 6);
for (const point of points) {
  assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
}
assert.strictEqual(brain.formatType("FACTUAL"), "事实");
assert.strictEqual(brain.formatType(undefined), "未分类");

// B2: read-only highlight state and pure matchers.
const highlight = brain.normalizeHighlight({
  memoryIds: [141, "139", 141, "x", -2, null],
  relationKey: " 南笙 ",
});
assert.deepStrictEqual(highlight, { memoryIds: [141, 139], relationKey: "南笙" });
assert.strictEqual(brain.relationMatchesHighlight(highlight, "南笙"), true);
assert.strictEqual(brain.relationMatchesHighlight(highlight, "南笙（QQ）"), true);
assert.strictEqual(brain.relationMatchesHighlight(highlight, "大肥鱼"), false);
assert.strictEqual(brain.relationMatchesHighlight(brain.normalizeHighlight(null), "南笙"), false);

const fallbackRenderer = brain.createRenderer({}, {});
fallbackRenderer.setHighlight({ memoryIds: [140, "140"], relationKey: "南笙" });
assert.deepStrictEqual(fallbackRenderer.getHighlight(), {
  memoryIds: [140],
  relationKey: "南笙",
});
console.log("brain model tests passed");
