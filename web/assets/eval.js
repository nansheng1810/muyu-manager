/* 牧鱼 · 人格质量回归（原生模块） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerEval = api;
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

  function normalizeList(payload, key) {
    if (Array.isArray(payload)) return payload;
    if (!payload || typeof payload !== "object") return [];
    if (Array.isArray(payload[key])) return payload[key];
    const data = payload.data;
    if (Array.isArray(data)) return data;
    if (data && Array.isArray(data[key])) return data[key];
    return [];
  }

  function scoreClass(score) {
    return score >= 70 ? "ok" : score >= 40 ? "warn" : "bad";
  }

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let fixtures = [];
    let history = [];
    let instanceId = "";
    let providerId = "";
    let personaId = "";
    let providers = [];
    let personas = [];
    let optionsToken = 0;
    let running = false;

    function fixtureHtml() {
      if (!fixtures.length) return `<div class="empty" style="padding:18px"><p>没有可用用例</p></div>`;
      return `<div class="eval-fixtures">${fixtures.map((item, index) => `
        <label class="eval-fixture">
          <input type="checkbox" data-fixture="${esc(item.id)}" checked>
          <div><b>${esc(item.title)}</b>
            <div><span>${esc(item.prompt)}</span></div>
          </div>
        </label>`).join("")}</div>`;
    }

    function resultsHtml(batch) {
      if (!batch) {
        return `<div class="empty" style="padding:26px">${icon("model")}<h4>还没有本次结果</h4>
          <p>选择模型和人格后点击「开始回归」，每个用例会真实调用一次模型。</p></div>`;
      }
      const results = batch.results || [];
      return `
        <div class="auto-summary-grid" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:14px">
          <div class="auto-summary"><div class="k">平均分</div><div class="v">${batch.average || 0}<small>分</small></div></div>
          <div class="auto-summary"><div class="k">通过</div><div class="v">${batch.passed || 0}<small>/ ${batch.total || results.length}</small></div></div>
          <div class="auto-summary"><div class="k">模型</div><div class="v" style="font-size:14px;line-height:1.4">${esc(batch.model || "—")}</div></div>
        </div>
        ${results.map((item) => {
          const score = Number(item.score?.score || 0);
          return `<div class="eval-result">
            <div class="eval-result-head">
              <div><b>${esc(item.title || item.fixture)}</b>
                <span class="badge ${item.status === "ok" ? "ok" : "bad"}">${esc(item.status)}</span></div>
              <div class="eval-score ${scoreClass(score)}">${score}</div>
            </div>
            ${item.reply ? `<p class="eval-reply">${esc(item.reply)}</p>` : ""}
            ${item.error ? `<p class="eval-reply" style="color:var(--bad-text)">${esc(item.error)}</p>` : ""}
            <div class="eval-checks">
              ${(item.score?.checks || []).map((check) =>
                `<div class="eval-check"><b>${check.ok ? "通过" : "未过"}</b><span>${esc(check.name)}：${esc(check.detail)}</span></div>`).join("")}
            </div>
          </div>`;
        }).join("")}`;
    }

    function historyHtml() {
      if (!history.length) return `<div class="empty" style="padding:18px"><p>还没有历史记录</p></div>`;
      return `<div class="digest-list">${history.map((item) => {
        const score = Number(item.score?.score || 0);
        return `<div class="digest-item">
          <div class="time">${esc(fmtTime(item.created))}</div>
          <div class="body"><b>${esc(item.fixture)}</b>
            <div class="sub">${esc(item.model)}${item.persona ? " · " + esc(item.persona) : ""}</div></div>
          <span class="eval-score ${scoreClass(score)}" style="font-size:14px">${score}</span>
        </div>`;
      }).join("")}</div>`;
    }

    function fillSelects(view) {
      const instSelect = view.querySelector("#eval-instance");
      const providerSelect = view.querySelector("#eval-provider");
      const personaSelect = view.querySelector("#eval-persona");
      if (instSelect) {
        instSelect.innerHTML = (state.instances || []).map((item) =>
          `<option value="${esc(item.id)}" ${item.id === instanceId ? "selected" : ""}>${esc(item.name || item.id)}</option>`).join("");
      }
      if (providerSelect) {
        providerSelect.innerHTML = providers.length
          ? providers.map((item) =>
            `<option value="${esc(item.id)}" ${item.id === providerId ? "selected" : ""}>${esc(item.model || item.id)}${item.enable === false ? "（停用）" : ""}</option>`).join("")
          : `<option value="">没有对话模型</option>`;
      }
      if (personaSelect) {
        personaSelect.innerHTML = `<option value="">不加载人格</option>` + personas.map((item) =>
          `<option value="${esc(item.persona_id)}" ${item.persona_id === personaId ? "selected" : ""}>${esc(item.persona_id)}</option>`).join("");
      }
    }

    async function refreshOptions(view, reset = false) {
      const token = ++optionsToken;
      if (!state.instances?.length) {
        fillSelects(view);
        return;
      }
      if (!instanceId || !state.instances.some((item) => item.id === instanceId)) {
        instanceId = state.instances[0].id;
        reset = true;
      }
      if (reset) {
        providerId = "";
        personaId = "";
      }
      fillSelects(view);
      const providerSelect = view.querySelector("#eval-provider");
      const personaSelect = view.querySelector("#eval-persona");
      if (providerSelect) providerSelect.innerHTML = `<option value="">读取模型中…</option>`;
      if (personaSelect) personaSelect.innerHTML = `<option value="">读取人格中…</option>`;
      try {
        const summary = await api(`/api/instances/${encodeURIComponent(instanceId)}/summary`).catch(() => null);
        if (token !== optionsToken || !view.isConnected) return;
        providers = Array.isArray(summary?.providers)
          ? summary.providers.filter((item) => item && item.id && (!item.type || String(item.type).includes("chat")))
          : [];
        // 实例未运行时 Dashboard 必然不可达，不再多打一次 personas 请求。
        const personaData = providers.length
          ? await api(`/api/instances/${encodeURIComponent(instanceId)}/proxy/personas`).catch(() => null)
          : null;
        if (token !== optionsToken || !view.isConnected) return;
        personas = normalizeList(personaData, "personas").filter((item) => item && item.persona_id);
        if (!providers.some((item) => item.id === providerId)) {
          providerId = providers.find((item) => item.enable !== false)?.id || providers[0]?.id || "";
        }
        if (!personas.some((item) => item.persona_id === personaId)) personaId = "";
        fillSelects(view);
      } catch (err) {
        if (token !== optionsToken) return;
        if (providerSelect) providerSelect.innerHTML = `<option value="">读取失败</option>`;
        if (personaSelect) personaSelect.innerHTML = `<option value="">读取失败</option>`;
      }
    }

    async function loadFixtures(view) {
      try {
        const data = await api("/api/evals/fixtures");
        if (!view.isConnected) return;
        fixtures = Array.isArray(data) ? data : [];
        const box = view.querySelector("#eval-fixtures");
        if (box) box.innerHTML = fixtureHtml();
        const count = view.querySelector("#eval-fixture-count");
        if (count) count.textContent = `${fixtures.length} 个`;
      } catch (err) {
        const box = view.querySelector("#eval-fixtures");
        if (box) box.innerHTML = `<div class="empty" style="padding:18px"><p>${esc(err.message)}</p></div>`;
      }
    }

    async function loadHistory(view) {
      try {
        const data = await api("/api/evals/runs?limit=30");
        if (!view.isConnected) return;
        history = Array.isArray(data) ? data : [];
        const box = view.querySelector("#eval-history");
        if (box) box.innerHTML = historyHtml();
      } catch (_) {
        const box = view.querySelector("#eval-history");
        if (box) box.innerHTML = `<div class="empty" style="padding:18px"><p>历史读取失败</p></div>`;
      }
    }

    async function run(view, btn) {
      if (running) return;
      if (!instanceId) {
        toast("没有可用机器人实例", "warn");
        return;
      }
      if (!providerId) {
        toast("请选择对话模型", "warn");
        return;
      }
      const selected = Array.from(view.querySelectorAll("[data-fixture]:checked"))
        .map((node) => node.dataset.fixture);
      if (!selected.length) {
        toast("请至少选择一个用例", "warn");
        return;
      }
      running = true;
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = "回归中…每个用例调用一次模型";
      const box = view.querySelector("#eval-result");
      if (box) box.innerHTML = `<div class="skeleton" style="height:220px"></div>`;
      try {
        const batch = await api("/api/evals/run", {
          method: "POST",
          body: {
            inst_id: instanceId,
            provider_id: providerId,
            persona_id: personaId,
            fixture_ids: selected,
          },
        });
        if (box) box.innerHTML = resultsHtml(batch);
        toast(`回归完成：平均 ${batch.average} 分，通过 ${batch.passed}/${batch.total}`);
        loadHistory(view);
        loadTrend(view);
      } catch (err) {
        if (box) box.innerHTML = `<div class="empty" style="padding:24px">${icon("alert")}<h4>回归失败</h4><p>${esc(err.message)}</p></div>`;
        toast(err.message, "err");
      } finally {
        running = false;
        btn.disabled = false;
        btn.innerHTML = original;
      }
    }

    function trendHtml(data) {
      if (!data || !data.runs) {
        return `<div class="empty" style="padding:18px"><p>还没有可汇总的回归记录</p></div>`;
      }
      const daily = data.daily || [];
      const fixtures = data.fixtures || [];
      const regressions = data.regressions || [];
      return `
        <div class="auto-summary-grid" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:12px">
          <div class="auto-summary"><div class="k">历史平均</div><div class="v">${data.average || 0}<small>分</small></div></div>
          <div class="auto-summary"><div class="k">运行</div><div class="v">${data.runs || 0}<small>次</small></div></div>
          <div class="auto-summary"><div class="k">回归告警</div><div class="v">${regressions.length}<small>项</small></div></div>
        </div>
        ${daily.length ? `<div class="digest-list" style="margin-bottom:10px">${daily.slice(-7).map((row) =>
          `<div class="digest-item"><div class="time">${esc(row.date)}</div>
            <div class="body"><b>平均 ${row.average} 分</b><div class="sub">${row.runs} 次运行</div></div>
            <div style="width:90px;height:5px;background:var(--surface-2);border-radius:3px;overflow:hidden">
              <div style="width:${Math.max(0, Math.min(100, row.average))}%;height:100%;background:var(--accent-text)"></div></div>
          </div>`).join("")}</div>` : ""}
        ${fixtures.length ? `<div class="digest-list">${fixtures.map((row) =>
          `<div class="digest-item"><div class="body"><b>${esc(row.fixture)}</b>
            <div class="sub">最近 ${row.latest?.score ?? "—"} 分 · 平均 ${row.average} 分 · ${row.runs} 次</div></div>
            ${row.regression ? `<span class="badge bad">↓ ${row.regression}</span>` : `<span class="badge ok">稳定</span>`}
          </div>`).join("")}</div>` : ""}
        ${regressions.length ? `<div class="eval-checks">${regressions.map((row) =>
          `<div class="eval-check"><b>回归</b><span>${esc(row.fixture)}：${row.from} → ${row.to}（下降 ${row.drop}）</span></div>`).join("")}</div>` : ""}`;
    }

    async function loadTrend(view) {
      const box = view.querySelector("#eval-trend");
      if (!box) return;
      try {
        const data = await api("/api/evals/trend?limit=300");
        if (!view.isConnected) return;
        box.innerHTML = trendHtml(data);
      } catch (err) {
        box.innerHTML = `<div class="empty" style="padding:18px"><p>${esc(err.message)}</p></div>`;
      }
    }

    function render(view) {
      if (!state.instances?.length) {
        view.innerHTML = `<div class="empty">${icon("model")}<h4>没有可用实例</h4><p>请先新增或接入机器人。</p></div>`;
        return;
      }
      instanceId = instanceId || state.instances[0].id;
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left">
            <div class="field" style="margin:0;min-width:150px"><label>机器人</label><select id="eval-instance"></select></div>
            <div class="field" style="margin:0;min-width:170px"><label>对话模型</label><select id="eval-provider"></select></div>
            <div class="field" style="margin:0;min-width:150px"><label>人格</label><select id="eval-persona"></select></div>
            <button class="btn sm primary" id="eval-run" style="align-self:flex-end">${icon("pulse")}开始回归</button>
          </div>
          <div class="right"><span class="side">评分：关键词 60 + 长度 20 + 禁用表达 20</span></div>
        </div>
        <div class="eval-layout">
          <div class="card">
            <div class="section-head" style="margin:0 0 10px"><h2>固定用例</h2><span class="side" id="eval-fixture-count">${fixtures.length || "…"} 个</span></div>
            <div id="eval-fixtures"><div class="skeleton" style="height:140px"></div></div>
            <p class="hint-text">用例读取自 data/eval_fixtures.json（不存在时使用内置 6 个），修改后刷新页面生效。</p>
          </div>
          <div class="digest-column">
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>本次结果</h2><span class="side">真实模型回复</span></div>
              <div id="eval-result"></div>
            </div>
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>回归趋势</h2><span class="side">按用例与日期</span></div>
              <div id="eval-trend"><div class="skeleton" style="height:100px"></div></div>
            </div>
            <div class="card">
              <div class="section-head" style="margin:0 0 10px"><h2>历史记录</h2><span class="side">最近 30 条</span></div>
              <div id="eval-history"><div class="skeleton" style="height:80px"></div></div>
            </div>
          </div>
        </div>`;
      view.querySelector("#eval-instance").addEventListener("change", (event) => {
        instanceId = event.target.value;
        refreshOptions(view, true);
      });
      view.querySelector("#eval-provider").addEventListener("change", (event) => {
        providerId = event.target.value;
      });
      view.querySelector("#eval-persona").addEventListener("change", (event) => {
        personaId = event.target.value;
      });
      view.querySelector("#eval-run").addEventListener("click", (event) => run(view, event.currentTarget));
      fillSelects(view);
      refreshOptions(view);
      loadFixtures(view);
      loadHistory(view);
      loadTrend(view);
    }

    function leave() {
      optionsToken += 1;
    }

    return { render, leave };
  }

  return { create, fmtTime, normalizeList };
});
