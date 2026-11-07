/* 牧鱼 · 群梗库 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerMemes = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let instId = "";
    let viewEl = null;
    let data = null;
    let tab = "active";
    let selectedId = "";
    let loading = false;

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];

    function statHtml() {
      const stats = data && data.stats ? data.stats : {};
      return `
        <div class="meme-stats">
          <div class="meme-stat"><b>${stats.total || 0}</b><span>正式梗</span></div>
          <div class="meme-stat"><b>${stats.active || 0}</b><span>正在注入</span></div>
          <div class="meme-stat"><b>${stats.disabled || 0}</b><span>已停用</span></div>
          <div class="meme-stat accent"><b>${stats.candidates || 0}</b><span>待确认候选</span></div>
        </div>`;
    }

    function itemRow(item) {
      const active = String(item.id) === String(selectedId);
      const status = item.status === "disabled"
        ? `<span class="badge">停用</span>`
        : `<span class="badge ok">启用</span>`;
      return `
        <button class="ins-row ${active ? "on" : ""}" data-meme="${esc(item.id)}">
          <div class="ins-row-top"><b>${esc(item.phrase)}</b>${status}</div>
          <div class="ins-row-sub">${esc(item.meaning || "还没有解释")}</div>
          <div class="ins-row-foot">${esc(item.source === "auto" ? "自动候选转入" : "手动收录")} · 出现 ${Number(item.count) || 0} 次</div>
        </button>`;
    }

    function activeHtml() {
      const rows = (data && data.all_items) || [];
      if (!rows.length) {
        return `<div class="ins-hint" style="margin:12px">还没有正式梗。可以在右侧新建，或在群里发 /梗 收录 短语 | 解释。</div>`;
      }
      return rows.map(itemRow).join("");
    }

    function candidateHtml() {
      const rows = (data && data.candidates) || [];
      if (!rows.length) {
        return `<div class="ins-hint" style="margin:12px">没有待确认的候选。机器人在群里看到反复出现的短句时会自动收集到这里。</div>`;
      }
      return rows.map((item) => `
        <div class="meme-cand">
          <div class="meme-cand-head">
            <b>${esc(item.phrase)}</b>
            <span class="badge accent">出现 ${item.count} 次</span>
            <span class="badge">${item.speakers} 人说</span>
          </div>
          <p>${esc(item.sample || "")}</p>
          <div class="meme-cand-foot">
            <span class="mono">群 ${esc(item.group_id || "—")}</span>
            <input type="text" maxlength="300" data-cand-meaning="${esc(item.phrase)}" placeholder="补一句解释（可留空）">
            <button class="btn xs" data-cand-ok="${esc(item.phrase)}" data-cand-group="${esc(item.group_id)}">${icon("check")}转正</button>
            <button class="btn xs ghost" data-cand-no="${esc(item.phrase)}">忽略</button>
          </div>
        </div>`).join("");
    }

    function detailHtml(item) {
      return `
        <div class="ins-detail-head">
          <div><h3>${esc(item.phrase)}</h3><p>${esc(item.source === "auto" ? "自动候选转入" : "手动收录")} · 出现 ${Number(item.count) || 0} 次</p></div>
          <div class="ins-badges"><span class="badge ${item.status === "active" ? "ok" : ""}">${item.status === "active" ? "启用中" : "已停用"}</span></div>
        </div>
        <section class="ins-sec">
          <div class="people-grid">
            <div class="field"><label>梗 / 短语</label><input type="text" maxlength="40" data-mf="phrase" value="${esc(item.phrase)}"></div>
            <div class="field"><label>状态</label><select data-mf="status">
              <option value="active" ${item.status === "active" ? "selected" : ""}>启用</option>
              <option value="disabled" ${item.status === "disabled" ? "selected" : ""}>停用</option>
            </select></div>
          </div>
          <div class="field"><label>解释（机器人需要知道它是什么意思）</label><textarea rows="3" maxlength="300" data-mf="meaning" placeholder="例如：说对方又在整经典活">${esc(item.meaning || "")}</textarea></div>
          <div class="field"><label>例句（可选）</label><textarea rows="2" maxlength="300" data-mf="example">${esc(item.example || "")}</textarea></div>
          <div class="people-actions">
            <button class="btn sm" id="meme-save">${icon("check")}保存</button>
            <button class="btn sm ghost" id="meme-delete" style="margin-left:auto">${icon("trash")}删除</button>
          </div>
        </section>`;
    }

    function settingsHtml() {
      const s = (data && data.settings) || {};
      return `
        <details class="life-settings" ${data && data.stats && data.stats.total ? "" : "open"}>
          <summary>${icon("settings")}群梗库设置<span>改动下一次回复生效</span></summary>
          <div class="gd-grid">
            <label class="gd-switch"><input type="checkbox" data-ms="enabled" ${s.enabled ? "checked" : ""}><span>启用群梗库</span></label>
            <label class="gd-switch"><input type="checkbox" data-ms="inject" ${s.inject ? "checked" : ""}><span>注入到对话</span></label>
            <label class="gd-switch"><input type="checkbox" data-ms="auto_capture" ${s.auto_capture ? "checked" : ""}><span>自动收集候选</span></label>
            <div class="field" style="margin:0"><label>最多注入几条</label><input type="number" min="0" max="20" data-ms="max_inject" value="${s.max_inject ?? 8}"></div>
            <div class="field" style="margin:0"><label>候选最少出现次数</label><input type="number" min="2" max="50" data-ms="min_count" value="${s.min_count ?? 4}"></div>
            <div class="field" style="margin:0"><label>候选最少发言人数</label><input type="number" min="1" max="20" data-ms="min_speakers" value="${s.min_speakers ?? 2}"></div>
            <div class="field" style="margin:0"><label>统计窗口（小时）</label><input type="number" min="1" max="720" data-ms="window_hours" value="${s.window_hours ?? 72}"></div>
          </div>
          <button class="btn sm" id="meme-settings-save">${icon("check")}保存设置</button>
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
          ${list.map((item) => `<button class="chip ${String(item.id) === String(instId) ? "on" : ""}" data-meme-inst="${esc(item.id)}">${esc(item.name || item.id)}</button>`).join("")}
          <button class="btn sm ghost" id="meme-refresh" style="margin-left:auto">${icon("refresh")}刷新</button>
        </div>
        <div id="meme-stats"></div>
        <div class="ins-toolbar">
          <div class="meme-tabs">
            <button class="chip ${tab === "active" ? "on" : ""}" data-meme-tab="active">正式梗</button>
            <button class="chip ${tab === "candidate" ? "on" : ""}" data-meme-tab="candidate">候选池</button>
          </div>
          <button class="btn sm" id="meme-new" style="margin-left:auto">${icon("plus")}新建群梗</button>
        </div>
        <div class="ins-layout" id="meme-body">
          <section class="card ins-side" id="meme-list"></section>
          <section class="card ins-detail" id="meme-detail">
            <div class="ins-placeholder">${icon("model")}<p>从左侧选一条群梗查看详情，或在右侧新建。</p></div>
          </section>
        </div>
        <div id="meme-form"></div>`;
      view.querySelectorAll("[data-meme-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.memeInst;
          selectedId = "";
          render(view);
        });
      });
      view.querySelectorAll("[data-meme-tab]").forEach((chip) => {
        chip.addEventListener("click", () => {
          tab = chip.dataset.memeTab;
          selectedId = "";
          paint();
        });
      });
      view.querySelector("#meme-refresh").addEventListener("click", () => load(true));
      view.querySelector("#meme-new").addEventListener("click", newForm);
      load();
    }

    function paintSettings() {
      const form = viewEl && viewEl.querySelector("#meme-form");
      if (!form) return;
      form.innerHTML = settingsHtml();
      const save = form.querySelector("#meme-settings-save");
      if (save) save.addEventListener("click", saveSettings);
    }

    function paint() {
      const stats = viewEl && viewEl.querySelector("#meme-stats");
      const listBox = viewEl && viewEl.querySelector("#meme-list");
      const detail = viewEl && viewEl.querySelector("#meme-detail");
      if (stats) stats.innerHTML = statHtml();
      if (viewEl) {
        viewEl.querySelectorAll("[data-meme-tab]").forEach((chip) => {
          chip.classList.toggle("on", chip.dataset.memeTab === tab);
        });
      }
      if (!listBox) return;
      if (tab === "candidate") {
        listBox.classList.add("wide");
        listBox.innerHTML = `
          <div class="ins-side-head"><h3>候选池</h3><span>${(data.candidates || []).length} 条</span></div>
          ${candidateHtml()}`;
        if (detail) {
          detail.innerHTML = `<div class="ins-placeholder">${icon("model")}<p>候选来自群里反复出现的短句。转正时补一句解释，机器人才能用对。</p></div>`;
        }
        bindCandidates();
        return;
      }
      listBox.classList.remove("wide");
      const rows = (data && data.all_items) || [];
      listBox.innerHTML = `
        <div class="ins-side-head"><h3>正式梗</h3><span>${rows.length} 条</span></div>
        <div class="ins-list">${activeHtml()}</div>`;
      listBox.querySelectorAll("[data-meme]").forEach((row) => {
        row.addEventListener("click", () => {
          selectedId = row.dataset.meme;
          paint();
          paintDetail();
        });
      });
      paintDetail();
    }

    function paintDetail() {
      const box = viewEl && viewEl.querySelector("#meme-detail");
      if (!box) return;
      const item = ((data && data.all_items) || []).find(
        (row) => String(row.id) === String(selectedId));
      if (!item) {
        box.innerHTML = `<div class="ins-placeholder">${icon("model")}<p>从左侧选一条群梗查看详情。</p></div>`;
        return;
      }
      box.innerHTML = detailHtml(item);
      const save = box.querySelector("#meme-save");
      if (save) save.addEventListener("click", () => saveItem(item));
      const remove = box.querySelector("#meme-delete");
      if (remove) remove.addEventListener("click", () => deleteItem(item));
    }

    function newForm() {
      const box = viewEl && viewEl.querySelector("#meme-detail");
      if (!box) return;
      tab = "active";
      selectedId = "";
      paint();
      box.innerHTML = `
        <div class="ins-detail-head"><div><h3>新建群梗</h3><p>收录一条群里常用的梗或口头禅</p></div></div>
        <section class="ins-sec">
          <div class="field"><label>梗 / 短语</label><input type="text" maxlength="40" data-new="phrase" placeholder="例如：典"></div>
          <div class="field"><label>解释（机器人需要知道它是什么意思）</label><textarea rows="3" maxlength="300" data-new="meaning" placeholder="例如：说对方又在整经典活"></textarea></div>
          <div class="field"><label>例句（可选）</label><textarea rows="2" maxlength="300" data-new="example" placeholder="你又在这典"></textarea></div>
          <div class="people-actions">
            <button class="btn sm" id="meme-create">${icon("plus")}收录</button>
          </div>
        </section>`;
      box.querySelector("#meme-create").addEventListener("click", createItem);
    }

    async function load(force) {
      if (!instId || loading) return;
      loading = true;
      const listBox = viewEl && viewEl.querySelector("#meme-list");
      if (listBox && (force || !data)) {
        listBox.innerHTML = `<div class="skeleton" style="height:220px"></div>`;
      }
      try {
        data = await api(`/api/instances/${encodeURIComponent(instId)}/memes`);
        if (!viewEl || !viewEl.isConnected) return;
        paint();
        paintSettings();
      } catch (err) {
        if (listBox) {
          listBox.innerHTML = `<div class="empty" style="padding:20px">${icon("alert")}<h4>读取群梗失败</h4><p>${esc(err.message || "")}</p></div>`;
        }
      } finally {
        loading = false;
      }
    }

    async function createItem() {
      const box = viewEl && viewEl.querySelector("#meme-detail");
      const payload = {};
      box.querySelectorAll("[data-new]").forEach((input) => {
        payload[input.dataset.new] = input.value.trim();
      });
      if (!payload.phrase) {
        toast("先写梗 / 短语");
        return;
      }
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/memes`, {
          method: "POST",
          body: payload,
        });
        toast("群梗已收录");
        load(true);
      } catch (err) {
        toast(err.message || "收录失败");
      }
    }

    async function saveItem(item) {
      const box = viewEl && viewEl.querySelector("#meme-detail");
      const payload = {};
      box.querySelectorAll("[data-mf]").forEach((input) => {
        payload[input.dataset.mf] = input.value.trim();
      });
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/memes/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          body: payload,
        });
        toast("群梗已保存");
        load(true);
      } catch (err) {
        toast(err.message || "保存失败");
      }
    }

    async function deleteItem(item) {
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/memes/${encodeURIComponent(item.id)}`, {
          method: "DELETE",
        });
        selectedId = "";
        toast("已删除");
        load(true);
      } catch (err) {
        toast(err.message || "删除失败");
      }
    }

    function bindCandidates() {
      const box = viewEl && viewEl.querySelector("#meme-list");
      if (!box) return;
      box.querySelectorAll("[data-cand-ok]").forEach((button) => {
        button.addEventListener("click", async () => {
          const phrase = button.dataset.candOk;
          const input = box.querySelector(`[data-cand-meaning="${CSS.escape(phrase)}"]`);
          try {
            await api(`/api/instances/${encodeURIComponent(instId)}/memes/candidates/activate`, {
              method: "POST",
              body: {
                phrase,
                meaning: input ? input.value.trim() : "",
                group_id: button.dataset.candGroup || "",
              },
            });
            toast(`已转正：${phrase}`);
            load(true);
          } catch (err) {
            toast(err.message || "转正失败");
          }
        });
      });
      box.querySelectorAll("[data-cand-no]").forEach((button) => {
        button.addEventListener("click", async () => {
          try {
            await api(`/api/instances/${encodeURIComponent(instId)}/memes/candidates/dismiss`, {
              method: "POST",
              body: { phrase: button.dataset.candNo },
            });
            toast("已忽略");
            load(true);
          } catch (err) {
            toast(err.message || "忽略失败");
          }
        });
      });
    }

    async function saveSettings() {
      const form = viewEl && viewEl.querySelector("#meme-form");
      if (!form) return;
      const payload = {};
      form.querySelectorAll("[data-ms]").forEach((input) => {
        const key = input.dataset.ms;
        if (input.type === "checkbox") payload[key] = input.checked;
        else payload[key] = Number(input.value) || 0;
      });
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/memes/settings`, {
          method: "PATCH",
          body: payload,
        });
        toast("群梗库设置已保存");
        load(true);
      } catch (err) {
        toast(err.message || "保存失败");
      }
    }

    return { render };
  }

  return { create };
});
