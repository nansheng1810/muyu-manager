/* 牧鱼 · 拟人模式：风格档案、行为设置与今日行为，不写人格 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerHuman = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const SOURCE_LABEL = { manual: "手动", auto: "自动", migration: "迁移" };
  const ACTION_LABEL = {
    reply: "回复", short: "短回复", split: "分段", delay: "延迟", silence: "沉默",
  };
  const STATUS_POLL_MS = 3000;
  // 影子汇总只统计非正常回复的行为；正常回复的影子记录不计入，否则默认影子模式下数值≈全部消息。
  const SHADOW_COUNT_KEYS = ["shadow_silence", "shadow_split", "shadow_delay", "shadow_short"];

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog } = ctx;
    let instances = [];
    let instId = "";
    let styles = [];
    let humanStatus = null;
    let humanTimer = null;

    function sourceLabel(source) {
      const key = String(source || "");
      return SOURCE_LABEL[key] || key || "未知";
    }

    function styleRow(item) {
      const enabled = !!item.enabled;
      const personText = item.scope === "relationship"
        ? `关系 ID ${esc(item.person_key || "未指定")}`
        : "全部会话";
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(item.name)}</strong>
            <span class="badge">${item.scope === "relationship" ? "关系" : "实例"}</span>
            <span class="badge">${esc(sourceLabel(item.source))}</span>
            <span class="badge ${enabled ? "ok" : ""}">${enabled ? "启用" : "停用"}</span>
          </div>
          <div class="auto-meta"><span>${personText}</span>
            <span>${esc(String(item.note || "").replace(/\s+/g, " ").slice(0, 80))}</span></div>
        </div>
        <div class="auto-actions">
          <button class="btn sm ghost" data-toggle="${esc(item.id)}">${enabled ? "停用" : "启用"}</button>
          <button class="btn sm danger" data-delete="${esc(item.id)}">${icon("trash")}</button>
        </div>
      </article>`;
    }

    function renderList(view) {
      const box = view.querySelector("#human-style-list");
      if (!box) return;
      box.innerHTML = styles.length
        ? styles.map(styleRow).join("")
        : `<div class="empty-inline">还没有风格档案。学习结果和手动新建的风格都会出现在这里。</div>`;
    }

    function renderInstances(view) {
      const select = view.querySelector("#human-inst");
      if (!select) return;
      select.innerHTML = instances
        .map((x) => `<option value="${esc(x.id)}">${esc(x.name || x.id)}</option>`)
        .join("");
      select.value = instId;
    }

    function setStatusError(view, message) {
      const el = view.querySelector("#human-status-error");
      if (!el) return;
      el.textContent = message || "";
      el.hidden = !message;
    }

    function applySettings(view, settings) {
      if (!settings || typeof settings !== "object") return;
      // 轮询回填时跳过正在编辑的控件，避免把用户输入改回旧值。
      const set = (id, prop, value) => {
        const el = view.querySelector(`#${id}`);
        if (!el || document.activeElement === el) return;
        el[prop] = value;
      };
      set("human-shadow", "checked", !!settings.shadow);
      set("human-silence", "checked", !!settings.silence_enabled);
      set("human-silence-prob", "value", settings.silence_probability ?? 0.08);
      set("human-silence-limit", "value", settings.silence_daily_limit ?? 2);
      set("human-split", "checked", !!settings.split_enabled);
      set("human-split-prob", "value", settings.split_probability ?? 0.25);
      set("human-delay", "checked", !!settings.delay_enabled);
      set("human-delay-prob", "value", settings.delay_probability ?? 0.25);
      set("human-max-delay", "value", settings.max_delay_ms ?? 3000);
    }

    function eventRows(events) {
      if (!events.length) return `<div class="empty-inline">今天还没有沉默、分段或延迟记录。</div>`;
      return events.slice(0, 20).map((e) => {
        const action = String(e.action || "");
        const label = ACTION_LABEL[action] || action || "未知行为";
        const shadow = !!e.shadow;
        const time = e.created ? new Date(Number(e.created) * 1000).toLocaleTimeString() : "—";
        return `<article class="auto-row">
          <div class="auto-main">
            <div class="auto-title"><strong>${esc(label)}</strong>
              <span class="badge ${shadow ? "warn" : "accent"}">${shadow ? "影子" : "真实"}</span>
              <span>${esc(time)}</span>
            </div>
            <div class="auto-meta"><span>${esc(e.reason || "无原因说明")}</span></div>
          </div>
        </article>`;
      }).join("");
    }

    function paintStatus(view) {
      if (!humanStatus) return;
      const settings = humanStatus.settings || {};
      const counts = humanStatus.counts || {};
      const plugin = view.querySelector("#human-plugin-state");
      if (plugin) plugin.textContent = humanStatus.plugin_active ? "插件活跃" : "最近未见插件调用";
      const shadow = view.querySelector("#human-shadow-state");
      if (shadow) shadow.textContent = settings.shadow ? "影子模式（只记录）" : "真实模式（会生效）";
      // 主人豁免是只读说明，后端缺失时仍要显示默认口径。
      const ownerNote = view.querySelector("#human-owner-note");
      if (ownerNote) ownerNote.textContent = humanStatus.owner_note || "主人/管理员永不沉默";
      const statBox = view.querySelector("#human-stats");
      if (statBox) {
        const num = (key) => Number(counts[key] || 0);
        const shadowTotal = SHADOW_COUNT_KEYS
          .reduce((sum, key) => sum + Number(counts[key] || 0), 0);
        statBox.textContent =
          `沉默 ${num("silence")} · 分段 ${num("split")} · 延迟 ${num("delay")} · ` +
          `短回复 ${num("short")} · 影子 ${shadowTotal}`;
      }
      const box = view.querySelector("#human-events");
      if (box) box.innerHTML = eventRows(Array.isArray(humanStatus.events) ? humanStatus.events : []);
    }

    async function refreshStatus(view) {
      if (!instId) return;
      const requestInst = instId;
      let data = null;
      try {
        data = await api(`/api/human/status?instance_id=${encodeURIComponent(requestInst)}`);
      } catch (err) {
        if (requestInst === instId) setStatusError(view, `行为状态读取失败：${err.message}`);
        return;
      }
      // 切换实例时丢弃旧实例的迟到响应，避免覆盖新实例状态。
      if (requestInst !== instId) return;
      humanStatus = data || {};
      setStatusError(view, "");
      applySettings(view, humanStatus.settings || {});
      paintStatus(view);
    }

    async function loadPersonas(view, instanceId) {
      const select = view.querySelector("#human-persona");
      if (!select) return;
      let list = [];
      try {
        const workbench = await api(`/api/instances/${encodeURIComponent(instanceId)}/personas/workbench`);
        list = Array.isArray(workbench.personas) ? workbench.personas : [];
      } catch (_) {
        list = [];
      }
      // 切换实例后丢弃旧实例的迟到响应，避免用旧人格列表覆盖新实例。
      if (instanceId !== instId) return;
      if (!list.length) {
        select.innerHTML = `<option value="">没有可迁移的人格</option>`;
        select.disabled = true;
        return;
      }
      select.disabled = false;
      select.innerHTML = list
        .map((p) => `<option value="${esc(p.persona_id)}">${esc(p.persona_id)}</option>`)
        .join("");
    }

    async function load(view) {
      try {
        instances = await api("/api/instances");
      } catch (err) {
        instances = [];
        toast(err.message, "err");
      }
      if (!instances.length) {
        instId = "";
        view.innerHTML = `<div class="empty">${icon("alert")}<h4>没有可用实例</h4><p>请先新增或接入机器人。</p></div>`;
        return;
      }
      if (!instId || !instances.some((x) => x.id === instId)) {
        instId = instances[0].id;
      }
      renderInstances(view);
      // 记下本次加载使用的实例；请求期间切走就丢弃 styles / personas 的迟到结果。
      const requestInst = instId;
      let list = [];
      try {
        list = await api(`/api/instances/${encodeURIComponent(requestInst)}/styles`);
      } catch (err) {
        if (requestInst === instId) toast(err.message, "err");
      }
      if (requestInst !== instId) return;
      styles = Array.isArray(list) ? list : [];
      renderList(view);
      await loadPersonas(view, requestInst);
      if (requestInst !== instId) return;
      await refreshStatus(view);
    }

    async function createStyle(view) {
      const name = view.querySelector("#human-name").value.trim();
      const note = view.querySelector("#human-note").value.trim();
      if (!name || !note) return toast("名称和内容不能为空", "err");
      const scope = view.querySelector("#human-scope").value === "relationship"
        ? "relationship" : "instance";
      const personKey = (view.querySelector("#human-person-key").value || "").trim();
      if (scope === "relationship" && !personKey) {
        return toast("关系级风格需要填写对方 ID", "err");
      }
      try {
        await api(`/api/instances/${instId}/styles`, {
          method: "POST",
          body: { name, note, scope: scope, person_key: scope === "relationship" ? personKey : "" },
        });
        view.querySelector("#human-name").value = "";
        view.querySelector("#human-note").value = "";
        view.querySelector("#human-person-key").value = "";
        toast(scope === "relationship" ? "已保存为关系级风格" : "已保存为风格档案");
        await load(view);
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function saveSettings(view) {
      const requestInst = instId;
      const shadowChecked = view.querySelector("#human-shadow").checked;
      // 从影子切到真实会让沉默/分段/延迟立刻生效，保存前必须确认用户看过今日记录。
      if (humanStatus && humanStatus.settings && humanStatus.settings.shadow && !shadowChecked) {
        const ok = await confirmDialog(
          "关闭影子模式",
          "请确认已查看今日行为记录。关闭后沉默、分段、延迟会真实生效。继续？");
        if (!ok) {
          view.querySelector("#human-shadow").checked = true;
          return;
        }
      }
      const body = {
        instance_id: requestInst,
        shadow: shadowChecked,
        silence_enabled: view.querySelector("#human-silence").checked,
        silence_probability: Number(view.querySelector("#human-silence-prob").value),
        silence_daily_limit: Number(view.querySelector("#human-silence-limit").value),
        split_enabled: view.querySelector("#human-split").checked,
        split_probability: Number(view.querySelector("#human-split-prob").value),
        delay_enabled: view.querySelector("#human-delay").checked,
        delay_probability: Number(view.querySelector("#human-delay-prob").value),
        max_delay_ms: Number(view.querySelector("#human-max-delay").value),
      };
      try {
        const saved = await api("/api/human/settings", { method: "PUT", body });
        // 保存期间切走实例时，不回填旧实例的设置。
        if (requestInst !== instId) return;
        if (humanStatus) humanStatus.settings = saved || {};
        applySettings(view, saved || {});
        // 立即刷新“影子模式/真实模式”标签，不必等下一轮轮询。
        paintStatus(view);
        toast("行为设置已保存");
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function migrate(view) {
      const select = view.querySelector("#human-persona");
      const personaId = select ? select.value : "";
      const name = view.querySelector("#human-migrate-name").value.trim() || "旧人格自动学习";
      if (!personaId) return toast("该实例没有可选人格", "err");
      const ok = await confirmDialog(
        "剥离自动学习块",
        "先保存风格档案，再从人格删除自动学习块；删除前自动快照。继续？");
      if (!ok) return;
      try {
        const data = await api(`/api/instances/${instId}/styles/migrate-persona`, {
          method: "POST",
          body: { persona_id: personaId, name },
        });
        await load(view);
        // 迁移结果写在卡片内，避免 toast 一闪而过后看不到人格精简了多少。
        const result = view.querySelector("#human-migrate-result");
        if (result) {
          const before = Number(data && data.before_chars) || 0;
          const after = Number(data && data.after_chars) || 0;
          result.textContent = `人格 ${before} → ${after} 字，风格已保存`;
          result.hidden = false;
        }
        toast("已剥离并保存为风格档案");
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function toggleStyle(view, id) {
      const item = styles.find((x) => String(x.id) === String(id));
      if (!item) return;
      try {
        await api(`/api/instances/${instId}/styles/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          body: { enabled: !item.enabled },
        });
        toast(item.enabled ? "已停用该风格" : "已启用该风格");
        await load(view);
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function deleteStyle(view, id) {
      const item = styles.find((x) => String(x.id) === String(id));
      if (!item) return;
      if (!(await confirmDialog("删除风格档案", "确定删除这条风格？"))) return;
      try {
        await api(`/api/instances/${instId}/styles/${encodeURIComponent(item.id)}`, {
          method: "DELETE",
        });
        toast("已删除风格档案");
        await load(view);
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function bind(view) {
      view.querySelector("#human-inst").addEventListener("change", async (e) => {
        instId = e.target.value;
        humanStatus = null;
        await load(view);
      });
      view.querySelector("#human-scope").addEventListener("change", (e) => {
        const relationship = e.target.value === "relationship";
        const field = view.querySelector("#human-person-key-field");
        if (field) field.hidden = !relationship;
        const key = view.querySelector("#human-person-key");
        if (key) key.disabled = !relationship;
      });
      view.querySelector("#human-create").addEventListener("click", () => createStyle(view));
      view.querySelector("#human-save-settings").addEventListener("click", () => saveSettings(view));
      view.querySelector("#human-migrate").addEventListener("click", () => migrate(view));
      view.querySelector("#human-style-list").addEventListener("click", async (e) => {
        const toggle = e.target.closest("[data-toggle]");
        if (toggle) return toggleStyle(view, toggle.dataset.toggle);
        const del = e.target.closest("[data-delete]");
        if (del) return deleteStyle(view, del.dataset.delete);
      });
    }

    function render(view) {
      leave();
      view.innerHTML = `
        <div class="card human-card">
          <div class="section-head" style="margin:0 0 10px">
            <h2>风格档案</h2><span class="side">学习结果只进这里，不改人格</span>
          </div>
          <div class="field"><label>机器人</label><select id="human-inst"></select></div>
          <div class="auto-list" id="human-style-list"><div class="skeleton" style="height:80px"></div></div>
        </div>
        <div class="human-grid">
          <div class="card">
            <div class="section-head" style="margin:0 0 10px"><h2>新建风格</h2></div>
            <div class="field"><label>名称</label><input id="human-name" type="text" placeholder="例如：大肥鱼口吻"></div>
            <div class="field"><label>作用域</label><select id="human-scope">
              <option value="instance">实例（所有会话）</option>
              <option value="relationship">关系（指定对方）</option></select></div>
            <div class="field" id="human-person-key-field" hidden><label>对方 ID</label>
              <input id="human-person-key" type="text" placeholder="QQ号或会话对方 ID" disabled></div>
            <div class="field"><label>风格内容（Markdown）</label><textarea id="human-note" rows="6"></textarea></div>
            <div class="human-actions">
              <button class="btn primary" id="human-create">保存风格档案</button>
            </div>
          </div>
          <div class="card">
            <div class="section-head" style="margin:0 0 10px"><h2>从人格剥离旧自动学习块</h2>
              <span class="side">先快照，再删除；不会自动执行</span></div>
            <p class="human-migrate-note">旧版自动学习可能把笔记写进过人格。这里会先把块内容另存为风格档案，再从人格中删除该块；删除前自动快照。</p>
            <div class="field"><label>人格</label><select id="human-persona"><option value="">加载中…</option></select></div>
            <div class="field"><label>档案名称</label><input id="human-migrate-name" type="text" value="旧人格自动学习"></div>
            <div class="human-actions">
              <button class="btn danger" id="human-migrate">剥离并保存</button>
            </div>
            <div class="hint-text" id="human-migrate-result" hidden></div>
          </div>
        </div>
        <div class="human-grid" style="margin-top:18px">
          <div class="card">
            <div class="section-head" style="margin:0 0 10px"><h2>行为设置</h2>
              <span class="side">影子模式只记录，不真正沉默或延迟</span></div>
            <label class="check-row"><input type="checkbox" id="human-shadow" checked> 影子模式</label>
            <label class="check-row"><input type="checkbox" id="human-silence"> 允许真实沉默</label>
            <div class="field"><label>沉默概率（0–1）</label>
              <input id="human-silence-prob" type="number" min="0" max="1" step="0.01" value="0.08"></div>
            <div class="field"><label>每天最多沉默</label>
              <input id="human-silence-limit" type="number" min="0" max="20" step="1" value="2"></div>
            <label class="check-row"><input type="checkbox" id="human-split" checked> 允许分段回复</label>
            <div class="field"><label>分段概率（0–1）</label>
              <input id="human-split-prob" type="number" min="0" max="1" step="0.01" value="0.25"></div>
            <label class="check-row"><input type="checkbox" id="human-delay" checked> 允许延迟回复</label>
            <div class="field"><label>延迟概率（0–1）</label>
              <input id="human-delay-prob" type="number" min="0" max="1" step="0.01" value="0.25"></div>
            <div class="field"><label>最大延迟（毫秒）</label>
              <input id="human-max-delay" type="number" min="0" max="4000" step="100" value="3000"></div>
            <div class="human-actions">
              <button class="btn primary" id="human-save-settings">保存行为设置</button>
            </div>
          </div>
          <div class="card">
            <div class="section-head" style="margin:0 0 10px"><h2>今日行为</h2>
              <span class="side">每 3 秒刷新；只显示非正常回复记录</span></div>
            <div class="auto-meta" style="margin:0 0 10px">
              <span id="human-plugin-state">读取中…</span>
              <span id="human-shadow-state">—</span>
            </div>
            <div class="hint-text" id="human-stats" style="margin:0 0 8px">今天还没有行为记录。</div>
            <div class="hint-text" id="human-owner-note">主人/管理员永不沉默</div>
            <div class="hint-text" id="human-status-error" hidden></div>
            <div class="auto-list" id="human-events"><div class="skeleton" style="height:80px"></div></div>
          </div>
        </div>`;
      bind(view);
      load(view).catch((err) => toast(err.message, "err"));
      humanTimer = setInterval(() => refreshStatus(view), STATUS_POLL_MS);
    }

    function leave() {
      if (humanTimer) { clearInterval(humanTimer); humanTimer = null; }
      styles = [];
      humanStatus = null;
    }

    return { render, leave };
  }

  return { create };
});
