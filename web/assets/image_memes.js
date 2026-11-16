/* 牧鱼 · 图片表情包 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerImageMemes = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast, state, confirmDialog } = ctx;
    const confirm = typeof confirmDialog === "function"
      ? confirmDialog
      : async () => true;
    let instId = "";
    let viewEl = null;
    let data = null;
    let packId = "";
    let category = "";
    let images = [];
    let loading = false;
    let busy = false;

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];

    const findPack = (id) =>
      ((data && data.packs) || []).find((pack) => String(pack.id) === String(id)) || null;

    const imageUrl = (item) =>
      `/api/instances/${encodeURIComponent(instId)}/image-memes/file` +
      `?pack_id=${encodeURIComponent(packId)}` +
      `&category=${encodeURIComponent(item.category)}` +
      `&name=${encodeURIComponent(item.name)}`;

    function statusBadge() {
      if (!data) return `<span class="badge">读取中</span>`;
      if (!data.plugin_ready) {
        return `<span class="badge warn" title="${esc(data.plugin_error || "")}">插件未就绪</span>`;
      }
      return `<span class="badge ok">meme_manager 已连接</span>`;
    }

    function statsHtml() {
      const pack = findPack(packId);
      const packs = (data && data.packs) || [];
      const total = packs.reduce((sum, item) => sum + Number(item.image_count || 0), 0);
      return `
        <div class="imemes-stats">
          <div class="imemes-stat"><b>${packs.length}</b><span>已安装表情包</span></div>
          <div class="imemes-stat"><b>${total}</b><span>全部图片</span></div>
          <div class="imemes-stat"><b>${pack ? pack.image_count : 0}</b><span>当前包图片</span></div>
          <div class="imemes-stat accent"><b>${data ? data.settings.probability : 0}%</b><span>回复配图概率</span></div>
        </div>`;
    }

    function packOptions() {
      const packs = (data && data.packs) || [];
      if (!packs.length) return `<option value="">没有表情包</option>`;
      return packs.map((pack) => `
        <option value="${esc(pack.id)}" ${String(pack.id) === String(packId) ? "selected" : ""}>
          ${esc(pack.name)} · ${pack.image_count} 张${pack.active ? " · 当前" : ""}
        </option>`).join("");
    }

    function categoryOptions() {
      const pack = findPack(packId);
      const categories = (pack && pack.categories) || {};
      const options = [`<option value="">全部分类</option>`];
      Object.keys(categories).sort().forEach((name) => {
        options.push(
          `<option value="${esc(name)}" ${name === category ? "selected" : ""}>` +
          `${esc(name)} · ${categories[name]}</option>`
        );
      });
      return options.join("");
    }

    function groupOptions() {
      const groups = (data && data.groups) || [];
      if (!groups.length) {
        return `<input type="text" id="imemes-group-input" inputmode="numeric" placeholder="群号，例如 884218771">`;
      }
      return `<select id="imemes-group">${groups.map((group) => `
        <option value="${esc(group.group_id)}">群 ${esc(group.group_id)} · ${group.count} 条记录</option>
      `).join("")}</select>`;
    }

    function imageCard(item) {
      return `
        <figure class="imemes-card">
          <div class="imemes-thumb">
            <img src="${esc(imageUrl(item))}" alt="${esc(item.name)}" loading="lazy">
          </div>
          <figcaption>
            <div class="imemes-name" title="${esc(item.name)}">${esc(item.name)}</div>
            <div class="imemes-meta"><span>${esc(item.category)}</span><span>${Math.max(1, Math.round(item.size / 1024))} KB</span></div>
          </figcaption>
          <button class="imemes-del" data-del="${esc(item.category)}::${esc(item.name)}" title="删除">${icon("trash")}</button>
        </figure>`;
    }

    function gridHtml() {
      if (loading) return `<div class="skeleton" style="height:260px"></div>`;
      const pack = findPack(packId);
      if (!pack) {
        return `<div class="imemes-empty">${icon("model")}<h4>还没有表情包</h4><p>先导入本地表情包，或从 AstrBot 插件页安装一个。</p></div>`;
      }
      if (!images.length) {
        return `<div class="imemes-empty">${icon("model")}<h4>这个分类还没有图片</h4><p>可以切换分类，或导入 50 张本地表情包。</p></div>`;
      }
      return `<div class="imemes-grid">${images.map(imageCard).join("")}</div>`;
    }

    function render() {
      if (!viewEl) return;
      if (!instances().length) {
        viewEl.innerHTML = `<div class="empty" style="padding:40px">${icon("bots")}<h4>没有实例</h4><p>先在「机器人」里添加一个实例。</p></div>`;
        return;
      }
      const current = instances().find((item) => String(item.id) === String(instId));
      const pack = findPack(packId);
      viewEl.innerHTML = `
        <div class="imemes-instances">
          ${instances().map((item) => `
            <button class="chip ${String(item.id) === String(instId) ? "on" : ""}" data-imemes-inst="${esc(item.id)}">
              ${esc(item.name || item.id)}
            </button>`).join("")}
          <span class="imemes-badge">${statusBadge()}</span>
          <button class="btn sm ghost" id="imemes-refresh" style="margin-left:auto">${icon("refresh")}刷新</button>
        </div>
        ${statsHtml()}
        <div class="imemes-toolbar">
          <div class="field imemes-select"><label>表情包</label><select id="imemes-pack">${packOptions()}</select></div>
          <div class="field imemes-select"><label>分类</label><select id="imemes-category">${categoryOptions()}</select></div>
          ${pack && !pack.active ? `<button class="btn sm" id="imemes-activate">${icon("check")}设为当前包</button>` : ""}
          <button class="btn sm" id="imemes-import-toggle">${icon("plus")}导入本地 50 张</button>
        </div>
        <div class="imemes-layout">
          <section class="card imemes-library">
            <div class="imemes-lib-head">
              <div><h3>${esc(pack ? pack.name : "表情包")}</h3><p>${esc(pack ? pack.description : "")}</p></div>
              <span class="badge">${images.length} 张</span>
            </div>
            ${gridHtml()}
          </section>
          <aside class="imemes-side">
            <section class="card imemes-panel">
              <div class="imemes-panel-head"><h3>回复随机配图</h3><span class="badge ok">${data ? data.settings.probability : 0}%</span></div>
              <p class="imemes-note">每次回复前按概率决定是否附带一张表情；0 表示不自动发。</p>
              <div class="imemes-range-row">
                <input type="range" id="imemes-prob" min="0" max="100" step="1" value="${data ? data.settings.probability : 30}">
                <output id="imemes-prob-out">${data ? data.settings.probability : 30}%</output>
              </div>
              <button class="btn sm" id="imemes-save-prob">${icon("check")}保存概率</button>
            </section>
            <section class="card imemes-panel">
              <div class="imemes-panel-head"><h3>随机发一张</h3><span class="badge">手动测试</span></div>
              <div class="field"><label>目标群</label>${groupOptions()}</div>
              <div class="imemes-send-row">
                <button class="btn sm ghost" id="imemes-dry">${icon("search")}试选一张</button>
                <button class="btn sm" id="imemes-send">${icon("play")}发送到群</button>
              </div>
              <p class="imemes-result" id="imemes-result">只在点击时发送，不会自动往群里刷图。</p>
            </section>
            <section class="card imemes-panel">
              <div class="imemes-panel-head"><h3>导入本地表情包</h3><span class="badge">${data && data.source_exists ? `${data.source_images} 张` : "目录缺失"}</span></div>
              <div class="field"><label>来源目录</label><input type="text" id="imemes-source" value="${esc(data ? data.source_dir : "")}"></div>
              <div class="field"><label>新包名称</label><input type="text" id="imemes-pack-name" value="牧鱼自选表情包"></div>
              <button class="btn sm" id="imemes-import">${icon("download")}导入到新包</button>
              <p class="imemes-note">导入后会把新包设为当前包，并重载 meme_manager。${current ? esc(current.name || "") : ""}</p>
            </section>
          </aside>
        </div>`;
      bind();
    }

    function bind() {
      viewEl.querySelectorAll("[data-imemes-inst]").forEach((button) => {
        button.addEventListener("click", () => {
          instId = button.dataset.imemesInst;
          data = null;
          packId = "";
          category = "";
          images = [];
          load();
        });
      });
      const refresh = viewEl.querySelector("#imemes-refresh");
      if (refresh) refresh.addEventListener("click", () => load(true));
      const packSelect = viewEl.querySelector("#imemes-pack");
      if (packSelect) packSelect.addEventListener("change", async () => {
        packId = packSelect.value;
        category = "";
        await loadImages();
        render();
      });
      const categorySelect = viewEl.querySelector("#imemes-category");
      if (categorySelect) categorySelect.addEventListener("change", async () => {
        category = categorySelect.value;
        await loadImages();
        render();
      });
      const activate = viewEl.querySelector("#imemes-activate");
      if (activate) activate.addEventListener("click", activatePack);
      const importToggle = viewEl.querySelector("#imemes-import-toggle");
      if (importToggle) importToggle.addEventListener("click", () => {
        const panel = viewEl.querySelector("#imemes-source");
        if (panel) {
          panel.scrollIntoView({ behavior: "smooth", block: "center" });
          panel.focus();
        }
      });
      viewEl.querySelectorAll("[data-del]").forEach((button) => {
        button.addEventListener("click", () => removeImage(button.dataset.del));
      });
      const prob = viewEl.querySelector("#imemes-prob");
      const probOut = viewEl.querySelector("#imemes-prob-out");
      if (prob && probOut) {
        prob.addEventListener("input", () => { probOut.textContent = `${prob.value}%`; });
      }
      const saveProb = viewEl.querySelector("#imemes-save-prob");
      if (saveProb) saveProb.addEventListener("click", saveProbability);
      const dry = viewEl.querySelector("#imemes-dry");
      if (dry) dry.addEventListener("click", () => sendRandom(true));
      const send = viewEl.querySelector("#imemes-send");
      if (send) send.addEventListener("click", () => sendRandom(false));
      const importButton = viewEl.querySelector("#imemes-import");
      if (importButton) importButton.addEventListener("click", importPack);
    }

    async function load(force) {
      if (!instId || loading) return;
      loading = true;
      if (!data || force) render();
      try {
        data = await api(`/api/instances/${encodeURIComponent(instId)}/image-memes`);
        if (!data.packs.some((pack) => String(pack.id) === String(packId))) {
          packId = data.active_pack_id || (data.packs[0] && data.packs[0].id) || "";
        }
        await loadImages();
      } catch (err) {
        toast(`读取表情包失败：${err.message || err}`, "err");
        data = data || { packs: [], settings: {}, plugin_ready: false, groups: [], source_dir: "", source_exists: false, source_images: 0 };
      } finally {
        loading = false;
        render();
      }
    }

    async function loadImages() {
      images = [];
      if (!packId) return;
      try {
        const result = await api(
          `/api/instances/${encodeURIComponent(instId)}/image-memes/images` +
          `?pack_id=${encodeURIComponent(packId)}&category=${encodeURIComponent(category)}`
        );
        images = result.items || [];
      } catch (err) {
        toast(`读取图片失败：${err.message || err}`, "err");
      }
    }

    async function activatePack() {
      if (!packId || busy) return;
      busy = true;
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/image-memes/activate`, {
          method: "POST", body: { pack_id: packId },
        });
        toast("已设为当前表情包");
        data = null;
        await load(true);
      } catch (err) {
        toast(err.message || "切换失败", "err");
      } finally { busy = false; }
    }

    async function removeImage(key) {
      const [cat, name] = String(key).split("::");
      if (!(await confirm("删除表情", `确定删除 ${name}？`))) return;
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/image-memes/images/delete`, {
          method: "POST", body: { pack_id: packId, category: cat, name },
        });
        toast("已删除");
        await loadImages();
        data = null;
        await load(true);
      } catch (err) { toast(err.message || "删除失败", "err"); }
    }

    async function saveProbability() {
      const input = viewEl && viewEl.querySelector("#imemes-prob");
      if (!input || busy) return;
      busy = true;
      try {
        const result = await api(
          `/api/instances/${encodeURIComponent(instId)}/image-memes/settings`,
          { method: "PATCH", body: { probability: Number(input.value) } }
        );
        data.settings = result.settings || data.settings;
        const reload = result.reload || {};
        toast(reload.ok === false ? `已保存，但插件重载失败：${reload.message}` : "概率已保存", reload.ok === false ? "warn" : "ok");
        render();
      } catch (err) { toast(err.message || "保存失败", "err"); }
      finally { busy = false; }
    }

    function groupValue() {
      const select = viewEl && viewEl.querySelector("#imemes-group");
      if (select) return select.value;
      const input = viewEl && viewEl.querySelector("#imemes-group-input");
      return input ? input.value.trim() : "";
    }

    async function sendRandom(dryRun) {
      const group = groupValue();
      if (!group) { toast("先填写群号", "warn"); return; }
      if (!dryRun && !(await confirm("随机发一张", `确认把一张随机表情发送到群 ${group}？`))) return;
      try {
        const result = await api(
          `/api/instances/${encodeURIComponent(instId)}/image-memes/random-send`,
          { method: "POST", body: { group_id: group, pack_id: packId, category, dry_run: dryRun } }
        );
        const line = `${dryRun ? "试选" : "已发送"}：${result.filename || "—"}（${result.category || "—"}）`;
        if (viewEl) {
          const box = viewEl.querySelector("#imemes-result");
          if (box) box.textContent = line;
        }
        toast(line, "ok");
      } catch (err) { toast(err.message || "发送失败", "err"); }
    }

    async function importPack() {
      const source = viewEl && viewEl.querySelector("#imemes-source");
      const name = viewEl && viewEl.querySelector("#imemes-pack-name");
      if (!source || busy) return;
      if (!(await confirm("导入表情包", "会把来源目录里的图片导入新包，并把新包设为当前包。继续？"))) return;
      busy = true;
      try {
        const result = await api(
          `/api/instances/${encodeURIComponent(instId)}/image-memes/import`,
          { method: "POST", body: { source_dir: source.value.trim(), name: name ? name.value.trim() : "" } }
        );
        toast(result.imported ? `已导入 ${result.image_count} 张` : "表情包已存在", "ok");
        data = null;
        packId = result.id || "";
        category = "";
        await load(true);
      } catch (err) { toast(err.message || "导入失败", "err"); }
      finally { busy = false; }
    }

    function renderView(view) {
      viewEl = view;
      const list = instances();
      const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(list);
      if (focusHit) {
        instId = String(focusHit.id);
      } else if (!list.some((item) => String(item.id) === String(instId))) {
        const focused = globalThis.ManagerFocus && globalThis.ManagerFocus.pick(list);
        instId = list.length ? String((focused || list[0]).id) : "";
      }
      if (!instId) {
        view.innerHTML = `<div class="empty" style="padding:40px">${icon("bots")}<h4>没有实例</h4><p>先在「机器人」里添加一个实例。</p></div>`;
        return;
      }
      render();
      load();
    }

    return { render: renderView };
  }

  return { create };
});
