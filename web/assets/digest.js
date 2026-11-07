/* 牧鱼 · 舰队日报（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerDigest = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STATUS_LABEL = { ok: "正常", warn: "注意", bad: "异常" };

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function todayLocal() {
    const now = new Date();
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function fmtBytes(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) return "0 B";
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }

  function statusBadge(status) {
    const cls = status === "ok" ? "ok" : status === "bad" ? "bad" : "warn";
    return `<span class="badge ${cls}">${escSafe(STATUS_LABEL[status] || status || "未知")}</span>`;
  }

  function escSafe(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    let markdown = "";
    let loading = false;

    function listHtml(items, emptyText, renderItem) {
      if (!items || !items.length) return `<div class="empty" style="padding:18px"><p>${esc(emptyText)}</p></div>`;
      return `<div class="digest-list">${items.map(renderItem).join("")}</div>`;
    }

    function bodyHtml(data) {
      const fleet = data.fleet || {};
      const health = data.health || {};
      const approvals = data.approvals || {};
      const tasks = data.tasks || {};
      const backups = data.backups || {};
      const healthCounts = health.counts || {};
      const taskCounts = tasks.counts || {};
      const approvalItems = approvals.items || [];
      const taskItems = tasks.items || [];
      const backupItems = backups.items || [];

      return `
        <div class="auto-summary-grid">
          <div class="auto-summary"><div class="k">总体状态</div><div class="v">${esc(STATUS_LABEL[data.overall] || data.overall || "未知")}</div></div>
          <div class="auto-summary"><div class="k">机器人在线</div><div class="v">${fleet.online || 0}<small>/ ${fleet.total || 0}</small></div></div>
          <div class="auto-summary"><div class="k">待审批</div><div class="v">${approvals.pending_total || 0}<small>条</small></div></div>
          <div class="auto-summary"><div class="k">今日任务</div><div class="v">${tasks.total || 0}<small>次</small></div></div>
          <div class="auto-summary"><div class="k">今日备份</div><div class="v">${backups.total || 0}<small>份</small></div></div>
        </div>
        <div class="digest-grid">
          <div class="digest-column">
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>健康组件</h2>
                <span class="side">正常 ${healthCounts.ok || 0} · 注意 ${healthCounts.warn || 0} · 异常 ${healthCounts.bad || 0}</span></div>
              ${listHtml(health.components || [], "没有健康数据", (item) => `
                <div class="digest-item">
                  <div class="body"><b>${esc(item.label)}</b>
                    <div class="sub">${esc(item.summary)}</div></div>
                  ${statusBadge(item.status)}
                </div>`)}
            </div>
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>今日事件</h2><span class="side">${data.counts?.events || 0} 条</span></div>
              ${listHtml(data.events || [], "暂无事件", (item) => `
                <div class="digest-item">
                  <div class="time">${esc(fmtTime(item.ts))}</div>
                  <div class="body"><b>${esc(item.title)}</b>
                    <div class="sub">${esc(item.source || "")}</div></div>
                </div>`)}
            </div>
          </div>
          <div class="digest-column">
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>机器人</h2><span class="side">${fleet.online || 0} / ${fleet.total || 0} 在线</span></div>
              ${listHtml(fleet.instances || [], "未接入实例", (item) => {
                const state = item.running ? (item.dashboard_ready ? "在线" : "进程在运行，Dashboard 未就绪") : "离线";
                return `<div class="digest-item"><div class="body"><b>${esc(item.name)}</b>
                  <div class="sub">${esc(item.id)}</div></div>
                  <span class="badge ${item.running && item.dashboard_ready ? "ok" : item.running ? "warn" : "bad"}">${esc(state)}</span></div>`;
              })}
            </div>
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>审批</h2><span class="side">今日 ${approvals.total || 0} 条</span></div>
              ${listHtml(approvalItems, "今日没有审批记录", (item) => `
                <div class="digest-item"><div class="body"><b>${esc(item.title)}</b>
                  <div class="sub">${esc(item.target || "未指定目标")} · ${esc(fmtTime(item.created))}</div></div>
                  <span class="badge ${item.status === "approved" ? "ok" : item.status === "pending" ? "warn" : "bad"}">${esc(item.status)}</span></div>`)}
            </div>
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>任务运行</h2>
                <span class="side">成功 ${taskCounts.success || 0} · 失败 ${taskCounts.failed || 0}</span></div>
              ${listHtml(taskItems, "今日没有任务运行", (item) => `
                <div class="digest-item"><div class="body"><b>${esc(item.task_name)}</b>
                  <div class="sub">${esc(item.summary || "")}</div></div>
                  <span class="badge ${item.status === "success" ? "ok" : item.status === "running" ? "warn" : "bad"}">${esc(item.status)}</span></div>`)}
            </div>
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>备份</h2><span class="side">今日 ${backups.total || 0} 份</span></div>
              ${listHtml(backupItems, "今日没有备份", (item) => `
                <div class="digest-item"><div class="body"><b>${esc(item.name)}</b>
                  <div class="sub">${esc(fmtBytes(item.bytes))} · ${esc(fmtTime(item.created))}</div></div></div>`)}
            </div>
          </div>
        </div>`;
    }

    async function load(view) {
      if (loading) return;
      loading = true;
      const box = view.querySelector("#digest-body");
      const dateInput = view.querySelector("#digest-date");
      const date = dateInput?.value || todayLocal();
      if (box) box.innerHTML = `<div class="skeleton" style="height:220px"></div>`;
      try {
        const data = await api(`/api/digest?date=${encodeURIComponent(date)}&force=1`);
        if (!view.isConnected) return;
        markdown = data.markdown || "";
        if (box) box.innerHTML = bodyHtml(data);
        const meta = view.querySelector("#digest-meta");
        if (meta) meta.textContent = `生成于 ${fmtTime(data.generated_at)}`;
      } catch (err) {
        if (box) box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
        toast(err.message, "err");
      } finally {
        loading = false;
      }
    }

    function render(view) {
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left">
            <input type="date" id="digest-date" value="${todayLocal()}" style="width:auto">
            <button class="btn sm ghost" id="digest-refresh">${icon("refresh")}刷新</button>
            <button class="btn sm ghost" id="digest-copy">${icon("download")}复制 Markdown</button>
          </div>
          <div class="right"><span class="side" id="digest-meta"></span></div>
        </div>
        <div id="digest-body"><div class="skeleton" style="height:220px"></div></div>
        <p class="hint-text">日报为只读汇总：健康来自 /api/health/fleet 缓存，审批、任务与事件来自 fleet_ops.sqlite3，备份来自备份目录。</p>`;
      view.querySelector("#digest-refresh").addEventListener("click", () => load(view));
      view.querySelector("#digest-date").addEventListener("change", () => load(view));
      view.querySelector("#digest-copy").addEventListener("click", async () => {
        if (!markdown) {
          toast("日报尚未加载完成", "warn");
          return;
        }
        try {
          await navigator.clipboard.writeText(markdown);
          toast("日报 Markdown 已复制");
        } catch (_) {
          toast("复制失败，请检查浏览器剪贴板权限", "err");
        }
      });
      load(view);
    }

    function leave() {}

    return { render, leave };
  }

  return { create, todayLocal, fmtTime, fmtBytes };
});
