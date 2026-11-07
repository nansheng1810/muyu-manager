/* 牧鱼 · DSH 页（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerDsh = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const PAGE_LIMIT = 12;
  const PLUGIN_CATEGORY_LABELS = {
    "fun-dressup": "趣味换装",
    "web-tools": "联网工具",
    memory: "记忆",
    "agent-workflow": "工作流",
    "model-inference": "模型推理",
    client: "客户端",
    "admin-security": "安全管理",
  };

  const TABS = [
    { id: "plugins", label: "DSH 插件" },
    { id: "skills", label: "DSH 技能" },
    { id: "access", label: "机器人接入" },
  ];

  function safeUrl(value) {
    const text = String(value || "").trim();
    return /^https?:\/\//i.test(text) ? text : "";
  }

  function formatCount(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return String(Math.round(n));
  }

  function truncate(text, length = 150) {
    const value = String(text || "").replace(/\s+/g, " ").trim();
    return value.length > length ? `${value.slice(0, length - 1)}…` : value;
  }

  function hueFor(value) {
    let hash = 0;
    const text = String(value || "");
    for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
    return hash % 360;
  }

  function monogramStyle(value) {
    const hue = hueFor(value);
    return `background:hsl(${hue} 28% 20%);color:hsl(${hue} 52% 78%);border-color:hsl(${hue} 24% 34%)`;
  }

  function monogramText(value) {
    const text = String(value || "?").replace(/^@/, "").trim();
    return text.slice(0, 2).toUpperCase();
  }

  function normalizePlugin(item) {
    const row = item && typeof item === "object" ? item : {};
    return {
      owner: String(row.owner || ""),
      name: String(row.name || ""),
      fullName: String(row.fullName || `${row.owner || ""}/${row.name || ""}`),
      description: String(row.description || ""),
      stars: Number(row.stars) || 0,
      categoryKey: String(row.categoryKey || ""),
      categoryLabel: PLUGIN_CATEGORY_LABELS[row.categoryKey] || String(row.categoryKey || "插件"),
      installability: String(row.installability || ""),
      repositoryUrl: safeUrl(row.repositoryUrl),
      installed: Boolean(row.installed),
    };
  }

  function normalizeSkill(item) {
    const row = item && typeof item === "object" ? item : {};
    return {
      slug: String(row.slug || row.id || ""),
      name: String(row.name || row.slug || ""),
      description: String(row.description || ""),
      category: String(row.categoryLabel || row.category || "技能"),
      version: String(row.version || ""),
      downloads: Number(row.downloads) || 0,
      stars: Number(row.stars) || 0,
      rating: Number(row.rating) || 0,
      installed: Boolean(row.installed),
      pageUrl: safeUrl(row.pageUrl),
    };
  }

  function filterInstalledPlugins(items, query) {
    const q = String(query || "").trim().toLowerCase();
    const rows = (Array.isArray(items) ? items : []).map((item) => ({
      pkg: String(item.pkg || item.name || ""),
      name: String(item.name || item.pkg || ""),
      version: String(item.version || ""),
      description: String(item.description || ""),
      source: String(item.source || ""),
      spec: String(item.spec || ""),
      dsh: Boolean(item.dsh),
    }));
    if (!q) return rows;
    return rows.filter((row) =>
      `${row.pkg} ${row.name} ${row.description}`.toLowerCase().includes(q)
    );
  }

  function connectorSummary(config) {
    const cfg = config && typeof config === "object" ? config : {};
    return {
      host: String(cfg.dsh_host || "127.0.0.1"),
      port: Number(cfg.dsh_port) || 3080,
      sessionMode: String(cfg.session_mode || "new"),
      prompt: Boolean(cfg.inject_prompt_enabled),
      timeout: Number(cfg.request_timeout_seconds) || 900,
    };
  }

  function create(ctx) {
    const { api, esc, icon, toast, openModal, closeModal, confirmDialog } = ctx;
    const state = {
      view: null,
      tab: "plugins",
      token: 0,
      timer: null,
      status: null,
      statusError: "",
      plugin: {
        q: "",
        scope: "market",
        category: "",
        page: 1,
        data: null,
        installed: null,
        loading: false,
        error: "",
      },
      skill: {
        q: "",
        scope: "market",
        offset: 0,
        data: null,
        installed: null,
        loading: false,
        error: "",
      },
      categories: [],
      job: null,
      connectors: null,
      connectorsLoading: false,
      connectorsError: "",
    };

    function clearTimer() {
      if (state.timer) {
        clearInterval(state.timer);
        state.timer = null;
      }
    }

    function leave() {
      state.token += 1;
      clearTimer();
      state.view = null;
      state.status = null;
      state.job = null;
    }

    function tabLabel(tab) {
      const found = TABS.find((item) => item.id === tab);
      return found ? found.label : "DSH";
    }

    function runtimeHtml(status) {
      if (!status) {
        const message = state.statusError || "正在读取 DSH 状态…";
        return `<section class="dsh-runtime card dsh-runtime-failed">
          <div class="dsh-runtime-id"><div class="dsh-runtime-mark">D</div><div><div class="dsh-runtime-title"><h2>DeepSeek Harness</h2><span class="dsh-state warn"><i></i>状态读取失败</span></div><p>${esc(message)}</p></div></div>
          <div class="dsh-runtime-actions"><button class="btn sm ghost" data-dsh-action="refresh">${icon("refresh")}重试</button></div>
        </section>`;
      }
      const running = Boolean(status.running);
      const ready = Boolean(status.ready);
      const stateText = !status.installed
        ? "未检测到 DSH"
        : ready
          ? "运行中"
          : running
            ? "端口已占用"
            : "未运行";
      const stateClass = ready ? "ok" : running ? "warn" : "";
      const details = [];
      if (status.version) details.push(`v${esc(status.version)}`);
      details.push(`127.0.0.1:${esc(status.port)}`);
      if (status.plugins_count !== null && status.plugins_count !== undefined) {
        details.push(`${esc(status.plugins_count)} 个插件`);
      }
      if (status.skills_count !== null && status.skills_count !== undefined) {
        details.push(`${esc(status.skills_count)} 个技能`);
      }
      const managed = status.managed ? "管理器托管" : running ? "外部进程" : "固定回环端口";
      return `<section class="dsh-runtime card">
        <div class="dsh-runtime-id">
          <div class="dsh-runtime-mark">D</div>
          <div>
            <div class="dsh-runtime-title">
              <h2>DeepSeek Harness</h2>
              <span class="dsh-state ${stateClass}"><i></i>${stateText}</span>
              <span class="badge">${managed}</span>
            </div>
            <p>${details.join(" · ")}</p>
            ${status.overlay_active ? `<p class="dsh-runtime-note">兼容启动层已启用：运行时禁用故障插件 local-memory，不改 DSH 配置。</p>` : ""}
            ${status.error ? `<p class="dsh-runtime-error">${esc(status.error)}</p>` : ""}
          </div>
        </div>
        <div class="dsh-runtime-actions">
          <button class="btn sm ghost" data-dsh-action="refresh" title="刷新状态">${icon("refresh")}刷新</button>
          ${
            !running && status.installed
              ? `<button class="btn sm primary" data-dsh-action="start">启动 DSH</button>`
              : ""
          }
          ${
            running && status.managed
              ? `<button class="btn sm ghost" data-dsh-action="restart">${icon("restart")}重启</button>
                 <button class="btn sm ghost" data-dsh-action="stop">${icon("stop")}停止</button>`
              : ""
          }
          ${
            running
              ? `<a class="btn sm ghost" href="${esc(status.url)}" target="_blank" rel="noopener">${icon("external")}打开 Web</a>`
              : ""
          }
          <button class="btn sm ghost" data-dsh-action="logs">${icon("terminal")}日志</button>
        </div>
      </section>`;
    }

    function notReadyHtml(status) {
      if (!status) {
        return `<div class="empty dsh-empty">${icon("alert")}<h4>无法读取 DSH</h4><p>${esc(state.statusError || "管理器后端没有返回状态。")}</p></div>`;
      }
      if (!status.installed) {
        return `<div class="empty dsh-empty">${icon("alert")}<h4>没有检测到 DSH</h4><p>${esc(status.error || "请先安装 @deepseek-ai/dsh。")}</p></div>`;
      }
      if (!status.running) {
        return `<div class="empty dsh-empty">${icon("play")}<h4>DSH 还没启动</h4><p>启动后，插件市场与技能市场会直接通过 DSH 的 SkillHub 接口工作。</p><button class="btn primary" data-dsh-action="start">启动 DSH</button></div>`;
      }
      return `<div class="empty dsh-empty">${icon("alert")}<h4>DSH 未就绪</h4><p>3080 已有监听，但 SkillHub 没有响应。请查看日志，或停止外部进程后由管理器启动。</p><button class="btn ghost" data-dsh-action="logs">查看日志</button></div>`;
    }

    function host(view) {
      return view.querySelector("#dsh-runtime");
    }

    function body(view) {
      return view.querySelector("#dsh-body");
    }

    async function refreshStatus() {
      try {
        const status = await api("/api/dsh/status?log_lines=12");
        state.status = status;
        state.statusError = "";
        return status;
      } catch (err) {
        state.status = null;
        state.statusError = err.message;
        return null;
      }
    }

    function wireRuntime(view, tab, token) {
      const scope = host(view);
      if (!scope) return;
      scope.querySelectorAll("[data-dsh-action]").forEach((node) => {
        node.addEventListener("click", async () => {
          const action = node.dataset.dshAction;
          if (action === "refresh") {
            await draw(view, tab, token);
            return;
          }
          if (action === "logs") {
            showLogs();
            return;
          }
          if (action === "start") {
            await runRuntimeAction("start", "启动 DSH", node);
            return;
          }
          if (action === "restart") {
            const ok = await confirmDialog(
              "重启 DSH",
              "重启会中断正在执行的 DSH 会话。确定继续？",
              false
            );
            if (ok) await runRuntimeAction("restart", "重启 DSH", node);
            return;
          }
          if (action === "stop") {
            const ok = await confirmDialog(
              "停止 DSH",
              "停止后，QQ 里的 /dsh 命令和 DSH 插件/技能暂时不可用。确定继续？",
              true
            );
            if (ok) await runRuntimeAction("stop", "停止 DSH", node);
          }
        });
      });
    }

    async function runRuntimeAction(action, label, button) {
      if (button) {
        button.disabled = true;
        button.textContent = `${label}中…`;
      }
      try {
        await api(`/api/dsh/runtime/${action}`, { method: "POST" });
        toast(`${label}已完成`);
      } catch (err) {
        toast(err.message, "err");
      }
      state.status = null;
      if (state.view) await draw(state.view, state.tab, ++state.token);
    }

    function paintRuntime(view, tab, token) {
      const target = host(view);
      if (!target) return;
      target.innerHTML = runtimeHtml(state.status);
      wireRuntime(view, tab, token);
    }

    function showLogs() {
      openModal({
        title: "DSH Web 日志",
        sub: state.status?.log_path || "data/logs/dsh-web.log",
        wide: true,
        body: `<div class="dsh-logbox"><div class="skeleton" style="height:160px"></div></div>`,
        footer: `<button class="btn ghost" data-close>关闭</button>`,
        onMount(root) {
          const box = root.querySelector(".dsh-logbox");
          api("/api/dsh/logs?lines=180")
            .then((data) => {
              const lines = Array.isArray(data?.lines) ? data.lines : [];
              box.innerHTML = lines.length
                ? `<pre>${esc(lines.join("\n"))}</pre>`
                : `<div class="empty" style="padding:24px">${icon("logs")}<h4>暂无日志</h4></div>`;
            })
            .catch((err) => {
              box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
            });
        },
      });
    }

    function toolbarHtml(kind) {
      if (kind === "plugins") {
        const p = state.plugin;
        const categories = state.categories
          .map(
            (item) =>
              `<option value="${esc(item.key)}" ${p.category === item.key ? "selected" : ""}>${esc(item.displayName || item.key)}</option>`
          )
          .join("");
        return `<div class="dsh-toolbar card">
          <div class="dsh-search">${icon("search")}<input id="dsh-plugin-q" value="${esc(p.q)}" placeholder="搜索 DSH 插件，如 browser / memory" autocomplete="off" /></div>
          <select id="dsh-plugin-category" class="dsh-select"><option value="">全部分类</option>${categories}</select>
          <div class="seg dsh-seg">
            <button class="seg-btn ${p.scope === "market" ? "active" : ""}" data-plugin-scope="market">市场</button>
            <button class="seg-btn ${p.scope === "installed" ? "active" : ""}" data-plugin-scope="installed">已安装</button>
          </div>
          <button class="btn sm ghost" id="dsh-plugin-refresh">${icon("refresh")}刷新</button>
        </div>`;
      }
      const s = state.skill;
      return `<div class="dsh-toolbar card">
        <div class="dsh-search">${icon("search")}<input id="dsh-skill-q" value="${esc(s.q)}" placeholder="搜索 DSH 技能，如 PDF / 周报 / 浏览器" autocomplete="off" /></div>
        <div class="seg dsh-seg">
          <button class="seg-btn ${s.scope === "market" ? "active" : ""}" data-skill-scope="market">市场</button>
          <button class="seg-btn ${s.scope === "installed" ? "active" : ""}" data-skill-scope="installed">已安装</button>
        </div>
        <button class="btn sm ghost" id="dsh-skill-refresh">${icon("refresh")}刷新</button>
      </div>`;
    }

    function pluginCard(item) {
      const repo = item.repositoryUrl
        ? `<a class="dsh-link" href="${esc(item.repositoryUrl)}" target="_blank" rel="noopener">仓库</a>`
        : "";
      return `<article class="dsh-card">
        <div class="dsh-card-head">
          <div class="dsh-monogram" style="${monogramStyle(item.fullName)}">${esc(monogramText(item.name || item.owner))}</div>
          <div class="dsh-card-title">
            <h3>${esc(item.name || item.fullName || "未命名插件")}</h3>
            <p>${esc(item.fullName)}</p>
          </div>
          ${item.installed ? `<span class="badge ok">已安装</span>` : `<span class="badge">${esc(item.installability === "verified" ? "已验证" : "插件")}</span>`}
        </div>
        <p class="dsh-desc">${esc(truncate(item.description, 210) || "暂无简介")}</p>
        <div class="dsh-card-meta">
          <span>${esc(item.categoryLabel)}</span>
          <span class="dsh-star">★ ${formatCount(item.stars)}</span>
        </div>
        <div class="dsh-card-actions">
          ${repo}
          ${
            item.installed
              ? `<button class="btn sm ghost" disabled>已安装</button>`
              : `<button class="btn sm primary" data-plugin-install="${esc(item.owner)}" data-plugin-name="${esc(item.name)}">安装</button>`
          }
        </div>
      </article>`;
    }

    function installedPluginCard(item) {
      return `<article class="dsh-card dsh-card-installed">
        <div class="dsh-card-head">
          <div class="dsh-monogram" style="${monogramStyle(item.pkg)}">${esc(monogramText(item.name || item.pkg))}</div>
          <div class="dsh-card-title"><h3>${esc(item.name || item.pkg)}</h3><p>${esc(item.pkg)}</p></div>
          <span class="badge ok">本地</span>
        </div>
        <p class="dsh-desc">${esc(truncate(item.description, 210) || "本地已安装插件")}</p>
        <div class="dsh-card-meta"><span>${esc(item.source || "本地")}</span><span>${esc(item.version || "—")}</span></div>
        <div class="dsh-card-actions">
          <span class="dsh-spec" title="${esc(item.spec)}">${esc(truncate(item.spec, 42))}</span>
          <button class="btn sm danger" data-plugin-uninstall="${esc(item.pkg)}">卸载</button>
        </div>
      </article>`;
    }

    function skillCard(item) {
      const page = item.pageUrl
        ? `<a class="dsh-link" href="${esc(item.pageUrl)}" target="_blank" rel="noopener">来源</a>`
        : "";
      const rating = item.rating ? ` · ★ ${item.rating.toFixed(1)}` : "";
      return `<article class="dsh-card">
        <div class="dsh-card-head">
          <div class="dsh-monogram" style="${monogramStyle(item.slug)}">${esc(monogramText(item.name))}</div>
          <div class="dsh-card-title"><h3>${esc(item.name || item.slug)}</h3><p>${esc(item.slug)}</p></div>
          ${item.installed ? `<span class="badge ok">已安装</span>` : `<span class="badge">${esc(item.category)}</span>`}
        </div>
        <p class="dsh-desc">${esc(truncate(item.description, 230) || "暂无简介")}</p>
        <div class="dsh-card-meta">
          <span>${esc(item.version ? `v${item.version}` : item.category)}</span>
          <span>${formatCount(item.downloads)} 次下载${rating}</span>
        </div>
        <div class="dsh-card-actions">
          ${page}
          ${
            item.installed
              ? `<button class="btn sm danger" data-skill-uninstall="${esc(item.slug)}">卸载</button>`
              : `<button class="btn sm primary" data-skill-install="${esc(item.slug)}">安装</button>`
          }
        </div>
      </article>`;
    }

    function installedSkillCard(item) {
      return `<article class="dsh-card dsh-card-installed">
        <div class="dsh-card-head">
          <div class="dsh-monogram" style="${monogramStyle(item.slug)}">${esc(monogramText(item.name || item.slug))}</div>
          <div class="dsh-card-title"><h3>${esc(item.name || item.slug)}</h3><p>${esc(item.slug)}</p></div>
          <span class="badge ok">本地</span>
        </div>
        <p class="dsh-desc">${esc(truncate(item.description, 210) || "已安装到 DSH 技能目录")}</p>
        <div class="dsh-card-actions">
          <span class="dsh-spec">${esc(item.version ? `v${item.version}` : item.updated || "—")}</span>
          <button class="btn sm danger" data-skill-uninstall="${esc(item.slug || item.name)}">卸载</button>
        </div>
      </article>`;
    }

    function pluginListHtml() {
      const p = state.plugin;
      if (p.loading) return `<div class="dsh-grid">${Array.from({ length: 6 }).map(() => `<div class="skeleton" style="height:190px;border-radius:14px"></div>`).join("")}</div>`;
      if (p.error) return `<div class="empty dsh-empty">${icon("alert")}<h4>读取失败</h4><p>${esc(p.error)}</p></div>`;
      if (p.scope === "installed") {
        const rows = filterInstalledPlugins(p.installed?.items || [], p.q).filter((item) => item.dsh);
        if (!rows.length) return `<div class="empty dsh-empty">${icon("market")}<h4>还没有安装 DSH 插件</h4><p>切换到市场搜索插件，安装后在这里管理。</p></div>`;
        return `<div class="dsh-grid">${rows.map(installedPluginCard).join("")}</div>`;
      }
      const items = (p.data?.items || []).map(normalizePlugin);
      if (!items.length) return `<div class="empty dsh-empty">${icon("search")}<h4>没有找到插件</h4><p>换个关键词，或清空搜索看看热门插件。</p></div>`;
      const total = Number(p.data?.total) || items.length;
      const pages = Math.max(1, Math.ceil(total / PAGE_LIMIT));
      return `<div class="dsh-result-head"><span>共 ${total} 款插件</span><span>第 ${p.page} / ${pages} 页</span></div>
        <div class="dsh-grid">${items.map(pluginCard).join("")}</div>
        <div class="dsh-pager">
          <button class="btn sm ghost" data-plugin-page="${p.page - 1}" ${p.page <= 1 ? "disabled" : ""}>上一页</button>
          <button class="btn sm ghost" data-plugin-page="${p.page + 1}" ${p.page >= pages ? "disabled" : ""}>下一页</button>
        </div>`;
    }

    function skillListHtml() {
      const s = state.skill;
      if (s.loading) return `<div class="dsh-grid">${Array.from({ length: 6 }).map(() => `<div class="skeleton" style="height:190px;border-radius:14px"></div>`).join("")}</div>`;
      if (s.error) return `<div class="empty dsh-empty">${icon("alert")}<h4>读取失败</h4><p>${esc(s.error)}</p></div>`;
      if (s.scope === "installed") {
        const items = (s.installed?.items || []).map(normalizeSkill);
        if (!items.length) return `<div class="empty dsh-empty">${icon("model")}<h4>还没有安装 DSH 技能</h4><p>技能安装到 ~/.dsh/skills，新会话即可被发现。</p></div>`;
        return `<div class="dsh-result-head"><span>已安装 ${items.length} 个技能</span><span>${esc(s.installed?.skillsDir || "")}</span></div><div class="dsh-grid">${items.map(installedSkillCard).join("")}</div>`;
      }
      const items = (s.data?.items || []).map(normalizeSkill);
      if (!items.length) return `<div class="empty dsh-empty">${icon("search")}<h4>没有找到技能</h4><p>换个关键词再试。</p></div>`;
      const total = Number(s.data?.total) || items.length;
      const page = Math.floor(s.offset / PAGE_LIMIT) + 1;
      const pages = Math.max(1, Math.ceil(total / PAGE_LIMIT));
      return `<div class="dsh-result-head"><span>共 ${total} 个技能</span><span>第 ${page} / ${pages} 页</span></div>
        <div class="dsh-grid">${items.map(skillCard).join("")}</div>
        <div class="dsh-pager">
          <button class="btn sm ghost" data-skill-page="${Math.max(0, s.offset - PAGE_LIMIT)}" ${s.offset <= 0 ? "disabled" : ""}>上一页</button>
          <button class="btn sm ghost" data-skill-page="${s.offset + PAGE_LIMIT}" ${s.offset + PAGE_LIMIT >= total || !s.data?.hasMore ? "disabled" : ""}>下一页</button>
        </div>`;
    }

    async function loadPluginCategories() {
      if (state.categories.length) return;
      try {
        const data = await api("/api/dsh/skillhub/plugin-categories");
        state.categories = Array.isArray(data?.items) ? data.items : [];
      } catch (_) {
        state.categories = [];
      }
    }

    async function loadPlugins() {
      const p = state.plugin;
      p.loading = true;
      p.error = "";
      try {
        if (p.scope === "installed") {
          p.installed = await api("/api/dsh/skillhub/plugins/installed");
        } else {
          const qs = new URLSearchParams({
            q: p.q,
            page: String(p.page),
            limit: String(PAGE_LIMIT),
          });
          if (p.category) qs.set("category", p.category);
          p.data = await api(`/api/dsh/skillhub/plugins?${qs}`);
        }
      } catch (err) {
        p.error = err.message;
      } finally {
        p.loading = false;
      }
    }

    async function loadSkills() {
      const s = state.skill;
      s.loading = true;
      s.error = "";
      try {
        if (s.scope === "installed") {
          s.installed = await api("/api/dsh/skillhub/skills/installed");
        } else {
          const qs = new URLSearchParams({
            q: s.q,
            limit: String(PAGE_LIMIT),
            offset: String(s.offset),
          });
          s.data = await api(`/api/dsh/skillhub/skills?${qs}`);
        }
      } catch (err) {
        s.error = err.message;
      } finally {
        s.loading = false;
      }
    }

    async function loadConnectors() {
      state.connectorsLoading = true;
      state.connectorsError = "";
      try {
        state.connectors = await api("/api/dsh/connectors");
      } catch (err) {
        state.connectorsError = err.message;
      } finally {
        state.connectorsLoading = false;
      }
    }

    function jobBannerHtml() {
      const job = state.job;
      if (!job) return "";
      if (job.active) {
        const p = job.progress || {};
        const percent = p.total ? Math.min(100, Math.round((Number(p.done || 0) / Number(p.total)) * 100)) : null;
        return `<div class="dsh-job"><div><b>正在安装 ${esc(job.target)}</b><span>${esc(p.lastLine || job.message || "下载并写入 profile…")}</span></div>
          <div class="dsh-progress"><i style="width:${percent === null ? "35%" : `${percent}%`}"></i></div></div>`;
      }
      if (job.error) {
        return `<div class="dsh-job bad"><div><b>${esc(job.target)} 安装失败</b><span>${esc(job.error)}</span></div></div>`;
      }
      if (job.finished_at) {
        return `<div class="dsh-job ok"><div><b>${esc(job.target)} 已安装</b><span>重启 DSH 后生效。</span></div><button class="btn sm ghost" data-dsh-action="restart">${icon("restart")}重启 DSH</button></div>`;
      }
      return "";
    }

    function renderPlugins(ready) {
      if (!ready) return `<div class="card dsh-bodycard">${notReadyHtml(state.status)}</div>`;
      return `${jobBannerHtml()}
        ${toolbarHtml("plugins")}
        <div id="dsh-plugin-list" class="dsh-list">${pluginListHtml()}</div>`;
    }

    function renderSkills(ready) {
      if (!ready) return `<div class="card dsh-bodycard">${notReadyHtml(state.status)}</div>`;
      return `${toolbarHtml("skills")}<div class="dsh-tip">技能安装到 <code>${esc(state.status?.home ? `${state.status.home}\\skills` : "~/.dsh/skills")}</code>，新对话即可发现，无需重启 DSH。</div><div id="dsh-skill-list" class="dsh-list">${skillListHtml()}</div>`;
    }

    function accessInstanceHtml(entry, dshMeta) {
      const plugin = entry.plugin;
      const compatible = Boolean(plugin && plugin.compatible);
      const offline = !entry.running;
      const statusBadge = offline
        ? `<span class="badge">机器人离线</span>`
        : compatible
          ? `<span class="badge ok">已接入</span>`
          : plugin
            ? `<span class="badge bad">协议不兼容</span>`
            : `<span class="badge">未安装</span>`;
      const config = connectorSummary(entry.config);
      const tools = entry.tools || {};
      const toolsOk = ["dsh_ask", "dsh_ping"].every((name) => tools[name] === "admin");
      const toolText = Object.keys(tools).length
        ? ["dsh_ask", "dsh_ping"]
            .map((name) => `${name}=${tools[name] || "未设置"}`)
            .join(" · ")
        : "尚未读取到工具权限";
      let actions = "";
      if (!offline && !plugin) {
        actions = `<button class="btn sm primary" data-dsh-connector-install="${esc(entry.id)}">安装兼容桥</button>`;
      } else if (!offline && plugin && compatible) {
        actions = `<button class="btn sm ghost" data-dsh-connector-config="${esc(entry.id)}">配置</button>
          <button class="btn sm ghost" data-dsh-connector-test="${esc(entry.id)}">测试连接</button>
          <button class="btn sm ghost" data-dsh-connector-reload="${esc(entry.id)}">重载</button>`;
      }
      return `<article class="dsh-instance">
        <div class="dsh-instance-head">
          <div class="dsh-monogram dsh-instance-mark" style="${monogramStyle(entry.name || entry.id)}">${esc(monogramText(entry.name || entry.id))}</div>
          <div class="dsh-card-title"><h3>${esc(entry.name || entry.id)}</h3><p>${esc(entry.id)} · ${offline ? "AstrBot 未运行" : "AstrBot 在线"}</p></div>
          ${statusBadge}
        </div>
        ${
          plugin
            ? `<div class="dsh-kv">
                <div><span>桥插件</span><b>${esc(plugin.id)} ${esc(plugin.version ? `v${plugin.version}` : "")}</b></div>
                <div><span>DSH 地址</span><b>${esc(config.host)}:${esc(config.port)}</b></div>
                <div><span>会话模式</span><b>${esc(config.sessionMode === "persistent" ? "复用会话" : "新会话")}</b></div>
                <div><span>工具权限</span><b class="${toolsOk ? "dsh-good" : "dsh-warn-text"}">${esc(toolText)}</b></div>
              </div>
              ${plugin.compatible ? "" : `<p class="dsh-warn">这个插件使用 DSH 0.2+ 协议，对当前 0.1.1 会返回 404；请停用/卸载后安装兼容桥。</p>`}`
            : `<p class="dsh-instance-copy">${offline ? "启动机器人后可安装。" : `未检测到 DSH 桥。安装后，QQ 管理员可用 /dsh ping 与 /dsh ask；LLM 工具默认收口为仅主人。`}</p>`
        }
        ${entry.error ? `<p class="dsh-warn">${esc(entry.error)}</p>` : ""}
        ${actions ? `<div class="dsh-instance-actions">${actions}</div>` : ""}
      </article>`;
    }

    function renderAccess() {
      if (state.connectorsLoading) return `<div class="card dsh-bodycard"><div class="skeleton" style="height:160px"></div></div>`;
      if (state.connectorsError) return `<div class="empty dsh-empty">${icon("alert")}<h4>读取失败</h4><p>${esc(state.connectorsError)}</p></div>`;
      const data = state.connectors;
      if (!data) return "";
      const ready = data.dsh?.ready;
      return `<div class="dsh-access-note card">
        <div>${icon("terminal")}<div><b>DSH ${esc(data.dsh?.version || "")} · 0.1.1 点号 RPC</b><p>当前用兼容桥 <code>${esc(data.bridge_market_id)}</code>（v${esc(data.bridge_version)}）。DSH 0.2+ 连接器 2.1.1 与本机协议不匹配，不要安装。</p></div></div>
        <span class="dsh-state ${ready ? "ok" : "warn"}"><i></i>${ready ? "DSH 就绪" : "DSH 未就绪"}</span>
      </div>
      <div class="dsh-instances">${(data.instances || []).map((entry) => accessInstanceHtml(entry, data.dsh || {})).join("")}</div>
      <div class="card dsh-command-help">
        <div class="section-head" style="margin:0 0 12px"><h2>接入后怎么用</h2></div>
        <div class="dsh-command-grid">
          <div><code>/dsh ping</code><span>只读检查 DSH 连接</span></div>
          <div><code>/dsh ask 帮我查一下磁盘空间</code><span>管理员把任务交给 DSH 执行</span></div>
          <div><code>dsh_ask</code><span>主智能体的工具，已收口为仅主人</span></div>
          <div><code>/dsh scan</code><span>重新发现 DSH 端口</span></div>
        </div>
        <p class="dsh-help-copy">QQ 中安装第三方 DSH 插件/技能后无需改 AstrBot；DSH 会按自己的 skill 发现机制读取。</p>
      </div>`;
    }

    async function draw(view, tab, token) {
      state.view = view;
      state.tab = tab;
      const status = await refreshStatus();
      if (token !== state.token) return;
      view.innerHTML = `<div class="dsh-page" id="dsh-page">
        <div id="dsh-runtime">${runtimeHtml(status)}</div>
        <div id="dsh-body"></div>
      </div>`;
      wireRuntime(view, tab, token);
      if (tab === "access") {
        if (!state.connectors) await loadConnectors();
        if (token !== state.token) return;
        body(view).innerHTML = renderAccess();
        wireAccess(view, token);
        return;
      }
      if (!status?.ready) {
        body(view).innerHTML = `<div class="card dsh-bodycard">${notReadyHtml(status)}</div>`;
        wireBodyActions(view, token);
        return;
      }
      if (tab === "plugins") {
        if (!state.plugin.data && !state.plugin.installed) {
          await loadPluginCategories();
          await loadPlugins();
        }
        if (token !== state.token) return;
        body(view).innerHTML = renderPlugins(true);
        wirePlugins(view, token);
      } else {
        if (!state.skill.data && !state.skill.installed) await loadSkills();
        if (token !== state.token) return;
        body(view).innerHTML = renderSkills(true);
        wireSkills(view, token);
      }
    }

    function wireBodyActions(view, token) {
      const scope = body(view);
      if (!scope) return;
      scope.querySelectorAll("[data-dsh-action]").forEach((node) => {
        node.addEventListener("click", async () => {
          const action = node.dataset.dshAction;
          if (action === "start") {
            await runRuntimeAction("start", "启动 DSH", node);
          } else if (action === "logs") {
            showLogs();
          }
        });
      });
    }

    async function refreshPlugins(view, token) {
      state.plugin.loading = true;
      const list = view.querySelector("#dsh-plugin-list");
      if (list) list.innerHTML = pluginListHtml();
      await loadPlugins();
      await refreshStatus();
      if (token !== state.token || state.tab !== "plugins") return;
      if (list) list.innerHTML = pluginListHtml();
      paintRuntime(view, "plugins", token);
      wirePluginList(view, token);
    }

    async function refreshSkills(view, token) {
      state.skill.loading = true;
      const list = view.querySelector("#dsh-skill-list");
      if (list) list.innerHTML = skillListHtml();
      await loadSkills();
      await refreshStatus();
      if (token !== state.token || state.tab !== "skills") return;
      if (list) list.innerHTML = skillListHtml();
      paintRuntime(view, "skills", token);
      wireSkillList(view, token);
    }

    function wirePluginToolbar(view, token) {
      const q = view.querySelector("#dsh-plugin-q");
      const cat = view.querySelector("#dsh-plugin-category");
      const btn = view.querySelector("#dsh-plugin-refresh");
      if (q) {
        q.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            state.plugin.q = q.value.trim();
            state.plugin.page = 1;
            refreshPlugins(view, token);
          }
        });
      }
      if (cat) {
        cat.addEventListener("change", () => {
          state.plugin.category = cat.value;
          state.plugin.page = 1;
          refreshPlugins(view, token);
        });
      }
      if (btn) btn.addEventListener("click", () => {
        state.plugin.q = q?.value.trim() || "";
        refreshPlugins(view, token);
      });
      view.querySelectorAll("[data-plugin-scope]").forEach((node) => {
        node.addEventListener("click", async () => {
          state.plugin.scope = node.dataset.pluginScope;
          state.plugin.q = q?.value.trim() || "";
          state.plugin.page = 1;
          state.plugin.data = null;
          state.plugin.installed = null;
          await render(view, "plugins");
        });
      });
    }

    function wirePluginList(view, token) {
      view.querySelectorAll("[data-plugin-page]").forEach((node) => {
        node.addEventListener("click", () => {
          state.plugin.page = Number(node.dataset.pluginPage) || 1;
          refreshPlugins(view, token);
        });
      });
      view.querySelectorAll("[data-plugin-install]").forEach((node) => {
        node.addEventListener("click", async () => {
          const owner = node.dataset.pluginInstall;
          const name = node.dataset.pluginName;
          const ok = await confirmDialog(
            "安装 DSH 插件",
            `将从 SkillHub 安装 ${owner}/${name} 到 web profile。插件会执行第三方代码，安装完成后需要重启 DSH。确定继续？`,
            false
          );
          if (!ok) return;
          node.disabled = true;
          node.textContent = "安装中…";
          try {
            await api("/api/dsh/skillhub/plugins/install", {
              method: "POST",
              body: { owner, name },
            });
            toast("安装任务已开始");
            await pollInstall(view, token);
          } catch (err) {
            toast(err.message, "err");
            node.disabled = false;
            node.textContent = "安装";
          }
        });
      });
      view.querySelectorAll("[data-plugin-uninstall]").forEach((node) => {
        node.addEventListener("click", async () => {
          const pkg = node.dataset.pluginUninstall;
          const ok = await confirmDialog(
            "卸载 DSH 插件",
            `将卸载 ${pkg}，重启 DSH 后生效。确定继续？`,
            true
          );
          if (!ok) return;
          node.disabled = true;
          try {
            await api("/api/dsh/skillhub/plugins/uninstall", {
              method: "POST",
              body: { pkg },
            });
            toast("插件已卸载，重启 DSH 后生效");
            await refreshPlugins(view, token);
          } catch (err) {
            toast(err.message, "err");
            node.disabled = false;
          }
        });
      });
    }

    async function pollInstall(view, token) {
      if (state.timer) clearInterval(state.timer);
      const tick = async () => {
        if (token !== state.token || state.tab !== "plugins") {
          clearTimer();
          return;
        }
        try {
          state.job = await api("/api/dsh/skillhub/plugins/install-status");
          const container = body(view);
          const existing = container?.querySelector(".dsh-job");
          if (existing) existing.outerHTML = jobBannerHtml();
          else if (container) container.insertAdjacentHTML("afterbegin", jobBannerHtml());
          if (!state.job.active) {
            clearTimer();
            const ok = !state.job.error;
            toast(ok ? "插件安装完成，重启 DSH 后生效" : `安装失败：${state.job.error}`, ok ? "ok" : "err");
            await refreshStatus();
            if (ok) await refreshPlugins(view, token);
            wireJobActions(view, token);
          }
        } catch (err) {
          clearTimer();
          toast(err.message, "err");
        }
      };
      await tick();
      if (state.job?.active && token === state.token) {
        state.timer = setInterval(tick, 1000);
      }
    }

    function wireJobActions(view, token) {
      view.querySelectorAll(".dsh-job [data-dsh-action='restart']").forEach((node) => {
        node.addEventListener("click", async () => {
          const ok = await confirmDialog("重启 DSH", "重启会中断正在执行的 DSH 会话。确定继续？", false);
          if (ok) await runRuntimeAction("restart", "重启 DSH", node);
        });
      });
    }

    function wirePlugins(view, token) {
      wirePluginToolbar(view, token);
      wirePluginList(view, token);
      wireJobActions(view, token);
    }

    function wireSkillList(view, token) {
      view.querySelectorAll("[data-skill-page]").forEach((node) => {
        node.addEventListener("click", () => {
          state.skill.offset = Number(node.dataset.skillPage) || 0;
          refreshSkills(view, token);
        });
      });
      view.querySelectorAll("[data-skill-install]").forEach((node) => {
        node.addEventListener("click", async () => {
          const slug = node.dataset.skillInstall;
          node.disabled = true;
          node.textContent = "安装中…";
          try {
            await api("/api/dsh/skillhub/skills/install", {
              method: "POST",
              body: { slug },
            });
            toast("技能已安装，新对话即可发现");
            await refreshSkills(view, token);
          } catch (err) {
            toast(err.message, "err");
            node.disabled = false;
            node.textContent = "安装";
          }
        });
      });
      view.querySelectorAll("[data-skill-uninstall]").forEach((node) => {
        node.addEventListener("click", async () => {
          const slug = node.dataset.skillUninstall;
          const ok = await confirmDialog("卸载 DSH 技能", `将删除技能目录 ${slug}。确定继续？`, true);
          if (!ok) return;
          node.disabled = true;
          try {
            await api("/api/dsh/skillhub/skills/uninstall", {
              method: "POST",
              body: { slug },
            });
            toast("技能已卸载");
            await refreshSkills(view, token);
          } catch (err) {
            toast(err.message, "err");
            node.disabled = false;
          }
        });
      });
    }

    function wireSkills(view, token) {
      const q = view.querySelector("#dsh-skill-q");
      const btn = view.querySelector("#dsh-skill-refresh");
      if (q) q.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          state.skill.q = q.value.trim();
          state.skill.offset = 0;
          refreshSkills(view, token);
        }
      });
      if (btn) btn.addEventListener("click", () => {
        state.skill.q = q?.value.trim() || "";
        state.skill.offset = 0;
        refreshSkills(view, token);
      });
      view.querySelectorAll("[data-skill-scope]").forEach((node) => {
        node.addEventListener("click", async () => {
          state.skill.scope = node.dataset.skillScope;
          state.skill.q = q?.value.trim() || "";
          state.skill.offset = 0;
          state.skill.data = null;
          state.skill.installed = null;
          await render(view, "skills");
        });
      });
      wireSkillList(view, token);
    }

    async function refreshConnectors(view, token) {
      state.connectorsLoading = true;
      body(view).innerHTML = renderAccess();
      await loadConnectors();
      await refreshStatus();
      if (token !== state.token || state.tab !== "access") return;
      const runtime = host(view);
      if (runtime) {
        runtime.innerHTML = runtimeHtml(state.status);
        wireRuntime(view, "access", token);
      }
      body(view).innerHTML = renderAccess();
      wireAccess(view, token);
    }

    function openConfigModal(entry) {
      const cfg = connectorSummary(entry.config);
      const actual = entry.config && typeof entry.config === "object" ? entry.config : {};
      openModal({
        title: `配置 ${entry.name || entry.id}`,
        sub: "配置写入 AstrBot Dashboard；dsh_ask / dsh_ping 会自动收口为仅主人。",
        body: `<div class="dsh-form">
          <div class="dsh-form-row">
            <label>DSH 主机<input id="dsh-cfg-host" value="${esc(actual.dsh_host || cfg.host)}" /></label>
            <label>端口<input id="dsh-cfg-port" type="number" min="1" max="65535" value="${esc(actual.dsh_port || cfg.port)}" /></label>
          </div>
          <div class="dsh-form-row">
            <label>会话模式<select id="dsh-cfg-mode"><option value="new" ${cfg.sessionMode !== "persistent" ? "selected" : ""}>每次新建会话</option><option value="persistent" ${cfg.sessionMode === "persistent" ? "selected" : ""}>复用会话</option></select></label>
            <label>单任务超时（秒）<input id="dsh-cfg-timeout" type="number" min="30" max="3600" value="${esc(actual.request_timeout_seconds || cfg.timeout)}" /></label>
          </div>
          <label class="dsh-check"><input id="dsh-cfg-prompt" type="checkbox" ${cfg.prompt ? "checked" : ""} /> 向主智能体注入 DSH 工具使用说明</label>
          <p class="dsh-help-copy">工具权限由管理器在保存时统一设为 admin，避免群聊成员驱动电脑上的 DSH。</p>
        </div>`,
        footer: `<button class="btn ghost" data-close>取消</button><button class="btn primary" id="dsh-cfg-save">保存配置</button>`,
        onMount(root) {
          const save = root.querySelector("#dsh-cfg-save");
          save.addEventListener("click", async () => {
            const payload = {
              dsh_host: root.querySelector("#dsh-cfg-host").value.trim(),
              dsh_port: Number(root.querySelector("#dsh-cfg-port").value) || 3080,
              session_mode: root.querySelector("#dsh-cfg-mode").value,
              request_timeout_seconds: Number(root.querySelector("#dsh-cfg-timeout").value) || 900,
              inject_prompt_enabled: root.querySelector("#dsh-cfg-prompt").checked,
            };
            save.disabled = true;
            try {
              await api(`/api/dsh/connectors/${entry.id}/config`, { method: "PUT", body: payload });
              toast("连接器配置已保存");
              closeModal();
              if (state.view) await refreshConnectors(state.view, state.token);
            } catch (err) {
              toast(err.message, "err");
              save.disabled = false;
            }
          });
        },
      });
    }

    function wireAccess(view, token) {
      view.querySelectorAll("[data-dsh-connector-install]").forEach((node) => {
        node.addEventListener("click", async () => {
          const id = node.dataset.dshConnectorInstall;
          const ok = await confirmDialog(
            "安装 DSH 兼容桥",
            "将安装 Fantasality/astrbot_plugin_dsh_bridge 1.0.0。它会执行第三方插件代码；安装后 dsh_ask / dsh_ping 会收口为仅主人。确定继续？",
            false
          );
          if (!ok) return;
          node.disabled = true;
          node.textContent = "安装中…";
          try {
            await api("/api/dsh/connectors/install", { method: "POST", body: { instance_id: id } });
            toast("兼容桥已安装并配置");
            await refreshConnectors(view, token);
          } catch (err) {
            toast(err.message, "err");
            node.disabled = false;
            node.textContent = "安装兼容桥";
          }
        });
      });
      view.querySelectorAll("[data-dsh-connector-config]").forEach((node) => {
        node.addEventListener("click", () => {
          const id = node.dataset.dshConnectorConfig;
          const entry = (state.connectors?.instances || []).find((item) => String(item.id) === id);
          if (entry) openConfigModal(entry);
        });
      });
      view.querySelectorAll("[data-dsh-connector-test]").forEach((node) => {
        node.addEventListener("click", async () => {
          const id = node.dataset.dshConnectorTest;
          node.disabled = true;
          node.textContent = "测试中…";
          try {
            const result = await api(`/api/dsh/connectors/${id}/test`, { method: "POST" });
            toast(`DSH 连接正常 · ${result.sessions} 个会话 · v${result.version}`);
          } catch (err) {
            toast(err.message, "err");
          } finally {
            node.disabled = false;
            node.textContent = "测试连接";
          }
        });
      });
      view.querySelectorAll("[data-dsh-connector-reload]").forEach((node) => {
        node.addEventListener("click", async () => {
          const id = node.dataset.dshConnectorReload;
          node.disabled = true;
          node.textContent = "重载中…";
          try {
            await api(`/api/dsh/connectors/${id}/reload`, { method: "POST" });
            toast("连接器已重载");
            await refreshConnectors(view, token);
          } catch (err) {
            toast(err.message, "err");
          } finally {
            node.disabled = false;
            node.textContent = "重载";
          }
        });
      });
    }

    async function render(view, tab) {
      state.token += 1;
      const token = state.token;
      clearTimer();
      state.view = view;
      state.tab = tab;
      state.status = null;
      view.innerHTML = `<div class="dsh-page">
        <div id="dsh-runtime"><section class="dsh-runtime card"><div class="skeleton" style="height:72px"></div></section></div>
        <div id="dsh-body"><div class="skeleton" style="height:190px;border-radius:14px"></div></div>
      </div>`;
      await draw(view, tab, token);
    }

    return {
      render,
      leave,
      runtimeHtml,
      tabLabel,
    };
  }

  return {
    TABS,
    create,
    safeUrl,
    formatCount,
    truncate,
    normalizePlugin,
    normalizeSkill,
    filterInstalledPlugins,
    connectorSummary,
  };
});
