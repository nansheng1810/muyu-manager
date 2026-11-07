/* 牧鱼 · 看图接话 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerVision = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();
    const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
    return sameDay ? clock : `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${clock}`;
  }

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let instId = "";
    let viewEl = null;
    let data = null;
    let filter = "all";
    let selectedId = "";
    let loading = false;

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];

    function items() {
      return (data && data.items) || [];
    }

    function visibleItems() {
      const rows = items();
      if (filter === "described") return rows.filter((item) => item.description);
      if (filter === "auto") return rows.filter((item) => item.auto_reply);
      return rows;
    }

    function statHtml() {
      const stats = (data && data.stats) || {};
      return `
        <div class="meme-stats">
          <div class="meme-stat"><b>${stats.total || 0}</b><span>已收图片</span></div>
          <div class="meme-stat"><b>${stats.described || 0}</b><span>已生成描述</span></div>
          <div class="meme-stat accent"><b>${stats.auto_replies || 0}</b><span>主动接话</span></div>
          <div class="meme-stat"><b>${stats.today || 0}</b><span>今天</span></div>
        </div>`;
    }

    function thumb(item) {
      if (!item.url) return `<span class="vision-noimg">${icon("model")}</span>`;
      return `<img class="vision-thumb" src="${esc(item.url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`;
    }

    function rowHtml(item) {
      const active = String(item.id) === String(selectedId);
      return `
        <button class="vision-row ${active ? "on" : ""}" data-vision="${esc(item.id)}">
          ${thumb(item)}
          <span class="vision-row-main">
            <b>${esc(item.sender_name || item.sender_id || "未知")}</b>
            <span class="vision-row-text">${esc(item.description || item.caption || "还没有描述")}</span>
            <span class="vision-row-foot">
              <span class="mono">${esc(fmtTime(item.ts))}</span>
              ${item.auto_reply ? `<span class="badge accent">接话</span>` : ""}
              ${item.description ? "" : `<span class="badge">待描述</span>`}
            </span>
          </span>
        </button>`;
    }

    function detailHtml(item) {
      return `
        <div class="ins-detail-head">
          <div>
            <h3>${esc(item.sender_name || item.sender_id || "未知发送者")}</h3>
            <p>${esc(fmtTime(item.ts))} · 群 ${esc(item.group_id || "—")} · ${esc(item.sender_id || "")}</p>
          </div>
          <div class="ins-badges">
            ${item.description ? `<span class="badge ok">已描述</span>` : `<span class="badge">未描述</span>`}
            ${item.auto_reply ? `<span class="badge accent">主动接话</span>` : ""}
          </div>
        </div>
        <section class="ins-sec vision-preview">
          ${item.url
            ? `<a class="vision-big" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer"><img src="${esc(item.url)}" alt="" referrerpolicy="no-referrer"></a>`
            : `<div class="ins-hint">这条记录没有图片地址。</div>`}
        </section>
        <section class="ins-sec">
          <h4>模型看到的画面</h4>
          <div class="ins-plain">${esc(item.description || "还没有描述。插件会在收到图片后调用视觉模型生成 40 字描述。")}</div>
        </section>
        ${item.caption ? `<section class="ins-sec"><h4>随图附言</h4><div class="ins-quote">${esc(item.caption)}</div></section>` : ""}
        ${item.reply_text ? `<section class="ins-sec"><h4>机器人接话</h4><div class="ins-quote"><b>它当时说</b>${esc(item.reply_text)}</div></section>` : ""}
        <div class="people-actions">
          <span class="ins-hint" style="margin:0">删掉后就只影响管理器展示，图片仍留在插件记录里。</span>
          <button class="btn sm ghost" id="vision-delete" style="margin-left:auto">${icon("trash")}删除记录</button>
        </div>`;
    }

    function settingsHtml() {
      const s = (data && data.settings) || {};
      const probability = Number(s.probability);
      return `
        <details class="life-settings" ${data && data.stats && data.stats.total ? "" : "open"}>
          <summary>${icon("settings")}看图接话设置<span>改动下一次收到图片时生效</span></summary>
          <div class="gd-grid">
            <label class="gd-switch"><input type="checkbox" data-vs="enabled" ${s.enabled ? "checked" : ""}><span>启用看图</span></label>
            <label class="gd-switch"><input type="checkbox" data-vs="inject" ${s.inject ? "checked" : ""}><span>把画面描述注入对话</span></label>
            <label class="gd-switch"><input type="checkbox" data-vs="auto_reply" ${s.auto_reply ? "checked" : ""}><span>允许主动接图</span></label>
            <div class="field" style="margin:0"><label>主动接话概率（0-1）</label><input type="number" min="0" max="1" step="0.05" data-vs="probability" value="${Number.isFinite(probability) ? probability : 0.15}"></div>
            <div class="field" style="margin:0"><label>每小时最多接几次</label><input type="number" min="0" max="100" data-vs="hourly_limit" value="${s.hourly_limit ?? 3}"></div>
            <div class="field" style="margin:0"><label>描述字数上限</label><input type="number" min="20" max="400" step="10" data-vs="max_chars" value="${s.max_chars ?? 90}"></div>
            <div class="field" style="margin:0"><label>视觉模型 Provider ID（可留空）</label><input type="text" maxlength="60" data-vs="provider_id" value="${esc(s.provider_id || "")}" placeholder="留空则用当前对话模型"></div>
          </div>
          <div class="field"><label>只在哪些群看图（每行一个群号，留空=所有群）</label><textarea rows="3" data-vs="groups" placeholder="123456789">${esc((s.groups || []).join("\n"))}</textarea></div>
          <button class="btn sm" id="vision-settings-save">${icon("check")}保存设置</button>
        </details>`;
    }

    function render(view) {
      viewEl = view;
      const list = instances();
      if (!list.length) {
        view.innerHTML = `<div class="empty" style="padding:40px">${icon("bots")}<h4>没有实例</h4><p>先在「机器人」里添加一个实例。</p></div>`;
        return;
      }
      if (!list.some((item) => String(item.id) === String(instId))) {
        instId = String(list[0].id);
      }
      view.innerHTML = `
        <div class="gd-bar">
          ${list.map((item) => `<button class="chip ${String(item.id) === String(instId) ? "on" : ""}" data-vision-inst="${esc(item.id)}">${esc(item.name || item.id)}</button>`).join("")}
          <button class="btn sm ghost" id="vision-refresh" style="margin-left:auto">${icon("refresh")}刷新</button>
        </div>
        <div id="vision-stats"></div>
        <div class="ins-toolbar">
          <div class="meme-tabs">
            <button class="chip ${filter === "all" ? "on" : ""}" data-vision-filter="all">全部</button>
            <button class="chip ${filter === "described" ? "on" : ""}" data-vision-filter="described">已描述</button>
            <button class="chip ${filter === "auto" ? "on" : ""}" data-vision-filter="auto">主动接话</button>
          </div>
        </div>
        <div class="ins-layout" id="vision-body">
          <section class="card ins-side" id="vision-list"></section>
          <section class="card ins-detail" id="vision-detail">
            <div class="ins-placeholder">${icon("model")}<p>从左侧点一张图，查看模型看到了什么、它当时怎么接话。</p></div>
          </section>
        </div>
        <div id="vision-form"></div>`;
      view.querySelectorAll("[data-vision-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.visionInst;
          selectedId = "";
          render(view);
        });
      });
      view.querySelectorAll("[data-vision-filter]").forEach((chip) => {
        chip.addEventListener("click", () => {
          filter = chip.dataset.visionFilter;
          paint();
        });
      });
      view.querySelector("#vision-refresh").addEventListener("click", () => load(true));
      load();
    }

    function paintSettings() {
      const form = viewEl && viewEl.querySelector("#vision-form");
      if (!form) return;
      form.innerHTML = settingsHtml();
      const save = form.querySelector("#vision-settings-save");
      if (save) save.addEventListener("click", saveSettings);
    }

    function paint() {
      const stats = viewEl && viewEl.querySelector("#vision-stats");
      const listBox = viewEl && viewEl.querySelector("#vision-list");
      if (stats) stats.innerHTML = statHtml();
      if (viewEl) {
        viewEl.querySelectorAll("[data-vision-filter]").forEach((chip) => {
          chip.classList.toggle("on", chip.dataset.visionFilter === filter);
        });
      }
      if (!listBox) return;
      const rows = visibleItems();
      listBox.innerHTML = `
        <div class="ins-side-head"><h3>图片记录</h3><span>${rows.length} 张</span></div>
        <div class="ins-list">${rows.length
          ? rows.map(rowHtml).join("")
          : `<div class="ins-hint" style="padding:14px">还没有图片记录。插件收到群图片后会先让视觉模型看一遍。</div>`}</div>`;
      listBox.querySelectorAll("[data-vision]").forEach((row) => {
        row.addEventListener("click", () => {
          selectedId = row.dataset.vision;
          paint();
          paintDetail();
        });
      });
      paintDetail();
    }

    function paintDetail() {
      const box = viewEl && viewEl.querySelector("#vision-detail");
      if (!box) return;
      const item = items().find((row) => String(row.id) === String(selectedId));
      if (!item) {
        box.innerHTML = `<div class="ins-placeholder">${icon("model")}<p>从左侧选一条记录查看详情。</p></div>`;
        return;
      }
      box.innerHTML = detailHtml(item);
      const remove = box.querySelector("#vision-delete");
      if (remove) remove.addEventListener("click", () => deleteItem(item));
    }

    async function load(force) {
      if (!instId || loading) return;
      loading = true;
      const listBox = viewEl && viewEl.querySelector("#vision-list");
      if (listBox && (force || !data)) {
        listBox.innerHTML = `<div class="skeleton" style="height:220px"></div>`;
      }
      try {
        data = await api(`/api/instances/${encodeURIComponent(instId)}/vision?limit=60`);
        if (!viewEl || !viewEl.isConnected) return;
        paint();
        paintSettings();
      } catch (err) {
        if (listBox) {
          listBox.innerHTML = `<div class="empty" style="padding:20px">${icon("alert")}<h4>读取看图记录失败</h4><p>${esc(err.message || "")}</p></div>`;
        }
      } finally {
        loading = false;
      }
    }

    async function deleteItem(item) {
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/vision/${encodeURIComponent(item.id)}`, {
          method: "DELETE",
        });
        selectedId = "";
        toast("已从管理器删除");
        load(true);
      } catch (err) {
        toast(err.message || "删除失败");
      }
    }

    async function saveSettings() {
      const form = viewEl && viewEl.querySelector("#vision-form");
      if (!form) return;
      const payload = {};
      form.querySelectorAll("[data-vs]").forEach((input) => {
        const key = input.dataset.vs;
        if (input.type === "checkbox") payload[key] = input.checked;
        else if (key === "groups") payload[key] = input.value.split(/[\n,，]/).map((x) => x.trim()).filter(Boolean);
        else if (input.type === "number") payload[key] = Number(input.value) || 0;
        else payload[key] = input.value.trim();
      });
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/vision/settings`, {
          method: "PATCH",
          body: payload,
        });
        toast("看图设置已保存");
        load(true);
      } catch (err) {
        toast(err.message || "保存失败");
      }
    }

    return { render };
  }

  return { create, fmtTime };
});
