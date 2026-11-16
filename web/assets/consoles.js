/* B站 / 抖音插件控制台 —— 纯前端模块，依赖 app.js 传入的 ctx 助手 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerConsoles = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const PLUGINS = {
    bili: {
      id: "astrbot_plugin_bilibili_ai_bot",
      title: "B站控制台",
      sub: "主动看片频率、互动开关与今日运行状态",
      icon: "play",
    },
    douyin: {
      id: "astrbot_plugin_douyin_dm",
      title: "抖音控制台",
      sub: "主动刷时隙、互动/评论开关与 QQ 汇报状态",
      icon: "play",
    },
  };

  const BILI_LABELS = {
    ENABLE_PROACTIVE: "启用主动看片",
    ENABLE_AUTONOMOUS_DAILY_PLAN: "Bot 自主日程",
    PROACTIVE_TIMES_COUNT: "每天轮数",
    PROACTIVE_VIDEO_COUNT: "每轮视频数",
    PROACTIVE_DAILY_LIMIT: "每日视频上限",
    FIXED_PROACTIVE_WINDOWS: "固定时间段",
    FIXED_PROACTIVE_TIMES: "精确时刻",
    AUTONOMOUS_ACTIVITY_LEVEL: "活跃度（0-100）",
    SLEEP_START: "睡眠开始（小时）",
    SLEEP_END: "睡眠结束（小时）",
    AUTONOMOUS_MIN_ACTION_GAP_MINUTES: "最小事件间隔（分钟）",
    PROACTIVE_LIKE: "主动点赞",
    PROACTIVE_LIKE_MIN_SCORE: "点赞最低评分",
    PROACTIVE_FAV: "主动收藏",
    PROACTIVE_FAV_MIN_SCORE: "收藏最低评分",
    PROACTIVE_COIN: "主动投币",
    PROACTIVE_COIN_MIN_SCORE: "投币最低评分",
    PROACTIVE_COMMENT: "主动评论",
    PROACTIVE_COMMENT_MIN_SCORE: "评论最低评分",
    PROACTIVE_COMMENT_COUNT: "每视频最多评论",
    PROACTIVE_COMMENT_DAILY_LIMIT: "每日最多主动评论",
    PROACTIVE_FOLLOW: "主动关注",
    PROACTIVE_FOLLOW_MIN_SCORE: "关注最低评分",
    RECOMMEND_OWNER_DAILY_LIMIT: "每日给主人推荐上限",
    ENABLE_DYNAMIC_WATCH: "关注动态巡视",
    DYNAMIC_WATCH_TIMES_COUNT: "动态巡视每天次数",
    DYNAMIC_WATCH_DAILY_LIMIT: "动态巡视每日上限",
    DYNAMIC_TIMES_COUNT: "每日发动态次数",
    BANGUMI_PROACTIVE: "追番自动观看",
    BANGUMI_DAILY_LIMIT: "追番每日上限",
    SPECIAL_FOLLOW_TIMES_COUNT: "特别关注每天轮数",
    SPECIAL_FOLLOW_FIXED_TIMES: "特别关注时刻",
  };

  const DOUYIN_LABELS = {
    qq_proactive_enabled: "启用主动刷",
    OWNER_QQ_UMO: "QQ 汇报目标 UMO",
    qq_proactive_times: "主动刷时隙",
    qq_proactive_daily_limit: "每日上限",
    qq_proactive_max_seconds: "单次最长观看（秒）",
    allow_like: "允许点赞",
    allow_favorite: "允许收藏",
    allow_follow: "允许关注",
    interaction_dry_run: "互动干跑",
    like_daily_limit: "点赞每日上限",
    favorite_daily_limit: "收藏每日上限",
    follow_daily_limit: "关注每日上限",
    allow_public_comments: "允许公开评论",
    comment_backend: "评论后端",
    client_comment_enabled: "启用客户端评论",
    client_comment_dry_run: "客户端评论干跑",
    client_comment_daily_limit: "客户端评论每日上限",
    client_comment_interval_seconds: "客户端评论最小间隔（秒）",
    client_comment_peer: "客户端评论会话",
    client_comment_peer_kind: "会话类型",
    video_perception_mode: "视频感知方式",
    local_frame_count: "抽帧数",
    local_frame_max_edge: "抽帧最长边",
  };

  const BILI_GROUPS = [
    { id: "frequency", title: "主动看片频率", keys: [
      "ENABLE_PROACTIVE", "PROACTIVE_TIMES_COUNT", "PROACTIVE_VIDEO_COUNT",
      "PROACTIVE_DAILY_LIMIT", "FIXED_PROACTIVE_WINDOWS", "FIXED_PROACTIVE_TIMES",
      "AUTONOMOUS_ACTIVITY_LEVEL", "SLEEP_START", "SLEEP_END",
      "AUTONOMOUS_MIN_ACTION_GAP_MINUTES",
    ] },
    { id: "interactions", title: "互动", keys: [
      "PROACTIVE_LIKE", "PROACTIVE_LIKE_MIN_SCORE", "PROACTIVE_FAV", "PROACTIVE_FAV_MIN_SCORE",
      "PROACTIVE_COIN", "PROACTIVE_COIN_MIN_SCORE", "PROACTIVE_COMMENT",
      "PROACTIVE_COMMENT_MIN_SCORE", "PROACTIVE_COMMENT_COUNT", "PROACTIVE_COMMENT_DAILY_LIMIT",
      "PROACTIVE_FOLLOW", "PROACTIVE_FOLLOW_MIN_SCORE", "RECOMMEND_OWNER_DAILY_LIMIT",
    ] },
    { id: "extensions", title: "扩展行为", keys: [
      "ENABLE_DYNAMIC_WATCH", "DYNAMIC_WATCH_TIMES_COUNT", "DYNAMIC_WATCH_DAILY_LIMIT",
      "DYNAMIC_TIMES_COUNT", "BANGUMI_PROACTIVE", "BANGUMI_DAILY_LIMIT",
      "SPECIAL_FOLLOW_TIMES_COUNT", "SPECIAL_FOLLOW_FIXED_TIMES",
    ] },
  ];

  const DOUYIN_GROUPS = [
    { id: "frequency", title: "主动刷频率", keys: [
      "qq_proactive_enabled", "OWNER_QQ_UMO", "qq_proactive_times",
      "qq_proactive_daily_limit", "qq_proactive_max_seconds",
    ] },
    { id: "interactions", title: "互动", keys: [
      "allow_like", "allow_favorite", "allow_follow", "interaction_dry_run",
      "like_daily_limit", "favorite_daily_limit", "follow_daily_limit",
    ] },
    { id: "comments", title: "评论", keys: [
      "allow_public_comments", "comment_backend", "client_comment_enabled",
      "client_comment_dry_run", "client_comment_daily_limit",
      "client_comment_interval_seconds", "client_comment_peer", "client_comment_peer_kind",
    ] },
    { id: "perception", title: "感知", keys: [
      "video_perception_mode", "local_frame_count", "local_frame_max_edge",
    ] },
  ];

  const RANGES = {
    PROACTIVE_TIMES_COUNT: [0, 12], PROACTIVE_VIDEO_COUNT: [1, 12],
    PROACTIVE_DAILY_LIMIT: [0, 100], AUTONOMOUS_ACTIVITY_LEVEL: [0, 100],
    SLEEP_START: [0, 23], SLEEP_END: [0, 23], AUTONOMOUS_MIN_ACTION_GAP_MINUTES: [0, 1440],
    PROACTIVE_LIKE_MIN_SCORE: [0, 10], PROACTIVE_FAV_MIN_SCORE: [0, 10],
    PROACTIVE_COIN_MIN_SCORE: [0, 10], PROACTIVE_COMMENT_MIN_SCORE: [0, 10],
    PROACTIVE_FOLLOW_MIN_SCORE: [0, 10], RECOMMEND_OWNER_DAILY_LIMIT: [0, 10],
    PROACTIVE_COMMENT_COUNT: [0, 10], PROACTIVE_COMMENT_DAILY_LIMIT: [0, 50],
    DYNAMIC_WATCH_TIMES_COUNT: [0, 12], DYNAMIC_WATCH_DAILY_LIMIT: [0, 100],
    DYNAMIC_TIMES_COUNT: [0, 3], BANGUMI_DAILY_LIMIT: [0, 10],
    SPECIAL_FOLLOW_TIMES_COUNT: [0, 12],
    qq_proactive_daily_limit: [1, 3], qq_proactive_max_seconds: [30, 600],
    like_daily_limit: [1, 10], favorite_daily_limit: [1, 5], follow_daily_limit: [1, 3],
    client_comment_daily_limit: [1, 10], client_comment_interval_seconds: [0, 3600],
    local_frame_count: [6, 20], local_frame_max_edge: [320, 3840],
  };

  const TIME_LIST_KEYS = new Set(["FIXED_PROACTIVE_TIMES", "qq_proactive_times", "SPECIAL_FOLLOW_FIXED_TIMES"]);
  const WINDOW_LIST_KEYS = new Set(["FIXED_PROACTIVE_WINDOWS"]);

  function clone(value) {
    return JSON.parse(JSON.stringify(value === undefined ? null : value));
  }

  function clock(raw) {
    const match = String(raw == null ? "" : raw).trim().match(/^(\d{1,2}):(\d{2})$/);
    if (!match) return null;
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (hour > 23 || minute > 59) return null;
    return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  }

  function parseTimes(raw, max = 12) {
    const items = Array.isArray(raw) ? raw : String(raw || "").split(/[\n,，]+/);
    const times = [];
    for (const item of items) {
      if (String(item == null ? "" : item).trim() === "") continue;
      const value = clock(item);
      if (!value) return { times, error: `时间格式应为 HH:MM：${String(item).trim()}` };
      if (!times.includes(value)) times.push(value);
    }
    times.sort();
    if (times.length > max) return { times, error: `最多 ${max} 个时隙` };
    return { times, error: "" };
  }

  function parseWindows(raw, max = 12) {
    const items = Array.isArray(raw) ? raw : String(raw || "").split(/[\n,，]+/);
    const windows = [];
    for (const item of items) {
      if (String(item == null ? "" : item).trim() === "") continue;
      const parts = String(item).split(/\s*-\s*/);
      if (parts.length !== 2) return { windows, error: `时间段格式应为 HH:MM-HH:MM：${item}` };
      const start = clock(parts[0]);
      const end = clock(parts[1]);
      if (!start || !end) return { windows, error: `时间段格式应为 HH:MM-HH:MM：${item}` };
      if (start >= end) return { windows, error: `开始时间必须早于结束时间：${item}` };
      const value = `${start}-${end}`;
      if (!windows.includes(value)) windows.push(value);
    }
    windows.sort();
    if (windows.length > max) return { windows, error: `最多 ${max} 个时间段` };
    return { windows, error: "" };
  }

  function deriveBiliMode(values) {
    if (values && values.ENABLE_AUTONOMOUS_DAILY_PLAN) return "auto";
    const windows = Array.isArray(values && values.FIXED_PROACTIVE_WINDOWS) ? values.FIXED_PROACTIVE_WINDOWS : [];
    if (windows.filter((item) => String(item || "").trim()).length) return "windows";
    return "times";
  }

  function nextDouyinSlot(times, now = new Date()) {
    const parsed = parseTimes(times, 3);
    if (parsed.error || !parsed.times.length) return "—";
    const minutes = now.getHours() * 60 + now.getMinutes();
    const next = parsed.times.find((item) => {
      const [hour, minute] = item.split(":").map(Number);
      return hour * 60 + minute >= minutes;
    });
    return next ? `今天 ${next}` : `明天 ${parsed.times[0]}`;
  }

  function integerError(values, key, errors, label) {
    const range = RANGES[key];
    if (!range) return;
    const value = Number(values[key]);
    if (!Number.isFinite(value) || value < range[0] || value > range[1]) {
      errors[key] = `${label}需在 ${range[0]}–${range[1]} 之间`;
    }
  }

  function validateBili(values) {
    const errors = {};
    const warnings = {};
    integerError(values, "PROACTIVE_TIMES_COUNT", errors, "每天轮数");
    integerError(values, "PROACTIVE_VIDEO_COUNT", errors, "每轮视频数");
    integerError(values, "PROACTIVE_DAILY_LIMIT", errors, "每日视频上限");
    for (const key of ["AUTONOMOUS_ACTIVITY_LEVEL", "SLEEP_START", "SLEEP_END",
      "AUTONOMOUS_MIN_ACTION_GAP_MINUTES", "PROACTIVE_LIKE_MIN_SCORE", "PROACTIVE_FAV_MIN_SCORE",
      "PROACTIVE_COIN_MIN_SCORE", "PROACTIVE_COMMENT_MIN_SCORE", "PROACTIVE_FOLLOW_MIN_SCORE",
      "RECOMMEND_OWNER_DAILY_LIMIT", "PROACTIVE_COMMENT_COUNT", "PROACTIVE_COMMENT_DAILY_LIMIT",
      "DYNAMIC_WATCH_TIMES_COUNT", "DYNAMIC_WATCH_DAILY_LIMIT", "DYNAMIC_TIMES_COUNT",
      "BANGUMI_DAILY_LIMIT", "SPECIAL_FOLLOW_TIMES_COUNT"]) {
      integerError(values, key, errors, BILI_LABELS[key] || key);
    }
    if (!values.ENABLE_PROACTIVE) warnings.ENABLE_PROACTIVE = "主动看片已关闭，不会自动观看或互动。";
    const mode = deriveBiliMode(values);
    const rounds = Number(values.PROACTIVE_TIMES_COUNT) || 0;
    if (mode === "windows") {
      const parsed = parseWindows(values.FIXED_PROACTIVE_WINDOWS, 12);
      if (parsed.error) errors.FIXED_PROACTIVE_WINDOWS = parsed.error;
      if (!parsed.error && !parsed.windows.length) errors.FIXED_PROACTIVE_WINDOWS = "请至少填写一个时间段，或切换为精确时刻。";
      if (!parsed.error && parsed.windows.length > rounds) warnings.FIXED_PROACTIVE_WINDOWS = `时间段数量超过每天轮数（${rounds}），超出部分会被截断。`;
      if ((values.FIXED_PROACTIVE_TIMES || []).length) warnings.FIXED_PROACTIVE_TIMES = "时间段非空时，精确时刻列表不生效。";
    } else if (mode === "times") {
      const parsed = parseTimes(values.FIXED_PROACTIVE_TIMES, 12);
      if (parsed.error) errors.FIXED_PROACTIVE_TIMES = parsed.error;
      if (!parsed.error && !parsed.times.length) errors.FIXED_PROACTIVE_TIMES = "请至少填写一个精确时刻，或切换为固定时间段。";
      if (!parsed.error && parsed.times.length > rounds) warnings.FIXED_PROACTIVE_TIMES = `时刻数量超过每天轮数（${rounds}），超出部分会被截断。`;
    } else {
      if ((values.FIXED_PROACTIVE_WINDOWS || []).length || (values.FIXED_PROACTIVE_TIMES || []).length) {
        warnings.FIXED_PROACTIVE_WINDOWS = "Bot 自主日程开启后，固定时间段/精确时刻不生效。";
      }
    }
    return { errors, warnings, mode };
  }

  function validateDouyin(values) {
    const errors = {};
    const warnings = {};
    const parsed = parseTimes(values.qq_proactive_times, 3);
    if (parsed.error) errors.qq_proactive_times = parsed.error;
    if (!parsed.error && !parsed.times.length) warnings.qq_proactive_times = "时隙留空时会使用默认 12:30、20:30。";
    integerError(values, "qq_proactive_daily_limit", errors, "每日上限");
    integerError(values, "qq_proactive_max_seconds", errors, "单次最长观看");
    for (const key of ["like_daily_limit", "favorite_daily_limit", "follow_daily_limit",
      "client_comment_daily_limit", "client_comment_interval_seconds",
      "local_frame_count", "local_frame_max_edge"]) {
      integerError(values, key, errors, DOUYIN_LABELS[key] || key);
    }
    if (values.qq_proactive_enabled) {
      if (!String(values.OWNER_QQ_UMO || "").trim()) {
        warnings.OWNER_QQ_UMO = "未填写 QQ 汇报目标，主动刷会失败。";
      }
    } else {
      warnings.qq_proactive_enabled = "主动刷已关闭，不会按时隙执行。";
    }
    if (values.interaction_dry_run) warnings.interaction_dry_run = "互动干跑开启：点赞/收藏/关注只读状态，不真正点击。";
    if (values.client_comment_enabled && !values.allow_public_comments) {
      warnings.client_comment_enabled = "公开评论总开关关闭时，客户端评论不会执行。";
    }
    if (values.allow_public_comments && values.comment_backend === "client") {
      warnings.comment_backend = "客户端评论要求客户端停在视频详情页且消息面板为全高布局；结果不明时不会重发。";
    }
    if (values.client_comment_dry_run) warnings.client_comment_dry_run = "客户端评论干跑开启：只输入再清空，不发送。";
    return { errors, warnings, mode: "" };
  }

  function buildConfigPayload(original, values, schema) {
    const payload = clone(original || {});
    for (const [key, raw] of Object.entries(values || {})) {
      if (key.startsWith("__")) continue;
      const def = (schema && schema[key]) || {};
      const type = def.type || (Array.isArray(raw) ? "list" : typeof raw);
      if (type === "bool") payload[key] = Boolean(raw);
      else if (type === "int") payload[key] = Number.isFinite(Number(raw)) ? Math.trunc(Number(raw)) : 0;
      else if (type === "float") payload[key] = Number(raw) || 0;
      else if (type === "list") {
        payload[key] = Array.isArray(raw) ? raw.map((item) => String(item)) : [];
        if (key === "FIXED_PROACTIVE_WINDOWS" || TIME_LIST_KEYS.has(key)) payload[key].sort();
      } else payload[key] = raw == null ? "" : String(raw);
    }
    return payload;
  }

  function countDirty(values, initial) {
    let count = 0;
    const keys = new Set([...Object.keys(values || {}), ...Object.keys(initial || {})]);
    for (const key of keys) {
      if (key.startsWith("__")) continue;
      if (JSON.stringify(values[key]) !== JSON.stringify(initial[key])) count += 1;
    }
    return count;
  }

  function create(ctx) {
    const { esc, icon, api, toast, openModal, closeModal, confirmDialog } = ctx;

    function statusPath(inst, kind) {
      return `/api/instances/${encodeURIComponent(inst.id)}/consoles/${kind}/status`;
    }

    function configPath(inst, pluginId) {
      return `/api/instances/${encodeURIComponent(inst.id)}/plugins/${encodeURIComponent(pluginId)}/config`;
    }

    function pluginPath(inst, pluginId, suffix = "") {
      return `/api/instances/${encodeURIComponent(inst.id)}/plugins/${encodeURIComponent(pluginId)}${suffix}`;
    }

    function labelsFor(kind) {
      return kind === "bili" ? BILI_LABELS : DOUYIN_LABELS;
    }

    function groupsFor(kind) {
      return kind === "bili" ? BILI_GROUPS : DOUYIN_GROUPS;
    }

    function schemaFor(metadata, pluginId) {
      if (!metadata || typeof metadata !== "object") return {};
      const exact = metadata[pluginId];
      if (exact && exact.items) return exact.items;
      const first = Object.values(metadata)[0];
      return first && first.items ? first.items : {};
    }

    function extractValues(config, schema, keys) {
      const values = {};
      for (const key of keys) {
        const def = schema[key] || {};
        let value = config[key];
        if (value === undefined || value === null) value = def.default;
        if (def.type === "bool" || typeof value === "boolean") value = Boolean(value);
        else if (def.type === "int" || def.type === "float" || typeof value === "number") value = value === undefined || value === "" ? "" : String(value);
        else if (def.type === "list" || Array.isArray(value)) value = Array.isArray(value) ? value.map((item) => String(item)) : [];
        else value = value === undefined ? "" : String(value);
        values[key] = value;
      }
      return values;
    }

    function allKeys(kind) {
      return groupsFor(kind).flatMap((group) => group.keys);
    }

    function pluginMeta(kind) {
      return PLUGINS[kind];
    }

    function fieldDef(kind, key, schema) {
      const def = schema[key] || {};
      const labels = labelsFor(kind);
      let type = def.type || "string";
      if (def._special || type === "object") type = "string";
      let help = String(def.hint || "");
      if (!help && def.description) help = String(def.description);
      return {
        key,
        type,
        label: labels[key] || def.description || key,
        help,
        options: Array.isArray(def.options) ? def.options : [],
        range: RANGES[key] || null,
      };
    }

    function controlFor(ui, def, value) {
      const disabled = ui.busy ? " disabled" : "";
      if (def.type === "bool") {
        const checked = value ? " checked" : "";
        return `<label class="console-switch"><input type="checkbox" data-key="${esc(def.key)}"${checked}${disabled}><span class="console-switch-track"></span><span class="console-switch-text">${value ? "已开启" : "已关闭"}</span></label>`;
      }
      if (def.options.length) {
        return `<select data-key="${esc(def.key)}"${disabled}>${def.options.map((option) => {
          const text = typeof option === "object" ? (option.label || option.value) : option;
          const optValue = typeof option === "object" ? option.value : option;
          return `<option value="${esc(optValue)}"${String(value) === String(optValue) ? " selected" : ""}>${esc(text)}</option>`;
        }).join("")}</select>`;
      }
      if (def.type === "int" || def.type === "float") {
        const range = def.range ? ` min="${def.range[0]}" max="${def.range[1]}"` : "";
        const step = def.type === "float" ? "0.1" : "1";
        return `<input type="number" data-key="${esc(def.key)}" value="${esc(value)}"${range} step="${step}"${disabled}>`;
      }
      return `<input type="text" data-key="${esc(def.key)}" value="${esc(value)}"${disabled}>`;
    }

    function renderList(ui, def, value) {
      const disabled = ui.busy ? " disabled" : "";
      const items = Array.isArray(value) ? value : [];
      if (def.key === "FIXED_PROACTIVE_WINDOWS" && ui.kind === "bili") {
        return `<div class="console-list" data-list="${esc(def.key)}">
          ${items.map((item, index) => {
            const parts = String(item || "").split(/\s*-\s*/);
            return `<div class="console-slot">
              <input type="text" data-window="${index}" data-part="start" value="${esc(parts[0] || "")}" placeholder="10:00"${disabled}>
              <span class="console-dash">—</span>
              <input type="text" data-window="${index}" data-part="end" value="${esc(parts[1] || "")}" placeholder="11:30"${disabled}>
              <button type="button" class="btn sm ghost icon-only" data-remove-window="${index}" title="删除"${disabled}>${icon("trash")}</button>
            </div>`;
          }).join("")}
          <button type="button" class="btn sm ghost" data-add-window ${items.length >= 12 ? "disabled" : ""}>${icon("plus")}添加时间段</button>
        </div>`;
      }
      if (TIME_LIST_KEYS.has(def.key)) {
        const max = ui.kind === "douyin" ? 3 : 12;
        return `<div class="console-list" data-list="${esc(def.key)}">
          ${items.map((item, index) => `<div class="console-slot">
            <input type="text" data-time="${esc(def.key)}" data-index="${index}" value="${esc(item)}" placeholder="HH:MM"${disabled}>
            <button type="button" class="btn sm ghost icon-only" data-remove-time="${esc(def.key)}" data-index="${index}" title="删除"${disabled}>${icon("trash")}</button>
          </div>`).join("")}
          <button type="button" class="btn sm ghost" data-add-time="${esc(def.key)}" ${items.length >= max ? "disabled" : ""}>${icon("plus")}添加时隙</button>
          <span class="console-help">最多 ${max} 个；格式 HH:MM。</span>
        </div>`;
      }
      const text = items.join("\n");
      return `<textarea data-list-text="${esc(def.key)}" rows="3" placeholder="每行一项"${disabled}>${esc(text)}</textarea>`;
    }

    function renderField(ui, key) {
      const def = fieldDef(ui.kind, key, ui.schema);
      const value = ui.values[key];
      const span = def.type === "list" ? " console-span" : "";
      const control = def.type === "list" ? renderList(ui, def, value) : controlFor(ui, def, value);
      const help = def.help ? `<span class="console-help">${esc(def.help)}</span>` : "";
      return `<div class="console-field${span}" data-field="${esc(key)}">
        <label>${esc(def.label)}</label>
        ${control}
        ${help}
      </div>`;
    }

    function renderGenericGroup(ui, group, note = "") {
      return `<section class="card console-card">
        <div class="console-card-head"><h3>${esc(group.title)}</h3></div>
        ${note}
        <div class="console-fields">${group.keys.map((key) => renderField(ui, key)).join("")}</div>
      </section>`;
    }

    function renderBiliFrequency(ui) {
      const mode = deriveBiliMode(ui.values);
      const options = [["windows", "固定时间段"], ["times", "精确时刻"], ["auto", "Bot 自主日程"]];
      const modeSelect = `<div class="console-field console-span"><label>排期模式</label>
        <select data-mode ${ui.busy ? "disabled" : ""}>${options.map(([value, text]) => `<option value="${value}"${mode === value ? " selected" : ""}>${text}</option>`).join("")}</select>
        <span class="console-help">插件优先使用时间段；时间段为空时才回退到精确时刻。自主日程开启后固定列表不生效。</span></div>`;
      const common = ["ENABLE_PROACTIVE", "PROACTIVE_TIMES_COUNT", "PROACTIVE_VIDEO_COUNT", "PROACTIVE_DAILY_LIMIT"]
        .map((key) => renderField(ui, key)).join("");
      let modeFields = "";
      if (mode === "auto") {
        modeFields = ["AUTONOMOUS_ACTIVITY_LEVEL", "SLEEP_START", "SLEEP_END", "AUTONOMOUS_MIN_ACTION_GAP_MINUTES"]
          .map((key) => renderField(ui, key)).join("");
      } else if (mode === "windows") {
        modeFields = renderField(ui, "FIXED_PROACTIVE_WINDOWS");
        modeFields += `<div class="console-field console-span console-hint-line"><span class="console-help">精确时刻列表当前不生效；如需按精确时刻执行，请把模式切换为“精确时刻”。</span></div>`;
      } else {
        modeFields = renderField(ui, "FIXED_PROACTIVE_TIMES");
        modeFields += `<div class="console-field console-span console-hint-line"><span class="console-help">固定时间段为空，当前按精确时刻执行。</span></div>`;
      }
      return `<section class="card console-card">
        <div class="console-card-head"><h3>主动看片频率</h3><span>${mode === "auto" ? "自主日程" : mode === "windows" ? "时间段" : "精确时刻"}</span></div>
        <div class="console-fields">${modeSelect}${common}${modeFields}</div>
        <div class="console-preview" id="console-preview"></div>
      </section>`;
    }

    function renderDouyinFrequency(ui) {
      const key = "qq_proactive_times";
      const common = ["qq_proactive_enabled", "OWNER_QQ_UMO", key, "qq_proactive_daily_limit", "qq_proactive_max_seconds"]
        .map((item) => renderField(ui, item)).join("");
      return `<section class="card console-card">
        <div class="console-card-head"><h3>主动刷频率</h3><span>时隙后 30 分钟内触发</span></div>
        <div class="console-fields">${common}</div>
        <div class="console-preview" id="console-preview"></div>
      </section>`;
    }

    function renderHeader(ui) {
      const meta = pluginMeta(ui.kind);
      const plugin = ui.plugin || {};
      const enabled = plugin.enabled ? '<span class="badge ok">已启用</span>' : '<span class="badge bad">已停用</span>';
      const version = plugin.version ? `<span class="console-version">v${esc(plugin.version)}</span>` : "";
      return `<div class="console-head">
        <div>
          <div class="console-kicker">${esc(ui.inst.name)} · ${esc(plugin.display_name || plugin.name || meta.id)} ${version}</div>
          <h2>${esc(meta.title)}</h2>
          <p>${esc(meta.sub)}</p>
        </div>
        <div class="console-actions">
          ${enabled}
          <button class="btn primary" data-run>${icon("play")}立即执行</button>
          <button class="btn ghost" data-reload>${icon("restart")}重载</button>
          <button class="btn ghost" data-raw>${icon("edit")}原始 JSON</button>
          <button class="btn ghost icon-only" data-refresh title="刷新">${icon("refresh")}</button>
        </div>
      </div>`;
    }

    function statCard(label, value, hint) {
      return `<div class="stat"><div class="k">${esc(label)}</div><div class="v">${value}</div><div class="hint">${hint || ""}</div></div>`;
    }

    function renderBiliStatus(ui) {
      const s = ui.status || {};
      const snap = ui.snapshot || {};
      const max = Number(s.proactive_max || 0);
      const used = Number(s.proactive_used || 0);
      const warnings = Array.isArray(s.warnings) ? s.warnings : [];
      const recent = Array.isArray(snap.proactive) ? snap.proactive.slice(0, 3) : [];
      return `<div class="stat-grid console-stats">
        ${statCard("今日主动", `${used}<small>${max ? "/ " + max : " / 不限"}</small>`, `下一事件：${esc(s.next_action || "暂无")}`)}
        ${statCard("运行状态", s.running ? "运行中" : "未运行", s.account_connected ? "B站账号已连接" : "B站账号未连接")}
        ${statCard("今日失败", String(s.failed_today || 0), warnings[0] ? esc(warnings[0].title || "") : "暂无警告")}
        ${statCard("最近主动", String(recent.length), recent[0] ? esc(recent[0].title || "").slice(0, 28) : "暂无记录")}
      </div>
      ${warnings.length ? `<div class="console-warn">${warnings.slice(0, 3).map((item) => `<div>${esc(item.title || "")}：${esc(item.detail || "")}</div>`).join("")}</div>` : ""}
      ${recent.length ? `<section class="card console-card console-recent"><div class="console-card-head"><h3>最近主动推荐</h3></div>${recent.map((item) => `<div class="console-recent-row"><span>${esc(item.time || "")}</span><b>${esc(item.title || item.bvid || "")}</b>${item.comment ? `<em>${esc(item.comment)}</em>` : ""}</div>`).join("")}</section>` : ""}`;
    }

    function renderDouyinStatus(ui) {
      const s = ui.status || {};
      const p = s.proactive || {};
      const binding = s.binding && s.binding.peer ? s.binding.peer.name : "";
      const last = p.last_result || null;
      const times = Array.isArray(p.times) ? p.times : [];
      return `<div class="stat-grid console-stats">
        ${statCard("今日已刷", `${Number(p.used_today || 0)}<small>/ ${Number(p.daily_limit || 0)}</small>`, `时隙：${esc(times.join("、") || "默认")}`)}
        ${statCard("下一时隙", esc(nextDouyinSlot(times)), "时隙后 30 分钟内触发")}
        ${statCard("运行环境", s.browser_running ? "浏览器运行" : "浏览器未运行", binding ? `绑定：${esc(binding)}` : "未绑定私信")}
        ${statCard("上次结果", last ? esc(last.state || "—") : "暂无", last ? esc(String(last.message || "").slice(0, 30)) : "还没有主动刷记录")}
      </div>
      ${p.last_error ? `<div class="console-warn"><div>最近错误：${esc(p.last_error)}</div></div>` : ""}
      ${last ? `<section class="card console-card console-recent"><div class="console-card-head"><h3>上次主动刷</h3></div>
        <div class="console-recent-row"><span>${esc(last.slot || "")}</span><b>${esc(last.message || "")}</b>${last.url ? `<a href="${esc(last.url)}" target="_blank" rel="noreferrer">作品</a>` : ""}</div></section>` : ""}`;
    }

    function renderForm(ui) {
      const groups = groupsFor(ui.kind);
      const frequency = ui.kind === "bili" ? renderBiliFrequency(ui) : renderDouyinFrequency(ui);
      const rest = groups.filter((group) => group.id !== "frequency").map((group) => {
        let note = "";
        if (ui.kind === "douyin" && group.id === "comments") {
          note = `<div class="console-note">客户端评论需要客户端停在视频详情页、消息面板为全高布局；公开评论总开关关闭时不会执行。</div>`;
        }
        return renderGenericGroup(ui, group, note);
      }).join("");
      return `<div class="console-grid">${frequency}${rest}
        <section class="card console-card console-advanced">
          <div class="console-card-head"><h3>高级设置</h3></div>
          <p class="console-help">Cookie、provider、提示词、白名单等字段不在常用分组中，使用原始 JSON 编辑。保存会保留未展示的字段。</p>
          <button class="btn ghost" data-raw>${icon("edit")}打开原始 JSON</button>
        </section>
      </div>`;
    }

    function renderSaveBar(ui) {
      return `<div class="console-savebar" id="console-savebar">
        <div class="console-save-state">
          <b id="console-save-count">没有未保存修改</b>
          <span id="console-warn-count"></span>
          <span class="console-save-note">保存后 AstrBot 会重载插件，可能中断当前任务。</span>
        </div>
        <div class="console-save-actions">
          <button class="btn primary" data-save disabled>保存并生效</button>
        </div>
      </div>`;
    }

    function renderAll(ui) {
      const meta = pluginMeta(ui.kind);
      ui.view.innerHTML = `
        <div class="console-instance-chips">${ctx.state.instances.map((inst) =>
          `<button class="chip ${inst.id === ui.inst.id ? "active" : ""}" data-console-inst="${esc(inst.id)}">${esc(inst.name)}${inst.status?.running ? "" : "（未运行）"}</button>`).join("")}</div>
        ${renderHeader(ui)}
        ${ui.kind === "bili" ? renderBiliStatus(ui) : renderDouyinStatus(ui)}
        ${ui.statusError ? `<div class="console-warn"><div>插件状态读取失败：${esc(ui.statusError)}</div></div>` : ""}
        <div id="console-warnings"></div>
        ${renderForm(ui)}
        ${renderSaveBar(ui)}`;
      updateChrome(ui);
    }

    function previewHtml(ui) {
      if (ui.kind === "douyin") {
        const values = ui.values;
        const parsed = parseTimes(values.qq_proactive_times, 3);
        const times = parsed.error ? "（时隙格式有误）" : parsed.times.join("、") || "默认 12:30、20:30";
        const status = ui.status?.proactive || {};
        return `<div><b>当前配置</b>：时隙 ${esc(times)}；每天最多 ${esc(values.qq_proactive_daily_limit)} 次；每次最长 ${esc(values.qq_proactive_max_seconds)} 秒；时隙后 30 分钟内触发。</div>
          <div class="console-help">今日已用 ${esc(status.used_today ?? "—")}/${esc(status.daily_limit ?? "—")}；下一时隙：${esc(nextDouyinSlot(parsed.times))}。</div>`;
      }
      const v = ui.values;
      const mode = deriveBiliMode(v);
      const rounds = Number(v.PROACTIVE_TIMES_COUNT) || 0;
      const videos = Number(v.PROACTIVE_VIDEO_COUNT) || 0;
      const daily = Number(v.PROACTIVE_DAILY_LIMIT) || 0;
      const windows = (v.FIXED_PROACTIVE_WINDOWS || []).filter((item) => String(item || "").trim());
      const times = (v.FIXED_PROACTIVE_TIMES || []).filter((item) => String(item || "").trim());
      let plan = "";
      if (mode === "auto") {
        plan = `Bot 自主日程：每天最多 ${rounds} 轮；活动度 ${v.AUTONOMOUS_ACTIVITY_LEVEL}/100；睡眠 ${v.SLEEP_START}–${v.SLEEP_END} 点；事件间隔 ≥ ${v.AUTONOMOUS_MIN_ACTION_GAP_MINUTES} 分钟。`;
      } else if (mode === "windows") {
        plan = `固定时间段：${windows.join("、") || "未填写"}；每天最多 ${rounds} 轮（超出截断）；每轮 ${videos} 条；日上限 ${daily || "不限"}。`;
      } else {
        plan = `精确时刻：${times.join("、") || "未填写"}；每天最多 ${rounds} 轮（超出截断）；每轮 ${videos} 条；日上限 ${daily || "不限"}。`;
      }
      return `<div><b>当前配置</b>：${esc(plan)}</div>
        <div class="console-help">下一事件：${esc(ui.status?.next_action || "暂无")}；今日已看 ${esc(ui.status?.proactive_used ?? "—")}${ui.status?.proactive_max ? " / " + ui.status.proactive_max : " / 不限"}。</div>`;
    }

    function updateChrome(ui) {
      if (!ui.view || !ui.view.isConnected) return;
      const validation = ui.kind === "bili" ? validateBili(ui.values) : validateDouyin(ui.values);
      ui.validation = validation;
      const preview = ui.view.querySelector("#console-preview");
      if (preview) preview.innerHTML = previewHtml(ui);
      const dirty = countDirty(ui.values, ui.initialValues);
      const count = ui.view.querySelector("#console-save-count");
      if (count) count.textContent = dirty ? `${dirty} 项未保存` : "没有未保存修改";
      const warnCount = ui.view.querySelector("#console-warn-count");
      const warnings = Object.values(validation.warnings || {});
      if (warnCount) warnCount.textContent = warnings.length ? ` · ${warnings.length} 条提示` : "";
      for (const key of allKeys(ui.kind)) {
        const node = ui.view.querySelector(`[data-field="${key}"]`);
        if (node) node.classList.toggle("invalid", Boolean(validation.errors[key]));
      }
      const warnBox = ui.view.querySelector("#console-warnings");
      if (warnBox) {
        warnBox.innerHTML = warnings.length
          ? `<div class="console-warn">${warnings.slice(0, 4).map((text) => `<div>${esc(text)}</div>`).join("")}</div>`
          : "";
      }
      const save = ui.view.querySelector("[data-save]");
      if (save) save.disabled = ui.busy || dirty === 0 || Object.keys(validation.errors || {}).length > 0;
      const run = ui.view.querySelector("[data-run]");
      if (run) {
        const reason = runBlockedReason(ui);
        run.disabled = ui.busy || Boolean(reason);
        run.title = reason || "立即执行一次";
      }
    }

    function runBlockedReason(ui) {
      if (ui.kind === "bili") {
        if (!ui.values.ENABLE_PROACTIVE) return "主动看片未开启";
        if (ui.status && ui.status.account_connected === false) return "B站账号未连接";
        return "";
      }
      if (!ui.values.qq_proactive_enabled) return "主动刷未开启";
      if (!String(ui.values.OWNER_QQ_UMO || "").trim()) return "未配置 QQ 汇报目标";
      if (ui.status && ui.status.processing_message) return "机器人正在处理其他任务";
      return "";
    }

    function findValueOwner(target) {
      if (target.dataset.key) return { key: target.dataset.key, kind: "key" };
      if (target.dataset.window !== undefined) return { key: "FIXED_PROACTIVE_WINDOWS", kind: "window", index: Number(target.dataset.window), part: target.dataset.part };
      if (target.dataset.time !== undefined) return { key: target.dataset.time, kind: "time", index: Number(target.dataset.index) };
      if (target.dataset.listText) return { key: target.dataset.listText, kind: "list" };
      return null;
    }

    function applyField(ui, target) {
      const owner = findValueOwner(target);
      if (!owner) return;
      if (owner.kind === "key") {
        const def = (ui.schema && ui.schema[owner.key]) || {};
        if (target.type === "checkbox") ui.values[owner.key] = target.checked;
        else if (def.type === "int" || def.type === "float") ui.values[owner.key] = target.value;
        else ui.values[owner.key] = target.value;
      } else if (owner.kind === "window") {
        const rows = Array.isArray(ui.values[owner.key]) ? ui.values[owner.key].slice() : [];
        const parts = String(rows[owner.index] || "").split(/\s*-\s*/);
        const start = owner.part === "start" ? target.value : (parts[0] || "");
        const end = owner.part === "end" ? target.value : (parts[1] || "");
        rows[owner.index] = `${start}-${end}`;
        ui.values[owner.key] = rows;
      } else if (owner.kind === "time") {
        const rows = Array.isArray(ui.values[owner.key]) ? ui.values[owner.key].slice() : [];
        rows[owner.index] = target.value;
        ui.values[owner.key] = rows;
      } else if (owner.kind === "list") {
        ui.values[owner.key] = target.value.split(/[\n,，]+/).map((item) => item.trim()).filter(Boolean);
      }
      if (owner.kind === "key" && target.type === "checkbox") {
        const text = target.parentElement?.querySelector(".console-switch-text");
        if (text) text.textContent = target.checked ? "已开启" : "已关闭";
      }
      updateChrome(ui);
    }

    async function load(ui) {
      ui.loading = true;
      try {
        const inst = ui.inst;
        if (!inst.status?.running) {
          ui.view.innerHTML = renderInstanceOffline(inst);
          return;
        }
        const [plugins, configPayload, statusPayload] = await Promise.all([
          api(`/api/instances/${encodeURIComponent(inst.id)}/plugins`),
          api(configPath(inst, ui.pluginId)),
          api(statusPath(inst, ui.kind)).catch((err) => ({ __error: err.message })),
        ]);
        const plugin = (Array.isArray(plugins) ? plugins : []).find((item) => item.id === ui.pluginId || item.name === ui.pluginId);
        if (!plugin) {
          ui.view.innerHTML = renderMissingPlugin(ui);
          return;
        }
        ui.plugin = plugin;
        ui.config = configPayload.config || {};
        ui.schema = schemaFor(configPayload.metadata, ui.pluginId);
        ui.original = clone(ui.config);
        ui.values = extractValues(ui.config, ui.schema, allKeys(ui.kind));
        ui.initialValues = clone(ui.values);
        if (statusPayload && statusPayload.__error) {
          ui.status = null;
          ui.snapshot = null;
          ui.statusError = statusPayload.__error;
        } else {
          ui.status = statusPayload?.status || null;
          ui.snapshot = statusPayload?.snapshot || null;
          ui.statusError = "";
        }
        if (!plugin.enabled) {
          ui.view.innerHTML = renderDisabledPlugin(ui);
          return;
        }
        renderAll(ui);
      } catch (err) {
        ui.view.innerHTML = `<div class="empty">${icon("alert")}<h4>控制台加载失败</h4><p>${esc(err.message)}</p><button class="btn ghost" data-console-retry>重试</button></div>`;
      } finally {
        ui.loading = false;
      }
    }

    function renderInstanceOffline(inst) {
      return `<div class="empty">${icon("play")}<h4>机器人未运行</h4><p>${esc(inst.name)} 当前未运行，启动后再打开控制台。</p><a class="btn ghost" href="#/bots">去机器人页</a></div>`;
    }

    function renderMissingPlugin(ui) {
      return `<div class="empty">${icon("market")}<h4>没有安装 ${esc(pluginMeta(ui.kind).title)} 所需插件</h4><p>请先在插件市场安装 ${esc(ui.pluginId)}。</p><a class="btn ghost" href="#/market">去插件市场</a></div>`;
    }

    function renderDisabledPlugin(ui) {
      return `<div class="empty">${icon("alert")}<h4>插件已停用</h4><p>${esc(ui.pluginId)} 已安装但未启用。</p><button class="btn primary" data-enable>启用插件</button></div>`;
    }

    async function save(ui) {
      const validation = ui.kind === "bili" ? validateBili(ui.values) : validateDouyin(ui.values);
      const errorKeys = Object.keys(validation.errors || {});
      if (errorKeys.length) {
        updateChrome(ui);
        const node = ui.view.querySelector(`[data-field="${errorKeys[0]}"]`);
        if (node) node.scrollIntoView({ block: "center", behavior: "smooth" });
        toast(validation.errors[errorKeys[0]], "err");
        return;
      }
      ui.busy = true;
      updateChrome(ui);
      try {
        const payload = buildConfigPayload(ui.original, ui.values, ui.schema);
        await api(configPath(ui.inst, ui.pluginId), { method: "PUT", body: { config: payload } });
        toast("配置已保存并生效");
        await load(ui);
      } catch (err) {
        toast(err.message, "err");
      } finally {
        ui.busy = false;
        updateChrome(ui);
      }
    }

    async function runNow(ui) {
      const reason = runBlockedReason(ui);
      if (reason) {
        toast(reason, "warn");
        return;
      }
      const dirty = countDirty(ui.values, ui.initialValues);
      const note = dirty ? "\n\n当前有未保存修改，立即执行会使用已保存配置。" : "";
      let text = "";
      if (ui.kind === "bili") {
        const active = [
          ui.values.PROACTIVE_LIKE && "点赞",
          ui.values.PROACTIVE_FAV && "收藏",
          ui.values.PROACTIVE_COIN && "投币",
          ui.values.PROACTIVE_COMMENT && "评论",
          ui.values.PROACTIVE_FOLLOW && "关注",
        ].filter(Boolean).join("、") || "无";
        const status = ui.status || {};
        text = `会立即看 1 个 B站视频，并按当前互动开关执行（已开启：${active}；达到评分阈值才动作）。\n今日已看 ${status.proactive_used ?? "—"}${status.proactive_max ? " / " + status.proactive_max : " / 不限"}。${note}`;
      } else {
        const p = ui.status?.proactive || {};
        text = `会立即看 1 条抖音并汇报到 QQ（${ui.values.OWNER_QQ_UMO || "未配置"}）。\n今日已用 ${p.used_today ?? "—"} / ${p.daily_limit ?? "—"}，受每日上限和开关限制。${note}`;
      }
      const ok = await confirmDialog(`立即执行 · ${pluginMeta(ui.kind).title}`, text, false);
      if (!ok) return;
      ui.busy = true;
      updateChrome(ui);
      const before = Number(ui.status?.proactive_used || 0);
      try {
        if (ui.kind === "douyin") {
          openModal({
            title: "正在看视频",
            sub: "立即执行 · 抖音",
            body: `<div class="console-running">${icon("pulse")}<b>正在观看并生成 QQ 汇报…</b><p>通常 1–3 分钟；失败会重试，可能更久。关闭此窗口不会取消执行。</p></div>`,
            footer: `<button class="btn ghost" data-close>后台运行</button>`,
          });
          const receipt = await api(`/api/instances/${encodeURIComponent(ui.inst.id)}/consoles/douyin/run`, { method: "POST" });
          closeModal();
          openModal({
            title: "主动刷完成",
            sub: "真实回执",
            body: `<div class="console-result">
              <div><span>状态</span><b>${esc(receipt?.state || "—")}</b></div>
              <div><span>作品</span><b>${esc(receipt?.post_id || "—")}</b></div>
              <div><span>QQ 汇报</span><b>${esc(receipt?.message || "—")}</b></div>
            </div>`,
            footer: `<button class="btn ghost" data-close>关闭</button>`,
          });
          toast("抖音主动刷已完成");
        } else {
          const result = await api(`/api/instances/${encodeURIComponent(ui.inst.id)}/consoles/bili/run`, { method: "POST" });
          toast(result?.started ? "B站主动看片已触发" : "B站主动看片请求已提交");
          pollBili(ui, before);
        }
        await load(ui);
      } catch (err) {
        closeModal();
        toast(err.message, "err");
      } finally {
        ui.busy = false;
        updateChrome(ui);
      }
    }

    function pollBili(ui, before) {
      let attempts = 0;
      const timer = setInterval(async () => {
        attempts += 1;
        if (!ui.view || !ui.view.isConnected || ui.view._consoleUI !== ui) {
          clearInterval(timer);
          return;
        }
        try {
          const payload = await api(statusPath(ui.inst, "bili"));
          const used = Number(payload?.status?.proactive_used || 0);
          if (used > before) {
            clearInterval(timer);
            toast("B站主动看片已完成");
            await load(ui);
            return;
          }
        } catch (_) {
          /* 状态暂时不可读时继续等 */
        }
        if (attempts >= 24) {
          clearInterval(timer);
          toast("已触发，仍在运行或尚未产生新记录；请稍后刷新", "warn");
          await load(ui);
        }
      }, 5000);
    }

    function setBiliMode(ui, mode) {
      if (mode === "auto") {
        ui.values.ENABLE_AUTONOMOUS_DAILY_PLAN = true;
      } else if (mode === "windows") {
        ui.values.ENABLE_AUTONOMOUS_DAILY_PLAN = false;
        if (!(ui.values.FIXED_PROACTIVE_WINDOWS || []).filter((item) => String(item || "").trim()).length) {
          ui.values.FIXED_PROACTIVE_WINDOWS = ["10:00-11:30", "19:00-21:00"];
        }
      } else if (mode === "times") {
        ui.values.ENABLE_AUTONOMOUS_DAILY_PLAN = false;
        ui.values.FIXED_PROACTIVE_WINDOWS = [];
        if (!(ui.values.FIXED_PROACTIVE_TIMES || []).filter((item) => String(item || "").trim()).length) {
          ui.values.FIXED_PROACTIVE_TIMES = ["10:30", "19:30"];
        }
      }
      renderAll(ui);
    }

    function bind(view) {
      if (view._consoleBound) return;
      view._consoleBound = true;
      view.addEventListener("input", (event) => {
        const ui = view._consoleUI;
        if (ui) applyField(ui, event.target);
      });
      view.addEventListener("change", (event) => {
        const ui = view._consoleUI;
        if (!ui) return;
        if (event.target.dataset.mode !== undefined) {
          setBiliMode(ui, event.target.value);
          return;
        }
        applyField(ui, event.target);
      });
      view.addEventListener("click", async (event) => {
        const ui = view._consoleUI;
        if (!ui) return;
        const target = event.target.closest("[data-add-window],[data-remove-window],[data-add-time],[data-remove-time],[data-save],[data-run],[data-reload],[data-raw],[data-refresh],[data-enable],[data-console-inst],[data-console-retry]");
        if (!target) return;
        if (target.dataset.addWindow !== undefined) {
          const rows = Array.isArray(ui.values.FIXED_PROACTIVE_WINDOWS) ? ui.values.FIXED_PROACTIVE_WINDOWS.slice() : [];
          if (rows.length < 12) rows.push("10:00-11:30");
          ui.values.FIXED_PROACTIVE_WINDOWS = rows;
          renderAll(ui);
          return;
        }
        if (target.dataset.removeWindow !== undefined) {
          const rows = Array.isArray(ui.values.FIXED_PROACTIVE_WINDOWS) ? ui.values.FIXED_PROACTIVE_WINDOWS.slice() : [];
          rows.splice(Number(target.dataset.removeWindow), 1);
          ui.values.FIXED_PROACTIVE_WINDOWS = rows;
          renderAll(ui);
          return;
        }
        if (target.dataset.addTime !== undefined) {
          const key = target.dataset.addTime;
          const max = ui.kind === "douyin" ? 3 : 12;
          const rows = Array.isArray(ui.values[key]) ? ui.values[key].slice() : [];
          if (rows.length < max) rows.push(ui.kind === "douyin" ? "12:30" : "10:30");
          ui.values[key] = rows;
          renderAll(ui);
          return;
        }
        if (target.dataset.removeTime !== undefined) {
          const key = target.dataset.removeTime;
          const rows = Array.isArray(ui.values[key]) ? ui.values[key].slice() : [];
          rows.splice(Number(target.dataset.index), 1);
          ui.values[key] = rows;
          renderAll(ui);
          return;
        }
        if (target.dataset.save !== undefined) {
          await save(ui);
          return;
        }
        if (target.dataset.run !== undefined) {
          await runNow(ui);
          return;
        }
        if (target.dataset.reload !== undefined) {
          const ok = await confirmDialog("重载插件", "重载会重启插件并短暂中断当前任务，确定继续？", false);
          if (!ok) return;
          try {
            await api(pluginPath(ui.inst, ui.pluginId, "/reload"), { method: "POST" });
            toast("插件已重载");
            await load(ui);
          } catch (err) {
            toast(err.message, "err");
          }
          return;
        }
        if (target.dataset.raw !== undefined) {
          ctx.pluginConfigModal(ui.inst, ui.pluginId, ui.plugin?.display_name || ui.plugin?.name || ui.pluginId, () => load(ui));
          return;
        }
        if (target.dataset.refresh !== undefined) {
          await load(ui);
          return;
        }
        if (target.dataset.enable !== undefined) {
          try {
            await api(pluginPath(ui.inst, ui.pluginId, "/enabled"), { method: "PATCH", body: { enabled: true } });
            toast("插件已启用");
            await load(ui);
          } catch (err) {
            toast(err.message, "err");
          }
          return;
        }
        if (target.dataset.consoleInst !== undefined) {
          ctx.state.pluginInst = target.dataset.consoleInst;
          await renderConsole(ui.view, ui.kind);
          return;
        }
        if (target.dataset.consoleRetry !== undefined) {
          await load(ui);
        }
      });
    }

    async function renderConsole(view, kind) {
      const meta = pluginMeta(kind);
      if (!ctx.state.instances.length) {
        view.innerHTML = `<div class="empty">${icon("bots")}<h4>没有可用实例</h4><p>请先新增或接入机器人。</p></div>`;
        return;
      }
      const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(ctx.state.instances);
      if (focusHit) {
        ctx.state.pluginInst = String(focusHit.id);
      } else if (!ctx.state.pluginInst || !ctx.state.instances.find((item) => item.id === ctx.state.pluginInst)) {
        ctx.state.pluginInst = ((globalThis.ManagerFocus && globalThis.ManagerFocus.pick(ctx.state.instances)) || ctx.state.instances[0]).id;
      }
      const inst = ctx.state.instances.find((item) => item.id === ctx.state.pluginInst) || ctx.state.instances[0];
      const ui = {
        kind,
        pluginId: meta.id,
        inst,
        view,
        plugin: null,
        config: {},
        schema: {},
        status: null,
        snapshot: null,
        statusError: "",
        values: {},
        initialValues: {},
        busy: false,
        loading: false,
      };
      view._consoleUI = ui;
      bind(view);
      view.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
      await load(ui);
    }

    return { viewBili: (view) => renderConsole(view, "bili"), viewDouyin: (view) => renderConsole(view, "douyin") };
  }

  return {
    create,
    parseTimes,
    parseWindows,
    deriveBiliMode,
    validateBili,
    validateDouyin,
    buildConfigPayload,
    countDirty,
    nextDouyinSlot,
  };
});
