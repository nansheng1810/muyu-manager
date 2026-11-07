/* 管理器 · 记忆脑图：确定性布局 + 2D 科学可视化 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerBrain = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
  const TYPES = {
    FACTUAL: "事实",
    PREFERENCE: "偏好",
    RELATIONAL: "关系",
    PLANNED: "计划",
    EPISODIC: "情景",
    UNKNOWN: "未知",
    GENERAL: "未分类",
  };
  const TYPE_COLORS = {
    FACTUAL: "#c9b38a",
    PREFERENCE: "#7db7a5",
    RELATIONAL: "#7f9fc9",
    PLANNED: "#c9a06a",
    EPISODIC: "#b98a92",
    UNKNOWN: "#8b97a8",
    GENERAL: "#8b97a8",
  };

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function clamp01(value, fallback = 0.5) {
    const n = Number(value);
    return Number.isFinite(n) ? clamp(n, 0, 1) : fallback;
  }

  function formatType(value) {
    return TYPES[String(value || "").toUpperCase()] || "未分类";
  }

  function typeColor(value) {
    return TYPE_COLORS[String(value || "").toUpperCase()] || TYPE_COLORS.GENERAL;
  }

  function normalizeHighlight(input) {
    const source = input && typeof input === "object" ? input : {};
    const ids = Array.isArray(source.memoryIds) ? source.memoryIds : [];
    const seen = new Set();
    const memoryIds = [];
    for (const raw of ids) {
      if (raw === null || raw === undefined || raw === "") continue;
      const id = Number(raw);
      if (!Number.isFinite(id) || id <= 0 || seen.has(id)) continue;
      seen.add(id);
      memoryIds.push(id);
    }
    return {
      memoryIds,
      relationKey: String(source.relationKey ?? "").trim(),
    };
  }

  function relationMatchesHighlight(highlight, ...values) {
    const key = String((highlight && highlight.relationKey) || "").trim().toLowerCase();
    if (!key) return false;
    return values.some((value) => {
      const text = String(value ?? "").trim().toLowerCase();
      return Boolean(text) && (text === key || text.includes(key));
    });
  }

  function memoryIsHighlighted(highlight, memoryId) {
    const id = Number(memoryId);
    return Boolean(
      highlight &&
        Number.isFinite(id) &&
        Array.isArray(highlight.memoryIds) &&
        highlight.memoryIds.includes(id)
    );
  }

  function hashString(text) {
    let h = 2166136261;
    for (let i = 0; i < String(text).length; i += 1) {
      h ^= String(text).charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function mulberry32(seed) {
    let a = seed >>> 0;
    return function random() {
      a += 0x6d2b79f5;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function metadataOf(item) {
    const raw = item && item.metadata;
    if (raw && typeof raw === "object") return raw;
    if (typeof raw === "string" && raw.trim()) {
      try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : {};
      } catch (_) {
        return {};
      }
    }
    return {};
  }

  function normalizeMemory(item) {
    const metadata = metadataOf(item);
    const keyFacts = Array.isArray(metadata.key_facts) ? metadata.key_facts : [];
    return {
      id: Number(item.id ?? metadata.memory_id),
      summary: String(
        item.text ||
          metadata.persona_summary ||
          metadata.canonical_summary ||
          "（无摘要）"
      ),
      type: String(metadata.memory_type || "GENERAL").toUpperCase(),
      importance: clamp01(metadata.importance, 0.5),
      arousal: clamp01(metadata.arousal, 0.3),
      salience: clamp01(metadata.salience, 0.5),
      sessionId: String(metadata.session_id || ""),
      personaId: String(metadata.persona_id || ""),
      keyFacts,
      createdAt: Number(metadata.create_time || 0),
      atomEstimate: clamp(Math.round((keyFacts.length || 2) + 1), 2, 7),
    };
  }

  function normalizeGraph(graph) {
    const source = graph && graph.snapshot ? graph.snapshot : graph || {};
    const nodes = Array.isArray(source.nodes) ? source.nodes : [];
    const edges = Array.isArray(source.edges) ? source.edges : [];
    return { source, nodes, edges };
  }

  function ellipseClamp(x, y, cx, cy, rx, ry) {
    const dx = (x - cx) / Math.max(1, rx);
    const dy = (y - cy) / Math.max(1, ry);
    const d = Math.sqrt(dx * dx + dy * dy);
    if (d <= 1) return { x, y };
    return { x: cx + (dx / d) * rx, y: cy + (dy / d) * ry };
  }

  function layoutGraph(nodes, edges, width, height, seed = 7) {
    const random = mulberry32(seed);
    const cx = width * 0.47;
    const cy = height * 0.49;
    const rx = width * 0.24;
    const ry = height * 0.22;
    const positions = new Map();
    const typeAngle = { fact: -0.6, participant: 0.8, topic: 2.5, unknown: 0 };

    nodes.forEach((node, index) => {
      const type = String(node.type || "unknown");
      const base = typeAngle[type] ?? (GOLDEN_ANGLE * index);
      const angle = base + random() * 0.9 + index * 0.13;
      const radius = 0.32 + random() * 0.62;
      positions.set(String(node.id), {
        x: cx + Math.cos(angle) * rx * radius,
        y: cy + Math.sin(angle) * ry * radius,
        vx: 0,
        vy: 0,
      });
    });

    const linkPairs = [];
    const seen = new Set();
    for (const edge of edges) {
      const a = String(edge.source);
      const b = String(edge.target);
      if (a === b || !positions.has(a) || !positions.has(b)) continue;
      const key = a < b ? `${a}|${b}` : `${b}|${a}`;
      if (seen.has(key)) continue;
      seen.add(key);
      linkPairs.push([a, b, clamp(Number(edge.weight) || 1, 0.2, 5)]);
    }

    const ids = [...positions.keys()];
    for (let step = 0; step < 60; step += 1) {
      for (let i = 0; i < ids.length; i += 1) {
        const a = positions.get(ids[i]);
        for (let j = i + 1; j < ids.length; j += 1) {
          const b = positions.get(ids[j]);
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let dist2 = dx * dx + dy * dy;
          if (dist2 < 1) {
            dx = random() - 0.5;
            dy = random() - 0.5;
            dist2 = 1;
          }
          const force = 340 / Math.max(80, dist2);
          const dist = Math.sqrt(dist2);
          a.vx += (dx / dist) * force;
          a.vy += (dy / dist) * force;
          b.vx -= (dx / dist) * force;
          b.vy -= (dy / dist) * force;
        }
      }
      for (const [aKey, bKey, weight] of linkPairs) {
        const a = positions.get(aKey);
        const b = positions.get(bKey);
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const force = (dist - 62) * 0.0018 * weight;
        a.vx += (dx / dist) * force;
        a.vy += (dy / dist) * force;
        b.vx -= (dx / dist) * force;
        b.vy -= (dy / dist) * force;
      }
      for (const key of ids) {
        const p = positions.get(key);
        p.vx += (cx - p.x) * 0.0009;
        p.vy += (cy - p.y) * 0.0009;
        p.vx *= 0.72;
        p.vy *= 0.72;
        p.x += p.vx;
        p.y += p.vy;
        const bounded = ellipseClamp(p.x, p.y, cx, cy, rx, ry);
        p.x = bounded.x;
        p.y = bounded.y;
      }
    }
    return positions;
  }

  function buildModel(memories, graph, options = {}) {
    const width = Math.max(320, Number(options.width) || 900);
    const height = Math.max(280, Number(options.height) || 520);
    const maxMemories = clamp(Number(options.maxMemories) || 60, 1, 120);
    const maxGraphNodes = clamp(Number(options.maxGraphNodes) || 80, 1, 120);
    const maxEdges = clamp(Number(options.maxEdges) || 120, 1, 240);
    const seed = Number(options.seed) || 7;

    const allMemories = (Array.isArray(memories) ? memories : [])
      .map(normalizeMemory)
      .filter((item) => Number.isFinite(item.id))
      .sort(
        (a, b) =>
          b.importance - a.importance ||
          b.salience - a.salience ||
          b.createdAt - a.createdAt ||
          b.id - a.id
      )
      .slice(0, maxMemories);

    const graphData = normalizeGraph(graph);
    const seenNodes = new Set();
    const graphNodes = [];
    for (const raw of graphData.nodes) {
      const id = raw.id;
      if (id === undefined || id === null || seenNodes.has(String(id))) continue;
      seenNodes.add(String(id));
      graphNodes.push({
        id,
        key: String(id),
        label: String(raw.label || raw.canonical_value || raw.key || id),
        type: String(raw.type || "unknown"),
        degree: Number(raw.degree) || 0,
        weight: Number(raw.weight) || 0,
      });
      if (graphNodes.length >= maxGraphNodes) break;
    }

    const nodeKeys = new Set(graphNodes.map((node) => node.key));
    const graphEdges = [];
    const edgeSeen = new Set();
    for (const raw of graphData.edges) {
      const source = String(raw.source);
      const target = String(raw.target);
      if (source === target || !nodeKeys.has(source) || !nodeKeys.has(target)) continue;
      const key = `${source}|${target}|${raw.memory_id || ""}`;
      if (edgeSeen.has(key)) continue;
      edgeSeen.add(key);
      graphEdges.push({
        id: raw.id,
        source,
        target,
        memoryId: Number(raw.memory_id) || null,
        relationType: String(raw.relation_type || ""),
        weight: clamp(Number(raw.weight) || 1, 0.2, 5),
      });
      if (graphEdges.length >= maxEdges) break;
    }

    const graphPositions = layoutGraph(graphNodes, graphEdges, width, height, seed);
    for (const node of graphNodes) {
      const point = graphPositions.get(node.key);
      node.x = point ? point.x : width / 2;
      node.y = point ? point.y : height / 2;
      node.r = 2.2 + Math.min(5, Math.sqrt(Math.max(0, node.degree)) * 0.75);
    }

    const hippocampus = {
      x: width * 0.43,
      y: height * 0.58,
      scale: Math.min(width * 0.19, height * 0.27),
    };
    const brainCx = width * 0.47;
    const brainCy = height * 0.5;
    const memMap = new Map();
    allMemories.forEach((memory, index) => {
      const ring = index < 30 ? 0 : 1;
      const jitter = ((hashString(`m:${memory.id}`) % 100) / 100 - 0.5) * 0.03;
      const angle = index * GOLDEN_ANGLE + ring * 0.45;
      const radiusX = width * (0.285 - ring * 0.045 + jitter);
      const radiusY = height * (0.3 - ring * 0.045 + jitter * 0.7);
      const bounded = ellipseClamp(
        brainCx + Math.cos(angle) * radiusX,
        brainCy + Math.sin(angle) * radiusY,
        brainCx,
        brainCy,
        width * 0.335,
        height * 0.335
      );
      memory.x = clamp(bounded.x, 22, width - 22);
      memory.y = clamp(bounded.y, 22, height - 22);
      memory.r = 2.6 + memory.importance * 3.6 + memory.salience * 1.2;
      memMap.set(memory.id, memory);
    });

    const memoryLinks = [];
    for (const edge of graphEdges) {
      if (!edge.memoryId || !memMap.has(edge.memoryId)) continue;
      const memory = memMap.get(edge.memoryId);
      const node = graphNodes.find((item) => item.key === edge.source);
      if (!node) continue;
      memoryLinks.push({
        memoryId: edge.memoryId,
        nodeId: node.id,
        sourceX: memory.x,
        sourceY: memory.y,
        targetX: node.x,
        targetY: node.y,
        weight: edge.weight,
        phase: (hashString(`${edge.id}|${edge.memoryId}`) % 1000) / 1000,
      });
    }

    const sessionGroups = new Map();
    for (const memory of allMemories) {
      if (!memory.sessionId) continue;
      const group = sessionGroups.get(memory.sessionId) || [];
      group.push(memory);
      sessionGroups.set(memory.sessionId, group);
    }
    const sessionLinks = [];
    for (const group of sessionGroups.values()) {
      group.sort((a, b) => a.id - b.id);
      for (let i = 1; i < group.length; i += 1) {
        const a = group[i - 1];
        const b = group[i];
        sessionLinks.push({
          sourceX: a.x,
          sourceY: a.y,
          targetX: b.x,
          targetY: b.y,
          phase: (hashString(`${a.id}:${b.id}`) % 1000) / 1000,
        });
        if (sessionLinks.length >= 160) break;
      }
      if (sessionLinks.length >= 160) break;
    }

    const particles = [];
    for (const memory of allMemories) {
      const count = memory.atomEstimate;
      for (let i = 0; i < count; i += 1) {
        const angle = (hashString(`${memory.id}:${i}`) % 360) * (Math.PI / 180);
        const radius = memory.r + 3 + ((hashString(`${i}:${memory.id}`) % 100) / 100) * 14;
        particles.push({
          memoryId: memory.id,
          type: memory.type,
          baseX: memory.x + Math.cos(angle) * radius,
          baseY: memory.y + Math.sin(angle) * radius,
          radius: 0.45 + ((hashString(`${memory.id}:p:${i}`) % 100) / 100) * 0.8,
          phase: (hashString(`${memory.id}:phase:${i}`) % 6283) / 1000,
        });
      }
      if (particles.length >= 700) break;
    }

    return {
      width,
      height,
      memories: allMemories,
      graphNodes,
      graphEdges,
      memoryLinks,
      sessionLinks,
      particles: particles.slice(0, 700),
      hippocampus,
      seed,
    };
  }

  function hitTest(model, x, y) {
    if (!model) return null;
    for (let i = model.memories.length - 1; i >= 0; i -= 1) {
      const memory = model.memories[i];
      const dx = x - memory.x;
      const dy = y - memory.y;
      if (dx * dx + dy * dy <= (memory.r + 7) * (memory.r + 7)) {
        return { kind: "memory", id: memory.id, item: memory };
      }
    }
    for (let i = model.graphNodes.length - 1; i >= 0; i -= 1) {
      const node = model.graphNodes[i];
      const dx = x - node.x;
      const dy = y - node.y;
      if (dx * dx + dy * dy <= (node.r + 5) * (node.r + 5)) {
        return { kind: "graph", id: node.id, node };
      }
    }
    return null;
  }

  function hexPoints(cx, cy, r) {
    const points = [];
    for (let i = 0; i < 6; i += 1) {
      const angle = -Math.PI / 2 + (Math.PI / 3) * i;
      points.push({ x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r });
    }
    return points;
  }

  function quadraticPoint(p0, p1, p2, t) {
    const mt = 1 - t;
    return {
      x: mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x,
      y: mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y,
    };
  }

  function drawBrain(ctx, width, height, palette) {
    const cx = width * 0.47;
    const cy = height * 0.49;
    const sx = width * 0.37;
    const sy = height * 0.38;

    const tissue = ctx.createLinearGradient(cx - sx, cy - sy, cx + sx, cy + sy);
    tissue.addColorStop(0, "rgba(196, 181, 158, 0.2)");
    tissue.addColorStop(0.5, "rgba(151, 141, 127, 0.09)");
    tissue.addColorStop(1, "rgba(103, 119, 138, 0.16)");

    // Cerebellum and brainstem sit behind the cerebral hemisphere.
    ctx.save();
    ctx.beginPath();
    ctx.ellipse(cx + 0.35 * sx, cy + 0.65 * sy, 0.23 * sx, 0.16 * sy, 0.18, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(157, 143, 121, 0.14)";
    ctx.strokeStyle = palette.brainLine;
    ctx.lineWidth = 0.9;
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "rgba(205, 190, 166, 0.2)";
    ctx.lineWidth = 0.6;
    for (let i = 0; i < 7; i += 1) {
      const t = i / 8;
      ctx.beginPath();
      ctx.arc(
        cx + 0.35 * sx,
        cy + 0.65 * sy,
        0.15 * sx + t * 0.1 * sx,
        0.35 + t * 2.3,
        1.55 + t * 2.0
      );
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(cx + 0.02 * sx, cy + 0.52 * sy);
    ctx.bezierCurveTo(
      cx + 0.05 * sx, cy + 0.72 * sy,
      cx + 0.08 * sx, cy + 0.9 * sy,
      cx + 0.04 * sx, cy + 1.02 * sy
    );
    ctx.bezierCurveTo(
      cx - 0.05 * sx, cy + 1.05 * sy,
      cx - 0.08 * sx, cy + 0.82 * sy,
      cx - 0.05 * sx, cy + 0.55 * sy
    );
    ctx.closePath();
    ctx.fillStyle = "rgba(157, 143, 121, 0.13)";
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    const path = new Path2D();
    path.moveTo(cx - 0.94 * sx, cy + 0.02 * sy);
    path.bezierCurveTo(cx - 1.04 * sx, cy - 0.24 * sy, cx - 0.84 * sx, cy - 0.5 * sy, cx - 0.54 * sx, cy - 0.57 * sy);
    path.bezierCurveTo(cx - 0.32 * sx, cy - 0.62 * sy, cx - 0.12 * sx, cy - 0.54 * sy, cx + 0.02 * sx, cy - 0.47 * sy);
    path.bezierCurveTo(cx + 0.18 * sx, cy - 0.63 * sy, cx + 0.46 * sx, cy - 0.63 * sy, cx + 0.64 * sx, cy - 0.47 * sy);
    path.bezierCurveTo(cx + 0.84 * sx, cy - 0.3 * sy, cx + 0.95 * sx, cy - 0.02 * sy, cx + 0.84 * sx, cy + 0.22 * sy);
    path.bezierCurveTo(cx + 0.78 * sx, cy + 0.4 * sy, cx + 0.62 * sx, cy + 0.5 * sy, cx + 0.45 * sx, cy + 0.52 * sy);
    path.bezierCurveTo(cx + 0.34 * sx, cy + 0.62 * sy, cx + 0.18 * sx, cy + 0.64 * sy, cx + 0.06 * sx, cy + 0.55 * sy);
    path.bezierCurveTo(cx - 0.04 * sx, cy + 0.48 * sy, cx - 0.16 * sx, cy + 0.48 * sy, cx - 0.26 * sx, cy + 0.54 * sy);
    path.bezierCurveTo(cx - 0.45 * sx, cy + 0.63 * sy, cx - 0.68 * sx, cy + 0.55 * sy, cx - 0.8 * sx, cy + 0.42 * sy);
    path.bezierCurveTo(cx - 0.9 * sx, cy + 0.32 * sy, cx - 0.94 * sx, cy + 0.16 * sy, cx - 0.94 * sx, cy + 0.02 * sy);
    path.closePath();

    ctx.fillStyle = tissue;
    ctx.fill(path);
    ctx.strokeStyle = "rgba(215, 201, 180, 0.46)";
    ctx.lineWidth = 1.35;
    ctx.stroke(path);

    ctx.save();
    ctx.clip(path);
    ctx.strokeStyle = "rgba(213, 197, 173, 0.19)";
    ctx.lineWidth = 0.7;
    for (let i = 0; i < 16; i += 1) {
      const offset = i / 15;
      ctx.beginPath();
      ctx.moveTo(cx - 0.91 * sx + offset * 0.05 * sx, cy - 0.42 * sy + offset * 0.72 * sy);
      ctx.bezierCurveTo(
        cx - 0.5 * sx,
        cy - 0.67 * sy + offset * 0.72 * sy,
        cx + 0.28 * sx,
        cy - 0.57 * sy + offset * 0.62 * sy,
        cx + 0.84 * sx,
        cy - 0.22 * sy + offset * 0.48 * sy
      );
      ctx.stroke();
    }
    // Sylvian fissure and central sulcus make the silhouette read as a brain.
    ctx.strokeStyle = "rgba(228, 211, 185, 0.34)";
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    ctx.moveTo(cx - 0.92 * sx, cy + 0.13 * sy);
    ctx.bezierCurveTo(cx - 0.62 * sx, cy + 0.18 * sy, cx - 0.34 * sx, cy + 0.14 * sy, cx - 0.12 * sx, cy + 0.3 * sy);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx - 0.16 * sx, cy - 0.58 * sy);
    ctx.bezierCurveTo(cx - 0.05 * sx, cy - 0.3 * sy, cx + 0.02 * sx, cy + 0.1 * sy, cx - 0.1 * sx, cy + 0.44 * sy);
    ctx.stroke();
    ctx.strokeStyle = "rgba(226, 210, 185, 0.18)";
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(cx + 0.5 * sx, cy - 0.48 * sy);
    ctx.bezierCurveTo(cx + 0.45 * sx, cy - 0.12 * sy, cx + 0.5 * sx, cy + 0.18 * sy, cx + 0.36 * sx, cy + 0.48 * sy);
    ctx.stroke();
    ctx.restore();

    ctx.fillStyle = palette.muted;
    ctx.font = '8px "IBM Plex Mono", "Cascadia Code", monospace';
    ctx.fillText("FRONTAL", cx - 0.82 * sx, cy - 0.3 * sy);
    ctx.fillText("PARIETAL", cx + 0.28 * sx, cy - 0.4 * sy);
    ctx.fillText("OCCIPITAL", cx + 0.7 * sx, cy + 0.12 * sy);
    ctx.fillText("TEMPORAL", cx - 0.56 * sx, cy + 0.74 * sy);
    ctx.fillText("CEREBELLUM", cx + 0.3 * sx, cy + 0.83 * sy);
    ctx.fillText("BRAINSTEM", cx + 0.09 * sx, cy + 0.96 * sy);
  }

  function hippocampusSpine(hc, s, dy = 0) {
    const path = new Path2D();
    path.moveTo(hc.x - 0.58 * s, hc.y + 0.28 * s + dy);
    path.bezierCurveTo(
      hc.x - 0.92 * s, hc.y + 0.12 * s + dy,
      hc.x - 0.72 * s, hc.y - 0.4 * s + dy,
      hc.x - 0.2 * s, hc.y - 0.42 * s + dy
    );
    path.bezierCurveTo(
      hc.x + 0.24 * s, hc.y - 0.44 * s + dy,
      hc.x + 0.62 * s, hc.y - 0.12 * s + dy,
      hc.x + 0.44 * s, hc.y + 0.2 * s + dy
    );
    path.bezierCurveTo(
      hc.x + 0.3 * s, hc.y + 0.44 * s + dy,
      hc.x + 0.1 * s, hc.y + 0.56 * s + dy,
      hc.x - 0.02 * s, hc.y + 0.5 * s + dy
    );
    return path;
  }

  function drawHippocampus(ctx, model, palette) {
    const hc = model.hippocampus;
    const s = hc.scale;
    const spine = hippocampusSpine(hc, s);
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    // Curved body with a warm tissue edge and a cooler interior.
    ctx.strokeStyle = "rgba(211, 177, 132, 0.22)";
    ctx.lineWidth = 0.33 * s;
    ctx.stroke(spine);
    ctx.strokeStyle = "rgba(157, 139, 112, 0.18)";
    ctx.lineWidth = 0.23 * s;
    ctx.stroke(spine);

    const bands = [
      { dy: -0.055 * s, width: 0.045, color: "rgba(194, 148, 140, 0.58)" },
      { dy: 0.0, width: 0.06, color: "rgba(197, 160, 103, 0.6)" },
      { dy: 0.06 * s, width: 0.042, color: "rgba(101, 124, 151, 0.62)" },
      { dy: 0.115 * s, width: 0.03, color: "rgba(144, 160, 174, 0.42)" },
    ];
    for (const band of bands) {
      ctx.strokeStyle = band.color;
      ctx.lineWidth = Math.max(2, s * band.width);
      ctx.stroke(hippocampusSpine(hc, s, band.dy));
    }

    // Hippocampal head and the beginning of the curled tail.
    const head = ctx.createRadialGradient(
      hc.x - 0.62 * s, hc.y + 0.2 * s, 0.01 * s,
      hc.x - 0.58 * s, hc.y + 0.28 * s, 0.19 * s
    );
    head.addColorStop(0, "rgba(224, 188, 139, 0.28)");
    head.addColorStop(1, "rgba(154, 132, 103, 0.16)");
    ctx.beginPath();
    ctx.ellipse(
      hc.x - 0.58 * s, hc.y + 0.28 * s,
      0.17 * s, 0.13 * s, -0.35, 0, Math.PI * 2
    );
    ctx.fillStyle = head;
    ctx.strokeStyle = "rgba(226, 191, 148, 0.4)";
    ctx.lineWidth = 0.8;
    ctx.fill();
    ctx.stroke();

    ctx.beginPath();
    ctx.strokeStyle = "rgba(186, 154, 116, 0.28)";
    ctx.lineWidth = Math.max(2, s * 0.045);
    ctx.moveTo(hc.x - 0.02 * s, hc.y + 0.5 * s);
    ctx.bezierCurveTo(
      hc.x + 0.2 * s, hc.y + 0.62 * s,
      hc.x + 0.12 * s, hc.y + 0.74 * s,
      hc.x - 0.04 * s, hc.y + 0.7 * s
    );
    ctx.stroke();

    // Fine tissue hatching across the curved body.
    const p0 = { x: hc.x - 0.58 * s, y: hc.y + 0.28 * s };
    const p1 = { x: hc.x - 0.1 * s, y: hc.y - 0.62 * s };
    const p2 = { x: hc.x + 0.44 * s, y: hc.y + 0.2 * s };
    ctx.strokeStyle = "rgba(231, 205, 172, 0.2)";
    ctx.lineWidth = 0.55;
    for (let i = 0; i < 24; i += 1) {
      const t = 0.05 + (i / 23) * 0.9;
      const a = quadraticPoint(p0, p1, p2, t);
      const b = quadraticPoint(p0, p1, p2, Math.min(1, t + 0.012));
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const length = Math.max(0.001, Math.sqrt(dx * dx + dy * dy));
      const nx = -dy / length;
      const ny = dx / length;
      const half = (0.1 + Math.sin(t * Math.PI) * 0.05) * s;
      ctx.beginPath();
      ctx.moveTo(a.x - nx * half, a.y - ny * half);
      ctx.lineTo(a.x + nx * half, a.y + ny * half);
      ctx.stroke();
    }

    // A few cell nuclei along the principal cell layer.
    ctx.fillStyle = "rgba(225, 204, 176, 0.42)";
    for (let i = 0; i < 30; i += 1) {
      const t = 0.06 + (i / 29) * 0.86;
      const point = quadraticPoint(p0, p1, p2, t);
      const offset = Math.sin(t * 14) * 0.025 * s;
      ctx.beginPath();
      ctx.arc(point.x, point.y + offset, 0.8, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.fillStyle = palette.muted;
    ctx.font = '8px "IBM Plex Mono", "Cascadia Code", monospace';
    ctx.fillText("CA1", hc.x + 0.34 * s, hc.y + 0.12 * s);
    ctx.fillText("CA3", hc.x - 0.04 * s, hc.y - 0.36 * s);
    ctx.fillText("DG", hc.x - 0.46 * s, hc.y + 0.18 * s);
    ctx.fillText("SUB", hc.x + 0.26 * s, hc.y + 0.47 * s);
    ctx.fillText("HIPPOCAMPAL FORMATION", hc.x - 0.5 * s, hc.y + 0.94 * s);
    ctx.restore();
  }

  function createRenderer(canvas, options = {}) {
    let highlight = normalizeHighlight(null);
    const ctx = canvas && canvas.getContext ? canvas.getContext("2d") : null;
    if (!ctx) {
      return {
        render() {},
        setSelected() {},
        setHighlight(next) {
          highlight = normalizeHighlight(next);
        },
        getHighlight() {
          return { memoryIds: [...highlight.memoryIds], relationKey: highlight.relationKey };
        },
        resize() {},
        destroy() {},
        getSize() { return { width: 0, height: 0 }; },
      };
    }
    const reduceMotion = Boolean(
      options.reducedMotion ||
        (typeof window !== "undefined" &&
          window.matchMedia &&
          window.matchMedia("(prefers-reduced-motion: reduce)").matches)
    );
    let model = null;
    let selectedId = null;
    let hover = null;
    let width = 900;
    let height = 520;
    let dpr = 1;
    let raf = 0;
    let running = false;
    let lastFrame = 0;
    let dragging = false;
    let moved = false;
    let lastPoint = null;
    const view = { scale: 1, panX: 0, panY: 0 };

    function cssVar(name, fallback) {
      try {
        const value = getComputedStyle(canvas).getPropertyValue(name).trim();
        return value || fallback;
      } catch (_) {
        return fallback;
      }
    }

    function palette() {
      return {
        text: cssVar("--text", "#e9eef8"),
        muted: cssVar("--muted", "#9da9c1"),
        line: cssVar("--line", "rgba(255,255,255,.08)"),
        accent: cssVar("--accent", "#5b8cff"),
        tissueA: "rgba(190, 176, 154, 0.15)",
        tissueB: "rgba(151, 141, 127, 0.07)",
        tissueC: "rgba(108, 119, 135, 0.12)",
        brainLine: "rgba(203, 192, 176, 0.3)",
        gyri: "rgba(203, 192, 176, 0.12)",
        hippoFill: "rgba(197, 160, 118, 0.19)",
        hippoLine: "rgba(218, 184, 144, 0.48)",
        ca1: "rgba(208, 156, 127, 0.46)",
        ca3: "rgba(180, 145, 105, 0.46)",
        dg: "rgba(125, 142, 166, 0.48)",
        hatch: "rgba(220, 199, 171, 0.18)",
        particle: "rgba(219, 205, 184, 0.38)",
        graphNode: "rgba(175, 194, 211, 0.58)",
        graphEdge: "rgba(151, 174, 194, 0.14)",
        memoryLink: "rgba(188, 168, 137, 0.18)",
      };
    }

    function resize() {
      const rect = canvas.getBoundingClientRect();
      width = Math.max(320, Math.round(rect.width || canvas.clientWidth || 900));
      height = Math.max(280, Math.round(rect.height || canvas.clientHeight || 520));
      dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function screenToWorld(x, y) {
      return {
        x: (x - width / 2 - view.panX) / view.scale + width / 2,
        y: (y - height / 2 - view.panY) / view.scale + height / 2,
      };
    }

    function eventPoint(event) {
      const rect = canvas.getBoundingClientRect();
      return {
        x: (event.clientX - rect.left) * (width / Math.max(1, rect.width)),
        y: (event.clientY - rect.top) * (height / Math.max(1, rect.height)),
      };
    }

    function pointerHit(event) {
      const point = eventPoint(event);
      const world = screenToWorld(point.x, point.y);
      return { point, world, hit: hitTest(model, world.x, world.y) };
    }

    function drawParticles(p, time) {
      for (const particle of model.particles) {
        const t = time * 0.00018 + particle.phase;
        const x = particle.baseX + Math.sin(t) * 1.8;
        const y = particle.baseY + Math.cos(t * 0.8) * 1.8;
        ctx.beginPath();
        ctx.fillStyle = typeColor(particle.type);
        ctx.globalAlpha = 0.15;
        ctx.arc(x, y, particle.radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    }

    function drawGraph(p, time) {
      const highlightOn = highlight.memoryIds.length > 0 || Boolean(highlight.relationKey);
      for (const edge of model.graphEdges) {
        const a = model.graphNodes.find((node) => node.key === edge.source);
        const b = model.graphNodes.find((node) => node.key === edge.target);
        if (!a || !b) continue;
        const related =
          relationMatchesHighlight(highlight, edge.relationType) ||
          memoryIsHighlighted(highlight, edge.memoryId);
        const midX = (a.x + b.x) / 2;
        const midY = (a.y + b.y) / 2;
        const bend = Math.sin(hashString(String(edge.id)) % 6283 / 1000) * 14;
        const cx = midX + (b.y - a.y) * 0.08 + bend;
        const cy = midY - (b.x - a.x) * 0.08;
        ctx.globalAlpha = highlightOn && !related ? 0.28 : 1;
        ctx.beginPath();
        ctx.strokeStyle = related
          ? "rgba(201, 179, 138, 0.9)"
          : "rgba(164, 184, 201, 0.22)";
        ctx.lineWidth = related ? 1.3 : 0.75;
        ctx.moveTo(a.x, a.y);
        ctx.quadraticCurveTo(cx, cy, b.x, b.y);
        ctx.stroke();
        if (!reduceMotion && edge.weight >= 1.5) {
          const t = ((time * 0.00006 + hashString(String(edge.id)) / 6283) % 1);
          const pulse = quadraticPoint(a, { x: cx, y: cy }, b, t);
          ctx.beginPath();
          ctx.fillStyle = related ? "rgba(214, 190, 150, 0.9)" : "rgba(198, 178, 146, 0.55)";
          ctx.arc(pulse.x, pulse.y, 1.3, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.globalAlpha = 1;
      }
      for (const link of model.sessionLinks || []) {
        ctx.beginPath();
        ctx.globalAlpha = highlightOn ? 0.35 : 1;
        ctx.setLineDash([1, 6]);
        ctx.strokeStyle = "rgba(164, 183, 199, 0.075)";
        ctx.lineWidth = 0.55;
        ctx.moveTo(link.sourceX, link.sourceY);
        ctx.quadraticCurveTo(
          (link.sourceX + link.targetX) / 2,
          (link.sourceY + link.targetY) / 2 - 6,
          link.targetX,
          link.targetY
        );
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      for (const link of model.memoryLinks) {
        const active = link.memoryId === selectedId;
        const highlighted = memoryIsHighlighted(highlight, link.memoryId);
        ctx.beginPath();
        ctx.globalAlpha = highlightOn && !highlighted ? 0.3 : 1;
        ctx.setLineDash(active || highlighted ? [3, 3] : [1, 5]);
        ctx.strokeStyle = highlighted
          ? "rgba(201, 179, 138, 0.72)"
          : active
            ? "rgba(200, 178, 143, 0.56)"
            : p.memoryLink;
        ctx.lineWidth = highlighted ? 1.2 : active ? 1.1 : 0.7;
        ctx.moveTo(link.sourceX, link.sourceY);
        ctx.quadraticCurveTo(
          (link.sourceX + link.targetX) / 2 + 8,
          (link.sourceY + link.targetY) / 2 - 8,
          link.targetX,
          link.targetY
        );
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      ctx.setLineDash([]);
    }

    function drawGraphNodes(p) {
      const highlightOn = highlight.memoryIds.length > 0 || Boolean(highlight.relationKey);
      for (const node of model.graphNodes) {
        const related = relationMatchesHighlight(highlight, node.key, node.label, node.id);
        ctx.globalAlpha = highlightOn && !related ? 0.3 : 1;
        ctx.beginPath();
        ctx.fillStyle = p.graphNode;
        ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
        ctx.fill();
        const hovered = hover && hover.kind === "graph" && hover.id === node.id;
        if (related || hovered) {
          ctx.strokeStyle = related ? "rgba(201, 179, 138, 0.95)" : p.accent;
          ctx.lineWidth = related ? 1.5 : 1.2;
          ctx.stroke();
        }
        if (hovered) {
          ctx.fillStyle = p.text;
          ctx.font = '11px "IBM Plex Sans", "Segoe UI", sans-serif';
          ctx.fillText(node.label.slice(0, 34), node.x + node.r + 5, node.y + 3);
        }
        ctx.globalAlpha = 1;
      }
    }

    function drawMemories(p) {
      const highlightOn = highlight.memoryIds.length > 0 || Boolean(highlight.relationKey);
      for (const memory of model.memories) {
        const active = memory.id === selectedId;
        const hovered = hover && hover.kind === "memory" && hover.id === memory.id;
        const highlighted = memoryIsHighlighted(highlight, memory.id);
        ctx.beginPath();
        ctx.fillStyle = typeColor(memory.type);
        const baseAlpha = active ? 1 : hovered ? 0.92 : 0.72;
        ctx.globalAlpha = highlightOn && !highlighted && !active
          ? Math.min(baseAlpha, 0.3)
          : baseAlpha;
        ctx.arc(memory.x, memory.y, memory.r, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.strokeStyle = active
          ? p.accent
          : highlighted
            ? "rgba(201, 179, 138, 0.95)"
            : `rgba(201, 185, 157, ${0.2 + memory.salience * 0.42})`;
        ctx.lineWidth = active ? 2 : highlighted ? 2.2 : 0.9;
        ctx.arc(memory.x, memory.y, memory.r + 2.5, 0, Math.PI * 2);
        ctx.stroke();
        if (active || hovered || highlighted || memory.importance >= 0.88) {
          ctx.fillStyle = active ? p.text : highlighted ? "rgba(219, 200, 165, 0.95)" : p.muted;
          ctx.font = '9px "IBM Plex Mono", "Cascadia Code", monospace';
          ctx.fillText(`#${memory.id}`, memory.x + memory.r + 5, memory.y + 3);
        }
      }
    }

    function draw(time) {
      if (!model) return;
      const p = palette();
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(width / 2 + view.panX, height / 2 + view.panY);
      ctx.scale(view.scale, view.scale);
      ctx.translate(-width / 2, -height / 2);

      ctx.strokeStyle = p.line;
      ctx.lineWidth = 0.5;
      ctx.globalAlpha = 0.5;
      for (let x = 24; x < width; x += 32) {
        ctx.beginPath();
        ctx.moveTo(x, 12);
        ctx.lineTo(x, height - 12);
        ctx.stroke();
      }
      for (let y = 24; y < height; y += 32) {
        ctx.beginPath();
        ctx.moveTo(12, y);
        ctx.lineTo(width - 12, y);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      drawBrain(ctx, width, height, p);
      drawHippocampus(ctx, model, p);
      drawParticles(p, reduceMotion ? 0 : time);
      drawGraph(p, reduceMotion ? 0 : time);
      drawGraphNodes(p);
      drawMemories(p);
      ctx.restore();
    }

    function frame(timestamp) {
      if (!running) return;
      if (!document.hidden && timestamp - lastFrame > 32) {
        lastFrame = timestamp;
        draw(timestamp);
      }
      raf = requestAnimationFrame(frame);
    }

    function start() {
      if (running) return;
      running = true;
      lastFrame = 0;
      if (reduceMotion) {
        draw(0);
        return;
      }
      raf = requestAnimationFrame(frame);
    }

    function stop() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    }

    function onPointerMove(event) {
      const result = pointerHit(event);
      if (dragging) {
        const dx = event.clientX - lastPoint.x;
        const dy = event.clientY - lastPoint.y;
        if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
        view.panX += dx * (width / Math.max(1, canvas.getBoundingClientRect().width));
        view.panY += dy * (height / Math.max(1, canvas.getBoundingClientRect().height));
        lastPoint = { x: event.clientX, y: event.clientY };
      }
      hover = result.hit;
      canvas.style.cursor = result.hit ? "pointer" : dragging ? "grabbing" : "grab";
      if (options.onHover) {
        options.onHover(result.hit, {
          x: event.clientX,
          y: event.clientY,
        });
      }
      if (reduceMotion) draw(0);
    }

    function onPointerDown(event) {
      dragging = true;
      moved = false;
      lastPoint = { x: event.clientX, y: event.clientY };
      canvas.setPointerCapture?.(event.pointerId);
    }

    function onPointerUp(event) {
      if (!dragging) return;
      dragging = false;
      canvas.releasePointerCapture?.(event.pointerId);
      if (!moved) {
        const result = pointerHit(event);
        if (result.hit) {
          if (result.hit.kind === "memory") {
            selectedId = result.hit.id;
            options.onSelectMemory?.(result.hit.id, result.hit.item);
          } else if (options.onSelectGraph) {
            options.onSelectGraph(result.hit.node);
          }
        }
      }
      canvas.style.cursor = "grab";
      if (reduceMotion) draw(0);
    }

    function onPointerLeave() {
      hover = null;
      if (options.onHover) options.onHover(null);
      if (reduceMotion) draw(0);
    }

    function onWheel(event) {
      event.preventDefault();
      const point = eventPoint(event);
      const before = screenToWorld(point.x, point.y);
      const factor = Math.exp(-event.deltaY * 0.0012);
      view.scale = clamp(view.scale * factor, 0.78, 2.4);
      view.panX = (point.x - width / 2) - (before.x - width / 2) * view.scale;
      view.panY = (point.y - height / 2) - (before.y - height / 2) * view.scale;
      if (reduceMotion) draw(0);
    }

    function resetView() {
      view.scale = 1;
      view.panX = 0;
      view.panY = 0;
      if (reduceMotion) draw(0);
    }

    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointerleave", onPointerLeave);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("dblclick", resetView);

    return {
      render(nextModel) {
        model = nextModel;
        resize();
        draw(0);
        start();
      },
      setSelected(id) {
        selectedId = id === undefined || id === null ? null : Number(id);
        if (reduceMotion) draw(0);
      },
      setHighlight(next) {
        highlight = normalizeHighlight(next);
        if (reduceMotion) draw(0);
      },
      getHighlight() {
        return { memoryIds: [...highlight.memoryIds], relationKey: highlight.relationKey };
      },
      resize() {
        resize();
        if (reduceMotion) draw(0);
      },
      resetView,
      getSize() {
        return { width, height };
      },
      destroy() {
        stop();
        canvas.removeEventListener("pointermove", onPointerMove);
        canvas.removeEventListener("pointerdown", onPointerDown);
        canvas.removeEventListener("pointerup", onPointerUp);
        canvas.removeEventListener("pointerleave", onPointerLeave);
        canvas.removeEventListener("wheel", onWheel);
        canvas.removeEventListener("dblclick", resetView);
        if (options.onHover) options.onHover(null);
      },
    };
  }

  return {
    buildModel,
    layoutGraph,
    hitTest,
    hexPoints,
    typeColor,
    formatType,
    normalizeHighlight,
    relationMatchesHighlight,
    memoryIsHighlighted,
    createRenderer,
  };
});
