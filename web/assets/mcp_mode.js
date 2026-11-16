/* 牧鱼 · MCP 模式：Agent 直连 QQ 的控制面 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerMcpMode = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog } = ctx;
    const confirm = typeof confirmDialog === "function" ? confirmDialog : async () => true;
    let viewEl = null;
    let data = null;
    let busy = false;
    let timer = null;
    let selectedGroup = "";
    let selectedPersona = "";
    let selectedChoice = "";
    let participation = "natural";
    let logs = "";
    let groups = [];
    let personas = [];
    let sourceProcesses = [];
    let revealed = "";

    const badge = (ok, text) => `<span class="badge ${ok ? "ok" : "warn"}">${esc(text)}</span>`;
    const dot = (ok) => `<span class="mcp-dot ${ok ? "ok" : "warn"}"></span>`;
    const value = (v) => esc(v || "—");
    const has = (obj, key) => Boolean(obj && obj[key]);

    function statusCards() {
      const tulpa = (data && data.tulpa) || {};
      const source = (data && data.source) || {};
      const agents = (data && data.agents) || {};
      const connection = (data && data.connection) || {};
      const sourceUp = Boolean(source.running && source.onebot && source.onebot.ready);
      const managedUp = Boolean(data && data.managed && data.managed.qq_ready);
      const backendUp = (data && data.backend === "source") ? sourceUp : managedUp;
      const codex = Boolean(agents.codex && agents.codex.installed);
      const dsh = Boolean(agents.dsh && agents.dsh.installed && agents.dsh.config_installed);
      const backendError = data && data.backend === "source"
        ? (source.onebot && source.onebot.error)
        : (data && data.managed && data.managed.error);
      const cards = [
        ["Tulpa", Boolean(tulpa.mcp && tulpa.mcp.running), tulpa.version ? `v${tulpa.version}` : "未连接", tulpa.error],
        ["QQ 后端", backendUp, data ? (data.backend === "source" ? "SnowLuma 源码" : "SnowLuma 托管") : "读取中", backendError],
        ["聊天连接", Boolean(connection.id), connection.id ? (connection.conversation_id || connection.id) : "未创建", ""],
        ["Codex", codex, codex ? "配置已写入" : "未写入", agents.codex && agents.codex.error],
        ["DSH", dsh, dsh ? "配置已写入" : (agents.dsh && agents.dsh.installed ? "待写入" : "未安装"), agents.dsh && agents.dsh.error],
      ];
      return cards.map(([label, ok, text, err]) => `
        <div class="mcp-stat ${ok ? "ok" : "warn"}" title="${esc(err || "")}">
          ${dot(ok)}<div><span>${esc(label)}</span><b>${esc(text)}</b></div>
        </div>`).join("");
    }

    function backendTabs() {
      const backend = (data && data.backend) || "managed";
      return `
        <div class="mcp-tabs">
          <button class="chip ${backend === "managed" ? "on" : ""}" data-act="backend" data-kind="managed">托管 2.1.1</button>
          <button class="chip ${backend === "source" ? "on" : ""}" data-act="backend" data-kind="source">源码 2.4.2</button>
          <span class="mcp-hint">同一个 QQ 进程不能同时给 NapCat 和 SnowLuma</span>
        </div>`;
    }

    function managedPanel() {
      const m = (data && data.managed) || {};
      const choices = Array.isArray(m.choices) ? m.choices : [];
      const choiceHtml = choices.length ? choices.map((item) => `
        <label class="mcp-choice ${item.blocked ? "blocked" : ""}">
          <input type="radio" name="mcp-choice" value="${esc(item.id)}" ${selectedChoice === item.id ? "checked" : ""} ${item.blocked ? "disabled" : ""}>
          <span>
            <b>${esc(item.account || item.account_label || item.pid || "待验证")}</b>
            <small>${esc(item.path || "")}</small>
            ${item.blocked ? `<em>${esc(item.reason || "NapCat 占用")}</em>` : ""}
          </span>
        </label>`).join("") : `<p class="mcp-muted">还没有可绑定的 QQ 进程。先登录一个独立的 QQ 客户端，再刷新。</p>`;
      return `
        <section class="card mcp-panel">
          <div class="mcp-panel-head"><h3>${icon("dsh")}托管 SnowLuma</h3>${badge(Boolean(m.qq_ready), m.phase_label || m.phase || "未知")}</div>
          <p class="mcp-muted">${esc(m.message || "Tulpa 会自动准备已验证的 SnowLuma 2.1.1；NapCat 进程会被禁止绑定。")}</p>
          <div class="mcp-kv"><span>版本</span><b>${value(m.version)}</b><span>账号</span><b>${value(m.account)}</b><span>端口</span><b>${esc(JSON.stringify(m.ports || {}))}</b></div>
          <div class="mcp-actions">
            <button class="btn sm primary" data-act="managed-configure" ${m.has_consent ? "" : "disabled"}>${icon("check")}配置托管</button>
            <button class="btn sm" data-act="managed-select" ${choices.some((x) => x.id === selectedChoice && !x.blocked) ? "" : "disabled"}>${icon("play")}绑定所选 QQ</button>
            <button class="btn sm ghost" data-act="managed-test" ${m.qq_ready ? "" : "disabled"}>${icon("pulse")}OneBot 自检</button>
            <button class="btn sm danger" data-act="managed-cancel">${icon("stop")}取消托管</button>
          </div>
          ${m.has_consent ? "" : `<p class="mcp-warn">需要在 Tulpa 中同意当前 SnowLuma 协议后才能配置。</p>`}
          <div class="mcp-choices">${choiceHtml}</div>
        </section>`;
    }

    function sourcePanel() {
      const s = (data && data.source) || {};
      const one = s.onebot || {};
      const build = s.build || {};
      const buildActive = Boolean(build.active);
      return `
        <section class="card mcp-panel">
          <div class="mcp-panel-head"><h3>${icon("terminal")}源码 SnowLuma 2.4.2</h3>${badge(Boolean(s.built), s.built ? "已构建" : "未构建")}</div>
          <p class="mcp-muted">在复制下来的源码目录构建并运行；OneBot HTTP + WS 只绑本机。首次登录和选择 QQ 进程在 SnowLuma 控制台完成。</p>
          <p class="mcp-warn">SnowLuma 是源码可见非商业许可；只在本地构建使用，不随牧鱼安装包分发。</p>
          <div class="mcp-kv">
            <span>目录</span><b class="mcp-path">${value(s.root)}</b>
            <span>运行</span><b>${s.running ? "运行中" : "已停止"}${s.pid ? ` · PID ${s.pid}` : ""}</b>
            <span>OneBot</span><b>${one.ready ? `已登录 ${value(one.account)}` : "等待 QQ 登录"}</b>
          </div>
          <div class="mcp-actions">
            <button class="btn sm primary" data-act="source-build" ${buildActive ? "disabled" : ""}>${icon("download")}${buildActive ? "构建中…" : "构建源码"}</button>
            <button class="btn sm" data-act="source-start" ${s.built && !s.running ? "" : "disabled"}>${icon("play")}启动</button>
            <button class="btn sm danger" data-act="source-stop" ${s.running ? "" : "disabled"}>${icon("stop")}停止</button>
            <button class="btn sm ghost" data-act="source-reveal" ${s.running ? "" : "disabled"}>${icon("external")}控制台</button>
            <button class="btn sm ghost" data-act="source-detect" ${s.running ? "" : "disabled"}>${icon("refresh")}检测 OneBot</button>
            <button class="btn sm ghost" data-act="source-processes" ${s.running ? "" : "disabled"}>${icon("bots")}读取 QQ 进程</button>
            <button class="btn sm" data-act="source-connect" ${one.ready ? "" : "disabled"}>${icon("check")}接入 Tulpa</button>
          </div>
          ${sourceProcessList()}
          ${buildActive ? `<div class="mcp-progress"><span style="width:45%"></span></div><p class="mcp-muted">${esc(build.phase || "构建中")} · 日志在下面</p>` : ""}
          ${build.error ? `<p class="mcp-error">${esc(build.error)}</p>` : ""}
          ${revealed ? `<p class="mcp-secret">控制台：${esc(revealed.url)} · 密码：<code>${esc(revealed.password)}</code></p>` : ""}
          ${one.error ? `<p class="mcp-warn">${esc(one.error)}</p>` : ""}
        </section>`;
    }

    function sourceProcessList() {
      if (!sourceProcesses.length) return "";
      return `<div class="mcp-choices">${sourceProcesses.map((item) => `
        <div class="mcp-choice ${item.blocked ? "blocked" : ""}">
          <span>
            <b>${esc(item.account || item.uin || item.pid)} ${esc(item.nickname || "")}</b>
            <small>${esc(item.path || "")} · ${esc(item.status || "")}${item.logged_in ? " · 已登录" : ""}</small>
            ${item.blocked ? `<em>${esc(item.reason || "NapCat 占用")}</em>` : ""}
          </span>
          <button class="btn sm" data-act="source-select" data-pid="${esc(item.pid)}" ${item.blocked ? "disabled" : ""}>绑定</button>
        </div>`).join("")}</div>`;
    }

    function groupOptions() {
      if (!groups.length) return `<option value="">先加载群列表</option>`;
      return groups.map((item) => `<option value="${esc(item.conversation_id)}" ${item.conversation_id === selectedGroup ? "selected" : ""}>${esc(item.name)} · ${esc(item.conversation_id)}</option>`).join("");
    }

    function personaOptions() {
      if (!personas.length) return `<option value="">先加载人格</option>`;
      return personas.map((item) => `<option value="${esc(item.id)}" ${item.id === selectedPersona ? "selected" : ""}>${esc(item.name)}${item.summary ? ` · ${esc(item.summary)}` : ""}</option>`).join("");
    }

    function connectionPanel() {
      const c = (data && data.connection) || {};
      return `
        <section class="card mcp-panel">
          <div class="mcp-panel-head"><h3>${icon("fish")}聊天连接</h3>${badge(Boolean(c.id), c.id ? "已创建" : "未创建")}</div>
          <p class="mcp-muted">连接只开放所选群/好友的文字聊天，图片和表情可按需开启；群管理默认关闭。</p>
          <div class="mcp-form">
            <label>目标群<select id="mcp-group">${groupOptions()}</select></label>
            <label>人格<select id="mcp-persona">${personaOptions()}</select></label>
            <label>参与度<select id="mcp-participation">${["quiet", "natural", "active"].map((v) => `<option value="${v}" ${v === participation ? "selected" : ""}>${v}</option>`).join("")}</select></label>
          </div>
          <div class="mcp-flags">
            <label><input type="checkbox" id="mcp-flag-images" checked>图片/表情</label>
            <label><input type="checkbox" id="mcp-flag-sticker" checked>发送表情</label>
            <label><input type="checkbox" id="mcp-flag-collect">收藏表情</label>
            <label><input type="checkbox" id="mcp-flag-reactions" checked>表情回应</label>
            <label><input type="checkbox" id="mcp-flag-manage">群管理（危险）</label>
          </div>
          <div class="mcp-actions">
            <button class="btn sm ghost" data-act="load-groups">${icon("refresh")}加载群</button>
            <button class="btn sm ghost" data-act="load-personas">${icon("model")}加载人格</button>
            <button class="btn sm primary" data-act="connection-create">${icon("plus")}${c.id ? "新建连接" : "创建连接"}</button>
            <button class="btn sm" data-act="connection-test" ${c.id ? "" : "disabled"}>${icon("pulse")}测试 MCP</button>
            <button class="btn sm danger" data-act="connection-revoke" ${c.id ? "" : "disabled"}>${icon("trash")}撤销</button>
          </div>
          <div class="mcp-kv">
            <span>连接</span><b>${value(c.id)}</b>
            <span>会话</span><b>${value(c.conversation_id)}</b>
            <span>人格</span><b>${value(c.persona_preset)}</b>
            <span>Token</span><b>${c.token_saved ? "已保存（不显示）" : "—"}</b>
          </div>
          <div class="mcp-actions">
            <button class="btn sm primary" data-act="chat-start" ${c.id ? "" : "disabled"}>${icon("play")}开始聊天会话</button>
            <button class="btn sm" data-act="chat-refresh" ${c.id ? "" : "disabled"}>${icon("refresh")}刷新会话</button>
          </div>
          ${sessionsHtml()}
        </section>`;
    }

    function sessionsHtml() {
      const sessions = (data && data.sessions) || [];
      const receiver = (data && data.receiver) || {};
      if (!data || !sessions.length) {
        return `<p class="mcp-muted">还没有活跃聊天会话。创建连接后点“开始聊天会话”，再在 Codex/DSH 中运行启动指令。</p>`;
      }
      return `
        <div class="mcp-sessions">
          <div class="mcp-session-head"><span>活跃会话 ${sessions.length}</span><span>接收：${esc(receiver.state || "未知")}</span></div>
          ${sessions.map((item) => `
            <div class="mcp-session">
              <div><b>${esc(item.name || item.conversation_id)}</b><small>${esc(item.persona_name || "")} · ${esc(item.participation || "")}</small></div>
              <button class="btn sm danger" data-act="chat-stop" data-sid="${esc(item.id)}">停止</button>
            </div>`).join("")}
        </div>`;
    }

    function agentsPanel() {
      const agents = (data && data.agents) || {};
      const codex = agents.codex || {};
      const dsh = agents.dsh || {};
      const install = dsh.install || {};
      return `
        <section class="card mcp-panel">
          <div class="mcp-panel-head"><h3>${icon("terminal")}Agent 接入</h3>${badge(Boolean(codex.installed || dsh.config_installed), "Codex / DSH")}</div>
          <div class="mcp-agent">
            <div class="mcp-agent-head"><b>Codex</b>${badge(Boolean(codex.installed), codex.installed ? "已写入" : "未写入")}</div>
            <p class="mcp-muted">${esc(codex.path || "~/.codex/config.toml")}</p>
            <div class="mcp-actions">
              <button class="btn sm primary" data-act="agent-install" data-agent="codex" ${data.connection?.id ? "" : "disabled"}>${icon("download")}写入 Codex 配置</button>
              <button class="btn sm" data-act="agent-test" data-agent="codex" ${codex.installed ? "" : "disabled"}>${icon("pulse")}测试 MCP</button>
            </div>
          </div>
          <div class="mcp-agent">
            <div class="mcp-agent-head"><b>DSH</b>${badge(Boolean(dsh.installed && dsh.config_installed), dsh.installed ? (dsh.config_installed ? "已写入" : "待写入") : "未安装")}</div>
            <p class="mcp-muted">${esc(dsh.bin_js || dsh.error || "未找到 DSH")}</p>
            <div class="mcp-actions">
              <button class="btn sm ghost" data-act="dsh-install-runtime">${icon("download")}安装/修复 DSH</button>
              <button class="btn sm primary" data-act="agent-install" data-agent="dsh" ${dsh.installed && data.connection?.id ? "" : "disabled"}>${icon("download")}写入 DSH 配置</button>
              <button class="btn sm" data-act="agent-test" data-agent="dsh" ${dsh.config_installed ? "" : "disabled"}>${icon("pulse")}测试 MCP</button>
              <button class="btn sm ghost" data-act="dsh-restart" ${dsh.installed ? "" : "disabled"}>${icon("restart")}重启 DSH</button>
            </div>
            ${dsh.install && dsh.install.active ? `<div class="mcp-progress"><span style="width:55%"></span></div><p class="mcp-muted">${esc(install.phase || "安装中")}</p>` : ""}
            ${install.error ? `<p class="mcp-error">${esc(install.error)}</p>` : ""}
          </div>
          <div class="mcp-prompt">
            <div class="mcp-panel-head"><h3>Agent 启动指令</h3><button class="btn sm ghost" data-act="copy-prompt">${icon("external")}复制</button></div>
            <textarea id="mcp-prompt" readonly>${esc((data && data.prompt) || "")}</textarea>
          </div>
          <p class="mcp-warn">Codex/DSH 必须保持运行；Tulpa 不会在 Agent 退出后替你继续推理。DSH 的 MCP 配置在 web profile，重启后生效。</p>
        </section>`;
    }

    function rawPanel() {
      const raw = (data && data.raw) || {};
      return `
        <section class="card mcp-panel">
          <div class="mcp-panel-head"><h3>${icon("pulse")}全量 OneBot 动作</h3>${badge(Boolean(raw.server_built), raw.server_built ? "可挂载" : "未构建")}</div>
          <p class="mcp-muted">SnowLuma MCP 暴露 query_action / invoke_action，补齐 NapCat 同语义动作。聊天仍走 Tulpa；这里默认只读。</p>
          <div class="mcp-flags">
            <label><input type="checkbox" id="mcp-raw-enabled" ${raw.enabled ? "checked" : ""}>启用全量动作 MCP</label>
            <label><input type="checkbox" id="mcp-raw-write" ${raw.write ? "checked" : ""}>允许写操作（危险）</label>
          </div>
          <div class="mcp-actions">
            <button class="btn sm primary" data-act="raw-save">${icon("check")}保存并刷新 Agent 配置</button>
            <button class="btn sm ghost" data-act="raw-refresh">${icon("refresh")}刷新</button>
          </div>
          ${raw.write ? `<p class="mcp-error">写模式会允许 Agent 直接发送消息、改群资料等；只在明确需要时开启。</p>` : ""}
        </section>`;
    }

    function logsPanel() {
      return `
        <section class="card mcp-panel mcp-logs">
          <div class="mcp-panel-head"><h3>${icon("logs")}运行日志</h3><button class="btn sm ghost" data-act="logs-refresh">${icon("refresh")}刷新</button></div>
          <pre>${esc(logs || "暂无日志")}</pre>
        </section>`;
    }

    function render() {
      if (!viewEl) return;
      if (!data) {
        viewEl.innerHTML = `<div class="skeleton" style="height:360px"></div>`;
        return;
      }
      const backend = data.backend || "managed";
      viewEl.innerHTML = `
        <div class="mcp-head">
          <div class="mcp-stats">${statusCards()}</div>
          <div class="mcp-actions">
            <button class="btn sm ghost" data-act="refresh">${icon("refresh")}刷新</button>
            <button class="btn sm ghost" data-act="tulpa-enable">${icon("play")}启动 Tulpa MCP</button>
          </div>
        </div>
        ${backendTabs()}
        <div class="mcp-grid">
          ${backend === "managed" ? managedPanel() : sourcePanel()}
          ${connectionPanel()}
          ${agentsPanel()}
          ${rawPanel()}
          ${logsPanel()}
        </div>`;
    }

    function readConnectionForm() {
      const group = viewEl && viewEl.querySelector("#mcp-group");
      const persona = viewEl && viewEl.querySelector("#mcp-persona");
      const part = viewEl && viewEl.querySelector("#mcp-participation");
      const flag = (id, fallback) => {
        const node = viewEl && viewEl.querySelector(id);
        return node ? Boolean(node.checked) : fallback;
      };
      selectedGroup = group ? group.value : selectedGroup;
      selectedPersona = persona ? persona.value : selectedPersona;
      participation = part ? part.value : participation;
      return {
        conversation_id: selectedGroup,
        persona_preset: selectedPersona,
        participation,
        flags: {
          chat_images: flag("#mcp-flag-images", true),
          chat_sticker_send: flag("#mcp-flag-sticker", true),
          chat_sticker_collect: flag("#mcp-flag-collect", false),
          chat_reactions: flag("#mcp-flag-reactions", true),
          manage: flag("#mcp-flag-manage", false),
        },
      };
    }

    async function load(force) {
      if (busy && !force) return;
      try {
        data = await api("/api/mcp-mode/status");
        if (!selectedGroup && data.connection?.conversation_id) selectedGroup = data.connection.conversation_id;
        if (!selectedPersona && data.connection?.persona_preset) selectedPersona = data.connection.persona_preset;
        try {
          const chats = await api("/api/mcp-mode/chats");
          data.sessions = chats.sessions || [];
          data.receiver = chats.receiver || {};
        } catch (_) {
          data.sessions = data.sessions || [];
          data.receiver = data.receiver || {};
        }
        try {
          const log = await api("/api/mcp-mode/logs?lines=100");
          logs = log.text || "";
        } catch (_) { logs = ""; }
      } catch (err) {
        toast(err.message || "读取 MCP 状态失败", "err");
      }
      render();
    }

    async function run(action) {
      if (busy) return false;
      busy = true;
      try {
        await action();
        await load(true);
        return true;
      } catch (err) {
        toast(err.message || "操作失败", "err");
        return false;
      } finally {
        busy = false;
      }
    }

    function bind() {
      viewEl.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-act]");
        if (!button) return;
        const act = button.dataset.act;
        if (act === "refresh") return load(true);
        if (act === "backend" && button.dataset.kind) {
          return run(() => api("/api/mcp-mode/backend", { method: "POST", body: { backend: button.dataset.kind } }));
        }
        if (act === "tulpa-enable") {
          return run(() => api("/api/mcp-mode/tulpa/enable", { method: "POST", body: {} }));
        }
        if (act === "managed-configure") {
          if (!(await confirm("配置托管 SnowLuma", "会启动/配置 Tulpa 托管的 SnowLuma 2.1.1，并使用当前已同意的协议。继续？"))) return;
          return run(() => api("/api/mcp-mode/snowluma/managed/configure", { method: "POST", body: {} }));
        }
        if (act === "managed-select") {
          if (!selectedChoice) return toast("先选择一个 QQ 进程", "warn");
          if (!(await confirm("绑定 QQ 进程", "SnowLuma 会接管所选 QQ 进程；该进程不能同时给 NapCat 使用。继续？"))) return;
          return run(() => api("/api/mcp-mode/snowluma/managed/select", { method: "POST", body: { choice_id: selectedChoice } }));
        }
        if (act === "managed-test") {
          return run(() => api("/api/mcp-mode/snowluma/managed/test", { method: "POST", body: {} }));
        }
        if (act === "managed-cancel") {
          if (!(await confirm("取消托管", "会停止 Tulpa 托管的 SnowLuma，但不会删除已安装的运行包。继续？"))) return;
          return run(() => api("/api/mcp-mode/snowluma/managed/cancel", { method: "POST", body: {} }));
        }
        if (act === "source-build") {
          const ok = await run(() => api("/api/mcp-mode/snowluma/source/build", { method: "POST", body: {} }));
          if (ok) setTimeout(() => load(true), 1500);
          return ok;
        }
        if (act === "source-start") {
          return run(() => api("/api/mcp-mode/snowluma/source/start", { method: "POST", body: {} }));
        }
        if (act === "source-stop") {
          if (!(await confirm("停止源码 SnowLuma", "只停止牧鱼启动的这个 SnowLuma 进程。继续？"))) return;
          return run(() => api("/api/mcp-mode/snowluma/source/stop", { method: "POST", body: {} }));
        }
        if (act === "source-reveal") {
          return run(async () => {
            const result = await api("/api/mcp-mode/snowluma/source/reveal", { method: "POST", body: {} });
            revealed = result;
            if (result.url) window.open(result.url, "_blank", "noopener");
            toast("控制台地址已打开；密码显示在页面中", "ok");
          });
        }
        if (act === "source-detect") {
          return run(async () => {
            const result = await api("/api/mcp-mode/groups");
            groups = result.items || [];
            toast(groups.length ? `OneBot 已就绪，读到 ${groups.length} 个群` : "OneBot 还没有可读群", groups.length ? "ok" : "warn");
          });
        }
        if (act === "source-processes") {
          return run(async () => {
            const result = await api("/api/mcp-mode/snowluma/source/processes");
            sourceProcesses = result.items || [];
            toast(sourceProcesses.length ? `读到 ${sourceProcesses.length} 个 QQ 进程` : "没有读到 QQ 进程；先登录 QQ", sourceProcesses.length ? "ok" : "warn");
          });
        }
        if (act === "source-select") {
          const pid = Number(button.dataset.pid || 0);
          if (!(await confirm("绑定 QQ 进程", "SnowLuma 会接管这个 QQ 进程；它不能同时给 NapCat 使用。继续？"))) return;
          return run(async () => {
            const result = await api("/api/mcp-mode/snowluma/source/select", { method: "POST", body: { pid } });
            toast(result.onebot?.ready ? `已绑定 ${result.onebot.account}` : "已发起绑定；请在 QQ 客户端完成登录后刷新", result.onebot?.ready ? "ok" : "warn");
          });
        }
        if (act === "source-connect") {
          if (!(await confirm("接入 Tulpa", "会把 Tulpa 的 OneBot 设置切到源码 SnowLuma；如正在托管，会先停止托管。继续？"))) return;
          return run(() => api("/api/mcp-mode/snowluma/source/connect", { method: "POST", body: { force: true } }));
        }
        if (act === "load-groups") {
          return run(async () => {
            const result = await api("/api/mcp-mode/groups");
            groups = result.items || [];
            if (!selectedGroup && groups.length) selectedGroup = groups[0].conversation_id;
            toast(groups.length ? `读到 ${groups.length} 个群` : "没有读到群", groups.length ? "ok" : "warn");
          });
        }
        if (act === "load-personas") {
          return run(async () => {
            const result = await api("/api/mcp-mode/personas");
            personas = result.items || [];
            if (!selectedPersona && personas.length) selectedPersona = personas[0].id;
            toast(personas.length ? `读到 ${personas.length} 个人格` : "没有读到人格", personas.length ? "ok" : "warn");
          });
        }
        if (act === "connection-create") {
          const body = readConnectionForm();
          if (!body.conversation_id) return toast("先加载并选择目标群", "warn");
          if (!body.persona_preset) return toast("先加载并选择人格", "warn");
          if (!(await confirm("创建聊天连接", "会创建一条新的 Tulpa MCP 连接并写入管理器；旧连接不会自动删除。继续？"))) return;
          return run(() => api("/api/mcp-mode/connection", { method: "POST", body }));
        }
        if (act === "connection-test") {
          return run(async () => { const r = await api("/api/mcp-mode/connection/test", { method: "POST", body: {} }); toast(`MCP 可用，工具 ${r.tools || "?"} 个`, "ok"); });
        }
        if (act === "connection-revoke") {
          if (!(await confirm("撤销连接", "会立即停止该连接的所有聊天并撤销 Token。继续？"))) return;
          return run(() => api("/api/mcp-mode/connection", { method: "DELETE" }));
        }
        if (act === "chat-start") {
          return run(async () => { const r = await api("/api/mcp-mode/chats/start", { method: "POST", body: {} }); toast(r.session_id ? "会话已创建" : "会话已接续", "ok"); });
        }
        if (act === "chat-refresh") {
          return run(async () => { const r = await api("/api/mcp-mode/chats"); data.sessions = r.sessions || []; data.receiver = r.receiver || {}; });
        }
        if (act === "chat-stop") {
          const sid = button.dataset.sid;
          if (!(await confirm("停止聊天会话", "会唤醒等待并取消未派发的回复；已发送消息无法撤回。继续？"))) return;
          return run(() => api(`/api/mcp-mode/chats/${encodeURIComponent(sid)}/stop`, { method: "POST", body: {} }));
        }
        if (act === "agent-install") {
          const agent = button.dataset.agent;
          return run(async () => {
            await api(`/api/mcp-mode/agents/${encodeURIComponent(agent)}/install`, { method: "POST", body: {} });
            toast(agent === "codex" ? "Codex 配置已写入；重启 Codex 会话后生效" : "DSH 配置已写入；重启 DSH 后生效", "ok");
          });
        }
        if (act === "agent-test") {
          return run(async () => { const r = await api(`/api/mcp-mode/agents/${encodeURIComponent(button.dataset.agent)}/test`, { method: "POST", body: {} }); toast(`MCP 测试通过，工具 ${r.mcp?.tools || "?"} 个`, "ok"); });
        }
        if (act === "dsh-install-runtime") {
          return run(async () => { await api("/api/mcp-mode/agents/dsh/install-runtime", { method: "POST", body: {} }); toast("DSH 安装已开始，完成后点击写入配置", "ok"); setTimeout(() => load(true), 3000); });
        }
        if (act === "dsh-restart") {
          if (!(await confirm("重启 DSH", "会重启牧鱼管理的 DSH Web，加载新的 MCP 配置。继续？"))) return;
          return run(() => api("/api/dsh/runtime/restart", { method: "POST", body: {} }));
        }
        if (act === "raw-save") {
          const enabled = Boolean(viewEl.querySelector("#mcp-raw-enabled")?.checked);
          const write = Boolean(viewEl.querySelector("#mcp-raw-write")?.checked);
          if (write && !(await confirm("开启全量写操作", "Agent 将能直接调用 SnowLuma 的写动作。确认继续？"))) return;
          return run(async () => {
            await api("/api/mcp-mode/raw", { method: "POST", body: { enabled, write } });
            if (data.connection?.id) {
              if (data.agents?.dsh?.config_installed) {
                await api("/api/mcp-mode/agents/dsh/install", { method: "POST", body: {} }).catch(() => {});
              }
              if (data.agents?.codex?.installed) {
                await api("/api/mcp-mode/agents/codex/install", { method: "POST", body: {} }).catch(() => {});
              }
            }
            toast("全量动作配置已保存", "ok");
          });
        }
        if (act === "raw-refresh") return load(true);
        if (act === "logs-refresh") {
          return run(async () => { const r = await api("/api/mcp-mode/logs?lines=120"); logs = r.text || ""; });
        }
        if (act === "copy-prompt") {
          const text = (data && data.prompt) || "";
          try { await navigator.clipboard.writeText(text); toast("启动指令已复制"); }
          catch (_) { toast("复制失败，请手动选择文本", "warn"); }
          return;
        }
      });
      viewEl.addEventListener("change", (event) => {
        const target = event.target;
        if (target.name === "mcp-choice") selectedChoice = target.value;
        if (target.id === "mcp-group") selectedGroup = target.value;
        if (target.id === "mcp-persona") selectedPersona = target.value;
        if (target.id === "mcp-participation") participation = target.value;
      });
    }

    function renderView(view) {
      viewEl = view;
      if (!viewEl.dataset.mcpBound) {
        viewEl.dataset.mcpBound = "1";
        bind();
      }
      render();
      load(true);
      if (timer) clearInterval(timer);
      timer = setInterval(() => {
        const focused = document.activeElement && viewEl.contains(document.activeElement);
        if (document.visibilityState === "visible" && !busy && !focused) load();
      }, 8000);
    }

    function leave() {
      if (timer) clearInterval(timer);
      timer = null;
      revealed = "";
      sourceProcesses = [];
    }

    return { render: renderView, leave };
  }

  return { create };
});
