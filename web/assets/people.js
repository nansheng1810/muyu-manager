/* 牧鱼 · 人物档案 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerPeople = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STAGES = [
    ["stranger", "陌生"],
    ["familiar", "熟悉"],
    ["close", "亲近"],
  ];

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtDate(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let instId = "";
    let viewEl = null;
    let items = [];
    let selectedId = "";
    let keyword = "";
    let stageFilter = "";
    let milestones = [];
    let loading = false;

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];

    function stageLabel(stage) {
      const found = STAGES.find(([key]) => key === stage);
      return found ? found[1] : stage || "陌生";
    }

    function filtered() {
      const text = keyword.trim().toLowerCase();
      return items.filter((item) => {
        if (stageFilter && item.stage !== stageFilter) return false;
        if (!text) return true;
        const blob = [
          item.display_name, item.nickname, item.person_key,
          (item.aliases || []).join(" "), (item.traits || []).join(" "),
          (item.tags || []).join(" "), item.likes, item.dislikes,
          item.boundaries, item.notes,
        ].join(" ").toLowerCase();
        return blob.includes(text);
      });
    }

    function rowHtml(item) {
      const active = String(item.id) === String(selectedId);
      return `
        <button class="ins-row ${active ? "on" : ""}" data-person="${esc(item.id)}">
          <div class="ins-row-top">
            <b>${esc(item.nickname || item.display_name || item.person_key || "未知")}</b>
            <span class="badge ${item.stage === "close" ? "ok" : item.stage === "familiar" ? "accent" : ""}">${esc(stageLabel(item.stage))}</span>
          </div>
          <div class="ins-row-sub">${esc(item.display_name || "—")} · ${Number(item.message_count) || 0} 条消息</div>
          <div class="ins-row-foot">${esc(item.platform || "")} · ${esc(fmtDate(item.last_seen))}</div>
        </button>`;
    }

    function listHtml() {
      const rows = filtered();
      return `
        <div class="ins-side-head"><h3>人物档案</h3><span>${rows.length} / ${items.length}</span></div>
        <div class="ins-list">${rows.length
          ? rows.map(rowHtml).join("")
          : `<div class="ins-hint" style="margin:12px">还没有档案。机器人观察群聊后会自动建立关系档案。</div>`}</div>`;
    }

    function detailHtml(item) {
      const aliases = (item.aliases || []).join("，");
      const traits = (item.traits || []).join("，");
      const tags = (item.tags || []).join("，");
      const milestoneHtml = milestones.length
        ? milestones.map((ms) => `
            <div class="people-ms">
              <div><b>${esc(ms.title || "")}</b><span>${esc(fmtDate(ms.occurred_at))}</span></div>
              <p>${esc(ms.detail || "")}</p>
            </div>`).join("")
        : `<div class="ins-hint">还没有里程碑。</div>`;
      return `
        <div class="ins-detail-head">
          <div>
            <h3>${esc(item.nickname || item.display_name || item.person_key)}</h3>
            <p>${esc(item.platform || "")} · ${esc(item.person_key || "")} · 最后互动 ${esc(fmtDate(item.last_seen))}</p>
          </div>
          <div class="ins-badges">
            <span class="badge accent">${esc(stageLabel(item.stage))}</span>
            <span class="badge">熟悉度 ${Number(item.familiarity || 0).toFixed(1)}</span>
            <span class="badge">好感 ${Number(item.affection || 0).toFixed(1)}</span>
            <span class="badge">怒气 ${Number(item.anger || 0).toFixed(1)}</span>
          </div>
        </div>

        <section class="ins-sec">
          <h4>档案</h4>
          <div class="people-grid">
            <div class="field"><label>称呼（机器人怎么叫对方）</label><input type="text" maxlength="40" data-pf="display_name" value="${esc(item.display_name || "")}"></div>
            <div class="field"><label>常用昵称</label><input type="text" maxlength="40" data-pf="nickname" value="${esc(item.nickname || "")}"></div>
            <div class="field"><label>关系阶段</label><select data-pf="stage">${STAGES.map(([key, label]) => `<option value="${key}" ${item.stage === key ? "selected" : ""}>${label}</option>`).join("")}</select></div>
            <div class="field"><label>别名（逗号分隔）</label><input type="text" data-pf-list="aliases" value="${esc(aliases)}" placeholder="小明，阿明"></div>
            <div class="field"><label>性格（逗号分隔）</label><input type="text" data-pf-list="traits" value="${esc(traits)}" placeholder="话多，爱开玩笑"></div>
            <div class="field"><label>标签（逗号分隔）</label><input type="text" data-pf-list="tags" value="${esc(tags)}" placeholder="夜猫子，车队常客"></div>
          </div>
          <div class="people-grid">
            <div class="field"><label>喜欢</label><textarea rows="3" maxlength="500" data-pf="likes" placeholder="篮球、烧烤、深夜聊天">${esc(item.likes || "")}</textarea></div>
            <div class="field"><label>不喜欢</label><textarea rows="3" maxlength="500" data-pf="dislikes" placeholder="被催、被刷屏">${esc(item.dislikes || "")}</textarea></div>
            <div class="field"><label>雷区（别主动提）</label><textarea rows="3" maxlength="500" data-pf="boundaries" placeholder="前任、工作压力">${esc(item.boundaries || "")}</textarea></div>
            <div class="field"><label>最近印象</label><textarea rows="3" maxlength="300" data-pf="recent_summary" placeholder="最近总在凌晨出现，爱发表情包">${esc(item.recent_summary || "")}</textarea></div>
          </div>
          <div class="field"><label>备注</label><textarea rows="3" maxlength="2000" data-pf="notes">${esc(item.notes || "")}</textarea></div>
          <div class="people-switches">
            <label class="gd-switch"><input type="checkbox" data-pf-bool="allow_memory" ${item.allow_memory ? "checked" : ""}><span>允许记忆（关闭后不注入昵称与档案）</span></label>
            <label class="gd-switch"><input type="checkbox" data-pf-bool="followup_enabled" ${item.followup_enabled ? "checked" : ""}><span>允许话题回访</span></label>
          </div>
          <div class="people-actions">
            <button class="btn sm" id="people-save">${icon("check")}保存档案</button>
            <span class="ins-hint">改动会立刻影响下一次回复注入。</span>
          </div>
        </section>

        <section class="ins-sec">
          <h4>里程碑</h4>
          ${milestoneHtml}
        </section>`;
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
          ${list.map((item) => `<button class="chip ${String(item.id) === String(instId) ? "on" : ""}" data-people-inst="${esc(item.id)}">${esc(item.name || item.id)}</button>`).join("")}
          <button class="btn sm ghost" id="people-refresh" style="margin-left:auto">${icon("refresh")}刷新</button>
        </div>
        <div class="ins-toolbar">
          <div class="field" style="margin:0;flex:1 1 240px">
            <label>搜索</label>
            <input type="search" id="people-search" placeholder="搜昵称、别名、标签、备注" value="${esc(keyword)}">
          </div>
          <div class="field" style="margin:0;min-width:120px">
            <label>关系阶段</label>
            <select id="people-stage">
              <option value="">全部</option>
              ${STAGES.map(([key, label]) => `<option value="${key}" ${stageFilter === key ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="ins-layout">
          <section class="card ins-side" id="people-list"></section>
          <section class="card ins-detail" id="people-detail">
            <div class="ins-placeholder">${icon("memory")}<p>从左侧选一个人，查看并编辑他的档案。</p></div>
          </section>
        </div>`;
      view.querySelectorAll("[data-people-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.peopleInst;
          selectedId = "";
          render(view);
        });
      });
      view.querySelector("#people-refresh").addEventListener("click", () => load(true));
      const search = view.querySelector("#people-search");
      search.addEventListener("input", () => {
        keyword = search.value;
        paintList();
      });
      view.querySelector("#people-stage").addEventListener("change", (event) => {
        stageFilter = event.target.value;
        paintList();
      });
      load();
    }

    function paintList() {
      const box = viewEl && viewEl.querySelector("#people-list");
      if (!box) return;
      box.innerHTML = listHtml();
      box.querySelectorAll("[data-person]").forEach((row) => {
        row.addEventListener("click", () => {
          selectedId = row.dataset.person;
          paintList();
          loadDetail();
        });
      });
    }

    async function load(force) {
      if (!instId || loading) return;
      loading = true;
      try {
        items = await api(`/api/presence/relations?instance_id=${encodeURIComponent(instId)}&limit=300`);
        if (!Array.isArray(items)) items = [];
        if (!viewEl || !viewEl.isConnected) return;
        paintList();
        if (!selectedId && items.length) {
          selectedId = String(items[0].id);
          paintList();
        }
        loadDetail();
      } catch (err) {
        const box = viewEl && viewEl.querySelector("#people-list");
        if (box) {
          box.innerHTML = `<div class="empty" style="padding:20px">${icon("alert")}<h4>读取档案失败</h4><p>${esc(err.message || "")}</p></div>`;
        }
      } finally {
        loading = false;
      }
    }

    async function loadDetail() {
      const box = viewEl && viewEl.querySelector("#people-detail");
      if (!box) return;
      const item = items.find((row) => String(row.id) === String(selectedId));
      if (!item) {
        box.innerHTML = `<div class="ins-placeholder">${icon("memory")}<p>从左侧选一个人。</p></div>`;
        return;
      }
      milestones = [];
      try {
        const rows = await api(
          `/api/presence/milestones?instance_id=${encodeURIComponent(instId)}&platform=${encodeURIComponent(item.platform || "")}&person_key=${encodeURIComponent(item.person_key || "")}&limit=20`,
        );
        milestones = Array.isArray(rows) ? rows : [];
      } catch (err) {
        milestones = [];
      }
      box.innerHTML = detailHtml(item);
      const save = box.querySelector("#people-save");
      if (save) save.addEventListener("click", () => saveProfile(item));
    }

    async function saveProfile(item) {
      const box = viewEl && viewEl.querySelector("#people-detail");
      if (!box) return;
      const payload = {};
      box.querySelectorAll("[data-pf]").forEach((input) => {
        payload[input.dataset.pf] = input.value;
      });
      box.querySelectorAll("[data-pf-list]").forEach((input) => {
        payload[input.dataset.pfList] = input.value
          .split(/[，,\s]+/)
          .map((value) => value.trim())
          .filter(Boolean);
      });
      box.querySelectorAll("[data-pf-bool]").forEach((input) => {
        payload[input.dataset.pfBool] = input.checked;
      });
      try {
        const updated = await api(
          `/api/presence/relations/${encodeURIComponent(item.id)}`,
          { method: "PATCH", body: payload },
        );
        const index = items.findIndex((row) => String(row.id) === String(item.id));
        if (index >= 0 && updated) items[index] = updated;
        toast("人物档案已保存");
        paintList();
        loadDetail();
      } catch (err) {
        toast(err.message || "保存失败");
      }
    }

    return { render };
  }

  return { create, fmtDate };
});
