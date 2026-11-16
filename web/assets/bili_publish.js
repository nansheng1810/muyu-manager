/* 牧鱼 · B站发布（bili-cli） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerBiliPublish = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const PLUGIN_ID = "astrbot_plugin_bilibili_ai_bot";

  function create(ctx) {
    const { state, api, esc, icon, toast } = ctx;
    const ui = {
      view: null,
      instId: "",
      status: null,
      history: null,
      config: null,
      job: null,
      loginTimer: null,
      loginPolls: 0,
      jobTimer: null,
      loading: false,
    };

    const $ = (sel) => (ui.view ? ui.view.querySelector(sel) : null);

    function pickInstance() {
      const list = state.instances || [];
      const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(list);
      if (focusHit) {
        ui.instId = String(focusHit.id);
        return ui.instId;
      }
      if (ui.instId && list.some((item) => item.id === ui.instId)) return ui.instId;
      ui.instId = ((globalThis.ManagerFocus && globalThis.ManagerFocus.pick(list)) || list[0] || {}).id || "";
      return ui.instId;
    }

    function base() {
      return `/api/instances/${encodeURIComponent(ui.instId)}/bili-publish`;
    }

    function pluginPath(suffix) {
      return `/api/instances/${encodeURIComponent(ui.instId)}/plugins/${PLUGIN_ID}${suffix}`;
    }

    function stopTimers() {
      if (ui.loginTimer) clearInterval(ui.loginTimer);
      if (ui.jobTimer) clearInterval(ui.jobTimer);
      ui.loginTimer = null;
      ui.jobTimer = null;
    }

    function leave() {
      stopTimers();
    }

    async function load() {
      if (!pickInstance() || ui.loading) return;
      ui.loading = true;
      const instId = ui.instId;
      try {
        const [status, history, cfg] = await Promise.all([
          api(`${base()}/status`),
          api(`${base()}/history?limit=30`),
          api(pluginPath("/config")).catch(() => null),
        ]);
        if (ui.instId !== instId) return;
        ui.status = status || {};
        ui.history = history || {};
        ui.config = cfg || {};
        renderBody();
      } catch (err) {
        toast(err.message, "err");
      } finally {
        ui.loading = false;
      }
    }

    function statusBadges(s) {
      const installed = Boolean(s.installed);
      const logged = Boolean(s.logged_in);
      const user = s.user || {};
      return [
        `<span class="badge ${installed ? "ok" : "bad"}">${installed ? "bili-cli 已安装" : "bili-cli 未安装"}</span>`,
        `<span class="badge ${logged ? "ok" : "warn"}">${logged ? `已登录 ${esc(user.name || "")}` : "未登录"}</span>`,
      ].join("");
    }

    function statusCard() {
      const s = ui.status || {};
      const user = s.user || {};
      return `<section class="card">
        <div class="console-card-head">
          <div>
            <div class="console-kicker">BILIBILI PUBLISH</div>
            <h3>B站发布</h3>
            <p class="console-help">用 bili-cli 上传视频；自动发布和手动发布共用同一个 bili-cli 登录态。</p>
          </div>
          <div class="console-actions memory-actions">
            <button class="btn sm ghost" data-bp-refresh>${icon("refresh")}刷新</button>
            <button class="btn sm primary" data-bp-login>${icon("external")}扫码登录</button>
          </div>
        </div>
        <div class="auto-meta" style="gap:8px;flex-wrap:wrap">${statusBadges(s)}</div>
        <div class="bp-status-grid">
          <div><span>版本</span><b>${esc(s.version || "—")}</b></div>
          <div><span>登录用户</span><b>${esc(user.name || "未登录")}${user.mid ? ` · UID ${esc(String(user.mid))}` : ""}</b></div>
          <div class="span2"><span>可执行文件</span><b class="mono">${esc(s.exe || "未找到")}</b></div>
        </div>
        ${s.error ? `<div class="console-warn" style="margin-top:10px"><div>${esc(s.error)}${s.hint ? `：${esc(s.hint)}` : ""}</div></div>` : ""}
        <div id="bp-qr" class="bp-qr" hidden></div>
      </section>`;
    }

    function configCard() {
      const cfg = (ui.config && ui.config.config) || {};
      const enabled = cfg.ENABLE_VIDEO_PUBLISH === true;
      return `<section class="card">
        <div class="console-card-head"><h3>自动发布</h3><span class="side">由 AI Bot 合成后调用 bili-cli</span></div>
        <div class="memory-form-grid">
          <label class="memory-config-field"><span>启用自动制作并投稿</span>
            <input type="checkbox" data-bp-cfg="ENABLE_VIDEO_PUBLISH" ${enabled ? "checked" : ""}>
            <small>关闭后只保留手动发布。</small>
          </label>
          <label class="memory-config-field"><span>每天最多投稿</span>
            <input type="number" min="0" max="5" data-bp-cfg="VIDEO_PUBLISH_DAILY_COUNT" value="${esc(cfg.VIDEO_PUBLISH_DAILY_COUNT ?? 1)}">
            <small>0 表示当天不自动投稿。</small>
          </label>
          <label class="memory-config-field"><span>每天制作次数</span>
            <input type="number" min="0" max="4" data-bp-cfg="VIDEO_PUBLISH_TIMES_COUNT" value="${esc(cfg.VIDEO_PUBLISH_TIMES_COUNT ?? 1)}">
            <small>无固定时刻时在 10-22 点间随机排布。</small>
          </label>
          <label class="memory-config-field span2"><span>bili-cli 路径</span>
            <input type="text" data-bp-cfg="BILI_CLI_PATH" value="${esc(cfg.BILI_CLI_PATH || "")}" placeholder="留空自动查找 PATH 与 %USERPROFILE%\\.local\\bin">
            <small>未安装时先运行 uv tool install bili-agent。</small>
          </label>
        </div>
        <div class="console-actions" style="margin-top:12px">
          <button class="btn primary" data-bp-save>保存自动发布参数</button>
          <span class="console-help">保存会写入插件配置并重载插件；不影响私信/直播设置。</span>
        </div>
      </section>`;
    }

    function publishCard() {
      const pending = (ui.history && ui.history.legacy_pending) || {};
      return `<section class="card">
        <div class="console-card-head"><h3>手动发布</h3><span class="side">选择本地视频，上传后交给 bili-cli</span></div>
        ${pending.title ? `<div class="bp-legacy"><b>旧待发布：</b>${esc(pending.title)}${pending.exists ? "" : "（文件已不存在）"}<br><span class="mono">${esc(pending.video_path || "")}</span></div>` : ""}
        <div class="bp-form">
          <label class="span2">视频文件<input type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm,.mp4,.mov,.mkv,.flv,.avi" data-bp-file></label>
          <label>标题<input type="text" maxlength="80" data-bp-title placeholder="必填，最多 80 字"></label>
          <label>标签<input type="text" data-bp-tags placeholder="逗号分隔，至少 1 个"></label>
          <label class="span2">简介<textarea rows="3" maxlength="2000" data-bp-desc placeholder="可选"></textarea></label>
          <label>分区 ID<input type="number" data-bp-tid placeholder="留空按标题自动预测"></label>
          <label>文件大小<span class="bp-file-size" data-bp-size>未选择</span></label>
        </div>
        <div class="console-actions" style="margin-top:12px">
          <button class="btn primary" data-bp-publish>${icon("check")}上传并发布到B站</button>
          <span class="console-help">默认带“含AI生成内容”声明；601/验证码会停止并提示。</span>
        </div>
        <div id="bp-job" class="bp-job" hidden></div>
      </section>`;
    }

    function historyCard() {
      const items = (ui.history && ui.history.items) || [];
      if (!items.length) {
        return `<section class="card"><div class="console-card-head"><h3>发布记录</h3></div><div class="memory-empty-inline">还没有发布记录。</div></section>`;
      }
      return `<section class="card">
        <div class="console-card-head"><h3>发布记录</h3><span class="side">自动发布 + 旧创作，最近 30 条</span></div>
        <div class="bp-history">${items.map((item) => `<article class="bp-history-row">
          <div><b>${esc(item.title || "未命名")}</b><span>${esc(item.time || "")} · ${esc(item.source || "")}</span></div>
          <div>${item.bvid ? `<a class="mono" href="https://www.bilibili.com/video/${esc(item.bvid)}" target="_blank" rel="noopener">${esc(item.bvid)}</a>` : "—"}</div>
        </article>`).join("")}</div>
      </section>`;
    }

    function renderBody() {
      const target = $("#bp-body");
      if (!target) return;
      target.innerHTML = `${statusCard()}${configCard()}${publishCard()}${historyCard()}`;
      bindBody();
    }

    function bindBody() {
      $("[data-bp-refresh]")?.addEventListener("click", () => load());
      $("[data-bp-login]")?.addEventListener("click", startLogin);
      $("[data-bp-save]")?.addEventListener("click", saveConfig);
      $("[data-bp-publish]")?.addEventListener("click", publish);
      $("[data-bp-file]")?.addEventListener("change", (event) => {
        const file = event.target.files && event.target.files[0];
        const box = $("[data-bp-size]");
        if (box) box.textContent = file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "未选择";
        if (file && !$("[data-bp-title]").value) {
          $("[data-bp-title]").value = file.name.replace(/\.[^.]+$/, "").slice(0, 80);
        }
      });
    }

    async function startLogin() {
      const box = $("#bp-qr");
      if (!box) return;
      try {
        const data = await api(`${base()}/login`, { method: "POST" });
        const url = data.qr_data_url || "";
        const link = data.qr_url || "";
        box.hidden = false;
        box.innerHTML = `${url ? `<img src="${esc(url)}" alt="B站登录二维码">` : ""}
          <div><b>用B站 App 扫码登录</b><p>二维码 180 秒内有效${link ? `，也可以打开：<a href="${esc(link)}" target="_blank" rel="noopener">登录链接</a>` : ""}</p>
          <span class="side" data-bp-login-note>等待扫码…</span></div>`;
        pollLogin();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function pollLogin() {
      if (ui.loginTimer) clearInterval(ui.loginTimer);
      ui.loginPolls = 0;
      ui.loginTimer = setInterval(async () => {
        ui.loginPolls += 1;
        if (ui.loginPolls > 75) {
          stopTimers();
          const note = $("[data-bp-login-note]");
          if (note) note.textContent = "二维码已过期，请重新获取";
          return;
        }
        try {
          const data = await api(`${base()}/login/status`);
          if (data.logged_in) {
            stopTimers();
            toast("bili-cli 登录成功");
            await load();
            return;
          }
          const detail = data.detail || {};
          const note = $("[data-bp-login-note]");
          if (note) note.textContent = detail.scanned ? "已扫码，等待手机确认…" : "等待扫码…";
        } catch (_) {
          // 管理器/网络短暂不可用，继续轮询
        }
      }, 2500);
    }

    async function saveConfig() {
      try {
        const latest = await api(pluginPath("/config"));
        const config = { ...((latest && latest.config) || {}) };
        const enabled = $('[data-bp-cfg="ENABLE_VIDEO_PUBLISH"]');
        if (enabled) config.ENABLE_VIDEO_PUBLISH = enabled.checked;
        const daily = $('[data-bp-cfg="VIDEO_PUBLISH_DAILY_COUNT"]');
        if (daily) config.VIDEO_PUBLISH_DAILY_COUNT = Math.max(0, Math.min(5, Number(daily.value) || 0));
        const times = $('[data-bp-cfg="VIDEO_PUBLISH_TIMES_COUNT"]');
        if (times) config.VIDEO_PUBLISH_TIMES_COUNT = Math.max(0, Math.min(4, Number(times.value) || 0));
        const exe = $('[data-bp-cfg="BILI_CLI_PATH"]');
        if (exe) config.BILI_CLI_PATH = exe.value.trim();
        await api(pluginPath("/config"), { method: "PUT", body: { config } });
        toast("自动发布参数已保存");
        await load();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function setJobView(job) {
      const box = $("#bp-job");
      if (!box) return;
      if (!job) {
        box.hidden = true;
        return;
      }
      box.hidden = false;
      const elapsed = Math.max(0, Math.round((job.finished || Date.now() / 1000) - (job.started || Date.now() / 1000)));
      const label = { queued: "排队中", running: "上传中", success: "发布成功", error: "发布失败" }[job.status] || job.status;
      box.className = `bp-job ${job.status === "success" ? "ok" : job.status === "error" ? "bad" : ""}`;
      box.innerHTML = `<b>${esc(label)}</b><span>${esc(job.message || "")}</span>
        ${job.bvid ? `<a href="https://www.bilibili.com/video/${esc(job.bvid)}" target="_blank" rel="noopener">${esc(job.bvid)}</a>` : ""}
        <span class="side">${elapsed} 秒</span>`;
    }

    function pollJob(jobId) {
      if (ui.jobTimer) clearInterval(ui.jobTimer);
      ui.jobTimer = setInterval(async () => {
        try {
          const job = await api(`${base()}/jobs/${encodeURIComponent(jobId)}`);
          ui.job = job;
          setJobView(job);
          if (job.status === "success" || job.status === "error") {
            stopTimers();
            await load();
          }
        } catch (_) {
          // 继续等待
        }
      }, 1500);
    }

    async function publish() {
      const file = $("[data-bp-file]")?.files?.[0];
      const title = ($("[data-bp-title]")?.value || "").trim();
      const tags = ($("[data-bp-tags]")?.value || "").trim();
      const desc = ($("[data-bp-desc]")?.value || "").trim();
      const tid = ($("[data-bp-tid]")?.value || "").trim();
      if (!file) return toast("请选择视频文件", "err");
      if (!title) return toast("请填写标题", "err");
      if (!tags) return toast("请至少填写一个标签", "err");
      const btn = $("[data-bp-publish]");
      if (btn) btn.disabled = true;
      try {
        const uploadUrl = `${base()}/files?filename=${encodeURIComponent(file.name)}`;
        const res = await fetch(uploadUrl, { method: "POST", body: file });
        const uploaded = await res.json().catch(() => ({}));
        if (!res.ok || uploaded.status === "error") {
          throw new Error(uploaded.message || `上传失败（HTTP ${res.status}）`);
        }
        const fileId = uploaded.data?.file_id || "";
        if (!fileId) throw new Error("上传没有返回 file_id");
        const job = await api(`${base()}/publish`, {
          method: "POST",
          body: { file_id: fileId, title, tags, desc, tid },
        });
        ui.job = job;
        setJobView(job);
        pollJob(job.id);
      } catch (err) {
        toast(err.message, "err");
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function render(view) {
      ui.view = view;
      pickInstance();
      if (!ui.instId) {
        view.innerHTML = `<div class="empty">${icon("bots")}<h4>暂无机器人</h4><p>先创建一个 AstrBot 实例。</p></div>`;
        return;
      }
      const options = (state.instances || []).map((item) =>
        `<option value="${esc(item.id)}" ${item.id === ui.instId ? "selected" : ""}>${esc(item.name || item.id)}</option>`).join("");
      view.innerHTML = `
        <div class="bp-instance">
          <label>机器人 <select data-bp-inst>${options}</select></label>
        </div>
        <div id="bp-body"><div class="skeleton" style="height:180px"></div></div>`;
      view.querySelector("[data-bp-inst]")?.addEventListener("change", (event) => {
        ui.instId = event.target.value;
        stopTimers();
        ui.status = null;
        ui.history = null;
        ui.config = null;
        load();
      });
      load();
    }

    return { render, leave };
  }

  return { create };
});
