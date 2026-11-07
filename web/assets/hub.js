/* 牧鱼 · 功能分组总览（信息架构整合页） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerHub = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { esc, icon, routes } = ctx;

    function cardHtml(item) {
      const list = typeof routes === "function" ? routes() : routes || {};
      const meta = list[item.route] || {};
      return `
        <a class="hub-card" href="#/${esc(item.route)}">
          <span class="hub-icon">${icon(item.icon || "model")}</span>
          <span class="hub-card-text">
            <b>${esc(item.label || meta.title || item.route)}</b>
            <p>${esc(item.desc || meta.sub || "")}</p>
          </span>
          <span class="hub-arrow">›</span>
        </a>`;
    }

    function render(view, hub) {
      const groups = (hub && hub.groups) || [];
      view.innerHTML = `
        <div class="hub-hero">
          <h2>${esc((hub && hub.title) || "功能总览")}</h2>
          <p>${esc((hub && hub.desc) || "同类功能已经合并到这里，点卡片直接进入。")}</p>
        </div>
        <div class="hub-groups">
          ${groups.map((group) => `
            <section class="hub-group">
              <div class="hub-group-head">
                <h3>${esc(group.name)}</h3>
                ${group.desc ? `<p>${esc(group.desc)}</p>` : ""}
              </div>
              <div class="hub-cards">${(group.items || []).map(cardHtml).join("")}</div>
            </section>`).join("")}
        </div>`;
    }

    return { render };
  }

  return { create };
});
