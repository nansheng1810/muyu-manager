/* 牧鱼 · 概率回复（Agent 模式）：群消息按概率进入 DSH / Codex 队列 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerProbability = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    let viewEl = null;
    let data = null;
    let timer = null;
    let busy = false;
    let error = "";

    const badge = (ok, text) => `<span class="badge ${ok ? "ok" : "warn"}">${esc(text)}</span>`;

    function pct(value) {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return 0;
      return Math.max(0, Math.min(100, Math.round(parsed * 100) / 100));
    }

    function fmtTime(value) {
      const ts = Number(value);
      if (!ts || !Number.isFinite(ts)) return "—";
      return new Date(ts * 1000).toLocaleTimeString();
    }

    function intro() {
      return `
        <section class="card">
          <h3>${icon("pulse")}Agent 模式概率回复</h3>
          <p class="help">这里只管 DSH / Codex 的 Agent 模式：每条群消息按设定概率抽签，只有命中的消息才会进入 Agent 会话队列。未命中的消息 Agent 完全看不到，也不会回复。</p>
          <p class="help">被 @ 到机器人时无视概率必定放行。这里的概率与 NapCat 普通模式完全分开，互不同步。</p>
          <div class="sl-actions">
            <button class="btn sm ghost" data-act="all-2">全部设为 2%</button>
            <button class="btn sm ghost" data-act="refresh">${icon("refresh")}刷新</button>
            <a class="btn sm ghost" href="#/probabilityNapcat">${icon("bots")}去管理 NapCat 概率</a>
          </div>
          ${error ? `<p class="sl-error">${esc(error)}</p>` : ""}
        </section>`;
    }

    function instanceCard(row) {
      const mode = row.agent_mode || {};
      const stats = row.stats || {};
      const running = mode.enabled ? badge(true, `运行 ${mode.runtime_status || "idle"}`) : badge(false, "未开启");
      const group = mode.group_id
        ? `${mode.group_name || mode.group_id}（${mode.group_id}）`
        : "未选择接管群";
      return `
        <section class="card">
          <div class="sl-head">
            <h3>${icon("bots")}${esc(row.name || row.id)}${badge(Boolean(row.agent), row.agent_label || "无自动 Agent")}${running}</h3>
            <span class="sl-muted">${esc(row.id)}</span>
          </div>
          <div class="kv">
            <div class="row-item"><span class="k">接管群</span><span class="v">${esc(group)}</span></div>
            <div class="row-item"><span class="k">累计入队 / 跳过</span><span class="v">${Number(stats.delivered || 0)} / ${Number(stats.dropped || 0)}</span></div>
            <div class="row-item"><span class="k">最近抽签</span><span class="v">${fmtTime(stats.last_at)}${stats.last_reason ? ` · ${esc(stats.last_reason)}` : ""}</span></div>
          </div>
          <div class="row">
            <div class="field">
              <label>Agent 回复概率（%）</label>
              <input class="rp-percent" type="number" min="0" max="100" step="1" value="${pct(row.agent_probability_pct)}">
              <span class="help">0 = 完全不进 Agent；2 = 约 2% 的群消息会被处理；100 = 全部处理（旧行为）。被 @ 始终放行。</span>
            </div>
            <div class="field">
              <label>生效方式</label>
              <span class="help">消息进入队列时抽签。统计从管理器本次启动开始累计。</span>
              <button class="btn sm primary" data-act="save" data-inst="${esc(row.id)}">${icon("check")}保存概率</button>
            </div>
          </div>
        </section>`;
    }

    function paint() {
      if (!viewEl) return;
      const instances = (data && data.instances) || [];
      viewEl.innerHTML = intro() + (instances.length
        ? instances.map(instanceCard).join("")
        : `<div class="empty">${icon("alert")}<h4>没有可用实例</h4><p>请先在「机器人」里新增实例。</p></div>`);
    }

    async function load(silent = false) {
      if (busy) return;
      busy = true;
      if (!silent && viewEl && !data) viewEl.innerHTML = `<div class="empty">${icon("refresh")}<h4>正在读取概率</h4></div>`;
      try {
        data = await api("/api/reply-probability");
        error = "";
      } catch (err) {
        error = `概率读取失败：${err.message}`;
      } finally {
        busy = false;
        paint();
      }
    }

    async function save(instId) {
      const input = viewEl.querySelector(`[data-inst="${instId}"]`)
        ? viewEl.querySelector(`[data-inst="${instId}"]`).closest(".card").querySelector(".rp-percent")
        : null;
      if (!input) return;
      const value = Number(input.value);
      if (!Number.isFinite(value) || value < 0 || value > 100) return toast("概率需在 0–100 之间", "err");
      try {
        await api("/api/reply-probability", {
          method: "POST",
          body: { instance_id: instId, agent_probability: value },
        });
        toast(`已保存：Agent 概率 ${value}%`, "ok");
        await load();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function setAll() {
      const instances = (data && data.instances) || [];
      if (!instances.length) return;
      try {
        for (const row of instances) {
          await api("/api/reply-probability", {
            method: "POST",
            body: { instance_id: row.id, agent_probability: 2 },
          });
        }
        toast("已把全部实例的 Agent 概率设为 2%", "ok");
        await load();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function bind(view) {
      view.addEventListener("click", (event) => {
        const button = event.target.closest("[data-act]");
        if (!button) return;
        const act = button.dataset.act;
        if (act === "refresh") return load();
        if (act === "all-2") return setAll();
        if (act === "save") return save(button.dataset.inst);
      });
    }

    function render(view) {
      viewEl = view;
      if (!viewEl.dataset.rpBound) {
        viewEl.dataset.rpBound = "1";
        bind(view);
      }
      paint();
      load();
      if (timer) clearInterval(timer);
      timer = setInterval(() => {
        if (document.visibilityState === "visible" && !busy) load(true);
      }, 8000);
    }

    function leave() {
      if (timer) clearInterval(timer);
      timer = null;
    }

    return { render, leave };
  }

  return { create };
});
