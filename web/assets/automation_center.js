/* 牧鱼 · 自动化中心：内置巡检、DSH 技能任务与实时监控 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerAutomationCenter = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const KIND_LABEL = {
    backup: "备份",
    digest: "舰队日报",
    memory_sleep: "记忆睡眠",
    bili_proactive: "B站主动刷",
    douyin_proactive: "抖音主动刷",
    dsh_workflow: "DSH 工作流",
    dsh_prompt: "DSH 技能任务",
    health_patrol: "健康巡检",
    resource_scan: "资源采样",
    drift_scan: "一致性扫描",
    canary_patrol: "端到端巡检",
    workflow: "工作流",
  };
  const GROUP_ORDER = ["维护", "巡检", "DSH 技能", "自定义"];
  const POLL_MS = 3000;
  const MAX_LOG_ROWS = 200;

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function fmtClock(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "--:--:--";
    const date = new Date(value * 1000);
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }

  function groupTasks(tasks) {
    const buckets = {};
    (tasks || []).forEach((task) => {
      const group = task.group || "自定义";
      (buckets[group] = buckets[group] || []).push(task);
    });
    const names = GROUP_ORDER.filter((name) => buckets[name] && buckets[name].length)
      .concat(Object.keys(buckets).filter((name) => !GROUP_ORDER.includes(name)));
    return names.map((name) => ({ name, items: buckets[name] }));
  }

  function successRate(stats) {
    const total = Number(stats?.runs_24h || 0);
    if (!total) return "—";
    return `${Math.round((Number(stats?.success_24h || 0) / total) * 100)}%`;
  }

  function create(ctx) {
    const { api, esc, icon, toast, openModal, closeModal, confirmDialog } = ctx;
    let overview = null;
    let lastId = 0;
    let timer = null;
    let viewEl = null;
    let loading = false;
    let paused = false;
    let busy = false;

    const severity = (value) => {
      const text = String(value || "").toLowerCase();
      if (text === "critical" || text === "bad" || text === "error") return "bad";
      if (text === "warn" || text === "warning") return "warn";
      return "ok";
    };

    function statusClass(task) {
      const status = String(task.last_status || "");
      if (status === "failed") return "bad";
      if (status === "running") return "warn";
      if (task.enabled && !status) return "";
      if (status === "success") return "ok";
      return "";
    }

    function statHtml() {
      const stats = overview?.stats || {};
      const dsh = overview?.dsh || {};
      const failed = Number(stats.failed_24h || 0);
      const dshText = dsh.ready ? "就绪" : dsh.running ? "运行中·未就绪" : "未运行";
      const dshClass = dsh.ready ? "ok" : dsh.running ? "warn" : "bad";
      const sched = stats.scheduler_alive
        ? `<span class="ac-live"><i></i>调度器运行中</span>`
        : `<span class="ac-live off"><i></i>调度器未启动</span>`;
      return `
        <div class="ac-stat"><div class="k">已启用任务</div>
          <div class="v">${Number(stats.enabled || 0)}<small>/ ${Number(stats.total || 0)}</small></div>
          <div class="hint">下一次 ${esc(fmtTime(stats.next_run))}</div></div>
        <div class="ac-stat"><div class="k">24 小时运行</div>
          <div class="v">${Number(stats.runs_24h || 0)}<small>次</small></div>
          <div class="hint">成功 ${Number(stats.success_24h || 0)} · 失败 ${failed}</div></div>
        <div class="ac-stat"><div class="k">成功率</div>
          <div class="v">${esc(successRate(stats))}</div>
          <div class="hint">按最近 24 小时运行记录计算</div></div>
        <div class="ac-stat"><div class="k">异常任务</div>
          <div class="v ${failed ? "bad-text" : ""}">${failed}<small>个</small></div>
          <div class="hint">${failed ? "查看下方红色状态任务" : "最近 24 小时无失败"}</div></div>
        <div class="ac-stat"><div class="k">DSH</div>
          <div class="v ${dshClass === "bad" ? "bad-text" : ""}">${esc(dshText)}</div>
          <div class="hint">${Number((dsh.skills || []).length)} 个已安装技能 ${sched}</div></div>`;
    }

    function taskMeta(task) {
      const last = task.last_status === "failed"
        ? `<span class="ac-last bad-text">${esc(task.last_summary || "最近一次失败")}</span>`
        : task.last_summary
          ? `<span class="ac-last">${esc(task.last_summary)}</span>`
          : "";
      return `<div class="auto-meta">
        <span>调度 <b>${esc(task.schedule)}</b></span>
        <span>下次 <b>${esc(fmtTime(task.next_run))}</b></span>
        <span>上次 <b>${esc(fmtTime(task.last_run))}</b></span>
        ${task.last_status ? `<span>最近 <b>${esc(task.last_status === "success" ? "成功" : task.last_status === "running" ? "执行中" : "失败")}</b></span>` : ""}
        ${last}
      </div>`;
    }

    function taskHtml(task) {
      const enabled = Boolean(task.enabled);
      const builtin = Boolean(task.builtin);
      return `<article class="ac-task ${statusClass(task)}" data-task="${esc(task.id)}">
        <div class="ac-task-head">
          <i class="ac-dot ${statusClass(task)}"></i>
          <strong>${esc(task.name)}</strong>
          <span class="badge accent">${esc(KIND_LABEL[task.kind] || task.kind)}</span>
          <span class="badge ${enabled ? "ok" : ""}">${enabled ? "已启用" : "已停用"}</span>
          ${builtin ? `<span class="badge">内置</span>` : ""}
        </div>
        ${task.desc ? `<p class="ac-task-desc">${esc(task.desc)}</p>` : ""}
        ${taskMeta(task)}
        <div class="ac-task-foot">
          <button class="btn xs ghost" data-toggle="${esc(task.id)}">${enabled ? "停用" : "启用"}</button>
          <button class="btn xs primary" data-run="${esc(task.id)}">${icon("play")}立即执行</button>
          <button class="btn xs ghost" data-edit="${esc(task.id)}">${icon("edit")}编辑</button>
          ${builtin ? "" : `<button class="btn xs danger" data-delete="${esc(task.id)}">${icon("trash")}</button>`}
        </div>
      </article>`;
    }

    function tasksHtml() {
      const tasks = overview?.tasks || [];
      if (!tasks.length) {
        return `<div class="empty" style="padding:30px">${icon("refresh")}<h4>还没有自动化任务</h4>
          <p>刷新页面会自动补种内置巡检任务。</p></div>`;
      }
      return groupTasks(tasks).map((group) => `
        <section class="ac-group">
          <div class="ac-group-head"><h3>${esc(group.name)}</h3><span>${group.items.length}</span></div>
          <div class="ac-task-grid">${group.items.map(taskHtml).join("")}</div>
        </section>`).join("");
    }

    function skillsHtml() {
      const dsh = overview?.dsh || {};
      if (!dsh.running) {
        return `<div class="empty" style="padding:22px">${icon("dsh")}<h4>DSH 未运行</h4>
          <p>启动 DSH 后即可把已安装技能接入定时任务。</p>
          <a class="btn sm ghost" href="#/capDshPlugins">去启动 DSH</a></div>`;
      }
      if (!dsh.ready) {
        return `<div class="empty" style="padding:22px">${icon("alert")}<h4>DSH 尚未就绪</h4>
          <p>${esc(dsh.error || "等待 DSH 完成启动")}</p></div>`;
      }
      const skills = dsh.skills || [];
      if (!skills.length) {
        return `<div class="empty" style="padding:22px">${icon("download")}<h4>还没有已安装技能</h4>
          <p>到 DSH 技能页安装后再回来接入定时执行，也可以直接新建指令任务。</p>
          <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
            <a class="btn sm ghost" href="#/capDshSkills">去安装技能</a>
            <button class="btn sm primary" data-new-dsh>${icon("plus")}新建 DSH 任务</button>
          </div></div>`;
      }
      const tasks = overview?.tasks || [];
      return `<div class="ac-skill-list">${skills.map((skill) => {
        const linked = tasks.find((task) => (task.config || {}).skill === skill.slug);
        return `<div class="ac-skill">
          <div class="ac-skill-main">
            <div class="ac-skill-title"><strong>${esc(skill.name || skill.slug)}</strong>
              <span class="badge">${esc(skill.version || "本地")}</span></div>
            <p>${esc(skill.description || skill.slug)}</p>
            <code>${esc(skill.slug)}</code>
          </div>
          ${linked
            ? `<span class="ac-linked">${icon("check")}已接入「${esc(linked.name)}」</span>`
            : `<button class="btn xs primary" data-skill="${esc(skill.slug)}" data-skill-name="${esc(skill.name || skill.slug)}">${icon("plus")}接入自动化</button>`}
        </div>`;
      }).join("")}</div>`;
    }

    function eventHtml(event) {
      const level = severity(event.severity);
      return `<div class="ac-log" data-event="${Number(event.id)}">
        <time>${esc(fmtClock(event.ts))}</time>
        <i class="ac-dot ${level === "ok" ? "ok" : level}"></i>
        <span class="ac-log-source">${esc(event.source || event.kind || "系统")}</span>
        <span class="ac-log-text">${esc(event.title || "")}</span>
      </div>`;
    }

    function logHtml(events) {
      if (!events.length) return `<div class="ac-log-empty">还没有事件，任务运行后会实时出现在这里。</div>`;
      return events.map(eventHtml).join("");
    }

    function renderAll() {
      if (!viewEl) return;
      const stats = viewEl.querySelector("#ac-stats");
      const tasks = viewEl.querySelector("#ac-tasks");
      const skills = viewEl.querySelector("#ac-skills");
      const sched = viewEl.querySelector("#ac-sched-state");
      const skillCount = viewEl.querySelector("#ac-skill-count");
      if (stats) stats.innerHTML = statHtml();
      if (tasks) tasks.innerHTML = tasksHtml();
      if (skills) skills.innerHTML = skillsHtml();
      if (skillCount) skillCount.textContent = `${Number((overview?.dsh?.skills || []).length)} 个可用`;
      if (sched) {
        sched.innerHTML = `30 秒 tick · 单任务不并发 · 失败退避 1/5/15 分钟 · ` +
          `最近刷新 ${esc(fmtClock(overview?.server_time))}`;
      }
      wireLists();
    }

    function wireLists() {
      viewEl?.querySelectorAll("[data-run]").forEach((btn) =>
        btn.addEventListener("click", () => runNow(btn.dataset.run, btn)));
      viewEl?.querySelectorAll("[data-toggle]").forEach((btn) =>
        btn.addEventListener("click", () => toggle(btn.dataset.toggle)));
      viewEl?.querySelectorAll("[data-edit]").forEach((btn) =>
        btn.addEventListener("click", () => editTask(btn.dataset.edit)));
      viewEl?.querySelectorAll("[data-delete]").forEach((btn) =>
        btn.addEventListener("click", () => removeTask(btn.dataset.delete)));
      viewEl?.querySelectorAll("[data-skill]").forEach((btn) =>
        btn.addEventListener("click", () => createDshTask(btn.dataset.skill, btn.dataset.skillName)));
      viewEl?.querySelectorAll("[data-new-dsh]").forEach((btn) =>
        btn.addEventListener("click", () => createDshTask("", "")));
    }

    async function loadLogs(initial) {
      const payload = await api(`/api/automation/logs?since=${initial ? 0 : lastId}&limit=80`);
      const events = Array.isArray(payload?.events) ? payload.events : [];
      const box = viewEl?.querySelector("#ac-logs");
      if (!box) return;
      if (initial) box.innerHTML = logHtml(events);
      else if (events.length) {
        box.querySelector(".ac-log-empty")?.remove();
        box.insertAdjacentHTML("beforeend", events.map(eventHtml).join(""));
        const rows = box.querySelectorAll(".ac-log");
        for (let index = 0; index < rows.length - MAX_LOG_ROWS; index += 1) rows[index].remove();
      }
      if (payload?.last_id) lastId = Math.max(lastId, Number(payload.last_id));
      if (!paused) box.scrollTop = box.scrollHeight;
    }

    async function load(silent) {
      if (loading) return;
      loading = true;
      if (!silent && viewEl) {
        const tasks = viewEl.querySelector("#ac-tasks");
        if (tasks) tasks.innerHTML = `<div class="skeleton" style="height:180px"></div>`;
      }
      try {
        overview = await api("/api/automation/overview");
        if (!viewEl || !viewEl.isConnected) return;
        renderAll();
        await loadLogs(true);
      } catch (err) {
        const tasks = viewEl?.querySelector("#ac-tasks");
        if (tasks) {
          tasks.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4>
            <p>${esc(err.message)}</p></div>`;
        }
        if (!silent) toast(err.message, "err");
      } finally {
        loading = false;
      }
    }

    async function poll() {
      if (!viewEl || !viewEl.isConnected) return;
      if (document.hidden) return;
      try {
        overview = await api("/api/automation/overview");
        if (!viewEl.isConnected) return;
        renderAll();
        if (!paused) await loadLogs(false);
      } catch (_) {
        /* 轮询失败保持上一屏 */
      }
    }

    async function runNow(id, btn) {
      if (busy) return;
      busy = true;
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = "执行中…";
      try {
        const run = await api(`/api/tasks/${encodeURIComponent(id)}/run`, { method: "POST", body: {} });
        const ok = run?.status === "success";
        toast(ok ? `已完成：${run.summary}` : `失败：${run.summary}`, ok ? "ok" : "err");
      } catch (err) {
        toast(err.message, "err");
      } finally {
        busy = false;
        btn.disabled = false;
        btn.innerHTML = original;
        await poll();
      }
    }

    async function toggle(id) {
      const task = (overview?.tasks || []).find((item) => item.id === id);
      if (!task) return;
      try {
        await api(`/api/tasks/${encodeURIComponent(id)}`, {
          method: "PUT", body: { enabled: !task.enabled },
        });
        toast(task.enabled ? "任务已停用" : "任务已启用");
        await poll();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function removeTask(id) {
      const task = (overview?.tasks || []).find((item) => item.id === id);
      if (!task) return;
      const ok = await confirmDialog("删除任务", `确定删除「${task.name}」？运行历史会保留。`);
      if (!ok) return;
      try {
        await api(`/api/tasks/${encodeURIComponent(id)}`, { method: "DELETE" });
        toast("任务已删除");
        await poll();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function dshFields(task) {
      const config = task.config || {};
      return `
        <div class="form-grid">
          <div class="field"><label>任务名称</label><input id="ac-name" value="${esc(task.name)}"></div>
          <div class="field"><label>技能</label>
            <input id="ac-skill" value="${esc(config.skill_name || config.skill || "")}" readonly
              placeholder="不指定技能，直接执行指令">
            <span class="help">从技能列表接入时会自动绑定，也可在任务中心编辑 config.skill</span></div>
          <div class="field"><label>调度</label>
            <input id="ac-schedule" value="${esc(task.schedule)}" placeholder="09:30 或 every:6h">
            <span class="help">支持 09:30、09:30,21:00、daily、weekly:mon,thu、every:30m</span></div>
          <div class="field"><label>超时（秒）</label>
            <input id="ac-timeout" type="number" min="60" max="1800" step="60" value="${Number(config.timeout_sec || 600)}">
            <span class="help">DSH 单轮最长等待时间，超时会自动取消会话</span></div>
          <div class="field"><label>工作目录（可选）</label>
            <input id="ac-cwd" value="${esc(config.cwd || "")}" placeholder="例如 D:\\项目\\日报"></div>
          <div class="field"><label>指令</label>
            <textarea id="ac-prompt" rows="5" placeholder="告诉 DSH 要做什么">${esc(config.prompt || "")}</textarea>
            <span class="help">执行时会自动在指令前注明使用该技能</span></div>
          <label class="checkline"><input type="checkbox" id="ac-enabled" ${task.enabled ? "checked" : ""}>启用自动调度</label>
        </div>`;
    }

    function readDshFields(root, skill, skillName) {
      return {
        name: root.querySelector("#ac-name").value,
        schedule: root.querySelector("#ac-schedule").value,
        enabled: root.querySelector("#ac-enabled").checked,
        config: {
          skill,
          skill_name: skillName,
          prompt: root.querySelector("#ac-prompt").value,
          cwd: root.querySelector("#ac-cwd").value,
          timeout_sec: Number(root.querySelector("#ac-timeout").value || 600),
        },
      };
    }

    function createDshTask(skill, skillName) {
      const bound = String(skill || "").trim();
      const label = String(skillName || skill || "").trim();
      openModal({
        title: bound ? `接入 DSH 技能 · ${label}` : "新建 DSH 指令任务",
        sub: "任务在后台创建新 DSH 会话执行，结果写入事件流",
        wide: true,
        body: dshFields({
          name: bound ? `DSH · ${label}` : "DSH · 定时指令",
          schedule: "09:00",
          enabled: true,
          config: { skill: bound, skill_name: label, prompt: "", timeout_sec: 600 },
        }),
        footer: `<button class="btn ghost" data-close>取消</button>
          <button class="btn primary" id="ac-save">创建任务</button>`,
        onMount(root) {
          root.querySelector("#ac-save").addEventListener("click", async () => {
            const body = readDshFields(root, bound, label);
            if (!body.config.prompt.trim()) {
              toast("请填写让技能执行的指令", "err");
              return;
            }
            try {
              await api("/api/tasks", { method: "POST", body: { ...body, kind: "dsh_prompt" } });
              closeModal();
              toast("已接入自动化");
              await poll();
            } catch (err) {
              toast(err.message, "err");
            }
          });
        },
      });
    }

    function editTask(id) {
      const task = (overview?.tasks || []).find((item) => item.id === id);
      if (!task) return;
      const isDsh = task.kind === "dsh_prompt";
      const config = task.config || {};
      if (isDsh) {
        openModal({
          title: `编辑 · ${task.name}`,
          sub: "DSH 技能任务",
          wide: true,
          body: dshFields(task),
          footer: `<button class="btn ghost" data-close>取消</button>
            <button class="btn primary" id="ac-save">保存</button>`,
          onMount(root) {
            root.querySelector("#ac-save").addEventListener("click", async () => {
              const body = readDshFields(root, config.skill, config.skill_name || config.skill);
              if (!body.config.prompt.trim()) {
                toast("请填写让技能执行的指令", "err");
                return;
              }
              try {
                await api(`/api/tasks/${encodeURIComponent(id)}`, { method: "PUT", body });
                closeModal();
                toast("任务已保存");
                await poll();
              } catch (err) {
                toast(err.message, "err");
              }
            });
          },
        });
        return;
      }
      const visible = Object.fromEntries(
        Object.entries(config).filter(([key]) => key !== "_failures"),
      );
      openModal({
        title: `编辑 · ${task.name}`,
        sub: task.builtin ? "内置任务可改调度与配置，删除后会在下次刷新时补种" : "自定义任务",
        wide: true,
        body: `
          <div class="form-grid">
            <div class="field"><label>名称</label><input id="ac-name" value="${esc(task.name)}"></div>
            <div class="field"><label>调度</label>
              <input id="ac-schedule" value="${esc(task.schedule)}" placeholder="09:30 或 every:30m">
              <span class="help">支持 09:30、09:30,21:00、daily、weekly:mon,thu、every:30m / every:6h</span></div>
            <div class="field"><label>配置 JSON</label>
              <textarea id="ac-config" rows="5" spellcheck="false" style="font-family:var(--mono);font-size:12px">${esc(JSON.stringify(visible, null, 2))}</textarea></div>
            <label class="checkline"><input type="checkbox" id="ac-enabled" ${task.enabled ? "checked" : ""}>启用自动调度</label>
          </div>`,
        footer: `<button class="btn ghost" data-close>取消</button>
          <button class="btn primary" id="ac-save">保存</button>`,
        onMount(root) {
          root.querySelector("#ac-save").addEventListener("click", async () => {
            let parsed;
            try {
              parsed = JSON.parse(root.querySelector("#ac-config").value || "{}");
            } catch (_) {
              toast("配置不是合法 JSON", "err");
              return;
            }
            try {
              await api(`/api/tasks/${encodeURIComponent(id)}`, {
                method: "PUT",
                body: {
                  name: root.querySelector("#ac-name").value,
                  schedule: root.querySelector("#ac-schedule").value,
                  config: parsed,
                  enabled: root.querySelector("#ac-enabled").checked,
                },
              });
              closeModal();
              toast("任务已保存");
              await poll();
            } catch (err) {
              toast(err.message, "err");
            }
          });
        },
      });
    }

    function render(view) {
      viewEl = view;
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left">
            <button class="btn sm primary" id="ac-refresh">${icon("refresh")}刷新</button>
            <button class="btn sm primary" id="ac-new">${icon("plus")}新建 DSH 任务</button>
            <a class="btn sm ghost" href="#/tasks">${icon("settings")}任务中心</a>
          </div>
          <div class="right"><span class="side" id="ac-sched-state">正在读取调度状态…</span></div>
        </div>
        <div class="ac-stats" id="ac-stats"><div class="skeleton" style="height:86px"></div></div>
        <div class="ac-layout">
          <div class="ac-main" id="ac-tasks"><div class="skeleton" style="height:180px"></div></div>
          <aside class="ac-side">
            <section class="card ac-panel">
              <div class="section-head" style="margin:0 0 10px">
                <h2>DSH 技能</h2><span class="side" id="ac-skill-count"></span>
              </div>
              <div id="ac-skills"><div class="skeleton" style="height:120px"></div></div>
            </section>
            <section class="card ac-panel">
              <div class="section-head" style="margin:0 0 10px">
                <h2>实时日志</h2>
                <button class="btn xs ghost" id="ac-pause">暂停跟随</button>
              </div>
              <div class="ac-logbox" id="ac-logs"><div class="skeleton" style="height:140px"></div></div>
            </section>
          </aside>
        </div>`;
      view.querySelector("#ac-refresh").addEventListener("click", () => load(false));
      view.querySelector("#ac-new").addEventListener("click", () => createDshTask("", ""));
      view.querySelector("#ac-pause").addEventListener("click", (event) => {
        paused = !paused;
        event.currentTarget.textContent = paused ? "继续跟随" : "暂停跟随";
      });
      load(false);
      timer = setInterval(poll, POLL_MS);
    }

    function leave() {
      if (timer) clearInterval(timer);
      timer = null;
      viewEl = null;
    }

    return { render, leave };
  }

  return { create, fmtTime, fmtClock, groupTasks, KIND_LABEL };
});
