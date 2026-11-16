/* 牧鱼 · 一键部署首屏：机器上没有任何机器人时只展示这个页面 */
(function () {
  "use strict";

  const PRESET_COLORS = ["#5b8cff", "#8b5cf6", "#22c55e", "#f59e0b", "#ef4444"];

  function create({ api, esc, icon, toast, onReady }) {
    const state = {
      status: null,
      vendorId: "",
      form: { name: "我的机器人", api_key: "", api_base: "", model: "", skip_probe: false, qq: "" },
      busy: false,
      job: null,
      error: "",
      timer: null,
      entering: false,
      models: [],
      modelNote: "",
      modelSource: "",
      modelBusy: false,
      autoKey: "",
      testBusy: false,
      testResult: null,
      install: null,
      suiteChecked: null,
    };

    const vendorById = (id) => (state.status?.vendors || []).find((item) => item.id === id) || null;
    const currentVendor = () => vendorById(state.vendorId) || state.status?.vendors?.[0] || null;
    const suiteList = () => state.status?.runtime?.suite || [];
    const envBusy = () => Boolean(state.install && state.install.kind === "env" && !state.install.job?.state?.match(/done|failed/));

    function pickVendor(id) {
      const vendor = vendorById(id);
      if (!vendor) return;
      state.vendorId = id;
      state.form.api_base = vendor.api_base;
      state.form.model = vendor.model;
      state.form.api_key = "";
      state.models = [];
      state.modelNote = "";
      state.modelSource = "";
      state.testResult = null;
      state.autoKey = "";
    }

    function stopTimer() {
      if (state.timer) {
        clearTimeout(state.timer);
        state.timer = null;
      }
    }

    function envReady() {
      return Boolean(state.status?.env?.ready);
    }

    function stepIcon(kind) {
      if (kind === "ok") return icon("check");
      if (kind === "fail") return icon("alert");
      if (kind === "running") return '<span class="deploy-spinner"></span>';
      return '<span class="deploy-step-dot"></span>';
    }

    function renderSteps(job, opts = {}) {
      const steps = job?.steps || [];
      return `
        <div class="deploy-progress ${job?.state === "failed" ? "is-failed" : ""}">
          <div class="deploy-progress-head">
            <strong>${job?.state === "failed" ? "安装遇到问题" : job?.state === "done" ? "已完成" : esc(job?.title || "正在安装")}</strong>
            <span>${esc(job?.message || "")}</span>
          </div>
          <ul class="deploy-steps">
            ${steps.map((step) => `
              <li class="deploy-step ${esc(step.state || "pending")}">
                <i>${stepIcon(step.state)}</i>
                <div>
                  <b>${esc(step.label)}</b>
                  ${step.detail ? `<small>${esc(step.detail)}</small>` : ""}
                </div>
              </li>`).join("")}
          </ul>
          ${job?.state === "failed" ? `<div class="deploy-error">${esc(job.error || job.message || "安装失败")}</div>` : ""}
          ${opts.enter && job?.state === "done" ? `<button class="btn primary deploy-enter" data-act="enter">进入控制台</button>` : ""}
          ${opts.enter && job?.state === "failed" ? `<button class="btn deploy-enter" data-act="enter">进入控制台查看日志</button>` : ""}
        </div>`;
    }

    function installJob(kind) {
      if (!state.install || state.install.kind !== kind) return "";
      return renderSteps(state.install.job);
    }

    function vendorCards() {
      return (state.status?.vendors || []).map((vendor, index) => {
        const color = PRESET_COLORS[index % PRESET_COLORS.length];
        const active = vendor.id === state.vendorId;
        return `
          <button type="button" class="deploy-vendor ${active ? "active" : ""}" data-vendor="${esc(vendor.id)}"
            style="--vendor-color:${color}">
            <span class="deploy-vendor-mark">${esc(vendor.label.slice(0, 1))}</span>
            <span class="deploy-vendor-text">
              <b>${esc(vendor.label)}</b>
              <small>${esc(vendor.model || "自定义模型")}</small>
            </span>
            ${active ? `<span class="deploy-vendor-check">${icon("check")}</span>` : ""}
          </button>`;
      }).join("");
    }

    function envPanel() {
      const env = state.status?.env || {};
      const job = state.install?.kind === "env" ? state.install.job : null;
      const running = Boolean(job && !job.state?.match(/done|failed/));
      return `
        <div class="deploy-env ${envReady() ? "ok" : "bad"}">
          <div class="deploy-env-head">
            <b>运行环境</b>
            <span>${envReady() ? "已就绪" : "未就绪，可一键安装"}</span>
          </div>
          <div class="deploy-env-row">
            <span>${env.source_ok ? "✓" : "!"} AstrBot 源码</span>
            <code>${esc(env.source || "未找到 main.py")}</code>
          </div>
          <div class="deploy-env-row">
            <span>${env.python_ok ? "✓" : "!"} Python 解释器</span>
            <code>${esc(env.python || "未找到 python.exe")}</code>
          </div>
          ${envReady() ? "" : `
            <div class="deploy-env-actions">
              <button class="btn primary" data-act="install-env" ${running ? "disabled" : ""}>
                ${running ? "正在安装运行环境…" : "一键安装运行环境"}
              </button>
              <small>自动下载 AstrBot 源码、Python 与依赖，只在本机执行</small>
            </div>
            <details class="deploy-advanced">
              <summary>已经装过 AstrBot？手动指定路径</summary>
              <div class="deploy-env-fix">
                <label class="field"><span>AstrBot 源码目录</span>
                  <input id="deploy-source" placeholder="例如 D:\\AstrBot" value="${esc(env.source || "")}"></label>
                <label class="field"><span>Python 解释器</span>
                  <input id="deploy-python" placeholder="例如 D:\\AstrBot\\.venv\\Scripts\\python.exe" value="${esc(env.python || "")}"></label>
                <button class="btn" data-act="save-env">保存路径</button>
              </div>
            </details>`}
          ${job ? installJob("env") : ""}
        </div>`;
    }

    function formPanel() {
      const vendor = currentVendor();
      if (!vendor) return "";
      const custom = vendor.id === "custom";
      const allModels = Array.from(new Set([...(vendor.models || []), ...state.models]));
      return `
        <div class="deploy-field-grid">
          <label class="field"><span>机器人名字</span>
            <input id="deploy-name" maxlength="24" value="${esc(state.form.name)}" placeholder="例如 大肥鱼"></label>
          <label class="field"><span>模型名称</span>
            <input id="deploy-model" value="${esc(state.form.model)}" placeholder="例如 deepseek-v4-pro" list="deploy-models"></label>
          <datalist id="deploy-models">${allModels.map((item) => `<option value="${esc(item)}"></option>`).join("")}</datalist>
        </div>
        <label class="field"><span>接口地址（OpenAI 兼容）</span>
          <input id="deploy-base" value="${esc(state.form.api_base)}" placeholder="https://api.deepseek.com/v1"></label>
        <div class="deploy-keyline">
          <label class="field"><span>API Key${vendor.key_required ? "（必填）" : "（可留空）"}</span>
            <input id="deploy-key" type="password" autocomplete="off" value="${esc(state.form.api_key)}"
              placeholder="${vendor.key_required ? "粘贴你的 API Key，离开输入框会自动检测模型" : "本地模型可留空"}"></label>
          <div class="deploy-key-actions">
            <button class="btn" data-act="detect" ${state.modelBusy ? "disabled" : ""}>${state.modelBusy ? "检测中…" : "检测模型"}</button>
            <button class="btn" data-act="test" ${state.testBusy ? "disabled" : ""}>${state.testBusy ? "测试中…" : "测试连接"}</button>
          </div>
        </div>
        ${state.modelNote ? `<div class="deploy-hint ${state.modelSource === "remote" ? "ok" : ""}">${esc(state.modelNote)}</div>` : ""}
        ${state.testResult
          ? state.testResult.ok
            ? `<div class="deploy-hint ok">连接成功 · ${esc(String(state.testResult.latency_ms ?? 0))}ms · 模型 ${esc(state.testResult.model || state.form.model)}</div>`
            : `<div class="deploy-hint bad">${esc(state.testResult.error || "连接失败")}</div>`
          : ""}
        <details class="deploy-advanced">
          <summary>高级选项</summary>
          <label class="deploy-check">
            <input type="checkbox" id="deploy-skip" ${state.form.skip_probe ? "checked" : ""}>
            <span>跳过部署前的连接测试（接口暂时不可达时仍创建机器人）</span>
          </label>
        </details>`;
    }

    function enhancePanel() {
      const job = state.job;
      if (!job || job.state !== "done") return "";
      const instanceId = job.instance_id || "";
      const suite = suiteList();
      if (state.suiteChecked === null) {
        state.suiteChecked = suite.filter((item) => item.available).map((item) => item.id);
      }
      return `
        <section class="deploy-card deploy-enhance">
          <div class="deploy-card-head">
            <h2>3. 补齐管理器同款能力</h2>
            <span>可选，稍后也能在控制台里安装</span>
          </div>
          <div class="deploy-enhance-grid">
            <div class="deploy-enhance-item">
              <b>QQ 登录环境（NapCat）</b>
              <p>自动下载 NapCat 最新版并写入反向 WS，让机器人能真正登录 QQ。</p>
              <label class="field"><span>QQ 号（可留空，登录后自动同步）</span>
                <input id="deploy-qq" value="${esc(state.form.qq)}" placeholder="例如 123456789"></label>
              <button class="btn primary" data-act="install-napcat" ${instanceId ? "" : "disabled"}>一键安装 NapCat</button>
            </div>
            <div class="deploy-enhance-item">
              <b>插件套装（全部 ${suite.length} 个）</b>
              <p>生活线、梗库、长期记忆、B站/抖音/QQ空间、表情包等全部管理器同款插件。</p>
              <ul class="deploy-suite">
                ${suite.map((item) => `
                  <li>
                    <label class="deploy-check">
                      <input type="checkbox" data-suite="${esc(item.id)}" ${state.suiteChecked.includes(item.id) ? "checked" : ""} ${item.available ? "" : "disabled"}>
                      <span>${esc(item.label)}${item.available ? "" : "（暂无可用的安装源）"}</span>
                    </label>
                  </li>`).join("")}
              </ul>
              <button class="btn primary" data-act="install-plugins" ${instanceId ? "" : "disabled"}>一键安装插件</button>
            </div>
          </div>
          ${installJob("napcat")}
          ${installJob("plugins")}
        </section>`;
    }

    function paint(view) {
      if (!state.status) return;
      view.innerHTML = `
        <div class="deploy-shell">
          <header class="deploy-hero">
            <div class="deploy-brandline">
              <span class="deploy-logo">${icon("fish")}</span>
              <span>牧鱼 · 舰队管理器</span>
            </div>
            <span class="deploy-kicker">首次启动</span>
            <h1>先给你的电脑部署一个机器人</h1>
            <p>选一个模型服务商，填入 API Key，剩下的创建目录、写配置、启动 AstrBot 都会自动完成。没有环境也可以一键安装。</p>
          </header>
          ${envPanel()}
          <div class="deploy-grid">
            <section class="deploy-card">
              <div class="deploy-card-head"><h2>1. 选择模型服务商</h2><span>预设 8 家，支持自定义</span></div>
              <div class="deploy-vendors">${vendorCards()}</div>
              <div class="deploy-form">
                ${formPanel()}
              </div>
            </section>
            <aside class="deploy-card deploy-side">
              <div class="deploy-card-head"><h2>2. 一键部署</h2></div>
              <ul class="deploy-summary">
                <li><span>实例目录</span><b>独立隔离</b></li>
                <li><span>管理面板</span><b>自动分配端口</b></li>
                <li><span>QQ 适配器</span><b>预置反向 WS</b></li>
                <li><span>模型配置</span><b>自动写入</b></li>
              </ul>
              ${state.job
                ? renderSteps(state.job, { enter: true })
                : `<button class="btn primary deploy-run" data-act="run" ${state.busy || !envReady() ? "disabled" : ""}>
                    ${state.busy ? "正在部署…" : envReady() ? "一键部署" : "请先安装运行环境"}
                  </button>`}
              ${state.error && !state.job ? `<div class="deploy-error">${esc(state.error)}</div>` : ""}
              <p class="deploy-tip">部署完成后可以继续安装 QQ 登录环境与插件套装，也可以先进入控制台。</p>
            </aside>
          </div>
          ${enhancePanel()}
          <footer class="deploy-foot">牧鱼 v1.30.8 · 部署过程只在本机执行，API Key 仅写入本地实例配置</footer>
        </div>`;
    }

    function syncForm() {
      const name = document.querySelector("#deploy-name");
      if (!name) return;
      state.form.name = name.value;
      const base = document.querySelector("#deploy-base");
      const model = document.querySelector("#deploy-model");
      const key = document.querySelector("#deploy-key");
      const skip = document.querySelector("#deploy-skip");
      const qq = document.querySelector("#deploy-qq");
      if (base) state.form.api_base = base.value;
      if (model) state.form.model = model.value;
      if (key) state.form.api_key = key.value;
      if (skip) state.form.skip_probe = skip.checked;
      if (qq) state.form.qq = qq.value;
    }

    function payload() {
      return {
        name: state.form.name.trim(),
        vendor: state.vendorId,
        api_key: state.form.api_key.trim(),
        api_base: state.form.api_base.trim(),
        model: state.form.model.trim(),
        skip_probe: state.form.skip_probe,
      };
    }

    let view = null;
    let pollJobId = "";

    async function poll(viewEl) {
      if (!pollJobId) return;
      try {
        const job = await api(`/api/deploy/jobs/${pollJobId}`);
        state.job = job;
        state.busy = job.state !== "done" && job.state !== "failed";
        paint(viewEl);
        if (job.state === "done" || job.state === "failed") {
          pollJobId = "";
          if (job.state === "done") toast("机器人已部署完成，可以继续安装增强能力");
          else state.error = job.error || job.message || "部署失败";
          return;
        }
      } catch (exc) {
        pollJobId = "";
        state.busy = false;
        state.error = exc.message || "无法获取部署进度";
        paint(viewEl);
        return;
      }
      state.timer = setTimeout(() => poll(viewEl), 1500);
    }

    function pollInstall(viewEl, jobId) {
      const tick = async () => {
        try {
          const job = await api(`/api/deploy/install/jobs/${jobId}`);
          state.install.job = job;
          paint(viewEl);
          if (job.state === "done" || job.state === "failed") {
            if (state.install.kind === "env" && job.state === "done") {
              try { state.status = await api("/api/deploy/status"); } catch (_) { /* 状态刷新失败不影响安装结果 */ }
              paint(viewEl);
            }
            if (job.state === "done") toast(job.message || "安装完成");
            return;
          }
        } catch (exc) {
          state.error = exc.message || "无法获取安装进度";
          paint(viewEl);
          return;
        }
        state.timer = setTimeout(tick, 1500);
      };
      state.timer = setTimeout(tick, 1200);
    }

    async function saveEnv(viewEl) {
      const source = document.querySelector("#deploy-source")?.value || "";
      const python = document.querySelector("#deploy-python")?.value || "";
      try {
        state.status = await api("/api/deploy/env", {
          method: "POST",
          body: { astrbot_source: source, python_exe: python },
        });
        state.error = "";
        toast("环境路径已保存");
        paint(viewEl);
      } catch (exc) {
        state.error = exc.message;
        paint(viewEl);
      }
    }

    async function installEnv(viewEl) {
      if (state.install && !state.install.job?.state?.match(/done|failed/)) return;
      state.error = "";
      paint(viewEl);
      try {
        const job = await api("/api/deploy/install/env", { method: "POST", body: {} });
        state.install = { kind: "env", job };
        paint(viewEl);
        pollInstall(viewEl, job.id);
      } catch (exc) {
        state.error = exc.message;
        toast(exc.message || "安装启动失败");
        paint(viewEl);
      }
    }

    async function detectModels(viewEl, silent = false) {
      if (state.modelBusy) return;
      syncForm();
      state.modelBusy = true;
      if (!silent) {
        state.modelNote = "正在读取模型列表…";
        state.modelSource = "";
      }
      paint(viewEl);
      try {
        const result = await api("/api/deploy/models", {
          method: "POST",
          body: {
            vendor: state.vendorId,
            api_key: state.form.api_key.trim(),
            api_base: state.form.api_base.trim(),
          },
        });
        state.models = Array.isArray(result.models) ? result.models : [];
        state.modelSource = result.source || "";
        state.modelNote = result.message || "";
      } catch (exc) {
        state.models = [];
        state.modelSource = "";
        state.modelNote = silent ? "" : (exc.message || "模型检测失败");
      }
      state.modelBusy = false;
      paint(viewEl);
    }

    async function testConnection(viewEl) {
      if (state.testBusy) return;
      syncForm();
      if (!state.form.model.trim()) {
        state.testResult = { ok: false, error: "请先填写模型名称" };
        paint(viewEl);
        return;
      }
      state.testBusy = true;
      state.testResult = null;
      paint(viewEl);
      try {
        state.testResult = await api("/api/deploy/test", { method: "POST", body: payload() });
      } catch (exc) {
        state.testResult = { ok: false, error: exc.message || "连接失败" };
      }
      state.testBusy = false;
      paint(viewEl);
    }

    async function installNapcat(viewEl) {
      syncForm();
      if (!state.job?.instance_id) return;
      try {
        const job = await api("/api/deploy/install/napcat", {
          method: "POST",
          body: { instance_id: state.job.instance_id, qq: state.form.qq.trim(), start: true },
        });
        state.install = { kind: "napcat", job };
        paint(viewEl);
        pollInstall(viewEl, job.id);
      } catch (exc) {
        toast(exc.message || "NapCat 安装启动失败");
      }
    }

    async function installPlugins(viewEl) {
      if (!state.job?.instance_id) return;
      const chosen = state.suiteChecked || [];
      if (!chosen.length) {
        toast("请至少选择一个插件");
        return;
      }
      try {
        const job = await api("/api/deploy/install/plugins", {
          method: "POST",
          body: { instance_id: state.job.instance_id, plugins: chosen },
        });
        state.install = { kind: "plugins", job };
        paint(viewEl);
        pollInstall(viewEl, job.id);
      } catch (exc) {
        toast(exc.message || "插件安装启动失败");
      }
    }

    async function runDeploy(viewEl) {
      if (state.busy) return;
      syncForm();
      if (!envReady()) {
        state.error = "请先安装运行环境";
        paint(viewEl);
        return;
      }
      state.error = "";
      state.busy = true;
      state.job = null;
      state.install = null;
      paint(viewEl);
      try {
        const result = await api("/api/deploy/quick", { method: "POST", body: payload() });
        state.job = result.job;
        pollJobId = result.job.id;
        state.busy = true;
        paint(viewEl);
        state.timer = setTimeout(() => poll(viewEl), 1200);
      } catch (exc) {
        state.busy = false;
        state.error = exc.message || "部署失败";
        paint(viewEl);
      }
    }

    function bind(viewEl) {
      viewEl.onclick = (event) => {
        const vendor = event.target.closest("[data-vendor]");
        if (vendor) {
          syncForm();
          pickVendor(vendor.dataset.vendor);
          paint(viewEl);
          return;
        }
        const action = event.target.closest("[data-act]")?.dataset.act;
        if (action === "run") { runDeploy(viewEl); }
        else if (action === "save-env") { saveEnv(viewEl); }
        else if (action === "install-env") { installEnv(viewEl); }
        else if (action === "detect") { detectModels(viewEl); }
        else if (action === "test") { testConnection(viewEl); }
        else if (action === "install-napcat") { installNapcat(viewEl); }
        else if (action === "install-plugins") { installPlugins(viewEl); }
        else if (action === "enter") { onReady && onReady(); }
      };
      viewEl.onchange = (event) => {
        const target = event.target;
        if (target.id === "deploy-skip") state.form.skip_probe = target.checked;
        if (target.dataset && target.dataset.suite) {
          const id = target.dataset.suite;
          const list = state.suiteChecked || [];
          state.suiteChecked = target.checked
            ? Array.from(new Set([...list, id]))
            : list.filter((item) => item !== id);
        }
      };
      viewEl.onfocusout = (event) => {
        if (event.target.id !== "deploy-key") return;
        const key = event.target.value.trim();
        if (!key || !currentVendor()?.key_required) return;
        if (key === state.autoKey) return;
        state.autoKey = key;
        detectModels(viewEl, true);
      };
    }

    async function render(target) {
      view = target;
      if (!state.status) {
        target.innerHTML = `
          <div class="deploy-shell deploy-loading">
            <span class="deploy-spinner"></span>
            <p>正在检测本机的机器人…</p>
          </div>`;
        try {
          state.status = await api("/api/deploy/status");
        } catch (exc) {
          target.innerHTML = `<div class="deploy-shell"><div class="deploy-error">${esc(exc.message)}</div></div>`;
          return;
        }
        if (!state.vendorId) {
          pickVendor(state.status.vendors?.[0]?.id || "deepseek");
          state.form.name = "我的机器人";
        }
      }
      bind(target);
      paint(target);
    }

    function dispose() {
      stopTimer();
    }

    return { render, dispose };
  }

  window.ManagerDeploy = { create };
})();
