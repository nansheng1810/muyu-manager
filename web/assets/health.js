/* 牧鱼 · 舰队健康（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerHealth = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STATUS_LABEL = { ok: "正常", warn: "警告", bad: "异常" };
  const STATUS_CLASS = { ok: "ok", warn: "warn", bad: "bad" };

  function statusLabel(value) {
    return STATUS_LABEL[value] || "未知";
  }

  function overallClass(value) {
    return STATUS_CLASS[value] || "warn";
  }

  function summarize(components) {
    const rows = Array.isArray(components) ? components : [];
    const counts = { ok: 0, warn: 0, bad: 0, other: 0, total: rows.length };
    for (const row of rows) {
      const status = row && row.status;
      if (status === "ok" || status === "warn" || status === "bad") counts[status] += 1;
      else counts.other += 1;
    }
    return counts;
  }

  function formatGenerated(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds <= 0) return "—";
    const date = new Date(seconds * 1000);
    const pad = (number) => String(number).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    let token = 0;

    function panelHtml(data) {
      const components = Array.isArray(data?.components) ? data.components : [];
      const counts = summarize(components);
      const overall = overallClass(data?.overall);
      const rows = components.map((row) => {
        const status = STATUS_CLASS[row.status] || "warn";
        const route = String(row.route || "");
        const content = `
          <span class="fleet-health-dot ${status}"></span>
          <span class="fleet-health-name">${esc(row.label || row.id || "组件")}</span>
          <span class="fleet-health-summary">${esc(row.summary || "")}</span>
          <span class="fleet-health-state ${status}">${esc(statusLabel(row.status))}</span>
          ${route ? `<span class="fleet-health-arrow">›</span>` : ""}`;
        return route
          ? `<button type="button" class="fleet-health-row" data-health-route="${esc(route)}">${content}</button>`
          : `<div class="fleet-health-row">${content}</div>`;
      }).join("");
      return `<section class="card fleet-health">
        <div class="fleet-health-head">
          <div>
            <div class="fleet-health-kicker">FLEET HEALTH</div>
            <h2>舰队健康</h2>
            <p>只读巡检 · ${esc(formatGenerated(data?.generated_at))} · ${esc(data?.cache_seconds || 5)} 秒缓存</p>
          </div>
          <div class="fleet-health-actions">
            <span class="fleet-health-overall ${overall}">${esc(statusLabel(data?.overall))}</span>
            <button type="button" class="btn sm ghost" data-health-refresh>${icon("refresh")}刷新</button>
          </div>
        </div>
        <div class="fleet-health-counts">
          <span class="ok">正常 ${counts.ok}</span>
          <span class="warn">警告 ${counts.warn}</span>
          <span class="bad">异常 ${counts.bad}</span>
          <span class="dim">共 ${counts.total} 项</span>
        </div>
        <div class="fleet-health-list">${rows || `<div class="fleet-health-empty">没有返回组件。</div>`}</div>
      </section>`;
    }

    function wire(view) {
      const box = view.querySelector("#fleet-health");
      if (!box) return;
      const refresh = box.querySelector("[data-health-refresh]");
      if (refresh) {
        refresh.addEventListener("click", () => load(view, true));
      }
      box.querySelectorAll("[data-health-route]").forEach((row) => {
        row.addEventListener("click", () => {
          const route = row.dataset.healthRoute;
          if (route) location.hash = route;
        });
      });
    }

    async function load(view, force = false) {
      const box = view.querySelector("#fleet-health");
      if (!box) return;
      const current = ++token;
      box.innerHTML = `<section class="card fleet-health"><div class="skeleton" style="height:120px"></div></section>`;
      try {
        const data = await api(`/api/health/fleet${force ? "?force=1" : ""}`);
        if (current !== token || !box.isConnected) return;
        box.innerHTML = panelHtml(data);
        wire(view);
      } catch (error) {
        if (current !== token || !box.isConnected) return;
        box.innerHTML = `<section class="card fleet-health fleet-health-error">
          <div class="fleet-health-head"><div><div class="fleet-health-kicker">FLEET HEALTH</div><h2>舰队健康</h2>
          <p>${esc(error.message || "读取失败")}</p></div>
          <button type="button" class="btn sm ghost" data-health-refresh>${icon("refresh")}重试</button></div>
        </section>`;
        wire(view);
      }
    }

    return {
      renderFleet(view) {
        if (!view || !view.querySelector("#fleet-health")) return;
        load(view);
      },
      async refresh(view) {
        await load(view, true);
      },
    };
  }

  return { create, statusLabel, overallClass, summarize, formatGenerated };
});
