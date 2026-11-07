/* 牧鱼 · 回复复盘（上下文解剖） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerReview = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const date = new Date(value * 1000);
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let instId = "";
    let viewEl = null;
    let traces = [];
    let selectedId = "";
    let keyword = "";
    let limit = 30;
    let listToken = 0;
    let detailToken = 0;

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];

    function emptyBox(title, text) {
      return `<div class="empty" style="padding:26px">${icon("alert")}<h4>${esc(title)}</h4><p>${esc(text)}</p></div>`;
    }

    function flagHtml(flags) {
      const items = [
        ["quote", "引用原文"],
        ["memory_recall", "召回记忆"],
        ["identity", "身份校准"],
        ["correction", "本轮纠错"],
      ];
      return items
        .map(([key, label]) =>
          `<span class="ins-flag ${flags && flags[key] ? "on" : ""}">${esc(label)}</span>`)
        .join("");
    }

    function rowHtml(item) {
      const owner = item.owner || {};
      const review = item.review || {};
      const active = item.id === selectedId;
      const sender = item.sender_name || item.sender_id || "未知";
      return `<button class="ins-row ${active ? "active" : ""}" data-trace="${esc(item.id)}">
        <div class="ins-row-top">
          <span class="ins-time">${esc(fmtTime(item.created))}</span>
          <span class="ins-sender">${esc(sender)}</span>
          ${owner.owner ? `<span class="badge accent">主人</span>` : ""}
          ${owner.impersonation ? `<span class="badge bad">冒充</span>` : ""}
          ${review.wrong ? `<span class="badge warn">说错</span>` : ""}
        </div>
        <div class="ins-row-text">${esc(item.user_text || "（空消息）")}</div>
        <div class="ins-row-sub">${esc(item.outgoing || "（未发送）")}</div>
        <div class="ins-row-meta">
          ${item.memory_count ? `<span>记忆 ${item.memory_count}</span>` : ""}
          ${item.model ? `<span>${esc(item.model)}</span>` : ""}
          <span>${item.llm_calls || 0} 次模型调用</span>
        </div>
      </button>`;
    }

    function memoryHtml(items) {
      const list = Array.isArray(items) ? items : [];
      if (!list.length) {
        return `<div class="ins-hint">本轮没有检索到记忆（livingmemory 未注入，或没有命中）。</div>`;
      }
      return `<div class="ins-mem-list">${list.map((item) => `
        <div class="ins-mem">
          <div class="ins-mem-head">${esc(item.head || "记忆条目")}</div>
          <div class="ins-mem-body">${esc(item.text || "")}</div>
        </div>`).join("")}</div>`;
    }

    function detailHtml(trace) {
      const owner = trace.owner_check || {};
      const review = trace.review || {};
      const flags = trace.flags || {};
      const personas = Array.isArray(trace.personas) ? trace.personas : [];
      const quote = trace.quote;
      const modeNames = {
        any: "仅账号识别",
        "": "仅账号识别",
        passphrase: "口令二次校验",
        manager: "管理器授权",
        passphrase_or_manager: "口令或管理器授权",
        either: "口令或管理器授权",
      };
      const badges = [
        ["is_admin", "AstrBot 管理员"],
        ["in_owner_ids", "主人名单"],
        ["verified", "二次校验通过"],
        ["grant", "管理器授权"],
        ["passphrase", "口令有效"],
        ["impersonation", "疑似冒充"],
      ]
        .filter(([key]) => owner[key])
        .map(([, label]) => `<span class="badge ${label === "疑似冒充" ? "bad" : "ok"}">${esc(label)}</span>`)
        .join("");
      return `
        <div class="ins-detail-head">
          <div>
            <h3>${esc(trace.sender_name || trace.sender_id || "未知发送者")}</h3>
            <p>${esc(fmtTime(trace.created))} · ${esc(trace.umo || "")}${trace.group_id ? " · 群 " + esc(trace.group_id) : ""}</p>
          </div>
          <div class="ins-badges">${badges || `<span class="badge">普通成员</span>`}</div>
        </div>
        <div class="ins-flags">${flagHtml(flags)}</div>

        <section class="ins-sec">
          <h4>人格匹配</h4>
          ${
            personas.length
              ? `<div class="ins-chipline">${personas
                  .map((item) => `<span class="badge accent">${esc(item.persona_id)} · ${item.chars} 字</span>`)
                  .join("")}</div>`
              : `<div class="ins-hint">没有匹配到现有人格。可能是人格已改名/删除，或本轮未注入人格。</div>`
          }
        </section>

        <section class="ins-sec">
          <h4>身份校准</h4>
          <div class="ins-kv">
            <div><span>判定</span><b>${owner.owner ? "主人" : "普通群友"}</b></div>
            <div><span>模式</span><b>${esc(modeNames[owner.mode] || owner.mode || "—")}</b></div>
            <div><span>sender_id</span><b class="mono">${esc(owner.sender_id || trace.sender_id || "—")}</b></div>
            <div><span>昵称</span><b>${esc(owner.sender_name || trace.sender_name || "—")}</b></div>
          </div>
          ${owner.impersonation ? `<div class="ins-alert">本轮检测到疑似冒充主人（昵称或消息含“我是主人/爸爸来了”等）。</div>` : ""}
          ${!owner.owner && owner.mode && !["any", "off", ""].includes(owner.mode) ? `<div class="ins-hint">该模式要求二次校验；本轮未通过时不会进入主人专属模式。</div>` : ""}
        </section>

        ${
          quote
            ? `<section class="ins-sec"><h4>引用原文</h4>
                <div class="ins-quote">${quote.nickname ? `<b>${esc(quote.nickname)}</b>` : ""}
                <div>${esc(quote.text || "")}</div></div></section>`
            : ""
        }

        <section class="ins-sec">
          <h4>本轮召回记忆 <span class="ins-count">${Array.isArray(trace.memory_items) ? trace.memory_items.length : 0} 条</span></h4>
          ${memoryHtml(trace.memory_items)}
        </section>

        <section class="ins-sec">
          <h4>用户消息</h4>
          <div class="ins-plain">${esc(trace.user_text || "（空）")}</div>
        </section>

        <section class="ins-sec">
          <h4>最终回复</h4>
          <div class="ins-plain">${esc(trace.outgoing || trace.response || "（模型没有产出文本）")}</div>
          ${trace.sent_ids && trace.sent_ids.length ? `<div class="ins-hint">已发送消息 ID：${trace.sent_ids.map((id) => esc(id)).join("、")}</div>` : ""}
        </section>

        <section class="ins-sec">
          <h4>说错话自检</h4>
          ${
            review && (review.wrong || review.reason || review.correction)
              ? `<div class="ins-review ${review.wrong ? "bad" : "ok"}">
                  <div><span>判定</span><b>${review.wrong ? "说错了" : "通过"}</b></div>
                  ${review.reason ? `<div><span>原因</span><b>${esc(review.reason)}</b></div>` : ""}
                  ${review.correction ? `<div><span>改写</span><b>${esc(review.correction)}</b></div>` : ""}
                  ${review.recalled_ids && review.recalled_ids.length ? `<div><span>已撤回</span><b>${review.recalled_ids.map((id) => esc(id)).join("、")}</b></div>` : ""}
                </div>`
              : `<div class="ins-hint">本轮没有自检记录（可能关闭了自检、回复太短或还在处理中）。</div>`
          }
        </section>

        <section class="ins-sec">
          <h4>最终 system prompt <span class="ins-count">${(trace.system_prompt || "").length} 字</span></h4>
          <details class="ins-details" ${trace.system_prompt ? "" : "open"}>
            <summary>展开查看完整注入内容</summary>
            <pre class="ins-pre">${esc(trace.system_prompt || "（空）")}</pre>
          </details>
        </section>

        <section class="ins-sec">
          <h4>上下文与附加内容</h4>
          <div class="ins-kv">
            <div><span>上下文条数</span><b>${trace.context_count ?? 0}</b></div>
            <div><span>模型调用次数</span><b>${trace.llm_calls ?? 0}</b></div>
            <div><span>模型</span><b class="mono">${esc(trace.model || "—")}</b></div>
          </div>
          ${
            Array.isArray(trace.extra_parts) && trace.extra_parts.length
              ? `<details class="ins-details" style="margin-top:10px"><summary>附加用户内容（${trace.extra_parts.length} 段）</summary>
                  ${trace.extra_parts.map((part, index) => `<pre class="ins-pre">【片段 ${index + 1}】\n${esc(part)}</pre>`).join("")}
                </details>`
              : ""
          }
          ${
            Array.isArray(trace.memory_blocks) && trace.memory_blocks.length
              ? `<details class="ins-details" style="margin-top:10px"><summary>原始记忆块（${trace.memory_blocks.length} 段）</summary>
                  ${trace.memory_blocks.map((block) => `<pre class="ins-pre">${esc(block)}</pre>`).join("")}
                </details>`
              : ""
          }
        </section>

        <div class="ins-foot">轨迹 ID：${esc(trace.id || "—")} · 更新于 ${esc(fmtTime(trace.updated || trace.created))}</div>`;
    }

    async function loadDetail(id) {
      const box = viewEl && viewEl.querySelector("#rv-detail");
      if (!box) return;
      if (!id) {
        box.innerHTML = `<div class="ins-placeholder">${icon("logs")}<p>从左侧选一条回复，查看它本轮注入了什么。</p></div>`;
        return;
      }
      const token = ++detailToken;
      box.innerHTML = `<div class="skeleton" style="height:240px"></div>`;
      try {
        const trace = await api(
          `/api/instances/${encodeURIComponent(instId)}/insight/traces/${encodeURIComponent(id)}`,
        );
        if (token !== detailToken || !viewEl || !viewEl.isConnected) return;
        box.innerHTML = detailHtml(trace);
      } catch (err) {
        if (token !== detailToken) return;
        box.innerHTML = emptyBox("读取轨迹失败", err.message);
      }
    }

    async function loadList(reselect = true) {
      const box = viewEl && viewEl.querySelector("#rv-list");
      if (!box) return;
      const token = ++listToken;
      box.innerHTML = `<div class="skeleton" style="height:180px"></div>`;
      try {
        const items = await api(
          `/api/instances/${encodeURIComponent(instId)}/insight/traces?limit=${limit}&keyword=${encodeURIComponent(keyword)}`,
        );
        if (token !== listToken || !viewEl || !viewEl.isConnected) return;
        traces = Array.isArray(items) ? items : [];
        const count = viewEl.querySelector("#rv-count");
        if (count) count.textContent = `${traces.length} 条`;
        if (!traces.length) {
          box.innerHTML = emptyBox(
            keyword ? "没有匹配的轨迹" : "还没有回复轨迹",
            keyword
              ? "换个关键词试试，或者清空搜索。"
              : "先在 QQ 里让机器人回复一句；插件会在每轮请求时记录人格、记忆、身份校准和最终 prompt。",
          );
          selectedId = "";
          loadDetail("");
          return;
        }
        if (!reselect || !traces.some((item) => item.id === selectedId)) {
          selectedId = traces[0].id;
        }
        box.innerHTML = traces.map(rowHtml).join("");
        box.querySelectorAll("[data-trace]").forEach((el) => {
          el.addEventListener("click", () => {
            selectedId = el.dataset.trace;
            box.querySelectorAll("[data-trace]").forEach((row) => {
              row.classList.toggle("active", row.dataset.trace === selectedId);
            });
            loadDetail(selectedId);
          });
        });
        loadDetail(selectedId);
      } catch (err) {
        if (token !== listToken) return;
        box.innerHTML = emptyBox("读取轨迹失败", err.message);
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
          ${list.map((item) => `<button class="chip ${item.id === instId ? "active" : ""}" data-rv-inst="${esc(item.id)}">${esc(item.name || item.id)}${item.status && item.status.running ? "" : "（未运行）"}</button>`).join("")}
        </div>
        <div class="ins-toolbar">
          <div class="field" style="margin:0;flex:1 1 240px">
            <label>搜索</label>
            <input type="search" id="rv-search" placeholder="搜发送者、用户消息、机器人回复" value="${esc(keyword)}">
          </div>
          <div class="field" style="margin:0;min-width:110px">
            <label>条数</label>
            <select id="rv-limit">
              ${[15, 30, 60, 100].map((n) => `<option value="${n}" ${n === limit ? "selected" : ""}>最近 ${n} 条</option>`).join("")}
            </select>
          </div>
          <button class="btn sm ghost" id="rv-refresh" style="align-self:flex-end">${icon("refresh")}刷新</button>
        </div>
        <div class="ins-layout">
          <section class="card ins-side">
            <div class="ins-side-head"><h3>回复轨迹</h3><span id="rv-count">—</span></div>
            <div id="rv-list" class="ins-list"><div class="skeleton" style="height:180px"></div></div>
          </section>
          <section class="card ins-detail" id="rv-detail">
            <div class="ins-placeholder">${icon("logs")}<p>从左侧选一条回复，查看它本轮注入了什么。</p></div>
          </section>
        </div>`;

      view.querySelectorAll("[data-rv-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.rvInst;
          selectedId = "";
          render(view);
        });
      });
      const search = view.querySelector("#rv-search");
      search.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          keyword = search.value.trim();
          loadList();
        }
      });
      view.querySelector("#rv-limit").addEventListener("change", (event) => {
        limit = Number(event.target.value) || 30;
        loadList();
      });
      view.querySelector("#rv-refresh").addEventListener("click", () => {
        keyword = search.value.trim();
        loadList();
      });
      loadList();
    }

    return { render };
  }

  return { create, fmtTime };
});
