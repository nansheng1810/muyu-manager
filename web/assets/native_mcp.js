/* 牧鱼 · 原生 MCP：管理器直接接管 QQ 并读取自己的插件 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerNativeMcp = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog, state } = ctx;
    const confirm = typeof confirmDialog === "function" ? confirmDialog : async () => true;
    let viewEl = null;
    let data = null;
    let tools = [];
    let prompt = "";
    let timer = null;
    let busy = false;
    let instId = "";
    let groupId = "";
    let groups = [];
    let logs = "";
    let loadingGroups = false;

    const instances = () => (state && Array.isArray(state.instances) ? state.instances : []);
    const badge = (ok, text) => `<span class="badge ${ok ? "ok" : "warn"}">${esc(text)}</span>`;
    const dot = (ok) => `<span class="mcp-dot ${ok ? "ok" : "warn"}"></span>`;
    const value = (v) => esc(v || "—");

    function serviceCard() {
      const all = (data && data.services) || {};
      const services = all.services || {};
      const rows = Object.entries(services).map(([name, svc]) => `
        <div class="nmcp-endpoint">
          <div><b>${esc((svc.label || name).toUpperCase())}</b><small>固定实例 ${esc(instanceName(svc.instance_id))} · ${esc(svc.instance_id)}</small></div>
          <div class="nmcp-endpoint-meta"><code>${esc(svc.url || "")}</code>${badge(Boolean(svc.running), svc.running ? "运行中" : "已停止")}</div>
        </div>`).join("");
      const running = Object.values(services).some((svc) => svc && svc.running);
      return `
        <section class="card nmcp-panel">
          <div class="nmcp-head"><h3>${icon("terminal")}管理器原生 MCP</h3>${badge(running, running ? "运行中" : "已停止")}</div>
          <p class="nmcp-muted">两个固定端点：DSH 只接大肥鱼，Codex 只接龙娘；服务端会拒绝跨实例访问。不启动 Tulpa。</p>
          <div class="nmcp-endpoints">${rows || `<p class="nmcp-muted">正在读取端点…</p>`}</div>
          <div class="nmcp-actions">
            <button class="btn sm primary" data-act="service-start" ${running ? "disabled" : ""}>${icon("play")}启动 MCP</button>
            <button class="btn sm danger" data-act="service-stop" ${running ? "" : "disabled"}>${icon("stop")}停止</button>
            <button class="btn sm ghost" data-act="token-rotate">${icon("refresh")}轮换 Token</button>
            <button class="btn sm ghost" data-act="refresh">${icon("refresh")}刷新</button>
          </div>
          ${(all.error) ? `<p class="nmcp-error">${esc(all.error)}</p>` : ""}
        </section>`;
    }

    function instanceName(id) {
      const found = instances().find((x) => String(x.id) === String(id));
      return found ? found.name || found.id : id;
    }

    function bridgeRows() {
      const bridge = (data && data.bridge) || {};
      const rows = Array.isArray(bridge.instances) ? bridge.instances : [];
      if (!rows.length) return `<p class="nmcp-muted">还没有 AstrBot 实例。</p>`;
      return `<div class="nmcp-bridges">${rows.map((row) => `
        <div class="nmcp-bridge">
          <div>
            <b>${esc(row.name || row.instance_id)}</b>
            <small>${esc(row.instance_id)} · ${row.installed ? "桥插件已安装" : "未安装"}</small>
          </div>
          <div class="nmcp-actions">
            ${badge(Boolean(row.connected), row.connected ? "已连接" : (row.installed ? "等待连接" : "未连接"))}
            <button class="btn sm ${row.installed ? "ghost" : "primary"}" data-act="bridge-install" data-inst="${esc(row.instance_id)}">${icon("download")}${row.installed ? "重装桥" : "安装桥"}</button>
            <button class="btn sm ghost" data-act="bridge-restart" data-inst="${esc(row.instance_id)}" ${row.installed ? "" : "disabled"}>${icon("restart")}重启实例</button>
            <button class="btn sm ghost" data-act="bridge-groups" data-inst="${esc(row.instance_id)}" ${row.connected ? "" : "disabled"}>${icon("refresh")}读群</button>
          </div>
        </div>`).join("")}</div>`;
    }

    function bridgeCard() {
      return `
        <section class="card nmcp-panel">
          <div class="nmcp-head"><h3>${icon("dsh")}AstrBot 桥</h3>${badge((((data && data.bridge) || {}).connected || []).length > 0, "插件桥")}</div>
          <p class="nmcp-muted">桥插件只负责转发群消息、暂停默认 LLM 回复和发送文本。其他插件的事件钩子继续运行，所以记忆、心情、拟人仍能看到消息。</p>
          ${bridgeRows()}
        </section>`;
    }

    function groupOptions() {
      if (!groups.length) return `<option value="">先连接桥并读取群</option>`;
      return groups.map((g) => `<option value="${esc(g.group_id)}" ${String(g.group_id) === String(groupId) ? "selected" : ""}>${esc(g.group_name || g.group_id)} · ${esc(g.group_id)}</option>`).join("");
    }

    function sessionCard() {
      const sessions = (data && data.sessions) || [];
      return `
        <section class="card nmcp-panel">
          <div class="nmcp-head"><h3>${icon("inbox")}接管会话</h3>${badge(Boolean(sessions.length), sessions.length ? `${sessions.length} 个` : "未接管")}</div>
          <div class="nmcp-form">
            <label>实例<select id="nmcp-inst">${instances().map((x) => `<option value="${esc(x.id)}" ${String(x.id) === String(instId) ? "selected" : ""}>${esc(x.name || x.id)}</option>`).join("")}</select></label>
            <label>群<select id="nmcp-group">${groupOptions()}</select></label>
          </div>
          <div class="nmcp-actions">
            <button class="btn sm ghost" data-act="groups" ${instId ? "" : "disabled"}>${icon("refresh")}加载群</button>
            <button class="btn sm primary" data-act="session-start" ${instId && groupId ? "" : "disabled"}>${icon("play")}开始接管</button>
          </div>
          <p class="nmcp-warn">接管期间这个群的默认 AstrBot 回复会暂停，由 Agent 回复；停止后恢复。只填纯文本，图片/表情发送后续再接。</p>
          ${sessions.length ? `<div class="nmcp-sessions">${sessions.map((s) => `
            <div class="nmcp-session">
              <div><b>${esc(s.group_name || s.group_id)}</b><small>${esc(instanceName(s.instance_id))} · 待处理 ${s.pending}</small></div>
              <button class="btn sm danger" data-act="session-stop" data-sid="${esc(s.id)}">停止</button>
            </div>`).join("")}</div>` : ""}
        </section>`;
    }

    function toolsCard() {
      return `
        <section class="card nmcp-panel">
          <div class="nmcp-head"><h3>${icon("market")}插件工具</h3>${badge(true, `${tools.length} 个`)}</div>
          <p class="nmcp-muted">核心数据走管理器自己的插件模块；Agent 在回复前可以主动读取。</p>
          <div class="nmcp-tools">${tools.map((t) => `<div class="nmcp-tool"><b>${esc(t.name)}</b><span>${esc(t.description || "")}</span></div>`).join("")}</div>
        </section>`;
    }

    function agentsCard() {
      const agents = (data && data.agents) || {};
      return `
        <section class="card nmcp-panel">
          <div class="nmcp-head"><h3>${icon("terminal")}Agent 接入</h3>${badge(Boolean((agents.codex && agents.codex.installed) || (agents.dsh && agents.dsh.installed)), "Codex / DSH")}</div>
          <div class="nmcp-agent">
            <div class="nmcp-head"><b>Codex</b>${badge(Boolean(agents.codex && agents.codex.installed), agents.codex && agents.codex.installed ? "已写入" : "未写入")}</div>
            <p class="nmcp-muted">固定接 ${esc(instanceName((agents.codex && agents.codex.instance_id) || "bot-339f"))} · ${esc((agents.codex && agents.codex.instance_id) || "bot-339f")} · ${esc((agents.codex && agents.codex.url) || "http://127.0.0.1:18779/mcp")}</p>
            <button class="btn sm primary" data-act="agent-install" data-agent="codex">${icon("download")}写入 Codex 配置</button>
          </div>
          <div class="nmcp-agent">
            <div class="nmcp-head"><b>DSH</b>${badge(Boolean(agents.dsh && agents.dsh.installed), agents.dsh && agents.dsh.installed ? "已写入" : "未写入")}</div>
            <p class="nmcp-muted">固定接 ${esc(instanceName((agents.dsh && agents.dsh.instance_id) || "f0e1e0b6"))} · ${esc((agents.dsh && agents.dsh.instance_id) || "f0e1e0b6")} · ${esc((agents.dsh && agents.dsh.url) || "http://127.0.0.1:18778/mcp")}</p>
            <div class="nmcp-actions">
              <button class="btn sm primary" data-act="agent-install" data-agent="dsh">${icon("download")}写入 DSH 配置</button>
              <button class="btn sm ghost" data-act="dsh-restart">${icon("restart")}重启 DSH</button>
            </div>
          </div>
          <div class="nmcp-prompt">
            <div class="nmcp-head"><h3>Agent 启动指令</h3><button class="btn sm ghost" data-act="copy-prompt">${icon("external")}复制</button></div>
            <textarea id="nmcp-prompt" readonly>${esc(prompt)}</textarea>
          </div>
        </section>`;
    }

    function logsCard() {
      return `
        <section class="card nmcp-panel nmcp-logs">
          <div class="nmcp-head"><h3>${icon("logs")}说明</h3></div>
          <pre>${esc(logs || "无需额外日志。桥插件连接后，这里会显示接管状态。")}</pre>
        </section>`;
    }

    function render() {
      if (!viewEl) return;
      if (!data) {
        viewEl.innerHTML = `<div class="skeleton" style="height:320px"></div>`;
        return;
      }
      const svc = (data.service || {});
      viewEl.innerHTML = `
        <div class="nmcp-hero">
          <div>
            <h2>原生 MCP</h2>
            <p>管理器自己当 MCP 宿主，直接接 AstrBot / NapCat 和你的插件数据。</p>
          </div>
          <div class="nmcp-hero-actions">
            <button class="btn sm ghost" data-act="refresh">${icon("refresh")}刷新</button>
          </div>
        </div>
        <div class="nmcp-grid">
          ${serviceCard()}
          ${bridgeCard()}
          ${sessionCard()}
          ${toolsCard()}
          ${agentsCard()}
          ${logsCard()}
        </div>`;
      const instSelect = viewEl.querySelector("#nmcp-inst");
      if (instSelect) instSelect.addEventListener("change", () => {
        instId = instSelect.value;
        groupId = "";
        groups = [];
        render();
      });
      const groupSelect = viewEl.querySelector("#nmcp-group");
      if (groupSelect) groupSelect.addEventListener("change", () => { groupId = groupSelect.value; });
    }

    async function load(force) {
      if (busy && !force) return;
      try {
        const [status, sessionData, toolData, promptData] = await Promise.all([
          api("/api/mcp-native/status"),
          api("/api/mcp-native/sessions"),
          api("/api/mcp-native/tools"),
          api("/api/mcp-native/prompt"),
        ]);
        data = { ...status, sessions: sessionData.sessions || [] };
        tools = toolData.tools || [];
        prompt = [
          "【DSH → 大肥鱼】",
          promptData.dsh || "",
          "",
          "【Codex → 龙娘】",
          promptData.codex || "",
        ].join(String.fromCharCode(10));

        const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(instances());
        if (focusHit) {
          instId = String(focusHit.id);
        } else if (!instId && instances().length) {
          const focused = globalThis.ManagerFocus && globalThis.ManagerFocus.pick(instances());
          instId = String((focused || instances()[0]).id);
        }
      } catch (err) {
        toast(err.message || "读取原生 MCP 状态失败", "err");
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

    async function loadGroups(instance) {
      if (!instance) return toast("先选择实例", "warn");
      loadingGroups = true;
      try {
        const result = await api(`/api/mcp-native/groups?instance_id=${encodeURIComponent(instance)}`);
        groups = result.groups || [];
        if (!groupId && groups.length) groupId = String(groups[0].group_id);
        render();
        toast(groups.length ? `读到 ${groups.length} 个群` : "没有读到群", groups.length ? "ok" : "warn");
      } catch (err) {
        toast(err.message || "读取群失败", "err");
      } finally { loadingGroups = false; }
    }

    function bind() {
      viewEl.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-act]");
        if (!button) return;
        const act = button.dataset.act;
        if (act === "refresh") return load(true);
        if (act === "service-start") return run(() => api("/api/mcp-native/service/start", { method: "POST", body: {} }));
        if (act === "service-stop") {
          if (!(await confirm("停止原生 MCP", "Agent 将断开；正在接管的群会恢复 AstrBot 默认回复。继续？"))) return;
          return run(() => api("/api/mcp-native/service/stop", { method: "POST", body: {} }));
        }
        if (act === "token-rotate") {
          if (!(await confirm("轮换 Token", "旧 Agent 配置会立即失效，需要重新写入 Codex/DSH。继续？"))) return;
          return run(() => api("/api/mcp-native/tokens/rotate", { method: "POST", body: {} }));
        }
        if (act === "bridge-install") {
          const inst = button.dataset.inst;
          if (!(await confirm("安装 AstrBot 桥", "会复制 muyu_mcp_bridge 到该实例并重载插件；不会自动接管任何群。继续？"))) return;
          return run(async () => {
            await api("/api/mcp-native/bridge/install", {
              method: "POST",
              body: { instance_id: inst, manager_url: location.origin },
            });
            toast("桥插件已复制；请点“重启实例”加载它", "ok");
            setTimeout(() => load(true), 1500);
          });
        }
        if (act === "bridge-restart") {
          const inst = button.dataset.inst;
          if (!(await confirm("重启 AstrBot 实例", "会短暂断开该实例的 QQ 连接，用于加载/更新桥插件。继续？"))) return;
          return run(async () => {
            await api(`/api/instances/${encodeURIComponent(inst)}/restart`, { method: "POST", body: {} });
            toast("实例已重启；等待桥插件连接", "ok");
            setTimeout(() => load(true), 8000);
          });
        }
        if (act === "bridge-groups") {
          return run(async () => {
            await loadGroups(button.dataset.inst);
            if (!instId) instId = button.dataset.inst;
          });
        }
        if (act === "groups") return run(() => loadGroups(instId));
        if (act === "session-start") {
          if (!instId || !groupId) return toast("先选择实例和群", "warn");
          if (!(await confirm("开始接管", "该群默认 AstrBot 回复会暂停，直到你停止会话。确认开始？"))) return;
          return run(async () => {
            const sessionInst = instId;
            await api("/api/mcp-native/sessions/start", {
              method: "POST",
              body: { instance_id: sessionInst, group_id: groupId },
            });
            toast("已接管，Agent 可以开始 wait_chat_messages", "ok");
          });
        }
        if (act === "session-stop") {
          if (!(await confirm("停止接管", "会恢复该群 AstrBot 默认回复；已发出的消息无法撤回。继续？"))) return;
          return run(() => api(`/api/mcp-native/sessions/${encodeURIComponent(button.dataset.sid)}/stop`, { method: "POST", body: {} }));
        }
        if (act === "agent-install") {
          const agent = button.dataset.agent;
          return run(async () => {
            await api("/api/mcp-native/agents/install", { method: "POST", body: { agent } });
            toast(agent === "codex" ? "Codex 配置已写入；重启 Codex 会话后生效" : "DSH 配置已写入；重启 DSH 后生效", "ok");
          });
        }
        if (act === "dsh-restart") {
          if (!(await confirm("重启 DSH", "重启牧鱼管理的 DSH 以加载原生 MCP 配置。继续？"))) return;
          return run(() => api("/api/dsh/runtime/restart", { method: "POST", body: {} }));
        }
        if (act === "copy-prompt") {
          try { await navigator.clipboard.writeText(prompt); toast("启动指令已复制"); }
          catch (_) { toast("复制失败，请手动选择文本", "warn"); }
          return;
        }
      });
    }

    function renderView(view) {
      viewEl = view;
      if (!viewEl.dataset.nmcpBound) {
        viewEl.dataset.nmcpBound = "1";
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
    }

    return { render: renderView, leave };
  }

  return { create };
});
