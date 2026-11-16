/* 牧鱼 · 每日心情 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerMood = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MOOD_LABEL = { calm: "平静", happy: "开心", low: "低落", annoyed: "烦躁", angry: "生气" };
  const MOOD_COLOR = { calm: "#63B7A4", happy: "#D8A25E", low: "#7C8FA6", annoyed: "#C9866B", angry: "#B65C5C" };
  const MOOD_SOURCE = { daily_reset: "每日重置", conversation: "对话", manual: "手动" };
  const ERROR_TOAST_GAP_MS = 30000;

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    let instances = [];
    let instId = "";
    let status = null;
    let providers = [];
    let timer = null;
    let lastErrorAt = 0;

    function bar(label, value) {
      const pct = Math.max(0, Math.min(100, Number(value) || 0));
      return `<div class="mood-bar"><span>${esc(label)}</span>
        <div class="mood-track"><i style="width:${pct}%"></i></div><b>${pct.toFixed(0)}</b></div>`;
    }

    function moodColor(mood) { return MOOD_COLOR[mood] || MOOD_COLOR.calm; }

    function relationRows(relations) {
      if (!relations.length) return `<div class="empty-inline">还没有关系记录，等机器人收到私聊或 @ 后出现。</div>`;
      return relations.map((r) => `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(r.display_name || r.person_key)}</strong>
            <span class="badge">${esc(r.platform)}</span></div>
          <div class="auto-meta"><span>怒气 ${Math.round(r.anger)}</span>
            <span>好感 ${Math.round(r.affection)}</span>
            <span>熟悉度 ${Math.round(r.familiarity)}</span>
            <span>${r.last_seen ? new Date(r.last_seen * 1000).toLocaleString() : "—"}</span></div>
        </div>
        <button class="btn sm ghost" data-reset-platform="${esc(r.platform)}" data-reset-person="${esc(r.person_key)}">重置</button>
      </article>`).join("");
    }

    function eventRows(events) {
      if (!events.length) return `<div class="empty-inline">今天还没有模型评估。</div>`;
      return events.map((e) => {
        const a = e.assessment || {};
        const before = (e.before || {}).state || {};
        const after = (e.after || {}).state || {};
        const beforeLabel = MOOD_LABEL[before.mood] || before.mood || "—";
        const afterLabel = MOOD_LABEL[after.mood] || after.mood || "—";
        return `<article class="mood-event">
          <div class="mood-event-head">
            <strong>${esc(afterLabel)}</strong>
            <span>${esc(beforeLabel)} → ${esc(afterLabel)} · ${Math.round(e.assessment?.latency_ms || 0)}ms</span>
            <span>${e.created ? new Date(e.created * 1000).toLocaleTimeString() : ""}</span>
          </div>
          <p>${esc(a.reason || e.error || "无评估")}</p>
          ${a.tone_hint ? `<p class="mood-hint">语气：${esc(a.tone_hint)}</p>` : ""}
          ${e.error && e.assessment && Object.keys(e.assessment).length ? `<p class="mood-error">${esc(e.error)}</p>` : ""}
        </article>`;
      }).join("");
    }

    function paint(view) {
      if (!status) return;
      const s = status.state || {};
      const box = view.querySelector("#mood-state");
      if (box) {
        box.style.setProperty("--mood-color", moodColor(s.mood));
        box.innerHTML = `
          <div class="mood-now">
            <div class="mood-now-label">${esc(MOOD_LABEL[s.mood] || s.mood || "—")}</div>
            <div class="mood-now-meta">${esc(MOOD_SOURCE[s.source] || s.source || "")} · ${esc(status.state?.date || "")}</div>
          </div>
          ${bar("强度", s.intensity)}${bar("精力", s.energy)}${bar("社交电量", s.social)}
          <div class="mood-meta">重置时刻 ${status.reset_hour}:00 · 今日评估 ${status.today_events} 条</div>`;
      }
      const rel = view.querySelector("#mood-relations");
      if (rel) rel.innerHTML = relationRows(status.relations || []);
      const ev = view.querySelector("#mood-events");
      if (ev) ev.innerHTML = eventRows(status.events || []);
      const sliders = { intensity: s.intensity, energy: s.energy, social: s.social };
      Object.keys(sliders).forEach((key) => {
        const input = view.querySelector(`#mood-${key}`);
        if (input && document.activeElement !== input) {
          input.value = Math.round(sliders[key] || 0);
          const out = view.querySelector(`#mood-${key}-v`);
          if (out) out.textContent = input.value;
        }
      });
      const moodSelect = view.querySelector("#mood-manual-mood");
      if (moodSelect && document.activeElement !== moodSelect) moodSelect.value = s.mood || "calm";
      const resetHour = view.querySelector("#mood-reset-hour");
      if (resetHour && document.activeElement !== resetHour) {
        resetHour.value = status.settings?.reset_hour ?? 5;
      }
      const toggle = view.querySelector("#mood-enabled");
      if (toggle && document.activeElement !== toggle) toggle.checked = !!status.settings?.mood_enabled;
    }

    function setInlineError(view, message) {
      const el = view.querySelector("#mood-error");
      if (!el) return;
      el.textContent = message || "";
      el.hidden = !message;
    }

    async function refresh(view) {
      if (!instId) return;
      try {
        status = await api(`/api/mood/status?instance_id=${encodeURIComponent(instId)}`);
      } catch (err) {
        setInlineError(view, `心情状态读取失败：${err.message}`);
        const now = Date.now();
        if (view.isConnected && now - lastErrorAt >= ERROR_TOAST_GAP_MS) {
          lastErrorAt = now;
          toast(err.message, "err");
        }
        return;
      }
      setInlineError(view, "");
      paint(view);
    }

    async function loadProviders(view) {
      const select = view.querySelector("#mood-provider");
      if (!select) return;
      try {
        const data = await api(`/api/instances/${instId}/providers`);
        providers = data.providers || [];
        const current = status?.settings?.provider_id || data.current || "";
        select.innerHTML = `<option value="">跟随实例默认（${esc(data.current || "未设置")}）</option>` +
          providers.map((p) => `<option value="${esc(p.id)}">${esc(p.id)} · ${esc(p.model || "")}</option>`).join("");
        select.value = providers.some((p) => p.id === current) ? current : "";
      } catch (err) {
        select.innerHTML = `<option value="">读取失败：${esc(err.message)}</option>`;
      }
    }

    function applyBehavior(view, s) {
      if (!s) return;
      // 轮询/刷新回填时跳过用户正在操作的控件，避免把正在输入的值改回旧值。
      const set = (id, prop, value) => {
        const el = view.querySelector(`#${id}`);
        if (!el || document.activeElement === el) return;
        el[prop] = value;
      };
      set("mood-enabled", "checked", !!s.mood_enabled);
      set("mood-reset-hour", "value", s.reset_hour ?? 5);
      set("mood-silence", "checked", !!s.silence_enabled);
      set("mood-silence-prob", "value", s.silence_probability ?? 0.08);
      set("mood-silence-limit", "value", s.silence_daily_limit ?? 2);
      set("mood-delay-ms", "value", s.max_delay_ms ?? 3000);
    }

    async function loadBehavior(view) {
      // 先用 /api/mood/status 的 settings 回填，保证拟人状态接口就绪前行为参数也有值。
      applyBehavior(view, status?.settings);
      try {
        const data = await api(`/api/human/status?instance_id=${encodeURIComponent(instId)}`);
        applyBehavior(view, data.settings || {});
      } catch (_) {
        // /api/human/status 在拟人行为批次就绪前可能不存在；不影响心情页主体。
      }
    }

    // app 的 api() 只透出 message、丢了 HTTP 状态码：只有 404/未找到才算接口未注册，
    // 400/500 属于真实保存失败，必须继续抛出，不能吞掉后退回 /api/mood/settings。
    function isMissingEndpoint(err) {
      if (!err) return false;
      if (err.status === 404) return true;
      const message = String(err.message || "");
      return /HTTP 404|not\s*found/i.test(message) || message.includes("未找到");
    }

    async function load(view) {
      instances = await api("/api/instances");
      if (!instances.length) {
        view.innerHTML = `<div class="empty">${icon("alert")}<h4>没有可用实例</h4><p>请先新增或接入机器人。</p></div>`;
        return;
      }
      const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(instances);
      if (focusHit) instId = String(focusHit.id);
      else if (!instId || !instances.some((x) => x.id === instId)) instId = ((globalThis.ManagerFocus && globalThis.ManagerFocus.pick(instances)) || instances[0]).id;
      const select = view.querySelector("#mood-inst");
      select.innerHTML = instances.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("");
      select.value = instId;
      await refresh(view);
      await loadProviders(view);
      await loadBehavior(view);
    }

    function render(view) {
      leave();
      view.innerHTML = `
        <div class="card">
          <div class="section-head" style="margin:0 0 12px">
            <h2>每日心情</h2><span class="side">每天定时重置；对话会改变状态</span>
          </div>
          <div class="field"><label>机器人</label><select id="mood-inst"></select></div>
          <div id="mood-error" class="mood-inline-error" hidden></div>
          <div id="mood-state"><div class="skeleton" style="height:120px"></div></div>
        </div>
        <div class="human-grid">
          <div class="card"><div class="section-head"><h2>手动修正</h2></div>
            <div class="field"><label>心情</label><select id="mood-manual-mood">
              <option value="calm">平静</option><option value="happy">开心</option>
              <option value="low">低落</option><option value="annoyed">烦躁</option>
              <option value="angry">生气</option></select></div>
            ${["intensity", "energy", "social"].map((k) => `
              <div class="field"><label>${k === "intensity" ? "强度" : k === "energy" ? "精力" : "社交电量"}
                <b id="mood-${k}-v"></b></label>
                <input id="mood-${k}" type="range" min="0" max="100" step="1"></div>`).join("")}
            <div class="human-actions">
              <button class="btn primary" id="mood-apply">应用手动值</button>
              <button class="btn ghost" id="mood-reset">重置今日心情</button>
            </div>
          </div>
          <div class="card"><div class="section-head"><h2>心情设置</h2></div>
            <label class="check-row"><input type="checkbox" id="mood-enabled"> 启用每日心情</label>
            <div class="field"><label>重置时刻</label><input id="mood-reset-hour" type="number" min="0" max="23" value="5"></div>
            <div class="field"><label>评估模型</label><select id="mood-provider"></select></div>
            <div class="human-actions"><button class="btn primary" id="mood-save">保存设置</button></div>
            <div class="field"><label>沉默概率</label><input id="mood-silence-prob" type="number" min="0" max="1" step="0.01"></div>
            <div class="field"><label>每天最多沉默</label><input id="mood-silence-limit" type="number" min="0" max="20"></div>
            <div class="field"><label>最大延迟（毫秒）</label><input id="mood-delay-ms" type="number" min="0" max="4000"></div>
            <label class="check-row"><input type="checkbox" id="mood-silence"> 允许真实沉默</label>
            <div class="human-actions"><button class="btn ghost" id="mood-save-behavior">保存行为参数</button></div>
          </div>
        </div>
        <div class="card" style="margin-top:16px">
          <div class="section-head"><h2>关系态度</h2><span class="side">怒气/好感不会每天清零，只缓慢回落</span></div>
          <div id="mood-relations"><div class="skeleton" style="height:80px"></div></div>
        </div>
        <div class="card" style="margin-top:16px">
          <div class="section-head"><h2>实时评估</h2><span class="side">每 2 秒刷新；只显示结论，不显示思维链</span></div>
          <div id="mood-events"><div class="skeleton" style="height:80px"></div></div>
        </div>`;
      bind(view);
      load(view).catch((err) => toast(err.message, "err"));
      timer = setInterval(() => refresh(view), 2000);
    }

    function bind(view) {
      view.querySelector("#mood-inst").addEventListener("change", async (e) => {
        instId = e.target.value;
        status = null;
        await load(view);
      });
      ["intensity", "energy", "social"].forEach((k) => {
        view.querySelector(`#mood-${k}`).addEventListener("input", (e) => {
          view.querySelector(`#mood-${k}-v`).textContent = e.target.value;
        });
      });
      view.querySelector("#mood-apply").addEventListener("click", async () => {
        try {
          await api("/api/mood/adjust", { method: "POST", body: {
            instance_id: instId,
            scope: "global",
            mood: view.querySelector("#mood-manual-mood").value,
            intensity: Number(view.querySelector("#mood-intensity").value),
            energy: Number(view.querySelector("#mood-energy").value),
            social: Number(view.querySelector("#mood-social").value),
          }});
          toast("已更新心情"); await refresh(view);
        } catch (err) { toast(err.message, "err"); }
      });
      view.querySelector("#mood-reset").addEventListener("click", async () => {
        try {
          await api("/api/mood/reset", { method: "POST", body: { instance_id: instId, scope: "global" } });
          toast("已重置今日心情"); await refresh(view);
        } catch (err) { toast(err.message, "err"); }
      });
      view.querySelector("#mood-relations").addEventListener("click", async (e) => {
        const btn = e.target.closest("[data-reset-platform]");
        if (!btn) return;
        const platform = btn.dataset.resetPlatform;
        const personKey = btn.dataset.resetPerson;
        try {
          await api("/api/mood/reset", { method: "POST", body: {
            instance_id: instId, scope: "relation", platform, person_key: personKey } });
          toast("已重置该关系"); await refresh(view);
        } catch (err) { toast(err.message, "err"); }
      });
      view.querySelector("#mood-save").addEventListener("click", async () => {
        try {
          await api("/api/mood/settings", { method: "PUT", body: {
            instance_id: instId,
            mood_enabled: view.querySelector("#mood-enabled").checked,
            reset_hour: Number(view.querySelector("#mood-reset-hour").value),
            provider_id: view.querySelector("#mood-provider").value,
          }});
          toast("设置已保存"); await refresh(view);
        } catch (err) { toast(err.message, "err"); }
      });
      view.querySelector("#mood-save-behavior").addEventListener("click", async () => {
        const body = {
          instance_id: instId,
          silence_enabled: view.querySelector("#mood-silence").checked,
          silence_probability: Number(view.querySelector("#mood-silence-prob").value),
          silence_daily_limit: Number(view.querySelector("#mood-silence-limit").value),
          max_delay_ms: Number(view.querySelector("#mood-delay-ms").value),
        };
        try {
          try {
            await api("/api/human/settings", { method: "PUT", body });
          } catch (err) {
            // Task 5 之前 /api/human/settings 尚未注册；只有 404/未找到才退回写同一份实例设置。
            if (!isMissingEndpoint(err)) throw err;
            await api("/api/mood/settings", { method: "PUT", body });
          }
          toast("行为参数已保存");
          // 先刷新 status.settings 再回填，否则 loadBehavior 会用旧值覆盖刚保存的参数。
          await refresh(view);
          await loadBehavior(view);
        } catch (err) { toast(err.message, "err"); }
      });
    }

    function leave() {
      if (timer) { clearInterval(timer); timer = null; }
      status = null;
      providers = [];
      lastErrorAt = 0;
    }

    return { render, leave };
  }

  return { create };
});
