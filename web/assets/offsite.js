/* 牧鱼 · 异地备份（WebDAV） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerOffsite = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog } = ctx;

    function fmtTime(seconds) {
      const value = Number(seconds);
      if (!Number.isFinite(value) || value <= 0) return "—";
      const date = new Date(value * 1000);
      const pad = (n) => String(n).padStart(2, "0");
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    function size(bytes) {
      const value = Number(bytes || 0);
      if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
      if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
      if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
      return `${value} B`;
    }

    function configCard(data) {
      const enabled = data.enabled ? "checked" : "";
      return `<div class="card">
        <div class="section-head" style="margin:0 0 10px"><h2>WebDAV 连接</h2>
          <span class="side">${data.tick_seconds ? `每 ${Math.round(data.tick_seconds / 60)} 分钟自动检查新备份` : ""}</span></div>
        <label class="hint-text" style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
          <input type="checkbox" id="of-enabled" ${enabled}> 启用自动上传（产生新备份后自动传到 WebDAV）
        </label>
        <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px">
          <label class="hint-text">WebDAV 地址<input class="input" id="of-url" placeholder="https://dav.example.com/remote.php/dav/files/me" value="${esc(data.url || "")}"></label>
          <label class="hint-text">远程目录<input class="input" id="of-dir" placeholder="muyu-backups" value="${esc(data.dir || "")}"></label>
          <label class="hint-text">用户名<input class="input" id="of-user" value="${esc(data.user || "")}"></label>
          <label class="hint-text">密码<input class="input" id="of-pass" type="password" placeholder="${data.has_password ? "已保存，留空不修改" : "密码"}"></label>
          <label class="hint-text">保留远程份数（0 不清理）<input class="input" id="of-keep" type="number" min="0" value="${esc(data.keep ?? 0)}"></label>
        </div>
        <div class="auto-toolbar" style="margin-top:10px">
          <div class="left"><button class="btn sm primary" id="of-save">${icon("check")}保存</button>
            <button class="btn sm ghost" id="of-test">${icon("pulse")}测试连接</button></div>
          <div class="right"><span class="side">仅支持 Basic Auth + HTTP/HTTPS</span></div>
        </div>
      </div>`;
    }

    function localCard(data) {
      const uploads = data.uploads || [];
      const names = new Set(uploads.filter((item) => item.status === "ok").map((item) => item.backup_name));
      const rows = (data.local || []).map((item) => `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(item.name)}</strong>
            <span class="badge">${esc(size(item.bytes))}</span>
            ${names.has(item.name) ? `<span class="badge ok">已上传</span>` : `<span class="badge warn">未上传</span>`}</div>
          <div class="auto-meta"><span>${esc(fmtTime(item.created))}</span>
            <span>SHA <b>${esc(String(item.sha256 || "").slice(0, 12) || "—")}</b></span></div>
        </div>
        <div class="auto-actions"><button class="btn sm ghost" data-of-upload="${esc(item.path)}">${icon("download")}上传</button></div>
      </article>`).join("");
      return `<div class="card" style="margin-top:14px">
        <div class="section-head" style="margin:0 0 10px"><h2>本地备份</h2><span class="side">${(data.local || []).length} 个</span></div>
        ${rows || `<div class="empty" style="padding:22px">${icon("folder")}<h4>还没有本地备份</h4><p>先到设置里创建一次备份。</p></div>`}
      </div>`;
    }

    function remoteHtml(items) {
      if (!items || !items.length) {
        return `<div class="empty" style="padding:22px">${icon("download")}<h4>远程目录为空</h4><p>上传一个备份后会出现在这里。</p></div>`;
      }
      return `<div class="auto-list">${items.map((item) => `<article class="auto-row">
        <div class="auto-main"><div class="auto-title"><strong>${esc(item.name)}</strong>
          <span class="badge">${esc(size(item.bytes))}</span></div>
          <div class="auto-meta"><span>${esc(item.modified || "—")}</span></div></div>
        <div class="auto-actions"><button class="btn sm ghost" data-of-remote-del="${esc(item.name)}">${icon("trash")}</button></div>
      </article>`).join("")}</div>`;
    }

    async function load(view, remote = false) {
      const box = view.querySelector("#of-body");
      if (!box) return;
      box.innerHTML = `<div class="skeleton" style="height:260px"></div>`;
      try {
        const data = await api("/api/offsite");
        if (!view.isConnected) return;
        box.innerHTML = `${configCard(data)}${localCard(data)}
          <div class="card" style="margin-top:14px">
            <div class="section-head" style="margin:0 0 10px"><h2>远程备份</h2>
              <div style="display:flex;gap:8px"><button class="btn sm ghost" id="of-remote">${icon("refresh")}读取远端</button></div></div>
            <div id="of-remote-body"><p class="hint-text">浏览器不会直接访问 WebDAV；点「读取远端」由管理器拉取目录。</p></div>
          </div>`;
        bind(view, data);
        if (remote) await loadRemote(view);
      } catch (err) {
        if (!view.isConnected) return;
        box.innerHTML = `<div class="empty" style="padding:26px">${icon("alert")}<h4>读取异地备份状态失败</h4><p>${esc(err.message)}</p></div>`;
      }
    }

    async function loadRemote(view) {
      const box = view.querySelector("#of-remote-body");
      if (!box) return;
      box.innerHTML = `<div class="skeleton" style="height:100px"></div>`;
      try {
        const data = await api("/api/offsite/remote");
        if (!view.isConnected) return;
        box.innerHTML = remoteHtml(data.items || []);
        box.querySelectorAll("[data-of-remote-del]").forEach((node) => {
          node.addEventListener("click", async () => {
            if (!await confirmDialog("删除远程备份", `确定删除 ${node.dataset.ofRemoteDel}？`)) return;
            try {
              await api(`/api/offsite/remote?name=${encodeURIComponent(node.dataset.ofRemoteDel)}`, { method: "DELETE" });
              toast("远程备份已删除");
              loadRemote(view);
            } catch (err) { toast(err.message, "err"); }
          });
        });
      } catch (err) {
        box.innerHTML = `<div class="empty" style="padding:20px">${icon("alert")}<h4>读取远程目录失败</h4><p>${esc(err.message)}</p></div>`;
      }
    }

    function bind(view, data) {
      view.querySelector("#of-remote")?.addEventListener("click", () => loadRemote(view));
      view.querySelector("#of-save")?.addEventListener("click", async () => {
        const payload = {
          offsite_enabled: Boolean(view.querySelector("#of-enabled").checked),
          offsite_url: String(view.querySelector("#of-url").value || "").trim(),
          offsite_user: String(view.querySelector("#of-user").value || "").trim(),
          offsite_dir: String(view.querySelector("#of-dir").value || "").trim(),
          offsite_keep: Number(view.querySelector("#of-keep").value || 0),
        };
        const password = String(view.querySelector("#of-pass").value || "");
        if (password) payload.offsite_password = password;
        try {
          await api("/api/offsite", { method: "PUT", body: payload });
          toast("异地备份设置已保存");
          load(view, false);
        } catch (err) { toast(err.message, "err"); }
      });
      view.querySelector("#of-test")?.addEventListener("click", async () => {
        const button = view.querySelector("#of-test");
        button.disabled = true;
        try {
          const result = await api("/api/offsite/test", { method: "POST", body: {} });
          toast(`连接正常：${result.url}`);
        } catch (err) { toast(err.message, "err"); }
        finally { button.disabled = false; }
      });
      view.querySelectorAll("[data-of-upload]").forEach((node) => {
        node.addEventListener("click", async () => {
          node.disabled = true;
          node.textContent = "上传中…";
          try {
            const result = await api("/api/offsite/upload", { method: "POST", body: { path: node.dataset.ofUpload } });
            toast(`已上传 ${result.name}${result.pruned ? `，清理 ${result.pruned} 份旧备份` : ""}`);
            load(view, true);
          } catch (err) {
            toast(err.message, "err");
            node.disabled = false;
            node.innerHTML = `${icon("download")}上传`;
          }
        });
      });
    }

    function render(view) {
      view.innerHTML = `<div id="of-body"><div class="skeleton" style="height:260px"></div></div>
        <p class="hint-text">异地备份只上传管理器生成的 zip；密码保存在本机 settings.json，不会出现在日志里。</p>`;
      load(view);
    }

    function leave() {}

    return { render, leave };
  }

  return { create };
});
