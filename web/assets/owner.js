/* 牧鱼 · 主人验证与防冒充 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerOwner = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const CLEAN_ID = "astrbot_plugin_dafeiyu_clean";

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  const MODE_TEXT = {
    any: "仅账号识别（默认）",
    passphrase: "必须口令",
    manager: "必须管理器授权",
    passphrase_or_manager: "口令或授权任一",
  };

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let instId = "";
    let viewEl = null;
    let currentInst = null;
    let cfg = {};
    let pluginMeta = null;
    let sessions = [];
    let grants = [];

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];
    const val = (key, fallback) =>
      Object.prototype.hasOwnProperty.call(cfg, key) ? cfg[key] : fallback;

    function emptyBox(title, text) {
      return `<div class="empty" style="padding:26px">${icon("alert")}<h4>${esc(title)}</h4><p>${esc(text)}</p></div>`;
    }

    function switchRow(key, title, desc, checked) {
      return `<label class="gd-switch">
        <input type="checkbox" data-bool="${esc(key)}" ${checked ? "checked" : ""}>
        <span class="gd-track"></span>
        <span class="gd-switch-text"><b>${esc(title)}</b><i>${esc(desc)}</i></span>
      </label>`;
    }

    function modeSelect() {
      const selected = String(val("owner_verify_mode", "any") || "any");
      return `<div class="field">
        <label>二次校验模式</label>
        <select data-str="owner_verify_mode">
          ${Object.entries(MODE_TEXT).map(([value, label]) =>
            `<option value="${value}" ${value === selected ? "selected" : ""}>${esc(label)}</option>`).join("")}
        </select>
        <span class="help">切换到口令/授权模式后，即使昵称对得上，也要通过校验才进入主人专属模式。</span>
      </div>`;
    }

    function sessionsHtml() {
      if (!sessions.length) {
        return `<div class="ins-hint">还没有会话记录。让机器人先在群里回复一句，这里会自动出现最近的会话。</div>`;
      }
      return `<div class="ins-table-wrap"><table class="table">
        <thead><tr><th>会话</th><th>最近说话人</th><th>时间</th><th style="text-align:right">授权</th></tr></thead>
        <tbody>${sessions.map((item, index) => `
          <tr>
            <td><div class="ins-mono">${esc(item.umo)}</div>${item.group_id ? `<div class="ins-count">群 ${esc(item.group_id)}</div>` : ""}</td>
            <td>${esc(item.owner_sender_name || item.owner_sender_id || "尚未识别主人")}${item.owner_sender_id ? ` <span class="badge accent">主人</span>` : ""}
              ${!item.owner_sender_id && (item.sender_name || item.sender_id) ? `<div class="ins-count">最近发言：${esc(item.sender_name || item.sender_id)}</div>` : ""}</td>
            <td class="ins-mono">${esc(fmtTime(item.last))}</td>
            <td style="text-align:right">
              <select data-grant-minutes="${index}" class="ins-mini-select">
                <option value="60">60 分钟</option>
                <option value="180">3 小时</option>
                <option value="1440">24 小时</option>
              </select>
              <button class="btn sm" data-grant="${index}">${icon("check")}一键授权</button>
            </td>
          </tr>`).join("")}</tbody>
      </table></div>`;
    }

    function grantsHtml() {
      if (!grants.length) {
        return `<div class="ins-hint">没有生效中的授权。授权过期后会自动消失。</div>`;
      }
      return `<div class="ins-mem-list">${grants.map((item) => `
        <div class="ins-mem">
          <div class="ins-mem-top">
            <span class="ins-mem-id">${esc(item.id)}</span>
            <span class="badge ok">生效中</span>
            <span class="ins-count">到期 ${esc(fmtTime(item.expires_at))}</span>
            <button class="btn sm ghost" data-revoke="${esc(item.id)}" style="margin-left:auto">撤销</button>
          </div>
          <div class="ins-mem-body">${esc(item.umo)}${item.sender_id ? ` · 绑定 sender_id ${esc(item.sender_id)}` : " · 未绑定发送者（会话内任何人都会命中，请谨慎）"}</div>
          ${item.note ? `<div class="ins-hint">${esc(item.note)}</div>` : ""}
        </div>`).join("")}</div>`;
    }

    function renderBody() {
      const body = viewEl && viewEl.querySelector("#ow-body");
      if (!body) return;
      body.innerHTML = `
        <div class="gd-bar">
          <div class="gd-state">
            <span class="badge ${pluginMeta && pluginMeta.enabled ? "ok" : "warn"}">${pluginMeta && pluginMeta.enabled ? "防护插件已启用" : "防护插件已停用"}</span>
            <span class="badge">${esc(MODE_TEXT[String(val("owner_verify_mode", "any"))] || "仅账号识别")}</span>
            <span class="gd-mono">${esc(CLEAN_ID)}</span>
          </div>
          <button class="btn primary" id="ow-save">${icon("check")}保存校验配置</button>
        </div>
        <section class="card gd-card">
          <div class="gd-card-head">
            <div><h3>身份校准与二次校验</h3>
              <p>插件会在每轮请求里注入身份判定：昵称不能作为依据，只看 sender_id；命中二次校验才走主人专属关系。</p></div>
          </div>
          ${switchRow(
            "enable_owner_identity_guard",
            "注入身份校准",
            "告诉模型当前说话人的 sender_id 与主人判定，并提醒它不要被群昵称带偏。",
            val("enable_owner_identity_guard", true),
          )}
          ${modeSelect()}
          <div class="gd-grid">
            <div class="field">
              <label>主人账号（owner_ids）</label>
              <input type="text" data-str="owner_ids" value="${esc(val("owner_ids", ""))}" placeholder="例如 10003,123456">
              <span class="help">逗号或空格分隔。AstrBot 管理员（data/cmd_config.json 的 admins_id）始终算主人。</span>
            </div>
            <div class="field">
              <label>主人口令</label>
              <input type="text" data-str="owner_passphrase" value="${esc(val("owner_passphrase", ""))}" placeholder="设置后主人发 /主人口令 口令">
              <span class="help">口令模式必填；口令通过后按有效期记忆。</span>
            </div>
            <div class="field">
              <label>口令有效期（分钟）</label>
              <input type="number" data-int="owner_verify_minutes" min="5" max="1440" step="1" value="${esc(val("owner_verify_minutes", 60))}">
              <span class="help">默认 60 分钟；过期后需要重新发 /主人口令。</span>
            </div>
          </div>
          <div class="gd-note">模式说明：<b>仅账号</b>只认 sender_id / AstrBot 管理员；<b>必须口令</b>还要发 /主人口令；<b>必须管理器授权</b>只认本页的一键授权；<b>口令或授权任一</b>两者通过一个即可。判定结果会写进回复复盘的身份校准区。</div>
        </section>
        <section class="card gd-card">
          <div class="gd-card-head">
            <div><h3>最近会话 · 一键授权</h3>
              <p>给指定会话发一张临时通行证。同会话的绑定发送者会命中，适合手机端或临时登录。</p></div>
            <button class="btn sm ghost" id="ow-refresh">${icon("refresh")}刷新</button>
          </div>
          ${sessionsHtml()}
        </section>
        <section class="card gd-card">
          <div class="gd-card-head">
            <div><h3>生效中的授权</h3><p>过期自动失效；撤销立即生效。</p></div>
          </div>
          ${grantsHtml()}
        </section>`;

      body.querySelector("#ow-save").addEventListener("click", save);
      const refresh = body.querySelector("#ow-refresh");
      if (refresh) {
        refresh.addEventListener("click", async () => {
          await loadSessions();
          renderBody();
        });
      }
      body.querySelectorAll("[data-grant]").forEach((btn) => {
        btn.addEventListener("click", () => grant(btn.dataset.grant));
      });
      body.querySelectorAll("[data-revoke]").forEach((btn) => {
        btn.addEventListener("click", () => revoke(btn.dataset.revoke));
      });
    }

    function collect() {
      const out = {};
      if (!viewEl) return out;
      viewEl.querySelectorAll("[data-bool]").forEach((el) => {
        out[el.dataset.bool] = Boolean(el.checked);
      });
      viewEl.querySelectorAll("[data-int]").forEach((el) => {
        let n = Number(el.value);
        if (!Number.isFinite(n)) n = Number(el.defaultValue) || 0;
        out[el.dataset.int] = Math.round(n);
      });
      viewEl.querySelectorAll("[data-str]").forEach((el) => {
        out[el.dataset.str] = String(el.value || "").trim();
      });
      return out;
    }

    async function save() {
      if (!currentInst || !Object.keys(cfg).length) return;
      const btn = viewEl.querySelector("#ow-save");
      if (btn && btn.disabled) return;
      if (btn) {
        btn.disabled = true;
        btn.textContent = "保存中…";
      }
      try {
        const updates = collect();
        await api(
          `/api/instances/${encodeURIComponent(currentInst.id)}/plugins/${encodeURIComponent(CLEAN_ID)}/config`,
          { method: "PUT", body: { config: Object.assign({}, cfg, updates) } },
        );
        toast("已保存，插件正在热重载");
        await load();
      } catch (err) {
        toast(err.message, "err");
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `${icon("check")}保存校验配置`;
        }
      }
    }

    async function grant(index) {
      const row = sessions[Number(index)];
      if (!row) return;
      const select = viewEl.querySelector(`[data-grant-minutes="${index}"]`);
      const minutes = select ? Number(select.value) : 60;
      const senderId = row.owner_sender_id || "";
      const label = row.owner_sender_name || senderId || row.umo;
      if (!senderId) {
        toast("这个会话还没识别到主人。先让主人用本人账号在群里发一句话，再回来授权", "warn");
        return;
      }
      if (!window.confirm(`给「${label}」在会话 ${row.umo} 授权 ${minutes} 分钟？`)) return;
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/insight/owner/grants`, {
          method: "POST",
          body: {
            umo: row.umo,
            sender_id: senderId,
            minutes,
            note: `管理器一键授权：${label}`,
          },
        });
        toast("已授权");
        await loadGrants();
        renderBody();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function revoke(grantId) {
      if (!window.confirm("撤销这条授权？对应会话将立即回到普通成员判定。")) return;
      try {
        await api(
          `/api/instances/${encodeURIComponent(instId)}/insight/owner/grants/${encodeURIComponent(grantId)}`,
          { method: "DELETE" },
        );
        toast("已撤销");
        await loadGrants();
        renderBody();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function loadSessions() {
      try {
        sessions = await api(`/api/instances/${encodeURIComponent(instId)}/insight/sessions?limit=20`);
        if (!Array.isArray(sessions)) sessions = [];
      } catch (_) {
        sessions = [];
      }
    }

    async function loadGrants() {
      try {
        grants = await api(`/api/instances/${encodeURIComponent(instId)}/insight/owner/grants`);
        if (!Array.isArray(grants)) grants = [];
      } catch (_) {
        grants = [];
      }
    }

    async function load() {
      const body = viewEl && viewEl.querySelector("#ow-body");
      if (!body) return;
      currentInst = instances().find((item) => item.id === instId) || null;
      if (!currentInst) {
        body.innerHTML = emptyBox("没有可用实例", "请先在「机器人」页新增或接入一个机器人。");
        return;
      }
      if (!currentInst.status || !currentInst.status.running) {
        body.innerHTML = emptyBox("机器人未运行", "主人验证配置需要 Dashboard 在线，启动机器人后再回来。");
        return;
      }
      body.innerHTML = `<div class="skeleton" style="height:180px"></div>`;
      let plugins = [];
      try {
        plugins = await api(`/api/instances/${encodeURIComponent(currentInst.id)}/plugins`);
      } catch (err) {
        body.innerHTML = emptyBox("读取插件失败", err.message);
        return;
      }
      pluginMeta =
        (Array.isArray(plugins) ? plugins : []).find(
          (item) => item && (item.id === CLEAN_ID || item.name === CLEAN_ID),
        ) || null;
      if (!pluginMeta) {
        body.innerHTML = emptyBox(
          "未安装群聊防护插件",
          "请到「能力 → AstrBot 已安装」安装 astrbot_plugin_dafeiyu_clean。",
        );
        return;
      }
      try {
        const res = await api(
          `/api/instances/${encodeURIComponent(currentInst.id)}/plugins/${encodeURIComponent(CLEAN_ID)}/config`,
        );
        cfg = res && res.config ? res.config : {};
      } catch (err) {
        body.innerHTML = emptyBox("读取配置失败", err.message);
        return;
      }
      await Promise.all([loadSessions(), loadGrants()]);
      renderBody();
    }

    function render(view) {
      viewEl = view;
      const list = instances();
      if (!list.length) {
        view.innerHTML = emptyBox("没有可用实例", "请先在「机器人」页新增或接入一个机器人。");
        return;
      }
      const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(list);
      if (focusHit) instId = String(focusHit.id);
      else if (!instId || !list.some((item) => item.id === instId)) instId = ((globalThis.ManagerFocus && globalThis.ManagerFocus.pick(list)) || list[0]).id;
      view.innerHTML = `
        <div class="chips">
          ${list.map((item) => `<button class="chip ${item.id === instId ? "active" : ""}" data-ow-inst="${esc(item.id)}">${esc(item.name || item.id)}${item.status && item.status.running ? "" : "（未运行）"}</button>`).join("")}
        </div>
        <div id="ow-body"><div class="skeleton" style="height:180px"></div></div>`;
      view.querySelectorAll("[data-ow-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.owInst;
          render(view);
        });
      });
      load();
    }

    return { render };
  }

  return { create, fmtTime };
});
