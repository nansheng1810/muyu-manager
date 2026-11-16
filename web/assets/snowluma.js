/* 牧鱼 · SnowLuma QQ 后端：替换 NapCat，保留 AstrBot */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerSnowLuma = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    const confirm = typeof ctx.confirmDialog === "function" ? ctx.confirmDialog : async () => true;
    let viewEl = null;
    let data = null;
    let processes = [];
    let processError = "";
    let webui = null;
    let timer = null;
    let busy = false;
    let groups = {};
    let picker = "";

    const badge = (ok, text) => `<span class="badge ${ok ? "ok" : "warn"}">${esc(text)}</span>`;
    const backendBadge = (backend, row) => {
      if (backend === "snowluma") return badge(true, "SnowLuma");
      if (backend === "napcat") return badge(true, "NapCat");
      if (row && row.snowluma && row.snowluma.account_ready && !row.astrbot_clients) return badge(false, "等待 AstrBot");
      return badge(false, "离线");
    };

    function runtimeCard() {
      const runtime = (data && data.runtime) || {};
      const build = runtime.build || {};
      const running = Boolean(runtime.running);
      const built = Boolean(runtime.built);
      const building = Boolean(build.active);
      return `
        <section class="card sl-panel">
          <div class="sl-head">
            <h3>${icon("terminal")}SnowLuma 运行时</h3>
            ${badge(running, running ? "运行中" : (built ? "已构建" : "未构建"))}
          </div>
          <p class="sl-muted">SnowLuma 只替换 QQ 协议端；AstrBot 的 aiocqhttp、插件、记忆和拟人全部保留。</p>
          <div class="sl-meta">
            <span>版本</span><b>${esc(runtime.version || "—")}</b>
            <span>源码</span><code>${esc(runtime.root || "—")}</code>
            <span>控制台</span><code>${esc(runtime.webui_url || "未启动")}</code>
            <span>数据</span><code>${esc(runtime.data_dir || "—")}</code>
          </div>
          ${building ? `<div class="sl-build"><div class="sl-build-bar indeterminate"><i></i></div><small>${esc(build.phase || "构建中")}</small></div>` : ""}
          <div class="sl-actions">
            <button class="btn sm ${built ? "ghost" : "primary"}" data-act="build" ${building || running ? "disabled" : ""}>${icon("download")}${built ? "重新构建" : "构建 SnowLuma"}</button>
            <button class="btn sm primary" data-act="start" ${!built || running || building ? "disabled" : ""}>${icon("play")}启动</button>
            <button class="btn sm danger" data-act="stop" ${running ? "" : "disabled"}>${icon("stop")}停止</button>
            <button class="btn sm ghost" data-act="webui" ${running ? "" : "disabled"}>${icon("external")}打开控制台</button>
          </div>
          ${webui && webui.url ? `<div class="sl-secret"><span>控制台密码</span><code>${esc(webui.password || "—")}</code><button class="btn sm ghost" data-act="copy-webui">复制</button></div>` : ""}
          ${runtime.error ? `<p class="sl-error">${esc(runtime.error)}</p>` : ""}
        </section>`;
    }

    function groupPicker(row) {
      const inst = row.id;
      const state = groups[inst] || {};
      const close = `<button class="btn sm ghost" data-act="agent-group-close">收起</button>`;
      if (state.loading) return `<div class="sl-agent-picker"><p class="sl-muted">正在读取群列表…</p></div>`;
      if (state.error) return `<div class="sl-agent-picker"><p class="sl-error">${esc(state.error)}</p><div class="sl-actions"><button class="btn sm ghost" data-act="agent-groups-load" data-inst="${esc(inst)}">重试</button>${close}</div></div>`;
      const items = state.items || [];
      if (!items.length) return `<div class="sl-agent-picker"><p class="sl-muted">还没有读到群。先在目标群发一条消息，再重新读取。</p><div class="sl-actions"><button class="btn sm ghost" data-act="agent-groups-load" data-inst="${esc(inst)}">重新读取</button>${close}</div></div>`;
      const current = String((row.agent || {}).group_id || "");
      return `
        <div class="sl-agent-picker">
          <p class="sl-muted">选择要接管的群，会自动记住这次选择：</p>
          <div class="sl-agent-groups">${items.map((item) => {
            const gid = String(item.group_id || item.id || "");
            const name = String(item.group_name || item.name || gid);
            return `<button class="btn sm ${gid === current ? "primary" : "ghost"}" data-act="agent-group-set" data-inst="${esc(inst)}" data-gid="${esc(gid)}" data-gname="${esc(name)}">${esc(name)} · ${esc(gid)}</button>`;
          }).join("")}</div>
          <div class="sl-actions"><button class="btn sm ghost" data-act="agent-groups-load" data-inst="${esc(inst)}">重新读取</button>${close}</div>
        </div>`;
    }

    function agentCard(row) {
      const agent = row.agent || {};
      const runtime = agent.runtime || {};
      const enabled = Boolean(agent.enabled);
      const label = agent.agent_label || "无自动 Agent";
      const canAgent = Boolean(agent.agent);
      const running = enabled && runtime.status === "running";
      const groupText = agent.group_id
        ? `${agent.group_name || agent.group_id}（${agent.group_id}）`
        : "未选择，开启时自动使用上次的群";
      const runtimeText = enabled
        ? `运行 ${runtime.status || "idle"}${runtime.pid ? ` · PID ${runtime.pid}` : ""}`
        : "";
      const isDsh = agent.agent === "dsh";
      const isCodex = agent.agent === "codex";
      const chosen = agent.dsh_model || {};
      const catalog = (data && data.dsh_models) || { default: {}, groups: [] };
      const current = chosen.provider && chosen.model ? chosen.provider + "/" + chosen.model : "";
      const defaultName = catalog.default && catalog.default.provider
        ? "DSH 默认（" + catalog.default.provider + "/" + catalog.default.model + "）"
        : "DSH 默认模型";
      const modelOptions = (catalog.groups || []).map((group) => `
        <optgroup label="${esc(group.name || group.id)}">
          ${(group.models || []).map((model) => {
            const value = group.id + "/" + model;
            return `<option value="${esc(value)}" ${current === value ? "selected" : ""}>${esc(model)}</option>`;
          }).join("")}
        </optgroup>`).join("");
      const modelRow = isDsh ? `
        <div class="sl-agent-model">
          <span>模型${chosen.provider ? " · 当前 " + esc(current) : ""}</span>
          <select data-act="agent-model" data-inst="${esc(row.id)}" data-agent="dsh">
            <option value="" ${current ? "" : "selected"}>${esc(defaultName)}</option>
            ${modelOptions}
          </select>
        </div>` : "";
      const codexCatalog = (data && data.codex_models) || { current: "", models: [], error: "" };
      const codexCurrent = String(agent.codex_model || codexCatalog.current || "");
      const codexList = codexCatalog.models || [];
      const codexKnown = codexList.some((model) => model.id === codexCurrent);
      const codexOptions = codexList.map((model) => `
        <option value="${esc(model.id)}" ${codexCurrent === model.id ? "selected" : ""}>${esc(model.name || model.id)}</option>`).join("");
      const codexRow = isCodex ? `
        <div class="sl-agent-model">
          <span>模型${codexCurrent ? " · 当前 " + esc(codexCurrent) : ""}</span>
          ${codexList.length ? `
          <select data-act="agent-model" data-inst="${esc(row.id)}" data-agent="codex">
            ${codexCurrent && !codexKnown ? `<option value="${esc(codexCurrent)}" selected>${esc(codexCurrent)}</option>` : ""}
            ${codexOptions}
          </select>` : `<span class="sl-muted">${esc(codexCatalog.error || "没有读取到 Codex 模型目录")}</span>`}
        </div>` : "";
      return `
        <div class="sl-agent ${enabled ? "on" : ""}">
          <div class="sl-agent-head">
            <b>${icon("bots")}Agent 模式</b>
            ${enabled ? badge(running, running ? `${label} 接管中` : "已开启") : badge(false, canAgent ? label : "无自动 Agent")}
          </div>
          <div class="sl-instance-note">
            <span>接管群 ${esc(groupText)}${runtimeText ? ` · ${esc(runtimeText)}` : ""}</span>
          </div>
          <div class="sl-actions">
            <button class="btn sm ${enabled ? "ghost" : "primary"}" data-act="agent-toggle" data-inst="${esc(row.id)}" ${canAgent && row.snowluma.bound && data.runtime && data.runtime.running ? "" : "disabled"}>${icon(enabled ? "stop" : "play")}${enabled ? "关闭 Agent 模式" : "开启 Agent 模式"}</button>
            <button class="btn sm ghost" data-act="agent-group" data-inst="${esc(row.id)}" ${row.snowluma.bound ? "" : "disabled"}>选择群</button>
          </div>
          ${modelRow}
          ${codexRow}
          ${canAgent ? "" : `<p class="sl-muted">这个实例没有绑定 DSH / Codex，先在原生 MCP 页把 Agent 绑定到它。</p>`}
          ${picker === row.id ? groupPicker(row) : ""}
          ${runtime.error ? `<p class="sl-error">${esc(runtime.error)}</p>` : ""}
        </div>`;
    }

    function instanceCard(row) {
      const snow = row.snowluma || {};
      const binding = snow.binding || {};
      const bound = Boolean(snow.bound);
      const napcat = row.napcat || {};
      const canBind = Boolean(row.qq && data.runtime && data.runtime.running && !napcat.running);
      return `
        <div class="sl-instance">
          <div class="sl-instance-main">
            <div>
              <b>${esc(row.name || row.id)}</b>
              <small>${esc(row.id)} · QQ ${esc(row.qq || "未填写")} · AstrBot WS ${esc(row.ws_port || "—")}</small>
            </div>
            <div class="sl-instance-state">
              ${backendBadge(row.backend, row)}
              ${bound ? badge(Boolean(snow.account_ready), snow.account_ready ? "账号在线" : "等待账号") : ""}
              ${napcat.clients ? badge(true, `NapCat ${napcat.clients}`) : ""}
            </div>
          </div>
          <div class="sl-instance-note">
            ${bound
              ? `<span>绑定 QQ ${esc(binding.uin || row.qq)} · OneBot HTTP ${esc(binding.http_port || "—")} · ${esc(binding.astrbot_url || "")}${snow.account_ready && !row.astrbot_clients ? " · AstrBot 实例未运行，启动后才会收消息" : ""}</span>`
              : `<span>未绑定 SnowLuma${napcat.running ? " · 请先停止 NapCat" : ""}</span>`}
          </div>
          <div class="sl-actions">
            <button class="btn sm primary" data-act="bind" data-inst="${esc(row.id)}" ${canBind || bound ? "" : "disabled"}>${icon("check")}${bound ? (snow.account_ready ? "重新绑定" : "加载账号") : "一键绑定 SnowLuma"}</button>
            <button class="btn sm ghost" data-act="unbind" data-inst="${esc(row.id)}" ${bound ? "" : "disabled"}>解除绑定</button>
            <button class="btn sm ghost" data-act="napcat-stop" data-inst="${esc(row.id)}" ${napcat.running ? "" : "disabled"}>停止 NapCat</button>
            <button class="btn sm ghost" data-act="napcat" data-inst="${esc(row.id)}" ${bound || row.backend === "snowluma" ? "" : "disabled"}>切回 NapCat</button>
          </div>
          ${bound ? agentCard(row) : ""}
          ${binding.error ? `<p class="sl-error">${esc(binding.error)}</p>` : ""}
        </div>`;
    }

    function instancesCard() {
      const rows = (data && Array.isArray(data.instances)) ? data.instances : [];
      return `
        <section class="card sl-panel">
          <div class="sl-head"><h3>${icon("bots")}机器人后端</h3>${badge(rows.some((x) => x.backend === "snowluma"), "按实例切换")}</div>
          <p class="sl-muted">每个实例单独绑定。绑定要求该 QQ 已由 SnowLuma 加载，且不能和 NapCat 共用同一个 QQ 进程。</p>
          <div class="sl-instances">${rows.length ? rows.map(instanceCard).join("") : `<p class="sl-muted">还没有 AstrBot 实例。</p>`}</div>
        </section>`;
    }

    function processCard() {
      const runtime = (data && data.runtime) || {};
      const rows = processes.map((row) => `
        <div class="sl-process ${row.blocked ? "blocked" : ""}">
          <div>
            <b>${esc(row.nickname || row.name || `PID ${row.pid}`)}</b>
            <small>PID ${esc(row.pid)} · QQ ${esc(row.uin || "未登录")} · ${esc(row.status || "未知")}${row.instance_name ? ` · ${esc(row.instance_name)}` : ""}</small>
            <code>${esc(row.path || "")}</code>
          </div>
          <div class="sl-process-actions">
            ${row.blocked ? `<span class="sl-blocked">NapCat 进程，禁止绑定</span>` : ""}
            <button class="btn sm ghost" data-act="bind-process" data-pid="${esc(row.pid)}" data-inst="${esc(row.instance_id || "")}" ${!row.instance_id || row.blocked || !runtime.running ? "disabled" : ""}>绑定此进程</button>
          </div>
        </div>`).join("");
      return `
        <section class="card sl-panel">
          <div class="sl-head"><h3>${icon("terminal")}QQ 进程</h3>${badge(!processError, processError ? "不可用" : `${processes.length} 个`)}</div>
          <p class="sl-muted">首次使用先在 SnowLuma 控制台同意 EULA / 隐私政策，并登录一个不在 NapCat 目录下的 QQ 进程。</p>
          ${processError ? `<div class="sl-callout"><span>${esc(processError)}</span>${runtime.running ? `<button class="btn sm ghost" data-act="webui">打开控制台</button>` : ""}<button class="btn sm ghost" data-act="refresh-processes">刷新</button></div>` : ""}
          ${rows ? `<div class="sl-processes">${rows}</div>` : `<p class="sl-muted">还没有可用的 QQ 进程。打开 SnowLuma 控制台加载进程后刷新。</p>`}
        </section>`;
    }

    function logCard() {
      return `
        <section class="card sl-panel">
          <div class="sl-head"><h3>${icon("logs")}怎么切</h3></div>
          <ol class="sl-steps">
            <li>构建并启动 SnowLuma，打开控制台同意协议、登录普通 QQ 客户端。</li>
            <li>回到这里刷新进程，确认 QQ 进程不在 NapCat 目录下。</li>
            <li>点“一键绑定 SnowLuma”，管理器会写入 SnowLuma 的 OneBot 反向 WS 到 AstrBot。</li>
            <li>需要回退时点“切回 NapCat”，会先卸载 SnowLuma 的 QQ 进程，再启动 NapCat。</li>
            <li>绑定后打开“Agent 模式”，会记住接管群并自动拉起 DSH / Codex 直接进群回复。</li>
          </ol>
        </section>`;
    }

    function render() {
      if (!viewEl) return;
      if (!data) {
        viewEl.innerHTML = `<div class="skeleton" style="height:320px"></div>`;
        return;
      }
      viewEl.innerHTML = `
        <div class="sl-hero">
          <div>
            <h2>SnowLuma</h2>
            <p>QQ 协议端替换为 SnowLuma，AstrBot 继续管记忆、插件和拟人。</p>
          </div>
          <div class="sl-hero-actions">
            <button class="btn sm ghost" data-act="refresh">${icon("refresh")}刷新</button>
          </div>
        </div>
        <div class="sl-grid">
          ${runtimeCard()}
          ${instancesCard()}
          ${processCard()}
          ${logCard()}
        </div>`;
    }

    async function loadProcesses(showError) {
      try {
        const result = await api("/api/snowluma/processes");
        processes = Array.isArray(result.items) ? result.items : [];
        processError = "";
      } catch (err) {
        processes = [];
        processError = err.message || "读取 QQ 进程失败";
        if (showError) toast(processError, "warn");
      }
    }

    async function loadGroups(inst) {
      groups[inst] = { loading: true, items: [], error: "" };
      render();
      try {
        const result = await api(`/api/mcp-native/groups?instance_id=${encodeURIComponent(inst)}`);
        groups[inst] = { loading: false, items: Array.isArray(result.groups) ? result.groups : [], error: "" };
      } catch (err) {
        groups[inst] = { loading: false, items: [], error: err.message || "读取群列表失败" };
      }
      render();
    }

    async function load(force) {
      if (busy && !force) return;
      try {
        const status = await api("/api/snowluma/status");
        data = status;
        await loadProcesses(false);
      } catch (err) {
        toast(err.message || "读取 SnowLuma 状态失败", "err");
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
      viewEl.addEventListener("change", async (event) => {
        const select = event.target.closest('[data-act="agent-model"]');
        if (!select) return;
        const inst = select.dataset.inst;
        const kind = select.dataset.agent || "dsh";
        const value = String(select.value || "");
        let provider = "";
        let model = "";
        if (kind === "codex") {
          model = value;
        } else {
          const split = value.indexOf("/");
          provider = split > 0 ? value.slice(0, split) : "";
          model = split > 0 ? value.slice(split + 1) : "";
        }
        if (kind === "codex" && !model) {
          toast("请选择 Codex 模型", "err");
          render();
          return;
        }
        const label = kind === "codex" ? "Codex" : "DSH";
        if (!(await confirm(`切换 ${label} 模型`, value ? `之后 ${label} Agent 使用「${value}」，正在运行会立即重启接管会话。继续？` : `恢复使用 ${label} 设置里的默认模型，正在运行会立即重启接管会话。继续？`))) {
          render();
          return;
        }
        return run(async () => {
          await api("/api/snowluma/agent-model", {
            method: "POST",
            body: { instance_id: inst, provider, model },
          });
          toast(value ? `${label} 模型已切换：${value}` : `已恢复 ${label} 默认模型`, "ok");
        });
      });
      viewEl.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-act]");
        if (!button) return;
        const act = button.dataset.act;
        if (act === "refresh") return load(true);
        if (act === "refresh-processes") return run(() => loadProcesses(true));
        if (act === "build") {
          if (!(await confirm("构建 SnowLuma", "会安装依赖并构建全部源码，可能需要几分钟；不会影响正在运行的 QQ。继续？"))) return;
          return run(async () => {
            await api("/api/snowluma/build", { method: "POST", body: {} });
            toast("SnowLuma 开始构建，进度会自动刷新", "ok");
          });
        }
        if (act === "start") {
          return run(async () => {
            await api("/api/snowluma/start", { method: "POST", body: {} });
            toast("SnowLuma 已启动", "ok");
          });
        }
        if (act === "stop") {
          if (!(await confirm("停止 SnowLuma", "所有 SnowLuma 账号会断开，AstrBot 将暂时没有 QQ 连接。继续？"))) return;
          return run(() => api("/api/snowluma/stop", { method: "POST", body: {} }));
        }
        if (act === "webui") {
          return run(async () => {
            webui = await api("/api/snowluma/webui", { method: "POST", body: {} });
            render();
            if (webui.url) window.open(webui.url, "_blank", "noopener");
          });
        }
        if (act === "copy-webui") {
          try { await navigator.clipboard.writeText(webui ? webui.password || "" : ""); toast("控制台密码已复制"); }
          catch (_) { toast("复制失败，请手动选择", "warn"); }
          return;
        }
        if (act === "bind" || act === "bind-process") {
          const inst = button.dataset.inst;
          const pid = Number(button.dataset.pid || 0);
          if (!inst) return toast("这个 QQ 进程还没有匹配到机器人实例", "warn");
          const row = (data.instances || []).find((x) => String(x.id) === String(inst));
          const name = row ? row.name : inst;
          if (!(await confirm("绑定 SnowLuma", `把 ${name} 的 AstrBot 接到 SnowLuma。需要该 QQ 已由 SnowLuma 加载，且不能和 NapCat 共用进程。继续？`))) return;
          return run(async () => {
            const result = await api("/api/snowluma/bind", {
              method: "POST",
              body: { instance_id: inst, pid },
            });
            const onebot = result.onebot || {};
            if (onebot.ready) toast(`已绑定 ${name}，QQ ${onebot.account} 已在线`, "ok");
            else toast(`配置已写入，但账号还没就绪：${onebot.error || "请刷新进程"}`, "warn");
          });
        }
        if (act === "agent-toggle") {
          const inst = button.dataset.inst;
          const row = (data.instances || []).find((x) => String(x.id) === String(inst)) || {};
          const agent = row.agent || {};
          const enable = !agent.enabled;
          const label = agent.agent_label || "Agent";
          const group = agent.group_id ? `${agent.group_name || agent.group_id}（${agent.group_id}）` : "上次记住的群（没有就用第一个群）";
          if (enable) {
            const warn = agent.agent === "codex" ? "Codex 会以绕过审批的沙箱模式运行，只在本机使用。" : "";
            if (!(await confirm("开启 Agent 模式", `会自动拉起 ${label}，建立接管会话并直接开始回复，目标群：${group}。${warn}继续？`))) return;
          } else if (!(await confirm("关闭 Agent 模式", `会停止 ${label} 并释放接管会话，AstrBot 恢复默认回复。继续？`))) return;
          return run(async () => {
            const result = await api("/api/snowluma/agent-mode", {
              method: "POST",
              body: { instance_id: inst, enabled: enable },
            });
            const next = result.agent || {};
            if (enable) toast(`Agent 模式已开启：${next.group_name || next.group_id || ""}`, "ok");
            else toast("Agent 模式已关闭", "ok");
          });
        }
        if (act === "agent-group") {
          const inst = button.dataset.inst;
          if (picker === inst) {
            picker = "";
            render();
            return;
          }
          picker = inst;
          return loadGroups(inst);
        }
        if (act === "agent-groups-load") {
          return loadGroups(button.dataset.inst);
        }
        if (act === "agent-group-close") {
          picker = "";
          render();
          return;
        }
        if (act === "agent-group-set") {
          const inst = button.dataset.inst;
          const gid = button.dataset.gid;
          const gname = button.dataset.gname || gid;
          if (!(await confirm("记住接管群", `之后开启 Agent 模式会接管「${gname}」。如果 Agent 正在运行，会立即切到这个群。继续？`))) return;
          return run(async () => {
            await api("/api/snowluma/agent-group", {
              method: "POST",
              body: { instance_id: inst, group_id: gid, group_name: gname },
            });
            picker = "";
            toast(`已记住接管群：${gname}`, "ok");
          });
        }
        if (act === "unbind") {
          const inst = button.dataset.inst;
          if (!(await confirm("解除 SnowLuma 绑定", "会从 SnowLuma 移除 AstrBot 的 OneBot 客户端；不会自动启动 NapCat。继续？"))) return;
          return run(async () => {
            await api("/api/snowluma/unbind", { method: "POST", body: { instance_id: inst } });
            toast("已解除绑定", "ok");
          });
        }
        if (act === "napcat-stop") {
          const inst = button.dataset.inst;
          if (!(await confirm("停止 NapCat", "只会结束该实例 NapCat 目录下的 QQ / 启动器进程，不会关闭普通 QQ 客户端。继续？"))) return;
          return run(async () => {
            const result = await api("/api/snowluma/napcat-stop", { method: "POST", body: { instance_id: inst } });
            toast(result.killed ? `已停止 NapCat（${result.killed} 个进程）` : "没有发现运行中的 NapCat 进程", result.killed ? "ok" : "warn");
          });
        }
        if (act === "napcat") {
          const inst = button.dataset.inst;
          if (!(await confirm("切回 NapCat", "会卸载 SnowLuma 的这个 QQ 进程，然后启动 NapCat；短暂离线。继续？"))) return;
          return run(async () => {
            await api("/api/snowluma/napcat", { method: "POST", body: { instance_id: inst } });
            toast("已切回 NapCat，正在重新登录", "ok");
          });
        }
      });
    }

    function renderView(view) {
      viewEl = view;
      if (!viewEl.dataset.slBound) {
        viewEl.dataset.slBound = "1";
        bind();
      }
      render();
      load(true);
      if (timer) clearInterval(timer);
      timer = setInterval(() => {
        const focused = document.activeElement && viewEl.contains(document.activeElement);
        if (document.visibilityState === "visible" && !busy && !focused) load();
      }, 6000);
    }

    function leave() {
      if (timer) clearInterval(timer);
      timer = null;
    }

    return { render: renderView, leave };
  }

  return { create };
});
