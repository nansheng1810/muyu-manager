/* 牧鱼 · 连续生活线 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerLife = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function fmtDay(seconds) {
    const date = new Date(Number(seconds) * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${WEEK[date.getDay() === 0 ? 6 : date.getDay() - 1]}`;
  }

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let instId = "";
    let viewEl = null;
    let days = 7;
    let data = null;
    let loading = false;

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];

    function current() {
      return instances().find((item) => String(item.id) === String(instId)) || instances()[0] || {};
    }

    function eventHtml(event, showDelete) {
      const source = event.source === "manual"
        ? `<span class="badge accent">手动</span>`
        : `<span class="badge">节律</span>`;
      return `
        <div class="life-event" data-ts="${event.ts}">
          <b class="mono">${esc(fmtTime(event.ts))}</b>
          <span class="life-text">${esc(event.text || "")}</span>
          ${source}
          ${showDelete && event.source === "manual"
            ? `<button class="btn xs ghost life-del" data-life-del="${esc(event.id)}" title="删除">${icon("trash")}</button>`
            : ""}
        </div>`;
    }

    function dayHtml(day) {
      const items = (day.events || []).map((event) => eventHtml(event, true)).join("");
      return `
        <section class="life-day">
          <h4>${esc(fmtDay(Number(day.events[0] && day.events[0].ts) || 0))}<span>${(day.events || []).length} 件事</span></h4>
          ${items}
        </section>`;
    }

    function heroHtml() {
      const s = data.state || {};
      const energy = Math.max(0, Math.min(100, Number(s.energy) || 0));
      const updated = data.updated ? fmtTime(data.updated) : "尚未写入";
      return `
        <section class="card life-hero">
          <div class="life-hero-main">
            <div class="life-clock">
              <span>${esc(s.weekday || "—")}</span>
              <b>${esc(s.clock || "—")}</b>
            </div>
            <div class="life-now">
              <h3>${esc(s.phase_label || "还没开始生活")}</h3>
              <p>${esc(s.doing || "插件还没有上报状态，等机器人收到一条消息后就会开始。")}</p>
            </div>
          </div>
          <div class="life-energy">
            <div class="life-meter"><i style="width:${energy}%"></i></div>
            <span>精力 ${energy}/100</span>
          </div>
          <div class="life-hero-foot">
            <span>今天 ${data.today.length} 件事</span>
            <span>最近更新 ${esc(updated)}</span>
            <span class="mono">${esc(current().name || "")}</span>
          </div>
        </section>`;
    }

    function settingsHtml() {
      const s = data.settings || {};
      const daysChoices = WEEK.map((label, index) => `
        <label class="life-week ${s.weekend_days && s.weekend_days.includes(index) ? "on" : ""}">
          <input type="checkbox" data-week="${index}" ${s.weekend_days && s.weekend_days.includes(index) ? "checked" : ""}>
          ${label}
        </label>`).join("");
      const timeField = (key, label) => `
        <div class="field" style="margin:0">
          <label>${label}</label>
          <input type="time" data-life="${key}" value="${esc(s[key] || "")}">
        </div>`;
      return `
        <details class="life-settings" ${data.total ? "" : "open"}>
          <summary>${icon("settings")}生活线设置<span>这些改动会立即生效</span></summary>
          <div class="gd-grid">
            <label class="gd-switch"><input type="checkbox" data-life="enabled" ${s.enabled ? "checked" : ""}><span>启用生活线</span></label>
            <label class="gd-switch"><input type="checkbox" data-life="inject" ${s.inject ? "checked" : ""}><span>注入到对话</span></label>
            ${timeField("wake_time", "起床")}
            ${timeField("sleep_time", "睡觉")}
            ${timeField("work_start", "上班")}
            ${timeField("work_end", "下班")}
            ${timeField("lunch_start", "午休开始")}
            ${timeField("lunch_end", "午休结束")}
            <div class="field" style="margin:0">
              <label>注入字数上限</label>
              <input type="number" min="60" max="600" step="10" data-life="inject_chars" value="${esc(s.inject_chars || 140)}">
            </div>
          </div>
          <div class="life-weekline">${daysChoices}</div>
          <button class="btn sm" id="life-save">${icon("check")}保存设置</button>
        </details>`;
    }

    function render(view) {
      viewEl = view;
      const list = instances();
      if (!list.length) {
        view.innerHTML = `<div class="empty" style="padding:40px">${icon("bots")}<h4>没有实例</h4><p>先在「机器人」里添加一个实例。</p></div>`;
        return;
      }
      const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(list);
      if (focusHit) {
        instId = String(focusHit.id);
      } else if (!list.some((item) => String(item.id) === String(instId))) {
        const focused = globalThis.ManagerFocus && globalThis.ManagerFocus.pick(list);
        instId = String((focused || list[0]).id);
      }
      view.innerHTML = `
        <div class="gd-bar">
          ${list.map((item) => `<button class="chip ${String(item.id) === String(instId) ? "on" : ""}" data-life-inst="${esc(item.id)}">${esc(item.name || item.id)}</button>`).join("")}
          <button class="btn sm ghost" id="life-refresh" style="margin-left:auto">${icon("refresh")}刷新</button>
        </div>
        <div id="life-data"></div>
        <div id="life-form"></div>`;
      view.querySelectorAll("[data-life-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.lifeInst;
          render(view);
        });
      });
      view.querySelector("#life-refresh").addEventListener("click", () => load(true));
      load();
    }

    async function load(force) {
      if (!instId || loading) return;
      loading = true;
      const box = viewEl && viewEl.querySelector("#life-data");
      const form = viewEl && viewEl.querySelector("#life-form");
      if (box && (force || !data)) {
        box.innerHTML = `<div class="skeleton" style="height:260px"></div>`;
      }
      try {
        data = await api(`/api/instances/${encodeURIComponent(instId)}/life?days=${days}`);
        if (!viewEl || !viewEl.isConnected) return;
        if (box) {
          const timeline = (data.days || []).length
            ? data.days.map(dayHtml).join("")
            : `<div class="ins-hint">还没有记录。等机器人收到群消息，或手动记录一件正在做的事。</div>`;
          box.innerHTML = `
            ${heroHtml()}
            <div class="life-tools">
              <input type="text" id="life-input" maxlength="120" placeholder="手动记一件正在做的事，例如：刚打完一把游戏">
              <button class="btn sm" id="life-add">${icon("plus")}记一笔</button>
            </div>
            <section class="card life-timeline">${timeline}</section>`;
          box.querySelector("#life-add").addEventListener("click", addEvent);
          box.querySelector("#life-input").addEventListener("keydown", (event) => {
            if (event.key === "Enter") addEvent();
          });
          box.querySelectorAll("[data-life-del]").forEach((button) => {
            button.addEventListener("click", () => removeEvent(button.dataset.lifeDel));
          });
        }
        if (form) {
          form.innerHTML = settingsHtml();
          form.querySelectorAll("[data-week]").forEach((input) => {
            input.addEventListener("change", () => {
              input.closest(".life-week").classList.toggle("on", input.checked);
            });
          });
          form.querySelector("#life-save").addEventListener("click", saveSettings);
        }
      } catch (err) {
        if (box) {
          box.innerHTML = `<div class="empty" style="padding:26px">${icon("alert")}<h4>读取生活线失败</h4><p>${esc(err.message || "未知错误")}</p></div>`;
        }
      } finally {
        loading = false;
      }
    }

    async function addEvent() {
      const input = viewEl && viewEl.querySelector("#life-input");
      const text = input ? input.value.trim() : "";
      if (!text) return;
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/life/events`, {
          method: "POST",
          body: { text, kind: "manual" },
        });
        toast("已记入生活线");
        load(true);
      } catch (err) {
        toast(err.message || "记录失败");
      }
    }

    async function removeEvent(id) {
      if (!id) return;
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/life/events/${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
        toast("已删除");
        load(true);
      } catch (err) {
        toast(err.message || "删除失败");
      }
    }

    async function saveSettings() {
      const form = viewEl && viewEl.querySelector("#life-form");
      if (!form) return;
      const payload = {};
      form.querySelectorAll("[data-life]").forEach((input) => {
        const key = input.dataset.life;
        if (input.type === "checkbox") payload[key] = input.checked;
        else if (input.type === "number") payload[key] = Number(input.value) || 0;
        else payload[key] = input.value;
      });
      payload.weekend_days = [];
      form.querySelectorAll("[data-week]").forEach((input) => {
        if (input.checked) payload.weekend_days.push(Number(input.dataset.week));
      });
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/life/settings`, {
          method: "PATCH",
          body: payload,
        });
        toast("生活线设置已保存");
        load(true);
      } catch (err) {
        toast(err.message || "保存失败");
      }
    }

    return { render };
  }

  return { create, fmtTime };
});
