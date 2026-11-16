/* 牧鱼 · 用量与成本中心 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerCost = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    let days = 30;

    function num(value) {
      return Number(value || 0).toLocaleString("zh-CN");
    }

    function money(value, currency = "CNY") {
      const symbol = currency === "USD" ? "$" : "¥";
      return `${symbol}${Number(value || 0).toFixed(2)}`;
    }

    function summary(data) {
      const totals = data.totals || {};
      const tokens = (totals.input || 0) + (totals.cached || 0) + (totals.output || 0);
      const cards = [
        ["总 Token", num(tokens), `${data.days} 天`],
        ["调用次数", num(totals.calls), "次模型请求"],
        ["估算费用", money(totals.cost, data.currency), `${num(totals.input)} 输入 / ${num(totals.output)} 输出`],
        ["今日费用", money((data.today || {}).cost, data.currency), `本月 ${money((data.month || {}).cost, data.currency)}`],
      ];
      return `<div class="auto-summary-grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">
        ${cards.map((item) => `<div class="auto-summary"><div class="k">${esc(item[0])}</div>
          <div class="v">${esc(item[1])}</div><div class="hint-text" style="margin:4px 0 0">${esc(item[2])}</div></div>`).join("")}
      </div>`;
    }

    function alertsHtml(data) {
      const alerts = data.alerts || [];
      if (!alerts.length) return "";
      return `<div class="auto-list" style="margin-bottom:12px">${alerts.map((item) => `<article class="auto-row">
        <div class="auto-main"><div class="auto-title">
          <strong>${esc(item.title)}</strong>
          <span class="badge ${item.level === "bad" ? "bad" : "warn"}">${item.level === "bad" ? "超限" : "提醒"}</span>
        </div><p class="approval-reason">${esc(item.detail)}</p></div>
      </article>`).join("")}</div>`;
    }

    function bars(data) {
      const items = data.by_day || [];
      if (!items.length) {
        return `<div class="empty" style="padding:26px">${icon("model")}<h4>还没有调用记录</h4><p>机器人开始对话后，这里会按天显示 token 用量。</p></div>`;
      }
      const max = Math.max(...items.map((item) => (item.input || 0) + (item.cached || 0) + (item.output || 0)), 1);
      return `<div style="display:flex;align-items:flex-end;gap:4px;height:120px;padding:8px 4px;overflow-x:auto">
        ${items.map((item) => {
          const total = (item.input || 0) + (item.cached || 0) + (item.output || 0);
          const height = Math.max(3, Math.round(total / max * 100));
          return `<div title="${esc(item.date)} · ${num(total)} token · ${money(item.cost, data.currency)}"
            style="flex:1;min-width:10px;height:${height}%;background:var(--accent);border-radius:4px;opacity:.8"></div>`;
        }).join("")}
      </div>
      <div class="auto-meta" style="display:flex;justify-content:space-between">
        <span>${esc(items[0].date)}</span><span>${esc(items[items.length - 1].date)}</span>
      </div>`;
    }

    function modelRows(data) {
      const items = data.by_model || [];
      if (!items.length) return `<div class="empty" style="padding:20px">暂无模型用量</div>`;
      return `<div class="auto-list">${items.map((item) => `<article class="auto-row">
        <div class="auto-main"><div class="auto-title"><strong>${esc(item.model)}</strong>
          <span class="badge">${num(item.calls)} 次</span></div>
          <div class="auto-meta"><span>输入 <b>${num(item.input)}</b></span><span>缓存 <b>${num(item.cached)}</b></span>
            <span>输出 <b>${num(item.output)}</b></span><span>费用 <b>${money(item.cost, data.currency)}</b></span></div>
        </div></article>`).join("")}</div>`;
    }

    function instanceRows(data) {
      const items = data.by_instance || [];
      if (!items.length) return "";
      return `<div class="auto-list">${items.map((item) => `<article class="auto-row">
        <div class="auto-main"><div class="auto-title"><strong>${esc(item.name)}</strong>
          <span class="badge">${num(item.calls)} 次</span></div>
          <div class="auto-meta"><span>Token <b>${num((item.input || 0) + (item.cached || 0) + (item.output || 0))}</b></span>
            <span>费用 <b>${money(item.cost, data.currency)}</b></span></div></div>
      </article>`).join("")}</div>`;
    }

    function configHtml(config, data) {
      const prices = config.prices || {};
      const models = (data.models || []).slice();
      const rows = models.map((model) => {
        const item = prices[model] || {};
        return `<tr data-price-row data-model="${esc(model)}">
          <td>${esc(model)}</td>
          <td><input class="input" data-price="input" type="number" min="0" step="0.01" value="${esc(item.input ?? 0)}"></td>
          <td><input class="input" data-price="cached" type="number" min="0" step="0.01" value="${esc(item.cached ?? 0)}"></td>
          <td><input class="input" data-price="output" type="number" min="0" step="0.01" value="${esc(item.output ?? 0)}"></td>
        </tr>`;
      }).join("");
      const wildcard = prices["*"] || {};
      return `<div class="card" style="margin-top:14px">
        <div class="section-head" style="margin:0 0 10px"><h2>价格与预算</h2>
          <span class="side">单价：${esc(config.currency || "CNY")} / 百万 token</span></div>
        <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:10px">
          <label class="hint-text">每日预算（0 表示不提醒）<input class="input" id="cost-daily" type="number" min="0" step="0.01" value="${esc((config.budget || {}).daily ?? 0)}"></label>
          <label class="hint-text">每月预算<input class="input" id="cost-monthly" type="number" min="0" step="0.01" value="${esc((config.budget || {}).monthly ?? 0)}"></label>
          <label class="hint-text">未匹配模型的默认单价<input class="input" id="cost-star" type="number" min="0" step="0.01" value="${esc(wildcard.output ?? 0)}" title="用作输入与输出单价"></label>
        </div>
        <table class="table" style="width:100%;border-collapse:collapse">
          <thead><tr><th style="text-align:left">模型</th><th>输入价</th><th>缓存价</th><th>输出价</th></tr></thead>
          <tbody id="cost-price-body">${rows || `<tr><td colspan="4" class="hint-text">暂无模型记录，先让机器人聊几句。</td></tr>`}</tbody>
        </table>
        <div class="auto-toolbar" style="margin-top:10px"><div class="left">
          <button class="btn sm primary" id="cost-save">${icon("check")}保存设置</button>
        </div><div class="right hint-text">费用为估算值，以供应商账单为准</div></div>
      </div>`;
    }

    async function load(view) {
      const box = view.querySelector("#cost-body");
      if (!box) return;
      box.innerHTML = `<div class="skeleton" style="height:260px"></div>`;
      try {
        const [data, config] = await Promise.all([
          api(`/api/cost?days=${days}`),
          api("/api/cost/config"),
        ]);
        if (!view.isConnected) return;
        box.innerHTML = `${alertsHtml(data)}${summary(data)}
          <div class="card" style="margin-top:14px">
            <div class="section-head" style="margin:0 0 10px"><h2>每日 Token</h2><span class="side">按天聚合，含缓存命中</span></div>
            ${bars(data)}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px">
            <div class="card"><div class="section-head" style="margin:0 0 10px"><h2>按模型</h2></div>${modelRows(data)}</div>
            <div class="card"><div class="section-head" style="margin:0 0 10px"><h2>按实例</h2></div>
              ${instanceRows(data) || `<div class="empty" style="padding:20px">暂无实例数据</div>`}</div>
          </div>
          ${configHtml(config, data)}`;
        view.querySelector("#cost-save")?.addEventListener("click", async () => {
          const prices = {};
          box.querySelectorAll("[data-price-row]").forEach((row) => {
            const model = row.dataset.model;
            const item = {};
            row.querySelectorAll("[data-price]").forEach((input) => {
              item[input.dataset.price] = input.value === "" ? 0 : Number(input.value);
            });
            prices[model] = item;
          });
          const star = Number(view.querySelector("#cost-star").value || 0);
          prices["*"] = { input: star, cached: star, output: star };
          try {
            await api("/api/cost/config", {
              method: "PUT",
              body: {
                prices,
                budget: {
                  daily: Number(view.querySelector("#cost-daily").value || 0),
                  monthly: Number(view.querySelector("#cost-monthly").value || 0),
                },
              },
            });
            toast("成本设置已保存");
            load(view);
          } catch (err) { toast(err.message, "err"); }
        });
      } catch (err) {
        if (!view.isConnected) return;
        box.innerHTML = `<div class="empty" style="padding:26px">${icon("alert")}<h4>读取用量失败</h4><p>${esc(err.message)}</p></div>`;
      }
    }

    function render(view) {
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left" style="display:flex;gap:8px;align-items:center">
            <select class="input" id="cost-days" style="width:120px">
              <option value="7">近 7 天</option>
              <option value="30" selected>近 30 天</option>
              <option value="90">近 90 天</option>
            </select>
            <button class="btn sm ghost" id="cost-refresh">${icon("refresh")}刷新</button>
          </div>
          <div class="right"><span class="side">读取各实例 provider_stats，不额外调用模型</span></div>
        </div>
        <div id="cost-body"><div class="skeleton" style="height:260px"></div></div>
        <p class="hint-text">Token 来自 AstrBot 的 provider_stats；单价按「元 / 百万 token」填写，留空或 0 不计费。</p>`;
      const select = view.querySelector("#cost-days");
      days = Number(select.value || 30);
      select.addEventListener("change", () => { days = Number(select.value || 30); load(view); });
      view.querySelector("#cost-refresh")?.addEventListener("click", () => load(view));
      load(view);
    }

    function leave() {}

    return { render, leave };
  }

  return { create };
});
