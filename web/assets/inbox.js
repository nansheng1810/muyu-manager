/* 牧鱼 · 收件箱（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerInbox = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const PLATFORM = { qq: "QQ", bilibili: "B站", douyin: "抖音" };
  const KIND = { private: "私信", group: "QQ群" };

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "";
    return new Date(value * 1000).toLocaleString();
  }

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog } = ctx;
    let threads = [];
    let current = null;
    let messages = [];
    let timer = null;
    let loadSeq = 0;
    let selectSeq = 0;
    const filter = { platform: "", kind: "private", q: "", unread: false };

    function threadRow(item) {
      // 账号名区分同平台的不同实例；后端缺 account_name 时退回平台名
      const meta = [PLATFORM[item.platform] || item.platform, item.account_name]
        .filter(Boolean).join(" · ");
      return `<button type="button" class="inbox-thread ${item.id === current?.id ? "active" : ""}" data-thread="${esc(item.id)}">
        <div class="inbox-thread-top"><strong>${esc(item.display_name || item.thread_key)}</strong>
          ${item.unread ? `<span class="badge accent">${esc(item.unread)}</span>` : ""}</div>
        <div class="inbox-thread-meta">${esc(meta)} · ${esc(item.last_text || "")}</div>
        <div class="inbox-thread-foot"><span>${item.takeover ? "人工接管" : ""}</span><span>${esc(fmtTime(item.last_message_at))}</span></div>
      </button>`;
    }

    function messageRow(item) {
      return `<div class="inbox-message ${item.direction === "out" ? "out" : "in"}">
        <div class="inbox-message-head"><strong>${esc(item.sender_name || "—")}</strong>
          <span>${esc(fmtTime(item.ts))}</span></div>
        <p>${esc(item.text)}</p></div>`;
    }

    function renderThreads(view) {
      const box = view.querySelector("#inbox-threads");
      if (!box) return;
      box.innerHTML = threads.length
        ? threads.map((item) => threadRow(item)).join("")
        : `<div class="empty-inline">没有会话</div>`;
    }

    function updateChrome(view) {
      const sendBtn = view.querySelector("#inbox-send");
      if (sendBtn) sendBtn.disabled = !current?.takeover;
      const takeoverBtn = view.querySelector("#inbox-takeover");
      if (takeoverBtn) {
        takeoverBtn.textContent = current?.takeover ? "取消接管" : "接管";
        takeoverBtn.disabled = !current;
      }
      const title = view.querySelector("#inbox-title");
      if (title) {
        title.textContent = current
          ? [current.display_name || current.thread_key,
            PLATFORM[current.platform] || current.platform, current.account_name]
            .filter(Boolean).join(" · ")
          : "选择会话";
      }
      const hint = view.querySelector("#inbox-send-hint");
      if (hint) hint.textContent = current?.takeover ? "已接管，可人工发送" : "先开启人工接管才能发送";
    }

    function newestTs() {
      return messages.reduce((max, item) => Math.max(max, Number(item?.ts) || 0), 0);
    }

    function renderMessages(view, keepScroll = false) {
      const box = view.querySelector("#inbox-messages");
      if (!box) return;
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
      const prevTop = box.scrollTop;
      box.innerHTML = messages.length
        ? messages.map((item) => messageRow(item)).join("")
        : `<div class="empty-inline">暂无消息</div>`;
      box.scrollTop = !keepScroll || atBottom ? box.scrollHeight : prevTop;
      updateChrome(view);
    }

    async function loadThreads(view, silent = false) {
      if (!view.isConnected) return;
      const token = ++loadSeq;
      const params = new URLSearchParams({ limit: "200" });
      if (filter.platform) params.set("platform", filter.platform);
      if (filter.kind) params.set("kind", filter.kind);
      if (filter.q) params.set("q", filter.q);
      if (filter.unread) params.set("unread", "true");
      try {
        const data = await api(`/api/inbox/threads?${params}`);
        if (token !== loadSeq || !view.isConnected) return;
        threads = Array.isArray(data) ? data : [];
        // 轮询回包后重绑当前会话，避免接管状态停留在旧对象上；被过滤掉的会话继续显示。
        if (current) {
          const fresh = threads.find((item) => item.id === current.id);
          if (fresh) current = fresh;
        }
        renderThreads(view);
        updateChrome(view);
        if (!current && threads[0] && !filter.unread) {
          await selectThread(view, threads[0].id);
          return;
        }
        if (current && Number(current.last_message_at || 0) > newestTs()) await refreshCurrent(view);
      } catch (err) {
        if (token !== loadSeq || !view.isConnected) return;
        threads = [];
        const box = view.querySelector("#inbox-threads");
        if (box) box.innerHTML = `<div class="empty-inline">读取失败：${esc(err.message)}</div>`;
        updateChrome(view);
        if (!silent) toast(err.message, "err");
      }
    }

    async function refreshCurrent(view) {
      const id = current?.id;
      if (!id) return;
      const token = selectSeq;
      try {
        const data = await api(`/api/inbox/threads/${encodeURIComponent(id)}/messages?limit=100`);
        if (token !== selectSeq || !view.isConnected || current?.id !== id) return;
        messages = Array.isArray(data) ? data : [];
        renderMessages(view, true);
      } catch (_) { /* 轮询刷新失败时保留旧消息 */ }
    }

    async function selectThread(view, id, { markRead = false } = {}) {
      const item = threads.find((x) => x.id === id);
      if (!item) return;
      const token = ++selectSeq;
      current = item;
      renderThreads(view);
      updateChrome(view);
      try {
        const data = await api(`/api/inbox/threads/${encodeURIComponent(id)}/messages?limit=100`);
        if (token !== selectSeq || !view.isConnected) return;
        messages = Array.isArray(data) ? data : [];
      } catch (err) {
        if (token !== selectSeq || !view.isConnected) return;
        messages = [];
        toast(err.message, "err");
      }
      renderMessages(view);
      if (!markRead) return;
      try {
        await api(`/api/inbox/threads/${encodeURIComponent(id)}/read`, { method: "POST" });
        item.unread = 0;
      } catch (_) { /* 已读回执失败不影响浏览 */ }
      if (token !== selectSeq || !view.isConnected) return;
      renderThreads(view);
      updateChrome(view);
    }

    async function toggleTakeover(view) {
      if (!current) return;
      const button = view.querySelector("#inbox-takeover");
      if (button) button.disabled = true;
      try {
        const result = await api(`/api/inbox/threads/${encodeURIComponent(current.id)}/takeover`, {
          method: "POST", body: { enabled: !current.takeover },
        });
        if (result && result.thread) current = result.thread;
        updateChrome(view);
        toast(current.takeover ? "已接管，AI 自动回复暂停" : "已取消接管");
        if ((result?.sync || []).some((x) => !x.ok)) toast("接管已保存，但插件同步失败", "err");
        await loadThreads(view);
      } catch (err) {
        toast(err.message, "err");
      } finally {
        if (button) button.disabled = !current;
      }
    }

    async function send(view) {
      if (!current) return;
      if (!current.takeover) return toast("先开启人工接管才能发送", "err");
      const box = view.querySelector("#inbox-text");
      const text = box.value.trim();
      if (!text) return toast("请输入内容", "err");
      if (text.length > 500) return toast("最多发送 500 字", "err");
      const ok = await confirmDialog("人工发送", `确认发送到「${current.display_name || current.thread_key}」？`);
      if (!ok) return;
      const button = view.querySelector("#inbox-send");
      if (button) button.disabled = true;
      try {
        await api(`/api/inbox/threads/${encodeURIComponent(current.id)}/send`, {
          method: "POST", body: { text, confirm: "SEND" },
        });
        box.value = "";
        toast("已发送");
        const data = await api(`/api/inbox/threads/${encodeURIComponent(current.id)}/messages?limit=100`);
        messages = Array.isArray(data) ? data : [];
        renderMessages(view);
        loadThreads(view, true);
      } catch (err) {
        toast(err.message, "err");
      } finally {
        if (button) button.disabled = !current?.takeover;
      }
    }

    async function syncNow(view, manual = false) {
      try {
        const result = await api("/api/inbox/sync", { method: "POST" });
        if (!view.isConnected) return;
        if (result && !Array.isArray(result) && result.skipped) {
          if (manual) toast("同步正在进行", "warn");
        } else if (Array.isArray(result) && result.some((x) => (x?.sources || []).some((src) => src && src.error))) {
          toast("同步完成，部分源失败", "warn");
        } else {
          toast("已同步");
        }
      } catch (err) {
        toast(err.message, "err");
      }
      await loadThreads(view);
    }

    function render(view) {
      leave();
      view.innerHTML = `
        <div class="inbox-filters">
          <select id="inbox-platform"><option value="">全部平台</option><option value="qq">QQ</option><option value="bilibili">B站</option><option value="douyin">抖音</option></select>
          <select id="inbox-kind"><option value="private">私信</option><option value="group">QQ群</option></select>
          <input type="text" id="inbox-search" placeholder="搜索会话或最后一句">
          <label class="checkline"><input id="inbox-unread" type="checkbox">只看未读</label>
          <button type="button" class="btn sm ghost" id="inbox-refresh">${icon("refresh")}刷新</button>
        </div>
        <div class="inbox-layout">
          <div class="inbox-threads" id="inbox-threads"><div class="skeleton" style="height:120px"></div></div>
          <div class="inbox-main">
            <div class="inbox-head"><strong id="inbox-title">选择会话</strong><button type="button" class="btn sm ghost" id="inbox-takeover" disabled>接管</button></div>
            <div class="inbox-messages" id="inbox-messages"><div class="empty-inline">暂无消息</div></div>
            <div class="inbox-send"><div class="side" id="inbox-send-hint">先开启人工接管才能发送</div>
              <textarea id="inbox-text" rows="2" maxlength="500" placeholder="人工回复，最多 500 字"></textarea>
              <button type="button" class="btn primary" id="inbox-send" disabled>发送</button></div>
          </div>
        </div>`;
      const platform = view.querySelector("#inbox-platform");
      platform.value = filter.platform;
      platform.addEventListener("change", (e) => { filter.platform = e.target.value; loadThreads(view); });
      const kind = view.querySelector("#inbox-kind");
      kind.value = filter.kind;
      kind.addEventListener("change", (e) => { filter.kind = e.target.value; loadThreads(view); });
      const search = view.querySelector("#inbox-search");
      search.value = filter.q;
      search.addEventListener("input", (e) => { filter.q = e.target.value.trim(); loadThreads(view); });
      const unread = view.querySelector("#inbox-unread");
      unread.checked = filter.unread;
      unread.addEventListener("change", (e) => { filter.unread = e.target.checked; loadThreads(view); });
      view.querySelector("#inbox-refresh").addEventListener("click", () => { syncNow(view, true); });
      view.querySelector("#inbox-threads").addEventListener("click", (e) => {
        const el = e.target.closest("[data-thread]");
        if (el) selectThread(view, el.dataset.thread, { markRead: true });
      });
      view.querySelector("#inbox-takeover").addEventListener("click", () => toggleTakeover(view));
      view.querySelector("#inbox-send").addEventListener("click", () => send(view));
      loadThreads(view);
      syncNow(view);
      timer = setInterval(() => {
        if (view.isConnected) loadThreads(view, true);
      }, 10000);
    }

    function leave() {
      if (timer) clearInterval(timer);
      timer = null;
      loadSeq += 1;
      selectSeq += 1;
      threads = [];
      current = null;
      messages = [];
    }

    return { render, leave, threadRow, messageRow };
  }

  return { create, PLATFORM, KIND, fmtTime };
});
