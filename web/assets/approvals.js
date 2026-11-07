/* 牧鱼 · 审批队列（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerApprovals = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const CATEGORY_LABEL = {
    bili_write: "B站写入",
    douyin_write: "抖音写入",
    dsh_action: "DSH 动作",
    manager_action: "管理器动作",
    other: "其它",
  };
  const STATUS_LABEL = {
    pending: "待审批",
    approved: "已批准",
    denied: "已拒绝",
    expired: "已过期",
    cancelled: "已取消",
  };

  function categoryLabel(value) {
    return CATEGORY_LABEL[value] || "其它";
  }

  function statusLabel(value) {
    return STATUS_LABEL[value] || "未知";
  }

  function fmtTime(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds <= 0) return "—";
    const date = new Date(seconds * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    let timer = null;
    let status = "pending";
    let items = [];
    let loadToken = 0;

    function payloadPreview(payload) {
      if (!payload || typeof payload !== "object") return "";
      const text = JSON.stringify(payload);
      return text.length > 180 ? text.slice(0, 180) + "…" : text;
    }

    function rowHtml(item, actionable) {
      const statusCls = item.status === "pending" ? "warn" : item.status === "approved" ? "ok" : "bad";
      return `<article class="approval-row">
        <div class="approval-main">
          <div class="approval-title">
            <strong>${esc(item.title || "未命名审批")}</strong>
            <span class="badge ${statusCls}">${esc(statusLabel(item.status))}</span>
            <span class="badge">${esc(categoryLabel(item.category))}</span>
          </div>
          <div class="approval-meta">
            ${item.target ? `<span>目标 <b>${esc(item.target)}</b></span>` : ""}
            <span>发起 <b>${esc(item.requested_by || "—")}</b></span>
            <span>创建 <b>${esc(fmtTime(item.created))}</b></span>
            <span>过期 <b>${esc(fmtTime(item.expires_at))}</b></span>
          </div>
          ${item.reason ? `<p class="approval-reason">${esc(item.reason)}</p>` : ""}
          ${payloadPreview(item.payload) ? `<code class="approval-payload">${esc(payloadPreview(item.payload))}</code>` : ""}
        </div>
        ${actionable ? `<div class="approval-actions">
          <button class="btn sm primary" data-approve="${esc(item.id)}">批准</button>
          <button class="btn sm danger" data-deny="${esc(item.id)}">拒绝</button>
        </div>` : ""}
      </article>`;
    }

    function listHtml() {
      if (!items.length) {
        return `<div class="empty" style="padding:30px">${icon("check")}<h4>没有待处理审批</h4><p>插件写操作会先进入这里，批准后才执行。</p></div>`;
      }
      return `<div class="approval-list">${items.map((item) =>
        rowHtml(item, item.status === "pending")).join("")}</div>`;
    }

    async function load(view, silent = false) {
      const token = ++loadToken;
      if (!silent) {
        const box = view.querySelector("#approval-list");
        if (box) box.innerHTML = `<div class="skeleton" style="height:180px"></div>`;
      }
      try {
        const data = await api(`/api/approvals?status=${encodeURIComponent(status)}&limit=100`);
        if (token !== loadToken || !view.isConnected) return;
        items = Array.isArray(data) ? data : [];
        const box = view.querySelector("#approval-list");
        if (box) box.innerHTML = listHtml();
        wire(view);
      } catch (err) {
        if (token !== loadToken || !view.isConnected) return;
        const box = view.querySelector("#approval-list");
        if (box) box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
        if (!silent) toast(err.message, "err");
      }
    }

    function wire(view) {
      view.querySelectorAll("[data-approve]").forEach((btn) =>
        btn.addEventListener("click", () => decide(view, btn.dataset.approve, "approve")));
      view.querySelectorAll("[data-deny]").forEach((btn) =>
        btn.addEventListener("click", () => decide(view, btn.dataset.deny, "deny")));
    }

    async function decide(view, id, action) {
      const buttons = view.querySelectorAll("[data-approve],[data-deny]");
      buttons.forEach((btn) => { btn.disabled = true; });
      try {
        await api(`/api/approvals/${encodeURIComponent(id)}/${action}`, { method: "POST", body: {} });
        toast(action === "approve" ? "已批准，写操作可继续执行" : "已拒绝，写操作不会执行");
        await load(view, true);
      } catch (err) {
        toast(err.message, "err");
        buttons.forEach((btn) => { btn.disabled = false; });
      }
    }

    function render(view) {
      leave();
      view.innerHTML = `
        <div class="section-head" style="margin-top:0">
          <h2>审批队列</h2>
          <div class="side">写操作先入队，批准后才执行</div>
        </div>
        <div class="approval-toolbar">
          <div class="chips">
            <button class="chip ${status === "pending" ? "active" : ""}" data-approval-status="pending">待审批</button>
            <button class="chip ${status === "all" ? "active" : ""}" data-approval-status="all">全部</button>
          </div>
          <button class="btn sm ghost" id="approval-refresh">${icon("refresh")}刷新</button>
        </div>
        <div id="approval-list"><div class="skeleton" style="height:180px"></div></div>
        <p class="hint-text">审批默认 30 分钟过期；拒绝或过期都不会执行写操作。插件需要开启 approval_mode 才会入队。</p>`;
      view.querySelectorAll("[data-approval-status]").forEach((btn) =>
        btn.addEventListener("click", () => {
          status = btn.dataset.approvalStatus;
          view.querySelectorAll("[data-approval-status]").forEach((node) =>
            node.classList.toggle("active", node === btn));
          load(view);
        }));
      view.querySelector("#approval-refresh").addEventListener("click", () => load(view));
      load(view);
      timer = setInterval(() => {
        if (view.isConnected) load(view, true);
      }, 10000);
    }

    function leave() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    return { render, leave, refresh: (view) => load(view) };
  }

  return { create, categoryLabel, statusLabel, fmtTime };
});
