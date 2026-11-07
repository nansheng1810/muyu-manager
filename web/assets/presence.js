/* 牧鱼 · 活人感：话题回访、关系里程碑、生活节律、群聊读空气与自我日记 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerPresence = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const POLL_MS = 4000;
  const LEAVES = ["loops", "relations", "rhythm", "radar", "diary"];
  const LOOP_STATUS = { open: "未完成", resolved: "已解决", ignored: "已忽略" };
  const STAGE_LABEL = { stranger: "陌生", familiar: "熟悉", close: "亲近" };
  const RADAR_LABEL = { radar_reply: "接话", radar_silent: "沉默" };
  const WEEKDAY_LABEL = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const OVERRIDE_PHASES = [
    ["sleeping", "睡眠"], ["working", "工作"], ["off_work", "休息"],
    ["weekend", "周末"], ["quiet", "安静"],
  ];
  const LOOP_FORM_IDS = [
    "presence-loop-person", "presence-loop-topic", "presence-loop-detail",
    "presence-loop-hours", "presence-set-enabled", "presence-set-shadow",
    "presence-set-threshold", "presence-set-daily", "presence-set-weekly",
    "presence-set-quiet-start", "presence-set-quiet-end",
  ];
  const REL_FORM_IDS = [
    "presence-rel-nickname", "presence-rel-stage", "presence-rel-notes",
    "presence-rel-allow", "presence-rel-followup",
  ];
  const GC_FORM_IDS = [
    "presence-gc-enabled_groups", "presence-gc-initial_probability",
    "presence-gc-proactive_quiet_start", "presence-gc-proactive_quiet_end",
  ];

  function num(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function clampPct(value) {
    return Math.max(0, Math.min(100, Math.round(num(value))));
  }

  function signed(value) {
    const parsed = num(value);
    return `${parsed >= 0 ? "+" : ""}${parsed.toFixed(0)}`;
  }

  function fmtTime(value) {
    const ts = Number(value);
    if (!ts || !Number.isFinite(ts)) return "—";
    return new Date(ts * 1000).toLocaleString();
  }

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog } = ctx;
    let instances = [];
    let instId = "";
    let scope = "";
    let timer = null;
    let loops = [];
    let loopStatus = "";
    let loopPreviews = {};
    let relations = [];
    let relationId = "";
    let milestones = [];
    let rhythm = null;
    let moodStatus = null;
    let radar = null;
    let gc = null;
    let diaries = [];
    let diaryId = "";
    let diaryDirty = false;
    let presenceSettings = null;
    let generating = false;

    /* ------------------------------------------------------------ 通用 */

    function resetData() {
      loops = [];
      loopPreviews = {};
      relations = [];
      relationId = "";
      milestones = [];
      rhythm = null;
      moodStatus = null;
      radar = null;
      gc = null;
      diaries = [];
      diaryId = "";
      diaryDirty = false;
      presenceSettings = null;
      generating = false;
    }

    function leave() {
      if (timer) { clearInterval(timer); timer = null; }
      scope = "";
      resetData();
    }

    function setError(view, message) {
      const el = view.querySelector("#presence-error");
      if (!el) return;
      el.textContent = message || "";
      el.hidden = !message;
    }

    function isFocused(view, ids) {
      const active = typeof document !== "undefined" ? document.activeElement : null;
      if (!active) return false;
      return ids.some((id) => {
        const el = view.querySelector(`#${id}`);
        return !!el && el === active;
      });
    }

    function setField(view, id, prop, value) {
      // 轮询/保存回填时跳过正在操作的控件，避免把输入改回旧值。
      if (isFocused(view, [id])) return;
      const el = view.querySelector(`#${id}`);
      if (el) el[prop] = value;
    }

    function instanceField() {
      return `<div class="field"><label>机器人</label><select id="presence-inst"></select></div>`;
    }

    function errorBox() {
      return `<div class="presence-inline-error" id="presence-error" hidden></div>`;
    }

    function emptyInstances(view) {
      view.innerHTML = `<div class="empty">${icon("alert")}<h4>没有可用实例</h4><p>请先新增或接入机器人。</p></div>`;
    }

    function boot(view, loader) {
      return (async () => {
        let list = [];
        try {
          list = await api("/api/instances");
        } catch (err) {
          setError(view, `实例读取失败：${err.message}`);
          return false;
        }
        instances = Array.isArray(list) ? list : [];
        if (!instances.length) {
          emptyInstances(view);
          return false;
        }
        if (!instId || !instances.some((item) => item.id === instId)) instId = instances[0].id;
        const select = view.querySelector("#presence-inst");
        if (select) {
          select.innerHTML = instances
            .map((item) => `<option value="${esc(item.id)}">${esc(item.name || item.id)}</option>`)
            .join("");
          select.value = instId;
        }
        await loader(view);
        return true;
      })();
    }

    function bindInstance(view) {
      const select = view.querySelector("#presence-inst");
      if (!select) return;
      select.addEventListener("change", async (event) => {
        instId = event.target.value;
        resetData();
        try {
          await reload(view);
        } catch (err) {
          toast(err.message, "err");
        }
      });
    }

    function reload(view) {
      if (scope === "relations") return loadRelations(view);
      if (scope === "rhythm") return loadRhythm(view);
      if (scope === "radar") return loadRadar(view);
      if (scope === "diary") return loadDiaries(view);
      return loadLoops(view);
    }

    function startPoll(view, expectedScope, task) {
      if (timer) { clearInterval(timer); timer = null; }
      timer = setInterval(() => {
        if (scope !== expectedScope || !view || view.isConnected === false) {
          leave();
          return;
        }
        Promise.resolve(task(view)).catch(() => {});
      }, POLL_MS);
    }

    /* -------------------------------------------------------- 话题回访 */

    function loopStatusBadge(status) {
      const key = String(status || "open");
      const cls = key === "open" ? "accent" : key === "resolved" ? "ok" : "warn";
      return `<span class="badge ${cls}">${esc(LOOP_STATUS[key] || key)}</span>`;
    }

    function loopRow(item) {
      const id = String(item.id || "");
      const status = String(item.status || "open");
      const preview = loopPreviews[id];
      const text = preview ? String(preview.text || "") : String(item.follow_up_text || "");
      const label = preview ? (preview.shadow ? "影子预览" : "回访文案") : "已生成文案";
      const actions = [
        `<button class="btn sm ghost" data-preview="${esc(id)}">${preview ? "重新生成" : "预览"}</button>`,
      ];
      if (status === "open") {
        actions.push(`<button class="btn sm primary" data-send="${esc(id)}">立即发送</button>`);
        actions.push(`<button class="btn sm ghost" data-resolve="${esc(id)}">解决</button>`);
        actions.push(`<button class="btn sm ghost" data-ignore="${esc(id)}">忽略</button>`);
      } else {
        actions.push(`<button class="btn sm ghost" data-reopen="${esc(id)}">重新打开</button>`);
      }
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(item.topic || "未命名话题")}</strong>
            ${loopStatusBadge(status)}
            <span class="badge">${item.source === "manual" ? "手动" : "自动"}</span>
            <span class="badge">置信 ${clampPct(num(item.confidence) * 100)}%</span>
            <span>${esc(item.person_key || "")}</span>
          </div>
          <div class="auto-meta">
            <span>${esc(item.platform || "qq")}</span>
            ${item.detail ? `<span>${esc(item.detail)}</span>` : ""}
            <span>下次回访 ${esc(fmtTime(item.follow_up_after))}</span>
            <span>已回访 ${num(item.follow_up_count)} 次</span>
          </div>
          ${text ? `<div class="presence-preview">${label}：${esc(text)}</div>` : ""}
        </div>
        <div class="auto-actions">${actions.join("")}</div>
      </article>`;
    }

    function renderLoopList(view) {
      const box = view.querySelector("#presence-loop-list");
      if (!box) return;
      box.innerHTML = loops.length
        ? loops.map(loopRow).join("")
        : `<div class="empty-inline">还没有符合条件的回访。私聊出现未聊完的话题时会自动出现，也可以手动新增。</div>`;
    }

    function applyLoopSettings(view) {
      if (!presenceSettings) return;
      setField(view, "presence-set-enabled", "checked", !!presenceSettings.followup_enabled);
      setField(view, "presence-set-shadow", "checked", !!presenceSettings.followup_shadow);
      setField(view, "presence-set-threshold", "value", num(presenceSettings.familiarity_threshold, 30));
      setField(view, "presence-set-daily", "value", num(presenceSettings.daily_limit, 1));
      setField(view, "presence-set-weekly", "value", num(presenceSettings.weekly_limit, 3));
      setField(view, "presence-set-quiet-start", "value", presenceSettings.quiet_start || "23:00");
      setField(view, "presence-set-quiet-end", "value", presenceSettings.quiet_end || "08:00");
    }

    async function loadLoops(view, options = {}) {
      if (!instId) return;
      const requestInst = instId;
      const status = loopStatus;
      let items = [];
      let cfg = null;
      try {
        const results = await Promise.all([
          api(`/api/presence/loops?instance_id=${encodeURIComponent(requestInst)}${status ? `&status=${encodeURIComponent(status)}` : ""}`),
          options.withSettings === false
            ? Promise.resolve(null)
            : api(`/api/presence/settings?instance_id=${encodeURIComponent(requestInst)}`),
        ]);
        items = results[0];
        cfg = results[1];
      } catch (err) {
        if (requestInst === instId) setError(view, `回访数据读取失败：${err.message}`);
        return;
      }
      if (requestInst !== instId) return;
      loops = Array.isArray(items) ? items : [];
      if (cfg && typeof cfg === "object") {
        presenceSettings = cfg;
        applyLoopSettings(view);
      }
      setError(view, "");
      renderLoopList(view);
    }

    async function refreshLoops(view) {
      if (isFocused(view, LOOP_FORM_IDS)) return;
      await loadLoops(view, { withSettings: false });
    }

    async function previewLoop(view, id) {
      const data = await api(`/api/presence/loops/${encodeURIComponent(id)}/preview`, {
        method: "POST",
        body: { instance_id: instId },
      });
      const saved = (data && data.loop) || {};
      loopPreviews[id] = { text: String(saved.follow_up_text || ""), shadow: !!(data && data.shadow) };
      const index = loops.findIndex((item) => String(item.id) === String(id));
      if (index >= 0) loops[index] = Object.assign({}, loops[index], saved);
      renderLoopList(view);
      toast(loopPreviews[id].shadow ? "已生成影子回访文案" : "已生成回访文案");
    }

    async function sendLoop(view, id) {
      const item = loops.find((entry) => String(entry.id) === String(id));
      if (!item) return;
      const preview = loopPreviews[id];
      const text = String((preview && preview.text) || item.follow_up_text || "");
      const target = item.person_key || item.thread_key || "对方";
      const ok = await confirmDialog(
        "立即发送回访",
        `将通过回访插件私聊真实发送给 ${target}：\n${text || "（发送时会先生成文案）"}`);
      if (!ok) return;
      const saved = await api(`/api/presence/loops/${encodeURIComponent(id)}/send`, {
        method: "POST",
        body: { instance_id: instId, confirm: true },
      });
      const index = loops.findIndex((entry) => String(entry.id) === String(id));
      if (index >= 0 && saved) loops[index] = Object.assign({}, loops[index], saved);
      toast("已发送回访");
      await loadLoops(view, { withSettings: false });
    }

    async function setLoopStatus(view, id, status) {
      await api(`/api/presence/loops/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: { instance_id: instId, status },
      });
      toast(status === "resolved" ? "已标记为已解决" : status === "ignored" ? "已忽略该话题" : "已重新打开");
      await loadLoops(view, { withSettings: false });
    }

    async function createLoop(view) {
      const personKey = String((view.querySelector("#presence-loop-person").value || "")).trim();
      const topic = String((view.querySelector("#presence-loop-topic").value || "")).trim();
      const detail = String((view.querySelector("#presence-loop-detail").value || "")).trim();
      const hours = num(view.querySelector("#presence-loop-hours").value, 24);
      if (!personKey) return toast("请填写对方 ID", "err");
      if (!topic) return toast("请填写话题", "err");
      await api("/api/presence/loops", {
        method: "POST",
        body: {
          instance_id: instId, platform: "qq", person_key: personKey,
          topic, detail, follow_up_after_hours: hours,
        },
      });
      view.querySelector("#presence-loop-person").value = "";
      view.querySelector("#presence-loop-topic").value = "";
      view.querySelector("#presence-loop-detail").value = "";
      toast("已新增回访话题");
      await loadLoops(view);
    }

    async function saveLoopSettings(view) {
      const shadowChecked = view.querySelector("#presence-set-shadow").checked;
      // 从影子切到真实会让到期回访真的发出去，保存前必须确认。
      if (presenceSettings && presenceSettings.followup_shadow && !shadowChecked) {
        const ok = await confirmDialog(
          "关闭影子模式",
          "关闭后到期的回访会真实私聊发送，仅限满足熟悉度、每日/每周上限与安静时段的私聊。确定继续？");
        if (!ok) {
          view.querySelector("#presence-set-shadow").checked = true;
          return;
        }
      }
      const body = {
        instance_id: instId,
        followup_enabled: view.querySelector("#presence-set-enabled").checked,
        followup_shadow: shadowChecked,
        familiarity_threshold: num(view.querySelector("#presence-set-threshold").value, 30),
        daily_limit: num(view.querySelector("#presence-set-daily").value, 1),
        weekly_limit: num(view.querySelector("#presence-set-weekly").value, 3),
        quiet_start: String((view.querySelector("#presence-set-quiet-start").value || "")).trim(),
        quiet_end: String((view.querySelector("#presence-set-quiet-end").value || "")).trim(),
      };
      const saved = await api("/api/presence/settings", { method: "PUT", body });
      if (saved && typeof saved === "object") {
        presenceSettings = saved;
        applyLoopSettings(view);
      }
      toast("回访设置已保存");
    }

    function bindLoops(view) {
      const list = view.querySelector("#presence-loop-list");
      if (list) {
        list.addEventListener("click", async (event) => {
          const node = event.target.closest("[data-preview],[data-send],[data-resolve],[data-ignore],[data-reopen]");
          if (!node) return;
          const data = node.dataset || {};
          try {
            if (data.preview) await previewLoop(view, data.preview);
            else if (data.send) await sendLoop(view, data.send);
            else if (data.resolve) await setLoopStatus(view, data.resolve, "resolved");
            else if (data.ignore) await setLoopStatus(view, data.ignore, "ignored");
            else if (data.reopen) await setLoopStatus(view, data.reopen, "open");
          } catch (err) {
            toast(err.message, "err");
          }
        });
      }
      const statusSelect = view.querySelector("#presence-loop-status");
      if (statusSelect) {
        statusSelect.addEventListener("change", (event) => {
          loopStatus = event.target.value || "";
          loadLoops(view).catch((err) => toast(err.message, "err"));
        });
      }
      const add = view.querySelector("#presence-loop-add");
      if (add) add.addEventListener("click", () => createLoop(view).catch((err) => toast(err.message, "err")));
      const save = view.querySelector("#presence-set-save");
      if (save) save.addEventListener("click", () => saveLoopSettings(view).catch((err) => toast(err.message, "err")));
    }

    function renderLoops(view) {
      view.innerHTML = `
        <div class="card">
          <div class="section-head" style="margin:0 0 12px">
            <h2>话题回访</h2><span class="side">默认影子只生成文案；真实发送需二次确认</span>
          </div>
          ${instanceField()}
          <div class="field"><label>状态筛选</label><select id="presence-loop-status">
            <option value="">全部</option>
            <option value="open">未完成</option>
            <option value="resolved">已解决</option>
            <option value="ignored">已忽略</option>
          </select></div>
          ${errorBox()}
          <div class="auto-list" id="presence-loop-list"><div class="skeleton" style="height:90px"></div></div>
        </div>
        <div class="presence-grid" style="margin-top:16px">
          <div class="card">
            <div class="section-head" style="margin:0 0 10px">
              <h2>手动新增</h2><span class="side">只对熟悉私聊生效</span>
            </div>
            <div class="field"><label>对方 ID</label>
              <input id="presence-loop-person" type="text" placeholder="QQ 号或私聊会话对方 ID"></div>
            <div class="field"><label>话题</label>
              <input id="presence-loop-topic" type="text" placeholder="例如：周末约好的车赛"></div>
            <div class="field"><label>细节（可选）</label><textarea id="presence-loop-detail" rows="3"></textarea></div>
            <div class="field"><label>多久后回访（小时）</label>
              <input id="presence-loop-hours" type="number" min="0" max="8760" step="1" value="24"></div>
            <div class="human-actions"><button class="btn primary" id="presence-loop-add">新增回访</button></div>
          </div>
          <div class="card">
            <div class="section-head" style="margin:0 0 10px">
              <h2>回访设置</h2><span class="side">影子模式不会真的发出去</span>
            </div>
            <label class="check-row"><input type="checkbox" id="presence-set-enabled"> 允许回访</label>
            <label class="check-row"><input type="checkbox" id="presence-set-shadow"> 影子模式</label>
            <div class="field"><label>熟悉度阈值</label>
              <input id="presence-set-threshold" type="number" min="0" max="100" step="1"></div>
            <div class="field"><label>每天上限</label>
              <input id="presence-set-daily" type="number" min="0" max="20" step="1"></div>
            <div class="field"><label>每周上限</label>
              <input id="presence-set-weekly" type="number" min="0" max="100" step="1"></div>
            <div class="presence-range">
              <div class="field"><label>安静开始</label>
                <input id="presence-set-quiet-start" type="text" placeholder="23:00"></div>
              <div class="field"><label>安静结束</label>
                <input id="presence-set-quiet-end" type="text" placeholder="08:00"></div>
            </div>
            <div class="human-actions" style="margin-top:12px">
              <button class="btn primary" id="presence-set-save">保存回访设置</button>
            </div>
          </div>
        </div>`;
      bindInstance(view);
      bindLoops(view);
      // 页面间切换后保留筛选条件，避免下拉显示和实际请求不一致。
      const statusSelect = view.querySelector("#presence-loop-status");
      if (statusSelect) statusSelect.value = loopStatus;
      boot(view, (target) => loadLoops(target))
        .then((ready) => { if (ready) startPoll(view, "loops", refreshLoops); })
        .catch((err) => toast(err.message, "err"));
    }

    /* ------------------------------------------------------ 关系里程碑 */

    function selectedRelation() {
      return relations.find((item) => String(item.id) === String(relationId)) || null;
    }

    function relationName(item) {
      return item.nickname || item.display_name || item.person_key || "未知人物";
    }

    function relationRow(item) {
      const id = String(item.id || "");
      const stage = String(item.stage || "stranger");
      const stageClass = stage === "close" ? "ok" : stage === "familiar" ? "accent" : "";
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(relationName(item))}</strong>
            <span class="badge">${esc(item.platform || "qq")}</span>
            <span class="badge ${stageClass}">${esc(STAGE_LABEL[stage] || stage)}</span>
            ${item.followup_enabled ? "" : `<span class="badge warn">不回访</span>`}
            ${item.allow_memory ? "" : `<span class="badge warn">不读记忆</span>`}
            ${id === String(relationId) ? `<span class="badge ok">已选中</span>` : ""}
          </div>
          <div class="auto-meta">
            <span>${esc(item.person_key || "")}</span>
            <span>好感 ${Math.round(num(item.affection))}</span>
            <span>怒气 ${Math.round(num(item.anger))}</span>
            <span>熟悉度 ${Math.round(num(item.familiarity))}</span>
            <span>消息 ${num(item.message_count)}</span>
            <span>最近 ${esc(fmtTime(item.last_seen))}</span>
          </div>
        </div>
        <div class="auto-actions">
          <button class="btn sm ghost" data-rel="${esc(id)}">${id === String(relationId) ? "已选" : "编辑"}</button>
        </div>
      </article>`;
    }

    function renderRelationList(view) {
      const box = view.querySelector("#presence-rel-list");
      if (!box) return;
      box.innerHTML = relations.length
        ? relations.map(relationRow).join("")
        : `<div class="empty-inline">还没有关系记录。插件上报私聊/群聊活动后会自动出现。</div>`;
    }

    function relationMetaInner(item) {
      return `<span>好感 ${Math.round(num(item.affection))}</span>
        <span>怒气 ${Math.round(num(item.anger))}</span>
        <span>熟悉度 ${Math.round(num(item.familiarity))}</span>
        <span>消息 ${num(item.message_count)}</span>
        <span>首见 ${esc(fmtTime(item.first_seen))}</span>
        <span>最近 ${esc(fmtTime(item.last_seen))}</span>`;
    }

    function relationMetaHtml(item) {
      return `<div class="auto-meta" id="presence-rel-meta" style="margin:0 0 12px">
        ${relationMetaInner(item)}
      </div>`;
    }

    function renderRelationDetail(view) {
      const box = view.querySelector("#presence-rel-detail");
      if (!box) return;
      const item = selectedRelation();
      if (!item) {
        box.innerHTML = `<div class="empty-inline">选择左侧人物查看昵称、阶段与备注。</div>`;
        return;
      }
      box.innerHTML = `
        <div class="section-head" style="margin:0 0 10px">
          <h2>${esc(relationName(item))}</h2>
          <span class="side">${esc(item.platform || "qq")} · ${esc(item.person_key || "")}</span>
        </div>
        ${relationMetaHtml(item)}
        <div class="field"><label>昵称</label>
          <input id="presence-rel-nickname" type="text" maxlength="80" placeholder="留空则用显示名"></div>
        <div class="field"><label>阶段</label><select id="presence-rel-stage">
          <option value="stranger">陌生</option>
          <option value="familiar">熟悉</option>
          <option value="close">亲近</option>
        </select></div>
        <div class="field"><label>备注</label>
          <textarea id="presence-rel-notes" rows="3" placeholder="只在本机管理器可见"></textarea></div>
        <label class="check-row"><input type="checkbox" id="presence-rel-allow"> 允许读取关系记忆（昵称/里程碑）</label>
        <label class="check-row"><input type="checkbox" id="presence-rel-followup"> 允许自动回访</label>
        <div class="human-actions"><button class="btn primary" id="presence-rel-save">保存关系</button></div>`;
      const nickname = view.querySelector("#presence-rel-nickname");
      if (nickname) nickname.value = item.nickname || "";
      const stage = view.querySelector("#presence-rel-stage");
      if (stage) stage.value = String(item.stage || "stranger");
      const notes = view.querySelector("#presence-rel-notes");
      if (notes) notes.value = item.notes || "";
      const allow = view.querySelector("#presence-rel-allow");
      if (allow) allow.checked = !!item.allow_memory;
      const followup = view.querySelector("#presence-rel-followup");
      if (followup) followup.checked = !!item.followup_enabled;
      const save = view.querySelector("#presence-rel-save");
      if (save) save.addEventListener("click", () => saveRelation(view).catch((err) => toast(err.message, "err")));
    }

    function milestoneHtml(item) {
      return `<div class="presence-ms">
        <div class="presence-ms-time">${esc(fmtTime(item.occurred_at))}<br>${item.source === "manual" ? "手动" : "自动"}</div>
        <div class="presence-ms-body">
          <strong>${esc(item.title || item.kind || "里程碑")}</strong>
          ${item.detail ? `<div class="presence-note">${esc(item.detail)}</div>` : ""}
        </div>
        <button class="btn sm danger" data-ms-del="${esc(item.id || "")}" title="删除里程碑">${icon("trash")}</button>
      </div>`;
    }

    function renderMilestones(view) {
      const box = view.querySelector("#presence-ms-list");
      if (!box) return;
      if (!relationId) {
        box.innerHTML = `<div class="empty-inline">先选择一位人物。</div>`;
        return;
      }
      box.innerHTML = milestones.length
        ? milestones.map(milestoneHtml).join("")
        : `<div class="empty-inline">还没有里程碑；首次私聊、消息数和认识天数会自动记录。</div>`;
    }

    async function loadMilestones(view) {
      const item = selectedRelation();
      if (!item) {
        milestones = [];
        renderMilestones(view);
        return;
      }
      const requestInst = instId;
      const requestId = String(item.id);
      let items = [];
      try {
        items = await api(`/api/presence/milestones?instance_id=${encodeURIComponent(requestInst)}`
          + `&platform=${encodeURIComponent(item.platform || "qq")}`
          + `&person_key=${encodeURIComponent(item.person_key || "")}`);
      } catch (err) {
        if (requestInst === instId) setError(view, `里程碑读取失败：${err.message}`);
        return;
      }
      if (requestInst !== instId || requestId !== String(relationId)) return;
      milestones = Array.isArray(items) ? items : [];
      renderMilestones(view);
      setError(view, "");
    }

    async function loadRelations(view) {
      if (!instId) return;
      const requestInst = instId;
      let items = [];
      try {
        items = await api(`/api/presence/relations?instance_id=${encodeURIComponent(requestInst)}`);
      } catch (err) {
        if (requestInst === instId) setError(view, `关系读取失败：${err.message}`);
        return;
      }
      if (requestInst !== instId) return;
      relations = Array.isArray(items) ? items : [];
      if (!relations.some((item) => String(item.id) === String(relationId))) {
        relationId = relations.length ? String(relations[0].id) : "";
      }
      setError(view, "");
      renderRelationList(view);
      renderRelationDetail(view);
      await loadMilestones(view);
    }

    async function refreshRelations(view) {
      if (isFocused(view, REL_FORM_IDS)) return;
      const requestInst = instId;
      let items = [];
      try {
        items = await api(`/api/presence/relations?instance_id=${encodeURIComponent(requestInst)}`);
      } catch (_) {
        return;
      }
      if (requestInst !== instId) return;
      relations = Array.isArray(items) ? items : [];
      if (!relations.some((item) => String(item.id) === String(relationId))) {
        relationId = relations.length ? String(relations[0].id) : "";
        renderRelationDetail(view);
        await loadMilestones(view);
      } else {
        const item = selectedRelation();
        const meta = view.querySelector("#presence-rel-meta");
        if (item && meta) meta.innerHTML = relationMetaInner(item);
      }
      renderRelationList(view);
    }

    async function saveRelation(view) {
      const item = selectedRelation();
      if (!item) return toast("先选择一位人物", "err");
      const nickname = String((view.querySelector("#presence-rel-nickname").value || "")).trim();
      const stage = String(view.querySelector("#presence-rel-stage").value || "stranger");
      const notes = String((view.querySelector("#presence-rel-notes").value || "")).trim();
      const saved = await api(`/api/presence/relations/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        body: {
          instance_id: instId,
          nickname,
          stage,
          notes,
          allow_memory: view.querySelector("#presence-rel-allow").checked,
          followup_enabled: view.querySelector("#presence-rel-followup").checked,
        },
      });
      const index = relations.findIndex((entry) => String(entry.id) === String(item.id));
      if (index >= 0 && saved) relations[index] = Object.assign({}, relations[index], saved);
      toast("关系已保存");
      renderRelationList(view);
      renderRelationDetail(view);
    }

    async function addMilestone(view) {
      const item = selectedRelation();
      if (!item) return toast("先选择一位人物", "err");
      const title = String((view.querySelector("#presence-ms-title").value || "")).trim();
      const detail = String((view.querySelector("#presence-ms-detail").value || "")).trim();
      if (!title) return toast("里程碑标题不能为空", "err");
      await api("/api/presence/milestones", {
        method: "POST",
        body: {
          instance_id: instId, platform: item.platform || "qq",
          person_key: item.person_key || "", kind: "custom", title, detail,
        },
      });
      view.querySelector("#presence-ms-title").value = "";
      view.querySelector("#presence-ms-detail").value = "";
      toast("已新增里程碑");
      await loadMilestones(view);
    }

    async function deleteMilestone(view, id) {
      const ok = await confirmDialog("删除里程碑", "确定删除这条里程碑？只影响管理器里的记录，不影响记忆库。");
      if (!ok) return;
      await api(`/api/presence/milestones?milestone_id=${encodeURIComponent(id)}`
        + `&instance_id=${encodeURIComponent(instId)}`, { method: "DELETE" });
      toast("已删除里程碑");
      await loadMilestones(view);
    }

    function bindRelations(view) {
      const list = view.querySelector("#presence-rel-list");
      if (list) {
        list.addEventListener("click", (event) => {
          const node = event.target.closest("[data-rel]");
          if (!node) return;
          relationId = String((node.dataset || {}).rel || "");
          renderRelationList(view);
          renderRelationDetail(view);
          loadMilestones(view).catch((err) => toast(err.message, "err"));
        });
      }
      const msList = view.querySelector("#presence-ms-list");
      if (msList) {
        msList.addEventListener("click", (event) => {
          const node = event.target.closest("[data-ms-del]");
          if (!node) return;
          deleteMilestone(view, String((node.dataset || {}).msDel || "")).catch((err) => toast(err.message, "err"));
        });
      }
      const add = view.querySelector("#presence-ms-add");
      if (add) add.addEventListener("click", () => addMilestone(view).catch((err) => toast(err.message, "err")));
    }

    function renderRelations(view) {
      view.innerHTML = `
        <div class="card">
          <div class="section-head" style="margin:0 0 12px">
            <h2>关系里程碑</h2><span class="side">昵称/阶段只影响称呼；好感动怒仍来自心情模块</span>
          </div>
          ${instanceField()}
          ${errorBox()}
          <div class="auto-list" id="presence-rel-list"><div class="skeleton" style="height:90px"></div></div>
        </div>
        <div class="presence-grid" style="margin-top:16px">
          <div class="card" id="presence-rel-detail"><div class="empty-inline">选择左侧人物查看详情。</div></div>
          <div class="card">
            <div class="section-head" style="margin:0 0 10px">
              <h2>里程碑</h2><span class="side">按发生时间倒序；来源标自动/手动</span>
            </div>
            <div class="field"><label>标题</label>
              <input id="presence-ms-title" type="text" maxlength="120" placeholder="例如：第一次一起跑车队赛"></div>
            <div class="field"><label>细节（可选）</label><textarea id="presence-ms-detail" rows="2"></textarea></div>
            <div class="human-actions"><button class="btn primary" id="presence-ms-add">新增里程碑</button></div>
            <div class="presence-timeline" id="presence-ms-list">
              <div class="empty-inline">先选择一位人物。</div>
            </div>
          </div>
        </div>`;
      bindInstance(view);
      bindRelations(view);
      boot(view, (target) => loadRelations(target))
        .then((ready) => { if (ready) startPoll(view, "relations", refreshRelations); })
        .catch((err) => toast(err.message, "err"));
    }

    /* -------------------------------------------------------- 生活节律 */

    function renderRhythmNow(view) {
      const box = view.querySelector("#presence-rt-now");
      if (!box || !rhythm) return;
      const state = (moodStatus && moodStatus.state) || {};
      const baseEnergy = num(state.energy);
      const baseSocial = num(state.social);
      const energy = Math.max(0, Math.min(100, baseEnergy + num(rhythm.energy_mod)));
      const social = Math.max(0, Math.min(100, baseSocial + num(rhythm.social_mod)));
      const override = rhythm.override || {};
      const schedule = rhythm.schedule || {};
      box.innerHTML = `
        <div class="presence-split">
          <div class="presence-stat"><div class="k">当前阶段</div>
            <div class="v">${esc(rhythm.label || rhythm.phase || "—")}</div>
            <div class="presence-note">${override.active ? `手动覆盖到 ${esc(fmtTime(override.until))}` : "按作息自动计算"}</div>
          </div>
          <div class="presence-stat"><div class="k">有效精力</div>
            <div class="v">${energy.toFixed(0)}</div>
            <div class="presence-meter"><i style="width:${energy}%"></i></div>
            <div class="presence-note">心情 ${baseEnergy.toFixed(0)} ${signed(rhythm.energy_mod)}</div>
          </div>
          <div class="presence-stat"><div class="k">有效社交</div>
            <div class="v">${social.toFixed(0)}</div>
            <div class="presence-meter"><i style="width:${social}%"></i></div>
            <div class="presence-note">心情 ${baseSocial.toFixed(0)} ${signed(rhythm.social_mod)}</div>
          </div>
        </div>
        <div class="presence-note">
          ${schedule.rhythm_enabled ? "节律生效" : "节律已关闭（修正为 0）"}
          · 自动微调 ${signed(rhythm.auto_mod)}
          · ${override.note ? `备注：${esc(override.note)}` : "无手动备注"}
        </div>`;
    }

    function hourBuckets() {
      const events = moodStatus && Array.isArray(moodStatus.events) ? moodStatus.events : [];
      const buckets = new Array(24).fill(0);
      events.forEach((event) => {
        const ts = num(event.created);
        if (!ts) return;
        buckets[new Date(ts * 1000).getHours()] += 1;
      });
      return buckets;
    }

    function renderRhythmCurve(view) {
      const box = view.querySelector("#presence-rt-curve");
      if (!box) return;
      const buckets = hourBuckets();
      const total = buckets.reduce((sum, count) => sum + count, 0);
      const max = Math.max(...buckets, 0);
      box.innerHTML = total
        ? `<div class="presence-curve">${buckets.map((count, hour) => {
          const height = max ? Math.max(4, Math.round((count / max) * 100)) : 4;
          return `<div class="presence-curve-bar ${count === max ? "hot" : ""}" style="height:${height}%" title="${hour}:00 · ${count} 条"></div>`;
        }).join("")}</div>
        <div class="presence-curve-axis"><span>0:00</span><span>6:00</span><span>12:00</span><span>18:00</span><span>23:00</span></div>`
        : `<div class="empty-inline">还没有心情评估记录，有对话后会出现按小时分布。</div>`;
      const totalEl = view.querySelector("#presence-rt-total");
      if (totalEl) totalEl.textContent = `最近 ${total} 条评估 · 按小时分布`;
    }

    function applyRhythmForm(view) {
      if (!rhythm) return;
      const schedule = rhythm.schedule || {};
      setField(view, "presence-rt-enabled", "checked", !!schedule.rhythm_enabled);
      setField(view, "presence-rt-wake", "value", schedule.wake_time || "");
      setField(view, "presence-rt-sleep", "value", schedule.sleep_time || "");
      setField(view, "presence-rt-work-start", "value", schedule.work_start || "");
      setField(view, "presence-rt-work-end", "value", schedule.work_end || "");
      const days = Array.isArray(schedule.weekend_days) ? schedule.weekend_days.map((day) => num(day)) : [];
      for (let day = 0; day < 7; day += 1) {
        setField(view, `presence-week-${day}`, "checked", days.includes(day));
      }
      setField(view, "presence-rt-auto", "checked", !!schedule.auto_adjust);
      const override = rhythm.override || {};
      setField(view, "presence-ov-phase", "value", override.phase || "");
      setField(view, "presence-ov-note", "value", override.note || "");
    }

    async function loadRhythm(view) {
      if (!instId) return;
      const requestInst = instId;
      let current = null;
      let status = null;
      try {
        const results = await Promise.all([
          api(`/api/presence/rhythm?instance_id=${encodeURIComponent(requestInst)}`),
          api(`/api/mood/status?instance_id=${encodeURIComponent(requestInst)}`),
        ]);
        current = results[0];
        status = results[1];
      } catch (err) {
        if (requestInst === instId) setError(view, `节律读取失败：${err.message}`);
        return;
      }
      if (requestInst !== instId) return;
      rhythm = current || null;
      moodStatus = status || null;
      setError(view, "");
      applyRhythmForm(view);
      renderRhythmNow(view);
      renderRhythmCurve(view);
    }

    async function saveRhythm(view) {
      const weekend = [];
      for (let day = 0; day < 7; day += 1) {
        if (view.querySelector(`#presence-week-${day}`).checked) weekend.push(day);
      }
      await api("/api/presence/rhythm", {
        method: "PUT",
        body: {
          instance_id: instId,
          rhythm_enabled: view.querySelector("#presence-rt-enabled").checked,
          wake_time: String((view.querySelector("#presence-rt-wake").value || "")).trim(),
          sleep_time: String((view.querySelector("#presence-rt-sleep").value || "")).trim(),
          work_start: String((view.querySelector("#presence-rt-work-start").value || "")).trim(),
          work_end: String((view.querySelector("#presence-rt-work-end").value || "")).trim(),
          weekend_days: weekend,
          auto_adjust: view.querySelector("#presence-rt-auto").checked,
        },
      });
      toast("作息已保存");
      await loadRhythm(view);
    }

    async function applyOverride(view) {
      const phase = String(view.querySelector("#presence-ov-phase").value || "");
      if (!phase) return toast("先选择要覆盖的阶段", "err");
      const hours = num(view.querySelector("#presence-ov-hours").value, 0);
      if (hours <= 0) return toast("覆盖时长需大于 0 小时", "err");
      await api("/api/presence/rhythm", {
        method: "PUT",
        body: {
          instance_id: instId,
          override_phase: phase,
          override_note: String((view.querySelector("#presence-ov-note").value || "")).trim(),
          override_until: Math.floor(Date.now() / 1000) + Math.round(hours * 3600),
        },
      });
      toast("已应用临时覆盖");
      await loadRhythm(view);
    }

    async function clearOverride(view) {
      await api("/api/presence/rhythm", {
        method: "PUT",
        body: { instance_id: instId, override_until: 0, override_phase: "", override_note: "" },
      });
      toast("已恢复自动节律");
      await loadRhythm(view);
    }

    function renderRhythm(view) {
      view.innerHTML = `
        <div class="card">
          <div class="section-head" style="margin:0 0 12px">
            <h2>生活节律</h2><span class="side">只影响内部状态与回复节奏，不声称真实的线下行动</span>
          </div>
          ${instanceField()}
          ${errorBox()}
          <div id="presence-rt-now"><div class="skeleton" style="height:100px"></div></div>
        </div>
        <div class="presence-grid" style="margin-top:16px">
          <div class="card">
            <div class="section-head" style="margin:0 0 10px">
              <h2>作息</h2><span class="side">时间格式 HH:MM</span>
            </div>
            <label class="check-row"><input type="checkbox" id="presence-rt-enabled"> 启用生活节律</label>
            <div class="presence-range">
              <div class="field"><label>起床</label><input id="presence-rt-wake" type="text" placeholder="08:00"></div>
              <div class="field"><label>睡觉</label><input id="presence-rt-sleep" type="text" placeholder="23:30"></div>
            </div>
            <div class="presence-range">
              <div class="field"><label>工作开始</label><input id="presence-rt-work-start" type="text" placeholder="09:00"></div>
              <div class="field"><label>工作结束</label><input id="presence-rt-work-end" type="text" placeholder="18:00"></div>
            </div>
            <div class="presence-week">${WEEKDAY_LABEL.map((label, day) =>
              `<label class="check-row" style="margin:0"><input type="checkbox" id="presence-week-${day}"> ${esc(label)}</label>`).join("")}</div>
            <label class="check-row"><input type="checkbox" id="presence-rt-auto"> 按近 7 天活跃度自动微调</label>
            <div class="human-actions">
              <button class="btn primary" id="presence-rt-save">保存作息</button>
              <button class="btn ghost" id="presence-rt-refresh">刷新</button>
            </div>
          </div>
          <div class="card">
            <div class="section-head" style="margin:0 0 10px">
              <h2>临时覆盖</h2><span class="side">到期自动恢复，可随时手动恢复</span>
            </div>
            <div class="field"><label>阶段</label><select id="presence-ov-phase">
              <option value="">不覆盖</option>
              ${OVERRIDE_PHASES.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join("")}
            </select></div>
            <div class="field"><label>备注</label>
              <input id="presence-ov-note" type="text" maxlength="200" placeholder="例如：通宵后补觉"></div>
            <div class="field"><label>持续（小时）</label>
              <input id="presence-ov-hours" type="number" min="1" max="168" step="1" value="2"></div>
            <div class="human-actions">
              <button class="btn primary" id="presence-ov-apply">应用覆盖</button>
              <button class="btn ghost" id="presence-ov-clear">恢复自动</button>
            </div>
          </div>
        </div>
        <div class="card" style="margin-top:16px">
          <div class="section-head" style="margin:0 0 10px">
            <h2>24 小时活动</h2><span class="side" id="presence-rt-total">读取中…</span>
          </div>
          <div id="presence-rt-curve"><div class="skeleton" style="height:96px"></div></div>
        </div>`;
      bindInstance(view);
      const save = view.querySelector("#presence-rt-save");
      if (save) save.addEventListener("click", () => saveRhythm(view).catch((err) => toast(err.message, "err")));
      const refresh = view.querySelector("#presence-rt-refresh");
      if (refresh) refresh.addEventListener("click", () => loadRhythm(view).catch((err) => toast(err.message, "err")));
      const apply = view.querySelector("#presence-ov-apply");
      if (apply) apply.addEventListener("click", () => applyOverride(view).catch((err) => toast(err.message, "err")));
      const clear = view.querySelector("#presence-ov-clear");
      if (clear) clear.addEventListener("click", () => clearOverride(view).catch((err) => toast(err.message, "err")));
      boot(view, (target) => loadRhythm(target)).catch((err) => toast(err.message, "err"));
    }

    /* ------------------------------------------------------ 群聊读空气 */

    function renderRadarStats(view) {
      const summary = view.querySelector("#presence-radar-summary");
      if (summary && radar) {
        const total = num(radar.total);
        const rate = total ? Math.round((num(radar.reply) / total) * 100) : 0;
        summary.innerHTML = `
          <div class="presence-split">
            <div class="presence-stat"><div class="k">接话</div><div class="v">${num(radar.reply)}</div></div>
            <div class="presence-stat"><div class="k">沉默</div><div class="v">${num(radar.silent)}</div></div>
            <div class="presence-stat"><div class="k">接话率</div><div class="v">${rate}%</div>
              <div class="presence-note">近 ${num(radar.window_days, 7)} 天 ${total} 次影子判断</div></div>
          </div>
          <div class="presence-note">接话 ${num(radar.reply)} · 沉默 ${num(radar.silent)} · 只观察，不改变群聊插件决策</div>`;
      }
      const groups = view.querySelector("#presence-radar-groups");
      if (groups) {
        const items = radar && Array.isArray(radar.groups)
          ? radar.groups.filter((item) => num(item.reply) + num(item.silent) > 0)
          : [];
        groups.innerHTML = items.length ? items.map((item) => {
          const reply = num(item.reply);
          const silent = num(item.silent);
          const total = reply + silent;
          const rate = total ? Math.round((reply / total) * 100) : 0;
          return `<article class="auto-row">
            <div class="auto-main">
              <div class="auto-title"><strong>${esc(item.group_id || "未知群")}</strong>
                <span class="badge">接话 ${reply}</span>
                <span class="badge">沉默 ${silent}</span>
              </div>
              <div class="presence-meter"><i style="width:${rate}%"></i></div>
            </div>
            <div class="auto-actions"><span class="badge">${rate}%</span></div>
          </article>`;
        }).join("") : `<div class="empty-inline">近 ${num(radar && radar.window_days, 7)} 天还没有影子事件。</div>`;
      }
      const events = view.querySelector("#presence-radar-events");
      if (events) {
        const items = radar && Array.isArray(radar.recent)
          ? radar.recent.filter((item) => RADAR_LABEL[String(item.kind || "")])
          : [];
        events.innerHTML = items.length ? items.map((item) => {
          const kind = String(item.kind || "");
          const label = RADAR_LABEL[kind] || kind || "事件";
          const text = item.payload && typeof item.payload.text === "string" ? item.payload.text : "";
          return `<article class="auto-row">
            <div class="auto-main">
              <div class="auto-title"><strong>${esc(label)}</strong>
                <span class="badge ${kind === "radar_reply" ? "accent" : "warn"}">${esc(kind || "unknown")}</span>
                <span>${esc(item.group_id || "未知群")}</span>
                <span>${esc(item.person_key || "")}</span>
              </div>
              <div class="auto-meta">
                <span>${esc(fmtTime(item.created))}</span>
                ${text ? `<span>${esc(text)}</span>` : ""}
              </div>
            </div>
          </article>`;
        }).join("") : `<div class="empty-inline">还没有影子事件；插件运行后这里会出现接话/沉默判断。</div>`;
      }
    }

    function gcFieldHtml(key) {
      if (key === "enabled_groups") {
        return `<div class="field"><label>群白名单（每行一个群号）</label>
          <textarea id="presence-gc-enabled_groups" rows="3" placeholder="123456"></textarea></div>`;
      }
      if (key === "initial_probability") {
        return `<div class="field"><label>接话概率（0–1）</label>
          <input id="presence-gc-initial_probability" type="number" min="0" max="1" step="0.01"></div>`;
      }
      if (key === "proactive_quiet_start") {
        return `<div class="field"><label>安静开始（HH:MM）</label>
          <input id="presence-gc-proactive_quiet_start" type="text" placeholder="23:00"></div>`;
      }
      if (key === "proactive_quiet_end") {
        return `<div class="field"><label>安静结束（HH:MM）</label>
          <input id="presence-gc-proactive_quiet_end" type="text" placeholder="08:00"></div>`;
      }
      return "";
    }

    function renderGc(view) {
      const box = view.querySelector("#presence-gc-form");
      const hint = view.querySelector("#presence-gc-hint");
      const save = view.querySelector("#presence-gc-save");
      if (!box) return;
      if (!gc || gc.error) {
        box.innerHTML = "";
        if (hint) {
          hint.textContent = gc && gc.error ? `群聊配置不可用：${gc.error}` : "群聊配置读取中…";
          hint.hidden = false;
        }
        if (save) save.disabled = true;
        return;
      }
      const allowed = Array.isArray(gc.allowed_keys) ? gc.allowed_keys : [];
      const config = gc.config && typeof gc.config === "object" ? gc.config : {};
      const keys = GC_FORM_IDS.map((id) => id.replace("presence-gc-", ""))
        .filter((key) => allowed.includes(key));
      box.innerHTML = keys.map(gcFieldHtml).join("");
      setField(view, "presence-gc-enabled_groups", "value",
        Array.isArray(config.enabled_groups) ? config.enabled_groups.join("\n") : "");
      setField(view, "presence-gc-initial_probability", "value",
        config.initial_probability === undefined || config.initial_probability === null ? "" : config.initial_probability);
      setField(view, "presence-gc-proactive_quiet_start", "value", config.proactive_quiet_start || "");
      setField(view, "presence-gc-proactive_quiet_end", "value", config.proactive_quiet_end || "");
      if (hint) {
        hint.textContent = keys.length
          ? "只写入以上白名单字段，其余群聊插件配置保持不变；写入前会二次确认。"
          : "当前群聊插件没有可写的白名单/概率/安静时段配置。";
        hint.hidden = false;
      }
      if (save) save.disabled = !keys.length;
    }

    async function loadGc(view) {
      const requestInst = instId;
      try {
        const data = await api(`/api/presence/group-config?instance_id=${encodeURIComponent(requestInst)}`);
        if (requestInst !== instId) return;
        gc = data || {};
      } catch (err) {
        if (requestInst !== instId) return;
        gc = { error: err.message };
      }
      renderGc(view);
    }

    async function loadRadar(view, options = {}) {
      if (!instId) return;
      const requestInst = instId;
      let stats = null;
      try {
        stats = await api(`/api/presence/radar?instance_id=${encodeURIComponent(requestInst)}&days=7`);
      } catch (err) {
        if (requestInst === instId) setError(view, `影子统计读取失败：${err.message}`);
        return;
      }
      if (requestInst !== instId) return;
      radar = stats || {};
      setError(view, "");
      renderRadarStats(view);
      if (options.withGc || !gc) await loadGc(view);
    }

    async function refreshRadar(view) {
      if (isFocused(view, GC_FORM_IDS)) return;
      await loadRadar(view);
    }

    async function saveGc(view) {
      const allowed = gc && Array.isArray(gc.allowed_keys) ? gc.allowed_keys : [];
      const config = {};
      if (allowed.includes("enabled_groups")) {
        const raw = String((view.querySelector("#presence-gc-enabled_groups").value || ""));
        config.enabled_groups = raw.split(/[\r\n,]+/).map((item) => item.trim()).filter(Boolean);
      }
      if (allowed.includes("initial_probability")) {
        const value = Number(view.querySelector("#presence-gc-initial_probability").value);
        if (!Number.isFinite(value) || value < 0 || value > 1) {
          return toast("接话概率需在 0–1 之间", "err");
        }
        config.initial_probability = value;
      }
      if (allowed.includes("proactive_quiet_start")) {
        config.proactive_quiet_start = String((view.querySelector("#presence-gc-proactive_quiet_start").value || "")).trim();
      }
      if (allowed.includes("proactive_quiet_end")) {
        config.proactive_quiet_end = String((view.querySelector("#presence-gc-proactive_quiet_end").value || "")).trim();
      }
      if (!Object.keys(config).length) return toast("没有可写配置项", "err");
      const ok = await confirmDialog(
        "写入群聊配置",
        "将修改群聊读空气的白名单/概率/安静时段，并直接影响真实群聊行为。继续？");
      if (!ok) return;
      const saved = await api("/api/presence/group-config", {
        method: "PUT",
        body: { instance_id: instId, confirm: true, config },
      });
      if (saved && typeof saved === "object" && !saved.error) gc = saved;
      toast("群聊配置已写入");
      renderGc(view);
    }

    function renderRadar(view) {
      view.innerHTML = `
        <div class="card">
          <div class="section-head" style="margin:0 0 12px">
            <h2>群聊读空气</h2><span class="side">只记录接话/沉默影子事件，不改群聊插件决策</span>
          </div>
          ${instanceField()}
          ${errorBox()}
          <div id="presence-radar-summary"><div class="skeleton" style="height:80px"></div></div>
          <div class="auto-list" id="presence-radar-groups" style="margin-top:12px">
            <div class="skeleton" style="height:70px"></div>
          </div>
        </div>
        <div class="presence-grid" style="margin-top:16px">
          <div class="card">
            <div class="section-head" style="margin:0 0 10px">
              <h2>最近事件</h2><span class="side">每 4 秒刷新列表</span>
            </div>
            <div class="auto-list" id="presence-radar-events"><div class="skeleton" style="height:90px"></div></div>
            <div class="human-actions" style="margin-top:12px">
              <button class="btn ghost" id="presence-radar-refresh">刷新</button>
            </div>
          </div>
          <div class="card">
            <div class="section-head" style="margin:0 0 10px">
              <h2>群聊配置</h2><span class="side">只读写白名单子集，写入需确认</span>
            </div>
            <div id="presence-gc-form"><div class="skeleton" style="height:80px"></div></div>
            <div class="hint-text" id="presence-gc-hint">读取群聊插件配置中…</div>
            <div class="human-actions" style="margin-top:12px">
              <button class="btn primary" id="presence-gc-save" disabled>写入群聊配置</button>
            </div>
          </div>
        </div>`;
      bindInstance(view);
      const refresh = view.querySelector("#presence-radar-refresh");
      if (refresh) {
        refresh.addEventListener("click", () => loadRadar(view, { withGc: true }).catch((err) => toast(err.message, "err")));
      }
      const save = view.querySelector("#presence-gc-save");
      if (save) save.addEventListener("click", () => saveGc(view).catch((err) => toast(err.message, "err")));
      boot(view, (target) => loadRadar(target))
        .then((ready) => { if (ready) startPoll(view, "radar", refreshRadar); })
        .catch((err) => toast(err.message, "err"));
    }

    /* -------------------------------------------------------- 自我日记 */

    function selectedDiary() {
      return diaries.find((item) => String(item.id) === String(diaryId)) || null;
    }

    function diaryRow(item) {
      const id = String(item.id || "");
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(item.date || "")}</strong>
            ${id === String(diaryId) ? `<span class="badge ok">已选中</span>` : ""}
            <span class="badge">${esc(item.model_id || "未记录模型")}</span>
          </div>
          <div class="auto-meta">
            <span>${esc(String(item.text || "").slice(0, 60))}</span>
            ${item.summary ? `<span>${esc(item.summary)}</span>` : ""}
          </div>
        </div>
        <div class="auto-actions">
          <button class="btn sm ghost" data-diary="${esc(id)}">打开</button>
        </div>
      </article>`;
    }

    function renderDiaryList(view) {
      const box = view.querySelector("#presence-diary-list");
      if (!box) return;
      box.innerHTML = diaries.length
        ? diaries.map(diaryRow).join("")
        : `<div class="empty-inline">还没有日记。到点自动生成，或点「立即生成」。</div>`;
    }

    function renderDiaryEditor(view) {
      const box = view.querySelector("#presence-diary-editor");
      if (!box) return;
      const item = selectedDiary();
      if (!item) {
        box.innerHTML = `<div class="empty-inline">选择左侧日期或点「立即生成」。</div>`;
        return;
      }
      box.innerHTML = `
        <div class="section-head" style="margin:0 0 10px">
          <h2 id="presence-diary-date">${esc(item.date || "")}</h2>
          <span class="side">${esc(item.model_id || "未记录模型")} · 更新 ${esc(fmtTime(item.updated))}</span>
        </div>
        <p class="presence-note" id="presence-diary-summary">${esc(item.summary || "没有摘要")}</p>
        <div class="field"><label>正文（只在本机管理器可见）</label>
          <textarea id="presence-diary-text" rows="12"></textarea></div>
        <div class="human-actions">
          <button class="btn primary" id="presence-diary-save">保存正文</button>
          <button class="btn danger" id="presence-diary-delete">删除日记</button>
        </div>`;
      const text = view.querySelector("#presence-diary-text");
      if (text) {
        text.value = item.text || "";
        text.addEventListener("input", () => { diaryDirty = true; });
      }
      const save = view.querySelector("#presence-diary-save");
      if (save) save.addEventListener("click", () => saveDiary(view).catch((err) => toast(err.message, "err")));
      const del = view.querySelector("#presence-diary-delete");
      if (del) del.addEventListener("click", () => deleteDiary(view).catch((err) => toast(err.message, "err")));
    }

    function applyDiarySettings(view) {
      if (!presenceSettings) return;
      setField(view, "presence-set-diary-enabled", "checked", !!presenceSettings.diary_enabled);
      setField(view, "presence-set-diary-time", "value", presenceSettings.diary_time || "23:30");
      setField(view, "presence-set-diary-inject", "checked", !!presenceSettings.diary_inject_next_day);
    }

    async function loadDiaries(view, options = {}) {
      if (!instId) return;
      const requestInst = instId;
      let items = [];
      let cfg = null;
      try {
        const results = await Promise.all([
          api(`/api/presence/diaries?instance_id=${encodeURIComponent(requestInst)}&limit=60`),
          options.withSettings === false
            ? Promise.resolve(null)
            : api(`/api/presence/settings?instance_id=${encodeURIComponent(requestInst)}`),
        ]);
        items = results[0];
        cfg = results[1];
      } catch (err) {
        if (requestInst === instId) setError(view, `日记读取失败：${err.message}`);
        return;
      }
      if (requestInst !== instId) return;
      diaries = Array.isArray(items) ? items : [];
      if (cfg && typeof cfg === "object") {
        presenceSettings = cfg;
        applyDiarySettings(view);
      }
      if (!diaries.some((item) => String(item.id) === String(diaryId))) {
        diaryId = diaries.length ? String(diaries[0].id) : "";
      }
      diaryDirty = false;
      setError(view, "");
      renderDiaryList(view);
      renderDiaryEditor(view);
    }

    async function refreshDiaries(view) {
      // 用户正在编辑正文时只暂停刷新，避免覆盖未保存的改动。
      if (diaryDirty || isFocused(view, ["presence-diary-text"])) return;
      const requestInst = instId;
      let items = [];
      try {
        items = await api(`/api/presence/diaries?instance_id=${encodeURIComponent(requestInst)}&limit=60`);
      } catch (_) {
        return;
      }
      if (requestInst !== instId || diaryDirty) return;
      diaries = Array.isArray(items) ? items : [];
      if (!diaries.some((item) => String(item.id) === String(diaryId))) {
        diaryId = diaries.length ? String(diaries[0].id) : "";
        renderDiaryEditor(view);
      }
      renderDiaryList(view);
    }

    async function saveDiary(view) {
      const item = selectedDiary();
      if (!item) return toast("先选择一篇日记", "err");
      const text = String((view.querySelector("#presence-diary-text").value || "")).trim();
      if (!text) return toast("日记正文不能为空", "err");
      const saved = await api(`/api/presence/diaries/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        body: { instance_id: instId, text },
      });
      diaryDirty = false;
      if (saved) {
        const index = diaries.findIndex((entry) => String(entry.id) === String(item.id));
        if (index >= 0) diaries[index] = Object.assign({}, diaries[index], saved);
      }
      toast("日记已保存");
      renderDiaryList(view);
      renderDiaryEditor(view);
    }

    async function deleteDiary(view) {
      const item = selectedDiary();
      if (!item) return;
      const ok = await confirmDialog("删除日记", `确定删除 ${item.date} 的日记？删除后不可恢复。`);
      if (!ok) return;
      await api(`/api/presence/diaries/${encodeURIComponent(item.id)}`
        + `?instance_id=${encodeURIComponent(instId)}&confirm=true`, { method: "DELETE" });
      diaryId = "";
      diaryDirty = false;
      toast("日记已删除");
      await loadDiaries(view);
    }

    async function generateDiary(view) {
      if (generating) return;
      generating = true;
      const button = view.querySelector("#presence-diary-generate");
      if (button) { button.disabled = true; button.textContent = "生成中…"; }
      try {
        const result = await api("/api/presence/diaries/generate", {
          method: "POST",
          body: { instance_id: instId },
        });
        if (result && result.skipped) {
          toast(`未生成：${result.reason || "当天事件不足"}`, "warn");
        } else {
          toast(`已生成 ${(result && result.date) || ""} 的日记`);
          if (result && result.diary && result.diary.id) diaryId = String(result.diary.id);
        }
        await loadDiaries(view, { withSettings: false });
      } finally {
        generating = false;
        if (button) { button.disabled = false; button.textContent = "立即生成"; }
      }
    }

    async function saveDiarySettings(view) {
      const body = {
        instance_id: instId,
        diary_enabled: view.querySelector("#presence-set-diary-enabled").checked,
        diary_time: String((view.querySelector("#presence-set-diary-time").value || "")).trim(),
        diary_inject_next_day: view.querySelector("#presence-set-diary-inject").checked,
      };
      const saved = await api("/api/presence/settings", { method: "PUT", body });
      if (saved && typeof saved === "object") {
        presenceSettings = saved;
        applyDiarySettings(view);
      }
      toast("日记设置已保存");
    }

    function bindDiary(view) {
      const list = view.querySelector("#presence-diary-list");
      if (list) {
        list.addEventListener("click", (event) => {
          const node = event.target.closest("[data-diary]");
          if (!node) return;
          diaryId = String((node.dataset || {}).diary || "");
          diaryDirty = false;
          renderDiaryList(view);
          renderDiaryEditor(view);
        });
      }
      const generate = view.querySelector("#presence-diary-generate");
      if (generate) generate.addEventListener("click", () => generateDiary(view).catch((err) => toast(err.message, "err")));
      const save = view.querySelector("#presence-set-diary-save");
      if (save) save.addEventListener("click", () => saveDiarySettings(view).catch((err) => toast(err.message, "err")));
    }

    function renderDiary(view) {
      view.innerHTML = `
        <div class="card">
          <div class="section-head" style="margin:0 0 10px">
            <h2>自我日记</h2><span class="side">只在本机管理器可见，不发给用户、不写记忆</span>
          </div>
          ${instanceField()}
          ${errorBox()}
          <div class="auto-toolbar">
            <div class="left"><span class="hint-text" style="margin:0">每天到点自动生成；也可以立即生成</span></div>
            <div class="right"><button class="btn primary" id="presence-diary-generate">立即生成</button></div>
          </div>
          <div class="auto-list" id="presence-diary-list"><div class="skeleton" style="height:90px"></div></div>
        </div>
        <div class="presence-grid" style="margin-top:16px">
          <div class="card"><div id="presence-diary-editor"><div class="empty-inline">选择左侧日期或点「立即生成」。</div></div></div>
          <div class="card">
            <div class="section-head" style="margin:0 0 10px">
              <h2>日记设置</h2><span class="side">次日只注入一句不含姓名的摘要</span>
            </div>
            <label class="check-row"><input type="checkbox" id="presence-set-diary-enabled"> 每天自动生成</label>
            <div class="field"><label>生成时间（HH:MM）</label>
              <input id="presence-set-diary-time" type="text" placeholder="23:30"></div>
            <label class="check-row"><input type="checkbox" id="presence-set-diary-inject"> 次日影响语气</label>
            <div class="human-actions">
              <button class="btn primary" id="presence-set-diary-save">保存日记设置</button>
            </div>
          </div>
        </div>`;
      bindInstance(view);
      bindDiary(view);
      boot(view, (target) => loadDiaries(target))
        .then((ready) => { if (ready) startPoll(view, "diary", refreshDiaries); })
        .catch((err) => toast(err.message, "err"));
    }

    /* ------------------------------------------------------------ 出口 */

    function render(view, leaf = "loops") {
      leave();
      scope = LEAVES.includes(leaf) ? leaf : "loops";
      if (scope === "relations") return renderRelations(view);
      if (scope === "rhythm") return renderRhythm(view);
      if (scope === "radar") return renderRadar(view);
      if (scope === "diary") return renderDiary(view);
      return renderLoops(view);
    }

    return { render, leave };
  }

  return { create };
});
