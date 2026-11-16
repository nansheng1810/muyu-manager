/* 牧鱼 · NapCat 概率回复：普通模式群聊插件的读空气概率 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerNapcatProbability = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    const confirm = typeof ctx.confirmDialog === "function" ? ctx.confirmDialog : async () => true;
    let viewEl = null;
    let instances = [];
    let rows = {};
    let loading = false;

    const badge = (ok, text) => `<span class="badge ${ok ? "ok" : "warn"}">${esc(text)}</span>`;

    function ratio(value, fallback) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function pctText(value, fallback) {
      return Math.round(ratio(value, fallback) * 10000) / 100;
    }

    function intro() {
      return `
        <section class="card">
          <h3>${icon("bots")}NapCat 普通模式概率回复</h3>
          <p class="help">这里只管普通模式：AstrBot 群聊插件 <code>astrbot_plugin_group_chat_plus</code> 的读空气概率。Agent 模式开启时会暂停默认 LLM，本页配置只在 Agent 模式关闭或未接管时生效。</p>
          <p class="help">与「Agent 概率」完全分开，互不同步。开启「动态概率」后插件会按发言频率自动调整初始概率，手动设置的 2% 可能被覆盖，想要固定 2% 建议关闭动态概率。</p>
          <div class="sl-actions">
            <button class="btn sm ghost" data-act="refresh">${icon("refresh")}重新读取</button>
            <a class="btn sm ghost" href="#/probability">${icon("pulse")}去管理 Agent 概率</a>
          </div>
        </section>`;
    }

    function fields(row) {
      const config = row.config || {};
      const allowed = row.allowed || [];
      const parts = [];
      if (allowed.includes("initial_probability")) {
        parts.push(`
          <div class="field">
            <label>初始接话概率（%）</label>
            <input class="np-initial" type="number" min="0" max="100" step="0.5" value="${pctText(config.initial_probability, 0.02)}">
            <span class="help">AI 初始判断是否接话的概率。2% 表示平均每条消息有 2% 机会触发读空气。</span>
          </div>`);
      }
      if (allowed.includes("after_reply_probability")) {
        parts.push(`
          <div class="field">
            <label>回复后的接话概率（%）</label>
            <input class="np-after" type="number" min="0" max="100" step="0.5" value="${pctText(config.after_reply_probability, 0.8)}">
            <span class="help">传统模式下，成功回复后短时间内的概率。</span>
          </div>`);
      }
      if (allowed.includes("probability_duration")) {
        parts.push(`
          <div class="field">
            <label>概率提升持续时间（秒）</label>
            <input class="np-duration" type="number" min="0" max="86400" step="10" value="${Math.round(ratio(config.probability_duration, 120))}">
            <span class="help">回复后临时提升概率的持续时间。</span>
          </div>`);
      }
      if (allowed.includes("enable_dynamic_reply_probability")) {
        const checked = config.enable_dynamic_reply_probability === true ? "checked" : "";
        parts.push(`
          <div class="field">
            <label>动态调整概率</label>
            <label style="display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text)">
              <input class="np-dynamic" type="checkbox" ${checked}> 让插件按发言频率自动调整初始概率
            </label>
            <span class="help">开启后会覆盖手动设置；固定 2% 请取消勾选。</span>
          </div>`);
      }
      if (!parts.length) {
        return `<p class="sl-error">当前群聊插件没有可写的概率配置（白名单为空）。请确认已安装并启用 astrbot_plugin_group_chat_plus。</p>`;
      }
      return `<div class="row">${parts.join("")}</div>`;
    }

    function instanceCard(inst) {
      const row = rows[inst.id] || {};
      const head = `
        <div class="sl-head">
          <h3>${icon("bots")}${esc(inst.name || inst.id)}
            ${row.error ? badge(false, "读取失败") : (row.loaded ? badge(true, "已读取") : badge(false, "读取中"))}
          </h3>
          <span class="sl-muted">${esc(inst.id)}</span>
        </div>`;
      if (row.error) {
        return `<section class="card">${head}<p class="sl-error">${esc(row.error)}</p>
          <div class="sl-actions"><button class="btn sm ghost" data-act="retry" data-inst="${esc(inst.id)}">重试</button></div></section>`;
      }
      if (!row.loaded) {
        return `<section class="card">${head}<p class="sl-muted">正在读取群聊插件配置…</p></section>`;
      }
      return `
        <section class="card">
          ${head}
          ${fields(row)}
          <div class="sl-actions">
            <button class="btn sm primary" data-act="save" data-inst="${esc(inst.id)}">${icon("check")}保存到该实例</button>
          </div>
        </section>`;
    }

    function paint() {
      if (!viewEl) return;
      viewEl.innerHTML = intro() + (instances.length
        ? instances.map(instanceCard).join("")
        : `<div class="empty">${icon("alert")}<h4>没有可用实例</h4><p>请先在「机器人」里新增实例。</p></div>`);
    }

    async function loadInstance(inst) {
      rows[inst.id] = { loaded: false, error: "", allowed: [], config: {} };
      try {
        const data = await api(`/api/reply-probability/napcat?instance_id=${encodeURIComponent(inst.id)}`);
        rows[inst.id] = {
          loaded: true,
          error: "",
          allowed: Array.isArray(data.allowed_keys) ? data.allowed_keys : [],
          config: data.config && typeof data.config === "object" ? data.config : {},
        };
      } catch (err) {
        rows[inst.id] = { loaded: false, error: err.message, allowed: [], config: {} };
      }
    }

    async function loadAll() {
      if (loading) return;
      loading = true;
      try {
        instances = await api("/api/instances");
        if (!Array.isArray(instances)) instances = [];
        rows = {};
        paint();
        for (const inst of instances) {
          await loadInstance(inst);
          paint();
        }
      } catch (err) {
        toast(`实例读取失败：${err.message}`, "err");
        if (viewEl && !instances.length) {
          viewEl.innerHTML = intro() + `<div class="empty">${icon("alert")}<h4>实例读取失败</h4><p>${esc(err.message)}</p></div>`;
        }
      } finally {
        loading = false;
      }
    }

    async function save(inst) {
      const row = rows[inst.id];
      if (!row || !row.loaded) return;
      const card = viewEl.querySelector(`[data-inst="${inst.id}"]`)?.closest(".card");
      if (!card) return;
      const allowed = row.allowed || [];
      const config = {};
      const readPct = (selector) => {
        const input = card.querySelector(selector);
        if (!input) return null;
        const value = Number(input.value);
        if (!Number.isFinite(value) || value < 0 || value > 100) {
          throw new Error("概率需在 0–100 之间");
        }
        return Math.round((value / 100) * 10000) / 10000;
      };
      try {
        if (allowed.includes("initial_probability")) {
          const value = readPct(".np-initial");
          if (value !== null) config.initial_probability = value;
        }
        if (allowed.includes("after_reply_probability")) {
          const value = readPct(".np-after");
          if (value !== null) config.after_reply_probability = value;
        }
        if (allowed.includes("probability_duration")) {
          const input = card.querySelector(".np-duration");
          const value = Number(input && input.value);
          if (!Number.isFinite(value) || value < 0 || value > 86400) {
            throw new Error("持续时间需在 0–86400 秒之间");
          }
          config.probability_duration = Math.round(value);
        }
        if (allowed.includes("enable_dynamic_reply_probability")) {
          const input = card.querySelector(".np-dynamic");
          config.enable_dynamic_reply_probability = Boolean(input && input.checked);
        }
        if (!Object.keys(config).length) return toast("没有可保存的字段", "warn");
        if (!(await confirm("保存 NapCat 概率", `会写入「${inst.name || inst.id}」的群聊插件配置，立即生效。继续？`))) return;
        await api("/api/reply-probability/napcat", {
          method: "POST",
          body: { instance_id: inst.id, config, confirm: true },
        });
        toast("NapCat 接话概率已保存", "ok");
        await loadInstance(inst);
        paint();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function bind(view) {
      view.addEventListener("click", (event) => {
        const button = event.target.closest("[data-act]");
        if (!button) return;
        const act = button.dataset.act;
        if (act === "refresh") return loadAll();
        if (act === "retry") {
          const inst = instances.find((item) => item.id === button.dataset.inst);
          if (!inst) return;
          rows[inst.id] = { loaded: false, error: "", allowed: [], config: {} };
          paint();
          return loadInstance(inst).then(paint);
        }
        if (act === "save") {
          const inst = instances.find((item) => item.id === button.dataset.inst);
          if (inst) return save(inst);
        }
      });
    }

    function render(view) {
      viewEl = view;
      if (!viewEl.dataset.npBound) {
        viewEl.dataset.npBound = "1";
        bind(view);
      }
      paint();
      loadAll();
    }

    function leave() {
      /* 本页无定时器 */
    }

    return { render, leave };
  }

  return { create };
});
