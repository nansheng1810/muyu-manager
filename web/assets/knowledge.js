/* 牧鱼 · 知识库管理（代理 AstrBot RAG） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerKnowledge = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog, state } = ctx;
    let instId = "";
    let bases = [];
    let active = null;
    let providers = [];

    function instances() {
      return (state && state.instances) || [];
    }

    function instName(id) {
      const inst = instances().find((item) => item.id === id);
      return inst ? inst.name : id;
    }

    function baseId(item) {
      return String(item.kb_id || item.id || "");
    }

    function baseName(item) {
      return String(item.kb_name || item.name || "未命名知识库");
    }

    function baseOf(id) {
      return bases.find((item) => baseId(item) === String(id)) || null;
    }

    function fmtTime(value) {
      if (!value) return "—";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
      const pad = (n) => String(n).padStart(2, "0");
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    function listHtml() {
      if (!instances().length) {
        return `<div class="empty">${icon("bots")}<h4>还没有机器人实例</h4><p>先添加实例后再管理知识库。</p></div>`;
      }
      if (!bases.length) {
        return `<div class="empty">${icon("memory")}<h4>这个实例还没有知识库</h4><p>点右上角「新建知识库」，选一个向量模型即可开始。</p></div>`;
      }
      return `<div class="auto-list">${bases.map((item) => {
        const id = baseId(item);
        const isActive = active && baseId(active) === id;
        return `<article class="auto-row">
          <div class="auto-main">
            <div class="auto-title">
              <strong>${esc(baseName(item))}</strong>
              <span class="badge">${esc(String(item.doc_count || 0))} 文档</span>
              <span class="badge">${esc(String(item.chunk_count || 0))} 片段</span>
              ${item.embedding_provider_id ? `<span class="badge">${esc(String(item.embedding_provider_id))}</span>` : ""}
              ${isActive ? `<span class="badge ok">当前</span>` : ""}
            </div>
            ${item.description ? `<p class="approval-reason">${esc(item.description)}</p>` : ""}
            <div class="auto-meta"><span>更新 <b>${esc(fmtTime(item.updated_at))}</b></span>
              <span>ID <b>${esc(id)}</b></span></div>
          </div>
          <div class="auto-actions">
            <button class="btn sm ghost" data-kb-open="${esc(id)}">文档与检索</button>
            <button class="btn sm ghost" data-kb-del="${esc(id)}">${icon("trash")}</button>
          </div>
        </article>`;
      }).join("")}</div>`;
    }

    function docsHtml() {
      if (!active) return "";
      const docs = active._docs || [];
      const id = baseId(active);
      const rows = docs.length
        ? docs.map((doc) => `<article class="auto-row">
            <div class="auto-main">
              <div class="auto-title"><strong>${esc(doc.name)}</strong>
                <span class="badge">${esc(String(doc.chunks || 0))} 片段</span>
                ${doc.status ? `<span class="badge">${esc(doc.status)}</span>` : ""}</div>
              </div>
            <div class="auto-actions"><button class="btn sm ghost" data-doc-del="${esc(doc.id)}">${icon("trash")}</button></div>
          </article>`).join("")
        : `<div class="empty" style="padding:20px">${icon("folder")}<h4>还没有文档</h4><p>上传文件或导入网页，解析完成后会出现在这里。</p></div>`;
      return `<div class="card" style="margin-top:12px">
        <div class="section-head" style="margin:0 0 10px"><h2>${esc(baseName(active))}</h2>
          <span class="side">${esc(String(active.doc_count || 0))} 文档 · ${esc(String(active.chunk_count || 0))} 片段</span></div>
        <div class="auto-toolbar" style="flex-wrap:wrap;gap:8px">
          <div class="left" style="display:flex;gap:8px;flex-wrap:wrap">
            <input type="file" id="kb-file" multiple accept=".txt,.md,.pdf,.docx,.html,.csv,.json" style="display:none">
            <button class="btn sm primary" id="kb-pick">${icon("plus")}上传文档</button>
            <input class="input" id="kb-url" placeholder="https://example.com/page" style="min-width:240px">
            <button class="btn sm ghost" id="kb-url-go">导入网页</button>
          </div>
        </div>
        <div class="auto-list" style="margin-top:10px">${rows}</div>
        <div class="section-head" style="margin:16px 0 8px"><h2>检索测试</h2><span class="side">只读预览，不写入对话</span></div>
        <div class="auto-toolbar" style="gap:8px">
          <div class="left" style="display:flex;gap:8px;flex:1">
            <input class="input" id="kb-query" placeholder="输入一个群里常问的问题" style="flex:1">
            <button class="btn sm primary" id="kb-search">${icon("search")}检索</button>
          </div>
        </div>
        <div id="kb-results"></div>
        <p class="hint-text">上传解析在 AstrBot 后台进行；解析较慢时可稍后刷新文档列表。知识库只影响绑定了它的会话。</p>
      </div>`;
    }

    function resultsHtml(data) {
      const results = (data && data.results) || [];
      if (!results.length) {
        return `<div class="empty" style="padding:20px">${icon("search")}<h4>没有召回结果</h4><p>换个问法，或先确认文档已完成解析。</p></div>`;
      }
      return `<div class="auto-list" style="margin-top:10px">${results.map((item) => `<article class="auto-row">
        <div class="auto-main">
          <div class="auto-title"><strong>${esc(item.doc_name || item.kb_name || "片段")}</strong>
            ${item.score != null ? `<span class="badge">${esc(Number(item.score).toFixed(3))}</span>` : ""}</div>
          <p class="approval-reason" style="white-space:pre-wrap">${esc(String(item.content || item.text || "").slice(0, 400))}</p>
        </div>
      </article>`).join("")}</div>`;
    }

    async function load(view, keep = false) {
      const focused = globalThis.ManagerFocus && globalThis.ManagerFocus.pick(instances());
      if (!instId && instances().length) instId = ((focused || instances()[0])).id;
      const box = view.querySelector("#kb-body");
      if (!box) return;
      box.innerHTML = `<div class="skeleton" style="height:220px"></div>`;
      try {
        const data = await api(`/api/instances/${encodeURIComponent(instId)}/knowledge/bases?page_size=100`);
        if (!view.isConnected) return;
        bases = (data.items || data.knowledge_bases || data || []).slice();
        if (keep && active) {
          active = baseOf(baseId(active)) || null;
        }
        if (!active && bases.length) active = bases[0];
        box.innerHTML = listHtml() + docsHtml();
        bindBody(view);
        if (active) loadDocs(view);
      } catch (err) {
        if (!view.isConnected) return;
        box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>读取知识库失败</h4><p>${esc(err.message)}</p></div>`;
      }
    }

    async function loadDocs(view) {
      if (!active) return;
      const id = baseId(active);
      try {
        const data = await api(`/api/instances/${encodeURIComponent(instId)}/knowledge/bases/${encodeURIComponent(id)}/documents?search=`);
        if (!view.isConnected) return;
        active._docs = (data.items || data.documents || data || []).map((doc) => ({
          id: String(doc.doc_id || doc.id || doc.file_id || ""),
          name: String(doc.doc_name || doc.file_name || doc.name || "未命名文档"),
          chunks: doc.chunk_count || doc.chunks || 0,
          status: String(doc.status || ""),
        }));
        const detail = view.querySelector("#kb-body");
        if (detail) detail.innerHTML = listHtml() + docsHtml();
        bindBody(view);
        loadProviders(view);
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function loadProviders(view) {
      if (providers.length) return;
      try {
        const data = await api(`/api/instances/${encodeURIComponent(instId)}/knowledge/providers`);
        providers = (data.items || data || []).slice();
        const select = view.querySelector("#kb-embedding");
        if (select) {
          select.innerHTML = providers.length
            ? providers.map((item) => `<option value="${esc(item.id)}">${esc(item.model || item.id)}</option>`).join("")
            : `<option value="">没有可用的向量模型</option>`;
        }
      } catch (_) { /* 忽略：新建时再提示 */ }
    }

    function bindBody(view) {
      view.querySelectorAll("[data-kb-open]").forEach((node) => {
        node.addEventListener("click", (event) => {
          event.stopPropagation();
          active = baseOf(node.dataset.kbOpen);
          view.querySelector("#kb-body").innerHTML = listHtml() + docsHtml();
          bindBody(view);
          loadDocs(view);
        });
      });
      view.querySelectorAll("[data-kb-del]").forEach((node) => {
        node.addEventListener("click", async (event) => {
          event.stopPropagation();
          const id = node.dataset.kbDel;
          const item = baseOf(id);
          if (!await confirmDialog("删除知识库", `确定删除「${baseName(item || {})}」？文档与向量会一起删除，无法恢复。`)) return;
          try {
            await api(`/api/instances/${encodeURIComponent(instId)}/knowledge/bases/${encodeURIComponent(id)}`, { method: "DELETE" });
            toast("知识库已删除");
            active = null;
            load(view);
          } catch (err) { toast(err.message, "err"); }
        });
      });
      view.querySelectorAll("[data-doc-del]").forEach((node) => {
        node.addEventListener("click", async () => {
          if (!active) return;
          const id = node.dataset.docDel;
          if (!await confirmDialog("删除文档", "确定删除这份文档？对应向量片段会一起删除。")) return;
          try {
            await api(`/api/instances/${encodeURIComponent(instId)}/knowledge/bases/${encodeURIComponent(baseId(active))}/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
            toast("文档已删除");
            load(view, true);
          } catch (err) { toast(err.message, "err"); }
        });
      });
      const pick = view.querySelector("#kb-pick");
      const file = view.querySelector("#kb-file");
      if (pick && file) {
        pick.addEventListener("click", () => file.click());
        file.addEventListener("change", async () => {
          if (!active || !file.files.length) return;
          const form = new FormData();
          form.append("kb_id", baseId(active));
          Array.from(file.files).forEach((item) => form.append("file", item, item.name));
          pick.disabled = true;
          pick.textContent = "上传中…";
          try {
            const res = await fetch(`/api/instances/${encodeURIComponent(instId)}/knowledge/bases/${encodeURIComponent(baseId(active))}/documents`, { method: "POST", body: form });
            const json = await res.json().catch(() => null);
            if (!res.ok || (json && json.status === "error")) throw new Error((json && json.message) || `上传失败（HTTP ${res.status}）`);
            toast("已提交解析，稍后刷新查看");
            setTimeout(() => load(view, true), 2000);
          } catch (err) { toast(err.message, "err"); }
          finally { pick.disabled = false; pick.innerHTML = `${icon("plus")}上传文档`; file.value = ""; }
        });
      }
      const urlGo = view.querySelector("#kb-url-go");
      if (urlGo) {
        urlGo.addEventListener("click", async () => {
          const input = view.querySelector("#kb-url");
          const url = String(input && input.value || "").trim();
          if (!active || !url) return toast("请填写网页链接", "err");
          urlGo.disabled = true;
          try {
            await api(`/api/instances/${encodeURIComponent(instId)}/knowledge/bases/${encodeURIComponent(baseId(active))}/import-url`, { method: "POST", body: { urls: [url] } });
            toast("网页已提交解析");
            input.value = "";
            setTimeout(() => load(view, true), 2000);
          } catch (err) { toast(err.message, "err"); }
          finally { urlGo.disabled = false; }
        });
      }
      const search = view.querySelector("#kb-search");
      if (search) {
        search.addEventListener("click", async () => {
          const input = view.querySelector("#kb-query");
          const box = view.querySelector("#kb-results");
          const query = String(input && input.value || "").trim();
          if (!active || !query) return toast("请输入检索问题", "err");
          box.innerHTML = `<div class="skeleton" style="height:100px;margin-top:10px"></div>`;
          search.disabled = true;
          try {
            const data = await api(`/api/instances/${encodeURIComponent(instId)}/knowledge/bases/${encodeURIComponent(baseId(active))}/retrieve`, { method: "POST", body: { query, top_k: 5 } });
            if (!view.isConnected) return;
            box.innerHTML = resultsHtml(data);
          } catch (err) {
            box.innerHTML = `<div class="empty" style="padding:20px">${icon("alert")}<h4>检索失败</h4><p>${esc(err.message)}</p></div>`;
          } finally { search.disabled = false; }
        });
      }
    }

    function formHtml() {
      return `<div class="card" id="kb-create-card" style="margin-bottom:12px">
        <div class="section-head" style="margin:0 0 10px"><h2>新建知识库</h2><span class="side">选择向量模型后不可随意更换</span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <input class="input" id="kb-name" placeholder="知识库名称，例如：群规与常见问题">
          <input class="input" id="kb-desc" placeholder="一句话描述（可选）">
          <select class="input" id="kb-embedding"><option value="">加载向量模型中…</option></select>
          <input class="input" id="kb-chunk" type="number" min="100" max="2000" placeholder="分块大小，默认 512">
        </div>
        <div class="auto-toolbar" style="margin-top:10px">
          <div class="left"><button class="btn sm primary" id="kb-create">${icon("check")}创建</button>
            <button class="btn sm ghost" id="kb-cancel">取消</button></div>
        </div>
      </div>`;
    }

    function render(view) {
      leave();
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left" style="display:flex;gap:8px;align-items:center">
            <select class="input" id="kb-inst" style="min-width:180px">${instances().map((item) => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")}</select>
            <button class="btn sm ghost" id="kb-refresh">${icon("refresh")}刷新</button>
          </div>
          <div class="right"><button class="btn sm primary" id="kb-new">${icon("plus")}新建知识库</button></div>
        </div>
        <div id="kb-create-slot"></div>
        <div id="kb-body"><div class="skeleton" style="height:220px"></div></div>
        <p class="hint-text">知识库走 AstrBot 自带的 RAG：上传文档或网页后自动分块向量化；这里只做管理，不改变对话内容。</p>`;
      const select = view.querySelector("#kb-inst");
      if (select) {
        const focused = (globalThis.ManagerFocus && globalThis.ManagerFocus.consume(instances()))
          || (globalThis.ManagerFocus && globalThis.ManagerFocus.pick(instances()));
        instId = (focused && focused.id) || select.value || (instances()[0] && instances()[0].id) || "";
        select.value = instId;
        select.addEventListener("change", () => {
          instId = select.value;
          bases = [];
          active = null;
          providers = [];
          load(view);
        });
      }
      view.querySelector("#kb-refresh")?.addEventListener("click", () => load(view, true));
      view.querySelector("#kb-new")?.addEventListener("click", () => {
        if (!instId) return toast("先选择实例", "err");
        const slot = view.querySelector("#kb-create-slot");
        if (!slot.querySelector("#kb-create-card")) {
          slot.innerHTML = formHtml();
          providers = [];
          loadProviders(view);
          view.querySelector("#kb-cancel").addEventListener("click", () => { slot.innerHTML = ""; });
          view.querySelector("#kb-create").addEventListener("click", async () => {
            const name = String(view.querySelector("#kb-name").value || "").trim();
            const embedding = String(view.querySelector("#kb-embedding").value || "").trim();
            if (!name) return toast("请填写知识库名称", "err");
            if (!embedding) return toast("请选择向量模型", "err");
            const chunk = view.querySelector("#kb-chunk").value;
            try {
              await api(`/api/instances/${encodeURIComponent(instId)}/knowledge/bases`, {
                method: "POST",
                body: { name, description: view.querySelector("#kb-desc").value || "", embedding_provider_id: embedding, chunk_size: chunk || undefined },
              });
              toast("知识库已创建");
              slot.innerHTML = "";
              load(view);
            } catch (err) { toast(err.message, "err"); }
          });
        } else {
          slot.innerHTML = "";
        }
      });
      load(view);
    }

    function leave() {
      /* 无轮询，无需清理 */
    }

    return { render, leave };
  }

  return { create };
});
