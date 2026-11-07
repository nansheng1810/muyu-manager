/* 牧鱼 · 群聊剧场（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerDuet = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STATUS_LABEL = {
    starting: "准备中",
    running: "进行中",
    paused: "已暂停",
    completed: "已完成",
    stopped: "已结束",
    error: "失败",
  };
  const ACTIVE = new Set(["starting", "running", "paused"]);
  const MODE_LABEL = { rounds: "轮数", duration: "时长", auto: "安静自动" };

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }

  function fmtDuration(seconds) {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const rest = value % 60;
    return hours ? `${hours} 小时 ${minutes} 分` : minutes ? `${minutes} 分 ${pad(rest)} 秒` : `${rest} 秒`;
  }

  function statusClass(status) {
    if (status === "running") return "ok";
    if (status === "paused" || status === "starting") return "warn";
    if (status === "error") return "bad";
    return "";
  }

  function create(ctx) {
    const { api, esc, icon, toast } = ctx;
    let timer = null;
    let status = null;
    let scenes = [];
    let instancesReady = false;
    let autoReady = false;
    let turnsKey = "";
    let detailId = "";
    let refreshTicks = 0;

    function speakerName(scene, turn) {
      if (turn.speaker_name) return turn.speaker_name;
      if (turn.speaker === "human") return "群友";
      if (turn.speaker === "system") return "系统";
      const names = (scene && scene.config && scene.config.names) || {};
      return names[turn.speaker] || turn.speaker || "—";
    }

    function instanceHtml(inst) {
      const ok = inst.reachable && inst.qq_connected && inst.self_qq;
      const state = !inst.reachable ? "不可用" : inst.qq_connected ? "在线" : "QQ 未连接";
      const peer = (inst.peer_qqs || []).join("、") || "未配置";
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title">
            <strong>${esc(inst.name)}</strong>
            <span class="badge ${ok ? "ok" : "bad"}">${esc(state)}</span>
            ${inst.reachable
              ? (inst.filter_enabled
                ? `<span class="badge">防循环已开</span>`
                : `<span class="badge bad">防循环关闭</span>`)
              : `<span class="badge">插件不可达</span>`}
          </div>
          <div class="auto-meta">
            <span>QQ <b>${esc(inst.self_qq || "—")}</b></span>
            <span>昵称 <b>${esc(inst.nickname || "—")}</b></span>
            <span>对端 <b>${esc(peer)}</b></span>
          </div>
          ${inst.error ? `<p class="approval-reason">${esc(inst.error)}</p>` : ""}
        </div>
      </article>`;
    }

    function instancesHtml(data) {
      return (data.instances || []).map(instanceHtml).join("") ||
        `<div class="empty-inline">没有配置机器人。</div>`;
    }

    function turnHtml(scene, turn) {
      const name = speakerName(scene, turn);
      const isHuman = turn.speaker === "human";
      const isError = turn.status === "error";
      const tag = isError
        ? `<span class="badge bad">失败</span>`
        : isHuman
          ? `<span class="badge warn">群友发言</span>`
          : "";
      return `<div class="duet-turn ${isHuman ? "human" : ""} ${isError ? "bad" : ""}">
        <div class="duet-turn-head">
          <strong>${esc(name)}</strong>
          <span class="side">${esc(fmtTime(turn.created))}</span>
          ${tag}
        </div>
        <p>${esc(turn.text || "")}</p>
      </div>`;
    }

    function transcriptHtml(scene) {
      const turns = (scene && scene.turns) || [];
      if (!turns.length) return `<div class="empty-inline">还没有发言。开始场景后，两个机器人会按各自人格轮流说话。</div>`;
      return turns.map((turn) => turnHtml(scene, turn)).join("");
    }

    function timingHtml(scene) {
      if (!scene) return "";
      const created = Number(scene.created) || 0;
      const now = Date.now() / 1000;
      const active = ACTIVE.has(scene.status);
      const parts = [`开始 ${esc(fmtTime(created))}`];
      if (active) parts.push(`已运行 ${esc(fmtDuration(now - created))}`);
      const config = scene.config || {};
      if (scene.mode === "duration" || config.mode === "duration") {
        const duration = Number(config.duration_seconds || 0);
        if (duration) {
          parts.push(`时长上限 ${esc(fmtDuration(duration))}`);
        }
      } else if (config.rounds) {
        parts.push(`轮数 ${esc(config.rounds)}`);
      }
      if (config.interval) parts.push(`间隔 ${esc(config.interval)} 秒`);
      return parts.join(" · ");
    }

    function sceneControls(scene) {
      if (!scene) return "";
      const active = ACTIVE.has(scene.status);
      if (!active) return "";
      const buttons = [];
      if (scene.status === "running" || scene.status === "starting") {
        buttons.push(`<button class="btn sm ghost" data-act="pause" data-id="${esc(scene.id)}">${icon("stop")}暂停</button>`);
      }
      if (scene.status === "paused") {
        buttons.push(`<button class="btn sm primary" data-act="resume" data-id="${esc(scene.id)}">${icon("play")}继续</button>`);
      }
      buttons.push(`<button class="btn sm danger" data-act="stop" data-id="${esc(scene.id)}">${icon("stop")}结束</button>`);
      return buttons.join("");
    }

    function activeHtml(scene) {
      if (!scene) {
        return `<div class="empty-inline">还没有场景。填好群号和话题后开始。</div>`;
      }
      return `<article class="auto-row duet-active-row">
        <div class="auto-main">
          <div class="auto-title">
            <strong>${esc(scene.topic || "未命名场景")}</strong>
            <span class="badge ${statusClass(scene.status)}">${esc(STATUS_LABEL[scene.status] || scene.status)}</span>
            <span class="badge">${esc(MODE_LABEL[scene.mode] || scene.mode)}</span>
          </div>
          <div class="auto-meta">
            <span>群 <b>${esc(scene.group_id)}</b></span>
            <span>${timingHtml(scene)}</span>
          </div>
          ${scene.note ? `<p class="approval-reason">${esc(scene.note)}</p>` : ""}
        </div>
        <div class="auto-actions">${sceneControls(scene)}</div>
      </article>`;
    }

    function autoStateHtml(data) {
      const state = data.auto_state || {};
      const auto = data.auto || {};
      const cls = auto.enabled ? (state.eligible ? "ok" : "warn") : "";
      const label = auto.enabled ? (state.eligible ? "可以开始" : state.reason || "等待") : "未开启";
      return `<span class="badge ${cls}">自动：${esc(label)}</span>
        <span class="side">今天 ${esc(state.today_count || 0)} 次 · 静默阈值 ${esc(auto.silence_minutes || 30)} 分钟</span>`;
    }

    function scenesHtml(items) {
      if (!items.length) return `<div class="empty-inline">还没有历史场景。</div>`;
      return items.map((scene) => `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title">
            <strong>${esc(scene.topic || "未命名场景")}</strong>
            <span class="badge ${statusClass(scene.status)}">${esc(STATUS_LABEL[scene.status] || scene.status)}</span>
            <span class="badge">${esc(MODE_LABEL[scene.mode] || scene.mode)}</span>
          </div>
          <div class="auto-meta">
            <span>群 <b>${esc(scene.group_id)}</b></span>
            <span>发言 <b>${esc(scene.turn_count || 0)}</b></span>
            <span>${esc(fmtTime(scene.created))}</span>
          </div>
        </div>
        <div class="auto-actions">
          <button class="btn sm ghost" data-detail="${esc(scene.id)}">查看记录</button>
        </div>
      </article>`).join("");
    }

    function fillInstances(view, data) {
      const list = data.instances || [];
      const selects = ["#duet-inst-a", "#duet-inst-b", "#duet-auto-inst-a", "#duet-auto-inst-b"];
      selects.forEach((selector, index) => {
        const select = view.querySelector(selector);
        if (!select) return;
        const current = select.value;
        select.innerHTML = list.map((inst) =>
          `<option value="${esc(inst.id)}">${esc(inst.name)}${inst.self_qq ? ` · ${esc(inst.self_qq)}` : ""}</option>`).join("");
        const preferred = current || (list[index % Math.max(1, list.length)] || {}).id || "";
        if (preferred) select.value = preferred;
      });
      if (list[1] && view.querySelector("#duet-inst-b") && !view.querySelector("#duet-inst-b").value) {
        view.querySelector("#duet-inst-b").value = list[1].id;
      }
      if (list[1] && view.querySelector("#duet-auto-inst-b") && !view.querySelector("#duet-auto-inst-b").value) {
        view.querySelector("#duet-auto-inst-b").value = list[1].id;
      }
      instancesReady = true;
    }

    function fillAuto(view, auto) {
      const values = auto || {};
      const set = (selector, value) => {
        const el = view.querySelector(selector);
        if (!el) return;
        if (el.type === "checkbox") el.checked = Boolean(value);
        else el.value = value === undefined || value === null ? "" : value;
      };
      set("#duet-auto-enabled", values.enabled);
      set("#duet-auto-group", values.group_id || "");
      set("#duet-auto-topic", values.topic || "");
      set("#duet-auto-silence", values.silence_minutes || 30);
      set("#duet-auto-night-start", values.night_start || "23:00");
      set("#duet-auto-night-end", values.night_end || "08:00");
      set("#duet-auto-daily", values.daily_limit === undefined ? 1 : values.daily_limit);
      set("#duet-auto-cooldown", values.cooldown_minutes || 120);
      set("#duet-auto-rounds", values.rounds || 6);
      set("#duet-auto-interval", values.interval || 15);
      set("#duet-auto-chars", values.max_chars || 80);
      const ids = values.instance_ids || [];
      if (ids[0] && view.querySelector("#duet-auto-inst-a")) view.querySelector("#duet-auto-inst-a").value = ids[0];
      if (ids[1] && view.querySelector("#duet-auto-inst-b")) view.querySelector("#duet-auto-inst-b").value = ids[1];
      autoReady = true;
    }

    function updateFormLock(view, scene) {
      const active = Boolean(scene && ACTIVE.has(scene.status));
      const form = view.querySelector("#duet-start-form");
      if (!form) return;
      form.querySelectorAll("input, select, button").forEach((el) => {
        el.disabled = active;
      });
    }

    function renderStatus(view, data) {
      status = data;
      const strip = view.querySelector("#duet-instance-strip");
      if (strip) strip.innerHTML = instancesHtml(data);
      if (!instancesReady) fillInstances(view, data);
      const reachable = (data.instances || []).filter((item) => item.reachable && item.self_qq).length;
      const meta = view.querySelector("#duet-meta");
      if (meta) meta.textContent = `${(data.instances || []).length} 个实例 · 插件可用 ${reachable}/${(data.instances || []).length}`;

      const scene = data.scene;
      const active = view.querySelector("#duet-active");
      if (active) active.innerHTML = activeHtml(scene);
      updateFormLock(view, scene);

      const key = scene ? `${scene.id}:${(scene.turns || []).length}:${scene.status}` : "";
      if (key !== turnsKey) {
        turnsKey = key;
        const transcript = view.querySelector("#duet-transcript");
        if (transcript) transcript.innerHTML = transcriptHtml(scene);
      }
      const timing = view.querySelector("#duet-scene-meta");
      if (timing) timing.innerHTML = scene ? timingHtml(scene) : "未开始";

      const auto = view.querySelector("#duet-auto-state");
      if (auto) auto.innerHTML = autoStateHtml(data);
      if (!autoReady) fillAuto(view, data.auto);
    }

    async function loadStatus(view) {
      try {
        renderStatus(view, await api("/api/duet/status"));
      } catch (err) {
        const meta = view.querySelector("#duet-meta");
        if (meta) meta.textContent = `状态读取失败：${err.message}`;
      }
    }

    async function loadScenes(view) {
      try {
        scenes = await api("/api/duet/scenes?limit=30");
        const box = view.querySelector("#duet-history-list");
        if (box) box.innerHTML = scenesHtml(scenes || []);
      } catch (err) {
        const box = view.querySelector("#duet-history-list");
        if (box) box.innerHTML = `<div class="empty-inline">${esc(err.message)}</div>`;
      }
    }

    async function act(view, id, action) {
      try {
        await api(`/api/duet/${encodeURIComponent(id)}/${action}`, { method: "POST" });
        toast(action === "pause" ? "已暂停" : action === "resume" ? "已继续" : "已结束");
        turnsKey = "";
        await loadStatus(view);
        await loadScenes(view);
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function startScene(view) {
      const value = (selector) => view.querySelector(selector)?.value;
      const mode = value("#duet-mode") || "rounds";
      const body = {
        mode,
        group_id: String(value("#duet-group") || "").trim(),
        topic: String(value("#duet-topic") || "").trim(),
        interval: Number(value("#duet-interval") || 15),
        max_chars: Number(value("#duet-chars") || 80),
        instance_ids: [value("#duet-inst-a"), value("#duet-inst-b")].filter(Boolean),
      };
      if (mode === "rounds") {
        body.rounds = Number(value("#duet-rounds") || 6);
      } else {
        const minutes = Number(value("#duet-minutes") || 0);
        body.duration_seconds = minutes > 0 ? Math.round(minutes * 60) : null;
      }
      const button = view.querySelector("#duet-start");
      if (button) button.disabled = true;
      try {
        await api("/api/duet/start", { method: "POST", body });
        toast("场景已开始");
        turnsKey = "";
        await loadStatus(view);
        await loadScenes(view);
      } catch (err) {
        toast(err.message, "err");
      } finally {
        const active = status && status.scene && ACTIVE.has(status.scene.status);
        if (button && !active) button.disabled = false;
      }
    }

    async function saveAuto(view) {
      const value = (selector) => view.querySelector(selector)?.value;
      const body = {
        enabled: Boolean(view.querySelector("#duet-auto-enabled")?.checked),
        group_id: String(value("#duet-auto-group") || "").trim(),
        topic: String(value("#duet-auto-topic") || "").trim(),
        silence_minutes: Number(value("#duet-auto-silence") || 30),
        night_start: value("#duet-auto-night-start") || "23:00",
        night_end: value("#duet-auto-night-end") || "08:00",
        daily_limit: Number(value("#duet-auto-daily") || 1),
        cooldown_minutes: Number(value("#duet-auto-cooldown") || 120),
        rounds: Number(value("#duet-auto-rounds") || 6),
        interval: Number(value("#duet-auto-interval") || 15),
        max_chars: Number(value("#duet-auto-chars") || 80),
        instance_ids: [value("#duet-auto-inst-a"), value("#duet-auto-inst-b")].filter(Boolean),
      };
      try {
        await api("/api/duet/auto", { method: "PUT", body });
        toast("自动模式已保存");
        autoReady = false;
        await loadStatus(view);
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function showDetail(view, sceneId) {
      const box = view.querySelector("#duet-history-detail");
      if (!box) return;
      if (detailId === sceneId) {
        detailId = "";
        box.innerHTML = "";
        return;
      }
      detailId = sceneId;
      box.innerHTML = `<div class="skeleton" style="height:80px"></div>`;
      try {
        const scene = await api(`/api/duet/scenes/${encodeURIComponent(sceneId)}`);
        box.innerHTML = `<div class="duet-history-detail">
          <div class="section-head" style="margin:10px 0">
            <h2>${esc(scene.topic || "场景记录")}</h2>
            <span class="side">${esc(fmtTime(scene.created))} · ${esc(scene.group_id)}</span>
          </div>
          <div class="duet-transcript">${transcriptHtml(scene)}</div>
        </div>`;
      } catch (err) {
        box.innerHTML = `<div class="empty-inline">${esc(err.message)}</div>`;
      }
    }

    function bind(view) {
      view.querySelector("#duet-refresh")?.addEventListener("click", () => {
        turnsKey = "";
        loadStatus(view);
        loadScenes(view);
      });
      view.querySelector("#duet-mode")?.addEventListener("change", (event) => {
        const rounds = event.target.value === "rounds";
        view.querySelector("#duet-rounds-field").style.display = rounds ? "" : "none";
        view.querySelector("#duet-minutes-field").style.display = rounds ? "none" : "";
      });
      view.querySelector("#duet-start")?.addEventListener("click", () => startScene(view));
      view.querySelector("#duet-auto-save")?.addEventListener("click", () => saveAuto(view));
      view.addEventListener("click", (event) => {
        const actButton = event.target.closest("[data-act]");
        if (actButton) {
          const id = actButton.dataset.id;
          const action = actButton.dataset.act;
          if (action === "stop") {
            const ask = ctx.confirmDialog
              ? ctx.confirmDialog("结束场景", "结束后两个机器人会立即停止发言。确定结束？")
              : Promise.resolve(window.confirm("结束场景？"));
            ask.then((ok) => { if (ok) act(view, id, action); });
          } else {
            act(view, id, action);
          }
          return;
        }
        const detail = event.target.closest("[data-detail]");
        if (detail) showDetail(view, detail.dataset.detail);
      });
    }

    function render(view) {
      leave();
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left">
            <button class="btn sm ghost" id="duet-refresh">${icon("refresh")}刷新</button>
          </div>
          <div class="right"><span class="side" id="duet-meta">读取状态…</span></div>
        </div>

        <div class="card">
          <div class="section-head" style="margin:0 0 10px">
            <h2>机器人</h2><span class="side">两个实例各用自己的人格与模型</span>
          </div>
          <div class="auto-list" id="duet-instance-strip"><div class="skeleton" style="height:80px"></div></div>
        </div>

        <div class="card" style="margin-top:16px">
          <div class="section-head" style="margin:0 0 10px">
            <h2>当前场景</h2><span class="side" id="duet-scene-meta">未开始</span>
          </div>
          <div id="duet-active"><div class="skeleton" style="height:70px"></div></div>
          <div class="duet-transcript" id="duet-transcript"></div>
        </div>

        <div class="card" style="margin-top:16px">
          <div class="section-head" style="margin:0 0 10px">
            <h2>开始新场景</h2><span class="side">轮数 / 时长两种模式，运行中也可随时暂停或结束</span>
          </div>
          <div id="duet-start-form">
            <div class="form-grid">
              <div class="field"><label>机器人 A</label><select id="duet-inst-a"></select></div>
              <div class="field"><label>机器人 B</label><select id="duet-inst-b"></select></div>
              <div class="field"><label>群号</label><input id="duet-group" type="text" placeholder="例如：123456789" autocomplete="off"></div>
              <div class="field"><label>话题</label><input id="duet-topic" type="text" placeholder="例如：周末去哪儿" autocomplete="off"></div>
              <div class="field"><label>模式</label><select id="duet-mode">
                <option value="rounds">按轮数</option><option value="duration">按时长</option>
              </select></div>
              <div class="field" id="duet-rounds-field"><label>轮数</label><input id="duet-rounds" type="number" min="1" max="20" value="6"></div>
              <div class="field" id="duet-minutes-field" style="display:none"><label>时长（分钟）</label>
                <input id="duet-minutes" type="number" min="1" max="60" placeholder="留空则直到手动结束，最长 60 分钟"></div>
              <div class="field"><label>每轮间隔（秒）</label><input id="duet-interval" type="number" min="5" max="120" value="15"></div>
              <div class="field"><label>单条字数上限</label><input id="duet-chars" type="number" min="20" max="200" value="80"></div>
            </div>
            <div class="auto-toolbar" style="margin:0">
              <div class="left"><button class="btn primary" id="duet-start">${icon("play")}开始场景</button></div>
              <div class="right"><span class="side">开始前会检查两个实例在线、插件可达、防循环已配置；不会 @ 人、不带链接。</span></div>
            </div>
          </div>
        </div>

        <div class="card" style="margin-top:16px">
          <div class="section-head" style="margin:0 0 10px">
            <h2>安静自动</h2><span class="side" id="duet-auto-state"><span class="skeleton" style="display:inline-block;width:120px;height:14px"></span></span>
          </div>
          <div class="form-grid">
            <div class="field"><label>机器人 A</label><select id="duet-auto-inst-a"></select></div>
            <div class="field"><label>机器人 B</label><select id="duet-auto-inst-b"></select></div>
            <div class="field"><label>群号</label><input id="duet-auto-group" type="text" placeholder="自动剧场使用的群" autocomplete="off"></div>
            <div class="field"><label>话题</label><input id="duet-auto-topic" type="text" placeholder="随便聊聊最近发生的事" autocomplete="off"></div>
            <div class="field"><label>静默阈值（分钟）</label><input id="duet-auto-silence" type="number" min="5" max="1440" value="30"></div>
            <div class="field"><label>每日上限（次）</label><input id="duet-auto-daily" type="number" min="0" max="10" value="1"></div>
            <div class="field"><label>夜间静默开始</label><input id="duet-auto-night-start" type="text" placeholder="23:00"></div>
            <div class="field"><label>夜间静默结束</label><input id="duet-auto-night-end" type="text" placeholder="08:00"></div>
            <div class="field"><label>冷却（分钟）</label><input id="duet-auto-cooldown" type="number" min="10" max="1440" value="120"></div>
            <div class="field"><label>自动场景轮数</label><input id="duet-auto-rounds" type="number" min="2" max="12" value="6"></div>
            <div class="field"><label>每轮间隔（秒）</label><input id="duet-auto-interval" type="number" min="5" max="120" value="15"></div>
            <div class="field"><label>单条字数上限</label><input id="duet-auto-chars" type="number" min="20" max="200" value="80"></div>
          </div>
          <div class="auto-toolbar" style="margin:0">
            <div class="left"><label class="checkline"><input id="duet-auto-enabled" type="checkbox"> 开启安静自动</label></div>
            <div class="right"><button class="btn sm primary" id="duet-auto-save">保存自动配置</button></div>
          </div>
        </div>

        <div class="card" style="margin-top:16px">
          <div class="section-head" style="margin:0 0 10px">
            <h2>历史场景</h2><span class="side">最近 30 次</span>
          </div>
          <div class="auto-list" id="duet-history-list"><div class="skeleton" style="height:80px"></div></div>
          <div id="duet-history-detail"></div>
        </div>

        <p class="hint-text">群聊剧场只在页面指定的群里真实发言；群内有人说话会自动暂停，确认后再继续。管理器的防循环配置会在开始时自动写入两个实例的插件。</p>`;
      bind(view);
      loadStatus(view);
      loadScenes(view);
      timer = setInterval(() => {
        if (!view.isConnected) return;
        loadStatus(view);
        refreshTicks += 1;
        if (refreshTicks % 5 === 0) loadScenes(view);
      }, 2000);
    }

    function leave() {
      if (timer) clearInterval(timer);
      timer = null;
      status = null;
      scenes = [];
      instancesReady = false;
      autoReady = false;
      turnsKey = "";
      detailId = "";
      refreshTicks = 0;
    }

    return { render, leave, STATUS_LABEL, MODE_LABEL };
  }

  return { create };
});
