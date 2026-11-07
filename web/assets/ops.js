/* 牧鱼 · 告警中心与一致性巡检（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerOps = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const SEVERITY_LABEL = { critical: "严重", warning: "警告", ok: "正常" };
  const CHECK_STATUS_LABEL = { ok: "正常", warn: "警告", bad: "异常" };
  const KIND_LABEL = { health: "健康", approval: "审批", task: "任务", backup: "备份" };
  const DRIFT_LABEL = { plugins: "插件", providers: "模型", personas: "人格" };

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function severityClass(value) {
    return value === "critical" ? "bad" : value === "warning" ? "warn" : "ok";
  }

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    let timer = null;
    let alertToken = 0;
    let driftToken = 0;
    let driftData = null;

    function summaryHtml(counts, labels) {
      return `<div class="auto-summary-grid" style="grid-template-columns:repeat(${labels.length},minmax(0,1fr))">
        ${labels.map((item) => `<div class="auto-summary"><div class="k">${esc(item.label)}</div>
          <div class="v">${esc(item.value)}${item.unit ? `<small>${esc(item.unit)}</small>` : ""}</div></div>`).join("")}
      </div>`;
    }

    function alertRow(item) {
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title">
            <strong>${esc(item.title)}</strong>
            <span class="badge ${severityClass(item.severity)}">${esc(SEVERITY_LABEL[item.severity] || item.severity)}</span>
            <span class="badge">${esc(KIND_LABEL[item.kind] || item.kind)}</span>
          </div>
          ${item.summary ? `<p class="approval-reason">${esc(item.summary)}</p>` : ""}
          <div class="auto-meta"><span>来源 <b>${esc(item.ref || "—")}</b></span></div>
        </div>
        ${item.route ? `<div class="auto-actions"><button class="btn sm ghost" data-alert-route="${esc(item.route)}">去处理</button></div>` : ""}
      </article>`;
    }

    function alertListHtml(data) {
      const items = data.alerts || [];
      if (!items.length) {
        return `<div class="empty" style="padding:30px">${icon("check")}<h4>没有需要处理的告警</h4>
          <p>健康、审批、任务和备份检查都正常。</p></div>`;
      }
      return `<div class="auto-list">${items.map(alertRow).join("")}</div>`;
    }

    async function loadAlerts(view, force = false) {
      const current = ++alertToken;
      const box = view.querySelector("#alert-list");
      if (!box) return;
      if (!force) box.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
      try {
        const data = await api(`/api/alerts${force ? "?force=1" : ""}`);
        if (current !== alertToken || !view.isConnected) return;
        const counts = data.counts || {};
        const summary = view.querySelector("#alert-summary");
        if (summary) {
          summary.innerHTML = summaryHtml(counts, [
            { label: "严重", value: counts.critical || 0, unit: "项" },
            { label: "警告", value: counts.warning || 0, unit: "项" },
            { label: "合计", value: counts.total || 0, unit: "项" },
          ]);
        }
        const meta = view.querySelector("#alert-meta");
        if (meta) meta.textContent = `生成于 ${fmtTime(data.generated_at)}`;
        box.innerHTML = alertListHtml(data);
        box.querySelectorAll("[data-alert-route]").forEach((btn) => {
          btn.addEventListener("click", () => { location.hash = btn.dataset.alertRoute; });
        });
      } catch (err) {
        if (current !== alertToken) return;
        box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
        toast(err.message, "err");
      }
    }

    function renderAlerts(view) {
      leave();
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left">
            <button class="btn sm ghost" id="alert-refresh">${icon("refresh")}刷新</button>
          </div>
          <div class="right"><span class="side" id="alert-meta"></span></div>
        </div>
        <div id="alert-summary"><div class="skeleton" style="height:80px"></div></div>
        <div class="card" style="margin-top:16px">
          <div class="section-head" style="margin:0 0 10px"><h2>待处理告警</h2>
            <span class="side">健康 / 审批 / 任务 / 备份</span></div>
          <div id="alert-list"><div class="skeleton" style="height:160px"></div></div>
        </div>
        <p class="hint-text">只读汇总，不会自动修复。严重告警会随健康检查每 5 秒缓存刷新；页面每 15 秒自动重读。</p>`;
      view.querySelector("#alert-refresh").addEventListener("click", () => loadAlerts(view, true));
      loadAlerts(view);
      timer = setInterval(() => {
        if (view.isConnected) loadAlerts(view, true);
      }, 15000);
    }

    function driftValue(kind, value) {
      if (!value) return "缺失";
      if (kind === "plugins") return `${value.version || "—"}${value.enabled === false ? "（停用）" : ""}`;
      if (kind === "providers") return `${value.model || "—"}${value.enabled === false ? "（停用）" : ""}`;
      return `${value.chars || 0} 字 · ${String(value.hash || "").slice(0, 8)}`;
    }

    function driftInstanceHtml(snap) {
      const counts = [
        ["插件", Object.keys(snap.plugins || {}).length],
        ["模型", Object.keys(snap.providers || {}).length],
        ["人格", Object.keys(snap.personas || {}).length],
      ];
      const errors = Object.entries(snap.errors || {}).map(([key, value]) => `${key}: ${value}`).join("；");
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(snap.name || snap.id)}</strong>
            <span class="badge ${snap.reachable ? "ok" : "bad"}">${snap.reachable ? "可达" : "不可达"}</span></div>
          <div class="auto-meta">${counts.map(([label, value]) => `<span>${esc(label)} <b>${value}</b></span>`).join("")}</div>
          ${errors ? `<p class="approval-reason">${esc(errors)}</p>` : ""}
        </div>
      </article>`;
    }

    function driftIssueHtml(issue) {
      const values = Object.entries(issue.values || {}).map(([inst, value]) =>
        `<span>${esc(inst)} <b>${esc(driftValue(issue.kind, value))}</b></span>`).join("");
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(DRIFT_LABEL[issue.kind] || issue.kind)} · ${esc(issue.key)}</strong>
            <span class="badge warn">不一致</span></div>
          <p class="approval-reason">${esc(issue.message)}</p>
          <div class="auto-meta">${values}</div>
        </div>
      </article>`;
    }

    async function loadDrift(view, force = false) {
      const current = ++driftToken;
      const box = view.querySelector("#drift-body");
      if (!box) return;
      if (!force) box.innerHTML = `<div class="skeleton" style="height:220px"></div>`;
      try {
        const data = await api("/api/drift");
        if (current !== driftToken || !view.isConnected) return;
        driftData = data;
        const counts = data.counts || {};
        const meta = view.querySelector("#drift-meta");
        if (meta) meta.textContent = `生成于 ${fmtTime(data.generated_at)} · 参考 ${data.reference || "—"}`;
        const issues = data.issues || [];
        const overall = data.overall === "ok" ? "一致" : data.overall === "bad" ? "有实例不可达" : "有差异";
        const overallCls = data.overall === "ok" ? "ok" : data.overall === "bad" ? "bad" : "warn";
        const unreachable = (counts.instances || 0) > (counts.reachable || 0);
        box.innerHTML = `
          ${summaryHtml(counts, [
            { label: "实例", value: counts.instances || 0, unit: "个" },
            { label: "可达", value: counts.reachable || 0, unit: "个" },
            { label: "差异", value: counts.total || 0, unit: "项" },
            { label: "整体", value: overall },
          ])}
          <div class="card">
            <div class="section-head" style="margin:0 0 10px"><h2>实例快照</h2><span class="side">插件 / 模型 / 人格数量</span></div>
            <div class="auto-list">${(data.instances || []).map(driftInstanceHtml).join("")}</div>
          </div>
          <div class="card" style="margin-top:16px">
            <div class="section-head" style="margin:0 0 10px"><h2>差异</h2>
              <span class="side"><span class="badge ${overallCls}">${esc(overall)}</span>
                ${issues.length ? `${issues.length} 项需要人工确认` : "未发现差异"}</span></div>
            ${issues.length ? `<div class="auto-list">${issues.map(driftIssueHtml).join("")}</div>` :
              `<div class="empty" style="padding:24px">${icon(unreachable ? "alert" : "check")}<h4>${unreachable ? "所有可达实例一致，但有实例不可达" : "所有可达实例一致"}</h4><p>参考实例：${esc(data.reference || "—")}</p></div>`}
          </div>`;
      } catch (err) {
        box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
        toast(err.message, "err");
      }
    }

    async function alignDrift(view) {
      if (!driftData || !driftData.reference) {
        toast("还没有可用的参考实例", "warn");
        return;
      }
      const kinds = [];
      if (view.querySelector("#drift-kind-plugins")?.checked) kinds.push("plugins");
      if (view.querySelector("#drift-kind-personas")?.checked) kinds.push("personas");
      if (!kinds.length) {
        toast("至少选择插件启停或人格正文", "warn");
        return;
      }
      const typed = window.prompt("对齐会先创建备份，再修改目标实例的插件启停/人格正文。\n不会改版本、模型密钥或 default 人格。\n\n输入 ALIGN 确认：", "");
      if (typed !== "ALIGN") {
        if (typed !== null) toast("未输入 ALIGN，已取消", "warn");
        return;
      }
      const btn = view.querySelector("#drift-align");
      if (btn) btn.disabled = true;
      try {
        const result = await api("/api/drift/align", {
          method: "POST",
          body: { reference: driftData.reference, kinds, confirm: "ALIGN" },
        });
        const skipped = (result.skipped || []).length;
        toast(result.actions?.length
          ? `已对齐 ${result.actions.length} 项${skipped ? `，跳过 ${skipped} 项` : ""}；备份 ${result.backup?.path ? "已生成" : "无"}`
          : `没有需要写入的项${skipped ? `，跳过 ${skipped} 项` : ""}`,
          skipped ? "warn" : "ok");
        await loadDrift(view);
      } catch (err) {
        toast(err.message, "err");
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function renderDrift(view) {
      leave();
      driftData = null;
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left">
            <button class="btn sm ghost" id="drift-refresh">${icon("refresh")}重新对比</button>
            <label class="checkline"><input type="checkbox" id="drift-kind-plugins" checked>插件启停</label>
            <label class="checkline"><input type="checkbox" id="drift-kind-personas" checked>人格正文</label>
            <button class="btn sm danger" id="drift-align">对齐差异</button>
          </div>
          <div class="right"><span class="side" id="drift-meta"></span></div>
        </div>
        <div id="drift-body"><div class="skeleton" style="height:220px"></div></div>
        <p class="hint-text">以第一个可达实例为参考，检查插件版本/启停、对话模型和人格内容哈希。对齐会先备份；只处理插件启停与人格正文，版本/密钥/模型配置和 default 人格不会自动改。</p>`;
      view.querySelector("#drift-refresh").addEventListener("click", () => loadDrift(view, true));
      view.querySelector("#drift-align").addEventListener("click", () => alignDrift(view));
      loadDrift(view);
    }

    function matrixValue(row, value) {
      if (value === null || value === undefined) return `<span class="badge">未装</span>`;
      const on = value === true;
      if (row.risk === "approval" || row.risk === "safety" || row.risk === "read") {
        return `<span class="badge ${on ? "ok" : "warn"}">${on ? "开" : "关"}</span>`;
      }
      return `<span class="badge ${on ? "warn" : "ok"}">${on ? "开" : "关"}</span>`;
    }

    async function loadMatrix(view) {
      const box = view.querySelector("#matrix-body");
      if (!box) return;
      box.innerHTML = `<div class="skeleton" style="height:220px"></div>`;
      try {
        const data = await api("/api/matrix");
        const summary = data.summary || {};
        const instances = data.instances || [];
        const rows = data.rows || [];
        const head = instances.map((item) => `<th>${esc(item.name)}${item.online ? "" : "（离线）"}</th>`).join("");
        box.innerHTML = `
          ${summaryHtml(summary, [
            { label: "实例", value: summary.instances || 0, unit: "个" },
            { label: "写开关开启", value: summary.write_on || 0, unit: "项" },
            { label: "审批未开", value: summary.approval_off || 0, unit: "个实例" },
            { label: "干跑关闭", value: summary.dry_run_off || 0, unit: "个实例" },
          ])}
          <div class="card" style="overflow-x:auto">
            <div class="section-head" style="margin:0 0 10px"><h2>权限与写开关</h2>
              <span class="side">只读自插件配置文件</span></div>
            <table class="table">
              <thead><tr><th>项目</th>${head}</tr></thead>
              <tbody>${rows.map((row) => `<tr>
                <td><div class="cell-title"><b>${esc(row.label)}</b>
                  <span class="badge">${esc(row.risk === "write" ? "写" : row.risk === "approval" ? "审批" : row.risk === "safety" ? "安全" : "读")}</span></div>
                  <div class="mono">${esc(row.id)}</div></td>
                ${instances.map((item) => `<td>${matrixValue(row, item.values?.[row.id])}</td>`).join("")}
              </tr>`).join("")}</tbody>
            </table>
          </div>
          <p class="hint-text">写开关开启不等于正在执行：还要看任务/调度、插件运行态和审批模式。审批未开、干跑关闭会单独计数，不会被悄悄改回。</p>`;
      } catch (err) {
        box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
        toast(err.message, "err");
      }
    }

    function renderMatrix(view) {
      leave();
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left"><button class="btn sm ghost" id="matrix-refresh">${icon("refresh")}刷新</button></div>
          <div class="right"><span class="side">B站 / 抖音 / 审批</span></div>
        </div>
        <div id="matrix-body"><div class="skeleton" style="height:220px"></div></div>`;
      view.querySelector("#matrix-refresh").addEventListener("click", () => loadMatrix(view));
      loadMatrix(view);
    }

    function processNames(names) {
      const entries = Object.entries(names || {});
      return entries.length ? entries.map(([name, count]) => `${name}×${count}`).join(" · ") : "—";
    }

    function resourceRow(item) {
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(item.name)}</strong>
            <span class="badge ${item.online ? "ok" : "bad"}">${item.online ? "运行中" : "离线"}</span>
            ${item.managed ? "" : `<span class="badge warn">外部进程</span>`}</div>
          <div class="auto-meta">
            <span>CPU <b>${esc(item.cpu_percent ?? 0)}%</b></span>
            <span>内存 <b>${esc(item.memory_mb ?? 0)} MB</b></span>
            <span>进程 <b>${esc(item.processes ?? 0)}</b></span>
            <span>PID <b>${esc(item.pid || "—")}</b></span>
          </div>
          <div class="mono" style="margin-top:6px;color:var(--dim)">${esc(processNames(item.names))}</div>
        </div>
      </article>`;
    }

    async function loadResources(view) {
      const box = view.querySelector("#resource-body");
      if (!box) return;
      try {
        const data = await api("/api/resources");
        const system = data.system || {};
        const manager = data.manager || {};
        box.innerHTML = `
          ${summaryHtml({}, [
            { label: "系统 CPU", value: `${system.cpu_percent ?? 0}%` },
            { label: "系统内存", value: `${system.memory_percent ?? 0}%`, unit: `${system.memory_used_gb ?? 0}/${system.memory_total_gb ?? 0} GB` },
            { label: "磁盘可用", value: `${system.disk_free_gb ?? 0} GB` },
            { label: "管理器", value: `${manager.memory_mb ?? 0} MB`, unit: `${manager.cpu_percent ?? 0}% CPU` },
          ])}
          <div class="card">
            <div class="section-head" style="margin:0 0 10px"><h2>机器人进程</h2>
              <span class="side">${(data.instances || []).length} 个实例 · ${esc(fmtTime(data.generated_at))}</span></div>
            <div class="auto-list">${(data.instances || []).map(resourceRow).join("") || `<div class="empty" style="padding:20px"><p>没有实例</p></div>`}</div>
          </div>`;
      } catch (err) {
        box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
        toast(err.message, "err");
      }
    }

    function renderResources(view) {
      leave();
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left"><button class="btn sm ghost" id="resource-refresh">${icon("refresh")}刷新</button></div>
          <div class="right"><span class="side">10 秒自动刷新 · 进程树只读</span></div>
        </div>
        <div id="resource-body"><div class="skeleton" style="height:220px"></div></div>`;
      view.querySelector("#resource-refresh").addEventListener("click", () => loadResources(view));
      loadResources(view);
      timer = setInterval(() => { if (view.isConnected) loadResources(view); }, 10000);
    }

    function canaryCheckRow(item) {
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(item.label)}</strong>
            <span class="badge ${severityClass(item.status === "bad" ? "critical" : item.status === "warn" ? "warning" : "ok")}">${esc(CHECK_STATUS_LABEL[item.status] || item.status)}</span></div>
          <p class="approval-reason">${esc(item.summary || "")}</p>
          <div class="auto-meta"><span>ID <b>${esc(item.id)}</b></span><span>耗时 <b>${esc(item.latency_ms ?? 0)} ms</b></span></div>
        </div>
        ${item.route ? `<div class="auto-actions"><button class="btn sm ghost" data-canary-route="${esc(item.route)}">查看</button></div>` : ""}
      </article>`;
    }

    function canaryBody(data) {
      if (!data) {
        return `<div class="empty" style="padding:28px">${icon("pulse")}<h4>还没有巡检记录</h4>
          <p>点击“立即巡检”执行一次只读端到端检查。</p></div>`;
      }
      const counts = data.counts || {};
      return `
        ${summaryHtml(counts, [
          { label: "总体", value: CHECK_STATUS_LABEL[data.overall] || data.overall || "—" },
          { label: "正常", value: counts.ok || 0, unit: "项" },
          { label: "警告", value: counts.warn || 0, unit: "项" },
          { label: "异常", value: counts.bad || 0, unit: "项" },
        ])}
        <div class="card">
          <div class="section-head" style="margin:0 0 10px"><h2>检查项</h2>
            <span class="side">${esc(fmtTime(data.generated_at))} · ${counts.total || 0} 项</span></div>
          <div class="auto-list">${(data.checks || []).map(canaryCheckRow).join("")}</div>
        </div>`;
    }

    async function loadCanary(view, run = false) {
      const box = view.querySelector("#canary-body");
      const btn = view.querySelector("#canary-run");
      if (!box) return;
      if (run) {
        if (btn) { btn.disabled = true; btn.textContent = "巡检中…"; }
        box.innerHTML = `<div class="skeleton" style="height:220px"></div>`;
      }
      try {
        const data = run
          ? await api("/api/canary/run", { method: "POST", body: {} })
          : await api("/api/canary/last");
        if (!view.isConnected) return;
        box.innerHTML = canaryBody(data);
        box.querySelectorAll("[data-canary-route]").forEach((node) => {
          node.addEventListener("click", () => { location.hash = node.dataset.canaryRoute; });
        });
        if (run) toast(`巡检完成：${CHECK_STATUS_LABEL[data.overall] || data.overall}`);
      } catch (err) {
        box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>巡检失败</h4><p>${esc(err.message)}</p></div>`;
        toast(err.message, "err");
      } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = `${icon("pulse")}立即巡检`; }
      }
    }

    function renderCanary(view) {
      leave();
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left"><button class="btn sm primary" id="canary-run">${icon("pulse")}立即巡检</button></div>
          <div class="right"><span class="side">只读：健康 / 登录 / 调度 / 审批 / 备份</span></div>
        </div>
        <div id="canary-body"><div class="skeleton" style="height:220px"></div></div>
        <p class="hint-text">巡检会真实调用 Dashboard、B站/抖音插件状态和记忆状态，但不发送消息、不点写操作、不改配置。</p>`;
      view.querySelector("#canary-run").addEventListener("click", () => loadCanary(view, true));
      loadCanary(view);
    }

    function leave() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    return { renderAlerts, renderDrift, renderMatrix, renderResources, renderCanary, leave };
  }

  return { create, fmtTime, severityClass };
});
