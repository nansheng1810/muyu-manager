/* 牧鱼 · 配置快照与差异回滚 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerSnapshots = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog, state } = ctx;
    let instId = "";
    let snapshots = [];
    let fromId = "";
    let toId = "";

    function instances() {
      return (state && state.instances) || [];
    }

    function fmtTime(seconds) {
      const value = Number(seconds);
      if (!Number.isFinite(value) || value <= 0) return "—";
      const date = new Date(value * 1000);
      const pad = (n) => String(n).padStart(2, "0");
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    function size(bytes) {
      const value = Number(bytes || 0);
      if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
      if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
      return `${value} B`;
    }

    function listHtml() {
      if (!snapshots.length) {
        return `<div class="empty" style="padding:26px">${icon("memory")}<h4>还没有配置快照</h4>
          <p>先创建一个快照，再改插件或实例配置；出问题时可以对比并回滚。</p></div>`;
      }
      return `<div class="auto-list">${snapshots.map((item) => `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(item.label || "手动快照")}</strong>
            <span class="badge">${esc(String(item.file_count || 0))} 文件</span>
            <span class="badge">${esc(size(item.bytes))}</span></div>
          <div class="auto-meta"><span>${esc(fmtTime(item.created))}</span><span>ID <b>${esc(item.id)}</b></span></div>
        </div>
        <div class="auto-actions">
          <button class="btn sm ghost" data-snap-from="${esc(item.id)}">设为基准</button>
          <button class="btn sm ghost" data-snap-rollback="${esc(item.id)}">${icon("restart")}回滚</button>
          <button class="btn sm ghost" data-snap-del="${esc(item.id)}">${icon("trash")}</button>
        </div>
      </article>`).join("")}</div>`;
    }

    function compareToolbar() {
      const opts = (selected) => snapshots.map((item) => `<option value="${esc(item.id)}" ${item.id === selected ? "selected" : ""}>${esc(fmtTime(item.created))} · ${esc(item.label || "快照")}</option>`).join("");
      return `<div class="auto-toolbar" style="gap:8px;flex-wrap:wrap">
        <div class="left" style="display:flex;gap:8px;align-items:center">
          <span class="side">基准</span><select class="input" id="snap-from" style="min-width:180px"><option value="">选择快照</option>${opts(fromId)}</select>
          <span class="side">对比</span><select class="input" id="snap-to" style="min-width:180px"><option value="">选择快照</option>${opts(toId)}</select>
          <button class="btn sm primary" id="snap-diff-go">${icon("search")}对比</button>
        </div>
      </div>`;
    }

    function diffHtml(data) {
      const files = data.files || [];
      const added = data.added || [];
      const removed = data.removed || [];
      if (!files.length && !added.length && !removed.length) {
        return `<div class="empty" style="padding:22px">${icon("check")}<h4>两个快照完全一致</h4><p>没有配置差异。</p></div>`;
      }
      const fileBlocks = files.map((item) => `<div class="card" style="margin-top:10px;padding:12px">
        <div class="section-head" style="margin:0 0 8px"><h2 style="font-size:13px">${esc(item.file)}</h2>
          <span class="side">${esc(String((item.changes || []).length))} 处变化</span></div>
        <div class="auto-list">${(item.changes || []).map((change) => `<article class="auto-row" style="padding:8px 0">
          <div class="auto-main">
            <div class="auto-title"><span class="badge ${change.kind === "added" ? "ok" : change.kind === "removed" ? "bad" : "warn"}">${esc(change.kind === "added" ? "新增" : change.kind === "removed" ? "删除" : "修改")}</span>
              <strong>${esc(change.path)}</strong></div>
            <div class="auto-meta" style="align-items:flex-start;gap:10px">
              <span style="max-width:45%;word-break:break-all">旧：<b>${esc(change.before ?? "—")}</b></span>
              <span style="max-width:45%;word-break:break-all">新：<b>${esc(change.after ?? "—")}</b></span>
            </div>
          </div></article>`).join("")}</div></div>`).join("");
      return `<div class="auto-summary-grid" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-top:10px">
          <div class="auto-summary"><div class="k">修改文件</div><div class="v">${files.length}</div></div>
          <div class="auto-summary"><div class="k">新增文件</div><div class="v">${added.length}</div></div>
          <div class="auto-summary"><div class="k">删除文件</div><div class="v">${removed.length}</div></div>
        </div>
        ${added.length ? `<p class="hint-text">新增：${added.map(esc).join("、")}</p>` : ""}
        ${removed.length ? `<p class="hint-text">删除：${removed.map(esc).join("、")}</p>` : ""}
        ${fileBlocks}`;
    }

    async function load(view) {
      const focused = globalThis.ManagerFocus && globalThis.ManagerFocus.pick(instances());
      if (!instId && instances().length) instId = ((focused || instances()[0])).id;
      const box = view.querySelector("#snap-body");
      if (!box) return;
      box.innerHTML = `<div class="skeleton" style="height:240px"></div>`;
      try {
        const data = await api(`/api/instances/${encodeURIComponent(instId)}/snapshots`);
        if (!view.isConnected) return;
        snapshots = data.items || data || [];
        if (!fromId || !snapshots.some((item) => item.id === fromId)) fromId = snapshots[0] ? snapshots[0].id : "";
        if (!toId || !snapshots.some((item) => item.id === toId)) toId = snapshots[0] ? snapshots[0].id : "";
        box.innerHTML = `${compareToolbar()}<div id="snap-diff"></div><div class="section-head" style="margin:16px 0 8px"><h2>历史快照</h2>
          <span class="side">${snapshots.length} 个 · 自动保留最近 20 个</span></div>${listHtml()}`;
        bind(view);
      } catch (err) {
        if (!view.isConnected) return;
        box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取快照失败</h4><p>${esc(err.message)}</p></div>`;
      }
    }

    function bind(view) {
      view.querySelector("#snap-from")?.addEventListener("change", (event) => { fromId = event.target.value; });
      view.querySelector("#snap-to")?.addEventListener("change", (event) => { toId = event.target.value; });
      view.querySelector("#snap-diff-go")?.addEventListener("click", async () => {
        const diffBox = view.querySelector("#snap-diff");
        if (!fromId || !toId) return toast("先选择两个快照", "err");
        diffBox.innerHTML = `<div class="skeleton" style="height:120px;margin-top:10px"></div>`;
        try {
          const data = await api(`/api/instances/${encodeURIComponent(instId)}/snapshots/diff?from_id=${encodeURIComponent(fromId)}&to_id=${encodeURIComponent(toId)}`);
          if (!view.isConnected) return;
          diffBox.innerHTML = diffHtml(data);
        } catch (err) {
          diffBox.innerHTML = `<div class="empty" style="padding:20px">${icon("alert")}<h4>对比失败</h4><p>${esc(err.message)}</p></div>`;
        }
      });
      view.querySelectorAll("[data-snap-from]").forEach((node) => {
        node.addEventListener("click", () => {
          fromId = node.dataset.snapFrom;
          toId = toId || fromId;
          load(view);
          toast("已设为基准快照");
        });
      });
      view.querySelectorAll("[data-snap-del]").forEach((node) => {
        node.addEventListener("click", async () => {
          if (!await confirmDialog("删除快照", "确定删除这个配置快照？")) return;
          try {
            await api(`/api/instances/${encodeURIComponent(instId)}/snapshots/${encodeURIComponent(node.dataset.snapDel)}`, { method: "DELETE" });
            toast("快照已删除");
            load(view);
          } catch (err) { toast(err.message, "err"); }
        });
      });
      view.querySelectorAll("[data-snap-rollback]").forEach((node) => {
        node.addEventListener("click", async () => {
          const id = node.dataset.snapRollback;
          const item = snapshots.find((entry) => entry.id === id);
          if (!await confirmDialog("回滚配置", `将把「${item ? (item.label || "快照") : id}」里的配置写回实例，并先自动创建一个回滚前快照。机器人可能需要重启才能生效。`)) return;
          node.disabled = true;
          try {
            const data = await api(`/api/instances/${encodeURIComponent(instId)}/snapshots/restore`, {
              method: "POST",
              body: { snapshot_id: id, confirm: "RESTORE" },
            });
            toast(`已回滚 ${data.restored} 个文件，回滚前快照 ${data.rollback}`);
            await load(view);
          } catch (err) { toast(err.message, "err"); }
          finally { node.disabled = false; }
        });
      });
    }

    function render(view) {
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left" style="display:flex;gap:8px;align-items:center">
            <select class="input" id="snap-inst" style="min-width:180px">${instances().map((item) => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")}</select>
            <input class="input" id="snap-label" placeholder="快照备注，例如「改插件前」" style="width:220px">
            <button class="btn sm primary" id="snap-create">${icon("plus")}创建快照</button>
            <button class="btn sm ghost" id="snap-refresh">${icon("refresh")}刷新</button>
          </div>
          <div class="right"><span class="side">cmd_config、插件配置、plugins.json、skills.json</span></div>
        </div>
        <div id="snap-body"><div class="skeleton" style="height:240px"></div></div>
        <p class="hint-text">快照只保存在本机管理器数据目录；回滚会覆盖实例配置文件，建议先停机器人再回滚。</p>`;
      const select = view.querySelector("#snap-inst");
      const focused = (globalThis.ManagerFocus && globalThis.ManagerFocus.consume(instances()))
        || (globalThis.ManagerFocus && globalThis.ManagerFocus.pick(instances()));
      instId = (focused && focused.id) || select.value || (instances()[0] && instances()[0].id) || "";
      select.value = instId;
      select.addEventListener("change", () => {
        instId = select.value;
        snapshots = [];
        fromId = "";
        toId = "";
        load(view);
      });
      view.querySelector("#snap-refresh")?.addEventListener("click", () => load(view));
      view.querySelector("#snap-create")?.addEventListener("click", async () => {
        const label = String(view.querySelector("#snap-label").value || "").trim() || "手动快照";
        try {
          const data = await api(`/api/instances/${encodeURIComponent(instId)}/snapshots`, { method: "POST", body: { label } });
          toast(`快照已创建：${data.files} 个文件`);
          view.querySelector("#snap-label").value = "";
          fromId = data.id;
          toId = data.id;
          load(view);
        } catch (err) { toast(err.message, "err"); }
      });
      load(view);
    }

    function leave() {}

    return { render, leave };
  }

  return { create };
});
