/* 牧鱼 · AstrBot 多机管理台 — 前端应用 */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));

const icon = (name, cls = "icon") => `<svg class="${cls}"><use href="#i-${name}"/></svg>`;

const initials = (name) => {
  const text = String(name || "?").trim();
  return text.slice(0, 2);
};

const avatarStyle = (color) =>
  `background:linear-gradient(135deg, ${color}, ${color}aa)`;


/* ------------------------------------------------------------------ api */

async function api(path, { method = "GET", body } = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  let json = null;
  try { json = await res.json(); } catch (_) { /* ignore */ }
  if (!res.ok) {
    const message = json?.message || json?.detail || `请求失败（HTTP ${res.status}）`;
    throw new Error(message);
  }
  if (json && json.status === "error") throw new Error(json.message || "请求失败");
  return json?.data ?? json;
}

async function postForm(path, formData) {
  const res = await fetch(path, { method: "POST", body: formData });
  let json = null;
  try { json = await res.json(); } catch (_) { /* ignore */ }
  if (!res.ok) {
    const message = json?.message || json?.detail || `请求失败（HTTP ${res.status}）`;
    throw new Error(message);
  }
  if (json && json.status === "error") throw new Error(json.message || "请求失败");
  return json?.data ?? json;
}


/* ---------------------------------------------------------------- state */

const state = {
  settings: {},
  instances: [],
  env: {},
  summaries: {},
  route: "overview",
  market: { q: "", category: "全部", page: 1, size: 24, total: 0, pages: 1, items: [] },
  marketTab: "market",
  installedFor: "",
  personas: {},
  providers: {},
  modelInst: "",
  pluginInst: "",
  pluginQuery: "",
  pluginList: {},
  learnInst: "",
  learnSource: "",
  learnKey: "",
  learnNoteKey: "",
  learnSavedNote: "",
  learnLimit: 200,
  learnProvider: "",
  learnData: { qq: [], bili: [] },
  learnProvidersList: [],
  autoTimer: null,
  autoCfg: null,
  logInst: "",
  logSource: "bot",
  logTimer: null,
  logAuto: true,
  thinkES: null,
  thinkRuns: new Map(),
  thinkNodes: {},
  thinkDirty: new Set(),
  thinkRaf: null,
  thinkTimer: null,
  busy: false,
};

const consoleUI = window.ManagerConsoles
  ? window.ManagerConsoles.create({
      state,
      api,
      esc,
      icon,
      toast,
      openModal,
      closeModal,
      confirmDialog,
      pluginConfigModal: (inst, pluginId, name, onSaved) => pluginConfigModal(inst, pluginId, name, onSaved),
    })
  : null;

const memoryUI = window.ManagerMemory
  ? window.ManagerMemory.create({
      state,
      api,
      esc,
      icon,
      toast,
      openModal,
      closeModal,
      confirmDialog,
      pluginConfigModal: (inst, pluginId, name, onSaved) => pluginConfigModal(inst, pluginId, name, onSaved),
    })
  : null;

const dshUI = window.ManagerDsh
  ? window.ManagerDsh.create({
      state,
      api,
      esc,
      icon,
      toast,
      openModal,
      closeModal,
      confirmDialog,
    })
  : null;

const healthUI = window.ManagerHealth
  ? window.ManagerHealth.create({ api, esc, icon, toast })
  : null;

const approvalsUI = window.ManagerApprovals
  ? window.ManagerApprovals.create({ api, esc, icon, toast })
  : null;

const tasksUI = window.ManagerTasks
  ? window.ManagerTasks.create({ api, esc, icon, toast, openModal, closeModal, confirmDialog })
  : null;

const automationCenterUI = window.ManagerAutomationCenter
  ? window.ManagerAutomationCenter.create({ api, esc, icon, toast, openModal, closeModal, confirmDialog })
  : null;

const duetUI = window.ManagerDuet
  ? window.ManagerDuet.create({ api, esc, icon, toast, confirmDialog })
  : null;

const digestUI = window.ManagerDigest
  ? window.ManagerDigest.create({ api, esc, icon, toast })
  : null;

const evalUI = window.ManagerEval
  ? window.ManagerEval.create({ api, esc, icon, toast, state })
  : null;

const humanUI = window.ManagerHuman
  ? window.ManagerHuman.create({ api, esc, icon, toast, confirmDialog })
  : null;

const moodUI = window.ManagerMood ? window.ManagerMood.create({ api, esc, icon, toast }) : null;

const presenceUI = window.ManagerPresence
  ? window.ManagerPresence.create({ api, esc, icon, toast, confirmDialog })
  : null;

const opsUI = window.ManagerOps
  ? window.ManagerOps.create({ api, esc, icon, toast })
  : null;

const inboxUI = window.ManagerInbox
  ? window.ManagerInbox.create({ api, esc, icon, toast, confirmDialog })
  : null;

const guardUI = window.ManagerGuard
  ? window.ManagerGuard.create({
      state,
      api,
      esc,
      icon,
      toast,
      pluginConfigModal: (inst, pluginId, name, onSaved) => pluginConfigModal(inst, pluginId, name, onSaved),
    })
  : null;

const reviewUI = window.ManagerReview
  ? window.ManagerReview.create({ state, api, esc, icon, toast })
  : null;

const fixUI = window.ManagerFix
  ? window.ManagerFix.create({ state, api, esc, icon, toast })
  : null;

const ownerUI = window.ManagerOwner
  ? window.ManagerOwner.create({ state, api, esc, icon, toast })
  : null;

const releaseUI = window.ManagerRelease
  ? window.ManagerRelease.create({ state, api, esc, icon, toast })
  : null;

const lifeUI = window.ManagerLife
  ? window.ManagerLife.create({ state, api, esc, icon, toast })
  : null;

const peopleUI = window.ManagerPeople
  ? window.ManagerPeople.create({ state, api, esc, icon, toast })
  : null;

const memesUI = window.ManagerMemes
  ? window.ManagerMemes.create({ state, api, esc, icon, toast })
  : null;

const visionUI = window.ManagerVision
  ? window.ManagerVision.create({ state, api, esc, icon, toast })
  : null;

const hubUI = window.ManagerHub
  ? window.ManagerHub.create({ esc, icon, routes: () => ROUTES })
  : null;

const deployUI = window.ManagerDeploy
  ? window.ManagerDeploy.create({
      api,
      esc,
      icon,
      toast,
      onReady: () => finishOnboarding(),
    })
  : null;


/* --------------------------------------------------------------- toast */

function toast(message, type = "ok") {
  const root = $("#toast-root");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const iconName = type === "err" ? "alert" : type === "warn" ? "alert" : "check";
  el.innerHTML = `${icon(iconName)}<div class="msg">${esc(message)}</div>`;
  root.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    el.style.transition = "all .25s";
    setTimeout(() => el.remove(), 260);
  }, 3600);
}


/* --------------------------------------------------------------- modal */

function closeModal() {
  const root = $("#modal-root");
  root.classList.remove("open");
  root.innerHTML = "";
}

function openModal({ title, sub = "", body = "", footer = "", wide = false, onMount }) {
  const root = $("#modal-root");
  root.innerHTML = `
    <div class="backdrop" data-close></div>
    <div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
      <div class="modal-head">
        <div><h3>${esc(title)}</h3>${sub ? `<p>${esc(sub)}</p>` : ""}</div>
        <button class="close" data-close aria-label="关闭">${icon("close")}</button>
      </div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ""}
    </div>`;
  root.classList.add("open");
  $$("[data-close]", root).forEach((node) => node.addEventListener("click", closeModal));
  if (onMount) onMount(root);
}

function confirmDialog(title, text, danger = true) {
  return new Promise((resolve) => {
    openModal({
      title,
      body: `<p style="margin:0;font-size:13px;line-height:1.7;color:var(--muted)">${esc(text)}</p>`,
      footer: `
        <button class="btn ghost" data-close>取消</button>
        <button class="btn ${danger ? "danger" : "primary"}" id="confirm-yes">确定</button>`,
      onMount(root) {
        $("#confirm-yes", root).addEventListener("click", () => {
          closeModal();
          resolve(true);
        });
        root.addEventListener("click", (e) => {
          if (e.target.closest("[data-close]")) resolve(false);
        });
      },
    });
  });
}


/* ------------------------------------------------------------- bootstrap */

async function loadBootstrap() {
  const data = await api("/api/bootstrap");
  state.settings = data.settings || {};
  state.instances = data.instances || [];
  state.env = data.env || {};
  renderEnvChip();
}

function renderEnvChip() {
  const chip = $("#env-chip");
  const ok = state.env.source_ok && state.env.python_ok;
  chip.className = `env-chip ${ok ? "ok" : "bad"}`;
  chip.innerHTML = `<span class="dot"></span><span>${ok ? "环境就绪" : "环境需检查"}</span>`;
  const online = state.instances.filter((i) => i.status?.running).length;
  const live = $("#live-chip");
  live.className = `live-chip ${online ? "on" : ""}`;
  live.innerHTML = `<span class="dot"></span><span>${online} / ${state.instances.length} 在线</span>`;
}

async function refreshAll(silent = false) {
  try {
    await loadBootstrap();
    if (!silent) toast("数据已刷新");
    await navigate(true);
  } catch (err) {
    toast(err.message, "err");
  }
}


/* --------------------------------------------------------------- router */

const ROUTES = {
  overview: { section: "overview", title: "总览", sub: "舰队健康、运行状态与异常入口", render: viewOverview },
  hubBots: { section: "bots", title: "机器人", sub: "实例管理、私信收件箱与人工接管", render: viewHubBots },
  hubLive: { section: "presence", title: "活人感", sub: "连续生活线、群聊互动与人物档案", render: viewHubLive },
  hubGroup: { section: "group", title: "群聊", sub: "群聊安全、平台控制台与群聊剧场", render: viewHubGroup },
  hubPersona: { section: "personas", title: "人格", sub: "模型人格、说话风格与质量回归", render: viewHubPersona },
  hubMemory: { section: "memory", title: "记忆", sub: "记忆库、脑图与纠错闭环", render: viewHubMemory },
  hubAuto: { section: "automation", title: "自动化", sub: "自动化中心、审批队列、定时任务与舰队日报", render: viewHubAuto },
  hubPlugin: { section: "capability", title: "插件", sub: "插件市场、已安装插件与 DSH 能力", render: viewHubPlugin },
  hubMonitor: { section: "monitor", title: "监控", sub: "回复复盘、实时思考、日志与巡检", render: viewHubMonitor },
  bots: { section: "bots", title: "机器人", sub: "新增、配置与启停每一个 QQ 机器人", render: viewBots },
  inbox: { section: "bots", title: "收件箱", sub: "QQ/B站/抖音私信与人工接管", render: viewInbox },
  capMarket: { section: "capability", title: "AstrBot 市场", sub: "浏览官方插件市场，安装到指定机器人", render: viewCapMarket },
  capInstalled: { section: "capability", title: "AstrBot 已安装", sub: "查看、启停、配置每个机器人已安装的插件", render: viewCapInstalled },
  capGuard: { section: "group", title: "群聊防护", sub: "自动引用、说错话自检撤回、敏感词闸门与群聊冷却", render: viewGuard },
  capOwner: { section: "group", title: "主人验证", sub: "身份校准、口令二次校验与管理器一键授权，防群友冒充", render: viewCapOwner },
  capMatrix: { section: "group", title: "权限矩阵", sub: "跨实例查看 B站/抖音写开关、干跑与审批状态", render: viewCapMatrix },
  capDshPlugins: { section: "capability", title: "DSH 插件", sub: "运行 DSH、搜索并安装插件", render: viewCapDshPlugins },
  capDshSkills: { section: "capability", title: "DSH 技能", sub: "安装到 ~/.dsh/skills，DSH 新会话自动发现", render: viewCapDshSkills },
  capDshAccess: { section: "capability", title: "DSH 接入", sub: "把 DSH 接到 AstrBot，让 QQ 管理员调用", render: viewCapDshAccess },
  capBili: { section: "group", title: "B站控制台", sub: "主动看片频率、互动开关与今日运行状态", render: viewCapBili },
  capDouyin: { section: "group", title: "抖音控制台", sub: "主动刷时隙、互动/评论开关与 QQ 汇报状态", render: viewCapDouyin },
  approvals: { section: "automation", title: "审批队列", sub: "插件写操作先入队，批准后才执行", render: viewApprovals },
  automationCenter: { section: "automation", title: "自动化中心", sub: "内置巡检、DSH 技能定时任务与实时运行监控", render: viewAutomationCenter },
  tasks: { section: "automation", title: "任务中心", sub: "定时备份、日报、记忆睡眠与主动刷", render: viewTasks },
  digest: { section: "automation", title: "舰队日报", sub: "健康、审批、任务与事件的一天汇总", render: viewDigest },
  duet: { section: "group", title: "群聊剧场", sub: "两个机器人在指定群里按话题真实轮流发言", render: viewDuet },
  memory: { section: "memory", title: "记忆", sub: "记忆库、脑图、睡眠巩固、召回与图谱", render: viewMemory },
  memoryFix: { section: "memory", title: "记忆纠错", sub: "待确认纠错队列：定位相关记忆，标记失效、降权或改写", render: viewMemoryFix },
  models: { section: "personas", title: "模型与人格", sub: "切换对话模型、维护人格设定", render: viewModels },
  personaRelease: { section: "personas", title: "人格灰度", sub: "候选人格、影子跑分、A/B 对比、灰度上线与一键回滚", render: viewPersonaRelease },
  learn: { section: "personas", title: "聊天记录学习", sub: "从群聊、私聊、B站私信里抽样，总结说话风格并追加到风格档案（不写人格）", render: viewLearn },
  mood: { section: "personas", title: "每日心情", sub: "情绪、关系态度与模型评估实时流", render: viewMood },
  human: { section: "personas", title: "拟人模式", sub: "风格档案与旧人格自动块剥离", render: viewHuman },
  presenceLoops: { section: "presence", title: "话题回访", sub: "未完成话题、影子预览与确认后真实发送", render: viewPresenceLoops },
  presenceRelations: { section: "presence", title: "关系里程碑", sub: "昵称、阶段、关系记忆开关与共同事件时间线", render: viewPresenceRelations },
  presenceRhythm: { section: "presence", title: "生活节律", sub: "作息、当前阶段、有效精力与 24 小时活动", render: viewPresenceRhythm },
  presenceRadar: { section: "presence", title: "群聊读空气", sub: "接话/沉默影子统计与群聊配置白名单", render: viewPresenceRadar },
  presenceDiary: { section: "presence", title: "自我日记", sub: "只在本机管理器可见的每日日记与次日摘要", render: viewPresenceDiary },
  life: { section: "presence", title: "连续生活线", sub: "按作息自动推进的日常状态、精力与今天做了什么", render: viewLife },
  people: { section: "presence", title: "人物档案", sub: "称呼、性格、喜好、雷区与最近印象，一个人一张卡", render: viewPeople },
  memes: { section: "presence", title: "群梗库", sub: "群里反复出现的梗与口头禅，确认后注入对话", render: viewMemes },
  vision: { section: "presence", title: "看图接话", sub: "群图片的画面描述、主动接话与视觉模型设置", render: viewVision },
  evals: { section: "personas", title: "质量回归", sub: "固定用例评估人格回复的一致性与边界", render: viewEvals },
  review: { section: "monitor", title: "回复复盘", sub: "每条回复注入了哪些人格、记忆、身份校准与最终 system prompt", render: viewReview },
  think: { section: "monitor", title: "实时思考", sub: "在 QQ 里给机器人发消息，模型的思考过程实时显示在这里", render: viewThinkLive },
  logs: { section: "monitor", title: "运行日志", sub: "实时查看机器人运行输出", render: viewLogs },
  alerts: { section: "monitor", title: "告警中心", sub: "健康、审批、任务与备份的待处理异常", render: viewAlerts },
  drift: { section: "monitor", title: "一致性", sub: "对比实例之间的插件、模型与人格差异", render: viewDrift },
  resources: { section: "monitor", title: "资源", sub: "系统 CPU/内存/磁盘与实例进程树", render: viewResources },
  canary: { section: "monitor", title: "巡检", sub: "只读端到端检查健康、登录、调度与备份", render: viewCanary },
  settings: { section: "settings", title: "设置", sub: "源码与解释器路径、实例目录", render: viewSettings },
};

// 信息架构：侧边栏 10 个入口；每个 section 先进分组总览，再进具体功能页。
// 同类型功能被收进同一个 group，旧 hash 仍可直接打开对应功能页。
const IA_GROUPS = {
  bots: {
    hub: "hubBots",
    groups: [
      { name: "机器人实例", desc: "新增、配置、启停，查看运行状态与进程", items: [{ route: "bots", icon: "bots", label: "机器人管理" }] },
      { name: "私信接管", desc: "QQ / B站 / 抖音私信统一收件箱，可人工接管", items: [{ route: "inbox", icon: "inbox" }] },
    ],
  },
  presence: {
    hub: "hubLive",
    groups: [
      { name: "生活", desc: "作息驱动的连续生活线、节律与自我日记", items: [
        { route: "life", icon: "sun" },
        { route: "presenceRhythm", icon: "pulse" },
        { route: "presenceDiary", icon: "edit" },
      ] },
      { name: "群聊互动", desc: "群梗、看图接话、话题回访与读空气", items: [
        { route: "memes", icon: "model" },
        { route: "vision", icon: "search" },
        { route: "presenceLoops", icon: "refresh" },
        { route: "presenceRadar", icon: "pulse" },
      ] },
      { name: "人物", desc: "人物档案与共同记忆时间线", items: [
        { route: "people", icon: "bots" },
        { route: "presenceRelations", icon: "memory" },
      ] },
    ],
  },
  group: {
    hub: "hubGroup",
    groups: [
      { name: "群聊安全", desc: "防护闸门、主人身份校验与跨实例权限矩阵", items: [
        { route: "capGuard", icon: "alert" },
        { route: "capOwner", icon: "check" },
        { route: "capMatrix", icon: "settings" },
      ] },
      { name: "平台控制台", desc: "B站与抖音的主动行为开关和运行状态", items: [
        { route: "capBili", icon: "play" },
        { route: "capDouyin", icon: "stop" },
      ] },
      { name: "群聊剧场", desc: "两个机器人按话题真实轮流发言", items: [
        { route: "duet", icon: "terminal" },
      ] },
    ],
  },
  capability: {
    hub: "hubPlugin",
    groups: [
      { name: "插件", desc: "浏览市场、安装、启停与配置", items: [
        { route: "capMarket", icon: "market" },
        { route: "capInstalled", icon: "folder" },
      ] },
      { name: "DSH", desc: "DSH 插件、技能与接入 AstrBot", items: [
        { route: "capDshPlugins", icon: "dsh" },
        { route: "capDshSkills", icon: "download" },
        { route: "capDshAccess", icon: "terminal" },
      ] },
    ],
  },
  automation: {
    hub: "hubAuto",
    groups: [
      { name: "执行流程", desc: "内置巡检与技能任务自动跑，写操作先审批", items: [
        { route: "automationCenter", icon: "refresh" },
        { route: "approvals", icon: "check" },
        { route: "tasks", icon: "refresh" },
      ] },
      { name: "报告", desc: "一天的健康、审批与事件汇总", items: [
        { route: "digest", icon: "logs" },
      ] },
    ],
  },
  memory: {
    hub: "hubMemory",
    groups: [
      { name: "记忆库", desc: "脑图、睡眠巩固、召回与知识图谱", items: [
        { route: "memory", icon: "memory" },
      ] },
      { name: "纠错闭环", desc: "定位记错的记忆，标记失效、降权或改写", items: [
        { route: "memoryFix", icon: "edit" },
      ] },
    ],
  },
  personas: {
    hub: "hubPersona",
    groups: [
      { name: "人格", desc: "模型切换、人格设定、候选灰度与回滚", items: [
        { route: "models", icon: "model" },
        { route: "personaRelease", icon: "external" },
      ] },
      { name: "风格与心情", desc: "说话风格档案、每日心情与聊天记录学习", items: [
        { route: "human", icon: "bots" },
        { route: "mood", icon: "sun" },
        { route: "learn", icon: "download" },
      ] },
      { name: "评测", desc: "固定用例回归人格一致性与边界", items: [
        { route: "evals", icon: "check" },
      ] },
    ],
  },
  monitor: {
    hub: "hubMonitor",
    groups: [
      { name: "运行", desc: "回复复盘、实时思考与运行日志", items: [
        { route: "review", icon: "logs" },
        { route: "think", icon: "terminal" },
        { route: "logs", icon: "folder" },
      ] },
      { name: "巡检", desc: "告警、一致性、资源与端到端检查", items: [
        { route: "alerts", icon: "alert" },
        { route: "drift", icon: "settings" },
        { route: "resources", icon: "pulse" },
        { route: "canary", icon: "check" },
      ] },
    ],
  },
};

const SECTION_NAME = { overview: "总览", bots: "机器人", group: "群聊", capability: "插件", automation: "自动化", memory: "记忆", personas: "人格", presence: "活人感", monitor: "监控", settings: "设置" };
const HUB_OF_SECTION = {};
const SECTIONS = {};
Object.keys(IA_GROUPS).forEach((section) => {
  HUB_OF_SECTION[section] = IA_GROUPS[section].hub;
  SECTIONS[section] = IA_GROUPS[section].groups.reduce(
    (all, group) => all.concat(group.items.map((item) => item.route)), []);
});

function groupOf(sectionId, leaf) {
  const def = IA_GROUPS[sectionId];
  if (!def) return null;
  return def.groups.find((group) => group.items.some((item) => item.route === leaf)) || null;
}

function tabBarHtml(sectionId, activeLeaf) {
  const hub = HUB_OF_SECTION[sectionId];
  if (!hub || activeLeaf === hub) return "";
  const back = `<a class="sub-back" href="#/${hub}">‹ ${esc(SECTION_NAME[sectionId] || "总览")}</a>`;
  const group = groupOf(sectionId, activeLeaf);
  if (!group || group.items.length < 2) {
    return `<div class="subbar">${back}</div>`;
  }
  return `<div class="subbar">${back}<span class="sub-group">${esc(group.name)}</span>
    <nav class="tabs">${group.items.map((item) =>
      `<a class="tab ${item.route === activeLeaf ? "active" : ""}" href="#/${item.route}">${esc(item.label || ROUTES[item.route].title)}</a>`).join("")}</nav></div>`;
}

/* --------------------------------------------------------- onboarding */

async function renderOnboarding() {
  document.body.classList.add("onboarding");
  state.route = "deploy";
  $$("#nav a").forEach((a) => a.classList.remove("active"));
  const view = $("#view");
  if (!deployUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>部署模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  await deployUI.render(view);
}

async function finishOnboarding() {
  try {
    await loadBootstrap();
    if (state.instances.length) {
      deployUI?.dispose();
      history.replaceState(null, "", "#/overview");
      await navigate(true);
      toast("机器人已创建，已进入控制台");
    }
  } catch (err) {
    toast(err.message, "err");
  }
}

async function navigate(silent = false) {
  // 本机还没有任何机器人时，只展示一键部署首屏，隐藏全部管理功能。
  if (!state.instances.length) {
    await renderOnboarding();
    return;
  }
  document.body.classList.remove("onboarding");
  const hash = location.hash.replace(/^#\/?/, "") || "overview";
  const resolved = window.ManagerIA
    ? window.ManagerIA.resolveRoute(hash)
    : { route: ROUTES[hash] ? hash : "overview", redirect: false };
  if (resolved.redirect) {
    location.replace(`#/${resolved.route}`);
    return;
  }
  const route = ROUTES[resolved.route] ? resolved.route : "overview";
  const section = ROUTES[route].section;
  if (state.route !== route) {
    memoryUI?.leave();
    dshUI?.leave();
    inboxUI?.leave();
    approvalsUI?.leave();
    automationCenterUI?.leave();
    tasksUI?.leave();
    digestUI?.leave();
    duetUI?.leave();
    evalUI?.leave();
    humanUI?.leave();
    moodUI?.leave();
    presenceUI?.leave();
    opsUI?.leave();
    clearLogTimer();
    clearAutoTimer();
    closeThinkStream();
  }
  state.route = route;

  // 导航按 section 高亮；顶栏显示 section 名 + 当前 leaf 的描述。
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === section));
  $("#page-title").textContent = SECTION_NAME[section];
  $("#page-sub").textContent = ROUTES[route].sub;

  const view = $("#view");
  const tabs = tabBarHtml(section, route);
  let target;
  if (tabs) {
    view.innerHTML = `${tabs}<div class="tabpane" id="tabpane"><div class="skeleton" style="height:160px"></div></div>`;
    target = $("#tabpane");
  } else {
    view.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
    target = view;
  }
  try {
    await ROUTES[route].render(target);
  } catch (err) {
    target.innerHTML = `<div class="empty">${icon("alert")}<h4>加载失败</h4><p>${esc(err.message)}</p></div>`;
  }
  renderEnvChip();
}


/* ------------------------------------------------------------- summaries */

async function loadSummary(id) {
  const cached = state.summaries[id];
  if (cached && Date.now() - cached.ts < 15000) return cached.data;
  try {
    const data = await api(`/api/instances/${id}/summary`);
    state.summaries[id] = { ts: Date.now(), data };
    return data;
  } catch (_) {
    return null;
  }
}

async function hydrateSummaries(ids, onDone) {
  const missing = ids.filter((id) => !state.summaries[id]);
  if (!missing.length) { onDone(); return; }
  await Promise.all(missing.map((id) => loadSummary(id)));
  if (state.route) onDone();
}

function pickModel(summary) {
  const list = summary?.providers || [];
  const active = list.find((p) => p.enable && (p.type || "").includes("chat")) || list[0];
  return active?.model || active?.id || "—";
}

function normalizeList(payload, key) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  if (Array.isArray(payload[key])) return payload[key];
  const data = payload.data;
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data[key])) return data[key];
  return [];
}

function pickPluginCount(summary) {
  if (typeof summary?.plugins === "number") return summary.plugins;
  return "—";
}


/* ------------------------------------------------------------- overview */

async function viewOverview(view) {
  const insts = state.instances;
  const online = insts.filter((i) => i.status?.running).length;
  const providerCount = Object.values(state.summaries).reduce(
    (sum, entry) => sum + (entry.data?.providers?.length || 0), 0);
  const pluginTotal = Object.values(state.summaries).reduce(
    (sum, entry) => sum + (entry.data?.plugins || 0), 0);

  view.innerHTML = `
    <div id="fleet-health"></div>
    <div class="stat-grid">
      <div class="stat"><div class="k">机器人实例</div><div class="v">${insts.length}<small>个</small></div>
        <div class="hint">${online} 个正在运行</div></div>
      <div class="stat"><div class="k">运行状态</div><div class="v">${online}<small>/ ${insts.length}</small></div>
        <div class="hint">Dashboard 端口可用即视为在线</div></div>
      <div class="stat"><div class="k">已装插件</div><div class="v">${pluginTotal || "—"}</div>
        <div class="hint">来自各实例的插件统计</div></div>
      <div class="stat"><div class="k">市场插件</div><div class="v">${state.env.market_index || 0}<small>款</small></div>
        <div class="hint">本地索引，可离线浏览</div></div>
      <div class="stat" id="overview-approvals" style="cursor:pointer"><div class="k">待审批</div>
        <div class="v" data-approval-count>—</div><div class="hint">写操作需批准后执行</div></div>
    </div>

    <div class="section-head">
      <h2>机器人舰队</h2>
      <div class="side">${insts.length ? "点击进入机器人页管理" : "还没有接入任何机器人"}</div>
    </div>
    ${insts.length ? `<div class="bot-grid" id="bot-grid">${insts.map(botCard).join("")}</div>` :
      `<div class="empty">${icon("bots")}<h4>还没有机器人</h4>
        <p>点击右上角「新增机器人」创建第一个实例，或到「设置」检查 AstrBot 源码路径。</p></div>`}`;

  healthUI?.renderFleet(view);
  const approvalCard = $("#overview-approvals", view);
  if (approvalCard) {
    approvalCard.addEventListener("click", () => { location.hash = "#/approvals"; });
    api("/api/approvals/summary").then((data) => {
      if (state.route !== "overview") return;
      const node = approvalCard.querySelector("[data-approval-count]");
      if (node) node.textContent = String(data?.pending ?? 0);
    }).catch(() => {});
  }
  $$("[data-go]", view).forEach((btn) =>
    btn.addEventListener("click", () => { location.hash = btn.dataset.go; }));

  hydrateSummaries(insts.map((i) => i.id), () => {
    if (state.route !== "overview") return;
    view.querySelectorAll("[data-sum]").forEach((node) => {
      const inst = insts.find((i) => i.id === node.dataset.sum);
      if (!inst) return;
      const summary = state.summaries[inst.id]?.data;
      node.querySelector("[data-model]").textContent = pickModel(summary);
      node.querySelector("[data-plugins]").textContent = pickPluginCount(summary);
    });
  });
}

function botCard(inst) {
  const running = inst.status?.running;
  const managed = inst.status?.managed;
  const napcat = inst.napcat || {};
  const wd = napcat.watchdog || {};
  const wdStage = String(wd.stage || "idle");
  const wdLabels = {
    self_heal: "掉线·观察自愈中",
    relogin: "掉线·自动快速登录中",
    qrcode: "掉线·等待扫码",
  };
  const napcatLabel = napcat.running
    ? "已连接"
    : napcat.configured
      ? "未登录"
      : "未配置";
  return `
    <div class="bot-card ${running ? "running" : ""}" data-sum="${inst.id}">
      <div class="bot-head">
        <div class="avatar" style="${avatarStyle(inst.color || "#5b8cff")}">${esc(initials(inst.name))}</div>
        <div class="bot-id">
          <h3>${esc(inst.name)}
            <span class="badge ${running ? "ok" : "bad"}"><span class="status-dot ${running ? "on" : "off"}"></span>${running ? "运行中" : "已停止"}</span>
            ${running && !managed ? `<span class="badge warn">外部进程</span>` : ""}
          </h3>
          <div class="sub">
            <span>QQ ${esc(inst.qq || "未绑定")}</span>
            <span>NapCat ${napcatLabel}</span>
            ${wdLabels[wdStage] ? `<span class="badge ${wdStage === "qrcode" ? "bad" : "warn"}">${esc(wdLabels[wdStage])}${wd.relogin_count ? `（已自动重登 ${wd.relogin_count} 次）` : ""}</span>` : ""}
          </div>
        </div>
      </div>
      <div class="bot-meta">
        <div class="item"><b>DASHBOARD</b><span>127.0.0.1:${esc(inst.dash_port)}</span></div>
        <div class="item"><b>QQ 反向 WS</b><span>${esc(inst.ws_port || "—")}</span></div>
        <div class="item"><b>当前模型</b><span data-model>读取中…</span></div>
        <div class="item"><b>插件数量</b><span data-plugins>—</span></div>
      </div>
      <div class="bot-actions">
        <button class="btn sm ghost" data-go="#/bots">${icon("bots")}进入机器人页</button>
      </div>
    </div>`;
}

function bindBotActions(root) {
  $$("[data-act]", root).forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const act = btn.dataset.act;
      const inst = state.instances.find((i) => i.id === id);
      if (!inst) return;
      if (act === "panel") {
        window.open(`http://127.0.0.1:${inst.dash_port}`, "_blank");
        return;
      }
      if (act === "logs") {
        state.logInst = id;
        location.hash = "#/logs";
        return;
      }
      if (act === "bili") {
        biliModal(inst);
        return;
      }
      btn.disabled = true;
      try {
        const res = await api(`/api/instances/${id}/${act}`, { method: "POST" });
        if (act === "start") {
          toast(res?.napcat_note ? `${inst.name} 已启动 · ${res.napcat_note}` : `${inst.name} 已启动，稍候刷新状态`);
        } else if (act === "adopt") {
          toast(`${inst.name} 的外部进程已接管，现在可以在管理器里启停`);
        } else {
          toast(`${inst.name} 已${act === "stop" ? "停止" : "重启"}，稍候刷新状态`);
        }
        setTimeout(() => refreshAll(true), 1200);
      } catch (err) {
        toast(err.message, "err");
        btn.disabled = false;
      }
    });
  });
}


/* ----------------------------------------------------------------- bots */

async function viewBots(view) {
  const insts = state.instances;
  view.innerHTML = `
    <div class="section-head" style="margin-top:0">
      <h2>实例列表</h2>
      <div class="side">共 ${insts.length} 个</div>
    </div>
    ${insts.length ? `
    <div class="card" style="padding:8px 6px 6px">
      <table class="table">
        <thead><tr>
          <th style="padding-left:16px">机器人</th><th>QQ</th><th>端口</th><th>状态</th>
          <th>插件</th><th>模型</th><th style="text-align:right;padding-right:16px">操作</th>
        </tr></thead>
        <tbody>
          ${insts.map((inst) => `
            <tr>
              <td style="padding-left:16px">
                <div class="cell-title">
                  <div class="avatar" style="width:30px;height:30px;border-radius:9px;font-size:12px;${avatarStyle(inst.color || "#5b8cff")}">${esc(initials(inst.name))}</div>
                  <div>
                    <div style="font-weight:550">${esc(inst.name)}</div>
                    <div style="font-size:11.5px;color:var(--dim)">${esc(inst.note || inst.root)}</div>
                  </div>
                </div>
              </td>
              <td class="mono">${esc(inst.qq || "—")}</td>
              <td class="mono">${esc(inst.dash_port)} / ${esc(inst.ws_port || "—")}</td>
              <td><span class="badge ${inst.status?.running ? "ok" : "bad"}"><span class="status-dot ${inst.status?.running ? "on" : "off"}"></span>${inst.status?.running ? "运行中" : "已停止"}</span></td>
              <td class="mono" data-plugins="${inst.id}">—</td>
              <td style="font-size:12px" data-model="${inst.id}">—</td>
              <td>
                <div class="actions" style="padding-right:8px">
                  <button class="btn sm ghost icon-only" data-act="${inst.status?.running ? "stop" : "start"}" data-id="${inst.id}" title="${inst.status?.running ? "停止" : "启动"}">${icon(inst.status?.running ? "stop" : "play")}</button>
                  <button class="btn sm ghost icon-only" data-act="restart" data-id="${inst.id}" title="重启" ${inst.status?.running ? "" : "disabled"}>${icon("restart")}</button>
                  <button class="btn sm ghost icon-only" data-napcat="${inst.id}" title="启动 NapCat" ${inst.napcat?.configured ? "" : "disabled"}>${icon("pulse")}</button>
                  ${inst.status?.running && !inst.status?.managed ? `<button class="btn sm ghost icon-only" data-act="adopt" data-id="${inst.id}" title="接管外部进程">${icon("check")}</button>` : ""}
                  <button class="btn sm ghost" data-detail="${inst.id}">详情</button>
                  <button class="btn sm ghost icon-only" data-edit="${inst.id}" title="编辑">${icon("edit")}</button>
                  <button class="btn sm ghost icon-only" data-act="panel" data-id="${inst.id}" title="打开 Dashboard">${icon("external")}</button>
                </div>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>` : `<div class="empty">${icon("bots")}<h4>暂无实例</h4><p>点击右上角新增，或在设置页检查 AstrBot 源码路径。</p></div>`}`;

  bindBotActions(view);
  $$("[data-napcat]", view).forEach((btn) => btn.addEventListener("click", async () => {
    const inst = state.instances.find((i) => i.id === btn.dataset.napcat);
    if (!inst) return;
    btn.disabled = true;
    try {
      const res = await api(`/api/instances/${inst.id}/napcat/start`, { method: "POST" });
      toast(res?.already ? "NapCat 已在运行，请在 QQ 窗口确认已登录" : "NapCat 已启动，请在弹出的窗口完成 QQ 登录");
      setTimeout(() => refreshAll(true), 1200);
    } catch (err) {
      toast(err.message, "err");
      btn.disabled = false;
    }
  }));
  $$("[data-detail]", view).forEach((btn) =>
    btn.addEventListener("click", () => openBotDetail(btn.dataset.detail)));
  $$("[data-edit]", view).forEach((btn) =>
    btn.addEventListener("click", () => editBotModal(btn.dataset.edit)));

  hydrateSummaries(insts.map((i) => i.id), () => {
    if (state.route !== "bots") return;
    insts.forEach((inst) => {
      const summary = state.summaries[inst.id]?.data;
      const cell = view.querySelector(`[data-plugins="${inst.id}"]`);
      const model = view.querySelector(`[data-model="${inst.id}"]`);
      if (cell) cell.textContent = pickPluginCount(summary);
      if (model) model.textContent = pickModel(summary);
    });
  });
}

const BOT_DETAIL_TABS = [
  ["runtime", "概览"],
  ["plugins", "插件"],
  ["permissions", "工具权限"],
  ["access", "DSH 接入"],
  ["logs", "日志"],
];

let botDetailLogTimer = null;

function clearBotDetailLogTimer() {
  if (botDetailLogTimer) {
    clearInterval(botDetailLogTimer);
    botDetailLogTimer = null;
  }
}

function closeBotDetail() {
  const root = $("#bot-detail-root");
  if (!root) return;
  clearBotDetailLogTimer();
  root.classList.remove("open");
  setTimeout(() => root.remove(), 200);
}

function openBotDetail(instId, tab = "runtime") {
  const inst = state.instances.find((i) => i.id === instId);
  if (!inst) return;
  closeBotDetail();
  const active = BOT_DETAIL_TABS.some(([id]) => id === tab) ? tab : "runtime";
  const running = Boolean(inst.status?.running);
  const root = document.createElement("div");
  root.id = "bot-detail-root";
  root.className = "drawer-root";
  root.innerHTML = `
    <div class="drawer-backdrop" data-drawer-close></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-label="${esc(inst.name)} 详情">
      <div class="drawer-head">
        <div class="drawer-identity">
          <div class="avatar" style="width:38px;height:38px;border-radius:11px;font-size:13px;${avatarStyle(inst.color || "#5b8cff")}">${esc(initials(inst.name))}</div>
          <div>
            <h3>${esc(inst.name)}</h3>
            <p>${inst.qq ? "QQ " + esc(inst.qq) + " · " : ""}${esc(inst.dash_port)} / ${esc(inst.ws_port || "—")}</p>
          </div>
          <span class="badge ${running ? "ok" : "bad"}"><span class="status-dot ${running ? "on" : "off"}"></span>${running ? "运行中" : "已停止"}</span>
        </div>
        <button class="close" data-drawer-close aria-label="关闭">${icon("close")}</button>
      </div>
      <div class="drawer-tabs">
        ${BOT_DETAIL_TABS.map(([id, label]) => `<button type="button" class="tab ${id === active ? "active" : ""}" data-bot-tab="${id}">${esc(label)}</button>`).join("")}
      </div>
      <div class="drawer-body" id="bot-detail-body"></div>
      <div class="drawer-foot">
        <button class="btn ghost" data-bot-edit>编辑资料</button>
        <button class="btn primary" data-bot-panel>打开 Dashboard</button>
      </div>
    </aside>`;
  document.body.appendChild(root);
  requestAnimationFrame(() => root.classList.add("open"));

  const body = $("#bot-detail-body", root);
  const showTab = async (name) => {
    clearBotDetailLogTimer();
    root.querySelectorAll("[data-bot-tab]").forEach((btn) =>
      btn.classList.toggle("active", btn.dataset.botTab === name));
    body.innerHTML = `<div class="skeleton" style="height:180px"></div>`;
    try {
      if (name === "runtime") await renderBotRuntimeTab(body, inst);
      else if (name === "plugins") await renderBotPluginsTab(body, inst);
      else if (name === "permissions") await renderBotPermissionsTab(body, inst);
      else if (name === "access") await renderBotAccessTab(body, inst);
      else await renderBotLogsTab(body, inst);
    } catch (err) {
      body.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
    }
  };

  root.querySelectorAll("[data-drawer-close]").forEach((node) =>
    node.addEventListener("click", closeBotDetail));
  root.querySelectorAll("[data-bot-tab]").forEach((btn) =>
    btn.addEventListener("click", () => showTab(btn.dataset.botTab)));
  $("[data-bot-edit]", root).addEventListener("click", () => {
    closeBotDetail();
    editBotModal(inst.id);
  });
  $("[data-bot-panel]", root).addEventListener("click", () =>
    window.open(`http://127.0.0.1:${inst.dash_port}`, "_blank"));
  showTab(active);
}

async function renderBotRuntimeTab(body, inst) {
  const running = Boolean(inst.status?.running);
  body.innerHTML = `
    <div class="drawer-section">
      <h4>运行</h4>
      <div class="kv">
        <div class="row-item"><span class="k">绑定 QQ</span><span class="v mono">${esc(inst.qq || "—")}</span></div>
        <div class="row-item"><span class="k">Dashboard</span><span class="v mono">127.0.0.1:${esc(inst.dash_port)}</span></div>
        <div class="row-item"><span class="k">反向 WS</span><span class="v mono">${esc(inst.ws_port || "—")}</span></div>
        <div class="row-item"><span class="k">当前模型</span><span class="v" data-bot-model>—</span></div>
        <div class="row-item"><span class="k">已装插件</span><span class="v" data-bot-plugins>—</span></div>
        <div class="row-item"><span class="k">管理方式</span><span class="v">${inst.status?.managed ? "管理器托管" : running ? "外部进程" : "未运行"}</span></div>
      </div>
      <div class="actions" style="margin-top:12px;flex-wrap:wrap">
        <button class="btn sm ${running ? "danger" : "primary"}" data-bot-act="${running ? "stop" : "start"}">${icon(running ? "stop" : "play")}${running ? "停止" : "启动"}</button>
        <button class="btn sm ghost" data-bot-act="restart" ${running ? "" : "disabled"}>${icon("restart")}重启</button>
        <button class="btn sm ghost" data-bot-act="napcat" ${inst.napcat?.configured ? "" : "disabled"}>${icon("pulse")}启动 NapCat</button>
      </div>
    </div>
    <div class="drawer-section">
      <h4>路径</h4>
      <div class="kv">
        <div class="row-item"><span class="k">实例目录</span><span class="v mono" style="word-break:break-all;text-align:right">${esc(inst.root || "—")}</span></div>
        <div class="row-item"><span class="k">NapCat</span><span class="v mono" style="word-break:break-all;text-align:right">${esc(inst.napcat_dir || "—")}</span></div>
      </div>
    </div>
    <div class="drawer-section">
      <h4>备注</h4>
      <p style="margin:0;font-size:12.5px;line-height:1.7;color:var(--muted)">${esc(inst.note || "—")}</p>
    </div>`;
  body.querySelectorAll("[data-bot-act]").forEach((btn) =>
    btn.addEventListener("click", () => runBotAction(inst, btn.dataset.botAct, btn)));
  loadSummary(inst.id).then((summary) => {
    if (!body.isConnected) return;
    const model = body.querySelector("[data-bot-model]");
    const plugins = body.querySelector("[data-bot-plugins]");
    if (model) model.textContent = pickModel(summary);
    if (plugins) plugins.textContent = pickPluginCount(summary);
  });
}

async function runBotAction(inst, act, btn) {
  btn.disabled = true;
  try {
    if (act === "napcat") {
      const res = await api(`/api/instances/${inst.id}/napcat/start`, { method: "POST" });
      toast(res?.already ? "NapCat 已在运行，请在 QQ 窗口确认已登录" : "NapCat 已启动，请在弹出的窗口完成 QQ 登录");
    } else {
      await api(`/api/instances/${inst.id}/${act}`, { method: "POST" });
      toast(`${inst.name} 已${act === "stop" ? "停止" : act === "start" ? "启动" : "重启"}，稍候刷新状态`);
    }
    closeBotDetail();
    setTimeout(() => refreshAll(true), 1200);
  } catch (err) {
    toast(err.message, "err");
    btn.disabled = false;
  }
}

async function renderBotPluginsTab(body, inst) {
  if (!inst.status?.running) {
    body.innerHTML = `<div class="empty" style="padding:24px">${icon("play")}<h4>机器人未运行</h4><p>启动后即可查看并管理该实例已安装的插件。</p></div>`;
    return;
  }
  body.innerHTML = `<div class="section-head" style="margin:0 0 12px"><h2 style="font-size:14px">已安装插件</h2>
    <button class="btn sm primary" id="bot-detail-install">${icon("download")}安装插件</button></div>
    <div id="bot-detail-plugins"><div class="skeleton" style="height:120px"></div></div>`;
  $("#bot-detail-install", body).addEventListener("click", () => pluginInstallModal(body, inst, "#bot-detail-plugins"));
  await loadPlugins(body, inst, "#bot-detail-plugins");
}

async function renderBotPermissionsTab(body, inst) {
  body.innerHTML = `<div class="section-head" style="margin:0 0 12px"><h2 style="font-size:14px">插件工具权限</h2>
    <button class="btn sm ghost" id="bot-detail-harden">收口 B站写操作</button></div>
    <div id="bot-detail-tools"><div class="skeleton" style="height:120px"></div></div>
    <p class="hint-text">member = 所有白名单会话可用；admin = 仅主人。B站写操作建议设为 admin。</p>`;
  const box = $("#bot-detail-tools", body);
  const reload = () => loadToolPermissionsInto(box, inst, reload);
  $("#bot-detail-harden", body).addEventListener("click", (event) =>
    hardenBiliTools(inst, event.currentTarget, reload));
  await reload();
}

async function renderBotAccessTab(body, inst) {
  const data = await api("/api/dsh/connectors");
  const entry = (data?.instances || []).find((item) => String(item.id) === String(inst.id));
  const dshReady = Boolean(data?.dsh?.ready);
  if (!entry) {
    body.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>未找到该实例的 DSH 接入信息</h4>
      <p>刷新 DSH 状态后再试。</p></div>`;
    return;
  }
  const plugin = entry.plugin;
  const compatible = Boolean(plugin && plugin.compatible);
  const tools = entry.tools || {};
  const toolText = Object.keys(tools).length
    ? ["dsh_ask", "dsh_ping"].map((name) => `${name}=${tools[name] || "未设置"}`).join(" · ")
    : "尚未读取到工具权限";
  body.innerHTML = `
    <div class="drawer-section">
      <h4>连接</h4>
      <div class="kv">
        <div class="row-item"><span class="k">DSH</span><span class="v">${dshReady ? "已就绪" : "未运行"}</span></div>
        <div class="row-item"><span class="k">兼容桥</span><span class="v">${plugin ? esc(plugin.id) + (plugin.version ? " v" + esc(plugin.version) : "") : "未安装"}</span></div>
        <div class="row-item"><span class="k">状态</span><span class="v">${compatible ? "已接入" : plugin ? "协议不兼容" : "未接入"}</span></div>
        <div class="row-item"><span class="k">工具权限</span><span class="v mono" style="text-align:right">${esc(toolText)}</span></div>
      </div>
    </div>
    ${entry.error ? `<p class="hint-text">${esc(entry.error)}</p>` : ""}
    <div class="actions" style="flex-wrap:wrap">
      <button class="btn sm ghost" data-bot-access-page>打开 DSH 接入页</button>
      <button class="btn sm ghost" data-bot-access-test ${plugin && compatible ? "" : "disabled"}>测试连接</button>
    </div>`;
  $("[data-bot-access-page]", body).addEventListener("click", () => {
    closeBotDetail();
    location.hash = "#/capDshAccess";
  });
  const testBtn = $("[data-bot-access-test]", body);
  if (testBtn) testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    try {
      const result = await api(`/api/dsh/connectors/${entry.id}/test`, { method: "POST" });
      toast(result?.ok === false ? `连接失败：${result.message || "未知错误"}` : "DSH 连接正常", result?.ok === false ? "err" : "ok");
    } catch (err) {
      toast(err.message, "err");
    } finally {
      testBtn.disabled = false;
    }
  });
}

async function renderBotLogsTab(body, inst) {
  body.innerHTML = `<div class="section-head" style="margin:0 0 10px"><h2 style="font-size:14px">机器人日志</h2>
    <div style="display:flex;gap:8px;align-items:center">
      <label class="checkline"><input type="checkbox" id="bot-detail-log-auto">自动刷新</label>
      <button class="btn sm ghost" id="bot-detail-log-refresh">${icon("refresh")}刷新</button>
    </div></div>
    <div class="terminal drawer-log" id="bot-detail-log"><span class="empty">加载中…</span></div>`;
  const term = $("#bot-detail-log", body);
  const load = async () => {
    try {
      const data = await api(`/api/instances/${inst.id}/logs?lines=200&source=bot`);
      const text = data.text || "";
      term.innerHTML = text.trim()
        ? logLinesHtml(text)
        : `<span class="empty">暂无日志。机器人启动后这里会显示输出。</span>`;
      term.scrollTop = term.scrollHeight;
    } catch (err) {
      term.innerHTML = `<span class="empty">${esc(err.message)}</span>`;
    }
  };
  $("#bot-detail-log-refresh", body).addEventListener("click", load);
  $("#bot-detail-log-auto", body).addEventListener("change", (event) => {
    clearBotDetailLogTimer();
    if (event.target.checked) botDetailLogTimer = setInterval(load, 3000);
  });
  await load();
}

function editBotModal(id) {
  const inst = state.instances.find((i) => i.id === id);
  if (!inst) return;
  openModal({
    title: `编辑 · ${inst.name}`,
    sub: "修改后需重启机器人才能完全生效",
    wide: true,
    body: `
      <div class="row">
        <div class="field"><label>机器人名称</label><input id="f-name" value="${esc(inst.name)}"></div>
        <div class="field"><label>绑定 QQ 号</label><input id="f-qq" value="${esc(inst.qq || "")}" placeholder="例如 10001"></div>
      </div>
      <div class="row">
        <div class="field"><label>Dashboard 端口</label><input id="f-dash" type="number" value="${esc(inst.dash_port)}"></div>
        <div class="field"><label>QQ 反向 WS 端口</label><input id="f-ws" type="number" value="${esc(inst.ws_port || "")}"></div>
      </div>
      <div class="row">
        <div class="field"><label>Dashboard 账号</label><input id="f-user" value="${esc(inst.dash_user || "astrbot")}"></div>
        <div class="field"><label>Dashboard 密码</label><input id="f-pass" type="password" placeholder="${inst.has_password ? "已保存，留空则不修改" : "请输入密码"}"></div>
      </div>
      <div class="row">
        <div class="field"><label>NapCat 目录</label><input id="f-napcat" value="${esc(inst.napcat_dir || "")}" placeholder="包含 napcat.quick.bat 的文件夹"></div>
        <div class="field"><label>NapCat WebUI 端口</label><input id="f-napcat-port" type="number" value="${esc(inst.napcat_port || "")}"></div>
      </div>
      <div class="field"><label>备注</label><input id="f-note" value="${esc(inst.note || "")}"></div>
      <div class="field"><label>实例目录</label><input id="f-root" value="${esc(inst.root)}" disabled>
        <span class="help">目录迁移请手动移动后在注册表修改，此处仅展示。</span></div>`,
    footer: `
      <button class="btn danger" id="btn-delete" style="margin-right:auto">${icon("trash")}移除实例</button>
      <button class="btn ghost" data-close>取消</button>
      <button class="btn primary" id="btn-save">保存</button>`,
    onMount(root) {
      $("#btn-save", root).addEventListener("click", async () => {
        const patch = {
          name: $("#f-name", root).value.trim(),
          qq: $("#f-qq", root).value.trim(),
          dash_port: Number($("#f-dash", root).value || 0),
          ws_port: Number($("#f-ws", root).value || 0),
          dash_user: $("#f-user", root).value.trim(),
          napcat_dir: $("#f-napcat", root).value.trim(),
          napcat_port: Number($("#f-napcat-port", root).value || 0),
          note: $("#f-note", root).value.trim(),
        };
        const pass = $("#f-pass", root).value;
        if (pass) patch.dash_pass = pass;
        try {
          await api(`/api/instances/${id}`, { method: "PUT", body: patch });
          closeModal();
          toast("已保存");
          await refreshAll(true);
        } catch (err) { toast(err.message, "err"); }
      });
      $("#btn-delete", root).addEventListener("click", async () => {
        const ok = await confirmDialog(
          "移除机器人",
          `将从管理器中移除「${inst.name}」，磁盘文件不会被删除。确定继续？`);
        if (!ok) return;
        try {
          await api(`/api/instances/${id}`, { method: "DELETE" });
          closeModal();
          toast("已移除");
          await refreshAll(true);
        } catch (err) { toast(err.message, "err"); }
      });
    },
  });
}


/* ---------------------------------------------------------------- bili */

async function biliModal(inst) {
  openModal({
    title: `B站状态 · ${inst.name}`,
    sub: "只读快照：生活状态、心情、好感度、今日动作与主动推荐",
    wide: true,
    body: `<div id="bili-body"><div class="skeleton" style="height:180px"></div></div>`,
    footer: `<button class="btn ghost" data-close>关闭</button>
      <button class="btn ghost" id="bili-refresh">${icon("refresh")}刷新</button>`,
    onMount(root) {
      const load = async () => {
        const box = $("#bili-body", root);
        box.innerHTML = `<div class="skeleton" style="height:180px"></div>`;
        try {
          const data = await api(`/api/instances/${inst.id}/bili`);
          box.innerHTML = biliHtml(data || {});
        } catch (err) {
          box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
        }
      };
      $("#bili-refresh", root).addEventListener("click", load);
      load();
    },
  });
}

function biliHtml(s) {
  if (!s.installed) {
    return `<div class="empty" style="padding:30px">${icon("pulse")}<h4>没有 B站插件数据</h4>
      <p>这个机器人没有安装 astrbot_plugin_bilibili_ai_bot，或插件还没有产生数据。</p></div>`;
  }
  const life = s.life || {};
  const mood = s.mood_daily || {};
  const actions = s.actions || {};
  const counts = s.counts || {};
  const affection = s.affection || [];
  const proactive = s.proactive || [];
  const byKind = Object.entries(actions.by_kind || {});
  const recent = actions.recent || [];
  const pct = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? `${Math.round(n * 100)}%` : "—";
  };
  return `
    <div class="stat-grid">
      <div class="stat"><div class="k">今日动作</div><div class="v">${actions.today_total ?? 0}</div><div class="hint">失败 ${actions.failed_today ?? 0}</div></div>
      <div class="stat"><div class="k">记忆条数</div><div class="v">${counts.memories ?? "—"}</div><div class="hint">事件 ${counts.events ?? "—"}</div></div>
      <div class="stat"><div class="k">看过视频</div><div class="v">${counts.seen_videos ?? "—"}</div><div class="hint">今日预算 ${s.today_budget ?? "—"}</div></div>
      <div class="stat"><div class="k">好感度对象</div><div class="v">${affection.length}</div><div class="hint">${affection[0] ? "最高 " + affection[0].value : "暂无"}</div></div>
    </div>
    <div class="panel-2" style="margin-top:18px">
      <div class="card">
        <div class="section-head" style="margin:0 0 12px"><h2>生活状态</h2><span class="side">${esc(life.time || "—")}</span></div>
        <div class="kv">
          <div class="row-item"><span class="k">心情</span><span class="v">${esc(life.mood || "—")}</span></div>
          <div class="row-item"><span class="k">精力 / 社交</span><span class="v">${pct(life.energy)} / ${pct(life.social)}</span></div>
          <div class="row-item"><span class="k">阶段</span><span class="v">${esc(life.phase || "—")}</span></div>
          <div class="row-item"><span class="k">备注</span><span class="v">${esc(life.note || "—")}</span></div>
        </div>
      </div>
      <div class="card">
        <div class="section-head" style="margin:0 0 12px"><h2>今日心情</h2><span class="side">${esc(mood.date || "—")}</span></div>
        <div class="kv">
          <div class="row-item"><span class="k">心情</span><span class="v">${esc(mood.mood || "—")}</span></div>
          <div class="row-item"><span class="k">提示词</span><span class="v">${esc(mood.prompt || "—")}</span></div>
          <div class="row-item"><span class="k">数据目录</span><span class="path">${esc(s.data_dir || "")}</span></div>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 12px"><h2>今日动作分布</h2><span class="side">共 ${actions.today_total ?? 0} 次</span></div>
      <div class="chips">${byKind.length ? byKind.map(([k, v]) => `<span class="chip">${esc(k)} <span class="count">${v}</span></span>`).join("") : `<span class="hint-text">今天还没有动作</span>`}</div>
      ${recent.length ? `<table class="table" style="margin-top:12px"><thead><tr><th>时间</th><th>动作</th><th>状态</th><th>目标</th></tr></thead><tbody>
        ${recent.map((r) => `<tr><td class="mono">${esc(r.time || "")}</td><td>${esc(r.kind || "")}</td><td><span class="badge ${r.ok ? "ok" : "bad"}">${esc(r.state || "")}</span></td><td class="mono">${esc(r.target || "")}</td></tr>`).join("")}
      </tbody></table>` : `<div class="hint-text">暂无最近动作</div>`}
    </div>
    <div class="panel-2" style="margin-top:18px">
      <div class="card">
        <div class="section-head" style="margin:0 0 12px"><h2>好感度</h2></div>
        ${affection.length ? affection.map((a) => `<div class="row-item"><span class="k">UID ${esc(a.uid)}</span><span class="v">${a.value}</span></div>`).join("") : `<div class="hint-text">暂无好感度数据</div>`}
      </div>
      <div class="card">
        <div class="section-head" style="margin:0 0 12px"><h2>主动推荐</h2><span class="side">${proactive.length} 条</span></div>
        ${proactive.length ? proactive.map((p) => `<div class="row-item" style="align-items:flex-start"><span class="k">${esc(p.time || "")} · ${esc(p.bvid || "")}</span><span class="v" style="text-align:right;max-width:65%">${esc(p.title || "")}${p.comment ? `<br><span class="hint-text">${esc(p.comment)}</span>` : ""}</span></div>`).join("") : `<div class="hint-text">暂无主动推荐</div>`}
      </div>
    </div>`;
}


/* ------------------------------------------------------------- new bot */

function newBotModal() {
  if (!state.instances.length) {
    toast("请先接入一个已有实例作为模板（设置页可指定源码路径）", "warn");
    return;
  }
  const used = {
    dash: Math.max(...state.instances.map((i) => Number(i.dash_port || 0)), 6186) + 1,
    ws: Math.max(...state.instances.map((i) => Number(i.ws_port || 0)), 6199) + 1,
  };
  const data = {
    name: "", qq: "", note: "", template_id: state.instances[0].id,
    dash_port: used.dash, ws_port: used.ws,
    copy_plugins: false, auto_start: true, persona_prompt: "",
  };
  let step = 1;

  const stepsBar = (n) => `<div class="steps">${[1, 2, 3].map((i) =>
    `<div class="step ${i <= n ? "done" : ""}"></div>`).join("")}</div>`;

  const renderStep = (root) => {
    const body = $("#wizard-body", root);
    const foot = $("#wizard-foot", root);
    if (step === 1) {
      body.innerHTML = `${stepsBar(1)}
        <div class="field"><label>机器人名称 *</label>
          <input id="w-name" value="${esc(data.name)}" placeholder="例如 小鲤鱼">
          <span class="help">同时作为人格 ID 与新平台的标识</span></div>
        <div class="row">
          <div class="field"><label>绑定 QQ 号</label><input id="w-qq" value="${esc(data.qq)}" placeholder="可稍后填写"></div>
          <div class="field"><label>备注</label><input id="w-note" value="${esc(data.note)}" placeholder="用途、所属群等"></div>
        </div>`;
      foot.innerHTML = `<button class="btn ghost" data-close>取消</button>
        <button class="btn primary" id="w-next">下一步</button>`;
      $("#w-next", foot).addEventListener("click", () => {
        const name = $("#w-name", body).value.trim();
        if (!name) { toast("请填写机器人名称", "warn"); return; }
        data.name = name;
        data.qq = $("#w-qq", body).value.trim();
        data.note = $("#w-note", body).value.trim();
        step = 2;
        renderStep(root);
      });
    } else if (step === 2) {
      body.innerHTML = `${stepsBar(2)}
        <div class="field"><label>模板实例</label>
          <select id="w-template">${state.instances.map((i) =>
            `<option value="${i.id}" ${i.id === data.template_id ? "selected" : ""}>${esc(i.name)}（复制模型配置与账号）</option>`).join("")}</select>
          <span class="help">新实例会复用模板的模型服务与 Dashboard 账号，并独立存放数据。</span></div>
        <div class="row">
          <div class="field"><label>Dashboard 端口</label><input id="w-dash" type="number" value="${data.dash_port}"></div>
          <div class="field"><label>QQ 反向 WS 端口</label><input id="w-ws" type="number" value="${data.ws_port}"></div>
        </div>
        <div class="field"><label>安装目录</label>
          <input id="w-root" placeholder="留空则自动创建 instances/bot-xxxx">
          <span class="help">留空会在管理器目录的 instances/ 下新建独立目录，与其他实例完全隔离。</span></div>
        <div class="checkline" style="margin-bottom:12px">
          <input type="checkbox" id="w-copy" ${data.copy_plugins ? "checked" : ""}>
          <label for="w-copy">克隆模板实例的插件与插件配置（首次启动即可用）</label>
        </div>
        <div class="field"><label>NapCat 目录（可选）</label>
          <input id="w-napcat" placeholder="例如 D:\\...\\NapCat2">
          <span class="help">填写后可在列表里一键启动 NapCat 完成扫码登录。</span></div>`;
      foot.innerHTML = `<button class="btn ghost" id="w-prev">上一步</button>
        <button class="btn primary" id="w-next">下一步</button>`;
      $("#w-prev", foot).addEventListener("click", () => { step = 1; renderStep(root); });
      $("#w-next", foot).addEventListener("click", () => {
        data.template_id = $("#w-template", body).value;
        data.dash_port = Number($("#w-dash", body).value || 0);
        data.ws_port = Number($("#w-ws", body).value || 0);
        data.root = $("#w-root", body).value.trim();
        data.copy_plugins = $("#w-copy", body).checked;
        data.napcat_dir = $("#w-napcat", body).value.trim();
        step = 3;
        renderStep(root);
      });
    } else {
      body.innerHTML = `${stepsBar(3)}
        <div class="field"><label>人格设定（系统提示词）</label>
          <textarea id="w-prompt" rows="8" placeholder="留空则使用内置的通用人格模板">${esc(data.persona_prompt)}</textarea>
          <span class="help">创建后会自动写入该实例的人格库并绑定默认配置档，可在「模型与人格」继续调整。</span></div>
        <div class="checkline">
          <input type="checkbox" id="w-start" ${data.auto_start ? "checked" : ""}>
          <label for="w-start">创建后立即启动该机器人</label>
        </div>`;
      foot.innerHTML = `<button class="btn ghost" id="w-prev">上一步</button>
        <button class="btn primary" id="w-create">${icon("plus")}创建机器人</button>`;
      $("#w-prev", foot).addEventListener("click", () => { step = 2; renderStep(root); });
      $("#w-create", foot).addEventListener("click", async (e) => {
        data.persona_prompt = $("#w-prompt", body).value.trim();
        data.auto_start = $("#w-start", body).checked;
        const btn = e.currentTarget;
        btn.disabled = true;
        btn.innerHTML = "创建中…";
        try {
          await api("/api/instances", { method: "POST", body: data });
          closeModal();
          toast("机器人已创建" + (data.auto_start ? "，正在启动" : ""));
          await refreshAll(true);
        } catch (err) {
          toast(err.message, "err");
          btn.disabled = false;
          btn.innerHTML = "创建机器人";
        }
      });
    }
  };

  openModal({
    title: "新增机器人",
    sub: "独立数据目录 + 独立端口，复用同一套 AstrBot 源码与解释器",
    wide: true,
    body: `<div id="wizard-body"></div>`,
    footer: `<div id="wizard-foot" style="display:flex;gap:9px;justify-content:flex-end;width:100%"></div>`,
    onMount(root) { renderStep(root); },
  });
}


/* --------------------------------------------------------------- market */

async function viewMarket(view) {
  view.innerHTML = `
    <div class="market-head">
      <div class="search">${icon("search")}<input id="m-q" placeholder="搜索插件名称、作者或关键词，例如 bilibili / 语音"></div>
      <select id="m-target" style="width:auto;min-width:190px">
        ${state.instances.map((i) => `<option value="${i.id}">安装到：${esc(i.name)}${i.status?.running ? "" : "（未运行）"}</option>`).join("")}
      </select>
      <button class="btn ghost" id="m-refresh">${icon("refresh")}刷新索引</button>
    </div>
    <div class="chips" id="m-cats"></div>
    <div id="m-body"></div>`;

  const qInput = $("#m-q", view);
  qInput.value = state.market.q;
  let debounce = null;
  qInput.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.market.q = qInput.value.trim();
      state.market.page = 1;
      loadMarket(view);
    }, 260);
  });
  $("#m-refresh", view).addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try {
      const res = await api("/api/market/refresh", { method: "POST" });
      toast(`索引已刷新，共 ${res.count} 款插件`);
      await loadMarket(view);
    } catch (err) { toast(err.message, "err"); }
    e.currentTarget.disabled = false;
  });

  const cats = await api("/api/market/categories").catch(() => []);
  $("#m-cats", view).innerHTML = [
    `<button class="chip ${state.market.category === "全部" ? "active" : ""}" data-cat="全部">全部 <span class="count">${cats.reduce((s, c) => s + c.count, 0)}</span></button>`,
    ...cats.slice(0, 12).map((c) => `<button class="chip ${state.market.category === c.name ? "active" : ""}" data-cat="${esc(c.name)}">${esc(c.name)} <span class="count">${c.count}</span></button>`),
  ].join("");
  $$("[data-cat]", view).forEach((chip) => chip.addEventListener("click", () => {
    state.market.category = chip.dataset.cat;
    state.market.page = 1;
    $$("[data-cat]", view).forEach((c) => c.classList.toggle("active", c === chip));
    loadMarket(view);
  }));

  await loadMarket(view);
}

async function loadMarket(view) {
  const body = $("#m-body", view);
  body.innerHTML = `<div class="plugin-grid">${Array(6).fill('<div class="skeleton" style="height:170px"></div>').join("")}</div>`;
  const params = new URLSearchParams({
    q: state.market.q, category: state.market.category,
    page: state.market.page, size: state.market.size,
  });
  const data = await api(`/api/market?${params}`);
  state.market.total = data.total;
  state.market.pages = data.pages;
  state.market.items = data.items;

  if (!data.items.length) {
    body.innerHTML = `<div class="empty">${icon("search")}<h4>没有匹配的插件</h4><p>换个关键词试试；市场索引来自本机缓存，可点击「刷新索引」同步。</p></div>`;
    return;
  }

  body.innerHTML = `
    <div class="plugin-grid">
      ${data.items.map((p) => `
        <div class="plugin">
          <div class="plugin-head">
            <div class="plugin-logo">${p.logo ? `<img src="${esc(p.logo)}" alt="" loading="lazy" onerror="this.style.display='none'">` : esc(initials(p.display_name || p.name))}</div>
            <div class="plugin-title">
              <h4 title="${esc(p.name)}">${esc(p.display_name || p.name)}</h4>
              <div class="meta"><span>${esc(p.author)}</span><span>v${esc(p.version || "—")}</span><span>${esc(p.category)}</span></div>
            </div>
          </div>
          <div class="plugin-desc">${esc(p.desc || "暂无描述")}</div>
          <div class="plugin-foot">
            <span class="tag">${p.updated_at ? "更新于 " + esc(p.updated_at.slice(0, 10)) : ""}</span>
            <button class="btn sm primary" data-install="${esc(p.id)}">${icon("download")}安装</button>
          </div>
        </div>`).join("")}
    </div>
    <div class="pager">
      <button class="btn sm ghost" id="m-prev" ${data.page <= 1 ? "disabled" : ""}>上一页</button>
      <span class="info">第 ${data.page} / ${data.pages} 页 · 共 ${data.total} 款</span>
      <button class="btn sm ghost" id="m-next" ${data.page >= data.pages ? "disabled" : ""}>下一页</button>
    </div>`;

  $("#m-prev", body).addEventListener("click", () => {
    state.market.page = Math.max(1, data.page - 1); loadMarket(view);
  });
  $("#m-next", body).addEventListener("click", () => {
    state.market.page = Math.min(data.pages, data.page + 1); loadMarket(view);
  });
  $$("[data-install]", body).forEach((btn) =>
    btn.addEventListener("click", () => installPlugin(btn.dataset.install, btn)));
}

async function installPlugin(pluginId, btn) {
  const target = $("#m-target");
  const instId = target?.value;
  const inst = state.instances.find((i) => i.id === instId);
  if (!inst) { toast("请先选择目标机器人", "warn"); return; }
  if (!inst.status?.running) {
    const ok = await confirmDialog(
      "目标未运行",
      `「${inst.name}」当前未运行，安装插件需要 Dashboard 在线。确定仍然尝试？`, false);
    if (!ok) return;
  }
  btn.disabled = true;
  const old = btn.innerHTML;
  btn.innerHTML = "安装中…";
  try {
    const res = await api("/api/market/install", {
      method: "POST",
      body: { instance_id: instId, plugin_id: pluginId },
    });
    toast(`已提交安装到 ${inst.name}${res?.message ? "：" + res.message : ""}`);
    state.summaries[instId] = null;
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}


/* -------------------------------------------------------------- plugins */

async function viewPlugins(view) {
  if (!state.instances.length) {
    view.innerHTML = `<div class="empty">${icon("market")}<h4>没有可用实例</h4><p>请先新增或接入机器人。</p></div>`;
    return;
  }
  if (!state.pluginInst || !state.instances.find((i) => i.id === state.pluginInst)) {
    state.pluginInst = state.instances[0].id;
  }
  const inst = state.instances.find((i) => i.id === state.pluginInst) || state.instances[0];

  view.innerHTML = `
    <div class="market-head">
      <div class="search">${icon("search")}<input id="pl-q" placeholder="搜索插件名称、作者或关键词"></div>
      <button class="btn primary" id="pl-install">${icon("download")}安装插件</button>
    </div>
    <div class="chips" id="pl-chips">
      ${state.instances.map((i) => `<button class="chip ${i.id === inst.id ? "active" : ""}" data-inst="${i.id}">${esc(i.name)}${i.status?.running ? "" : "（未运行）"}</button>`).join("")}
    </div>
    <div id="pl-body"><div class="skeleton" style="height:120px"></div></div>`;

  const qInput = $("#pl-q", view);
  qInput.value = state.pluginQuery;
  let debounce = null;
  qInput.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.pluginQuery = qInput.value.trim();
      renderPlugins(view, inst);
    }, 200);
  });

  $$("[data-inst]", view).forEach((chip) => chip.addEventListener("click", () => {
    state.pluginInst = chip.dataset.inst;
    viewPlugins(view);
  }));

  $("#pl-install", view).addEventListener("click", () => {
    if (!inst.status?.running) { toast("机器人未运行，请先启动后再安装插件", "warn"); return; }
    pluginInstallModal(view, inst);
  });

  await loadPlugins(view, inst);
}

async function loadPlugins(view, inst, boxSelector = "#pl-body") {
  const box = $(boxSelector, view);
  if (!box) return;
  if (!inst.status?.running) {
    box.innerHTML = `<div class="empty">${icon("play")}<h4>机器人未运行</h4><p>启动后即可查看并管理该实例已安装的插件。</p></div>`;
    return;
  }
  try {
    const list = await api(`/api/instances/${inst.id}/plugins`);
    state.pluginList[inst.id] = Array.isArray(list) ? list : [];
    renderPlugins(view, inst, boxSelector);
  } catch (err) {
    box.innerHTML = `<div class="empty">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
  }
}

function renderPlugins(view, inst, boxSelector = "#pl-body") {
  const box = $(boxSelector, view);
  if (!box) return;
  const all = state.pluginList[inst.id] || [];
  const q = (state.pluginQuery || "").toLowerCase();
  const list = q
    ? all.filter((p) => [p.display_name, p.name, p.author, p.desc].join(" ").toLowerCase().includes(q))
    : all;

  if (!list.length) {
    box.innerHTML = `<div class="empty">${icon("search")}<h4>${all.length ? "没有匹配的插件" : "还没有安装插件"}</h4><p>${all.length ? "换个关键词试试。" : "点击右上角「安装插件」从仓库地址或本地 zip 安装。"}</p></div>`;
    return;
  }
  const enabledCount = list.filter((p) => p.enabled).length;
  box.innerHTML = `
    <div class="card" style="padding:16px">
      <div class="plugin-list-head">共 ${list.length} 个插件 · 已启用 ${enabledCount} 个</div>
      ${list.map((p) => `
        <div class="plugin-row">
          <div class="plugin-row-main">
            <div class="plugin-row-title">
              <strong>${esc(p.display_name || p.name)}</strong>
              <span class="badge ${p.enabled ? "ok" : "bad"}">${p.enabled ? "已启用" : "已停用"}</span>
            </div>
            <div class="plugin-row-meta">${esc(p.name)} · v${esc(p.version || "—")}${p.author ? " · " + esc(p.author) : ""}</div>
            <div class="plugin-row-desc">${esc(p.desc || "暂无描述")}</div>
          </div>
          <div class="plugin-row-actions">
            <button class="btn sm ghost" data-act="toggle" data-id="${esc(p.id)}" data-name="${esc(p.display_name || p.name)}" data-enabled="${p.enabled ? 1 : 0}">${p.enabled ? "停用" : "启用"}</button>
            <button class="btn sm ghost" data-act="config" data-id="${esc(p.id)}" data-name="${esc(p.display_name || p.name)}">配置</button>
            <button class="btn sm ghost" data-act="reload" data-id="${esc(p.id)}" data-name="${esc(p.display_name || p.name)}">重载</button>
            <button class="btn sm danger" data-act="uninstall" data-id="${esc(p.id)}" data-name="${esc(p.display_name || p.name)}">卸载</button>
          </div>
        </div>`).join("")}
    </div>`;
  $$("[data-act]", box).forEach((btn) =>
    btn.addEventListener("click", () => handlePluginAction(view, inst, btn, boxSelector)));
}

async function handlePluginAction(view, inst, btn, boxSelector = "#pl-body") {
  const id = btn.dataset.id;
  const name = btn.dataset.name;
  const act = btn.dataset.act;
  const apiBase = `/api/instances/${inst.id}/plugins/${encodeURIComponent(id)}`;

  if (act === "toggle") {
    const enabled = btn.dataset.enabled === "1";
    btn.disabled = true;
    try {
      await api(`${apiBase}/enabled`, { method: "PATCH", body: { enabled: !enabled } });
      toast(`${enabled ? "已停用" : "已启用"} ${name}`);
      await loadPlugins(view, inst, boxSelector);
    } catch (err) {
      toast(err.message, "err");
      btn.disabled = false;
    }
    return;
  }

  if (act === "config") {
    pluginConfigModal(inst, id, name);
    return;
  }

  if (act === "reload") {
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = "重载中…";
    try {
      await api(`${apiBase}/reload`, { method: "POST" });
      toast(`已重载 ${name}`);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
    return;
  }

  if (act === "uninstall") {
    if (!window.confirm(`确定卸载插件「${name}」吗？\n\n该操作会删除插件目录，不可撤销。`)) return;
    btn.disabled = true;
    try {
      await api(apiBase, { method: "DELETE" });
      toast(`已卸载 ${name}`);
      await loadPlugins(view, inst, boxSelector);
    } catch (err) {
      toast(err.message, "err");
      btn.disabled = false;
    }
  }
}

function viewBiliConsole(view) {
  if (!consoleUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>控制台模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return consoleUI.viewBili(view);
}

function viewDouyinConsole(view) {
  if (!consoleUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>控制台模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return consoleUI.viewDouyin(view);
}

function viewInbox(view) {
  if (!inboxUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>收件箱模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return inboxUI.render(view);
}

function viewApprovals(view) {
  if (!approvalsUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>审批模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return approvalsUI.render(view);
}

function viewAutomationCenter(view) {
  if (!automationCenterUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>自动化中心未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return automationCenterUI.render(view);
}

function viewTasks(view) {
  if (!tasksUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>任务模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return tasksUI.render(view);
}

function viewDigest(view) {
  if (!digestUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>日报模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return digestUI.render(view);
}

function viewDuet(view) {
  if (!duetUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>群聊剧场模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return duetUI.render(view);
}

function viewEvals(view) {
  if (!evalUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>质量回归模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return evalUI.render(view);
}

function viewHuman(view) {
  if (!humanUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>拟人模式模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return humanUI.render(view);
}

function viewMood(view) {
  if (!moodUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>每日心情模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return moodUI.render(view);
}

function viewPresenceLoops(view) {
  if (!presenceUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>活人感模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return presenceUI.render(view, "loops");
}

function viewPresenceRelations(view) {
  if (!presenceUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>活人感模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return presenceUI.render(view, "relations");
}

function viewPresenceRhythm(view) {
  if (!presenceUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>活人感模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return presenceUI.render(view, "rhythm");
}

function viewPresenceRadar(view) {
  if (!presenceUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>活人感模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return presenceUI.render(view, "radar");
}

function viewPresenceDiary(view) {
  if (!presenceUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>活人感模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return presenceUI.render(view, "diary");
}

function viewLife(view) {
  if (!lifeUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>生活线模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return lifeUI.render(view);
}

function viewPeople(view) {
  if (!peopleUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>人物档案模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return peopleUI.render(view);
}

function viewMemes(view) {
  if (!memesUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>群梗库模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return memesUI.render(view);
}

function viewVision(view) {
  if (!visionUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>看图模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return visionUI.render(view);
}

function renderHub(view, route) {
  if (!hubUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>分组页模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  const section = ROUTES[route].section;
  const def = IA_GROUPS[section];
  return hubUI.render(view, {
    title: SECTION_NAME[section] || ROUTES[route].title,
    desc: ROUTES[route].sub,
    groups: (def && def.groups) || [],
  });
}

function viewHubBots(view) { return renderHub(view, "hubBots"); }
function viewHubLive(view) { return renderHub(view, "hubLive"); }
function viewHubGroup(view) { return renderHub(view, "hubGroup"); }
function viewHubPersona(view) { return renderHub(view, "hubPersona"); }
function viewHubMemory(view) { return renderHub(view, "hubMemory"); }
function viewHubAuto(view) { return renderHub(view, "hubAuto"); }
function viewHubPlugin(view) { return renderHub(view, "hubPlugin"); }
function viewHubMonitor(view) { return renderHub(view, "hubMonitor"); }

function viewAlerts(view) {
  if (!opsUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>告警模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return opsUI.renderAlerts(view);
}

function viewDrift(view) {
  if (!opsUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>一致性模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return opsUI.renderDrift(view);
}

function viewResources(view) {
  if (!opsUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>资源模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return opsUI.renderResources(view);
}

function viewCanary(view) {
  if (!opsUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>巡检模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return opsUI.renderCanary(view);
}

function viewMemory(view) {
  if (!memoryUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>记忆模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return memoryUI.viewMemory(view);
}

function dshMissing(view) {
  view.innerHTML = `<div class="empty">${icon("alert")}<h4>DSH 模块未加载</h4><p>请刷新页面或检查 web/assets/dsh.js 是否存在。</p></div>`;
}

function viewCapMarket(view) {
  return viewMarket(view);
}

function viewCapInstalled(view) {
  return viewPlugins(view);
}

function viewCapMatrix(view) {
  if (!opsUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>权限矩阵模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return opsUI.renderMatrix(view);
}

function viewCapDshPlugins(view) {
  if (!dshUI) return dshMissing(view);
  return dshUI.render(view, "plugins");
}

function viewCapDshSkills(view) {
  if (!dshUI) return dshMissing(view);
  return dshUI.render(view, "skills");
}

function viewCapDshAccess(view) {
  if (!dshUI) return dshMissing(view);
  return dshUI.render(view, "access");
}

function viewGuard(view) {
  if (!guardUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>群聊防护模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return guardUI.render(view);
}

function viewReview(view) {
  if (!reviewUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>回复复盘模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return reviewUI.render(view);
}

function viewMemoryFix(view) {
  if (!fixUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>记忆纠错模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return fixUI.render(view);
}

function viewCapOwner(view) {
  if (!ownerUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>主人验证模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return ownerUI.render(view);
}

function viewPersonaRelease(view) {
  if (!releaseUI) {
    view.innerHTML = `<div class="empty">${icon("alert")}<h4>人格灰度模块未加载</h4><p>请刷新页面后重试。</p></div>`;
    return;
  }
  return releaseUI.render(view);
}

function viewCapBili(view) {
  return viewBiliConsole(view);
}

function viewCapDouyin(view) {
  return viewDouyinConsole(view);
}

function viewDshPlugins(view) {
  if (!dshUI) return dshMissing(view);
  return dshUI.render(view, "plugins");
}

function viewDshSkills(view) {
  if (!dshUI) return dshMissing(view);
  return dshUI.render(view, "skills");
}

function viewDshAccess(view) {
  if (!dshUI) return dshMissing(view);
  return dshUI.render(view, "access");
}

function pluginConfigModal(inst, pluginId, name, onSaved = null) {
  openModal({
    title: `插件配置 · ${name}`,
    sub: "直接编辑配置 JSON，保存前会校验格式",
    wide: true,
    body: `
      <div class="field">
        <label>配置 JSON</label>
        <textarea id="pc-json" rows="18" spellcheck="false" placeholder="加载中…" style="font-family:var(--mono);font-size:12.5px"></textarea>
        <span class="help">保存后 AstrBot 会自动重载插件；不确定的字段建议先备份。</span>
      </div>`,
    footer: `<button class="btn ghost" data-close>取消</button>
      <button class="btn primary" id="pc-save" disabled>保存配置</button>`,
    onMount: async (root) => {
      const area = $("#pc-json", root);
      const save = $("#pc-save", root);
      try {
        const res = await api(`/api/instances/${inst.id}/plugins/${encodeURIComponent(pluginId)}/config`);
        area.value = JSON.stringify(res?.config ?? {}, null, 2);
        save.disabled = false;
      } catch (err) {
        area.placeholder = err.message;
        toast(err.message, "err");
      }
      save.addEventListener("click", async () => {
        let config = null;
        try {
          config = JSON.parse(area.value);
        } catch (err) {
          toast(`JSON 格式错误：${err.message}`, "err");
          return;
        }
        if (!config || typeof config !== "object" || Array.isArray(config)) {
          toast("配置必须是 JSON 对象", "err");
          return;
        }
        save.disabled = true;
        save.textContent = "保存中…";
        try {
          await api(`/api/instances/${inst.id}/plugins/${encodeURIComponent(pluginId)}/config`, {
            method: "PUT", body: { config },
          });
          closeModal();
          toast("配置已保存");
          if (onSaved) onSaved();
        } catch (err) {
          toast(err.message, "err");
          save.disabled = false;
          save.textContent = "保存配置";
        }
      });
    },
  });
}

function pluginInstallModal(view, inst, boxSelector = "#pl-body") {
  openModal({
    title: `安装插件 · ${inst.name}`,
    sub: "支持 GitHub 仓库、zip 直链，或直接上传本地 zip 包",
    wide: true,
    body: `
      <div class="field"><label>GitHub 仓库地址</label>
        <input id="pi-repo" placeholder="https://github.com/作者/仓库名"></div>
      <div class="field"><label>下载直链（可选）</label>
        <input id="pi-url" placeholder="https://.../plugin.zip">
        <span class="help">仓库地址与直链至少填一项；只填直链时按 zip 包安装。</span></div>
      <div class="field"><label>本地 zip 安装包</label>
        <input type="file" id="pi-file" accept=".zip">
        <span class="help">选择文件后优先按上传方式安装，忽略上面的地址。</span></div>`,
    footer: `<button class="btn ghost" data-close>取消</button>
      <button class="btn primary" id="pi-submit">${icon("download")}开始安装</button>`,
    onMount: (root) => {
      const btn = $("#pi-submit", root);
      btn.addEventListener("click", async () => {
        const repository = $("#pi-repo", root).value.trim();
        const url = $("#pi-url", root).value.trim();
        const file = $("#pi-file", root).files[0];
        if (!file && !repository && !url) {
          toast("请填写仓库地址、下载直链，或选择本地 zip", "warn");
          return;
        }
        btn.disabled = true;
        btn.textContent = "安装中…";
        try {
          if (file) {
            const form = new FormData();
            form.append("file", file, file.name);
            form.append("ignore_version_check", "true");
            await postForm(`/api/instances/${inst.id}/plugins/upload`, form);
          } else {
            await api(`/api/instances/${inst.id}/plugins/install`, {
              method: "POST",
              body: { repository, url, download_url: url },
            });
          }
          closeModal();
          toast("插件安装请求已完成");
          await loadPlugins(view, inst, boxSelector);
        } catch (err) {
          toast(err.message, "err");
          btn.disabled = false;
          btn.innerHTML = `${icon("download")}开始安装`;
        }
      });
    },
  });
}


/* --------------------------------------------------------------- models */

async function viewModels(view) {
  if (!state.instances.length) {
    view.innerHTML = `<div class="empty">${icon("model")}<h4>没有可用实例</h4><p>请先新增或接入机器人。</p></div>`;
    return;
  }
  if (!state.modelInst) state.modelInst = state.instances[0].id;
  const inst = state.instances.find((i) => i.id === state.modelInst) || state.instances[0];

  view.innerHTML = `
    <div class="chips">
      ${state.instances.map((i) => `<button class="chip ${i.id === inst.id ? "active" : ""}" data-inst="${i.id}">${esc(i.name)}</button>`).join("")}
    </div>
    <div class="panel-2">
      <div class="card">
        <div class="section-head" style="margin:0 0 14px">
          <h2>模型服务</h2>
          <div style="display:flex;align-items:center;gap:10px">
            <span class="side" id="cur-model"></span>
            <button class="btn sm primary" id="btn-new-provider">${icon("plus")}添加模型</button>
          </div>
        </div>
        <div id="provider-list"><div class="skeleton" style="height:90px"></div></div>
      </div>
      <div class="card">
        <div class="section-head" style="margin:0 0 14px"><h2>人格</h2>
          <button class="btn sm ghost" id="btn-new-persona">${icon("plus")}新建</button></div>
        <div id="persona-list"><div class="skeleton" style="height:90px"></div></div>
      </div>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 14px"><h2>深度思考</h2><span class="side">reasoning_effort</span></div>
      <div id="thinking-list"><div class="skeleton" style="height:80px"></div></div>
      <p class="hint-text">推理强度通过请求参数 reasoning_effort 生效，需模型本身支持；deepseek-flash 默认就带推理，设为「关闭」不一定能完全关掉思考。</p>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 14px"><h2>思考过程实测</h2><span class="side" id="think-meta"></span></div>
      <div class="think-form">
        <div class="field"><label>对话模型</label>
          <select id="think-provider"><option value="">加载中…</option></select></div>
        <div class="field"><label>系统提示词（可选）</label>
          <input id="think-system" placeholder="留空直接提问；也可粘贴人格提示词，看带人格时的真实思考">
        </div>
        <div class="field"><label>问题</label>
          <textarea id="think-prompt" rows="3" placeholder="输入一个需要推理的问题">笼子里有鸡和兔共 35 只，脚共 94 只。鸡和兔各有多少只？请一步步推理。</textarea></div>
        <div class="think-actions">
          <button class="btn primary" id="think-run">${icon("pulse")}开始思考</button>
          <label class="think-budget">tokens 上限<input id="think-budget" type="number" min="256" max="16000" step="500" value="8000"></label>
          <span class="hint-text">直接调用模型服务，展示模型返回的 reasoning_content（真实思考过程）与最终回复。</span>
        </div>
      </div>
      <div id="think-result"></div>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 14px"><h2>连接信息</h2></div>
      <div class="kv">
        <div class="row-item"><span class="k">Dashboard</span><span class="v">http://127.0.0.1:${esc(inst.dash_port)}</span></div>
        <div class="row-item"><span class="k">QQ 反向 WS</span><span class="v">ws://127.0.0.1:${esc(inst.ws_port || "—")}</span></div>
        <div class="row-item"><span class="k">反向 Token</span><span class="v">${inst.has_ws_token ? "已配置（本机）" : "未配置"}</span></div>
        <div class="row-item"><span class="k">实例目录</span><span class="path">${esc(inst.root)}</span></div>
      </div>
    </div>`;

  $$("[data-inst]", view).forEach((chip) => chip.addEventListener("click", () => {
    state.modelInst = chip.dataset.inst;
    viewModels(view);
  }));

  await Promise.all([
    loadProviders(view, inst),
    loadPersonas(view, inst),
    loadThinking(view, inst),
  ]);

  $("#btn-new-persona", view).addEventListener("click", () => personaModal(inst, null));
  $("#btn-new-provider", view).addEventListener("click", () => providerModal(inst, null));
  const thinkBtn = $("#think-run", view);
  if (thinkBtn) thinkBtn.addEventListener("click", () => runThink(view, inst));
}

const PROVIDER_TYPE_LABEL = {
  openai_chat_completion: "OpenAI 兼容",
  anthropic_chat_completion: "Anthropic",
  googlegenai_chat_completion: "Google Gemini",
};

const EFFORT_LABEL = { "": "默认", low: "低", medium: "中", high: "高" };

async function loadProviders(view, inst) {
  const box = $("#provider-list", view);
  if (!box) return;
  if (!inst.status?.running) {
    box.innerHTML = `<div class="empty" style="padding:26px">${icon("play")}<h4>机器人未运行</h4><p>启动后即可读取和配置模型服务。</p></div>`;
    return;
  }
  try {
    const data = await api(`/api/instances/${inst.id}/providers`);
    const list = data?.providers || [];
    const currentId = data?.current || "";
    $("#cur-model", view).textContent = currentId ? `当前：${currentId}` : "未设置当前模型";
    if (!list.length) {
      box.innerHTML = `<div class="empty" style="padding:26px">${icon("model")}<h4>还没有对话模型</h4><p>点击右上角「添加模型」，填入服务商 API 即可使用。</p></div>`;
      return;
    }
    box.innerHTML = `<div class="model-grid">${list.map((p) => modelCard(p)).join("")}</div>`;

    $$("[data-provider]", box).forEach((card) => {
      const p = list.find((item) => item.id === card.dataset.provider);
      if (!p) return;
      const testBtn = $("[data-act='test']", card);
      const editBtn = $("[data-act='edit']", card);
      const toggleBtn = $("[data-act='toggle']", card);
      const delBtn = $("[data-act='del']", card);
      const currentBtn = $("[data-act='current']", card);

      if (testBtn) testBtn.addEventListener("click", async () => {
        const origin = testBtn.innerHTML;
        testBtn.disabled = true;
        testBtn.innerHTML = "测试中…";
        try {
          const res = await api(`/api/instances/${inst.id}/providers/${encodeURIComponent(p.id)}/test`, {
            method: "POST", body: {},
          });
          if (res?.status === "available") {
            toast(`${p.id} 连接正常${res.model ? `（${res.model}）` : ""}`);
          } else {
            toast(`${p.id} 连接失败：${res?.error || "未知错误"}`, "err");
          }
        } catch (err) {
          toast(err.message, "err");
        } finally {
          testBtn.disabled = false;
          testBtn.innerHTML = origin;
        }
      });

      if (editBtn) editBtn.addEventListener("click", () => providerModal(inst, p));

      if (currentBtn) currentBtn.addEventListener("click", async () => {
        currentBtn.disabled = true;
        try {
          await api(`/api/instances/${inst.id}/providers/${encodeURIComponent(p.id)}/current`, { method: "POST", body: {} });
          toast(`已切换为 ${p.id}`);
          await loadProviders(view, inst);
        } catch (err) {
          toast(err.message, "err");
          currentBtn.disabled = false;
        }
      });

      if (toggleBtn) toggleBtn.addEventListener("click", async () => {
        toggleBtn.disabled = true;
        try {
          await api(`/api/instances/${inst.id}/providers/${encodeURIComponent(p.id)}/enabled`, {
            method: "PATCH", body: { enabled: !p.enable },
          });
          toast(p.enable ? `已禁用 ${p.id}` : `已启用 ${p.id}`);
          await loadProviders(view, inst);
        } catch (err) {
          toast(err.message, "err");
          toggleBtn.disabled = false;
        }
      });

      if (delBtn) delBtn.addEventListener("click", async () => {
        const yes = await confirmDialog("删除模型", `确定删除模型服务「${p.id}」吗？删除后不可恢复。`);
        if (!yes) return;
        try {
          await api(`/api/instances/${inst.id}/providers/${encodeURIComponent(p.id)}`, { method: "DELETE" });
          toast(`已删除 ${p.id}`);
          await loadProviders(view, inst);
        } catch (err) { toast(err.message, "err"); }
      });
    });
  } catch (err) {
    box.innerHTML = `<div class="empty" style="padding:26px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
  }
}

function modelCard(p) {
  const logo = (p.model || p.id || "?").trim().slice(0, 2).toUpperCase();
  return `
    <div class="model-card ${p.current ? "current" : ""}" data-provider="${esc(p.id)}">
      <div class="model-card-head">
        <div class="model-logo">${esc(logo)}</div>
        <div class="model-title">
          <div class="model-name">${esc(p.id)}</div>
          <div class="model-model">${esc(p.model || "未设置模型名")}</div>
        </div>
        <div class="model-badges">
          ${p.current ? '<span class="badge accent">当前</span>' : ""}
          ${p.enable ? '<span class="badge ok">启用</span>' : '<span class="badge">已禁用</span>'}
        </div>
      </div>
      <div class="model-info">
        <div class="model-info-row"><span class="k">服务商</span><span class="v">${esc(PROVIDER_TYPE_LABEL[p.type] || p.type || "—")}</span></div>
        <div class="model-info-row"><span class="k">API Base</span><span class="v" title="${esc(p.api_base)}">${esc(p.api_base || "—")}</span></div>
        <div class="model-info-row"><span class="k">密钥</span><span class="v">${esc(p.key_masked || "未配置")}</span></div>
        <div class="model-info-row"><span class="k">推理强度</span><span class="v">${esc(EFFORT_LABEL[p.effort] || p.effort || "默认")}</span></div>
      </div>
      <div class="model-actions">
        ${p.current ? "" : `<button class="btn sm primary" data-act="current">设为当前</button>`}
        <button class="btn sm ghost" data-act="test">${icon("pulse")}测试</button>
        <button class="btn sm ghost" data-act="edit">${icon("edit")}编辑</button>
        <button class="btn sm ghost" data-act="toggle">${p.enable ? "禁用" : "启用"}</button>
        <button class="btn sm danger" data-act="del">${icon("trash")}</button>
      </div>
    </div>`;
}

function providerModal(inst, provider) {
  const isNew = !provider;
  const p = provider || { type: "openai_chat_completion", timeout: 120, effort: "" };
  openModal({
    title: isNew ? "添加自定义模型" : `编辑模型 · ${p.id}`,
    sub: "支持任何 OpenAI / Anthropic / Gemini 兼容接口，保存后立即生效",
    wide: true,
    body: `
      <div class="form-grid">
        <div class="field"><label>模型 ID</label>
          <input id="mp-id" value="${esc(p.id || "")}" ${isNew ? "" : "disabled"} placeholder="例如 deepseek-chat、qwen-plus">
          <span class="help">在管理器内识别用的唯一名称，创建后不可修改。</span>
        </div>
        <div class="field"><label>服务商类型</label>
          <select id="mp-type" ${isNew ? "" : "disabled"}>
            ${Object.entries(PROVIDER_TYPE_LABEL).map(([value, label]) =>
              `<option value="${value}" ${p.type === value ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </div>
        <div class="field"><label>模型名称</label>
          <input id="mp-model" value="${esc(p.model || "")}" placeholder="服务端真实模型 ID，如 deepseek-flash">
        </div>
        <div class="field"><label>API Base</label>
          <input id="mp-base" value="${esc(p.api_base || "")}" placeholder="https://api.deepseek.com/v1">
        </div>
        <div class="field"><label>API Key</label>
          <input id="mp-key" type="password" autocomplete="off" placeholder="${isNew ? "sk-..." : `留空保持不变（当前 ${esc(p.key_masked || "未配置")}）`}">
        </div>
        <div class="field"><label>超时（秒）</label>
          <input id="mp-timeout" type="number" min="5" max="600" step="5" value="${esc(p.timeout || 120)}">
        </div>
        <div class="field"><label>推理强度</label>
          <select id="mp-effort">
            ${[["", "默认（不传参数）"], ["low", "低"], ["medium", "中"], ["high", "高"]].map(([value, label]) =>
              `<option value="${value}" ${(p.effort || "") === value ? "selected" : ""}>${label}</option>`).join("")}
          </select>
          <span class="help">写入 custom_extra_body.reasoning_effort，需模型支持。</span>
        </div>
        <div class="field"><label>HTTP 代理（可选）</label>
          <input id="mp-proxy" value="${esc(p.proxy || "")}" placeholder="http://127.0.0.1:7890">
        </div>
      </div>`,
    footer: `<button class="btn ghost" data-close>取消</button>
      <button class="btn primary" id="mp-save">${isNew ? "添加模型" : "保存修改"}</button>`,
    onMount(root) {
      $("#mp-save", root).addEventListener("click", async () => {
        const btn = $("#mp-save", root);
        const body = {
          id: $("#mp-id", root).value.trim(),
          type: $("#mp-type", root).value,
          model: $("#mp-model", root).value.trim(),
          api_base: $("#mp-base", root).value.trim(),
          key: $("#mp-key", root).value.trim(),
          timeout: Number.parseInt($("#mp-timeout", root).value || "120", 10),
          effort: $("#mp-effort", root).value,
          proxy: $("#mp-proxy", root).value.trim(),
        };
        if (!body.id) { toast("请填写模型 ID", "warn"); return; }
        if (!body.model) { toast("请填写模型名称", "warn"); return; }
        if (!body.api_base) { toast("请填写 API Base", "warn"); return; }
        btn.disabled = true;
        const origin = btn.innerHTML;
        btn.innerHTML = "保存中…";
        try {
          if (isNew) {
            await api(`/api/instances/${inst.id}/providers`, { method: "POST", body });
          } else {
            await api(`/api/instances/${inst.id}/providers/${encodeURIComponent(p.id)}`, { method: "PUT", body });
          }
          closeModal();
          toast(isNew ? `模型 ${body.id} 已添加` : `模型 ${body.id} 已保存`);
          await loadProviders($("#view"), inst);
          await loadThinking($("#view"), inst);
        } catch (err) {
          toast(err.message, "err");
          btn.disabled = false;
          btn.innerHTML = origin;
        }
      });
    },
  });
}

async function loadThinking(view, inst) {
  const box = $("#thinking-list", view);
  if (!box) return;
  if (!inst.status?.running) {
    box.innerHTML = `<div class="empty" style="padding:26px">${icon("play")}<h4>机器人未运行</h4><p>启动后即可调整对话模型的深度思考强度。</p></div>`;
    const sel = $("#think-provider", view);
    if (sel) sel.innerHTML = `<option value="">机器人未运行</option>`;
    return;
  }
  try {
    const data = await api(`/api/instances/${inst.id}/thinking`);
    const list = data?.providers || [];
    fillThinkProviders(view, data);
    if (!list.length) {
      box.innerHTML = `<div class="empty" style="padding:26px">${icon("model")}<h4>没有对话模型</h4><p>先在 Dashboard 中添加 chat_completion 类型的模型服务。</p></div>`;
      return;
    }
    const options = [["", "关闭"], ["low", "低"], ["medium", "中"], ["high", "高"]];
    const labels = { low: "低", medium: "中", high: "高" };
    box.innerHTML = list.map((p) => `
      <div class="thinking-row">
        <div class="thinking-main">
          <div class="thinking-title">${esc(p.id)}
            ${p.id === data.current ? '<span class="badge accent">当前使用</span>' : ""}</div>
          <div class="thinking-model">${esc(p.model || "—")}</div>
        </div>
        <div class="seg" data-pid="${esc(p.id)}">
          ${options.map(([value, label]) => `<button class="seg-btn ${p.effort === value ? "active" : ""}" data-effort="${value}">${label}</button>`).join("")}
        </div>
      </div>`).join("");
    $$("[data-pid]", box).forEach((seg) => {
      $$(".seg-btn", seg).forEach((btn) => btn.addEventListener("click", async () => {
        const providerId = seg.dataset.pid;
        const effort = btn.dataset.effort;
        $$(".seg-btn", seg).forEach((b) => { b.disabled = true; });
        try {
          await api(`/api/instances/${inst.id}/thinking`, {
            method: "PUT", body: { provider_id: providerId, effort },
          });
          await loadThinking(view, inst);
          toast(effort
            ? `已把 ${providerId} 的思考强度设为「${labels[effort]}」`
            : `已关闭 ${providerId} 的思考强度参数`);
        } catch (err) {
          toast(err.message, "err");
          $$(".seg-btn", seg).forEach((b) => { b.disabled = false; });
        }
      }));
    });
  } catch (err) {
    box.innerHTML = `<div class="empty" style="padding:26px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
  }
}

const THINK_EFFORT_LABEL = { "": "默认强度", low: "低强度", medium: "中强度", high: "高强度" };

function fillThinkProviders(view, data) {
  const sel = $("#think-provider", view);
  if (!sel) return;
  const list = data?.providers || [];
  const previous = sel.value;
  if (!list.length) {
    sel.innerHTML = `<option value="">没有对话模型</option>`;
    const meta = $("#think-meta", view);
    if (meta) meta.textContent = "";
    return;
  }
  sel.innerHTML = list.map((p) => `
    <option value="${esc(p.id)}">${esc(p.id)} · ${esc(p.model || "—")} · ${THINK_EFFORT_LABEL[p.effort] || p.effort || "默认强度"}</option>`).join("");
  const preferred = previous || data.current || list[0].id;
  if (list.some((p) => p.id === preferred)) sel.value = preferred;
  const meta = $("#think-meta", view);
  if (meta) {
    const item = list.find((p) => p.id === sel.value);
    meta.textContent = item ? `当前强度：${THINK_EFFORT_LABEL[item.effort] || item.effort}` : "";
  }
  sel.onchange = () => {
    const picked = list.find((p) => p.id === sel.value);
    if (meta) {
      meta.textContent = picked
        ? `当前强度：${THINK_EFFORT_LABEL[picked.effort] || picked.effort}`
        : "";
    }
  };
}

async function runThink(view, inst) {
  const btn = $("#think-run", view);
  const out = $("#think-result", view);
  const sel = $("#think-provider", view);
  const providerId = sel?.value || "";
  const prompt = ($("#think-prompt", view)?.value || "").trim();
  if (!providerId) { toast("没有可用的对话模型", "warn"); return; }
  if (!prompt) { toast("请先输入一个让模型思考的问题", "warn"); return; }

  const origin = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = "思考中…";
  const budgetInput = $("#think-budget", view);
  const budget = Number.parseInt(budgetInput?.value || "8000", 10);
  const startedAt = performance.now();
  out.innerHTML = `
    <div class="think-summary">
      <span class="badge accent">${esc(providerId)}</span>
      <span id="think-timer">思考中… 0.0s</span>
      <span id="think-count">思考 0 字</span>
    </div>
    <div class="think-block">
      <div class="think-block-head">${icon("pulse")}思考过程<span class="think-live" id="think-live">流式输出中</span></div>
      <pre class="think-text" id="think-reasoning"></pre>
    </div>
    <div class="think-block reply">
      <div class="think-block-head">${icon("check")}最终回复</div>
      <pre class="think-text" id="think-reply"></pre>
    </div>`;
  const reasoningEl = $("#think-reasoning", out);
  const replyEl = $("#think-reply", out);
  const timerEl = $("#think-timer", out);
  const countEl = $("#think-count", out);
  const liveEl = $("#think-live", out);
  const timer = setInterval(() => {
    timerEl.textContent = `思考中… ${((performance.now() - startedAt) / 1000).toFixed(1)}s`;
  }, 100);

  let reasoning = "";
  let reply = "";
  try {
    const res = await fetch(`/api/instances/${inst.id}/think/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider_id: providerId,
        prompt,
        max_tokens: Number.isFinite(budget) ? budget : 8000,
        system_prompt: ($("#think-system", view)?.value || "").trim(),
      }),
    });
    if (!res.ok || !res.body) {
      let message = `请求失败（HTTP ${res.status}）`;
      try {
        const data = await res.json();
        message = data?.message || data?.detail || message;
      } catch (_) { /* ignore */ }
      throw new Error(message);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.split("\n").find((item) => item.startsWith("data:"));
        if (!line) continue;
        let event = null;
        try {
          event = JSON.parse(line.slice(5).trim());
        } catch (_) {
          continue;
        }
        if (event.type === "reasoning") {
          reasoning += event.text;
          reasoningEl.textContent = reasoning;
          reasoningEl.scrollTop = reasoningEl.scrollHeight;
          countEl.textContent = `思考 ${reasoning.length} 字`;
        } else if (event.type === "content") {
          reply += event.text;
          replyEl.textContent = reply;
          replyEl.scrollTop = replyEl.scrollHeight;
        } else if (event.type === "error") {
          throw new Error(event.message || "模型返回错误");
        }
      }
    }
    if (!reasoning) {
      reasoningEl.innerHTML = `<span class="think-empty-inline">本次没有返回 reasoning_content：该模型可能不输出思考过程，或服务端未开启推理。</span>`;
    }
    if (!reply) {
      replyEl.innerHTML = `<span class="think-empty-inline">模型只返回了思考内容，没有正文——可降低思考强度或提高 max_tokens 后重试。</span>`;
    }
    timerEl.textContent = `用时 ${((performance.now() - startedAt) / 1000).toFixed(1)}s`;
    countEl.textContent = `思考 ${reasoning.length} 字`;
    if (liveEl) liveEl.remove();
    toast(
      reasoning ? `已流式输出 ${reasoning.length} 字思考内容` : "模型这次没有返回思考内容",
      reasoning ? "ok" : "warn"
    );
  } catch (err) {
    out.innerHTML = `<div class="empty" style="padding:18px">${icon("alert")}<h4>思考失败</h4><p>${esc(err.message)}</p></div>`;
    toast(err.message, "err");
  } finally {
    clearInterval(timer);
    btn.disabled = false;
    btn.innerHTML = origin;
  }
}

async function loadPersonas(view, inst) {
  const box = $("#persona-list", view);
  if (!inst.status?.running) {
    box.innerHTML = `<div class="empty" style="padding:26px">${icon("play")}<h4>机器人未运行</h4><p>启动后即可读取人格列表。</p></div>`;
    return;
  }
  try {
    const personas = await api(`/api/instances/${inst.id}/proxy/personas`);
    const list = normalizeList(personas, "personas");
    state.personas[inst.id] = list;
    if (!list.length) {
      box.innerHTML = `<div class="empty" style="padding:26px">${icon("bots")}<h4>还没有人格</h4><p>点击右上角「新建」创建第一个人格。</p></div>`;
      return;
    }
    box.innerHTML = list.map((p) => `
      <div style="display:flex;align-items:center;gap:10px;padding:11px 0;border-top:1px solid var(--line)">
        <div class="avatar" style="width:30px;height:30px;border-radius:9px;font-size:12px;background:linear-gradient(135deg,#5b8cff,#8b7cff)">${esc(initials(p.persona_id))}</div>
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:550">${esc(p.persona_id)}</div>
          <div style="font-size:11.5px;color:var(--dim);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc((p.system_prompt || "").slice(0, 60) || "无提示词预览")}</div>
        </div>
        <button class="btn sm ghost" data-persona="${esc(p.persona_id)}">编辑</button>
      </div>`).join("");
    $$("[data-persona]", box).forEach((btn) =>
      btn.addEventListener("click", () => personaModal(inst, btn.dataset.persona)));
  } catch (err) {
    box.innerHTML = `<div class="empty" style="padding:26px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
  }
}

async function personaModal(inst, personaId) {
  let prompt = "";
  let loading = true;
  const isNew = !personaId;
  openModal({
    title: isNew ? "新建人格" : `编辑人格 · ${personaId}`,
    sub: "人格即系统提示词，决定机器人的说话风格",
    wide: true,
    body: `
      <div class="field"><label>人格 ID</label>
        <input id="p-id" value="${esc(personaId || "")}" ${isNew ? "" : "disabled"} placeholder="通常与机器人同名">
      </div>
      <div class="field"><label>系统提示词</label>
        <textarea id="p-prompt" rows="12" placeholder="加载中…"></textarea>
      </div>`,
    footer: `<button class="btn ghost" data-close>取消</button>
      <button class="btn primary" id="p-save">保存人格</button>`,
    onMount: async (root) => {
      if (!isNew) {
        try {
          const detail = await api(`/api/instances/${inst.id}/proxy/personas/by-id?persona_id=${encodeURIComponent(personaId)}`);
          prompt = detail?.persona?.system_prompt || detail?.system_prompt || "";
        } catch (err) {
          toast(err.message, "err");
        }
      }
      loading = false;
      $("#p-prompt", root).value = prompt;
      $("#p-save", root).addEventListener("click", async () => {
        const id = $("#p-id", root).value.trim();
        const text = $("#p-prompt", root).value.trim();
        if (!id) { toast("请填写人格 ID", "warn"); return; }
        if (!text) { toast("系统提示词不能为空", "warn"); return; }
        try {
          if (isNew) {
            await api(`/api/instances/${inst.id}/proxy/personas`, {
              method: "POST", body: { persona_id: id, system_prompt: text, begin_dialogs: [] },
            });
          } else {
            await api(`/api/instances/${inst.id}/proxy/personas/by-id`, {
              method: "PUT", body: { persona_id: id, system_prompt: text },
            });
          }
          closeModal();
          toast("人格已保存");
          const view = $("#view");
          await loadPersonas(view, inst);
        } catch (err) { toast(err.message, "err"); }
      });
    },
  });
}


/* ----------------------------------------------------------------- learn */

async function viewLearn(view) {
  if (!state.instances.length) {
    view.innerHTML = `<div class="empty">${icon("pulse")}<h4>没有可用实例</h4><p>请先新增或接入机器人。</p></div>`;
    return;
  }
  if (!state.learnInst || !state.instances.find((i) => i.id === state.learnInst)) {
    state.learnInst = state.instances[0].id;
  }
  const inst = state.instances.find((i) => i.id === state.learnInst) || state.instances[0];

  view.innerHTML = `
    <div class="chips">
      ${state.instances.map((i) => `<button class="chip ${i.id === inst.id ? "active" : ""}" data-inst="${i.id}">${esc(i.name)}${i.status?.running ? "" : "（未运行）"}</button>`).join("")}
    </div>
    <div class="card al-card">
      <div class="section-head" style="margin:0 0 12px">
        <h2>全自动学习</h2>
        <span class="side">
          <label class="al-switch">
            <input type="checkbox" id="al-toggle">
            <span class="al-track"></span>
          </label>
        </span>
      </div>
      <div class="al-status" id="al-status">加载中…</div>
      <div class="al-controls">
        <div class="field"><label>学习周期</label>
          <select id="al-interval">
            ${[[30, "30 分钟"], [60, "1 小时"], [120, "2 小时"], [240, "4 小时"], [480, "8 小时"], [720, "12 小时"], [1440, "每天"]]
              .map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}
          </select></div>
        <div class="field"><label>每轮抽样</label>
          <select id="al-limit">
            ${[100, 200, 300, 500].map((n) => `<option value="${n}">${n} 条</option>`).join("")}
          </select></div>
        <div class="field"><label>生成模型</label>
          <select id="al-provider"><option value="">加载中…</option></select></div>
      </div>
      <div class="al-actions">
        <button class="btn primary" id="al-run">${icon("pulse")}立即学习一次</button>
        <button class="btn ghost" id="al-dry">试学（不保存）</button>
        <button class="btn ghost" id="al-note" hidden>查看上次笔记</button>
        <span class="help" style="margin:0">开启后按周期自动从最近的 QQ 群聊、私聊和 B站私信抽样，总结风格并追加到「自动学习」档案（不写人格）。</span>
      </div>
      <div class="al-history" id="al-history"></div>
    </div>
    <div class="learn-grid">
      <div class="card">
        <div class="section-head" style="margin:0 0 14px"><h2>素材来源</h2></div>
        <div id="ln-sources"><div class="skeleton" style="height:120px"></div></div>
      </div>
      <div class="card">
        <div class="section-head" style="margin:0 0 14px"><h2>学习设置</h2></div>
        <div class="field"><label>学习对象</label>
          <select id="ln-speaker" disabled><option value="">全部成员</option></select></div>
        <div class="field"><label>抽样条数</label>
          <select id="ln-limit">
            ${[50, 100, 200, 500].map((n) => `<option value="${n}" ${state.learnLimit === n ? "selected" : ""}>${n} 条</option>`).join("")}
          </select></div>
        <div class="field"><label>生成模型</label>
          <select id="ln-provider" disabled><option value="">加载中…</option></select></div>
        <div class="learn-actions">
          <button class="btn ghost" id="ln-preview">${icon("refresh")}随机抽样预览</button>
          <button class="btn primary" id="ln-summarize">${icon("pulse")}生成学习笔记</button>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 14px"><h2>抽样预览</h2><span class="side" id="ln-count"></span></div>
      <div id="ln-preview-box"><div class="empty" style="padding:32px">${icon("search")}<h4>还没有抽样</h4><p>先在左侧选择素材来源，再点击「随机抽样预览」。</p></div></div>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 14px"><h2>学习笔记</h2><span class="side" id="ln-sampled"></span></div>
      <div class="field">
        <textarea id="ln-note" rows="14" placeholder="点击「生成学习笔记」后，这里会出现可编辑的 Markdown 结果"></textarea>
        <span class="help">生成笔记后会自动追加到同名风格档案；第一次新建，之后在原文末尾按日期新增。可修改后再次追加，不会改动人格提示词。QQ 私聊来源会追加到关系级档案，只对那个 QQ 生效；群聊/B站保持实例级。</span>
      </div>
      <div class="learn-apply">
        <div class="field" style="margin:0;flex:1"><label>风格档案名称</label>
          <input id="ln-style-name" type="text" value="手动学习风格" placeholder="例如：大肥鱼口吻"></div>
        <button class="btn primary" id="ln-apply" disabled>追加编辑后的内容</button>
      </div>
    </div>`;

  $$("[data-inst]", view).forEach((chip) => chip.addEventListener("click", () => {
    state.learnInst = chip.dataset.inst;
    state.learnSource = "";
    state.learnKey = "";
    state.learnNoteKey = "";
    state.learnSavedNote = "";
    state.learnProvider = "";
    state.learnData = { qq: [], bili: [] };
    viewLearn(view);
  }));

  $("#ln-limit", view).addEventListener("change", (e) => {
    state.learnLimit = Number(e.target.value || 200);
  });
  $("#ln-preview", view).addEventListener("click", (e) => learnPreview(view, inst, e.currentTarget));
  $("#ln-summarize", view).addEventListener("click", (e) => learnSummarize(view, inst, e.currentTarget));
  $("#ln-apply", view).addEventListener("click", (e) => learnApply(view, inst, e.currentTarget));
  $("#ln-note", view).addEventListener("input", () => syncLearnApply(view));

  $("#al-toggle", view).addEventListener("change", (e) => {
    saveAutoLearn(view, inst, { enabled: e.target.checked });
  });
  ["al-interval", "al-limit", "al-provider"].forEach((id) => {
    $("#" + id, view).addEventListener("change", () => {
      saveAutoLearn(view, inst, {
        interval_min: Number($("#al-interval", view).value),
        limit: Number($("#al-limit", view).value),
        provider_id: $("#al-provider", view).value,
      });
    });
  });
  $("#al-run", view).addEventListener("click", (e) => autoLearnRun(view, inst, e.currentTarget));
  $("#al-dry", view).addEventListener("click", (e) => autoLearnRun(view, inst, e.currentTarget, true));
  $("#al-note", view).addEventListener("click", () => autoLearnNote(view, inst));

  await loadLearnSources(view, inst);
  await loadLearnModels(view, inst);
  await loadAutoLearn(view, inst);
  clearAutoTimer();
  state.autoTimer = setInterval(() => refreshAutoLearn(view, inst), 4000);
}

async function loadLearnSources(view, inst) {
  const box = $("#ln-sources", view);
  try {
    const data = await api(`/api/instances/${inst.id}/learn/sources`);
    state.learnData = { qq: data.qq || [], bili: data.bili || [] };
    const groups = [
      { title: "QQ 群聊", items: (data.qq || []).filter((s) => s.is_group) },
      { title: "QQ 私聊", items: (data.qq || []).filter((s) => !s.is_group) },
      { title: "B站私信", items: data.bili || [] },
    ];
    box.innerHTML = groups.map((group) => `
      <div class="source-group">
        <div class="source-group-title">${group.title}</div>
        ${group.items.length
          ? group.items.map((s) => `
            <button class="source-item ${state.learnKey === s.key ? "active" : ""}" data-key="${esc(s.key)}" data-source="${s.key.startsWith("bili") ? "bili" : "qq"}">
              <div class="source-item-main">
                <div class="source-item-label">${esc(s.label)}</div>
                <div class="source-item-meta">${s.count} 条 · 最近 ${esc(s.last_at || "—")}</div>
              </div>
            </button>`).join("")
          : `<div class="source-empty">暂无记录</div>`}
      </div>`).join("");
    $$("[data-key]", box).forEach((btn) => btn.addEventListener("click", () => {
      selectLearnSource(view, btn.dataset.key, btn.dataset.source);
    }));
    if (state.learnKey && !findLearnSource(state.learnKey)) {
      state.learnKey = "";
      state.learnSource = "";
    }
    if (state.learnKey) selectLearnSource(view, state.learnKey, state.learnSource);
  } catch (err) {
    box.innerHTML = `<div class="empty" style="padding:26px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
  }
}

function findLearnSource(key) {
  return [...(state.learnData.qq || []), ...(state.learnData.bili || [])].find((s) => s.key === key);
}

function selectLearnSource(view, key, source) {
  state.learnKey = key;
  state.learnSource = source;
  $$("[data-key]", view).forEach((btn) => btn.classList.toggle("active", btn.dataset.key === key));
  const select = $("#ln-speaker", view);
  const entry = findLearnSource(key);
  const speakers = (entry?.speakers || []).filter((s) => s.name);
  select.innerHTML = `<option value="">全部成员</option>` + speakers.map(
    (s) => `<option value="${esc(s.name)}">${esc(s.name)}（${s.count} 条）</option>`).join("");
  select.disabled = false;
}

async function loadLearnModels(view, inst) {
  const select = $("#ln-provider", view);
  if (!select) return;
  if (!inst.status?.running) {
    select.innerHTML = `<option value="">机器人未运行，启动后可选择模型</option>`;
    return;
  }
  try {
    const data = await api(`/api/instances/${inst.id}/thinking`);
    const list = data?.providers || [];
    state.learnProvidersList = list;
    select.innerHTML = `<option value="">默认模型（${esc(data?.current || "未设置")}）</option>` +
      list.map((p) => `<option value="${esc(p.id)}">${esc(p.id)} · ${esc(p.model || "—")}</option>`).join("");
    select.value = list.some((p) => p.id === state.learnProvider) ? state.learnProvider : "";
    select.disabled = false;
    select.addEventListener("change", () => { state.learnProvider = select.value; });
  } catch (err) {
    select.innerHTML = `<option value="">读取失败：${esc(err.message)}</option>`;
  }
}

function learnRequireSource() {
  if (!state.learnKey || !state.learnSource) {
    toast("请先在左侧选择素材来源", "warn");
    return false;
  }
  return true;
}

async function learnPreview(view, inst, btn) {
  if (!learnRequireSource()) return;
  const box = $("#ln-preview-box", view);
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "抽样中…";
  try {
    const data = await api(`/api/instances/${inst.id}/learn/sample`, {
      method: "POST",
      body: {
        source: state.learnSource,
        key: state.learnKey,
        speaker: $("#ln-speaker", view).value,
        limit: state.learnLimit,
      },
    });
    const messages = data.messages || [];
    $("#ln-count", view).textContent = messages.length ? `抽到 ${messages.length} 条` : "";
    if (!messages.length) {
      box.innerHTML = `<div class="empty" style="padding:26px">${icon("search")}<h4>没有抽到消息</h4><p>换一个学习对象或来源再试试。</p></div>`;
      return;
    }
    const shown = messages.slice(0, 50);
    box.innerHTML = `
      <div class="chat-preview">
        ${shown.map((m) => `
          <div class="chat-line">
            <div class="chat-meta"><span class="chat-time">${esc(m.time)}</span><span class="chat-sender">${esc(m.sender)}</span></div>
            <div class="chat-text">${esc(m.text)}</div>
          </div>`).join("")}
      </div>
      ${messages.length > shown.length ? `<div class="hint-text">仅展示前 ${shown.length} 条（共 ${messages.length} 条）</div>` : ""}`;
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

function learnTarget(key) {
  const entry = findLearnSource(key);
  // QQ 私聊（key 为 qq:<QQ号> 且不是群聊）落到关系级；群聊/B站仍为实例级。
  const relationship = Boolean(entry && entry.key.startsWith("qq:") && !entry.is_group);
  return {
    entry,
    scope: relationship ? "relationship" : "instance",
    personKey: relationship ? String(entry.user_id || entry.key.split(":")[1] || "") : "",
  };
}

function syncLearnApply(view) {
  const btn = $("#ln-apply", view);
  if (!btn) return;
  const note = $("#ln-note", view).value.trim();
  const saved = Boolean(state.learnSavedNote) && note === state.learnSavedNote;
  btn.disabled = !note || saved;
  btn.textContent = saved ? "已追加到风格档案" : "追加编辑后的内容";
}

async function learnSummarize(view, inst, btn) {
  if (!learnRequireSource()) return;
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "生成中…";
  const target = learnTarget(state.learnKey);
  const name = $("#ln-style-name", view).value.trim() || "手动学习风格";
  try {
    const data = await api(`/api/instances/${inst.id}/learn/summarize`, {
      method: "POST",
      body: {
        source: state.learnSource,
        key: state.learnKey,
        speaker: $("#ln-speaker", view).value,
        limit: state.learnLimit,
        provider_id: state.learnProvider,
        save: true,
        name,
        scope: target.scope,
        person_key: target.personKey,
      },
    });
    $("#ln-note", view).value = data.note || "";
    // 记住这条笔记是由哪个来源生成的，追加时据此判断是否已切走来源。
    state.learnNoteKey = state.learnKey;
    state.learnSavedNote = data.saved ? String(data.note || "") : "";
    $("#ln-sampled", view).textContent = `基于 ${data.sampled} 条消息 · ${data.provider_id}`;
    syncLearnApply(view);
    if (data.saved) {
      toast(target.scope === "relationship"
        ? "已自动追加到该 QQ 私聊的关系级档案"
        : "已自动追加到风格档案");
    } else if (data.save_error) {
      toast(data.save_error, "warn");
    } else {
      toast("学习笔记已生成，可修改后追加到风格档案");
    }
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

async function learnApply(view, inst, btn) {
  const name = $("#ln-style-name", view).value.trim() || "手动学习风格";
  const note = $("#ln-note", view).value.trim();
  if (!note) { toast("学习笔记不能为空", "warn"); return; }
  // 笔记可能来自 A 来源，追加时已切到 B 来源：拒绝保存，避免写进 B 的关系级风格。
  if (state.learnNoteKey && state.learnKey !== state.learnNoteKey) {
    toast("学习笔记来自另一个来源，请重新生成后再保存", "warn");
    return;
  }
  const noteKey = state.learnNoteKey || state.learnKey;
  const target = learnTarget(noteKey);
  btn.disabled = true;
  btn.textContent = "追加中…";
  try {
    const data = await api(`/api/instances/${inst.id}/learn/apply`, {
      method: "POST",
      body: { name, note, scope: target.scope, person_key: target.personKey },
    });
    $("#ln-style-name", view).value = name;
    state.learnNoteKey = noteKey;
    state.learnSavedNote = note;
    syncLearnApply(view);
    const action = data && data.appended ? "已追加到" : "已新建";
    toast(target.scope === "relationship"
      ? `${action}该 QQ 私聊的关系级风格档案`
      : `${action}风格档案`);
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    syncLearnApply(view);
  }
}


/* ------------------------------------------------------------- auto learn */

function clearAutoTimer() {
  if (state.autoTimer) { clearInterval(state.autoTimer); state.autoTimer = null; }
}

function autoLearnCfg(instId) {
  return state.autoCfg?.[instId] || null;
}

async function loadAutoLearn(view, inst) {
  try {
    const data = await api("/api/auto-learn");
    state.autoCfg = data || {};
    renderAutoLearn(view, inst, autoLearnCfg(inst.id));
  } catch (err) {
    const box = $("#al-status", view);
    if (box) box.textContent = `读取状态失败：${err.message}`;
  }
}

async function refreshAutoLearn(view, inst) {
  const status = $("#al-status", view);
  if (!status) return;
  try {
    const data = await api("/api/auto-learn");
    state.autoCfg = data || {};
    renderAutoLearn(view, inst, autoLearnCfg(inst.id));
  } catch (_) { /* 静默轮询失败 */ }
}

async function saveAutoLearn(view, inst, patch) {
  try {
    const cfg = await api(`/api/auto-learn/${inst.id}`, { method: "PUT", body: patch });
    state.autoCfg = state.autoCfg || {};
    state.autoCfg[inst.id] = cfg;
    renderAutoLearn(view, inst, cfg);
    toast(cfg.enabled ? "全自动学习已开启" : "已保存设置");
  } catch (err) {
    toast(err.message, "err");
    await refreshAutoLearn(view, inst);
  }
}

async function autoLearnRun(view, inst, btn, dryRun = false) {
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = dryRun ? "试学中…" : "学习中…";
  try {
    await api(`/api/auto-learn/${inst.id}/run`, { method: "POST", body: { dry_run: dryRun } });
    toast(dryRun ? "已开始试学，本轮只预览，不保存" : "已开始学习，完成后会追加到风格档案（不写人格）");
    await refreshAutoLearn(view, inst);
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

function autoLearnNote(view, inst) {
  const cfg = autoLearnCfg(inst.id) || {};
  const note = String(cfg.note || "").trim();
  if (!note) { toast("还没有学习笔记", "warn"); return; }
  openModal({
    title: `上次学习笔记 · ${inst.name}`,
    sub: "自动学习/试学生成的可编辑 Markdown 结果",
    wide: true,
    body: `<div class="field"><textarea id="al-note-text" rows="20" readonly style="font-family:var(--mono);font-size:12.5px"></textarea></div>`,
    footer: `<button class="btn ghost" data-close>关闭</button>`,
    onMount(root) {
      $("#al-note-text", root).value = note;
    },
  });
}

const AL_STATUS = {
  ok: { text: "上次学习成功", cls: "ok" },
  skip: { text: "上次跳过", cls: "warn" },
  error: { text: "上次失败", cls: "err" },
  wait: { text: "等待机器人运行", cls: "warn" },
  preview: { text: "试学完成（未保存）", cls: "warn" },
  cleared: { text: "已清除自动学习笔记", cls: "" },
};

function renderAutoLearn(view, inst, cfg) {
  if (!cfg) return;
  const status = $("#al-status", view);
  const toggle = $("#al-toggle", view);
  if (toggle) toggle.checked = !!cfg.enabled;

  if (status) {
    if (cfg.running) {
      status.innerHTML = `<span class="al-dot running"></span>正在学习：正在抽样并总结最近的聊天记录，结果会追加到风格档案…`;
    } else if (!cfg.enabled) {
      status.innerHTML = `<span class="al-dot off"></span>全自动学习未开启，可手动「立即学习一次」试试效果；学习结果只追加到风格档案，不写人格。`;
    } else if (cfg.next_run_in != null) {
      const parts = [];
      const mins = Math.floor(cfg.next_run_in / 60);
      if (mins > 0) parts.push(`${mins} 分钟`);
      const secs = cfg.next_run_in % 60;
      if (!parts.length || secs > 0) parts.push(`${secs} 秒`);
      const last = cfg.last_run_text ? `，上次：${esc(cfg.last_run_text)}` : "";
      status.innerHTML = `<span class="al-dot on"></span>已开启，约 ${parts.join("")} 后进行下一轮${last}`;
    } else {
      status.innerHTML = `<span class="al-dot on"></span>已开启`;
    }
  }

  const interval = $("#al-interval", view);
  if (interval && document.activeElement !== interval) interval.value = String(cfg.interval_min || 120);
  const limit = $("#al-limit", view);
  if (limit && document.activeElement !== limit) limit.value = String(cfg.limit || 200);

  const noteBtn = $("#al-note", view);
  if (noteBtn) noteBtn.hidden = !cfg.note;

  const provider = $("#al-provider", view);
  if (provider && document.activeElement !== provider) {
    const list = state.learnProvidersList || [];
    if (list.length) {
      const chosen = list.some((p) => p.id === cfg.provider_id) ? cfg.provider_id : "";
      provider.innerHTML = `<option value="">默认模型</option>` +
        list.map((p) => `<option value="${esc(p.id)}" ${p.id === chosen ? "selected" : ""}>${esc(p.id)} · ${esc(p.model || "—")}</option>`).join("");
    } else {
      provider.innerHTML = `<option value="">默认模型</option>`;
    }
  }

  const history = $("#al-history", view);
  if (history) {
    const items = cfg.history || [];
    if (!items.length) {
      history.innerHTML = `<div class="al-hist-empty">还没有学习记录。开启后每轮学习都会记录在这里。</div>`;
    } else {
      history.innerHTML = items.slice(0, 6).map((h) => {
        const meta = AL_STATUS[h.status] || { text: h.status, cls: "" };
        const sources = h.sources?.length ? `（${esc(h.sources.join("、"))}）` : "";
        const sampled = h.sampled ? ` · ${h.sampled} 条` : "";
        return `<div class="al-hist-item ${meta.cls}">
          <span class="al-hist-time">${esc(h.time || "")}</span>
          <span class="al-hist-msg">${esc(h.message || meta.text)}${sampled}${sources}</span>
        </div>`;
      }).join("");
    }
  }
}


/* ----------------------------------------------------------------- logs */

function clearLogTimer() {
  if (state.logTimer) { clearInterval(state.logTimer); state.logTimer = null; }
}

async function viewLogs(view) {
  if (!state.instances.length) {
    view.innerHTML = `<div class="empty">${icon("logs")}<h4>没有可查看的实例</h4></div>`;
    return;
  }
  if (!state.logInst || !state.instances.find((i) => i.id === state.logInst)) {
    state.logInst = state.instances[0].id;
  }
  view.innerHTML = `
    <div class="log-toolbar">
      <select id="l-inst" style="width:auto;min-width:180px">
        ${state.instances.map((i) => `<option value="${i.id}" ${i.id === state.logInst ? "selected" : ""}>${esc(i.name)}</option>`).join("")}
      </select>
      <button class="chip ${state.logSource === "bot" ? "active" : ""}" data-src="bot">机器人日志</button>
      <button class="chip ${state.logSource === "console" ? "active" : ""}" data-src="console">启动控制台</button>
      <div class="spacer"></div>
      <label class="checkline"><input type="checkbox" id="l-auto" ${state.logAuto ? "checked" : ""}>自动刷新</label>
      <button class="btn sm ghost" id="l-refresh">${icon("refresh")}刷新</button>
    </div>
    <div class="terminal" id="l-term"><span class="empty">加载中…</span></div>`;

  $("#l-inst", view).addEventListener("change", (e) => {
    state.logInst = e.target.value;
    fetchLog(view);
  });
  $$("[data-src]", view).forEach((chip) => chip.addEventListener("click", () => {
    state.logSource = chip.dataset.src;
    $$("[data-src]", view).forEach((c) => c.classList.toggle("active", c === chip));
    fetchLog(view);
  }));
  $("#l-refresh", view).addEventListener("click", () => fetchLog(view));
  $("#l-auto", view).addEventListener("change", (e) => {
    state.logAuto = e.target.checked;
    clearLogTimer();
    if (state.logAuto) state.logTimer = setInterval(() => fetchLog(view, true), 3000);
  });

  await fetchLog(view);
  clearLogTimer();
  if (state.logAuto) state.logTimer = setInterval(() => fetchLog(view, true), 3000);
}

async function fetchLog(view, quiet = false) {
  const term = $("#l-term", view);
  if (!term) return;
  try {
    const data = await api(`/api/instances/${state.logInst}/logs?lines=300&source=${state.logSource}`);
    const text = data.text || "";
    if (!text.trim()) {
      if (!quiet) term.innerHTML = `<span class="empty">暂无日志。机器人启动后这里会显示输出。</span>`;
      return;
    }
    const atBottom = term.scrollHeight - term.scrollTop - term.clientHeight < 60;
    term.innerHTML = logLinesHtml(text);
    if (atBottom || !quiet) term.scrollTop = term.scrollHeight;
  } catch (err) {
    if (!quiet) term.innerHTML = `<span class="empty">${esc(err.message)}</span>`;
  }
}


function logLinesHtml(text) {
  return String(text || "").split("\n").map((line) => {
    const lower = line.toLowerCase();
    let cls = "";
    if (lower.includes("error") || lower.includes("traceback") || lower.includes("critical")) cls = "error";
    else if (lower.includes("warning") || lower.includes("warn")) cls = "warn";
    else if (lower.includes("success") || lower.includes("已启动")) cls = "ok";
    else if (lower.includes("debug")) cls = "dim";
    return `<span class="ln ${cls}">${esc(line) || " "}</span>`;
  }).join("");
}


/* ----------------------------------------------------------- live think */

function closeThinkStream() {
  if (state.thinkES) {
    try { state.thinkES.close(); } catch (_) { /* ignore */ }
    state.thinkES = null;
  }
  if (state.thinkTimer) { clearInterval(state.thinkTimer); state.thinkTimer = null; }
  if (state.thinkRaf) { cancelAnimationFrame(state.thinkRaf); state.thinkRaf = null; }
  state.thinkRuns = new Map();
  state.thinkNodes = {};
  state.thinkDirty = new Set();
}

function thinkEmptyHTML() {
  return `<div class="empty" id="tl-empty">${icon("pulse")}<h4>等待消息</h4>
    <p>QQ 收到消息并调用模型后，思考过程会实时出现在这里。</p></div>`;
}

function thinkColor(run) {
  const inst = state.instances.find((i) => i.id === run.instance_id);
  return run.color || inst?.color || "#5b8cff";
}

function thinkClock(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function thinkAtBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 42;
}

async function viewThinkLive(view) {
  closeThinkStream();
  view.innerHTML = `
    <div class="log-toolbar">
      <div class="tl-conn" id="tl-conn"><span class="dot"></span><span>连接中…</span></div>
      <span class="tl-hint">在 QQ 里给机器人发消息，模型的思考过程会实时出现在下方。</span>
      <div class="spacer"></div>
      <button class="btn sm ghost" id="tl-clear">${icon("trash")}清空</button>
    </div>
    <div class="think-live-list" id="tl-list">${thinkEmptyHTML()}</div>`;

  $("#tl-clear", view).addEventListener("click", async () => {
    try { await api("/api/live-think/clear", { method: "POST", body: {} }); }
    catch (err) { toast(err.message, "err"); }
  });

  try {
    const data = await api("/api/live-think/recent?limit=20");
    seedThinkRuns(data.runs || []);
  } catch (err) {
    toast(err.message, "err");
  }
  if (state.route !== "think") return;
  connectThinkStream();
  state.thinkTimer = setInterval(tickThinkCards, 4000);
}

function seedThinkRuns(runs) {
  const list = $("#tl-list");
  if (!list) return;
  state.thinkNodes = {};
  state.thinkRuns = new Map();
  list.innerHTML = thinkEmptyHTML();
  runs.forEach((run) => upsertThinkRun(run, false));
}

function connectThinkStream() {
  if (state.thinkES) return;
  const es = new EventSource("/api/live-think/stream");
  state.thinkES = es;
  es.onopen = () => setThinkConn(true, "已连接");
  es.onerror = () => setThinkConn(false, "连接中断，正在重连…");
  es.onmessage = (event) => {
    let payload = null;
    try { payload = JSON.parse(event.data); } catch (_) { return; }
    handleThinkEvent(payload);
  };
}

function setThinkConn(ok, text) {
  const el = $("#tl-conn");
  if (!el) return;
  el.className = `tl-conn ${ok ? "on" : "off"}`;
  el.innerHTML = `<span class="dot"></span><span>${esc(text)}</span>`;
}

function handleThinkEvent(ev) {
  if (!document.getElementById("tl-list")) return;
  if (ev.type === "hello") {
    seedThinkRuns(ev.runs || []);
  } else if (ev.type === "run_start") {
    upsertThinkRun(ev.run, true);
  } else if (ev.type === "run_done") {
    upsertThinkRun(ev.run, false);
  } else if (ev.type === "delta") {
    const run = state.thinkRuns.get(ev.run_id);
    if (!run) return;
    if (ev.reasoning) run.reasoning += ev.reasoning;
    if (ev.content) run.content += ev.content;
    markThinkDirty(ev.run_id);
  } else if (ev.type === "clear") {
    seedThinkRuns([]);
  }
}

function upsertThinkRun(run, atTop) {
  const current = state.thinkRuns.get(run.run_id);
  if (current) Object.assign(current, run);
  else {
    state.thinkRuns.set(run.run_id, { ...run });
    if (atTop) trimThinkCards();
  }
  if (state.thinkNodes[run.run_id]) {
    applyThinkSnapshot(run.run_id);
  } else {
    createThinkCard(run, atTop);
  }
  markThinkDirty(run.run_id);
}

function trimThinkCards() {
  const nodes = Object.entries(state.thinkNodes);
  if (nodes.length < 24) return;
  const victim = nodes[nodes.length - 1];
  victim[1].el.remove();
  delete state.thinkNodes[victim[0]];
  state.thinkRuns.delete(victim[0]);
}

function createThinkCard(run, atTop) {
  const list = $("#tl-list");
  if (!list) return null;
  $("#tl-empty", list)?.remove();

  const el = document.createElement("div");
  el.className = "card think-live-card";
  el.innerHTML = `
    <div class="tl-head">
      <span class="tl-bot"><span class="status-dot"></span><b></b></span>
      <span class="tl-model"></span>
      <span class="tl-conv" title=""></span>
      <span class="spacer"></span>
      <span class="tl-time"></span>
      <span class="badge accent tl-status">思考中</span>
    </div>
    <div class="think-block">
      <div class="think-block-head">${icon("model")}<span>思考过程</span><span class="think-live tl-live">实时</span></div>
      <pre class="think-text tl-reason"></pre>
    </div>
    <div class="think-block reply tl-reply" hidden>
      <div class="think-block-head">${icon("pulse")}<span>回复内容</span></div>
      <pre class="think-text tl-content"></pre>
    </div>`;
  const node = {
    el,
    bot: $(".tl-bot", el),
    botName: $(".tl-bot b", el),
    dot: $(".tl-bot .status-dot", el),
    model: $(".tl-model", el),
    conv: $(".tl-conv", el),
    time: $(".tl-time", el),
    status: $(".tl-status", el),
    live: $(".tl-live", el),
    reason: $(".tl-reason", el),
    reply: $(".tl-reply", el),
    content: $(".tl-content", el),
  };
  node.dot.style.background = thinkColor(run);
  node.botName.textContent = run.instance_name || "未匹配实例";
  node.model.textContent = run.model || "";
  node.conv.textContent = run.conversation_id || "";
  node.conv.title = run.conversation_id || "";
  el.dataset.runid = run.run_id;
  state.thinkNodes[run.run_id] = node;

  if (atTop) list.prepend(el);
  else list.appendChild(el);
  applyThinkSnapshot(run.run_id);
  return node;
}

function applyThinkSnapshot(runId) {
  const node = state.thinkNodes[runId];
  const run = state.thinkRuns.get(runId);
  if (!node || !run) return;
  const running = run.status === "running";
  const stale = running && Date.now() / 1000 - (run.updated_at || 0) > 150;
  let cls = "accent";
  let text = "思考中";
  if (run.status === "done") { cls = "ok"; text = "已完成"; }
  else if (run.status === "error") { cls = "bad"; text = "出错"; }
  else if (stale) { cls = "warn"; text = "无更新"; }
  node.status.className = `badge ${cls} tl-status`;
  node.status.textContent = text;
  node.live.hidden = !running;
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - (run.started_at || 0)));
  node.time.textContent = thinkClock(run.started_at) + (running ? ` · ${seconds}s` : "");
  if (run.error) node.status.title = run.error;
}

function markThinkDirty(runId) {
  state.thinkDirty.add(runId);
  if (state.thinkRaf) return;
  state.thinkRaf = requestAnimationFrame(() => {
    state.thinkRaf = null;
    const dirty = state.thinkDirty;
    state.thinkDirty = new Set();
    dirty.forEach(flushThinkCard);
  });
}

function flushThinkCard(runId) {
  const node = state.thinkNodes[runId];
  const run = state.thinkRuns.get(runId);
  if (!node || !run) return;
  const stick = thinkAtBottom(node.reason);
  const hasReason = Boolean(run.reasoning);
  node.reason.classList.toggle("placeholder", !hasReason);
  node.reason.textContent = hasReason
    ? run.reasoning
    : (run.status === "running" ? "等待模型输出…" : "（本次没有返回思考内容，模型可能未开启推理）");
  if (stick) node.reason.scrollTop = node.reason.scrollHeight;
  const hasContent = Boolean(run.content);
  node.reply.hidden = !hasContent;
  if (hasContent) {
    const stickContent = thinkAtBottom(node.content);
    node.content.textContent = run.content;
    if (stickContent) node.content.scrollTop = node.content.scrollHeight;
  }
}

function tickThinkCards() {
  Object.keys(state.thinkNodes).forEach(applyThinkSnapshot);
}


/* ------------------------------------------------------------- settings */

async function loadNotifyStatus(view) {
  const box = $("#notify-status", view);
  if (!box) return;
  try {
    const data = await api("/api/notify/status");
    const channels = (data.channels || []).join(" + ") || "未配置渠道";
    const last = data.last_at ? ` · 上次 ${new Date(data.last_at * 1000).toLocaleString()}` : "";
    const error = data.last_error ? ` · ${data.last_error}` : "";
    box.textContent = `${data.enabled ? "已启用" : "未启用"} · ${channels}${last}${error}`;
  } catch (err) {
    box.textContent = err.message;
  }
}

async function viewSettings(view) {
  const s = state.settings;
  view.innerHTML = `
    <div class="panel-2">
      <div class="card">
        <div class="section-head" style="margin:0 0 16px"><h2>路径配置</h2></div>
        <div class="field"><label>AstrBot 源码目录</label>
          <input id="s-source" value="${esc(s.astrbot_source || "")}">
          <span class="help">包含 main.py 与 astrbot/ 的目录，所有实例共享这一份源码。</span></div>
        <div class="field"><label>Python 解释器</label>
          <input id="s-python" value="${esc(s.python_exe || "")}">
          <span class="help">建议使用 AstrBot 自带的 .venv\\Scripts\\python.exe。</span></div>
        <div class="field"><label>新实例默认目录</label>
          <input id="s-instances" value="${esc(s.instances_dir || "")}"></div>
        <div class="field"><label>自动发现扫描目录</label>
          <input id="s-scan" value="${esc(s.scan_dir || "")}">
          <span class="help">首次启动时会扫描该目录下含 data/cmd_config.json 的 AstrBot 实例。</span></div>
        <button class="btn primary" id="s-save">保存设置</button>
      </div>

      <div class="card">
        <div class="section-head" style="margin:0 0 16px"><h2>环境状态</h2></div>
        <div class="kv">
          <div class="row-item"><span class="k">源码</span><span class="v" style="color:${state.env.source_ok ? "var(--ok)" : "var(--bad)"}">${state.env.source_ok ? "存在" : "缺失"}</span></div>
          <div class="row-item"><span class="k">解释器</span><span class="v" style="color:${state.env.python_ok ? "var(--ok)" : "var(--bad)"}">${state.env.python_ok ? "存在" : "缺失"}</span></div>
          <div class="row-item"><span class="k">市场索引</span><span class="v">${state.env.market_index || 0} 条</span></div>
        </div>
        <div style="margin-top:16px;padding-top:14px;border-top:1px dashed var(--line)">
          <div style="font-size:11.5px;color:var(--dim);margin-bottom:8px">管理方式说明</div>
          <p style="font-size:12.5px;line-height:1.75;color:var(--muted);margin:0">
            每个机器人拥有独立的 <code style="color:var(--accent-text)">ASTRBOT_ROOT</code> 数据目录与独立端口，
            共享同一份 AstrBot 源码与 Python 环境。启动时管理器会设置该环境变量，
            因此新增机器人不会复制数百 MB 的运行环境。
          </p>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 14px"><h2>告警推送</h2>
        <span class="side" id="notify-status">读取中…</span>
      </div>
      <div class="form-grid">
        <label class="checkline" style="grid-column:1/-1"><input type="checkbox" id="notify-enabled" ${s.alert_push_enabled ? "checked" : ""}>启用后台推送（每 60 秒检查一次，只推新告警）</label>
        <div class="field"><label>Webhook 地址</label>
          <input id="notify-webhook" value="${esc(s.alert_webhook_url || "")}" placeholder="https://example.com/fleet-hook"></div>
        <div class="field"><label>Telegram Bot Token</label>
          <input id="notify-telegram-token" type="password" autocomplete="off" value="" placeholder="${s.alert_telegram_token ? "已配置，留空保持" : "可选"}"></div>
        <div class="field"><label>Telegram Chat ID</label>
          <input id="notify-telegram-chat" value="${esc(s.alert_telegram_chat_id || "")}" placeholder="可选"></div>
        <div class="field"><label>最低级别</label>
          <select id="notify-severity">
            <option value="warning" ${s.alert_min_severity !== "critical" ? "selected" : ""}>警告及以上</option>
            <option value="critical" ${s.alert_min_severity === "critical" ? "selected" : ""}>仅严重</option>
          </select></div>
      </div>
      <div class="chips">
        <button class="btn sm primary" id="notify-save">保存推送设置</button>
        <button class="btn sm ghost" id="notify-test">发送测试</button>
        <button class="btn sm ghost" id="notify-run">立即推送</button>
      </div>
      <p class="hint-text">Webhook 收到 JSON：{text, overall, alerts}。Telegram 使用 Bot API。密钥只保存在本机 data/settings.json；6 小时内同一告警不重复推送。</p>
    </div>

    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 14px"><h2>备份与恢复</h2>
        <button class="btn sm primary" id="b-create">${icon("download")}立即备份</button>
      </div>
      <div class="chips" id="b-options" style="margin-bottom:12px">
        <label class="checkline"><input type="checkbox" data-backup-comp="manager" checked>管理器配置</label>
        <label class="checkline"><input type="checkbox" data-backup-comp="instances" checked>AstrBot 实例</label>
        <label class="checkline"><input type="checkbox" data-backup-comp="dsh" checked>DSH 配置</label>
        <label class="checkline"><input type="checkbox" data-backup-login>浏览器登录资料（体积大）</label>
      </div>
      <div id="backup-list"><div class="skeleton" style="height:80px"></div></div>
      <p class="hint-text">恢复前会自动生成回滚快照；恢复需要输入 RESTORE 确认。演练只解压到临时目录并检查 JSON/SQLite，不会覆盖运行数据。默认保留最近 7 份。</p>
    </div>

    <div class="card" style="margin-top:18px">
      <div class="section-head" style="margin:0 0 14px"><h2>关于</h2></div>
      <div class="kv">
        <div class="row-item"><span class="k">管理器</span><span class="v">牧鱼 v1.23.11</span></div>
        <div class="row-item"><span class="k">运行方式</span><span class="v">本地 FastAPI + 桌面外壳（pywebview / Edge App）</span></div>
        <div class="row-item"><span class="k">登录凭据</span><span class="v">保存于 data/instances.json，仅本机可见</span></div>
      </div>
    </div>`;

  $("#b-create", view).addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    const components = $$("[data-backup-comp]", view).filter((node) => node.checked)
      .map((node) => node.dataset.backupComp);
    if (!components.length) { toast("至少选择一个备份组件", "warn"); return; }
    btn.disabled = true;
    try {
      const item = await api("/api/backups", {
        method: "POST",
        body: {
          components,
          include_login: Boolean($("[data-backup-login]", view)?.checked),
          label: "manual",
        },
      });
      toast(`备份完成：${item.files} 个文件`);
      await loadBackups(view);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
    }
  });
  loadBackups(view);
  loadNotifyStatus(view);

  $("#notify-save", view).addEventListener("click", async () => {
    const token = $("#notify-telegram-token", view).value.trim();
    const patch = {
      alert_push_enabled: $("#notify-enabled", view).checked,
      alert_webhook_url: $("#notify-webhook", view).value.trim(),
      alert_telegram_chat_id: $("#notify-telegram-chat", view).value.trim(),
      alert_min_severity: $("#notify-severity", view).value,
    };
    if (token) patch.alert_telegram_token = token;
    try {
      const saved = await api("/api/settings", { method: "PUT", body: patch });
      state.settings = { ...state.settings, ...saved };
      $("#notify-telegram-token", view).value = "";
      toast("推送设置已保存");
      await loadNotifyStatus(view);
    } catch (err) { toast(err.message, "err"); }
  });
  $("#notify-test", view).addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    try {
      const result = await api("/api/notify/test", { method: "POST", body: {} });
      toast(`测试已发送：${Object.keys(result.statuses || {}).join(" / ") || "无渠道"}`);
    } catch (err) { toast(err.message, "err"); }
    finally { btn.disabled = false; }
  });
  $("#notify-run", view).addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    try {
      const result = await api("/api/notify/run", { method: "POST", body: {} });
      toast(result.sent ? `已推送 ${result.count} 条新告警` : `未推送：${result.reason || result.error || "没有新告警"}`, result.sent ? "ok" : "warn");
      await loadNotifyStatus(view);
    } catch (err) { toast(err.message, "err"); }
    finally { btn.disabled = false; }
  });

  $("#s-save", view).addEventListener("click", async () => {
    try {
      await api("/api/settings", {
        method: "PUT",
        body: {
          astrbot_source: $("#s-source", view).value.trim(),
          python_exe: $("#s-python", view).value.trim(),
          instances_dir: $("#s-instances", view).value.trim(),
          scan_dir: $("#s-scan", view).value.trim(),
        },
      });
      toast("设置已保存");
      await refreshAll(true);
    } catch (err) { toast(err.message, "err"); }
  });

}

async function fetchPluginTools(inst) {
  const raw = await api(`/api/instances/${inst.id}/proxy/tools`);
  const list = Array.isArray(raw) ? raw : raw?.tools || [];
  return list.filter((t) => t && t.origin === "plugin");
}

async function loadToolPermissionsInto(box, inst, onChanged) {
  if (!box) return;
  if (!inst) {
    box.innerHTML = `<div class="empty" style="padding:24px">${icon("bots")}<h4>没有可用实例</h4></div>`;
    return;
  }
  if (!inst.status?.running) {
    box.innerHTML = `<div class="empty" style="padding:24px">${icon("play")}<h4>机器人未运行</h4><p>启动后才能读取和修改工具权限。</p></div>`;
    return;
  }
  box.innerHTML = `<div class="skeleton" style="height:90px"></div>`;
  try {
    const list = (await fetchPluginTools(inst)).sort((a, b) => {
      const oa = String(a.origin_display_name || a.origin_name || "");
      const ob = String(b.origin_display_name || b.origin_name || "");
      return oa.localeCompare(ob) || String(a.name).localeCompare(String(b.name));
    });
    if (!list.length) {
      box.innerHTML = `<div class="empty" style="padding:24px">${icon("model")}<h4>没有插件工具</h4></div>`;
      return;
    }
    const adminCount = list.filter((t) => t.permission === "admin").length;
    box.innerHTML = `<div class="plugin-list-head">共 ${list.length} 个插件工具 · 仅主人 ${adminCount} 个</div>
      ${list.map((t) => {
        const perm = t.permission === "admin" ? "admin" : "member";
        return `<div class="plugin-row">
          <div class="plugin-row-main">
            <div class="plugin-row-title"><strong>${esc(t.name)}</strong>
              <span class="badge ${perm === "admin" ? "ok" : ""}">${perm === "admin" ? "仅主人" : "所有人"}</span>
              ${t.active === false ? '<span class="badge bad">停用</span>' : ""}</div>
            <div class="plugin-row-meta">${esc(t.origin_display_name || t.origin_name || "插件")} · ${t.permission_configured ? "已配置" : "默认"}</div>
            <div class="plugin-row-desc">${esc(t.description || "")}</div>
          </div>
          <div class="plugin-row-actions">
            <select class="select" data-tool="${esc(t.name)}" style="width:150px">
              <option value="member" ${perm === "member" ? "selected" : ""}>所有人（member）</option>
              <option value="admin" ${perm === "admin" ? "selected" : ""}>仅主人（admin）</option>
            </select>
          </div>
        </div>`;
      }).join("")}`;
    $$("select[data-tool]", box).forEach((sel) => sel.addEventListener("change", async () => {
      const name = sel.dataset.tool;
      const permission = sel.value;
      sel.disabled = true;
      try {
        await api(`/api/instances/${inst.id}/proxy/tools/${encodeURIComponent(name)}/permission`, {
          method: "PATCH", body: { permission },
        });
        toast(`${name} 已设为 ${permission === "admin" ? "仅主人" : "所有人"}`);
        if (onChanged) await onChanged();
      } catch (err) {
        toast(err.message, "err");
        sel.disabled = false;
      }
    }));
  } catch (err) {
    box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
  }
}

const BILI_HARDEN_TOOLS = [
  "bili_action", "bili_block_user", "bili_send_video",
  "bili_parse_video", "bili_watch_videos", "watch_video",
];

async function hardenBiliTools(inst, btn, onDone) {
  if (!inst) { toast("没有可用实例", "warn"); return; }
  if (!inst.status?.running) { toast("机器人未运行", "warn"); return; }
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "收口中…";
  try {
    const tools = await fetchPluginTools(inst);
    const names = BILI_HARDEN_TOOLS.filter((name) => tools.some((t) => t.name === name));
    if (!names.length) {
      toast("当前实例没有可收口的 B站写工具", "warn");
      return;
    }
    const ok = await confirmDialog(
      "收口 B站写操作",
      `将把 ${names.join("、")} 设为仅主人可用。确定继续？`,
      false);
    if (!ok) return;
    let done = 0;
    for (const name of names) {
      try {
        await api(`/api/instances/${inst.id}/proxy/tools/${encodeURIComponent(name)}/permission`, {
          method: "PATCH", body: { permission: "admin" },
        });
        done += 1;
      } catch (err) {
        toast(`${name} 失败：${err.message}`, "err");
      }
    }
    toast(`已收口 ${done}/${names.length} 个 B站工具`);
    if (onDone) await onDone();
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

function backupSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.round(n / 1024)} KB`;
}

async function loadBackups(view) {
  const box = $("#backup-list", view);
  if (!box) return;
  try {
    const items = await api("/api/backups");
    if (!items.length) {
      box.innerHTML = `<div class="empty" style="padding:18px">${icon("download")}<h4>还没有备份</h4><p>点击“立即备份”生成第一份。</p></div>`;
      return;
    }
    box.innerHTML = items.map((item) => `
      <div class="plugin-row">
        <div class="plugin-row-main">
          <div class="plugin-row-title"><strong>${esc(item.name)}</strong>
            <span class="badge">${esc(backupSize(item.bytes))}</span></div>
          <div class="plugin-row-meta">${esc(new Date(item.created * 1000).toLocaleString())} · sha256 ${esc((item.sha256 || "").slice(0, 12))}…</div>
        </div>
        <div class="plugin-row-actions">
          <button class="btn sm ghost" data-backup-verify="${esc(item.path)}">校验</button>
          <button class="btn sm ghost" data-backup-rehearse="${esc(item.path)}">演练</button>
          <button class="btn sm danger" data-backup-restore="${esc(item.path)}">恢复</button>
        </div>
      </div>`).join("");
    $$("[data-backup-verify]", box).forEach((btn) =>
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const result = await api("/api/backups/verify", { method: "POST", body: { path: btn.dataset.backupVerify } });
          toast(result.ok ? `校验通过：${result.files} 个文件` : `校验失败：${(result.bad || []).slice(0, 3).join("、") || result.error}`, result.ok ? "ok" : "err");
        } catch (err) { toast(err.message, "err"); }
        finally { btn.disabled = false; }
      }));
    $$("[data-backup-rehearse]", box).forEach((btn) =>
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const r = await api("/api/backups/rehearse", { method: "POST", body: { path: btn.dataset.backupRehearse } });
          const detail = `${r.files} 个文件 · JSON ${r.json_checked} 个 · SQLite ${r.sqlite || "无"} · ${r.duration_ms} ms`;
          toast(r.ok ? `演练通过：${detail}` : `演练未通过：${(r.warnings || []).join("；") || detail}`, r.ok ? "ok" : "err");
        } catch (err) { toast(err.message, "err"); }
        finally { btn.disabled = false; }
      }));
    $$("[data-backup-restore]", box).forEach((btn) =>
      btn.addEventListener("click", async () => {
        const typed = window.prompt("恢复会覆盖当前配置，并从备份写入文件。\n恢复前会自动生成回滚快照。\n\n输入 RESTORE 确认：", "");
        if (typed !== "RESTORE") { if (typed !== null) toast("未输入 RESTORE，已取消", "warn"); return; }
        btn.disabled = true;
        try {
          const result = await api("/api/backups/restore", {
            method: "POST",
            body: { path: btn.dataset.backupRestore, confirm: "RESTORE" },
          });
          toast(`已恢复 ${result.restored} 个文件；回滚快照已生成`);
          await loadBackups(view);
        } catch (err) {
          toast(err.message, "err");
          btn.disabled = false;
        }
      }));
  } catch (err) {
    box.innerHTML = `<div class="empty" style="padding:18px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
  }
}

/* ----------------------------------------------------------------- theme */

const THEME_KEY = "astrbot.manager.theme";

function applyTheme(theme) {
  const light = theme === "light";
  document.documentElement.dataset.theme = light ? "light" : "dark";
  const btn = $("#btn-theme");
  if (btn) {
    btn.innerHTML = `<svg class="icon"><use href="#i-${light ? "sun" : "moon"}"/></svg>`;
    btn.title = light ? "切换到深色主题" : "切换到浅色主题";
  }
  try { localStorage.setItem(THEME_KEY, light ? "light" : "dark"); } catch (_) { /* ignore */ }
}

$("#btn-theme").addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});

applyTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");


/* ----------------------------------------------------------------- boot */

$("#btn-refresh").addEventListener("click", () => refreshAll());
$("#btn-new").addEventListener("click", newBotModal);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

window.addEventListener("hashchange", () => navigate());

(async function boot() {
  try {
    await loadBootstrap();
    await navigate();
  } catch (err) {
    $("#view").innerHTML = `<div class="empty">${icon("alert")}<h4>无法连接管理服务</h4><p>${esc(err.message)}</p></div>`;
  }
})();
