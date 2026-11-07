/* 牧鱼 · 记忆纠错闭环 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerFix = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  const STATUS_TEXT = { pending: "待确认", resolved: "已处理", dismissed: "已忽略" };
  const ACTION_TEXT = { archive: "标记失效", downweight: "降权", rewrite: "改写" };

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let instId = "";
    let viewEl = null;
    let items = [];
    let filter = "pending";
    let selected = null;
    let searchResults = [];
    let selectedMemoryId = null;
    let listToken = 0;
    let searchToken = 0;

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];

    function emptyBox(title, text) {
      return `<div class="empty" style="padding:26px">${icon("alert")}<h4>${esc(title)}</h4><p>${esc(text)}</p></div>`;
    }

    function rowHtml(item) {
      const active = selected && selected.id === item.id;
      return `<button class="ins-row ${active ? "active" : ""}" data-fix="${esc(item.id)}">
        <div class="ins-row-top">
          <span class="ins-time">${esc(fmtTime(item.created))}</span>
          <span class="ins-sender">${esc(item.sender_name || item.sender_id || "未知")}</span>
          <span class="badge ${item.status === "pending" ? "warn" : item.status === "resolved" ? "ok" : ""}">${esc(STATUS_TEXT[item.status] || item.status)}</span>
        </div>
        <div class="ins-row-text">${esc(item.text || "（空）")}</div>
        <div class="ins-row-meta">
          ${item.hint ? `<span>线索：${esc(item.hint)}</span>` : ""}
          ${item.source === "manager" ? "<span>管理器补录</span>" : "<span>群聊触发</span>"}
        </div>
      </button>`;
    }

    function memoryHtml() {
      if (!searchResults.length) {
        return `<div class="ins-hint">没有搜到可能相关的记忆。可以换一个关键词，或直接在记忆页手动处理。</div>`;
      }
      return `<div class="ins-mem-list">${searchResults.map((item) => {
        const active = selectedMemoryId === item.id;
        return `<label class="ins-mem pick ${active ? "active" : ""}" data-mem="${esc(item.id)}">
          <div class="ins-mem-top">
            <span class="ins-mem-id">#${esc(item.id)}</span>
            <span class="badge ${item.status === "active" ? "ok" : "warn"}">${esc(item.status || "active")}</span>
            <span class="ins-count">重要度 ${esc(item.importance ?? "—")}</span>
          </div>
          <div class="ins-mem-body">${esc(item.content || item.summary || "")}</div>
        </label>`;
      }).join("")}</div>`;
    }

    function detailHtml() {
      if (!selected) {
        return `<div class="ins-placeholder">${icon("memory")}<p>从左侧选一条纠错，定位相关记忆后标记失效、降权或改写。</p></div>`;
      }
      const item = selected;
      const canEdit = item.status === "pending";
      return `
        <div class="ins-detail-head">
          <div>
            <h3>纠错 #${esc(item.id)}</h3>
            <p>${esc(fmtTime(item.created))} · ${esc(item.sender_name || item.sender_id || "未知")} · ${esc(item.umo || "")}</p>
          </div>
          <span class="badge ${item.status === "pending" ? "warn" : item.status === "resolved" ? "ok" : ""}">${esc(STATUS_TEXT[item.status] || item.status)}</span>
        </div>
        <section class="ins-sec">
          <h4>原话</h4>
          <div class="ins-plain">${esc(item.text || "（空）")}</div>
          ${item.hint ? `<div class="ins-hint">提取线索：${esc(item.hint)}</div>` : ""}
        </section>
        <section class="ins-sec">
          <h4>定位相关记忆</h4>
          <div class="ins-searchline">
            <input type="search" id="fx-search" placeholder="按关键词搜索记忆" value="${esc(item.hint || "")}">
            <button class="btn sm ghost" id="fx-search-btn">${icon("search")}搜索</button>
          </div>
          <div class="ins-hint">命中结果只会标记、降权或改写，不会直接删除；处理前请先选中一条。</div>
          <div id="fx-memories">${memoryHtml()}</div>
        </section>
        <section class="ins-sec">
          <h4>处理动作</h4>
          ${canEdit ? "" : `<div class="ins-hint">这条纠错已经处理过，只能查看结果。</div>`}
          <div class="ins-actions">
            <button class="btn sm" data-action="archive" ${canEdit ? "" : "disabled"}>标记失效</button>
            <button class="btn sm" data-action="downweight" ${canEdit ? "" : "disabled"}>降权</button>
            <button class="btn sm" data-action="rewrite" ${canEdit ? "" : "disabled"}>改写</button>
            <button class="btn sm ghost" data-action="dismiss" ${canEdit ? "" : "disabled"}>忽略这条纠错</button>
          </div>
          <div id="fx-rewrite" class="ins-rewrite" hidden>
            <textarea rows="4" id="fx-rewrite-text" placeholder="输入改写后的记忆内容，保存后会以新内容替换旧记忆。"></textarea>
            <button class="btn sm primary" id="fx-rewrite-save">保存改写</button>
          </div>
        </section>
        ${
          item.resolution
            ? `<section class="ins-sec"><h4>处理结果</h4>
                <div class="ins-kv">
                  <div><span>动作</span><b>${esc(ACTION_TEXT[item.resolution.action] || item.resolution.action || "—")}</b></div>
                  <div><span>记忆</span><b>#${esc(item.resolution.memory_id ?? "—")}</b></div>
                  ${item.resolution.rewrite ? `<div><span>改写</span><b>${esc(item.resolution.rewrite)}</b></div>` : ""}
                  ${item.resolution.note ? `<div><span>备注</span><b>${esc(item.resolution.note)}</b></div>` : ""}
                </div></section>`
            : ""
        }`;
    }

    function paintDetail() {
      const box = viewEl && viewEl.querySelector("#fx-detail");
      if (box) box.innerHTML = detailHtml();
      bindDetail();
    }

    function bindDetail() {
      const search = viewEl && viewEl.querySelector("#fx-search");
      if (search) {
        search.addEventListener("keydown", (event) => {
          if (event.key === "Enter") searchMemories();
        });
      }
      const searchBtn = viewEl && viewEl.querySelector("#fx-search-btn");
      if (searchBtn) searchBtn.addEventListener("click", searchMemories);
      viewEl.querySelectorAll("[data-mem]").forEach((el) => {
        el.addEventListener("click", () => {
          if (selected && selected.status !== "pending") return;
          selectedMemoryId = Number(el.dataset.mem) || el.dataset.mem;
          paintDetail();
        });
      });
      viewEl.querySelectorAll("[data-action]").forEach((el) => {
        el.addEventListener("click", () => handleAction(el.dataset.action));
      });
      const saveBtn = viewEl.querySelector("#fx-rewrite-save");
      if (saveBtn) {
        saveBtn.addEventListener("click", submitRewrite);
      }
    }

    async function searchMemories() {
      if (!selected) return;
      const input = viewEl && viewEl.querySelector("#fx-search");
      const keyword = input ? input.value.trim() : selected.hint || "";
      const box = viewEl && viewEl.querySelector("#fx-memories");
      if (box) box.innerHTML = `<div class="skeleton" style="height:90px"></div>`;
      const token = ++searchToken;
      try {
        const data = await api(
          `/api/instances/${encodeURIComponent(instId)}/memory/items?keyword=${encodeURIComponent(keyword)}&status=all&page=1&page_size=20`,
        );
        if (token !== searchToken) return;
        searchResults = Array.isArray(data) ? data : data && Array.isArray(data.items) ? data.items : [];
        if (selectedMemoryId == null && searchResults.length === 1) {
          selectedMemoryId = searchResults[0].id;
        }
        paintDetail();
      } catch (err) {
        if (token !== searchToken) return;
        if (box) box.innerHTML = emptyBox("搜索记忆失败", err.message);
      }
    }

    async function handleAction(action) {
      if (!selected) return;
      if (action === "dismiss") {
        if (!window.confirm("忽略后这条纠错会移出待确认队列，但不会改动任何记忆。继续？")) return;
        try {
          await api(
            `/api/instances/${encodeURIComponent(instId)}/insight/corrections/${encodeURIComponent(selected.id)}/dismiss`,
            { method: "POST", body: { note: "管理器手动忽略" } },
          );
          toast("已忽略这条纠错");
          selected = null;
          await loadList();
        } catch (err) {
          toast(err.message, "err");
        }
        return;
      }
      if (action === "rewrite") {
        const box = viewEl.querySelector("#fx-rewrite");
        const textarea = viewEl.querySelector("#fx-rewrite-text");
        if (!box || !textarea) return;
        box.hidden = false;
        if (!textarea.value) {
          const picked = searchResults.find((item) => item.id === selectedMemoryId);
          textarea.value = picked ? String(picked.content || "") : "";
        }
        textarea.focus();
        return;
      }
      await resolveAction(action, "");
    }

    async function submitRewrite() {
      const textarea = viewEl.querySelector("#fx-rewrite-text");
      const content = textarea ? textarea.value.trim() : "";
      if (!content) {
        toast("改写内容不能为空", "warn");
        return;
      }
      await resolveAction("rewrite", content);
    }

    async function resolveAction(action, rewrite) {
      if (!selectedMemoryId) {
        toast("请先在搜索结果里选中一条记忆", "warn");
        return;
      }
      const label = ACTION_TEXT[action] || action;
      const confirmText =
        action === "archive"
          ? `把记忆 #${selectedMemoryId} 标记为失效（归档），之后默认不再召回。继续？`
          : action === "downweight"
            ? `把记忆 #${selectedMemoryId} 的重要度降到最低，之后很少被召回。继续？`
            : `用新内容替换记忆 #${selectedMemoryId}（会创建一条新记忆并归档旧记忆）。继续？`;
      if (!window.confirm(confirmText)) return;
      try {
        await api(
          `/api/instances/${encodeURIComponent(instId)}/insight/corrections/${encodeURIComponent(selected.id)}/resolve`,
          {
            method: "POST",
            body: {
              action,
              memory_id: selectedMemoryId,
              rewrite,
              reason: `记忆纠错：${selected.text || selected.hint || ""}`.slice(0, 200),
            },
          },
        );
        toast(`已${label}，纠错项已归档`);
        selected = null;
        selectedMemoryId = null;
        searchResults = [];
        await loadList();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function paintList() {
      const box = viewEl && viewEl.querySelector("#fx-list");
      if (!box) return;
      if (!items.length) {
        box.innerHTML = emptyBox(
          filter === "pending" ? "待确认队列是空的" : "没有记录",
          filter === "pending"
            ? "群里主人说“记错了/别再提”，或在上面的输入框补录一条，就会出现在这里。"
            : "切换上方的状态筛选查看其它记录。",
        );
        return;
      }
      box.innerHTML = items.map(rowHtml).join("");
      box.querySelectorAll("[data-fix]").forEach((el) => {
        el.addEventListener("click", () => {
          selected = items.find((item) => item.id === el.dataset.fix) || null;
          selectedMemoryId = null;
          searchResults = [];
          paintList();
          paintDetail();
          if (selected) searchMemories();
        });
      });
    }

    async function loadList() {
      const box = viewEl && viewEl.querySelector("#fx-list");
      if (!box) return;
      const token = ++listToken;
      box.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
      try {
        const query = filter === "all" ? "" : `?status=${encodeURIComponent(filter)}`;
        const data = await api(
          `/api/instances/${encodeURIComponent(instId)}/insight/corrections${query}`,
        );
        if (token !== listToken || !viewEl || !viewEl.isConnected) return;
        items = Array.isArray(data) ? data : [];
        const count = viewEl.querySelector("#fx-count");
        if (count) count.textContent = `${items.length} 条`;
        paintList();
        paintDetail();
      } catch (err) {
        if (token !== listToken) return;
        box.innerHTML = emptyBox("读取纠错队列失败", err.message);
      }
    }

    async function addManual() {
      const input = viewEl && viewEl.querySelector("#fx-new-text");
      const text = input ? input.value.trim() : "";
      if (!text) {
        toast("先写一句要纠正的话", "warn");
        return;
      }
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/insight/corrections`, {
          method: "POST",
          body: { text, hint: text, sender_name: "管理器", source: "manager" },
        });
        if (input) input.value = "";
        toast("已加入待确认队列");
        filter = "pending";
        if (viewEl) {
          viewEl.querySelectorAll("[data-filter]").forEach((el) => {
            el.classList.toggle("active", el.dataset.filter === filter);
          });
        }
        await loadList();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function render(view) {
      viewEl = view;
      const list = instances();
      if (!list.length) {
        view.innerHTML = emptyBox("没有可用实例", "请先在「机器人」页新增或接入一个机器人。");
        return;
      }
      if (!instId || !list.some((item) => item.id === instId)) instId = list[0].id;
      view.innerHTML = `
        <div class="chips">
          ${list.map((item) => `<button class="chip ${item.id === instId ? "active" : ""}" data-fx-inst="${esc(item.id)}">${esc(item.name || item.id)}${item.status && item.status.running ? "" : "（未运行）"}</button>`).join("")}
        </div>
        <div class="ins-layout">
          <section class="card ins-side">
            <div class="ins-side-head"><h3>纠错队列</h3><span id="fx-count">—</span></div>
            <div class="ins-filters">
              ${[["pending", "待确认"], ["resolved", "已处理"], ["dismissed", "已忽略"], ["all", "全部"]]
                .map(([value, label]) => `<button class="chip ${value === filter ? "active" : ""}" data-filter="${value}">${label}</button>`)
                .join("")}
            </div>
            <div class="ins-addline">
              <input type="text" id="fx-new-text" placeholder="补录一条：例如“昨天说我爱吃辣是记错了”">
              <button class="btn sm ghost" id="fx-add">${icon("plus")}加入</button>
            </div>
            <div id="fx-list" class="ins-list"><div class="skeleton" style="height:160px"></div></div>
          </section>
          <section class="card ins-detail" id="fx-detail">
            <div class="ins-placeholder">${icon("memory")}<p>从左侧选一条纠错，定位相关记忆后标记失效、降权或改写。</p></div>
          </section>
        </div>`;

      view.querySelectorAll("[data-fx-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.fxInst;
          selected = null;
          searchResults = [];
          selectedMemoryId = null;
          render(view);
        });
      });
      view.querySelectorAll("[data-filter]").forEach((chip) => {
        chip.addEventListener("click", () => {
          filter = chip.dataset.filter;
          view.querySelectorAll("[data-filter]").forEach((el) => {
            el.classList.toggle("active", el.dataset.filter === filter);
          });
          selected = null;
          loadList();
        });
      });
      view.querySelector("#fx-add").addEventListener("click", addManual);
      loadList();
    }

    return { render };
  }

  return { create, fmtTime };
});
