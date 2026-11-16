/* 牧鱼 · 记忆页（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerMemory = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const TABS = [
    { id: "library", label: "记忆库" },
    { id: "working", label: "工作记忆" },
    { id: "relations", label: "关系与情绪" },
    { id: "brain", label: "脑图" },
    { id: "sleep", label: "睡眠与梦境" },
    { id: "recall", label: "召回与主动回忆" },
    { id: "vector", label: "向量模型" },
    { id: "health", label: "记忆健康" },
  ];

  const LEGACY_TABS = { graph: "brain", audit: "health" };

  const TYPES = ["all", "GENERAL", "FACTUAL", "PREFERENCE", "RELATIONAL", "PLANNED", "EPISODIC", "UNKNOWN"];

  function fmtScore(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return `${(n * 100).toFixed(1)}%`;
  }

  function fmtArousal(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2) : "—";
  }

  function fmtSalience(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2) : "—";
  }

  function importanceLabel(value) {
    const n = Number(value);
    return Number.isFinite(n) ? `${Math.round(n * 100)}%` : "—";
  }

  function shortId(value) {
    return `#${String(value)}`;
  }

  function buildMemoryQuery(query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query || {})) {
      if (value === undefined || value === null || value === "") continue;
      params.set(key, String(value));
    }
    return params.toString();
  }

  function memoryTypeLabel(value) {
    return value ? String(value) : "未分类";
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

  function isBotIdentity(value) {
    if (typeof value === "boolean") return value;
    return ["1", "true", "yes", "on"].includes(String(value || "").trim().toLowerCase());
  }

  function identityEntries(item) {
    const identities = metadataOf(item).participant_identities;
    if (!Array.isArray(identities)) return [];
    const seen = new Set();
    const out = [];
    for (const raw of identities) {
      if (!raw || typeof raw !== "object" || isBotIdentity(raw.is_bot)) continue;
      const platform = String(raw.platform || "").trim().toLowerCase();
      const senderId = String(raw.sender_id || "").trim();
      const identityKey = String(raw.identity_key || "").trim() ||
        (platform && senderId ? `${platform}:${senderId}` : "");
      const displayName = String(raw.display_name || senderId || identityKey || "").trim();
      if (!identityKey && !displayName) continue;
      const key = identityKey || displayName;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ identityKey, platform, senderId, displayName });
    }
    return out;
  }

  function identityLabels(item) {
    return identityEntries(item)
      .map((entry) => entry.displayName)
      .filter((name) => Boolean(name));
  }

  function personKeys(item) {
    return identityEntries(item).map((entry) => entry.identityKey || entry.displayName);
  }

  function memoryPassesFilters(item, filters) {
    const state = filters || {};
    const meta = metadataOf(item);
    const itemType = String(meta.memory_type || item.memory_type || "GENERAL").toUpperCase();
    if (state.type && state.type !== "all" && itemType !== String(state.type).toUpperCase()) {
      return false;
    }
    const status = String(meta.status || "active");
    if (state.status && state.status !== "all" && status !== state.status) return false;
    const minImportance = Number(state.min_importance);
    if (state.min_importance !== "" && state.min_importance !== undefined && Number.isFinite(minImportance) && minImportance > 0) {
      const importance = Number(meta.importance);
      if (!Number.isFinite(importance) || importance < minImportance) return false;
    }
    const minArousal = Number(state.min_arousal);
    if (state.min_arousal !== "" && state.min_arousal !== undefined && Number.isFinite(minArousal) && minArousal > 0) {
      const arousal = Number(meta.arousal);
      if (!Number.isFinite(arousal) || arousal < minArousal) return false;
    }
    const person = String(state.person || "").trim();
    if (person) {
      const entries = identityEntries(item);
      const matched = entries.some((entry) =>
        entry.identityKey === person ||
        entry.senderId === person ||
        entry.displayName === person
      );
      if (!matched) return false;
    }
    return true;
  }

  function filterMemoryItems(items, filters) {
    return (Array.isArray(items) ? items : []).filter((item) =>
      memoryPassesFilters(item, filters)
    );
  }

  function buildExportQuery(filters) {
    const state = filters || {};
    const params = new URLSearchParams();
    const keyword = String(state.keyword || state.q || "").trim();
    if (keyword) params.set("q", keyword);
    const type = String(state.type || "").trim();
    if (type && type !== "all") params.set("type", type);
    params.set("status", String(state.status || "all").trim() || "all");
    return params.toString();
  }

  function formatDays(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return `${n.toFixed(1)} 天`;
  }

  function formatPercent01(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return `${Math.round(n * 100)}%`;
  }

  function validateSleepTime(value) {
    return /^([01]\d|2[0-3]):[0-5]\d$/.test(String(value || ""));
  }

  function summarizeReport(report) {
    if (!report) return "暂无报告";
    const c = report.consolidation || {};
    const clean = report.cleanup || {};
    return `${report.trigger || "—"} · 整合 ${c.merged || 0} 组 · 归档 ${clean.archived || 0} 条`;
  }

  function scoreRows(input) {
    const entries = Array.isArray(input)
      ? input
      : Object.entries(input || {}).map(([key, value]) => ({ key, value }));
    return entries
      .map((row) => ({
        key: String(row.key || ""),
        value: Number(row.value) || 0,
        percent: Math.round(Math.max(0, Math.min(100, (Number(row.value) || 0) * 100)) * 100) / 100,
      }))
      .filter((row) => row.key);
  }

  function serializeHumanConfig(nested) {
    const out = {};
    function walk(prefix, value) {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        for (const [key, child] of Object.entries(value)) walk(`${prefix}.${key}`, child);
      } else {
        out[prefix] = value;
      }
    }
    walk("human_memory", nested || {});
    return out;
  }

  function formatConfigNumber(value, step = "0.01") {
    const n = Number(value);
    if (!Number.isFinite(n)) return "";
    const stepText = String(step || "");
    const decimals = stepText.includes(".") ? stepText.split(".")[1].length : 0;
    return String(Number(n.toFixed(decimals)));
  }

  function parseGroupAllowlist(value) {
    const items = Array.isArray(value)
      ? value
      : String(value || "").split(/[,;，；\r\n]+/);
    const seen = new Set();
    const out = [];
    for (const item of items) {
      const text = String(item ?? "").trim();
      if (!text || seen.has(text)) continue;
      seen.add(text);
      out.push(text);
    }
    return out;
  }

  function formatGroupAllowlist(value) {
    return Array.isArray(value) ? value.join("\n") : String(value ?? "");
  }

  function collectConfigValues(nodes) {
    const values = {};
    for (const node of Array.from(nodes || [])) {
      const path = node && node.dataset ? node.dataset.cfg : "";
      if (!path) continue;
      if (node.type === "checkbox") {
        values[path] = Boolean(node.checked);
      } else if (node.type === "number") {
        const n = Number(node.value);
        if (!Number.isFinite(n)) throw new Error(`${path} 不是数字`);
        values[path] = n;
      } else if (String(path).endsWith("group_allowlist")) {
        values[path] = parseGroupAllowlist(node.value).join("\n");
      } else {
        values[path] = String(node.value ?? "");
      }
    }
    return values;
  }

  function estimateSalience(importanceRaw, arousal, importanceWeight = 0.7, emotionWeight = 0.3) {
    const clamp = (value, fallback) => {
      const n = Number(value);
      return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : fallback;
    };
    const raw = clamp(importanceRaw, 0);
    const level = clamp(arousal, 0);
    const w = clamp(importanceWeight, 0.7);
    const e = clamp(emotionWeight, 0.3);
    const value = Math.max(0, Math.min(1, w * raw + e * level));
    return Math.round(value * 10000) / 10000;
  }

  function promptMissingScopes(status) {
    if (!status || typeof status !== "object") return [];
    const scopes = ["private", "group"];
    const detailed = status.prompt_status;
    if (detailed && typeof detailed === "object") {
      return scopes.filter((scope) => {
        const item = detailed[scope];
        return Boolean(item) && (!item.has_arousal || !item.has_salience_reason);
      });
    }
    const legacy = status.prompt_has_arousal;
    if (legacy && typeof legacy === "object") {
      return scopes.filter((scope) => legacy[scope] === false);
    }
    return [];
  }

  function scoreDisplay(key, value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    const name = String(key || "");
    if (name.includes("days") || name.includes("day_old")) return `${n.toFixed(2)} 天`;
    if (name.includes("count")) return String(n);
    if (n >= 0 && n <= 1) return fmtScore(n);
    return n.toFixed(3);
  }

  function formatBytes(value) {
    let n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i += 1;
    }
    return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
  }

  function formatTime(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return "—";
    return new Date(n * 1000).toLocaleString();
  }

  function truncate(text, length = 90) {
    const value = String(text || "").replace(/\s+/g, " ").trim();
    return value.length > length ? `${value.slice(0, length - 1)}…` : value;
  }

  function distributionRows(value) {
    if (!value || typeof value !== "object") return [];
    return Object.entries(value)
      .filter(([, count]) => Number(count) > 0)
      .map(([key, count]) => ({ key, count: Number(count) }))
      .sort((a, b) => b.count - a.count);
  }

  function formatDurationMs(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) return "—";
    if (n < 1000) return `${Math.round(n)} ms`;
    if (n < 60000) return `${(n / 1000).toFixed(1)} 秒`;
    return `${(n / 60000).toFixed(1)} 分钟`;
  }

  function dreamState(dream) {
    if (!dream || typeof dream !== "object") return "empty";
    if (dream.error) return "error";
    if (String(dream.text || "").trim()) return "text";
    if (dream.enabled === false) return "disabled";
    if (dream.skipped) return "skipped";
    return "empty";
  }

  function dreamNarrative(dream) {
    if (!dream || typeof dream !== "object" || dream.error) return "";
    return String(dream.text || "").trim();
  }

  function dreamMemoryIds(dream) {
    if (!dream || typeof dream !== "object") return [];
    const raw = Array.isArray(dream.memory_ids) ? dream.memory_ids : [];
    return raw
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value > 0);
  }

  function replayTimelineRows(report, candidates) {
    const summary =
      report && report.summary && typeof report.summary === "object"
        ? report.summary
        : report && typeof report === "object"
          ? report
          : {};
    const dream = summary.dream && typeof summary.dream === "object" ? summary.dream : {};
    const ids = dreamMemoryIds(dream);
    const byId = new Map();
    for (const item of Array.isArray(candidates) ? candidates : []) {
      const id = Number(item && item.id);
      if (Number.isFinite(id) && id > 0) byId.set(id, item);
    }
    const time = dream.created_at || summary.finished_at || summary.started_at || null;
    return ids.map((id) => {
      const candidate = byId.get(id) || {};
      const importance = Number(candidate.importance);
      const salience = Number(candidate.salience);
      return {
        memory_id: id,
        time,
        summary: String(candidate.content || candidate.summary || "").trim(),
        importance: Number.isFinite(importance) ? importance : null,
        salience: Number.isFinite(salience) ? salience : null,
      };
    });
  }

  function activeRecallMode(status) {
    if (!status || typeof status !== "object" || !status.enabled) return "off";
    return status.shadow ? "shadow" : "real";
  }

  function activeRecallModeLabel(status) {
    const mode = activeRecallMode(status);
    if (mode === "real") return "真实";
    if (mode === "shadow") return "影子";
    return "关闭";
  }

  function activeRecallBlockedLabel(reason) {
    const labels = {
      disabled: "主动回忆已关闭",
      group_disabled: "群聊未开启主动回忆",
      private_disabled: "私聊未开启主动回忆",
      no_candidates: "没有达到阈值的候选",
      daily_limit: "达到今日真实注入上限",
      cooldown: "处于冷却期",
    };
    const key = String(reason || "").trim();
    if (!key) return "";
    return labels[key] || key;
  }

  function create(ctx) {
    const { esc, icon, api, toast, openModal, closeModal, confirmDialog } = ctx;
    let root = null;
    let activeId = null;
    let activeTab = "library";
    let statusData = null;
    let statusError = "";
    let libState = {
      keyword: "",
      session_id: "",
      status: "all",
      type: "",
      sort: "created_desc",
      page: 1,
      page_size: 20,
      min_importance: "",
      min_arousal: "",
      person: "",
      person_label: "",
    };
    let libData = null;
    let libBusy = false;
    let libBatchBusy = false;
    let libSelected = new Set();
    let sleepPreview = null;
    let sleepReports = [];
    let helperConfig = null;
    let helperConfigError = "";
    let backfillPreview = null;
    let recallData = null;
    let recallBusy = false;
    let vectorStatus = null;
    let vectorError = "";
    let vectorBusy = false;
    let vectorLive = true;
    let vectorConfigLoaded = false;
    let vectorTimer = null;
    let vectorFindData = null;
    let vectorFindBusy = false;
    let activeStatus = null;
    let activeStatusError = "";
    let activeEvents = [];
    let activeEventsError = "";
    let activeEventsBusy = false;
    let activeEventFilter = "all";
    let activePreviewData = null;
    let activePreviewBusy = false;
    let reviewBusyId = null;
    let workingSessions = null;
    let workingSessionId = "";
    let workingDetail = null;
    let workingError = "";
    let workingBusy = false;
    let relationsData = null;
    let relationsError = "";
    let relationsBusy = false;
    let relationSelectedKey = "";
    let emotionData = null;
    let emotionError = "";
    let emotionBusy = false;
    let healthAudit = null;
    let healthForgetting = null;
    let healthError = "";
    let healthWarning = "";
    let healthBusy = false;
    let healthStatus = "active";
    let brainHighlight = { memoryIds: [], relationKey: "" };
    let brainRaw = null;
    let brainModel = null;
    let brainRenderer = null;
    let brainResizeObserver = null;
    let brainResizeTimer = null;
    let brainSelectedId = null;
    let brainFilters = {
      session_id: "",
      persona_id: "",
      status: "active",
      type: "",
    };
    const timers = new Set();

    function rememberTimer(id) {
      timers.add(id);
      return id;
    }

    function clearTimers() {
      for (const id of timers) clearInterval(id);
      timers.clear();
    }

    function instance() {
      const instances = ctx.state.instances || [];
      return instances.find((item) => item.id === activeId) || null;
    }

    function running(inst) {
      return Boolean(inst && inst.status && inst.status.running);
    }

    function path(inst, suffix) {
      return `/api/instances/${encodeURIComponent(inst.id)}/memory${suffix}`;
    }

    async function request(inst, suffix, options) {
      return api(path(inst, suffix), options);
    }

    function leave() {
      clearTimers();
      destroyBrain();
      brainRaw = null;
      brainSelectedId = null;
      brainHighlight = { memoryIds: [], relationKey: "" };
      root = null;
    }

    function destroyBrainRenderer() {
      if (brainRenderer) {
        brainRenderer.destroy();
        brainRenderer = null;
      }
    }

    function destroyBrain() {
      if (brainResizeTimer) {
        clearTimeout(brainResizeTimer);
        brainResizeTimer = null;
      }
      if (brainResizeObserver) {
        brainResizeObserver.disconnect();
        brainResizeObserver = null;
      }
      destroyBrainRenderer();
      brainModel = null;
    }

    function viewMemory(view) {
      root = view;
      const instances = ctx.state.instances || [];
      if (!instances.length) {
        root.innerHTML = `<div class="empty">${icon("alert")}<h4>还没有机器人</h4><p>先在“机器人”页添加 AstrBot 实例。</p></div>`;
        return;
      }
      const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(instances);
      if (focusHit) {
        activeId = String(focusHit.id);
      } else if (!activeId || !instances.some((item) => item.id === activeId)) {
        activeId = ((globalThis.ManagerFocus && globalThis.ManagerFocus.pick(instances)) || instances.find(running) || instances[0]).id;
      }
      const queryTab = new URLSearchParams(location.search).get("tab");
      const mappedTab = LEGACY_TABS[queryTab] || queryTab;
      if (mappedTab && TABS.some((tab) => tab.id === mappedTab)) {
        activeTab = mappedTab;
      }
      root.innerHTML = `
        <div class="console-instance-chips">${instances.map((item) =>
          `<button class="chip ${item.id === activeId ? "active" : ""}" data-mem-inst="${esc(item.id)}">${esc(item.name)}${running(item) ? "" : "（未运行）"}</button>`
        ).join("")}</div>
        <div class="memory-head">
          <div>
            <div class="console-kicker">LivingMemory · 类人长期记忆</div>
            <h2>记忆</h2>
            <p>记忆库、工作记忆、关系与情绪、脑图、睡眠与梦境、召回与主动回忆、向量模型、记忆健康。</p>
          </div>
          <div class="console-actions">
            <button class="btn ghost" data-mem-config>${icon("edit")}原始配置</button>
            <button class="btn ghost icon-only" data-mem-refresh title="刷新">${icon("refresh")}</button>
          </div>
        </div>
        <div class="stat-grid memory-summary" id="mem-summary"></div>
        <div id="mem-warning"></div>
        <nav class="tabs memory-tabs">${TABS.map((tab) =>
          `<button class="tab ${tab.id === activeTab ? "active" : ""}" data-mem-tab="${tab.id}">${tab.label}</button>`
        ).join("")}</nav>
        <div class="memory-pane" id="mem-pane"><div class="skeleton" style="height:180px"></div></div>`;
      root.querySelectorAll("[data-mem-inst]").forEach((node) => {
        node.addEventListener("click", () => {
          if (node.dataset.memInst === activeId) return;
          activeId = node.dataset.memInst;
          statusData = null;
          statusError = "";
          libData = null;
          sleepPreview = null;
          sleepReports = [];
          helperConfig = null;
          backfillPreview = null;
          recallData = null;
          vectorStatus = null;
          vectorError = "";
          vectorBusy = false;
          vectorConfigLoaded = false;
          vectorTimer = null;
          vectorFindData = null;
          vectorFindBusy = false;
          activeStatus = null;
          activeStatusError = "";
          activeEvents = [];
          activeEventsError = "";
          activeEventsBusy = false;
          activeEventFilter = "all";
          activePreviewData = null;
          activePreviewBusy = false;
          reviewBusyId = null;
          workingSessions = null;
          workingSessionId = "";
          workingDetail = null;
          workingError = "";
          workingBusy = false;
          relationsData = null;
          relationsError = "";
          relationsBusy = false;
          relationSelectedKey = "";
          emotionData = null;
          emotionError = "";
          emotionBusy = false;
          healthAudit = null;
          healthForgetting = null;
          healthError = "";
          healthWarning = "";
          healthBusy = false;
          healthStatus = "active";
          brainHighlight = { memoryIds: [], relationKey: "" };
          libState = {
            keyword: "",
            session_id: "",
            status: "all",
            type: "",
            sort: "created_desc",
            page: 1,
            page_size: 20,
            min_importance: "",
            min_arousal: "",
            person: "",
            person_label: "",
          };
          libSelected = new Set();
          brainRaw = null;
          brainSelectedId = null;
          clearTimers();
          viewMemory(root);
        });
      });
      root.querySelectorAll("[data-mem-tab]").forEach((node) => {
        node.addEventListener("click", () => {
          activeTab = node.dataset.memTab;
          clearTimers();
          syncTabButtons();
          renderTab();
        });
      });
      const refresh = root.querySelector("[data-mem-refresh]");
      if (refresh) refresh.addEventListener("click", () => loadStatus());
      const raw = root.querySelector("[data-mem-config]");
      if (raw) raw.addEventListener("click", () => {
        const inst = instance();
        if (!inst) return;
        if (ctx.pluginConfigModal) {
          ctx.pluginConfigModal(inst, "astrbot_plugin_livingmemory", "LivingMemory", () => loadStatus());
        } else {
          toast("当前管理器不支持插件配置弹窗", "warn");
        }
      });
      loadStatus();
    }

    async function loadStatus() {
      const inst = instance();
      if (!inst) return;
      try {
        statusData = await request(inst, "/status");
        statusError = "";
      } catch (err) {
        statusData = null;
        statusError = err.message;
      }
      renderSummary();
      renderWarning();
      renderTab();
    }

    function renderSummary() {
      const box = root && root.querySelector("#mem-summary");
      if (!box) return;
      const stats = statusData && statusData.stats ? statusData.stats : {};
      const sleep = statusData && statusData.sleep ? statusData.sleep : {};
      const recon = statusData && statusData.reconsolidation ? statusData.reconsolidation : {};
      const statusBreakdown = stats.status_breakdown || {};
      const active = statusBreakdown.active ?? stats.active_memories ?? "—";
      const archived = statusBreakdown.archived ?? stats.archived_memories ?? "—";
      box.innerHTML = [
        statCard("记忆总数", stats.total_memories ?? "—", `Active ${active} · 已归档 ${archived}`),
        statCard("记忆原子", stats.atom_count ?? "—", `图谱 ${stats.graph_nodes ?? "—"} 节点 / ${stats.graph_edges ?? "—"} 边`),
        statCard("平均重要性", importanceLabel(stats.avg_importance), "0–1 重要性"),
        statCard("自动睡眠", sleep.enabled ? (sleep.running ? "运行中" : "已启用") : "未启用", sleep.last_run_date ? `上次 ${sleep.last_run_date}` : "首次运行前请先预览"),
        statCard("今日再巩固", recon.count ?? 0, `改写 ${recon.updated ?? 0} · 跳过 ${recon.skipped ?? 0}`),
      ].join("");
    }

    function statCard(label, value, hint) {
      return `<div class="stat"><div class="k">${esc(label)}</div><div class="v">${esc(String(value))}</div><div class="hint">${esc(hint || "")}</div></div>`;
    }

    function renderWarning() {
      const box = root && root.querySelector("#mem-warning");
      if (!box) return;
      const inst = instance();
      if (!inst) {
        box.innerHTML = "";
        return;
      }
      const warnings = [];
      if (!running(inst)) warnings.push("该机器人未运行，记忆接口可能不可达。");
      if (statusError) warnings.push(`记忆接口读取失败：${statusError}`);
      const missingScopes = promptMissingScopes(statusData);
      const scopeLabels = { private: "私聊", group: "群聊" };
      if (missingScopes.length) {
        warnings.push(
          `提示词缺少 arousal/salience_reason 字段（${missingScopes.map((scope) => scopeLabels[scope]).join("、")}），新记忆不会获得完整显著性。`
        );
      }
      if (!warnings.length) {
        box.innerHTML = "";
        return;
      }
      const promptActions = missingScopes.length
        ? `<div class="console-actions memory-actions" style="margin-top:8px">
            ${missingScopes.map((scope) =>
              `<button class="btn sm ghost" data-prompt-preview="${scope}">${icon("search")}预览补齐（${scopeLabels[scope]}）</button>`
            ).join("")}
            ${missingScopes.map((scope) =>
              `<button class="btn sm primary" data-prompt-merge="${scope}">确认合并（${scopeLabels[scope]}）</button>`
            ).join("")}
          </div>`
        : "";
      box.innerHTML = `<div class="console-warn">${warnings
        .map((text) => `<div>${esc(text)}</div>`)
        .join("")}${promptActions}</div>`;
      box.querySelectorAll("[data-prompt-preview]").forEach((node) => {
        node.addEventListener("click", () => previewPrompt(node.dataset.promptPreview));
      });
      box.querySelectorAll("[data-prompt-merge]").forEach((node) => {
        node.addEventListener("click", () => mergePrompt(node.dataset.promptMerge));
      });
    }

    async function previewPrompt(scope) {
      const inst = instance();
      if (!inst) return;
      const label = scope === "group" ? "群聊" : "私聊";
      try {
        const data = await request(inst, `/prompt/preview?scope=${encodeURIComponent(scope)}`);
        const fields = [
          ["是否自定义", data.custom ? "是" : "否"],
          ["已有 arousal", data.has_arousal ? "是" : "否"],
          ["已有 salience_reason", data.has_salience_reason ? "是" : "否"],
          ["内置提示词完整", data.builtin_complete ? "是" : "否"],
          ["当前长度", String(data.current_length ?? "—")],
          ["备份路径", data.backup_path || "—"],
        ];
        openModal({
          title: `提示词补齐预览（${label}）`,
          sub: data.message || "预览不会写入任何内容",
          wide: true,
          body: `<div class="memory-detail">
            <div class="memory-detail-grid">
              ${fields.map(([key, value]) => detailRow(key, value)).join("")}
            </div>
            <section class="memory-subcard"><h4>建议追加字段</h4>
              <pre class="memory-pre">${esc(data.append_block || "（无需追加）")}</pre>
            </section>
            <section class="memory-subcard"><h4>合并后预览</h4>
              <pre class="memory-pre">${esc(data.preview || data.current_prompt || "（空）")}</pre>
            </section>
            <div class="console-help">合并会先备份当前提示词，只追加缺失字段；不会覆盖已有内容。合并完成后需要手动重载插件才会生效。</div>
          </div>`,
          footer: `<button class="btn ghost" data-close>关闭</button>
            <button class="btn primary" data-prompt-merge-now ${data.needs_merge ? "" : "disabled"}>确认合并</button>`,
          onMount: (modal) => {
            const button = modal.querySelector("[data-prompt-merge-now]");
            if (button) button.addEventListener("click", () => {
              closeModal();
              mergePrompt(scope);
            });
          },
        });
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function mergePrompt(scope) {
      const inst = instance();
      if (!inst) return;
      const label = scope === "group" ? "群聊" : "私聊";
      const ok = await confirmDialog(
        "合并提示词",
        `会先备份当前${label}提示词，再只追加缺失的 arousal/salience_reason 说明，不覆盖已有内容。合并完成后需要手动重载插件才会生效。确定继续？`,
        false
      );
      if (!ok) return;
      try {
        const result = await request(inst, "/prompt/merge", {
          method: "POST",
          body: { scope, confirm: "MERGE" },
        });
        if (result.merged) {
          toast(`已合并并备份：${result.backup_path || "—"}，请手动重载插件`);
        } else {
          toast(result.message || "提示词无需合并", "warn");
        }
        await loadStatus();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function syncTabButtons() {
      if (!root) return;
      root.querySelectorAll("[data-mem-tab]").forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.memTab === activeTab);
      });
    }

    function renderTab() {
      if (!root) return;
      const pane = root.querySelector("#mem-pane");
      if (!pane) return;
      destroyBrain();
      if (statusError) {
        pane.innerHTML = `<div class="empty">${icon("alert")}<h4>无法读取记忆</h4><p>${esc(statusError)}</p><button class="btn ghost" data-mem-retry>重试</button></div>`;
        const retry = pane.querySelector("[data-mem-retry]");
        if (retry) retry.addEventListener("click", () => loadStatus());
        return;
      }
      if (activeTab === "library") renderLibrary(pane);
      else if (activeTab === "working") renderWorking(pane);
      else if (activeTab === "relations") renderRelations(pane);
      else if (activeTab === "brain") renderBrain(pane);
      else if (activeTab === "sleep") renderSleep(pane);
      else if (activeTab === "recall") renderRecall(pane);
      else if (activeTab === "vector") renderVector(pane);
      else if (activeTab === "health") renderHealth(pane);
      else renderLibrary(pane);
    }

    /* ------------------------------------------------------------ library */

    function renderLibrary(pane) {
      const personChip = libState.person
        ? `<div class="memory-person-filter"><span>人物：${esc(libState.person_label || libState.person)}</span><code>${esc(libState.person)}</code><button class="btn sm ghost" data-lib-person-clear>清除人物</button></div>`
        : "";
      pane.innerHTML = `
        <section class="card memory-filter-card">
          <div class="memory-filters">
            <label>关键词<input data-lib="keyword" value="${esc(libState.keyword)}" placeholder="摘要、ID、主题"></label>
            <label>状态<select data-lib="status">${["all", "active", "archived"].map((v) =>
              `<option value="${v}"${libState.status === v ? " selected" : ""}>${v === "all" ? "全部" : v === "active" ? "活跃" : "已归档"}</option>`
            ).join("")}</select></label>
            <label>类型<select data-lib="type">${TYPES.map((v) =>
              `<option value="${v === "all" ? "" : v}"${libState.type === (v === "all" ? "" : v) ? " selected" : ""}>${v === "all" ? "全部" : v}</option>`
            ).join("")}</select></label>
            <label>排序<select data-lib="sort">${[
              ["created_desc", "最新创建"],
              ["created_asc", "最早创建"],
              ["updated_desc", "最近更新"],
              ["importance_desc", "重要性"],
            ].map(([v, label]) =>
              `<option value="${v}"${libState.sort === v ? " selected" : ""}>${label}</option>`
            ).join("")}</select></label>
            <label>会话<input data-lib="session_id" value="${esc(libState.session_id)}" placeholder="可选"></label>
            <label>最低重要性<input data-lib="min_importance" type="number" min="0" max="1" step="0.05" value="${esc(libState.min_importance)}" placeholder="≥0.00"></label>
            <label>最低唤醒<input data-lib="min_arousal" type="number" min="0" max="1" step="0.05" value="${esc(libState.min_arousal)}" placeholder="≥0.00"></label>
            <button class="btn primary" data-lib-search>${icon("search")}查询</button>
            <button class="btn ghost" data-lib-export>${icon("download")}导出 JSON</button>
          </div>
          ${personChip}
          <div class="console-help">默认只读；内容编辑会重建索引并生成新 ID。归档不删除原文。重要性/唤醒筛选作用于当前加载页；导出按关键词、类型、状态导出全部匹配结果。</div>
        </section>
        <section class="card memory-list-card">
          <div class="memory-batch-bar">
            <span>已选 <b data-lib-selected-count>0</b> 条</span>
            <button class="btn sm ghost" data-lib-batch-archive>批量归档</button>
            <button class="btn sm ghost" data-lib-batch-restore>批量恢复</button>
            <button class="btn sm ghost" data-lib-select-clear disabled>清空选择</button>
            <span class="side" data-lib-filter-note></span>
          </div>
          <div id="mem-list"><div class="skeleton" style="height:140px"></div></div>
          <div class="memory-pager" id="mem-pager"></div>
        </section>`;
      pane.querySelectorAll("[data-lib]").forEach((node) => {
        const key = node.dataset.lib;
        const handler = () => {
          libState[key] = node.value;
          libState.page = 1;
        };
        if (node.tagName === "SELECT") node.addEventListener("change", handler);
        else node.addEventListener("input", handler);
      });
      pane.querySelector("[data-lib-search]").addEventListener("click", () => loadLibrary());
      pane.querySelector("[data-lib-export]").addEventListener("click", () => exportMemories());
      pane.querySelector("[data-lib-batch-archive]").addEventListener("click", () => batchUpdateStatus("archived"));
      pane.querySelector("[data-lib-batch-restore]").addEventListener("click", () => batchUpdateStatus("active"));
      pane.querySelector("[data-lib-select-clear]").addEventListener("click", () => {
        libSelected.clear();
        renderLibraryRows();
      });
      const personClear = pane.querySelector("[data-lib-person-clear]");
      if (personClear) personClear.addEventListener("click", () => {
        libState.person = "";
        libState.person_label = "";
        libState.page = 1;
        renderLibrary(pane);
      });
      pane.querySelectorAll("[data-lib]").forEach((node) => {
        if (node.tagName === "INPUT") node.addEventListener("keydown", (event) => {
          if (event.key === "Enter") loadLibrary();
        });
      });
      loadLibrary();
    }

    async function exportMemories() {
      const inst = instance();
      if (!inst) return;
      const query = buildExportQuery(libState);
      try {
        const data = await request(inst, `/export?${query}`);
        const filename = data && data.filename ? data.filename : "memory-export.json";
        const text = JSON.stringify(data || {}, null, 2);
        if (
          typeof document !== "undefined" &&
          typeof Blob !== "undefined" &&
          typeof URL !== "undefined" &&
          URL.createObjectURL
        ) {
          const url = URL.createObjectURL(new Blob([text], { type: "application/json;charset=utf-8" }));
          const link = document.createElement("a");
          link.href = url;
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
          toast(`已导出 ${Number(data && data.count) || 0} 条记忆`);
        } else if (typeof window !== "undefined" && window.open) {
          window.open(path(inst, `/export?${query}`), "_blank", "noopener");
        }
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function batchUpdateStatus(target) {
      const inst = instance();
      if (!inst || libBatchBusy) return;
      const ids = Array.from(libSelected)
        .map((id) => Number(id))
        .filter((id) => Number.isFinite(id));
      if (!ids.length) return toast("先勾选要处理的记忆", "warn");
      const action = target === "archived" ? "归档" : "恢复";
      const ok = await confirmDialog(
        `批量${action}记忆`,
        `将对已选 ${ids.length} 条记忆执行${action}。会逐条调用现有单条更新接口，失败会跳过；归档不删除原文，可随时恢复。确定继续？`,
        false
      );
      if (!ok) return;
      libBatchBusy = true;
      updateBatchBar();
      let done = 0;
      let failed = 0;
      for (const id of ids) {
        if (!root) break;
        try {
          await request(inst, `/items/${encodeURIComponent(id)}/update`, {
            method: "POST",
            body: { field: "status", value: target, reason: "管理器批量操作" },
          });
          done += 1;
        } catch (_) {
          failed += 1;
        }
      }
      libBatchBusy = false;
      libSelected.clear();
      if (failed) toast(`批量${action}完成：成功 ${done} 条，失败 ${failed} 条`, "warn");
      else toast(`已${action} ${done} 条记忆`);
      await loadStatus();
    }

    async function loadLibrary() {
      const inst = instance();
      if (!inst || libBusy) return;
      libBusy = true;
      libSelected.clear();
      const list = root && root.querySelector("#mem-list");
      if (list) list.innerHTML = `<div class="skeleton" style="height:140px"></div>`;
      try {
        const query = buildMemoryQuery({
          keyword: libState.keyword,
          session_id: libState.session_id,
          status: libState.status,
          type: libState.type,
          sort: libState.sort,
          page: libState.page,
          page_size: libState.page_size,
        });
        libData = await request(inst, `/items?${query}`);
        renderLibraryRows();
      } catch (err) {
        if (list) list.innerHTML = `<div class="empty">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
      } finally {
        libBusy = false;
      }
    }

    function updateBatchBar() {
      const count = root && root.querySelector("[data-lib-selected-count]");
      if (count) count.textContent = String(libSelected.size);
      const clear = root && root.querySelector("[data-lib-select-clear]");
      if (clear) clear.disabled = libBatchBusy || !libSelected.size;
      const archive = root && root.querySelector("[data-lib-batch-archive]");
      if (archive) archive.disabled = libBatchBusy || !libSelected.size;
      const restore = root && root.querySelector("[data-lib-batch-restore]");
      if (restore) restore.disabled = libBatchBusy || !libSelected.size;
    }

    function renderLibraryRows() {
      const list = root && root.querySelector("#mem-list");
      const pager = root && root.querySelector("#mem-pager");
      if (!list || !pager) return;
      const allItems = (libData && libData.items) || [];
      const items = filterMemoryItems(allItems, libState);
      const note = root && root.querySelector("[data-lib-filter-note]");
      if (note) {
        note.textContent = items.length === allItems.length
          ? ""
          : `当前页筛选后 ${items.length} / ${allItems.length} 条`;
      }
      updateBatchBar();
      if (!items.length) {
        list.innerHTML = allItems.length
          ? `<div class="empty">${icon("search")}<h4>当前页没有符合筛选的记忆</h4><p>放宽重要性/唤醒/人物筛选，或翻页后重试。</p></div>`
          : `<div class="empty">${icon("search")}<h4>没有匹配的记忆</h4><p>换关键词或放宽筛选。</p></div>`;
        pager.innerHTML = "";
        return;
      }
      const allSelected = items.every((item) => libSelected.has(String(item.id)));
      list.innerHTML = `<div class="memory-table-wrap"><table class="table memory-table">
        <thead><tr>
          <th class="memory-select"><input type="checkbox" data-lib-select-all ${allSelected ? "checked" : ""} aria-label="全选当前页"></th>
          <th>ID</th><th>摘要</th><th class="col-person">人物</th><th class="col-type">类型</th><th>重要性</th><th>唤醒 / 显著</th><th class="col-status">状态</th><th class="col-updated">更新时间</th>
        </tr></thead>
        <tbody>${items.map((item) => {
          const meta = metadataOf(item);
          const labels = identityLabels(item);
          return `<tr data-memory-id="${esc(item.id)}" class="${libSelected.has(String(item.id)) ? "selected" : ""}">
            <td class="memory-select"><input type="checkbox" data-lib-select="${esc(item.id)}" ${libSelected.has(String(item.id)) ? "checked" : ""} aria-label="选择记忆 ${esc(item.id)}"></td>
            <td class="mono">${esc(shortId(item.id))}</td>
            <td><div class="cell-title"><span>${esc(truncate(item.text || meta.persona_summary || meta.canonical_summary || "—", 96))}</span></div></td>
            <td class="col-person">${labels.length ? labels.map((name) => `<span class="memory-person-tag">${esc(name)}</span>`).join("") : "—"}</td>
            <td class="col-type">${esc(memoryTypeLabel(meta.memory_type || item.memory_type))}</td>
            <td class="mono">${esc(importanceLabel(meta.importance))}</td>
            <td class="mono">${esc(fmtArousal(meta.arousal))} / ${esc(fmtSalience(meta.salience))}</td>
            <td class="col-status"><span class="memory-status ${esc(meta.status || "active")}">${esc(meta.status === "archived" ? "已归档" : "活跃")}</span></td>
            <td class="col-updated mono">${esc(formatTime(item.updated_at || item.created_at))}</td>
          </tr>`;
        }).join("")}</tbody></table></div>`;
      list.querySelectorAll("[data-memory-id]").forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest("input")) return;
          openDetail(row.dataset.memoryId);
        });
      });
      list.querySelectorAll("[data-lib-select]").forEach((node) => {
        node.addEventListener("click", (event) => event.stopPropagation());
        node.addEventListener("change", () => {
          const id = String(node.dataset.libSelect);
          if (node.checked) libSelected.add(id);
          else libSelected.delete(id);
          const row = node.closest("[data-memory-id]");
          if (row) row.classList.toggle("selected", node.checked);
          updateBatchBar();
        });
      });
      const selectAll = list.querySelector("[data-lib-select-all]");
      if (selectAll) selectAll.addEventListener("change", () => {
        for (const item of items) {
          const id = String(item.id);
          if (selectAll.checked) libSelected.add(id);
          else libSelected.delete(id);
        }
        renderLibraryRows();
      });
      const total = Number(libData.total || 0);
      const page = Number(libData.page || libState.page || 1);
      const size = Number(libData.page_size || libState.page_size || 20);
      const pages = Math.max(1, Math.ceil(total / size));
      pager.innerHTML = `<span>共 ${total} 条 · 第 ${page} / ${pages} 页</span>
        <div><button class="btn sm ghost" data-page-prev ${page <= 1 ? "disabled" : ""}>上一页</button>
        <button class="btn sm ghost" data-page-next ${page >= pages ? "disabled" : ""}>下一页</button></div>`;
      const prev = pager.querySelector("[data-page-prev]");
      const next = pager.querySelector("[data-page-next]");
      if (prev) prev.addEventListener("click", () => { libState.page = Math.max(1, page - 1); loadLibrary(); });
      if (next) next.addEventListener("click", () => { libState.page = Math.min(pages, page + 1); loadLibrary(); });
    }

    async function openDetail(memoryId) {
      const inst = instance();
      if (!inst) return;
      try {
        const detail = await request(inst, `/items/${encodeURIComponent(memoryId)}`);
        const meta = detail.metadata || {};
        const history = Array.isArray(detail.update_history) ? detail.update_history : [];
        const source = Array.isArray(detail.source_messages) ? detail.source_messages : [];
        const arousalRaw = Number(meta.arousal ?? detail.arousal);
        const arousalNow = Number.isFinite(arousalRaw) ? Math.max(0, Math.min(1, arousalRaw)) : 0.3;
        const salienceRaw = Number(meta.salience ?? detail.salience);
        const salienceNow = Number.isFinite(salienceRaw) ? salienceRaw : estimateSalience(meta.importance_raw ?? detail.importance, arousalNow);
        const importanceRaw = Number(meta.importance_raw ?? detail.importance);
        const archivedHint = (detail.status || meta.status) === "archived"
          ? "该记忆已归档：允许校正，但不会自动恢复。"
          : "";
        openModal({
          title: `记忆 ${shortId(detail.memory_id || memoryId)}`,
          sub: `${memoryTypeLabel(detail.memory_type)} · ${detail.status || "active"}`,
          wide: true,
          body: `<div class="memory-detail">
            <div class="memory-detail-grid">
              ${detailRow("摘要", detail.summary || detail.text || "—", true)}
              ${detailRow("重要性", `${importanceLabel(detail.importance)}（原始 ${importanceLabel(meta.importance_raw)}）`)}
              ${detailRow("唤醒度", fmtArousal(meta.arousal || detail.arousal))}
              ${detailRow("显著性", fmtSalience(meta.salience || detail.salience))}
              ${detailRow("显著原因", meta.salience_reason || "—")}
              ${detailRow("情感", meta.sentiment || "—")}
              ${detailRow("会话", detail.session_id || meta.session_id || "—")}
              ${detailRow("人格", detail.persona_id || meta.persona_id || "—")}
              ${detailRow("创建时间", formatTime(detail.create_time || detail.created_at))}
              ${detailRow("最近访问", formatTime(detail.last_access_time || meta.last_access_time))}
              ${detailRow("主题", Array.isArray(detail.topics) && detail.topics.length ? detail.topics.join("、") : "—")}
              ${detailRow("关键事实", Array.isArray(detail.key_facts) && detail.key_facts.length ? detail.key_facts.join("；") : "—")}
            </div>
            <section class="memory-subcard">
              <h4>唤醒度校正</h4>
              <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                <input type="range" min="0" max="1" step="0.01" value="${esc(String(arousalNow))}" data-arousal-range style="flex:1;min-width:160px">
                <input type="number" min="0" max="1" step="0.01" value="${esc(String(arousalNow))}" data-arousal-number style="width:88px">
              </div>
              <div class="memory-kv" style="margin-top:8px">
                <div><span>当前显著性</span><b>${esc(fmtSalience(salienceNow))}</b></div>
                <div><span>预计显著性</span><b data-arousal-preview>${esc(estimateSalience(importanceRaw, arousalNow).toFixed(2))}（保存后将重算）</b></div>
              </div>
              <div class="field" style="margin-top:8px"><label>原因（可选，≤120 字）</label><input type="text" maxlength="120" data-arousal-reason placeholder="例如：管理员校正，这段对话情绪更强"></div>
              <div class="console-help">只改 arousal、salience 和审计记录；不改正文、重要性或类型，不重建索引。${esc(archivedHint)}</div>
              <div class="console-actions memory-actions"><button class="btn primary" data-arousal-save>保存唤醒度</button></div>
            </section>
            ${history.length ? `<section class="memory-subcard"><h4>更新历史</h4>${history.slice(-8).map((item) =>
              `<div class="memory-history-row"><span>${esc(formatTime(item.timestamp))}</span><b>${esc(item.field || "—")}</b><span>${esc(item.description || "")}</span><em>${esc(item.reason || "")}</em></div>`
            ).join("")}</section>` : ""}
            ${source.length ? `<section class="memory-subcard"><h4>来源原文</h4><pre class="memory-pre">${esc(JSON.stringify(source.slice(0, 8), null, 2))}</pre></section>` : ""}
          </div>`,
          footer: `<button class="btn ghost" data-close>关闭</button>
            <button class="btn ghost" data-detail-edit-content>${icon("edit")}改内容</button>
            <button class="btn ghost" data-detail-edit-importance>${icon("edit")}改重要性</button>
            <button class="btn ghost" data-detail-recon>${icon("pulse")}用新信息校正</button>
            <button class="btn ghost" data-detail-resummarize>${icon("refresh")}重新总结</button>
            <button class="btn ghost" data-detail-archive>${detail.status === "archived" ? "恢复" : "归档"}</button>`,
          onMount: (modal) => {
            bindDetailActions(modal, detail);
          },
        });
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function detailRow(label, value, wide = false) {
      return `<div class="memory-detail-row ${wide ? "wide" : ""}"><span>${esc(label)}</span><div>${esc(String(value ?? "—"))}</div></div>`;
    }

    function bindDetailActions(modal, detail) {
      const inst = instance();
      if (!inst) return;
      const memoryId = detail.memory_id;
      const range = modal.querySelector("[data-arousal-range]");
      const number = modal.querySelector("[data-arousal-number]");
      const preview = modal.querySelector("[data-arousal-preview]");
      const reasonInput = modal.querySelector("[data-arousal-reason]");
      const saveArousal = modal.querySelector("[data-arousal-save]");
      if (range && number && saveArousal) {
        const meta = detail.metadata || {};
        const rawValue = Number(meta.arousal ?? detail.arousal);
        const original = Number.isFinite(rawValue) ? Math.max(0, Math.min(1, rawValue)) : 0.3;
        const importanceRaw = meta.importance_raw ?? detail.importance;
        const salienceRaw = Number(meta.salience ?? detail.salience);
        const salienceNow = Number.isFinite(salienceRaw)
          ? salienceRaw
          : estimateSalience(importanceRaw, original);
        const clampValue = (value) => {
          const n = Number(value);
          return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : original;
        };
        const sync = (value, source) => {
          const next = clampValue(value);
          if (source !== "range") range.value = String(next);
          if (source !== "number") number.value = String(next);
          if (preview) {
            preview.textContent = `${estimateSalience(importanceRaw, next).toFixed(2)}（保存后将重算，当前 ${fmtSalience(salienceNow)}）`;
          }
        };
        range.addEventListener("input", () => sync(range.value, "range"));
        number.addEventListener("input", () => sync(number.value, "number"));
        saveArousal.addEventListener("click", async () => {
          const value = clampValue(number.value);
          const reason = reasonInput ? reasonInput.value.trim() : "";
          if (reason.length > 120) return toast("原因不能超过 120 字", "err");
          const ok = await confirmDialog(
            "校正唤醒度",
            `arousal ${fmtArousal(original)} → ${fmtArousal(value)}；保存后插件会重算显著性，只写 arousal/salience/审计，不改正文和重要性。确定继续？`,
            false
          );
          if (!ok) return;
          saveArousal.disabled = true;
          try {
            const result = await request(inst, `/items/${encodeURIComponent(memoryId)}/arousal`, {
              method: "POST",
              body: { arousal: value, reason },
            });
            const after = result && result.after ? result.after : {};
            const afterSalience = Number.isFinite(Number(after.salience))
              ? Number(after.salience)
              : estimateSalience(importanceRaw, value);
            toast(`唤醒度已更新：显著性 ${fmtSalience(afterSalience)}`);
            closeModal();
            await loadStatus();
          } catch (err) {
            saveArousal.disabled = false;
            toast(err.message, "err");
          }
        });
      }
      const editContent = modal.querySelector("[data-detail-edit-content]");
      if (editContent) editContent.addEventListener("click", () => editMemoryContent(inst, detail));
      const editImportance = modal.querySelector("[data-detail-edit-importance]");
      if (editImportance) editImportance.addEventListener("click", () => editMemoryImportance(inst, detail));
      const recon = modal.querySelector("[data-detail-recon]");
      if (recon) recon.addEventListener("click", () => openManualRecon(inst, memoryId));
      const resummarize = modal.querySelector("[data-detail-resummarize]");
      if (resummarize) resummarize.addEventListener("click", async () => {
        const ok = await confirmDialog("重新总结", "会使用保留的来源原文重新生成记忆；没有原文时插件会拒绝。确定继续？", false);
        if (!ok) return;
        try {
          await request(inst, `/items/${encodeURIComponent(memoryId)}/resummarize`, { method: "POST" });
          toast("已重新总结");
          closeModal();
          await loadStatus();
        } catch (err) {
          toast(err.message, "err");
        }
      });
      const archive = modal.querySelector("[data-detail-archive]");
      if (archive) archive.addEventListener("click", async () => {
        const target = detail.status === "archived" ? "active" : "archived";
        const ok = await confirmDialog(target === "archived" ? "归档记忆" : "恢复记忆", target === "archived" ? "归档后不再被召回，但可在已归档列表恢复。" : "恢复后会重建检索索引。", false);
        if (!ok) return;
        try {
          await request(inst, `/items/${encodeURIComponent(memoryId)}/update`, {
            method: "POST",
            body: { field: "status", value: target, reason: "管理器操作" },
          });
          toast(target === "archived" ? "已归档" : "已恢复");
          closeModal();
          await loadStatus();
        } catch (err) {
          toast(err.message, "err");
        }
      });
    }

    function editMemoryContent(inst, detail) {
      openModal({
        title: "编辑记忆内容",
        sub: "会重建向量、原子和图谱，并生成新 ID",
        wide: true,
        body: `<div class="field"><label>内容</label><textarea id="mem-edit-content" rows="8" spellcheck="false" style="font-family:var(--mono);font-size:12.5px">${esc(detail.text || "")}</textarea><span class="help">保留未展示的 metadata；来源原文会随替换保留。</span></div>`,
        footer: `<button class="btn ghost" data-close>取消</button><button class="btn primary" id="mem-edit-save">保存内容</button>`,
        onMount: (modal) => {
          modal.querySelector("#mem-edit-save").addEventListener("click", async () => {
            const value = modal.querySelector("#mem-edit-content").value.trim();
            if (!value) return toast("内容不能为空", "err");
            try {
              await request(inst, `/items/${encodeURIComponent(detail.memory_id)}/update`, {
                method: "POST",
                body: { field: "content", value, reason: "管理器手动编辑" },
              });
              toast("内容已更新");
              closeModal();
              await loadStatus();
            } catch (err) {
              toast(err.message, "err");
            }
          });
        },
      });
    }

    function editMemoryImportance(inst, detail) {
      openModal({
        title: "调整重要性",
        sub: "0.00–1.00；不会改正文",
        body: `<div class="field"><label>重要性</label><input id="mem-edit-importance" type="number" min="0" max="1" step="0.01" value="${esc(String(detail.importance ?? 0.5))}"><span class="help">写入 update_history，可追溯。</span></div>`,
        footer: `<button class="btn ghost" data-close>取消</button><button class="btn primary" id="mem-edit-save">保存</button>`,
        onMount: (modal) => {
          modal.querySelector("#mem-edit-save").addEventListener("click", async () => {
            const value = Number(modal.querySelector("#mem-edit-importance").value);
            if (!Number.isFinite(value) || value < 0 || value > 1) return toast("重要性必须在 0–1 之间", "err");
            try {
              await request(inst, `/items/${encodeURIComponent(detail.memory_id)}/update`, {
                method: "POST",
                body: { field: "importance", value, reason: "管理器手动调整" },
              });
              toast("重要性已更新");
              closeModal();
              await loadStatus();
            } catch (err) {
              toast(err.message, "err");
            }
          });
        },
      });
    }

    function openManualRecon(inst, memoryId) {
      openModal({
        title: "用新信息校正记忆",
        sub: "先预览，再应用；证据必须来自输入的文本",
        wide: true,
        body: `<div class="field"><label>新信息</label><textarea id="mem-recon-text" rows="5" placeholder="例如：不是这个地址，已经搬到朝阳了"></textarea></div>
          <div id="mem-recon-preview"></div>`,
        footer: `<button class="btn ghost" data-close>取消</button>
          <button class="btn ghost" id="mem-recon-preview-btn">预览</button>
          <button class="btn primary" id="mem-recon-apply" disabled>应用</button>`,
        onMount: (modal) => {
          let current = null;
          const previewBox = modal.querySelector("#mem-recon-preview");
          const applyBtn = modal.querySelector("#mem-recon-apply");
          modal.querySelector("#mem-recon-preview-btn").addEventListener("click", async () => {
            const text = modal.querySelector("#mem-recon-text").value.trim();
            if (!text) return toast("请输入新信息", "err");
            try {
              current = await request(inst, "/reconsolidation/manual", {
                method: "POST",
                body: { memory_id: Number(memoryId), user_message: text, mode: "preview" },
              });
              previewBox.innerHTML = `<div class="memory-diff">
                <div><span>动作</span><b>${esc(current.action || "keep")}</b></div>
                <div><span>置信度</span><b>${esc(fmtScore(current.confidence))}</b></div>
                <div><span>原因</span><b>${esc(current.reason || "—")}</b></div>
                <div><span>证据</span><b>${esc(current.evidence || "—")}</b></div>
                <div class="wide"><span>旧内容</span><p>${esc(current.old_content || "—")}</p></div>
                <div class="wide"><span>新内容</span><p>${esc(current.new_content || "—")}</p></div>
              </div>`;
              applyBtn.disabled = !["update", "supersede"].includes(current.action);
            } catch (err) {
              previewBox.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div></div>`;
              applyBtn.disabled = true;
            }
          });
          applyBtn.addEventListener("click", async () => {
            const text = modal.querySelector("#mem-recon-text").value.trim();
            if (!text || !current) return;
            applyBtn.disabled = true;
            try {
              const result = await request(inst, "/reconsolidation/manual", {
                method: "POST",
                body: { memory_id: Number(memoryId), user_message: text, mode: "apply" },
              });
              toast(result.applied ? "记忆已校正" : "没有写入改写");
              closeModal();
              await loadStatus();
            } catch (err) {
              applyBtn.disabled = false;
              toast(err.message, "err");
            }
          });
        },
      });
    }

    /* ------------------------------------------------------------ working */

    function renderWorking(pane) {
      pane.innerHTML = `
        <section class="card memory-filter-card">
          <div class="memory-section-head">
            <div>
              <div class="console-kicker">WORKING MEMORY</div>
              <h3>工作记忆</h3>
              <p class="console-help">只读视图：LivingMemory 视角的会话记忆，不进入模型上下文，也不会修改 AstrBot 对话上下文。</p>
            </div>
            <div class="console-actions memory-actions">
              <span class="memory-readonly">只读</span>
              <button class="btn sm ghost" data-working-refresh>${icon("refresh")}刷新</button>
            </div>
          </div>
        </section>
        <div class="memory-split">
          <section class="card memory-sessions-card">
            <div class="console-card-head"><h3>最近会话</h3><span>最多 30 个</span></div>
            <div id="working-sessions" class="memory-session-list"><div class="skeleton" style="height:120px"></div></div>
          </section>
          <div id="working-detail"><div class="memory-empty-inline">选择左侧会话查看最近记忆、原子与图谱入口。</div></div>
        </div>`;
      pane.querySelector("[data-working-refresh]").addEventListener("click", () => {
        loadWorkingSessions();
        if (workingSessionId) loadWorkingDetail();
      });
      loadWorkingSessions();
      if (workingSessionId) loadWorkingDetail();
    }

    async function loadWorkingSessions() {
      const inst = instance();
      if (!inst || workingBusy) return;
      workingBusy = true;
      const box = root && root.querySelector("#working-sessions");
      if (!box) {
        workingBusy = false;
        return;
      }
      box.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
      try {
        const data = await request(inst, "/working?limit=30");
        workingSessions = Array.isArray(data.sessions) ? data.sessions : [];
        workingError = "";
        renderWorkingSessions();
      } catch (err) {
        workingSessions = null;
        workingError = err.message;
        box.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div><button class="btn sm ghost" data-working-retry>重试</button></div>`;
        const retry = box.querySelector("[data-working-retry]");
        if (retry) retry.addEventListener("click", () => loadWorkingSessions());
      } finally {
        workingBusy = false;
      }
    }

    function renderWorkingSessions() {
      const box = root && root.querySelector("#working-sessions");
      if (!box || !workingSessions) return;
      if (!workingSessions.length) {
        box.innerHTML = `<div class="memory-empty-inline">还没有带会话 ID 的记忆。</div>`;
        return;
      }
      box.innerHTML = workingSessions.map((session) => {
        const sessionId = String(session.session_id || "");
        return `<button type="button" class="memory-session-item ${sessionId === workingSessionId ? "active" : ""}" data-working-session="${esc(sessionId)}">
          <b>${esc(truncate(sessionId, 48))}</b>
          <span>${esc(session.persona_id || "未标注人格")} · 记忆 ${Number(session.memory_count) || 0}</span>
          <span>${esc(formatTime(session.last_seen))}</span>
        </button>`;
      }).join("");
      box.querySelectorAll("[data-working-session]").forEach((node) => {
        node.addEventListener("click", () => {
          workingSessionId = node.dataset.workingSession;
          renderWorkingSessions();
          loadWorkingDetail();
        });
      });
    }

    async function loadWorkingDetail() {
      const inst = instance();
      if (!inst || !workingSessionId) return;
      const box = root && root.querySelector("#working-detail");
      if (!box) return;
      box.innerHTML = `<div class="card console-card"><div class="skeleton" style="height:160px"></div></div>`;
      try {
        workingDetail = await request(
          inst,
          `/working?session_id=${encodeURIComponent(workingSessionId)}&limit=20`
        );
        renderWorkingDetail();
      } catch (err) {
        workingDetail = null;
        box.innerHTML = `<div class="card console-card"><div class="console-warn"><div>${esc(err.message)}</div><button class="btn sm ghost" data-working-detail-retry>重试</button></div></div>`;
        const retry = box.querySelector("[data-working-detail-retry]");
        if (retry) retry.addEventListener("click", () => loadWorkingDetail());
      }
    }

    function renderWorkingDetail() {
      const box = root && root.querySelector("#working-detail");
      if (!box || !workingDetail) return;
      const data = workingDetail;
      const memories = Array.isArray(data.recent_memories)
        ? data.recent_memories
        : Array.isArray(data.memories) ? data.memories : [];
      const atoms = Array.isArray(data.recent_atoms)
        ? data.recent_atoms
        : Array.isArray(data.atoms) ? data.atoms : [];
      const graphEntries = Array.isArray(data.graph_entries) ? data.graph_entries : [];
      const sessionId = String(data.session_id || workingSessionId);
      const memoryRows = memories.length
        ? `<div class="memory-table-wrap"><table class="table memory-table">
            <thead><tr><th>ID</th><th>摘要</th><th>类型</th><th>重要性</th><th>唤醒</th><th>显著</th><th>时间</th></tr></thead>
            <tbody>${memories.map((item) => `<tr>
              <td class="mono">${esc(shortId(item.id))}</td>
              <td>${esc(truncate(item.summary || "—", 110))}</td>
              <td>${esc(memoryTypeLabel(item.memory_type))}</td>
              <td class="mono">${esc(importanceLabel(item.importance))}</td>
              <td class="mono">${esc(fmtArousal(item.arousal))}</td>
              <td class="mono">${esc(fmtSalience(item.salience))}</td>
              <td class="mono">${esc(formatTime(item.created_at))}</td>
            </tr>`).join("")}</tbody></table></div>`
        : `<div class="memory-empty-inline">该会话没有最近记忆。</div>`;
      const atomRows = atoms.length
        ? `<div class="memory-table-wrap"><table class="table memory-table">
            <thead><tr><th>类型</th><th>内容</th><th>重要性</th><th>状态</th><th>到期</th></tr></thead>
            <tbody>${atoms.map((item) => `<tr>
              <td>${esc(item.type || "—")}</td>
              <td>${esc(truncate(item.content || "—", 110))}</td>
              <td class="mono">${esc(importanceLabel(item.importance))}</td>
              <td><span class="memory-status ${esc(item.status || "active")}">${esc(item.status || "—")}</span></td>
              <td class="mono">${esc(formatTime(item.expires_at))}</td>
            </tr>`).join("")}</tbody></table></div>`
        : `<div class="memory-empty-inline">该会话没有记忆原子。</div>`;
      const graphRows = graphEntries.length
        ? `<div class="memory-table-wrap"><table class="table memory-table">
            <thead><tr><th>关系类型</th><th>内容</th></tr></thead>
            <tbody>${graphEntries.map((item) => `<tr>
              <td>${esc(item.relation_type || "related")}</td>
              <td>${esc(truncate(item.content || "—", 140))}</td>
            </tr>`).join("")}</tbody></table></div>`
        : `<div class="memory-empty-inline">该会话没有图谱入口。</div>`;
      box.innerHTML = `
        <section class="card console-card">
          <div class="console-card-head"><h3>${esc(truncate(sessionId, 56))}</h3><span class="memory-readonly">只读</span></div>
          <div class="memory-kv">
            <div><span>会话</span><b>${esc(sessionId)}</b></div>
            <div><span>人格</span><b>${esc(data.persona_id || "—")}</b></div>
            <div><span>最近活动</span><b>${esc(formatTime(data.last_seen))}</b></div>
            <div><span>记忆 / 原子</span><b>${Number(data.memory_count) || 0} / ${Number(data.atom_count) || 0}</b></div>
          </div>
          <div class="console-actions memory-actions">
            <button class="btn sm ghost" data-working-brain>${icon("pulse")}在脑图中高亮此会话</button>
            <button class="btn sm ghost" data-working-library>${icon("search")}在记忆库中查看会话</button>
          </div>
          <div class="console-help">只读，不进入模型上下文；不会修改 AstrBot 对话上下文。</div>
        </section>
        <section class="card console-card"><div class="console-card-head"><h3>最近记忆</h3><span>${memories.length} 条</span></div>${memoryRows}</section>
        <section class="card console-card"><div class="console-card-head"><h3>记忆原子</h3><span>${atoms.length} 条</span></div>${atomRows}</section>
        <section class="card console-card"><div class="console-card-head"><h3>图谱入口</h3><span>${graphEntries.length} 条</span></div>${graphRows}</section>`;
      const brainButton = box.querySelector("[data-working-brain]");
      if (brainButton) brainButton.addEventListener("click", () => {
        applyBrainHighlight({
          memoryIds: memories.map((item) => item.id),
          relationKey: "",
        });
      });
      const libraryButton = box.querySelector("[data-working-library]");
      if (libraryButton) libraryButton.addEventListener("click", () => {
        libState.session_id = sessionId;
        libState.keyword = "";
        libState.person = "";
        libState.person_label = "";
        libState.page = 1;
        activeTab = "library";
        syncTabButtons();
        renderTab();
      });
    }

    /* ---------------------------------------------------------- relations */

    function renderRelations(pane) {
      pane.innerHTML = `
        <section class="card memory-filter-card">
          <div class="memory-section-head">
            <div>
              <div class="console-kicker">RELATIONS &amp; EMOTION</div>
              <h3>关系与情绪</h3>
              <p class="console-help">只读：人物来自记忆里的参与者身份，怒气/好感/熟悉度与心情事件来自管理器本地心情记录。</p>
            </div>
            <div class="console-actions memory-actions">
              <span class="memory-readonly">只读</span>
              <button class="btn sm ghost" data-relations-refresh>${icon("refresh")}刷新</button>
            </div>
          </div>
        </section>
        <div class="memory-split memory-relations-split">
          <section class="card memory-sessions-card">
            <div class="console-card-head"><h3>人物</h3><span>最近 90 天</span></div>
            <div id="relations-list" class="memory-session-list"><div class="skeleton" style="height:120px"></div></div>
          </section>
          <div id="relation-detail"><div class="memory-empty-inline">选择左侧人物查看关系值、心情与情绪时间线。</div></div>
        </div>`;
      pane.querySelector("[data-relations-refresh]").addEventListener("click", () => {
        emotionData = null;
        loadRelations();
      });
      loadRelations();
    }

    async function loadRelations() {
      const inst = instance();
      if (!inst || relationsBusy) return;
      relationsBusy = true;
      const box = root && root.querySelector("#relations-list");
      if (box) box.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
      try {
        const data = await request(inst, "/relations?days=90&limit=100");
        relationsData = Array.isArray(data.relations) ? data.relations : [];
        relationsError = "";
        if (!relationsData.some((item) => item.identity_key === relationSelectedKey)) {
          relationSelectedKey = relationsData.length ? String(relationsData[0].identity_key || "") : "";
        }
        renderRelationList();
        if (relationSelectedKey) loadEmotion(relationSelectedKey);
        else renderRelationDetail();
      } catch (err) {
        relationsData = null;
        relationsError = err.message;
        if (box) {
          box.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div><button class="btn sm ghost" data-relations-retry>重试</button></div>`;
          const retry = box.querySelector("[data-relations-retry]");
          if (retry) retry.addEventListener("click", () => loadRelations());
        }
        renderRelationDetail();
      } finally {
        relationsBusy = false;
      }
    }

    function renderRelationList() {
      const box = root && root.querySelector("#relations-list");
      if (!box) return;
      if (!relationsData || !relationsData.length) {
        box.innerHTML = `<div class="memory-empty-inline">没有可聚合的非 bot 人物。</div>`;
        return;
      }
      box.innerHTML = relationsData.map((relation) => {
        const key = String(relation.identity_key || "");
        const mood = relation.mood || {};
        const current = mood.current || {};
        return `<button type="button" class="memory-session-item memory-person-card ${key === relationSelectedKey ? "active" : ""}" data-relation-key="${esc(key)}">
          <b>${esc(relation.display_name || relation.sender_id || key)}</b>
          <span>${esc(relation.platform || "unknown")} · ${esc(relation.sender_id || "—")} · 记忆 ${Number(relation.memory_count) || 0}</span>
          <span>怒 ${Math.round(Number(mood.anger) || 0)} · 好感 ${Math.round(Number(mood.affection) || 0)} · 熟 ${Math.round(Number(mood.familiarity) || 0)}</span>
          <span>${esc(current.label || "暂无心情事件")}${current.label ? ` · 唤醒均值 ${esc(fmtArousal(relation.mean_arousal))}` : ""}</span>
        </button>`;
      }).join("");
      box.querySelectorAll("[data-relation-key]").forEach((node) => {
        node.addEventListener("click", () => {
          relationSelectedKey = node.dataset.relationKey;
          emotionData = null;
          renderRelationList();
          renderRelationDetail();
          loadEmotion(relationSelectedKey);
        });
      });
    }

    function relationByKey(key) {
      return (relationsData || []).find((item) => String(item.identity_key) === String(key)) || null;
    }

    function renderRelationDetail() {
      const box = root && root.querySelector("#relation-detail");
      if (!box) return;
      const relation = relationByKey(relationSelectedKey);
      if (!relation) {
        box.innerHTML = `<div class="card console-card"><div class="memory-empty-inline">${esc(relationsError || "选择左侧人物查看详情。")}</div></div>`;
        return;
      }
      const mood = relation.mood || null;
      const current = mood && mood.current ? mood.current : null;
      const types = Array.isArray(relation.top_types) ? relation.top_types : [];
      const events = mood && Array.isArray(mood.events) ? mood.events : [];
      const name = relation.display_name || relation.sender_id || relation.identity_key;
      box.innerHTML = `
        <section class="card console-card">
          <div class="console-card-head"><h3>${esc(name)}</h3><span>${esc(relation.identity_key || "")}</span></div>
          <div class="memory-kv">
            <div><span>平台 / ID</span><b>${esc(relation.platform || "—")} · ${esc(relation.sender_id || "—")}</b></div>
            <div><span>记忆数</span><b>${Number(relation.memory_count) || 0}</b></div>
            <div><span>最近出现</span><b>${esc(formatTime(relation.last_seen))}</b></div>
            <div><span>唤醒 / 显著均值</span><b>${esc(fmtArousal(relation.mean_arousal))} / ${esc(fmtSalience(relation.mean_salience))}</b></div>
            <div><span>常见类型</span><b>${types.length ? types.map((type) => `<span class="memory-person-tag">${esc(memoryTypeLabel(type))}</span>`).join("") : "—"}</b></div>
          </div>
          <div class="memory-mood-grid">
            <div><span>怒气</span><b>${Math.round(Number(mood && mood.anger) || 0)}</b></div>
            <div><span>好感</span><b>${Math.round(Number(mood && mood.affection) || 0)}</b></div>
            <div><span>熟悉度</span><b>${Math.round(Number(mood && mood.familiarity) || 0)}</b></div>
            <div><span>当前心情</span><b>${esc(current && current.label || "—")}</b></div>
          </div>
          ${current ? `<div class="console-help">强度 ${esc(String(Number(current.intensity) || 0))} · 精力 ${esc(String(Number(current.energy) || 0))} · 社交 ${esc(String(Number(current.social) || 0))}</div>` : `<div class="console-help">${
            mood ? "该人物暂时没有心情事件。" : "管理器没有该人物的心情记录（仅显示记忆关系）。"
          }</div>`}
          <div class="console-actions memory-actions">
            <button class="btn sm ghost" data-relation-library>${icon("search")}在记忆库中查看此人</button>
            <button class="btn sm ghost" data-relation-brain>${icon("pulse")}在脑图中高亮此人</button>
          </div>
        </section>
        <div id="relation-emotion"><div class="skeleton" style="height:140px"></div></div>
        <section class="card console-card">
          <div class="console-card-head"><h3>心情事件</h3><span>${events.length} 条</span></div>
          ${events.length ? `<div class="memory-lane">${events.map((event) => `<div class="memory-lane-row">
            <time>${esc(formatTime(event.created))}</time>
            <b>${esc(event.label || event.mood || "—")}</b>
            <span>${esc(truncate(event.reason || "—", 90))}</span>
            <em>怒 ${esc(String(Math.round(Number(event.anger_delta) || 0)))} · 好感 ${esc(String(Math.round(Number(event.affection_delta) || 0)))} · 熟 ${esc(String(Math.round(Number(event.familiarity_delta) || 0)))}</em>
          </div>`).join("")}</div>` : `<div class="memory-empty-inline">暂无心情事件。</div>`}
          ${events.some((event) => event.tone_hint) ? `<div class="console-help">语气提示：${esc(events.find((event) => event.tone_hint).tone_hint)}</div>` : ""}
        </section>`;
      const libraryButton = box.querySelector("[data-relation-library]");
      if (libraryButton) libraryButton.addEventListener("click", () => {
        jumpToLibrary(relation.identity_key, name);
      });
      const brainButton = box.querySelector("[data-relation-brain]");
      if (brainButton) brainButton.addEventListener("click", () => {
        applyBrainHighlight({
          memoryIds: relation.sample_memory_ids || [],
          relationKey: name,
        });
      });
      renderEmotionLanes();
    }

    async function loadEmotion(identityKey) {
      const inst = instance();
      if (!inst || !identityKey) return;
      const box = root && root.querySelector("#relation-emotion");
      if (box) box.innerHTML = `<div class="card console-card"><div class="skeleton" style="height:140px"></div></div>`;
      emotionBusy = true;
      try {
        const data = await request(
          inst,
          `/emotion?identity_key=${encodeURIComponent(identityKey)}&days=90&limit=200`
        );
        emotionData = {
          identity_key: identityKey,
          items: Array.isArray(data.items) ? data.items : [],
        };
        emotionError = "";
      } catch (err) {
        emotionData = null;
        emotionError = err.message;
      } finally {
        emotionBusy = false;
      }
      if (identityKey === relationSelectedKey) renderEmotionLanes();
    }

    function renderEmotionLanes() {
      const box = root && root.querySelector("#relation-emotion");
      if (!box) return;
      if (emotionError) {
        box.innerHTML = `<div class="card console-card"><div class="console-warn"><div>${esc(emotionError)}</div><button class="btn sm ghost" data-emotion-retry>重试</button></div></div>`;
        const retry = box.querySelector("[data-emotion-retry]");
        if (retry) retry.addEventListener("click", () => loadEmotion(relationSelectedKey));
        return;
      }
      const items = emotionData && Array.isArray(emotionData.items) ? emotionData.items : [];
      box.innerHTML = `<section class="card console-card">
        <div class="console-card-head"><h3>记忆情绪时间线</h3><span>${items.length} 条 · 按唤醒度排序</span></div>
        ${items.length ? `<div class="memory-lane">${items.map((item) => `<div class="memory-lane-row">
          <time>${esc(formatTime(item.created_at))}</time>
          <b>${esc(shortId(item.memory_id))}</b>
          <span>${esc(truncate(item.summary || "—", 110))}</span>
          <em>唤醒 ${esc(fmtArousal(item.arousal))} · 显著 ${esc(fmtSalience(item.salience))} · ${esc(item.sentiment || "neutral")}</em>
        </div>`).join("")}</div>` : `<div class="memory-empty-inline">${emotionBusy ? "加载中…" : "该人物还没有记忆情绪记录。"}</div>`}
        ${items.some((item) => Array.isArray(item.key_facts) && item.key_facts.length) ? `<div class="console-help">关键事实：${esc(items.flatMap((item) => item.key_facts || []).slice(0, 6).join("；"))}</div>` : ""}
      </section>`;
    }

    function jumpToLibrary(identityKey, label) {
      libState.person = String(identityKey || "");
      libState.person_label = String(label || identityKey || "");
      libState.keyword = "";
      libState.page = 1;
      activeTab = "library";
      syncTabButtons();
      renderTab();
    }

    /* -------------------------------------------------------------- sleep */

    function renderSleep(pane) {
      const sleep = statusData && statusData.sleep ? statusData.sleep : {};
      const recon = statusData && statusData.reconsolidation ? statusData.reconsolidation : {};
      const backfill = statusData && statusData.backfill ? statusData.backfill : {};
      const lastReport = sleep.last_report && typeof sleep.last_report === "object" ? sleep.last_report : {};
      const reportTime = lastReport.started_at || sleep.last_run_at;
      const backup = lastReport.backup && typeof lastReport.backup === "object" ? lastReport.backup : {};
      const backupPath = backup.path || backup.file || backup.db_path || "—";
      const today = new Date();
      const todayStamp = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      const ranToday = sleep.last_run_date === todayStamp;
      const allowlist = parseGroupAllowlist(recon.group_allowlist);
      pane.innerHTML = `
        <div class="memory-sleep-grid">
          <section class="card console-card">
            <div class="console-card-head"><h3>睡眠周期</h3><span>${sleep.enabled ? "自动已启用" : "自动未启用"}</span></div>
            <div class="memory-kv">
              <div><span>状态</span><b>${sleep.running ? "运行中 · " + esc(sleep.step || "") : "空闲"}</b></div>
              <div><span>今日衰减</span><b>${ranToday ? "今日已执行（含衰减）" : "今日未执行"}</b></div>
              <div><span>上次运行</span><b>${esc(sleep.last_run_date || "—")}</b></div>
              <div><span>下次运行</span><b>${sleep.next_run_at ? esc(new Date(sleep.next_run_at * 1000).toLocaleString()) : "自动未启用"}</b></div>
              <div><span>上次报告</span><b>${esc(formatTime(reportTime))}</b></div>
              <div><span>备份路径</span><b title="${esc(backupPath)}">${esc(truncate(backupPath, 60))}</b></div>
              <div><span>最近错误</span><b>${esc(sleep.last_error || "—")}</b></div>
            </div>
            <div class="console-actions memory-actions">
              <button class="btn ghost" data-sleep-preview>${icon("search")}加载预览</button>
              <button class="btn primary" data-sleep-run disabled>${icon("play")}立即睡眠</button>
            </div>
            <div id="sleep-live"></div>
          </section>
          <section class="card console-card">
            <div class="console-card-head"><h3>再巩固</h3><span>${recon.enabled ? "已启用" : "已关闭"}</span></div>
            <div class="memory-kv">
              <div><span>今日判定</span><b>${recon.count ?? 0} / ${recon.daily_limit ?? "—"}</b></div>
              <div><span>已改写</span><b>${recon.updated ?? 0}</b></div>
              <div><span>跳过</span><b>${recon.skipped ?? 0}</b></div>
              <div><span>策略</span><b>私聊${recon.private_chat ? "开" : "关"} · 群聊${recon.group_chat ? "开" : "关"}</b></div>
              <div><span>群白名单</span><b>${esc(allowlist.length ? allowlist.join("、") : "空名单不允许任何群")}</b></div>
            </div>
            <div class="console-help">自动再巩固只在召回命中且用户明确纠正时触发；手动校正入口在记忆详情。群聊只对白名单群生效，空名单不允许任何群。</div>
          </section>
          <section class="card console-card">
            <div class="console-card-head"><h3>显著性回填</h3><span>${backfill.status || "idle"}</span></div>
            <div class="memory-kv">
              <div><span>进度</span><b>${backfill.done ?? 0} / ${backfill.total ?? "—"}</b></div>
              <div><span>已更新</span><b>${backfill.updated ?? 0}</b></div>
              <div><span>失败</span><b>${backfill.failed ?? 0}</b></div>
              <div><span>类型补全</span><b>${backfill.type_filled ?? 0}</b></div>
            </div>
            <div class="console-actions memory-actions">
              <button class="btn ghost" data-backfill-preview>${icon("search")}预览</button>
              <button class="btn primary" data-backfill-run>${icon("play")}开始回填</button>
              <button class="btn ghost" data-backfill-cancel>取消</button>
            </div>
            <div id="backfill-live"></div>
          </section>
        </div>
        <section class="card memory-preview-card"><div id="sleep-preview" class="memory-empty-inline">尚未加载预览。预览不会写任何数据。</div></section>
        <section class="card memory-config-card"><div class="console-card-head"><h3>生命周期参数</h3><span>保存后按插件机制生效</span></div><div id="mem-config-form" class="memory-form-grid">加载中…</div><div class="console-actions memory-actions"><button class="btn primary" data-config-save>保存参数</button></div></section>
        <section class="card memory-reports-card"><div class="console-card-head"><h3>最近睡眠报告</h3><span>梦境叙事 · 重放记忆时间线</span></div><div id="sleep-reports">加载中…</div></section>`;
      pane.querySelector("[data-sleep-preview]").addEventListener("click", () => loadSleepPreview());
      pane.querySelector("[data-sleep-run]").addEventListener("click", () => runSleep());
      pane.querySelector("[data-backfill-preview]").addEventListener("click", () => loadBackfillPreview());
      pane.querySelector("[data-backfill-run]").addEventListener("click", () => runBackfill());
      pane.querySelector("[data-backfill-cancel]").addEventListener("click", () => cancelBackfill());
      pane.querySelector("[data-config-save]").addEventListener("click", () => saveConfig());
      loadSleepPreview(false);
      loadConfig();
      loadSleepReports();
      if (backfill.status === "running") pollBackfill();
      if (sleep.running) pollSleep();
    }

    async function loadSleepPreview(showToast = true) {
      const inst = instance();
      if (!inst) return;
      const box = root && root.querySelector("#sleep-preview");
      if (box) box.innerHTML = `<div class="skeleton" style="height:100px"></div>`;
      try {
        sleepPreview = await request(inst, "/sleep/preview");
        renderSleepPreview();
        renderSleepReports();
        const run = root && root.querySelector("[data-sleep-run]");
        if (run) run.disabled = Boolean(sleepPreview.currently_running);
        if (showToast) toast("睡眠预览已加载");
      } catch (err) {
        if (box) box.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div></div>`;
      }
    }

    function renderSleepPreview() {
      const box = root && root.querySelector("#sleep-preview");
      if (!box || !sleepPreview) return;
      const p = sleepPreview;
      const extraWarnings = (p.warnings || []).filter(
        (text) => !String(text).includes("今天已经执行过衰减")
      );
      box.innerHTML = `<div class="stat-grid memory-preview-stats">
        ${statCard("清理候选", p.cleanup_candidates ?? 0, "睡眠路径只归档")}
        ${statCard("整合候选", p.consolidation_candidates ?? 0, `预计 ${p.consolidation_groups_estimate ?? 0} 组`)}
        ${statCard("重放候选", (p.rehearsal_candidates || []).length, "只更新访问统计")}
        ${statCard("数据库", formatBytes(p.db_size_bytes), `可用 ${formatBytes(p.free_space_bytes)}`)}
      </div>
      ${p.decay_already_today ? `<div class="console-warn"><div>今天已经执行过衰减；本次会跳过衰减和清理，仍会整合与重放。</div></div>` : ""}
      ${extraWarnings.length ? `<div class="console-warn">${extraWarnings.map((text) => `<div>${esc(text)}</div>`).join("")}</div>` : ""}
      ${(p.rehearsal_candidates || []).length ? `<div class="memory-rehearsal"><b>重放 Top ${(p.rehearsal_candidates || []).length}</b>${(p.rehearsal_candidates || []).slice(0, 8).map((item) =>
        `<div class="memory-history-row"><span>${esc(shortId(item.id))}</span><span>${esc(truncate(item.content, 70))}</span><em>重要 ${esc(importanceLabel(item.importance))} · 显著 ${esc(fmtSalience(item.salience))}</em></div>`
      ).join("")}</div>` : ""}`;
    }

    async function runSleep() {
      const inst = instance();
      if (!inst || !sleepPreview) return;
      const ok = await confirmDialog("立即睡眠", "会先备份，然后衰减、归档清理、整合和重放。清理只归档，可从记忆库恢复。确定继续？", false);
      if (!ok) return;
      try {
        await request(inst, "/sleep/run", { method: "POST" });
        toast("睡眠任务已启动");
        pollSleep();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function pollSleep() {
      clearTimers();
      const inst = instance();
      if (!inst) return;
      const tick = async () => {
        try {
          const status = await request(inst, "/sleep/status");
          const live = root && root.querySelector("#sleep-live");
          if (live) live.innerHTML = status.running
            ? `<div class="memory-live">${icon("pulse")} 正在执行：${esc(status.step || "…")}</div>`
            : `<div class="memory-live">上次任务已结束${status.last_error ? `：${esc(status.last_error)}` : ""}</div>`;
          if (!status.running) {
            clearTimers();
            await loadStatus();
            loadSleepReports();
          }
        } catch (err) {
          clearTimers();
          const live = root && root.querySelector("#sleep-live");
          if (live) live.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div></div>`;
        }
      };
      tick();
      rememberTimer(setInterval(tick, 2000));
    }

    async function loadSleepReports() {
      const inst = instance();
      if (!inst) return;
      const box = root && root.querySelector("#sleep-reports");
      if (!box) return;
      try {
        sleepReports = await request(inst, "/sleep/reports?limit=10");
        renderSleepReports();
      } catch (err) {
        sleepReports = [];
        box.innerHTML = `<div class="console-warn"><div>睡眠报告读取失败：${esc(err.message)}</div></div>`;
      }
    }

    function renderSleepReports() {
      const box = root && root.querySelector("#sleep-reports");
      if (!box) return;
      if (!Array.isArray(sleepReports) || !sleepReports.length) {
        box.innerHTML = `<div class="memory-empty-inline">还没有睡眠报告。梦境默认关闭，可在上方“生命周期参数”中开启。</div>`;
        return;
      }
      const candidates =
        sleepPreview && Array.isArray(sleepPreview.rehearsal_candidates)
          ? sleepPreview.rehearsal_candidates
          : [];
      box.innerHTML = sleepReports
        .map((item, index) => {
          const summary =
            item.summary && typeof item.summary === "object" ? item.summary : item;
          const dream = summary.dream && typeof summary.dream === "object" ? summary.dream : {};
          const rehearsal = summary.rehearsal && typeof summary.rehearsal === "object"
            ? summary.rehearsal
            : {};
          return `<article class="memory-dream-card ${index === 0 ? "latest" : ""}">
            <div class="memory-dream-head">
              <div>
                <b>${esc(item.trigger || "手动")} · ${esc(formatTime(item.started_at))}</b>
                <span>${esc(summarizeReport(summary))} · 用时 ${esc(formatDurationMs(item.duration_ms))}</span>
              </div>
              <span class="mono">${esc(item.file || "最近一次")}</span>
            </div>
            ${dreamHtml(dream)}
            ${replayHtml(item, summary, rehearsal, candidates, index === 0)}
          </article>`;
        })
        .join("");
      box.querySelectorAll("[data-dream-memory]").forEach((node) => {
        node.addEventListener("click", () => openDetail(node.dataset.dreamMemory));
      });
    }

    function dreamHtml(dream) {
      const state = dreamState(dream);
      if (state === "text") {
        const ids = dreamMemoryIds(dream);
        return `<div class="memory-dream-box">
          <div class="memory-dream-kicker">梦境叙事</div>
          <p class="memory-dream-text">${esc(dreamNarrative(dream))}</p>
          <div class="memory-dream-meta">
            <span>模型 ${esc(dream.model_id || "—")}</span>
            <span>${esc(formatTime(dream.created_at))}</span>
            <span>参考 ${ids.length} 条重放记忆</span>
          </div>
          ${ids.length ? `<div class="memory-dream-ids">${ids.map((id) =>
            `<button type="button" class="memory-dream-chip" data-dream-memory="${esc(id)}">${esc(shortId(id))}</button>`
          ).join("")}</div>` : ""}
        </div>`;
      }
      if (state === "error") {
        return `<div class="memory-dream-box"><div class="memory-dream-kicker">梦境叙事</div>
          <div class="console-warn"><div>梦境生成失败：${esc(dream.error)}（不影响睡眠其它步骤）</div></div>
        </div>`;
      }
      if (state === "skipped") {
        const reason = dream.reason === "no_rehearsal_memories"
          ? "本次没有可重放的记忆，未生成梦境。"
          : "本次梦境已跳过。";
        return `<div class="memory-dream-box"><div class="memory-dream-kicker">梦境叙事</div>
          <div class="memory-empty-inline">${esc(reason)}</div></div>`;
      }
      if (state === "disabled") {
        return `<div class="memory-dream-box"><div class="memory-dream-kicker">梦境叙事</div>
          <div class="memory-empty-inline">本次睡眠未生成梦境：梦境默认关闭，开启后每次睡眠会多一次本地模型调用，只写入报告，不发用户。</div>
        </div>`;
      }
      return `<div class="memory-dream-box"><div class="memory-dream-kicker">梦境叙事</div>
        <div class="memory-empty-inline">这份报告没有梦境数据（旧报告或插件未启用）。</div></div>`;
    }

    function replayHtml(item, summary, rehearsal, candidates, latest) {
      const rows = replayTimelineRows(item, candidates);
      let timeline = rows;
      let hint = "";
      if (!timeline.length && latest) {
        timeline = (Array.isArray(candidates) ? candidates : []).slice(0, 8).map((candidate) => ({
          memory_id: Number(candidate.id),
          time: summary.started_at || null,
          summary: String(candidate.content || "").trim(),
          importance: Number.isFinite(Number(candidate.importance)) ? Number(candidate.importance) : null,
          salience: Number.isFinite(Number(candidate.salience)) ? Number(candidate.salience) : null,
        })).filter((row) => Number.isFinite(row.memory_id) && row.memory_id > 0);
        if (timeline.length) hint = "取自最近一次睡眠预览的重放候选";
      }
      const counts = `候选 ${Number(rehearsal.candidates) || 0} 条 · 实际强化 ${Number(rehearsal.updated) || 0} 条`;
      if (!timeline.length) {
        return `<div class="memory-replay">
          <div class="memory-replay-head"><b>重放记忆时间线</b><span>${esc(counts)}</span></div>
          <div class="memory-empty-inline">本次报告没有记录重放记忆明细；重放只更新访问统计。</div>
        </div>`;
      }
      return `<div class="memory-replay">
        <div class="memory-replay-head"><b>重放记忆时间线</b><span>${esc(counts)}${hint ? ` · ${esc(hint)}` : ""}</span></div>
        <div class="memory-lane">${timeline.map((row) => `<div class="memory-lane-row">
          <time>${esc(formatTime(row.time))}</time>
          <b>${esc(shortId(row.memory_id))}</b>
          <span>${esc(row.summary || "报告未保存摘要，可在记忆库查看")}</span>
          <em>重要 ${esc(row.importance === null ? "—" : importanceLabel(row.importance))} · 显著 ${esc(row.salience === null ? "—" : fmtSalience(row.salience))}</em>
        </div>`).join("")}</div>
      </div>`;
    }

    async function loadConfig() {
      const inst = instance();
      if (!inst) return;
      const box = root && root.querySelector("#mem-config-form");
      if (!box) return;
      try {
        helperConfig = await request(inst, "/config");
        helperConfigError = "";
        renderConfigForm();
      } catch (err) {
        helperConfigError = err.message;
        box.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div></div>`;
      }
    }

    function fieldOf(path) {
      const sections = (helperConfig && helperConfig.sections) || [];
      for (const section of sections) {
        const field = (section.fields || []).find((item) => item.path === path);
        if (field) return field;
      }
      return null;
    }

    function configValue(path, fallback) {
      const field = fieldOf(path);
      return field && field.value !== undefined && field.value !== null ? field.value : fallback;
    }

    function boolField(path, label, hint, fallback = false) {
      const value = Boolean(configValue(path, fallback));
      return `<label class="memory-config-field"><span>${esc(label)}</span><input type="checkbox" data-cfg="${esc(path)}" ${value ? "checked" : ""}><small>${esc(hint || "")}</small></label>`;
    }

    function numberField(path, label, hint, step = "0.01", fallback = "", min = null, max = null) {
      const value = formatConfigNumber(configValue(path, fallback), step);
      const bounds = `${min === null ? "" : ` min="${esc(min)}"`}${max === null ? "" : ` max="${esc(max)}"`}`;
      return `<label class="memory-config-field"><span>${esc(label)}</span><input type="number" step="${step}"${bounds} data-cfg="${esc(path)}" value="${esc(value)}"><small>${esc(hint || "")}</small></label>`;
    }

    function textField(path, label, hint) {
      return `<label class="memory-config-field"><span>${esc(label)}</span><input type="text" data-cfg="${esc(path)}" value="${esc(String(configValue(path, "")))}"><small>${esc(hint || "")}</small></label>`;
    }

    function textareaField(path, label, hint, rows = 3) {
      const value = formatGroupAllowlist(configValue(path, ""));
      return `<label class="memory-config-field"><span>${esc(label)}</span><textarea rows="${rows}" data-cfg="${esc(path)}" placeholder="群号，逗号或换行分隔">${esc(value)}</textarea><small>${esc(hint || "")}</small></label>`;
    }

    function renderConfigForm() {
      const box = root && root.querySelector("#mem-config-form");
      if (!box) return;
      box.innerHTML = [
        boolField("human_memory.sleep.enabled", "自动睡眠", "首次开启前先预览；默认关闭。"),
        textField("human_memory.sleep.time", "睡眠时间", "HH:MM，本地时间"),
        boolField("human_memory.sleep.consolidation", "睡眠整合", "强制整合，但仍受组数限制"),
        boolField("human_memory.sleep.backup", "睡眠前备份", "备份失败会中止"),
        boolField("human_memory.sleep.archive_only", "只归档", "睡眠清理只归档，不物理删除，可恢复"),
        numberField("human_memory.sleep.rehearsal_top_n", "重放条数", "每晚最多重放", "1"),
        numberField("human_memory.sleep.rehearsal_min_interval_days", "重放间隔（天）", "同一记忆的冷却", "0.5"),
        numberField("memory_consolidation.max_groups_per_run", "最大整合组数", "全局整合上限（memory_consolidation）", "1"),
        numberField("human_memory.sleep.keep_reports", "报告保留数", "保留最近多少份睡眠报告", "1"),
        boolField("human_memory.sleep.dream.enabled", "睡眠梦境", "默认关闭；开启后每次睡眠多一次模型调用，只写入报告，不发用户。"),
        numberField("human_memory.sleep.dream.max_memories", "梦境参考记忆数", "最多用多少条重放记忆生成梦境，默认 8", "1", 8),
        numberField("human_memory.sleep.dream.max_chars", "梦境字数上限", "超过后截断保存，默认 600", "1", 600),
        boolField("human_memory.reconsolidation.enabled", "自动再巩固", "手动校正不受此开关影响"),
        boolField("human_memory.reconsolidation.private_chat", "私聊再巩固", "默认开"),
        boolField("human_memory.reconsolidation.group_chat", "群聊再巩固", "默认关，避免玩笑误判"),
        textareaField("human_memory.reconsolidation.group_allowlist", "群号白名单", "逗号或换行分隔；只对白名单群生效，空名单不允许任何群。"),
        numberField("human_memory.reconsolidation.daily_limit", "每日判定上限", "每天模型调用次数", "1"),
        numberField("human_memory.reconsolidation.cooldown_seconds", "会话冷却（秒）", "同一会话的最小间隔", "10"),
        numberField("human_memory.reconsolidation.min_confidence", "私聊置信度", "低于该值不写回", "0.01"),
        numberField("human_memory.reconsolidation.group_min_confidence", "群聊置信度", "更严格阈值", "0.01"),
        numberField("human_memory.salience.arousal_ttl_boost", "情绪寿命放大", "原子 TTL 最高 1.5 倍", "0.01"),
        numberField("human_memory.salience.default_arousal", "默认唤醒度", "缺失字段与旧记忆", "0.01"),
        numberField("human_memory.backfill.batch_size", "回填批大小", "每次模型调用条数", "1"),
        numberField("human_memory.backfill.max_per_run", "回填上限", "单次最多处理", "10"),
        numberField("human_memory.backfill.delay_seconds", "回填间隔（秒）", "批次间等待", "0.5"),
        `<div class="console-card-head" style="grid-column: 1 / -1; margin: 8px 0 0"><h3>两段式向量召回</h3><span>默认开启，失败回退现有混合检索</span></div>`,
        boolField("recall_engine.two_stage_enabled", "启用两段式召回", "默认开启，失败回退现有混合检索", true),
        numberField("recall_engine.two_stage_candidates", "候选数", "模糊召回候选条数，范围 1-200", "1", 30, 1, 200),
        numberField("recall_engine.two_stage_vector_weight", "向量权重", "向量精排分权重，范围 0-1", "0.01", 0.6, 0, 1),
        numberField("recall_engine.two_stage_fuzzy_weight", "模糊权重", "模糊候选分权重，范围 0-1", "0.01", 0.4, 0, 1),
        numberField("recall_engine.two_stage_vector_k", "向量查询上限", "FAISS kNN 上限，范围 1-8192", "1", 8192, 1, 8192),
      ].join("");
    }

    async function saveConfig() {
      const inst = instance();
      if (!inst) return;
      let values = {};
      try {
        values = collectConfigValues(root.querySelectorAll("[data-cfg]"));
      } catch (err) {
        return toast(err.message, "err");
      }
      if (!validateSleepTime(values["human_memory.sleep.time"])) {
        return toast("睡眠时间必须是 HH:MM", "err");
      }
      const twoStageBounds = {
        "recall_engine.two_stage_candidates": [1, 200],
        "recall_engine.two_stage_vector_weight": [0, 1],
        "recall_engine.two_stage_fuzzy_weight": [0, 1],
        "recall_engine.two_stage_vector_k": [1, 8192],
      };
      for (const [path, [min, max]] of Object.entries(twoStageBounds)) {
        if (!(path in values)) continue;
        if (values[path] < min || values[path] > max) {
          return toast(`${path} 必须在 ${min}-${max} 之间`, "err");
        }
      }
      try {
        await request(inst, "/config", { method: "PUT", body: { values } });
        toast("记忆参数已保存");
        await loadStatus();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function loadBackfillPreview() {
      const inst = instance();
      if (!inst) return;
      const box = root && root.querySelector("#backfill-live");
      if (box) box.innerHTML = `<div class="memory-live">加载回填预览…</div>`;
      try {
        backfillPreview = await request(inst, "/backfill/preview");
        if (box) box.innerHTML = `<div class="memory-live">缺失类型 ${backfillPreview.type_missing ?? 0} 条 · 缺失唤醒度 ${backfillPreview.arousal_missing ?? 0} 条 · 预计 ${backfillPreview.estimated_batches ?? 0} 批</div>`;
        toast("回填预览已加载");
      } catch (err) {
        if (box) box.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div></div>`;
      }
    }

    async function runBackfill() {
      const inst = instance();
      if (!inst) return;
      const ok = await confirmDialog("开始显著性回填", "只补类型、arousal 和显著原因，不改正文和重要性。会调用模型，建议先预览。确定继续？", false);
      if (!ok) return;
      try {
        await request(inst, "/backfill/run", { method: "POST" });
        toast("回填任务已启动");
        pollBackfill();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function cancelBackfill() {
      const inst = instance();
      if (!inst) return;
      try {
        await request(inst, "/backfill/cancel", { method: "POST" });
        toast("已请求取消，当前批次结束后停止");
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function pollBackfill() {
      clearTimers();
      const inst = instance();
      if (!inst) return;
      const tick = async () => {
        try {
          const status = await request(inst, "/backfill/status");
          const box = root && root.querySelector("#backfill-live");
          if (box) box.innerHTML = `<div class="memory-live">${status.status === "running" ? "回填中" : "回填结束"} · ${status.done ?? 0} / ${status.total ?? "—"} · 更新 ${status.updated ?? 0} · 失败 ${status.failed ?? 0}</div>`;
          if (status.status !== "running") {
            clearTimers();
            await loadStatus();
          }
        } catch (err) {
          clearTimers();
          const box = root && root.querySelector("#backfill-live");
          if (box) box.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div></div>`;
        }
      };
      tick();
      rememberTimer(setInterval(tick, 2000));
    }

    /* ------------------------------------------------------------- recall */

    function renderRecall(pane) {
      pane.innerHTML = `
        <section class="card memory-filter-card">
          <div class="memory-recall-form">
            <label>查询<input data-recall="query" placeholder="例如：我之前说过搬到哪"></label>
            <label>条数<input data-recall="k" type="number" min="1" max="50" value="5"></label>
            <label>会话<input data-recall="session_id" placeholder="可选"></label>
            <label>人物身份<input data-recall="person_identity" placeholder="如 aiocqhttp:10003"></label>
            <label>场景<select data-recall="scene">
              <option value="">按会话推断</option>
              <option value="group">群聊</option>
              <option value="private">私聊</option>
            </select></label>
            <button class="btn primary" data-recall-run>${icon("search")}召回</button>
          </div>
          <div class="console-help">只做检索和注入预览，不写回、不影响真实对话。</div>
        </section>
        <div id="recall-result"><div class="memory-empty-inline">输入一句话查看命中原因和注入文本。</div></div>
        <section class="card memory-active-card">
          <div class="memory-section-head">
            <div>
              <div class="console-kicker">ACTIVE RECALL</div>
              <h3>主动回忆</h3>
              <p class="console-help">只在现有召回结果中筛选，模拟聊天时自然想起旧记忆；默认关闭且默认影子，不额外调用模型，不发送主动消息。</p>
            </div>
            <div class="console-actions memory-actions">
              <span class="memory-readonly" data-active-mode>读取中…</span>
              <button class="btn sm ghost" data-active-refresh>${icon("refresh")}刷新</button>
            </div>
          </div>
          <div id="active-status"><div class="skeleton" style="height:90px"></div></div>
          <div id="active-config-form" class="memory-form-grid">加载中…</div>
          <div class="console-help">真实模式 = 开启主动回忆且关闭影子模式；保存前会再次确认。默认关闭，默认影子。</div>
          <div class="console-actions memory-actions">
            <button class="btn primary" data-active-save>保存主动回忆参数</button>
          </div>
          <div class="console-help">真实模式只在当前对话的正常回复里追加一段内部提示，不会主动私聊、群发或定时打扰。建议先看影子日志，再开启真实模式；群聊默认关闭。</div>
          <div class="memory-active-preview">
            <div class="memory-active-preview-form">
              <label>补忆测试语句<input data-active-query placeholder="例如：我之前说过搬到哪"></label>
              <label>会话<input data-active-session placeholder="可选"></label>
              <button class="btn ghost" data-active-preview>${icon("search")}补忆预览</button>
            </div>
            <div id="active-preview-result"><div class="memory-empty-inline">补忆预览只读：不写事件、不注入，也不改变任何回复。</div></div>
          </div>
        </section>
        <section class="card memory-active-events-card">
          <div class="console-card-head">
            <h3>影子 / 真实事件</h3>
            <div class="memory-active-event-tools">
              <select data-active-filter>
                <option value="all"${activeEventFilter === "all" ? " selected" : ""}>全部事件</option>
                <option value="shadow"${activeEventFilter === "shadow" ? " selected" : ""}>只看影子</option>
                <option value="real"${activeEventFilter === "real" ? " selected" : ""}>只看真实</option>
              </select>
              <span class="side" data-active-event-count></span>
            </div>
          </div>
          <div id="active-events"><div class="skeleton" style="height:120px"></div></div>
        </section>`;
      pane.querySelector("[data-recall-run]").addEventListener("click", runRecall);
      pane.querySelectorAll("[data-recall]").forEach((node) => node.addEventListener("keydown", (event) => {
        if (event.key === "Enter") runRecall();
      }));
      pane.querySelector("[data-active-refresh]").addEventListener("click", () => loadActiveRecall());
      pane.querySelector("[data-active-save]").addEventListener("click", () => saveActiveRecallConfig(pane));
      pane.querySelector("[data-active-preview]").addEventListener("click", () => runActivePreview());
      pane.querySelectorAll("[data-active-query], [data-active-session]").forEach((node) =>
        node.addEventListener("keydown", (event) => {
          if (event.key === "Enter") runActivePreview();
        })
      );
      pane.querySelector("[data-active-filter]").addEventListener("change", (event) => {
        activeEventFilter = event.target.value;
        renderActiveEvents();
      });
      loadActiveRecall();
    }

    async function loadActiveRecall() {
      const inst = instance();
      if (!inst) return;
      await Promise.all([loadActiveStatus(), loadActiveEvents(), loadActiveConfig()]);
    }

    async function loadActiveStatus() {
      const inst = instance();
      if (!inst) return;
      const box = root && root.querySelector("#active-status");
      try {
        activeStatus = await request(inst, "/active-recall/status");
        activeStatusError = "";
      } catch (err) {
        activeStatus = null;
        activeStatusError = err.message;
      }
      renderActiveStatus(box);
    }

    function renderActiveStatus(box) {
      const target = box || (root && root.querySelector("#active-status"));
      if (!target) return;
      const modeLabel = activeStatusError ? "读取失败" : activeRecallModeLabel(activeStatus);
      const chip = root && root.querySelector("[data-active-mode]");
      if (chip) {
        chip.textContent = `当前：${modeLabel}`;
        chip.classList.toggle("real", activeRecallMode(activeStatus) === "real");
      }
      if (activeStatusError) {
        target.innerHTML = `<div class="console-warn"><div>主动回忆状态读取失败：${esc(activeStatusError)}</div><button class="btn sm ghost" data-active-status-retry>重试</button></div>`;
        const retry = target.querySelector("[data-active-status-retry]");
        if (retry) retry.addEventListener("click", () => loadActiveStatus());
        return;
      }
      if (!activeStatus) {
        target.innerHTML = `<div class="skeleton" style="height:90px"></div>`;
        return;
      }
      const status = activeStatus;
      const mode = activeRecallMode(status);
      const dailyLimit = Number(status.daily_limit) || 0;
      target.innerHTML = `<div class="memory-active-mode ${esc(mode)}">
          <b>${esc(activeRecallModeLabel(status))}</b>
          <span>今日影子 ${Number(status.shadow_events_today) || 0} 条 · 今日真实 ${Number(status.real_events_today) || 0} / ${esc(String(dailyLimit))} · 今日剩余 ${Number(status.daily_remaining) || 0}</span>
        </div>
        <div class="memory-kv">
          <div><span>最低分数</span><b>${esc(fmtScore(status.min_score))}</b></div>
          <div><span>每日真实上限</span><b>${esc(String(dailyLimit))}</b></div>
          <div><span>冷却</span><b>${esc(String(Number(status.cooldown_minutes) || 0))} 分钟</b></div>
          <div><span>每次最多</span><b>${esc(String(Number(status.max_memories) || 0))} 条</b></div>
          <div><span>私聊 / 群聊</span><b>${status.allow_private ? "开" : "关"} / ${status.allow_group ? "开" : "关"}</b></div>
          <div><span>最近事件</span><b>${esc(formatTime(status.last_event_at))}</b></div>
          <div><span>事件文件</span><b title="${esc(status.events_path || "")}">${esc(truncate(status.events_path || "—", 80))}</b></div>
        </div>
        ${mode === "real"
          ? `<div class="console-warn"><div>真实模式已开启：只影响当前对话的正常回复，不会发送主动消息、不私聊、不群发。</div></div>`
          : mode === "shadow"
            ? `<div class="console-help">影子模式：只写事件日志，不改变回复。看完影子日志并确认稳定后，再关闭影子模式开启真实模式。</div>`
            : `<div class="console-help">主动回忆默认关闭。开启后先运行在影子模式，确认无误后再考虑真实模式。</div>`}`;
    }

    async function loadActiveEvents() {
      const inst = instance();
      if (!inst || activeEventsBusy) return;
      activeEventsBusy = true;
      const box = root && root.querySelector("#active-events");
      if (!box) {
        activeEventsBusy = false;
        return;
      }
      box.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
      try {
        const data = await request(inst, "/active-recall/events?limit=50");
        activeEvents = Array.isArray(data.items) ? data.items : [];
        activeEventsError = "";
      } catch (err) {
        activeEvents = [];
        activeEventsError = err.message;
      } finally {
        activeEventsBusy = false;
      }
      renderActiveEvents();
    }

    function renderActiveEvents() {
      const box = root && root.querySelector("#active-events");
      const count = root && root.querySelector("[data-active-event-count]");
      if (!box) return;
      if (activeEventsError) {
        box.innerHTML = `<div class="console-warn"><div>主动回忆事件读取失败：${esc(activeEventsError)}</div><button class="btn sm ghost" data-active-events-retry>重试</button></div>`;
        const retry = box.querySelector("[data-active-events-retry]");
        if (retry) retry.addEventListener("click", () => loadActiveEvents());
        return;
      }
      const filtered = activeEventFilter === "all"
        ? activeEvents
        : activeEvents.filter((event) => String(event.mode || "") === activeEventFilter);
      if (count) count.textContent = `${filtered.length} / ${activeEvents.length} 条`;
      if (!filtered.length) {
        box.innerHTML = `<div class="memory-empty-inline">${activeEvents.length
          ? "当前筛选条件下没有事件。"
          : "还没有主动回忆事件。开启影子模式并在聊天中触发召回后，这里会出现记录。"}</div>`;
        return;
      }
      box.innerHTML = `<div class="memory-table-wrap"><table class="table memory-table memory-active-events">
        <thead><tr><th>时间</th><th>模式</th><th>会话 / 人物</th><th>平台</th><th>记忆</th><th>最高分</th><th>状态</th></tr></thead>
        <tbody>${filtered.map((event) => {
          const mode = String(event.mode || "shadow") === "real" ? "real" : "shadow";
          const ids = Array.isArray(event.memory_ids) ? event.memory_ids : [];
          return `<tr>
            <td class="mono">${esc(formatTime(event.created_at))}</td>
            <td><span class="memory-mode ${mode}">${mode === "real" ? "真实" : "影子"}</span></td>
            <td><div class="memory-event-scope"><span>${esc(truncate(event.session_id || "—", 38))}</span><span>${esc(event.person_id || "—")}</span></div></td>
            <td>${esc(event.platform || "—")}${event.is_group ? " · 群聊" : " · 私聊"}</td>
            <td>${ids.length ? ids.map((id) => `<button type="button" class="memory-dream-chip" data-event-memory="${esc(id)}">${esc(shortId(id))}</button>`).join("") : "—"}</td>
            <td class="mono">${esc(fmtScore(event.top_score))}</td>
            <td><span class="memory-mode ${event.injected ? "real" : "shadow"}">${event.injected ? "已注入" : mode === "shadow" ? "影子记录" : "未注入"}</span></td>
          </tr>`;
        }).join("")}</tbody></table></div>`;
      box.querySelectorAll("[data-event-memory]").forEach((node) => {
        node.addEventListener("click", () => openDetail(node.dataset.eventMemory));
      });
    }

    async function loadActiveConfig() {
      const inst = instance();
      if (!inst) return;
      const box = root && root.querySelector("#active-config-form");
      if (!box) return;
      if (!helperConfig) {
        try {
          helperConfig = await request(inst, "/config");
          helperConfigError = "";
        } catch (err) {
          helperConfigError = err.message;
        }
      }
      renderActiveConfig();
    }

    function renderActiveConfig() {
      const box = root && root.querySelector("#active-config-form");
      if (!box) return;
      if (!helperConfig) {
        box.innerHTML = `<div class="console-warn"><div>读取主动回忆参数失败：${esc(helperConfigError || "配置不可用")}</div></div>`;
        return;
      }
      box.innerHTML = [
        boolField("human_memory.active_recall.enabled", "启用主动回忆", "默认关闭；开启后先运行在影子模式。"),
        boolField("human_memory.active_recall.shadow", "影子模式", "默认开；只写事件日志，不改变回复。关闭后才是真实模式。", true),
        numberField("human_memory.active_recall.min_score", "最低召回分数", "0–1，默认 0.6", "0.01", 0.6),
        numberField("human_memory.active_recall.daily_limit", "每日真实注入上限", "只统计真实注入事件，默认 3", "1", 3),
        numberField("human_memory.active_recall.cooldown_minutes", "冷却（分钟）", "同会话或同人物的最小间隔，默认 60", "1", 60),
        numberField("human_memory.active_recall.max_memories", "每次最多记忆数", "默认 2", "1", 2),
        boolField("human_memory.active_recall.allow_private", "允许私聊", "默认开", true),
        boolField("human_memory.active_recall.allow_group", "允许群聊", "默认关；群聊不会引用其他私聊记忆。"),
      ].join("");
    }

    async function saveActiveRecallConfig(pane) {
      const inst = instance();
      if (!inst) return;
      const scope = pane || (root && root.querySelector("#mem-pane"));
      if (!scope) return;
      let values = {};
      try {
        values = collectConfigValues(scope.querySelectorAll("[data-cfg]"));
      } catch (err) {
        return toast(err.message, "err");
      }
      const realAfter =
        values["human_memory.active_recall.enabled"] === true &&
        values["human_memory.active_recall.shadow"] === false;
      const realBefore = Boolean(activeStatus && activeStatus.enabled && !activeStatus.shadow);
      if (realAfter && !realBefore) {
        const ok = await confirmDialog(
          "开启主动回忆真实模式",
          "真实模式只会在当前对话的正常回复里追加一段内部提示，让回复更自然地提起旧记忆；不会发送主动消息，不私聊、不群发、不定时打扰。建议先查看影子日志。确定继续？",
          false
        );
        if (!ok) return;
      }
      try {
        await request(inst, "/config", { method: "PUT", body: { values } });
        toast(realAfter ? "主动回忆参数已保存（真实模式）" : "主动回忆参数已保存");
        await loadActiveStatus();
        await loadActiveEvents();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function runActivePreview() {
      const inst = instance();
      if (!inst || activePreviewBusy) return;
      const queryNode = root && root.querySelector("[data-active-query]");
      const sessionNode = root && root.querySelector("[data-active-session]");
      const box = root && root.querySelector("#active-preview-result");
      if (!queryNode || !box) return;
      const query = queryNode.value.trim();
      if (!query) return toast("请输入要测试的语句", "err");
      const sessionId = sessionNode ? sessionNode.value.trim() : "";
      activePreviewBusy = true;
      box.innerHTML = `<div class="skeleton" style="height:100px"></div>`;
      try {
        const body = { query };
        if (sessionId) body.session_id = sessionId;
        activePreviewData = await request(inst, "/active-recall/preview", {
          method: "POST",
          body,
        });
        renderActivePreview();
      } catch (err) {
        activePreviewData = null;
        box.innerHTML = `<div class="console-warn"><div>补忆预览失败：${esc(err.message)}</div></div>`;
      } finally {
        activePreviewBusy = false;
      }
    }

    function renderActivePreview() {
      const box = root && root.querySelector("#active-preview-result");
      if (!box || !activePreviewData) return;
      const data = activePreviewData;
      const selected = Array.isArray(data.selected) ? data.selected : [];
      const mode = activeRecallMode(data);
      const blocked = activeRecallBlockedLabel(data.blocked_reason);
      box.innerHTML = `<div class="memory-active-preview-result">
        <div class="memory-kv">
          <div><span>模式</span><b>${esc(activeRecallModeLabel(data))}</b></div>
          <div><span>候选</span><b>${Number(data.candidates) || 0} 条</b></div>
          <div><span>选中</span><b>${selected.length} 条</b></div>
          <div><span>会注入</span><b>${data.would_inject ? "是（仅本轮回复）" : "否"}</b></div>
          <div><span>阻止原因</span><b>${esc(blocked || "—")}</b></div>
        </div>
        ${selected.length ? `<div class="memory-table-wrap"><table class="table memory-table">
          <thead><tr><th>记忆</th><th>分数</th><th>摘要</th><th>原因</th></tr></thead>
          <tbody>${selected.map((item) => `<tr>
            <td class="mono">${esc(shortId(item.memory_id))}</td>
            <td class="mono">${esc(fmtScore(item.score))}</td>
            <td>${esc(truncate(item.summary || "—", 100))}</td>
            <td>${esc(item.reason || "—")}</td>
          </tr>`).join("")}</tbody></table></div>` : ""}
        ${data.prompt ? `<div class="memory-dream-box" style="margin-top:10px"><div class="memory-dream-kicker">真实模式下会追加的内部提示（预览）</div><pre class="memory-pre">${esc(data.prompt)}</pre></div>` : ""}
        <div class="console-help">补忆预览是只读的：不会写入主动回忆事件，不会注入，也不会改变回复。${mode === "real" ? "当前为真实模式，实际聊天中会受冷却和日限约束。" : ""}</div>
      </div>`;
    }

    async function runRecall() {
      const inst = instance();
      if (!inst || recallBusy) return;
      const box = root && root.querySelector("#recall-result");
      const query = root.querySelector('[data-recall="query"]').value.trim();
      if (!query) return toast("请输入查询内容", "err");
      const k = Number(root.querySelector('[data-recall="k"]').value) || 5;
      const sessionId = root.querySelector('[data-recall="session_id"]').value.trim();
      const personIdentity = root.querySelector('[data-recall="person_identity"]').value.trim();
      const scene = root.querySelector('[data-recall="scene"]').value;
      const body = { query, k, session_id: sessionId || null };
      if (personIdentity) body.person_identity = personIdentity;
      if (scene === "group") body.is_private = false;
      else if (scene === "private") body.is_private = true;
      recallBusy = true;
      if (box) box.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
      try {
        recallData = await request(inst, "/recall", {
          method: "POST",
          body,
        });
        renderRecallResult();
      } catch (err) {
        if (box) box.innerHTML = `<div class="console-warn"><div>${esc(err.message)}</div></div>`;
      } finally {
        recallBusy = false;
      }
    }

    function renderRecallResult() {
      const box = root && root.querySelector("#recall-result");
      if (!box || !recallData) return;
      const results = recallData.results || [];
      if (!results.length) {
        box.innerHTML = `<div class="empty">${icon("search")}<h4>没有命中</h4><p>换关键词或检查召回开关。</p></div>`;
        return;
      }
      box.innerHTML = `<div class="memory-recall-list">${results.map((item, index) => {
        const rows = scoreRows(item.score_breakdown || {})
          .filter((row) => row.key !== "cross_context");
        const cross = Boolean(item.metadata?.cross_context);
        return `<section class="card memory-recall-card">
          <div class="memory-recall-head"><b>${index + 1}. ${esc(truncate(item.content, 110))}</b><span class="mono">${esc(fmtScore(item.similarity_score))}</span></div>
          ${cross ? `<div class="memory-recall-meta">跨会话记忆 · 来自 ${esc(item.metadata?.session_id || "其他会话")}</div>` : ""}
          <div class="memory-score-bars">${rows.map((row) =>
            `<div><span>${esc(row.key)}</span><div class="memory-bar"><i style="width:${row.percent}%"></i></div><em>${esc(scoreDisplay(row.key, row.value))}</em></div>`
          ).join("") || `<div class="memory-empty-inline">无分数拆解</div>`}</div>
          <div class="memory-recall-meta">重要 ${esc(importanceLabel(item.metadata?.importance))} · 唤醒 ${esc(fmtArousal(item.metadata?.arousal))} · ${esc(item.metadata?.status || "active")}</div>
        </section>`;
      }).join("")}</div>
      <section class="card memory-injection-card"><div class="console-card-head"><h3>注入给模型的文本</h3><span>${esc(String(recallData.elapsed_time_ms || 0))} ms</span></div><pre class="memory-pre">${esc(recallData.injection_preview || "（无注入内容）")}</pre></section>`;
    }

    /* -------------------------------------------------------------- vector */

    function vectorKindLabel(kind) {
      return ({
        embedding: "嵌入",
        batch: "批量嵌入",
        probe: "探针",
        recall: "召回",
      })[kind] || kind || "—";
    }

    function renderVector(pane) {
      pane.innerHTML = `
        <section class="card memory-vector-hero">
          <div class="console-card-head">
            <div>
              <div class="console-kicker">VECTOR MODEL</div>
              <h3>向量模型</h3>
              <p class="console-help">实时监控 Embedding 请求、延迟、错误、FAISS 索引和召回事件；每 2 秒刷新一次。</p>
            </div>
            <div class="console-actions memory-actions">
              <span class="badge" data-vector-live-chip>实时</span>
              <button class="btn sm ghost" data-vector-live>暂停</button>
              <button class="btn sm ghost" data-vector-probe>${icon("pulse")}探针</button>
              <button class="btn sm ghost" data-vector-refresh>${icon("refresh")}刷新</button>
            </div>
          </div>
          <div id="vector-overview" class="stat-grid memory-health"></div>
        </section>
        <div class="memory-vector-grid">
          <section class="card">
            <div class="console-card-head"><h3>近 5 分钟延迟</h3><span class="side">最近 40 次</span></div>
            <div id="vector-latency" class="memory-vector-spark"></div>
          </section>
          <section class="card">
            <div class="console-card-head"><h3>最近嵌入事件</h3><span class="side">最多 20 条</span></div>
            <div id="vector-events"></div>
          </section>
        </div>
        <section class="card" style="margin-top:16px">
          <div class="console-card-head"><h3>最近找到的东西</h3><span class="side">真实召回查询与命中记忆</span></div>
          <div class="memory-recall-form">
            <label>找记忆<input data-vector-find-query placeholder="例如：之前说过的显卡和模型"></label>
            <label>条数<input data-vector-find-k type="number" min="1" max="20" value="5"></label>
            <button class="btn primary" data-vector-find>${icon("search")}找一下</button>
          </div>
          <div id="vector-found-results"><div class="memory-empty-inline">输入一句话，用当前向量模型找记忆；只读，不写回。</div></div>
          <div id="vector-recall-events" style="margin-top:12px"></div>
        </section>
        <section class="card" style="margin-top:16px">
          <div class="console-card-head"><h3>召回参数</h3><span class="side">保存后立即生效</span></div>
          <div id="vector-config" class="memory-form-grid">
            <div class="skeleton" style="height:80px;grid-column:1/-1"></div>
          </div>
          <div class="console-actions memory-actions">
            <button class="btn primary" data-vector-save>保存召回参数</button>
          </div>
        </section>
        <section class="card" style="margin-top:16px">
          <div class="console-card-head">
            <h3>索引重建</h3>
            <span class="side">只读 documents 源，失败不会删除原文</span>
          </div>
          <div id="vector-rebuild"></div>
          <div class="console-actions memory-actions">
            <button class="btn danger" data-vector-rebuild>重建向量索引</button>
          </div>
        </section>`;
      pane.querySelector("[data-vector-refresh]").addEventListener("click", () => loadVector(false));
      pane.querySelector("[data-vector-live]").addEventListener("click", () => {
        vectorLive = !vectorLive;
        const chip = pane.querySelector("[data-vector-live-chip]");
        const button = pane.querySelector("[data-vector-live]");
        if (chip) chip.textContent = vectorLive ? "实时" : "已暂停";
        if (button) button.textContent = vectorLive ? "暂停" : "继续";
      });
      pane.querySelector("[data-vector-probe]").addEventListener("click", probeVector);
      pane.querySelector("[data-vector-find]").addEventListener("click", runVectorFind);
      pane.querySelectorAll("[data-vector-find-query], [data-vector-find-k]").forEach((node) =>
        node.addEventListener("keydown", (event) => {
          if (event.key === "Enter") runVectorFind();
        }));
      pane.querySelector("[data-vector-save]").addEventListener("click", saveVectorConfig);
      pane.querySelector("[data-vector-rebuild]").addEventListener("click", rebuildVector);
      vectorConfigLoaded = false;
      if (vectorTimer) clearInterval(vectorTimer);
      vectorTimer = rememberTimer(setInterval(() => {
        if (!root || activeTab !== "vector" || !vectorLive) return;
        loadVector(false);
      }, 2000));
      loadVector(true);
    }

    async function loadVector(loadConfig) {
      const inst = instance();
      if (!inst || vectorBusy) return;
      try {
        const data = await request(inst, "/vector/status");
        vectorStatus = data;
        vectorError = "";
        if (loadConfig && !vectorConfigLoaded) fillVectorConfig(data);
      } catch (err) {
        vectorError = err.message;
      }
      renderVectorStatus();
    }

    function fillVectorConfig(data) {
      const box = root && root.querySelector("#vector-config");
      if (!box) return;
      const cfg = (data && data.recall_engine) || {};
      const bool = (key, label, hint, fallback) => `
        <label class="memory-config-field"><span>${esc(label)}</span>
          <input type="checkbox" data-vector-cfg="${key}" ${(cfg[key] ?? fallback) ? "checked" : ""}>
          <small>${esc(hint)}</small>
        </label>`;
      const num = (key, label, hint, step, fallback, min, max) => {
        const raw = cfg[key] ?? fallback;
        const value = typeof raw === "number" && !Number.isInteger(raw)
          ? raw.toFixed(2)
          : raw;
        return `
        <label class="memory-config-field"><span>${esc(label)}</span>
          <input type="number" step="${step}" min="${min}" max="${max}" data-vector-cfg="${key}" value="${esc(value)}">
          <small>${esc(hint)}</small>
        </label>`;
      };
      box.innerHTML = [
        bool("two_stage_enabled", "启用两段式向量召回", "模糊定位后向量精排，失败回退混合检索", true),
        num("two_stage_candidates", "模糊候选数", "进入向量精排的候选条数", "1", 30, 1, 200),
        num("two_stage_vector_weight", "向量权重", "精排分权重", "0.01", 0.6, 0, 1),
        num("two_stage_fuzzy_weight", "模糊权重", "候选分权重", "0.01", 0.4, 0, 1),
        num("two_stage_vector_k", "向量查询上限", "FAISS kNN 上限", "1", 8192, 1, 8192),
        bool("cross_context_enabled", "跨会话记忆", "同一人的私聊/群聊记忆参与召回", true),
        num("cross_context_limit", "跨会话条数", "最多补充几条其他会话记忆", "1", 3, 1, 10),
        bool("cross_context_private_to_group", "私聊→群聊", "群里 @ 时参考这个人的私聊记忆（内部参考）", true),
        bool("cross_context_group_to_private", "群聊→私聊", "私聊时参考这个人在群里的记忆", true),
      ].join("");
      vectorConfigLoaded = true;
    }

    function renderVectorStatus() {
      if (!root || activeTab !== "vector") return;
      const overview = root.querySelector("#vector-overview");
      if (!overview) return;
      if (vectorError) {
        overview.innerHTML = `<div class="console-warn" style="grid-column:1/-1"><div>向量状态读取失败：${esc(vectorError)}</div></div>`;
      } else if (!vectorStatus) {
        overview.innerHTML = `<div class="skeleton" style="height:80px;grid-column:1/-1"></div>`;
        return;
      } else {
        const p = vectorStatus.provider || {};
        const idx = vectorStatus.index || {};
        const m = vectorStatus.metrics || {};
        overview.innerHTML = [
          statCard("Provider", p.ready ? "就绪" : "未就绪", p.id || "未配置"),
          statCard("模型", p.model || "—", p.api_base || "未读取到地址"),
          statCard("向量维度", p.dimension || idx.dimension || "—", "Embedding 输出"),
          statCard("索引向量", idx.vectors ?? "—", "FAISS 当前条数"),
          statCard("5 分钟请求", m.requests || 0, `错误 ${m.errors || 0}`),
          statCard("运行中", m.active || 0, `峰值 ${m.peak_active || 0}`),
          statCard("吞吐", `${m.rpm || 0}/分`, "最近 1 分钟"),
          statCard("P50 / P95", `${m.p50_ms || 0} / ${m.p95_ms || 0} ms`, `P99 ${m.p99_ms || 0} ms`),
        ].join("");
      }
      renderVectorLatency();
      renderVectorEvents();
      renderVectorRecallEvents();
      renderVectorRebuild();
    }

    function vectorSmoothPath(points) {
      if (!points.length) return "";
      if (points.length === 1) {
        return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)} l 0.1 0`;
      }
      let path = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
      for (let index = 0; index < points.length - 1; index += 1) {
        const p0 = points[index - 1] || points[index];
        const p1 = points[index];
        const p2 = points[index + 1];
        const p3 = points[index + 2] || p2;
        const c1x = p1.x + (p2.x - p0.x) / 6;
        const c1y = p1.y + (p2.y - p0.y) / 6;
        const c2x = p2.x - (p3.x - p1.x) / 6;
        const c2y = p2.y - (p3.y - p1.y) / 6;
        path += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
      }
      return path;
    }

    function renderVectorLatency() {
      const box = root && root.querySelector("#vector-latency");
      if (!box) return;
      const events = ((vectorStatus && vectorStatus.metrics && vectorStatus.metrics.events) || [])
        .filter((event) => event.kind !== "recall").slice(-40);
      if (!events.length) {
        box.innerHTML = `<div class="memory-empty-inline">还没有 Embedding 请求，发一条聊天或点「探针」。</div>`;
        return;
      }
      const width = 760;
      const height = 218;
      const pad = { left: 48, right: 20, top: 16, bottom: 30 };
      const max = Math.max(10, ...events.map((event) => Number(event.ms) || 0));
      const step = Math.ceil(max / 4 / 10) * 10;
      const top = step * 4;
      const innerW = width - pad.left - pad.right;
      const innerH = height - pad.top - pad.bottom;
      const points = events.map((event, index) => {
        const x = events.length === 1
          ? pad.left + innerW / 2
          : pad.left + (index * innerW) / (events.length - 1);
        const ms = Number(event.ms) || 0;
        const y = pad.top + innerH * (1 - Math.min(1, ms / top));
        return { x, y, event, ms };
      });
      const linePath = vectorSmoothPath(points);
      const areaPath = `${linePath} L ${points.at(-1).x.toFixed(1)} ${(height - pad.bottom).toFixed(1)} L ${points[0].x.toFixed(1)} ${(height - pad.bottom).toFixed(1)} Z`;
      const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const y = pad.top + innerH * (1 - ratio);
        return `<line class="memory-vector-gridline" x1="${pad.left}" x2="${width - pad.right}" y1="${y}" y2="${y}"></line>
          <text x="${pad.left - 8}" y="${y + 3}" text-anchor="end">${Math.round(top * ratio)}ms</text>`;
      }).join("");
      const ticks = [0, 0.5, 1].map((ratio) => {
        const index = Math.round((events.length - 1) * ratio);
        const event = events[index];
        const x = points[index].x;
        return `<text x="${x}" y="${height - 8}" text-anchor="${ratio === 0 ? "start" : ratio === 1 ? "end" : "middle"}">${esc(new Date(event.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }))}</text>`;
      }).join("");
      const dots = points.map((point, index) => `<circle class="memory-vector-dot ${point.event.ok ? "" : "bad"}" data-vector-point="${index}" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="3.2"></circle>`).join("");
      const avg = events.reduce((sum, event) => sum + (Number(event.ms) || 0), 0) / events.length;
      const slow = [...events].sort((a, b) => (Number(b.ms) || 0) - (Number(a.ms) || 0)).slice(0, 3);
      const buckets = [
        { label: "0–100 ms", min: 0, max: 100 },
        { label: "100–200 ms", min: 100, max: 200 },
        { label: "200–400 ms", min: 200, max: 400 },
        { label: "400+ ms", min: 400, max: Infinity },
      ].map((bucket) => ({
        ...bucket,
        count: events.filter((event) => {
          const ms = Number(event.ms) || 0;
          return ms >= bucket.min && ms < bucket.max;
        }).length,
      }));
      const bucketMax = Math.max(1, ...buckets.map((bucket) => bucket.count));
      box.innerHTML = `
        <div class="memory-vector-chart-meta">
          <span>最近 <b>${events.length}</b> 次</span>
          <span>平均 <b>${avg.toFixed(1)} ms</b></span>
          <span>峰值 <b>${Math.max(...events.map((event) => Number(event.ms) || 0)).toFixed(1)} ms</b></span>
        </div>
        <div class="memory-vector-chart-wrap">
          <svg class="memory-vector-wave" viewBox="0 0 ${width} ${height}" role="img" aria-label="近 5 分钟 Embedding 延迟波形">
            ${grid}
            <path class="memory-vector-area" d="${areaPath}"></path>
            <path class="memory-vector-line" d="${linePath}"></path>
            ${dots}
            ${ticks}
          </svg>
          <div class="memory-vector-tooltip" hidden></div>
        </div>
        <div class="memory-vector-legend">
          <span><i class="memory-vector-legend-dot"></i>嵌入请求</span>
          <span><i class="memory-vector-legend-dot bad"></i>失败</span>
          <span>悬浮数据点查看详情</span>
        </div>
        <div class="memory-vector-detail">
          <div class="memory-vector-buckets">
            <div class="memory-vector-detail-title">延迟分布</div>
            ${buckets.map((bucket) => `<div class="memory-vector-bucket">
              <span>${esc(bucket.label)}</span>
              <div class="memory-bar"><i style="width:${Math.round(bucket.count / bucketMax * 100)}%"></i></div>
              <em>${bucket.count}</em>
            </div>`).join("")}
          </div>
          <div class="memory-vector-slow">
            <div class="memory-vector-detail-title">最慢请求</div>
            ${slow.map((event) => `<div class="memory-vector-slow-row">
              <span>${esc(new Date(event.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }))}</span>
              <span>${esc(vectorKindLabel(event.kind))}</span>
              <b>${esc(String(event.ms))} ms</b>
            </div>`).join("")}
          </div>
        </div>`;
      const svg = box.querySelector(".memory-vector-wave");
      const tip = box.querySelector(".memory-vector-tooltip");
      if (svg && tip) {
        svg.addEventListener("mousemove", (event) => {
          const rect = svg.getBoundingClientRect();
          const scale = width / rect.width;
          const x = (event.clientX - rect.left) * scale;
          let nearest = points[0];
          for (const point of points) {
            if (Math.abs(point.x - x) < Math.abs(nearest.x - x)) nearest = point;
          }
          const info = nearest.event;
          const left = Math.max(8, Math.min(rect.width - 8, (nearest.x / width) * rect.width));
          const topPx = Math.max(8, Math.min(rect.height - 8, (nearest.y / height) * rect.height));
          tip.innerHTML = `<b>${esc(String(info.ms))} ms</b><span>${esc(vectorKindLabel(info.kind))} · ${esc(String(info.chars || 0))} 字符</span><span>${esc(new Date(info.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }))}</span>${info.ok ? "" : `<span class="bad">${esc(info.error || "失败")}</span>`}`;
          tip.style.left = `${left}px`;
          tip.style.top = `${topPx}px`;
          tip.hidden = false;
          svg.querySelectorAll("[data-vector-point]").forEach((node) => node.classList.toggle("active", node.dataset.vectorPoint === String(points.indexOf(nearest))));
        });
        svg.addEventListener("mouseleave", () => {
          tip.hidden = true;
          svg.querySelectorAll("[data-vector-point]").forEach((node) => node.classList.remove("active"));
        });
      }
    }

    function renderVectorEvents() {
      const box = root && root.querySelector("#vector-events");
      if (!box) return;
      const events = ((vectorStatus && vectorStatus.metrics && vectorStatus.metrics.events) || [])
        .filter((event) => event.kind !== "recall").slice(-20).reverse();
      if (!events.length) {
        box.innerHTML = `<div class="memory-empty-inline">暂无嵌入请求。</div>`;
        return;
      }
      box.innerHTML = `<div class="memory-table-wrap"><table class="table memory-table">
        <thead><tr><th>时间</th><th>类型</th><th>耗时</th><th>字符</th><th>结果</th></tr></thead>
        <tbody>${events.map((event) => `<tr>
          <td class="mono">${esc(formatTime(event.ts))}</td>
          <td>${esc(vectorKindLabel(event.kind))}</td>
          <td class="mono">${esc(String(event.ms))} ms</td>
          <td class="mono">${esc(String(event.chars || 0))}</td>
          <td>${event.ok ? `<span class="badge ok">成功</span>` : `<span class="badge bad" title="${esc(event.error || "")}">失败</span>`}</td>
        </tr>`).join("")}</tbody>
      </table></div>`;
    }

    function vectorFoundCards(found) {
      const items = Array.isArray(found) ? found : [];
      if (!items.length) {
        return `<div class="memory-empty-inline">本次没有命中记忆。</div>`;
      }
      return `<div class="memory-recall-list">${items.map((item) => {
        const score = Number(item.score);
        const vectorScore = item.vector_score === null || item.vector_score === undefined
          ? "—" : fmtScore(item.vector_score);
        const fuzzyScore = item.fuzzy_score === null || item.fuzzy_score === undefined
          ? "—" : fmtScore(item.fuzzy_score);
        return `<section class="card memory-recall-card">
          <div class="memory-recall-head"><b>#${esc(String(item.id ?? "—"))} ${esc(truncate(item.content || "", 120))}</b><span class="mono">${Number.isFinite(score) ? fmtScore(score) : "—"}</span></div>
          <div class="memory-recall-meta">向量 ${esc(vectorScore)} · 模糊 ${esc(fuzzyScore)} · 重要 ${esc(importanceLabel(item.importance))} · 唤醒 ${esc(fmtArousal(item.arousal))}</div>
        </section>`;
      }).join("")}</div>`;
    }

    function renderVectorRecallEvents() {
      const box = root && root.querySelector("#vector-recall-events");
      if (!box) return;
      const events = ((vectorStatus && vectorStatus.metrics && vectorStatus.metrics.events) || [])
        .filter((event) => event.kind === "recall"
          && (event.query || Number(event.results) > 0 || Number(event.candidates) > 0))
        .slice(-10).reverse();
      if (!events.length) {
        box.innerHTML = `<div class="memory-empty-inline">还没有真实召回记录；聊天触发召回后会在这里显示找出来的记忆。</div>`;
        return;
      }
      box.innerHTML = events.map((event, index) => `
        <details class="memory-vector-found" ${index === 0 ? "open" : ""}>
          <summary>
            <span class="mono">${esc(formatTime(event.ts))}</span>
            <b>${esc(truncate(event.query || "（无查询文本）", 80))}</b>
            <span>${esc(String(event.ms))} ms · 候选 ${esc(String(event.candidates ?? "—"))} · 命中 ${esc(String(event.results ?? "—"))}</span>
            ${event.vector_ok === false ? `<span class="badge warn">回退模糊</span>` : `<span class="badge ok">向量正常</span>`}
          </summary>
          <div style="margin-top:10px">${vectorFoundCards(event.found)}</div>
        </details>`).join("");
    }

    async function runVectorFind() {
      const inst = instance();
      const box = root && root.querySelector("#vector-found-results");
      const queryNode = root && root.querySelector("[data-vector-find-query]");
      if (!inst || !box || vectorFindBusy) return;
      const query = String(queryNode?.value || "").trim();
      if (!query) {
        toast("先输入要找的内容", "warn");
        return;
      }
      const k = Math.max(1, Math.min(20, Number(root.querySelector("[data-vector-find-k]").value) || 5));
      vectorFindBusy = true;
      box.innerHTML = `<div class="skeleton" style="height:90px"></div>`;
      try {
        const data = await request(inst, "/recall", {
          method: "POST",
          body: { query, k },
        });
        vectorFindData = { ...(data || {}), query };
        renderVectorFoundResults(box);
      } catch (err) {
        box.innerHTML = `<div class="console-warn"><div>找记忆失败：${esc(err.message)}</div></div>`;
      } finally {
        vectorFindBusy = false;
      }
    }

    function renderVectorFoundResults(box) {
      if (!box || !vectorFindData) return;
      const results = vectorFindData.results || [];
      const found = results.map((item) => ({
        id: item.id ?? item.metadata?.id,
        content: item.content,
        score: item.similarity_score,
        vector_score: item.score_breakdown?.two_stage_vector_score,
        fuzzy_score: item.score_breakdown?.two_stage_fuzzy_score,
        importance: item.metadata?.importance,
        arousal: item.metadata?.arousal,
      }));
      box.innerHTML = `<div class="console-help">查询「${esc(truncate(vectorFindData.query || "", 60))}」 · ${esc(String(vectorFindData.elapsed_time_ms || 0))} ms · 命中 ${found.length} 条</div>
        <div style="margin-top:10px">${vectorFoundCards(found)}</div>`;
    }

    function renderVectorRebuild() {
      const box = root && root.querySelector("#vector-rebuild");
      if (!box) return;
      const state = (vectorStatus && vectorStatus.rebuild) || {};
      const result = vectorStatus && vectorStatus.last_result;
      if (state.running) {
        const total = Number(state.total) || 0;
        const current = Number(state.current) || 0;
        const percent = total ? Math.min(100, Math.round(current / total * 100)) : 0;
        box.innerHTML = `<div class="console-help">${esc(state.message || "重建中")} · ${current}/${total || "—"}</div>
          <div class="memory-bar" style="margin-top:8px"><i style="width:${percent}%"></i></div>`;
      } else if (state.error) {
        box.innerHTML = `<div class="console-warn"><div>上次重建失败：${esc(state.error)}</div></div>`;
      } else if (result) {
        box.innerHTML = `<div class="console-help">上次重建：处理 ${esc(String(result.processed ?? 0))} 条，失败 ${esc(String(result.errors ?? 0))} 条，切换索引 ${result.switched ? "是" : "否"}${result.partial ? "（部分成功）" : ""}。</div>`;
      } else {
        box.innerHTML = `<div class="memory-empty-inline">尚未执行重建。重建会补齐 BM25 和向量索引，不会删除 documents 原文。</div>`;
      }
    }

    async function probeVector() {
      const inst = instance();
      if (!inst || vectorBusy) return;
      vectorBusy = true;
      try {
        const data = await request(inst, "/vector/probe", { method: "POST" });
        toast(`向量探针成功：${data.latency_ms} ms，维度 ${data.dimension}`);
        vectorConfigLoaded = false;
        await loadVector(true);
      } catch (err) {
        toast(`向量探针失败：${err.message}`, "err");
      } finally {
        vectorBusy = false;
      }
    }

    async function saveVectorConfig() {
      const inst = instance();
      const box = root && root.querySelector("#vector-config");
      if (!inst || !box) return;
      const values = {};
      box.querySelectorAll("[data-vector-cfg]").forEach((node) => {
        const key = node.dataset.vectorCfg;
        values[`recall_engine.${key}`] = node.type === "checkbox"
          ? node.checked
          : Number(node.value);
      });
      const ok = await confirmDialog(
        "保存向量召回参数",
        "将立即修改两段式召回候选数和权重，影响后续真实聊天召回。继续？");
      if (!ok) return;
      try {
        await request(inst, "/config", { method: "PUT", body: { values } });
        toast("向量召回参数已保存");
        vectorConfigLoaded = false;
        await loadVector(true);
      } catch (err) {
        toast(`保存失败：${err.message}`, "err");
      }
    }

    async function rebuildVector() {
      const inst = instance();
      if (!inst || vectorBusy) return;
      const ok = await confirmDialog(
        "重建向量索引",
        "会对当前记忆重建 BM25 和向量索引，可能持续几十秒到几分钟；不会删除原文。确定开始？");
      if (!ok) return;
      vectorBusy = true;
      try {
        await request(inst, "/vector/rebuild", { method: "POST" });
        toast("索引重建已启动");
        await loadVector(false);
      } catch (err) {
        toast(`重建启动失败：${err.message}`, "err");
      } finally {
        vectorBusy = false;
      }
    }

    /* --------------------------------------------------------------- brain */

    function brainHealthHtml() {
      const stats = statusData && statusData.stats ? statusData.stats : {};
      const prompt = statusData && statusData.prompt_has_arousal ? statusData.prompt_has_arousal : {};
      return `<section class="card brain-health-card">
        <div class="console-card-head"><h3>图谱与健康</h3><span>节点、边与记忆分布</span></div>
        <div class="stat-grid memory-health">
          ${statCard("图谱节点", stats.graph_nodes ?? "—", "图记忆节点")}
          ${statCard("图谱边", stats.graph_edges ?? "—", "关系边")}
          ${statCard("记忆原子", stats.atom_count ?? "—", "分类原子")}
          ${statCard("平均重要性", importanceLabel(stats.avg_importance), "0–1")}
        </div>
        ${prompt.private === false || prompt.group === false ? `<div class="console-warn"><div>提示词缺少 arousal 字段：${prompt.custom_private || prompt.custom_group ? "自定义提示词需要补齐" : "插件提示词未更新"}。</div></div>` : ""}
        <div class="memory-health-grid">
          <div class="console-card"><div class="console-card-head"><h3>重要性分布</h3></div><div class="memory-dist">${distributionHtml(stats.importance_distribution)}</div></div>
          <div class="console-card"><div class="console-card-head"><h3>原子类型</h3></div><div class="memory-dist">${distributionHtml(stats.atom_breakdown)}</div></div>
          <div class="console-card"><div class="console-card-head"><h3>状态</h3></div><div class="memory-dist">${distributionHtml(stats.status_breakdown)}</div></div>
        </div>
      </section>`;
    }

    function auditHtml(data) {
      const counts = data.counts || {};
      const groups = data.duplicates || [];
      const privacy = data.privacy || [];
      const conflicts = data.conflicts || [];
      const section = (title, count, rows, empty) => `<div class="card" style="margin-top:14px">
        <div class="section-head" style="margin:0 0 10px"><h2>${esc(title)}</h2><span class="side">${count} 项</span></div>
        ${rows || `<div class="empty" style="padding:18px"><p>${esc(empty)}</p></div>`}
      </div>`;
      return `
        <div class="auto-summary-grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">
          <div class="auto-summary"><div class="k">已检查</div><div class="v">${data.total || 0}<small>条</small></div></div>
          <div class="auto-summary"><div class="k">重复</div><div class="v">${counts.duplicates || 0}<small>组</small></div></div>
          <div class="auto-summary"><div class="k">敏感信息</div><div class="v">${counts.privacy || 0}<small>条</small></div></div>
          <div class="auto-summary"><div class="k">疑似冲突</div><div class="v">${counts.conflicts || 0}<small>组</small></div></div>
        </div>
        ${section("重复记忆", groups.length, groups.length ? `<div class="digest-list">${groups.map((group, index) =>
          `<div class="digest-item"><div class="time">组 ${index + 1}</div><div class="body">
            ${group.map((item) => `<div><span class="mono">${esc(shortId(item.id))}</span> ${esc(item.snippet)}</div>`).join("")}
          </div></div>`).join("")}</div>` : "", "未发现高相似记忆")}
        ${section("敏感信息", privacy.length, privacy.length ? `<div class="digest-list">${privacy.map((item) =>
          `<div class="digest-item"><div class="time">${esc(item.type)}</div>
            <div class="body"><span class="mono">${esc(shortId(item.id))}</span> ${esc(item.snippet)}</div></div>`).join("")}</div>` : "", "未命中手机号、邮箱、身份证或密钥模式")}
        ${section("疑似冲突", conflicts.length, conflicts.length ? `<div class="digest-list">${conflicts.map((item) =>
          `<div class="digest-item"><div class="time">对比</div><div class="body">
            <div>${esc(item.left.snippet)}</div><div style="color:var(--dim)">↔ ${esc(item.right.snippet)}</div>
          </div></div>`).join("")}</div>` : "", "未发现明显的相反表达")}
        <p class="hint-text">只读体检：不会修改或删除记忆。重复与冲突是启发式提示，敏感信息命中请人工确认后再处理。</p>`;
    }

    async function loadHealth(pane) {
      const inst = instance();
      if (!inst || healthBusy) return;
      healthBusy = true;
      const auditBox = pane.querySelector("#mem-health-audit");
      const riskBox = pane.querySelector("#mem-health-risk");
      if (auditBox) auditBox.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
      if (riskBox) riskBox.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
      const [auditResult, forgettingResult] = await Promise.allSettled([
        request(inst, "/audit"),
        request(inst, `/health/forgetting?limit=50&status=${encodeURIComponent(healthStatus)}`),
      ]);
      if (auditResult.status === "fulfilled") {
        healthAudit = auditResult.value;
        healthError = "";
      } else {
        healthAudit = null;
        healthError = auditResult.reason?.message || "体检读取失败";
      }
      if (forgettingResult.status === "fulfilled") {
        healthForgetting = Array.isArray(forgettingResult.value.items)
          ? forgettingResult.value.items
          : [];
        healthWarning = "";
      } else {
        healthForgetting = null;
        healthWarning = forgettingResult.reason?.message || "遗忘风险读取失败";
      }
      healthBusy = false;
      renderHealthContent(pane);
    }

    function renderHealth(pane) {
      pane.innerHTML = `
        <div class="section-head" style="margin-top:0">
          <h2>记忆体检</h2>
          <div class="side">体检只读 · 复习需确认 · 重复 / 敏感信息 / 疑似冲突 / 遗忘风险</div>
        </div>
        <div class="console-actions memory-actions" style="margin-bottom:12px">
          <button class="btn sm primary" data-health-run>${icon("pulse")}重新体检</button>
          <label class="memory-inline-filter">风险状态
            <select data-health-status>
              ${[["active", "活跃"], ["archived", "已归档"], ["all", "全部"]].map(([value, label]) =>
                `<option value="${value}"${healthStatus === value ? " selected" : ""}>${label}</option>`
              ).join("")}
            </select>
          </label>
          <span class="side">读取最近 200 条记忆 · 风险榜最多 50 条</span>
        </div>
        <div id="mem-health-audit"><div class="skeleton" style="height:160px"></div></div>
        <div id="mem-health-risk"><div class="skeleton" style="height:160px"></div></div>
        <p class="hint-text">体检只读：不会修改或删除记忆。遗忘风险由插件按读取时计算；复习预览只显示 before/after，不会写回。复习会先确认，只增加访问/复习计数并写审计，不影响正文。</p>`;
      pane.querySelector("[data-health-run]").addEventListener("click", () => loadHealth(pane));
      pane.querySelector("[data-health-status]").addEventListener("change", (event) => {
        healthStatus = event.target.value;
        loadHealth(pane);
      });
      loadHealth(pane);
    }

    function renderHealthContent(pane) {
      const auditBox = pane && pane.querySelector("#mem-health-audit");
      if (auditBox) {
        auditBox.innerHTML = healthError
          ? `<div class="empty">${icon("alert")}<h4>体检失败</h4><p>${esc(healthError)}</p><button class="btn ghost" data-health-retry>重试</button></div>`
          : auditHtml(healthAudit || {});
        const retry = auditBox.querySelector("[data-health-retry]");
        if (retry) retry.addEventListener("click", () => loadHealth(pane));
      }
      const riskBox = pane && pane.querySelector("#mem-health-risk");
      if (!riskBox) return;
      const items = Array.isArray(healthForgetting) ? healthForgetting : [];
      const rows = items.length
        ? `<div class="memory-table-wrap"><table class="table memory-table memory-risk-table">
            <thead><tr><th>风险</th><th>ID</th><th>摘要</th><th>类型</th><th>重要</th><th>唤醒</th><th>显著</th><th>TTL</th><th>距到期</th><th>最近访问</th><th>操作</th></tr></thead>
            <tbody>${items.map((item) => {
              const risk = Number(item.risk) || 0;
              return `<tr>
                <td><span class="memory-risk ${risk >= 0.7 ? "high" : risk >= 0.4 ? "mid" : ""}">${esc(fmtScore(item.risk))}</span></td>
                <td class="mono">${esc(shortId(item.memory_id))}</td>
                <td>${esc(truncate(item.summary || "—", 96))}</td>
                <td>${esc(memoryTypeLabel(item.type))}</td>
                <td class="mono">${esc(importanceLabel(item.importance))}</td>
                <td class="mono">${esc(fmtArousal(item.arousal))}</td>
                <td class="mono">${esc(fmtSalience(item.salience))}</td>
                <td class="mono">${esc(formatDays(item.ttl_days))}</td>
                <td class="mono">${esc(formatDays(item.days_to_expire))}</td>
                <td class="mono">${esc(formatTime(item.last_access))}</td>
                <td><div class="memory-row-actions">
                  <button class="btn sm ghost" data-health-preview="${esc(item.memory_id)}">复习预览</button>
                  <button class="btn sm primary" data-health-review="${esc(item.memory_id)}" ${healthStatus === "archived" ? "disabled" : ""}>复习</button>
                </div></td>
              </tr>`;
            }).join("")}</tbody></table></div>`
        : `<div class="memory-empty-inline">${healthWarning ? esc(healthWarning) : "暂无遗忘风险数据。"}</div>`;
      riskBox.innerHTML = `<section class="card memory-risk-card">
        <div class="console-card-head"><h3>遗忘风险榜</h3><span>${items.length} 条 · ${esc(healthStatus === "archived" ? "已归档" : healthStatus === "all" ? "全部" : "活跃")}</span></div>
        ${rows}
        <div class="console-help">风险 = 1 - 保留率；TTL 取该记忆 active 原子最小值，无原子默认 30 天。复习预览只读；复习会写入访问/复习计数与审计，不改正文和重要性，每次执行都需要确认，不自动复习。</div>
      </section>`;
      riskBox.querySelectorAll("[data-health-preview]").forEach((node) => {
        node.addEventListener("click", () => previewReview(node.dataset.healthPreview));
      });
      riskBox.querySelectorAll("[data-health-review]").forEach((node) => {
        node.addEventListener("click", () => reviewMemory(node.dataset.healthReview));
      });
    }

    async function reviewMemory(memoryId) {
      const inst = instance();
      if (!inst) return;
      if (reviewBusyId) return toast("已有复习任务在进行", "warn");
      const id = Number(memoryId);
      if (!Number.isFinite(id) || id <= 0) return toast("记忆 ID 无效", "err");
      reviewBusyId = id;
      const ok = await confirmDialog(
        "复习记忆",
        `会对 ${shortId(id)} 执行复习：增加访问/复习计数并写入审计，不改正文、重要性或类型；不自动批量复习。确定继续？`,
        false
      );
      if (!ok) {
        reviewBusyId = null;
        return;
      }
      const pane = root && root.querySelector("#mem-pane");
      const button = root && root.querySelector(`[data-health-review="${id}"]`);
      if (button) button.disabled = true;
      try {
        const result = await request(inst, `/health/review`, {
          method: "POST",
          body: { memory_id: id, confirm: "REVIEW" },
        });
        const after = result && result.after ? result.after : {};
        toast(`已复习 ${shortId(id)}：访问 ${Number(after.access_count) || 0} · 复习 ${Number(after.rehearsal_count) || 0}`);
        await refreshForgetting(pane);
      } catch (err) {
        toast(`复习失败：${err.message}`, "err");
        if (button) button.disabled = false;
      } finally {
        reviewBusyId = null;
      }
    }

    async function refreshForgetting(pane) {
      const inst = instance();
      if (!inst || !pane) return;
      const riskBox = pane.querySelector("#mem-health-risk");
      if (riskBox) riskBox.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
      try {
        const data = await request(
          inst,
          `/health/forgetting?limit=50&status=${encodeURIComponent(healthStatus)}`
        );
        healthForgetting = Array.isArray(data.items) ? data.items : [];
        healthWarning = "";
      } catch (err) {
        healthForgetting = null;
        healthWarning = err.message;
      }
      renderHealthContent(pane);
    }

    async function previewReview(memoryId) {
      const inst = instance();
      if (!inst) return;
      const ok = await confirmDialog(
        "复习预览",
        `只计算记忆 ${shortId(memoryId)} 复习后的访问/复习次数与风险变化，不写回数据库；如需写回请用风险榜的“复习”按钮并再次确认。确定预览？`,
        false
      );
      if (!ok) return;
      try {
        const data = await request(inst, "/health/review-preview", {
          method: "POST",
          body: { memory_id: Number(memoryId) },
        });
        const before = data.before || {};
        const after = data.after || {};
        const cell = (value) => esc(String(value ?? "—"));
        openModal({
          title: `复习预览 ${shortId(memoryId)}`,
          sub: data.writes === false ? "只读预览，不写回" : "预览结果",
          wide: true,
          body: `<div class="memory-detail"><div class="memory-detail-grid">
            ${detailRow("状态", data.status || "—")}
            ${detailRow("是否写回", data.writes === false ? "否（只读）" : "未知")}
            ${detailRow("访问次数（前 → 后）", `${cell(before.access_count)} → ${cell(after.access_count)}`)}
            ${detailRow("复习次数（前 → 后）", `${cell(before.rehearsal_count)} → ${cell(after.rehearsal_count)}`)}
            ${detailRow("风险（前 → 后）", `${fmtScore(before.risk)} → ${fmtScore(after.risk)}`)}
            ${detailRow("TTL", formatDays(before.ttl_days))}
            ${detailRow("最近访问（前）", formatTime(before.last_access))}
            ${detailRow("最近访问（后）", formatTime(after.last_access))}
          </div><div class="console-help">复习预览不会修改正文、重要性或访问计数；如需写回，请关闭预览后在风险榜点击“复习”并确认。</div></div>`,
          footer: `<button class="btn ghost" data-close>关闭</button>`,
        });
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function brainHighlightActive() {
      return Boolean(
        (brainHighlight.memoryIds && brainHighlight.memoryIds.length) ||
        brainHighlight.relationKey
      );
    }

    function brainHighlightText() {
      const count = Array.isArray(brainHighlight.memoryIds) ? brainHighlight.memoryIds.length : 0;
      if (!count && !brainHighlight.relationKey) return "未设置高亮";
      return `只读高亮：${count} 条记忆${brainHighlight.relationKey ? ` · ${brainHighlight.relationKey}` : ""}`;
    }

    function syncBrainHighlight() {
      const text = root && root.querySelector("[data-brain-highlight-text]");
      if (text) text.textContent = brainHighlightText();
      const clear = root && root.querySelector("[data-brain-clear-highlight]");
      if (clear) clear.disabled = !brainHighlightActive();
      if (brainRenderer && typeof brainRenderer.setHighlight === "function") {
        brainRenderer.setHighlight(brainHighlight);
      }
    }

    function applyBrainHighlight(highlight) {
      if (window.ManagerBrain && ManagerBrain.normalizeHighlight) {
        brainHighlight = ManagerBrain.normalizeHighlight(highlight);
      } else {
        brainHighlight = {
          memoryIds: (highlight && highlight.memoryIds) || [],
          relationKey: String((highlight && highlight.relationKey) || "").trim(),
        };
      }
      if (activeTab !== "brain") {
        activeTab = "brain";
        syncTabButtons();
        renderTab();
        return;
      }
      syncBrainHighlight();
      if (!brainRaw) loadBrainData();
    }

    function renderBrain(pane) {
      if (!window.ManagerBrain) {
        pane.innerHTML = `<div class="empty">${icon("alert")}<h4>脑图模块未加载</h4><p>请刷新页面后重试。</p></div>`;
        return;
      }
      pane.innerHTML = `
        <section class="card brain-toolbar">
          <div class="brain-filters">
            <label>会话<input data-brain-filter="session_id" value="${esc(brainFilters.session_id)}" placeholder="可选"></label>
            <label>人格<input data-brain-filter="persona_id" value="${esc(brainFilters.persona_id)}" placeholder="可选"></label>
            <label>状态<select data-brain-filter="status">
              <option value="active"${brainFilters.status === "active" ? " selected" : ""}>活跃</option>
              <option value="all"${brainFilters.status === "all" ? " selected" : ""}>全部</option>
            </select></label>
            <label>类型<select data-brain-filter="type">${TYPES.map((value) =>
              `<option value="${value === "all" ? "" : value}"${brainFilters.type === (value === "all" ? "" : value) ? " selected" : ""}>${value === "all" ? "全部类型" : value}</option>`
            ).join("")}</select></label>
            <button class="btn primary" data-brain-apply>${icon("refresh")}应用</button>
          </div>
          <div class="brain-highlight-bar">
            <span data-brain-highlight-text>${esc(brainHighlightText())}</span>
            <button class="btn sm ghost" data-brain-clear-highlight ${brainHighlightActive() ? "" : "disabled"}>清除高亮</button>
          </div>
          <div class="console-help">图谱边来自真实记忆图谱；背景粒子密度按每条记忆的关键事实规模生成；不在此处修改数据。高亮为只读，不改变拖拽、缩放和点击。</div>
        </section>
        <section class="card brain-stage-card">
          <div class="brain-stage-head">
            <div>
              <div class="brain-kicker">SCIENTIFIC MEMORY ATLAS</div>
              <h3>海马体与记忆网络</h3>
            </div>
            <div class="brain-legend" aria-label="图例">
              ${["FACTUAL", "PREFERENCE", "RELATIONAL", "EPISODIC", "PLANNED"].map((type) =>
                `<span><i style="background:${ManagerBrain.typeColor(type)}"></i>${esc(ManagerBrain.formatType(type))}</span>`
              ).join("")}
              <span><i class="brain-legend-line"></i>图谱关系</span>
              <span><i class="brain-legend-dash"></i>会话聚合</span>
              <span><i class="brain-legend-dot"></i>原子粒子</span>
            </div>
          </div>
          <div class="brain-canvas-wrap" id="brain-canvas-wrap">
            <canvas id="brain-canvas" aria-label="记忆脑图"></canvas>
            <div class="brain-tooltip" id="brain-tooltip"></div>
            <div class="brain-empty-overlay" id="brain-empty" hidden>
              <b>没有可显示的记忆</b>
              <span>换筛选条件，或先让机器人产生一些记忆。</span>
            </div>
            <div class="brain-warning" id="brain-warning"></div>
          </div>
        </section>
        <div class="brain-lower">
          <section class="card brain-hex-card">
            <div class="console-card-head"><h3>记忆网格</h3><span>六边形单元 · 点击定位</span></div>
            <div id="brain-grid" class="brain-hex-grid"></div>
          </section>
          <aside class="card brain-detail-card" id="brain-detail">
            <div class="memory-empty-inline">点击六边形或脑图节点查看记忆。</div>
          </aside>
        </div>
        ${brainHealthHtml()}`;
      pane.querySelector("[data-brain-apply]").addEventListener("click", () => {
        pane.querySelectorAll("[data-brain-filter]").forEach((node) => {
          brainFilters[node.dataset.brainFilter] = node.value;
        });
        brainSelectedId = null;
        loadBrainData();
      });
      const clearHighlight = pane.querySelector("[data-brain-clear-highlight]");
      if (clearHighlight) clearHighlight.addEventListener("click", () => {
        brainHighlight = { memoryIds: [], relationKey: "" };
        syncBrainHighlight();
        if (brainRenderer && typeof brainRenderer.setHighlight === "function") {
          brainRenderer.setHighlight(brainHighlight);
        }
      });
      pane.querySelectorAll("[data-brain-filter]").forEach((node) => {
        if (node.tagName === "INPUT") {
          node.addEventListener("keydown", (event) => {
            if (event.key === "Enter") pane.querySelector("[data-brain-apply]").click();
          });
        }
      });
      const wrap = pane.querySelector("#brain-canvas-wrap");
      if (!brainResizeObserver && typeof ResizeObserver !== "undefined") {
        brainResizeObserver = new ResizeObserver(() => {
          if (!root || activeTab !== "brain" || !brainRaw) return;
          if (brainResizeTimer) clearTimeout(brainResizeTimer);
          brainResizeTimer = setTimeout(() => {
            if (root && activeTab === "brain" && brainRaw) renderBrainModel();
          }, 160);
        });
        brainResizeObserver.observe(wrap);
      }
      loadBrainData();
    }

    async function loadBrainData() {
      const inst = instance();
      if (!inst || !window.ManagerBrain) return;
      const warning = root && root.querySelector("#brain-warning");
      if (warning) warning.innerHTML = "加载记忆与图谱…";
      const memoryQuery = buildMemoryQuery({
        status: brainFilters.status,
        type: brainFilters.type,
        session_id: brainFilters.session_id,
        persona_id: brainFilters.persona_id,
        sort: "importance_desc",
        page_size: 200,
      });
      const graphQuery = buildMemoryQuery({
        session_id: brainFilters.session_id,
        persona_id: brainFilters.persona_id,
        limit_memories: 24,
        limit_entries: 80,
        limit_nodes: 80,
        limit_edges: 120,
      });
      const [memoryResult, graphResult] = await Promise.allSettled([
        request(inst, `/items?${memoryQuery}`),
        request(inst, `/graph?${graphQuery}`),
      ]);
      if (memoryResult.status !== "fulfilled") {
        if (warning) {
          warning.innerHTML = `<div class="console-warn"><div>${esc(memoryResult.reason?.message || "记忆读取失败")}</div></div>`;
        }
        return;
      }
      brainRaw = {
        memories: memoryResult.value.items || [],
        graph: graphResult.status === "fulfilled" ? graphResult.value : null,
      };
      if (warning) {
        warning.innerHTML =
          graphResult.status === "fulfilled"
            ? ""
            : `<div class="console-warn"><div>图谱关系读取失败，仅显示记忆节点与网格。</div></div>`;
      }
      renderBrainModel();
    }

    function renderBrainModel() {
      const inst = instance();
      const wrap = root && root.querySelector("#brain-canvas-wrap");
      const canvas = root && root.querySelector("#brain-canvas");
      if (!inst || !wrap || !canvas || !brainRaw || !window.ManagerBrain) return;
      const width = Math.max(520, wrap.clientWidth || 900);
      const height = Math.max(360, wrap.clientHeight || 520);
      brainModel = ManagerBrain.buildModel(brainRaw.memories, brainRaw.graph, {
        width,
        height,
        maxMemories: 60,
        maxGraphNodes: 80,
        maxEdges: 120,
      });
      destroyBrainRenderer();
      const empty = root.querySelector("#brain-empty");
      if (empty) empty.hidden = brainModel.memories.length > 0;
      if (!brainModel.memories.length) {
        const grid = root.querySelector("#brain-grid");
        if (grid) grid.innerHTML = `<div class="memory-empty-inline">没有匹配的记忆。</div>`;
        renderBrainDetail(null);
        return;
      }
      brainRenderer = ManagerBrain.createRenderer(canvas, {
        onHover: showBrainTip,
        onSelectMemory: selectBrainMemory,
        onSelectGraph: renderGraphNodeDetail,
      });
      brainRenderer.render(brainModel);
      if (typeof brainRenderer.setHighlight === "function") {
        brainRenderer.setHighlight(brainHighlight);
      }
      if (
        !brainSelectedId ||
        !brainModel.memories.some((item) => item.id === brainSelectedId)
      ) {
        brainSelectedId = brainModel.memories[0].id;
      }
      brainRenderer.setSelected(brainSelectedId);
      renderBrainGrid(brainModel.memories);
      renderBrainDetail(
        brainModel.memories.find((item) => item.id === brainSelectedId) || null
      );
    }

    function renderBrainGrid(memories) {
      const grid = root && root.querySelector("#brain-grid");
      if (!grid) return;
      grid.innerHTML = (memories || []).slice(0, 60).map((memory) => {
        const selected = memory.id === brainSelectedId;
        const color = ManagerBrain.typeColor(memory.type);
        const fillOpacity = Math.min(0.42, 0.08 + memory.importance * 0.2 + memory.arousal * 0.08);
        return `<button type="button" class="brain-hex ${selected ? "selected" : ""}" data-brain-id="${esc(memory.id)}" aria-label="${esc(`#${memory.id} ${memory.summary}`)}" title="${esc(memory.summary)}">
          <svg viewBox="0 0 100 112" aria-hidden="true"><polygon points="50,2 95,28 95,84 50,110 5,84 5,28" fill="${esc(color)}" fill-opacity="${fillOpacity.toFixed(2)}" stroke="${selected ? "var(--accent)" : "var(--line-2)"}" stroke-width="${selected ? 2 : 1}"></polygon></svg>
          <span class="brain-hex-copy">
            <span class="brain-hex-id">${esc(shortId(memory.id))}</span>
            <span class="brain-hex-type">${esc(ManagerBrain.formatType(memory.type))}</span>
            <span class="brain-hex-meta">${esc(importanceLabel(memory.importance))} · ${esc(fmtArousal(memory.arousal))}</span>
          </span>
        </button>`;
      }).join("");
      grid.querySelectorAll("[data-brain-id]").forEach((node) => {
        node.addEventListener("click", () => selectBrainMemory(Number(node.dataset.brainId)));
        node.addEventListener("dblclick", () => openDetail(Number(node.dataset.brainId)));
      });
    }

    function selectBrainMemory(id) {
      brainSelectedId = Number(id);
      if (brainRenderer) brainRenderer.setSelected(brainSelectedId);
      const grid = root && root.querySelector("#brain-grid");
      if (grid) {
        grid.querySelectorAll("[data-brain-id]").forEach((node) => {
          node.classList.toggle(
            "selected",
            Number(node.dataset.brainId) === brainSelectedId
          );
          const polygon = node.querySelector("polygon");
          if (polygon) {
            const selected = Number(node.dataset.brainId) === brainSelectedId;
            polygon.setAttribute("stroke", selected ? "var(--accent)" : "var(--line-2)");
            polygon.setAttribute("stroke-width", selected ? "2" : "1");
          }
        });
      }
      renderBrainDetail(
        brainModel?.memories.find((item) => item.id === brainSelectedId) || null
      );
    }

    function renderBrainDetail(item) {
      const box = root && root.querySelector("#brain-detail");
      if (!box) return;
      if (!item) {
        box.innerHTML = `<div class="memory-empty-inline">点击六边形或脑图节点查看记忆。</div>`;
        return;
      }
      const facts = Array.isArray(item.keyFacts) ? item.keyFacts.slice(0, 4) : [];
      box.innerHTML = `<div class="brain-detail-kicker">选中记忆</div>
        <div class="brain-detail-title"><span class="mono">${esc(shortId(item.id))}</span><b>${esc(ManagerBrain.formatType(item.type))}</b></div>
        <p class="brain-detail-summary">${esc(item.summary)}</p>
        <div class="brain-detail-grid">
          <div><span>重要性</span><b>${esc(importanceLabel(item.importance))}</b></div>
          <div><span>唤醒度</span><b>${esc(fmtArousal(item.arousal))}</b></div>
          <div><span>显著性</span><b>${esc(fmtSalience(item.salience))}</b></div>
          <div><span>会话</span><b>${esc(item.sessionId || "—")}</b></div>
        </div>
        ${facts.length ? `<div class="brain-facts"><span>关键事实</span>${facts.map((fact) => `<p>${esc(fact)}</p>`).join("")}</div>` : ""}
        <button type="button" class="btn primary" data-brain-open>${icon("search")}打开记忆详情</button>`;
      const open = box.querySelector("[data-brain-open]");
      if (open) open.addEventListener("click", () => openDetail(item.id));
    }

    function renderGraphNodeDetail(node) {
      const box = root && root.querySelector("#brain-detail");
      if (!box || !node) return;
      box.innerHTML = `<div class="brain-detail-kicker">图谱实体</div>
        <div class="brain-detail-title"><b>${esc(node.label || node.key || node.id)}</b></div>
        <div class="brain-detail-grid">
          <div><span>类型</span><b>${esc(node.type || "—")}</b></div>
          <div><span>连接度</span><b>${esc(String(node.degree ?? "—"))}</b></div>
          <div><span>权重</span><b>${esc(String(node.weight ?? "—"))}</b></div>
        </div>
        <div class="memory-empty-inline">这是图谱事实/参与者节点，不是一条记忆文档。</div>`;
    }

    function showBrainTip(hit, position) {
      const tip = root && root.querySelector("#brain-tooltip");
      const wrap = root && root.querySelector("#brain-canvas-wrap");
      if (!tip || !wrap) return;
      if (!hit || !position) {
        tip.classList.remove("show");
        return;
      }
      const rect = wrap.getBoundingClientRect();
      const isMemory = hit.kind === "memory";
      const title = isMemory
        ? `#${hit.item.id} · ${ManagerBrain.formatType(hit.item.type)}`
        : `${hit.node.label || hit.node.key || hit.node.id}`;
      const detail = isMemory
        ? truncate(hit.item.summary, 160)
        : `图谱实体 · 连接度 ${hit.node.degree ?? "—"} · 权重 ${hit.node.weight ?? "—"}`;
      tip.innerHTML = `<b>${esc(title)}</b><span>${esc(detail)}</span>`;
      const left = Math.min(Math.max(12, position.x - rect.left + 14), Math.max(12, rect.width - 250));
      const top = Math.min(Math.max(12, position.y - rect.top + 14), Math.max(12, rect.height - 96));
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
      tip.classList.add("show");
    }

    function distributionHtml(value) {
      const rows = distributionRows(value);
      if (!rows.length) return `<div class="memory-empty-inline">暂无数据</div>`;
      const max = Math.max(...rows.map((row) => row.count), 1);
      return rows.map((row) =>
        `<div class="memory-dist-row"><span>${esc(row.key)}</span><div class="memory-bar"><i style="width:${(row.count / max) * 100}%"></i></div><em>${row.count}</em></div>`
      ).join("");
    }

    return {
      viewMemory,
      leave,
    };
  }

  return {
    TABS,
    LEGACY_TABS,
    activeRecallBlockedLabel,
    activeRecallMode,
    activeRecallModeLabel,
    create,
    buildExportQuery,
    buildMemoryQuery,
    collectConfigValues,
    distributionRows,
    dreamMemoryIds,
    dreamNarrative,
    dreamState,
    estimateSalience,
    filterMemoryItems,
    fmtArousal,
    fmtSalience,
    fmtScore,
    formatBytes,
    formatConfigNumber,
    formatDays,
    formatDurationMs,
    formatGroupAllowlist,
    formatPercent01,
    identityEntries,
    identityLabels,
    importanceLabel,
    memoryPassesFilters,
    memoryTypeLabel,
    metadataOf,
    parseGroupAllowlist,
    personKeys,
    promptMissingScopes,
    replayTimelineRows,
    scoreDisplay,
    scoreRows,
    serializeHumanConfig,
    shortId,
    summarizeReport,
    truncate,
    validateSleepTime,
  };
});
