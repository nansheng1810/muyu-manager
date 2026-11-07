/* 牧鱼 · 任务中心（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerTasks = api;
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
  const KIND_HINT = {
    backup: "config 可填 {\"label\":\"scheduled\",\"include_login\":false}",
    digest: "无需配置，运行后写入日报事件",
    memory_sleep: "config 可填 {\"instance_id\":\"机器人 id\"}；留空则自动遍历全部运行中实例",
    bili_proactive: "config 需填 {\"instance_id\":\"...\",\"allow_write\":true}；写操作默认关闭",
    douyin_proactive: "config 需填 {\"instance_id\":\"...\",\"allow_write\":true}；写操作默认关闭",
    dsh_workflow: "暂未接入统一调度，请到 DSH 页面手动执行",
    dsh_prompt: "config 需填 {\"skill\":\"技能 slug\",\"prompt\":\"要做什么\",\"timeout_sec\":600}",
    health_patrol: "无需配置，强制刷新健康检查并汇总告警",
    resource_scan: "无需配置，记录 CPU、内存、磁盘与实例进程占用",
    drift_scan: "无需配置，对比实例之间的插件、模型与人格差异",
    canary_patrol: "无需配置，执行只读端到端巡检",
    workflow: "config 填 {\"steps\":[{\"kind\":\"backup\",\"config\":{}},{\"kind\":\"digest\",\"config\":{}}]}；按顺序执行，失败即停",
  };

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function create(ctx) {
    const { api, esc, icon, toast, openModal, closeModal, confirmDialog } = ctx;
    let tasks = [];
    let runs = [];
    let loading = false;

    function metaText(task) {
      const config = task.config || {};
      const failures = Number(config._failures || 0);
      return [
        `<span>调度 <b>${esc(task.schedule)}</b></span>`,
        `<span>下次 <b>${esc(fmtTime(task.next_run))}</b></span>`,
        `<span>上次 <b>${esc(fmtTime(task.last_run))}</b></span>`,
        failures ? `<span>连续失败 <b>${failures}</b> 次</span>` : "",
      ].filter(Boolean).join("");
    }

    function configPreview(config) {
      const visible = Object.fromEntries(
        Object.entries(config || {}).filter(([key]) => key !== "_failures"),
      );
      if (!Object.keys(visible).length) return "";
      const text = JSON.stringify(visible);
      return text.length > 200 ? text.slice(0, 200) + "…" : text;
    }

    function taskRow(task) {
      return `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title">
            <strong>${esc(task.name)}</strong>
            <span class="badge accent">${esc(KIND_LABEL[task.kind] || task.kind)}</span>
            <span class="badge ${task.enabled ? "ok" : ""}">${task.enabled ? "已启用" : "已停用"}</span>
          </div>
          <div class="auto-meta">${metaText(task)}</div>
          ${configPreview(task.config) ? `<code class="auto-code">${esc(configPreview(task.config))}</code>` : ""}
        </div>
        <div class="auto-actions">
          <button class="btn sm ghost" data-toggle="${esc(task.id)}">${task.enabled ? "停用" : "启用"}</button>
          <button class="btn sm primary" data-run="${esc(task.id)}">${icon("play")}立即执行</button>
          <button class="btn sm ghost" data-edit="${esc(task.id)}">${icon("edit")}编辑</button>
          <button class="btn sm danger" data-delete="${esc(task.id)}">${icon("trash")}</button>
        </div>
      </article>`;
    }

    function runRow(run) {
      const status = run.status === "success" ? "ok" : run.status === "running" ? "warn" : "bad";
      return `<div class="digest-item">
        <div class="time">${esc(fmtTime(run.started))}</div>
        <div class="body"><b>${esc(run.summary || "—")}</b>
          <div class="sub">${esc(run.task_id)} · ${esc(run.id)}</div></div>
        <span class="badge ${status}">${esc(run.status)}</span>
      </div>`;
    }

    function listHtml() {
      if (!tasks.length) {
        return `<div class="empty" style="padding:30px">${icon("play")}<h4>还没有任务</h4>
          <p>新建一个定时任务，或启用内置的每日备份/日报任务。</p></div>`;
      }
      return `<div class="auto-list">${tasks.map(taskRow).join("")}</div>`;
    }

    function historyHtml() {
      if (!runs.length) return `<div class="empty" style="padding:18px"><p>还没有运行记录</p></div>`;
      return `<div class="digest-list">${runs.map(runRow).join("")}</div>`;
    }

    async function load(view, silent = false) {
      if (loading) return;
      loading = true;
      if (!silent) {
        const box = view.querySelector("#task-list");
        if (box) box.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
      }
      try {
        const [taskData, runData] = await Promise.all([
          api("/api/tasks"),
          api("/api/tasks/runs?limit=60"),
        ]);
        if (!view.isConnected) return;
        tasks = Array.isArray(taskData) ? taskData : [];
        runs = Array.isArray(runData) ? runData : [];
        const box = view.querySelector("#task-list");
        if (box) box.innerHTML = listHtml();
        const history = view.querySelector("#task-history");
        if (history) history.innerHTML = historyHtml();
        wire(view);
      } catch (err) {
        const box = view.querySelector("#task-list");
        if (box) box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取失败</h4><p>${esc(err.message)}</p></div>`;
        toast(err.message, "err");
      } finally {
        loading = false;
      }
    }

    function wire(view) {
      view.querySelectorAll("[data-run]").forEach((btn) =>
        btn.addEventListener("click", () => runNow(view, btn.dataset.run, btn)));
      view.querySelectorAll("[data-toggle]").forEach((btn) =>
        btn.addEventListener("click", () => toggle(view, btn.dataset.toggle)));
      view.querySelectorAll("[data-edit]").forEach((btn) =>
        btn.addEventListener("click", () => edit(view, btn.dataset.edit)));
      view.querySelectorAll("[data-delete]").forEach((btn) =>
        btn.addEventListener("click", () => remove(view, btn.dataset.delete)));
    }

    async function runNow(view, id, btn) {
      btn.disabled = true;
      const original = btn.innerHTML;
      btn.innerHTML = "执行中…";
      try {
        const run = await api(`/api/tasks/${encodeURIComponent(id)}/run`, { method: "POST", body: {} });
        toast(run.status === "success" ? `已完成：${run.summary}` : `失败：${run.summary}`,
          run.status === "success" ? "ok" : "err");
      } catch (err) {
        toast(err.message, "err");
      } finally {
        btn.disabled = false;
        btn.innerHTML = original;
        load(view, true);
      }
    }

    async function toggle(view, id) {
      const task = tasks.find((item) => item.id === id);
      if (!task) return;
      try {
        await api(`/api/tasks/${encodeURIComponent(id)}`, {
          method: "PUT", body: { enabled: !task.enabled },
        });
        toast(task.enabled ? "任务已停用" : "任务已启用");
        await load(view, true);
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function edit(view, id) {
      const task = tasks.find((item) => item.id === id);
      if (!task) return;
      openModal({
        title: `编辑任务 · ${task.name}`,
        sub: "调度只支持受限时间表达，不支持 cron 全语法",
        wide: true,
        body: `
          <div class="form-grid">
            <div class="field"><label>名称</label><input id="task-name" value="${esc(task.name)}"></div>
            <div class="field"><label>类型</label><select id="task-kind">
              ${Object.entries(KIND_LABEL).map(([value, label]) =>
                `<option value="${value}" ${value === task.kind ? "selected" : ""}>${esc(label)}</option>`).join("")}
            </select></div>
            <div class="field"><label>调度</label>
              <input id="task-schedule" value="${esc(task.schedule)}" placeholder="09:30 或 daily 或 every:30m">
              <span class="help">支持 09:30、09:30,21:00、daily、weekly:mon,thu、every:30m / every:6h</span></div>
            <div class="field"><label>配置 JSON</label>
              <textarea id="task-config" rows="6" spellcheck="false" style="font-family:var(--mono);font-size:12px">${esc(JSON.stringify(task.config || {}, null, 2))}</textarea>
              <span class="help" id="task-kind-hint">${esc(KIND_HINT[task.kind] || "")}</span></div>
            <label class="checkline"><input type="checkbox" id="task-enabled" ${task.enabled ? "checked" : ""}>启用自动调度</label>
          </div>`,
        footer: `<button class="btn ghost" data-close>取消</button>
          <button class="btn primary" id="task-save">保存</button>`,
        onMount(root) {
          const kind = root.querySelector("#task-kind");
          kind.addEventListener("change", () => {
            root.querySelector("#task-kind-hint").textContent = KIND_HINT[kind.value] || "";
          });
          root.querySelector("#task-save").addEventListener("click", async () => {
            let config;
            try {
              config = JSON.parse(root.querySelector("#task-config").value || "{}");
            } catch (_) {
              toast("配置不是合法 JSON", "err");
              return;
            }
            try {
              await api(`/api/tasks/${encodeURIComponent(id)}`, {
                method: "PUT",
                body: {
                  name: root.querySelector("#task-name").value,
                  kind: kind.value,
                  schedule: root.querySelector("#task-schedule").value,
                  config,
                  enabled: root.querySelector("#task-enabled").checked,
                },
              });
              closeModal();
              toast("任务已保存");
              await load(view, true);
            } catch (err) {
              toast(err.message, "err");
            }
          });
        },
      });
    }

    function createTask(view) {
      openModal({
        title: "新建任务",
        sub: "任务默认停用，确认无误后再启用",
        wide: true,
        body: `
          <div class="form-grid">
            <div class="field"><label>名称</label><input id="task-name" placeholder="例如：每日备份"></div>
            <div class="field"><label>类型</label><select id="task-kind">
              ${Object.entries(KIND_LABEL).map(([value, label]) =>
                `<option value="${value}">${esc(label)}</option>`).join("")}
            </select></div>
            <div class="field"><label>调度</label>
              <input id="task-schedule" value="daily" placeholder="09:30 或 daily 或 every:30m">
              <span class="help">支持 09:30、09:30,21:00、daily、weekly:mon,thu、every:30m / every:6h</span></div>
            <div class="field"><label>配置 JSON</label>
              <textarea id="task-config" rows="6" spellcheck="false" style="font-family:var(--mono);font-size:12px">{}</textarea>
              <span class="help" id="task-kind-hint">${esc(KIND_HINT.backup)}</span></div>
            <label class="checkline"><input type="checkbox" id="task-enabled">启用自动调度</label>
          </div>`,
        footer: `<button class="btn ghost" data-close>取消</button>
          <button class="btn primary" id="task-save">创建</button>`,
        onMount(root) {
          const kind = root.querySelector("#task-kind");
          kind.addEventListener("change", () => {
            root.querySelector("#task-kind-hint").textContent = KIND_HINT[kind.value] || "";
          });
          root.querySelector("#task-save").addEventListener("click", async () => {
            let config;
            try {
              config = JSON.parse(root.querySelector("#task-config").value || "{}");
            } catch (_) {
              toast("配置不是合法 JSON", "err");
              return;
            }
            try {
              await api("/api/tasks", {
                method: "POST",
                body: {
                  name: root.querySelector("#task-name").value,
                  kind: kind.value,
                  schedule: root.querySelector("#task-schedule").value,
                  config,
                  enabled: root.querySelector("#task-enabled").checked,
                },
              });
              closeModal();
              toast("任务已创建");
              await load(view, true);
            } catch (err) {
              toast(err.message, "err");
            }
          });
        },
      });
    }

    async function remove(view, id) {
      const task = tasks.find((item) => item.id === id);
      if (!task) return;
      const ok = await confirmDialog("删除任务", `确定删除「${task.name}」？运行历史会保留。`);
      if (!ok) return;
      try {
        await api(`/api/tasks/${encodeURIComponent(id)}`, { method: "DELETE" });
        toast("任务已删除");
        await load(view, true);
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function render(view) {
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left">
            <button class="btn sm primary" id="task-new">${icon("plus")}新建任务</button>
            <button class="btn sm ghost" id="task-refresh">${icon("refresh")}刷新</button>
          </div>
          <div class="right"><span class="side">30 秒 tick · 单任务不并发 · 失败退避 1/5/15 分钟</span></div>
        </div>
        <div id="task-list"><div class="skeleton" style="height:160px"></div></div>
        <div class="card" style="margin-top:18px">
          <div class="section-head" style="margin:0 0 10px"><h2>运行历史</h2><span class="side">最近 60 条</span></div>
          <div id="task-history"><div class="skeleton" style="height:80px"></div></div>
        </div>
        <p class="hint-text">B站/抖音主动刷任务必须显式设置 allow_write=true，插件自身的写开关和审批模式仍然生效；默认停用，启用前请确认。</p>`;
      view.querySelector("#task-new").addEventListener("click", () => createTask(view));
      view.querySelector("#task-refresh").addEventListener("click", () => load(view));
      load(view);
    }

    function leave() {}

    return { render, leave };
  }

  return { create, KIND_LABEL, fmtTime };
});
