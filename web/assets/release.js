/* 牧鱼 · 人格版本与灰度 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerRelease = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STATUS_TEXT = {
    draft: "草稿",
    scored: "已跑分",
    gray: "灰度中",
    live: "已全量",
    rolled_back: "已回滚",
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

  function scoreClass(score) {
    const value = Number(score) || 0;
    return value >= 70 ? "ok" : value >= 40 ? "warn" : "bad";
  }

  function create(ctx) {
    const { api, esc, icon, toast, state } = ctx;
    let instId = "";
    let viewEl = null;
    let personaId = "";
    let personas = [];
    let candidates = [];
    let providers = [];
    let providerId = "";
    let currentPrompt = "";
    let versions = [];
    let selectedId = "";
    let loadToken = 0;

    const instances = () =>
      state && Array.isArray(state.instances) ? state.instances : [];

    function emptyBox(title, text) {
      return `<div class="empty" style="padding:26px">${icon("alert")}<h4>${esc(title)}</h4><p>${esc(text)}</p></div>`;
    }

    function statusBadge(status) {
      const cls = status === "live" ? "ok" : status === "gray" ? "accent" : status === "rolled_back" ? "bad" : "";
      return `<span class="badge ${cls}">${esc(STATUS_TEXT[status] || status || "草稿")}</span>`;
    }

    function candidateRow(item) {
      const active = item.id === selectedId;
      const evalScore = item.eval ? item.eval.average : null;
      const abScore = item.ab ? item.ab.candidate && item.ab.candidate.average : null;
      return `<button class="ins-row ${active ? "active" : ""}" data-cand="${esc(item.id)}">
        <div class="ins-row-top">
          <span class="ins-sender">${esc(item.name)}</span>
          ${statusBadge(item.status)}
        </div>
        <div class="ins-row-meta">
          <span>${esc(item.persona_id)} · ${item.chars || 0} 字</span>
          ${evalScore != null ? `<span>跑分 ${evalScore}</span>` : ""}
          ${abScore != null ? `<span>A/B ${abScore}</span>` : ""}
        </div>
        <div class="ins-row-text">${esc((item.note || item.prompt || "").slice(0, 110))}</div>
      </button>`;
    }

    function diffHtml(diff) {
      if (!diff) return "";
      const lines = Array.isArray(diff.lines) ? diff.lines : [];
      if (!lines.length) return `<div class="ins-hint">两侧内容完全一致，没有差异。</div>`;
      return `<div class="ins-diff">
        ${lines.map((line) => {
          const cls = line.type === "add" ? "add" : line.type === "del" ? "del" : "";
          const mark = line.type === "add" ? "+" : line.type === "del" ? "-" : " ";
          return `<div class="ins-diff-line ${cls}"><span>${mark}</span>${esc(line.text || " ")}</div>`;
        }).join("")}
      </div>
      <div class="ins-hint">新增 ${diff.added || 0} 行，删除 ${diff.removed || 0} 行；当前 ${diff.old_chars || 0} 字 → 候选 ${diff.new_chars || 0} 字。</div>`;
    }

    function evalHtml(evalResult) {
      if (!evalResult) return `<div class="ins-hint">还没有跑分。先点「影子跑分」，候选人格只在评测里使用，不会写线上。</div>`;
      const results = Array.isArray(evalResult.results) ? evalResult.results : [];
      return `
        <div class="ins-kv">
          <div><span>平均分</span><b>${evalResult.average ?? "—"}</b></div>
          <div><span>通过</span><b>${evalResult.passed ?? 0} / ${evalResult.total ?? 0}</b></div>
          <div><span>模型</span><b class="mono">${esc(evalResult.model || "—")}</b></div>
          <div><span>时间</span><b>${esc(fmtTime(evalResult.at))}</b></div>
        </div>
        ${results.length ? `<div class="ins-mem-list">${results.map((item) => `
          <div class="ins-mem">
            <div class="ins-mem-top">
              <span class="badge ${item.status === "ok" ? "ok" : "bad"}">${esc(item.status || "—")}</span>
              <span class="ins-mem-id">${esc(item.title || item.fixture)}</span>
              <span class="ins-count">${item.score ?? 0} 分</span>
            </div>
            ${item.reply ? `<div class="ins-mem-body">${esc(item.reply)}</div>` : ""}
          </div>`).join("")}</div>` : ""}`;
    }

    function abHtml(ab) {
      if (!ab) return `<div class="ins-hint">还没有 A/B 记录。A/B 会把线上人格和候选各跑一遍固定用例，消耗双倍模型调用。</div>`;
      const fixtures = Array.isArray(ab.fixtures) ? ab.fixtures : [];
      return `
        <div class="ins-ab">
          <div class="ins-ab-col"><span>线上</span><b>${ab.base ? ab.base.average : "—"}</b><i>通过 ${ab.base ? ab.base.passed : 0}/${ab.base ? ab.base.total : 0}</i></div>
          <div class="ins-ab-col"><span>候选</span><b>${ab.candidate ? ab.candidate.average : "—"}</b><i>通过 ${ab.candidate ? ab.candidate.passed : 0}/${ab.candidate ? ab.candidate.total : 0}</i></div>
          <div class="ins-ab-col ${ab.delta > 0 ? "up" : ab.delta < 0 ? "down" : ""}">
            <span>差值</span><b>${ab.delta > 0 ? "+" : ""}${ab.delta ?? 0}</b>
            <i>${ab.winner === "candidate" ? "候选更好" : ab.winner === "base" ? "线上更好" : "持平"}</i>
          </div>
        </div>
        ${fixtures.length ? `<div class="ins-mem-list">${fixtures.map((row) => `
          <div class="ins-mem">
            <div class="ins-mem-top">
              <span class="ins-mem-id">${esc(row.title || row.fixture)}</span>
              <span class="ins-count">线上 ${row.base} · 候选 ${row.candidate}</span>
              <span class="badge ${row.delta > 0 ? "ok" : row.delta < 0 ? "bad" : ""}">${row.delta > 0 ? "+" : ""}${row.delta}</span>
            </div>
            ${row.candidate_reply ? `<div class="ins-mem-body">候选回复：${esc(row.candidate_reply)}</div>` : ""}
          </div>`).join("")}</div>` : ""}`;
    }

    function deployHtml(item) {
      const running = instances().filter((inst) => inst.status && inst.status.running);
      const gray = item.gray || item.rollout;
      return `
        <div class="ins-deploy">
          <div class="field" style="margin:0;min-width:180px">
            <label>灰度目标实例</label>
            <select id="pr-target">
              ${running.length
                ? running.map((inst) => `<option value="${esc(inst.id)}" ${inst.id === instId ? "selected" : ""}>${esc(inst.name || inst.id)}</option>`).join("")
                : `<option value="">没有运行中的实例</option>`}
            </select>
          </div>
          <button class="btn sm" data-deploy="gray" ${running.length ? "" : "disabled"}>${icon("pulse")}灰度上线</button>
          <button class="btn sm primary" data-deploy="full">${icon("check")}全量上线</button>
          <button class="btn sm ghost" data-rollback="1" ${gray ? "" : "disabled"}>${icon("restart")}一键回滚</button>
        </div>
        ${gray ? `<div class="ins-hint">最近一次上线：${esc(fmtTime(gray.at))} · ${gray.targets.map((target) => esc(target.inst_name)).join("、")}。上线前已自动快照，可一键回滚。</div>` : ""}`;
    }

    function versionHtml() {
      if (!versions.length) {
        return `<div class="ins-hint">这个人格还没有历史快照。保存、导入、恢复或灰度上线前都会自动快照。</div>`;
      }
      return `<div class="ins-mem-list">${versions.slice(0, 10).map((item) => `
        <div class="ins-mem">
          <div class="ins-mem-top">
            <span class="ins-mem-id">${esc(item.time)}</span>
            <span class="ins-count">${item.chars} 字</span>
            <button class="btn sm ghost" data-vdiff="${esc(item.ts)}">对比当前</button>
            <button class="btn sm" data-vrestore="${esc(item.ts)}">恢复</button>
          </div>
          <div class="ins-mem-body">${esc(item.preview || "（无预览）")}</div>
        </div>`).join("")}</div>
        <div id="pr-vdiff"></div>`;
    }

    function detailHtml(item) {
      if (!item) {
        return `<div class="ins-placeholder">${icon("model")}<p>从左侧选一个候选人格，查看差异、跑分并灰度上线。</p></div>`;
      }
      return `
        <div class="ins-detail-head">
          <div>
            <h3>${esc(item.name)}</h3>
            <p>${esc(item.persona_id)} · 来自 ${esc(item.inst_name || item.inst_id || "—")} · ${esc(fmtTime(item.created))}</p>
          </div>
          <div class="ins-badges">${statusBadge(item.status)}<span class="badge">${item.chars || 0} 字</span></div>
        </div>
        ${item.note ? `<div class="ins-hint">${esc(item.note)}</div>` : ""}
        <section class="ins-sec">
          <h4>候选内容</h4>
          <details class="ins-details">
            <summary>展开查看完整提示词</summary>
            <pre class="ins-pre">${esc(item.prompt || "")}</pre>
          </details>
        </section>
        <section class="ins-sec">
          <h4>与线上差异</h4>
          <div class="ins-actions"><button class="btn sm ghost" data-diff="1">${icon("search")}计算差异</button></div>
          <div id="pr-diff"></div>
        </section>
        <section class="ins-sec">
          <h4>影子跑分</h4>
          <div class="ins-actions">
            <button class="btn sm" data-shadow="1">${icon("pulse")}影子跑分</button>
            <button class="btn sm" data-ab="1">${icon("model")}A/B 对比</button>
            <span class="ins-hint" style="margin-left:auto">模型：${esc(providerId || "未选择")}</span>
          </div>
          <div id="pr-eval">${evalHtml(item.eval)}</div>
          <div id="pr-ab">${abHtml(item.ab)}</div>
        </section>
        <section class="ins-sec">
          <h4>发布与回滚</h4>
          ${deployHtml(item)}
        </section>
        <section class="ins-sec">
          <h4>编辑候选</h4>
          <div class="ins-actions"><button class="btn sm ghost" data-edit="1">${icon("edit")}修改名称或内容</button></div>
          <div id="pr-edit" hidden>
            <div class="field"><label>名称</label><input type="text" id="pr-edit-name" value="${esc(item.name)}"></div>
            <div class="field"><label>候选提示词</label><textarea id="pr-edit-prompt" rows="10" spellcheck="false">${esc(item.prompt || "")}</textarea></div>
            <div class="ins-actions">
              <button class="btn sm primary" data-save-edit="1">${icon("check")}保存候选</button>
              <button class="btn sm ghost" data-cancel-edit="1">取消</button>
              <button class="btn sm danger" data-delete="1" style="margin-left:auto">${icon("trash")}删除候选</button>
            </div>
          </div>
        </section>`;
    }

    function paintDetail() {
      const box = viewEl && viewEl.querySelector("#pr-detail");
      if (!box) return;
      const item = candidates.find((cand) => cand.id === selectedId) || null;
      box.innerHTML = detailHtml(item);
      bindDetail();
    }

    function bindDetail() {
      const box = viewEl && viewEl.querySelector("#pr-detail");
      if (!box) return;
      const diffBtn = box.querySelector("[data-diff]");
      if (diffBtn) diffBtn.addEventListener("click", () => loadDiff(selectedId));
      const shadowBtn = box.querySelector("[data-shadow]");
      if (shadowBtn) shadowBtn.addEventListener("click", () => runShadow(selectedId, shadowBtn));
      const abBtn = box.querySelector("[data-ab]");
      if (abBtn) abBtn.addEventListener("click", () => runAb(selectedId, abBtn));
      box.querySelectorAll("[data-deploy]").forEach((btn) => {
        btn.addEventListener("click", () => deploy(selectedId, btn.dataset.deploy, btn));
      });
      const rollbackBtn = box.querySelector("[data-rollback]");
      if (rollbackBtn) rollbackBtn.addEventListener("click", () => rollback(selectedId));
      const editBtn = box.querySelector("[data-edit]");
      if (editBtn) {
        editBtn.addEventListener("click", () => {
          const edit = box.querySelector("#pr-edit");
          if (edit) edit.hidden = !edit.hidden;
        });
      }
      const saveEdit = box.querySelector("[data-save-edit]");
      if (saveEdit) saveEdit.addEventListener("click", () => saveEditCandidate(selectedId));
      const cancelEdit = box.querySelector("[data-cancel-edit]");
      if (cancelEdit) {
        cancelEdit.addEventListener("click", () => {
          const edit = box.querySelector("#pr-edit");
          if (edit) edit.hidden = true;
        });
      }
      const deleteBtn = box.querySelector("[data-delete]");
      if (deleteBtn) deleteBtn.addEventListener("click", () => deleteCandidate(selectedId));
    }

    async function loadDiff(candidateId) {
      const box = viewEl && viewEl.querySelector("#pr-diff");
      if (!box) return;
      box.innerHTML = `<div class="skeleton" style="height:100px"></div>`;
      try {
        const data = await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/candidates/${encodeURIComponent(candidateId)}/diff`,
        );
        box.innerHTML = diffHtml(data && data.diff);
      } catch (err) {
        box.innerHTML = emptyBox("计算差异失败", err.message);
      }
    }

    async function runShadow(candidateId, btn) {
      if (!providerId) {
        toast("先选择跑分用的对话模型", "warn");
        return;
      }
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.textContent = "跑分中…";
      try {
        const result = await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/candidates/${encodeURIComponent(candidateId)}/shadow`,
          { method: "POST", body: { provider_id: providerId } },
        );
        toast(`影子跑分完成：平均 ${result.average} 分`);
        await loadCandidates();
        paintDetail();
      } catch (err) {
        toast(err.message, "err");
        btn.disabled = false;
        btn.innerHTML = original;
      }
    }

    async function runAb(candidateId, btn) {
      if (!providerId) {
        toast("先选择对比用的对话模型", "warn");
        return;
      }
      if (!window.confirm("A/B 会把线上人格和候选用同一批固定用例各跑一遍，模型调用翻倍。继续？")) return;
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.textContent = "对比中…";
      try {
        const result = await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/candidates/${encodeURIComponent(candidateId)}/ab`,
          { method: "POST", body: { provider_id: providerId } },
        );
        toast(`A/B 完成：线上 ${result.base.average} → 候选 ${result.candidate.average}（${result.delta > 0 ? "+" : ""}${result.delta}）`);
        await loadCandidates();
        paintDetail();
      } catch (err) {
        toast(err.message, "err");
        btn.disabled = false;
        btn.innerHTML = original;
      }
    }

    async function deploy(candidateId, mode, btn) {
      let targetIds = [];
      if (mode === "gray") {
        const select = viewEl && viewEl.querySelector("#pr-target");
        const target = select ? select.value : "";
        if (!target) {
          toast("没有可用的灰度目标实例", "warn");
          return;
        }
        targetIds = [target];
      }
      const text =
        mode === "gray"
          ? "只把候选人格写到选中的实例，其它实例保持线上版本。继续？"
          : "把候选人格写到所有存在该人格的实例。每个实例上线前都会自动快照。继续？";
      if (!window.confirm(text)) return;
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.textContent = mode === "gray" ? "灰度中…" : "上线中…";
      try {
        const result = await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/candidates/${encodeURIComponent(candidateId)}/deploy`,
          { method: "POST", body: { mode, instances: targetIds } },
        );
        const applied = result.applied || [];
        toast(`${mode === "gray" ? "已灰度" : "已全量"}上线 ${applied.length} 个实例`);
        if (result.failed && result.failed.length) {
          toast(`有 ${result.failed.length} 个实例失败：${result.failed.map((item) => item.error).join("；")}`, "warn");
        }
        await loadWorkbench();
        await loadCandidates();
        paintDetail();
      } catch (err) {
        toast(err.message, "err");
        btn.disabled = false;
        btn.innerHTML = original;
      }
    }

    async function rollback(candidateId) {
      if (!window.confirm("回滚到该候选上次上线前的自动快照？当前线上内容会被覆盖。")) return;
      try {
        const result = await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/candidates/${encodeURIComponent(candidateId)}/rollback`,
          { method: "POST", body: {} },
        );
        toast(`已回滚 ${(result.applied || []).length} 个实例`);
        await loadWorkbench();
        await loadCandidates();
        paintDetail();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function saveEditCandidate(candidateId) {
      const name = viewEl.querySelector("#pr-edit-name");
      const prompt = viewEl.querySelector("#pr-edit-prompt");
      if (!prompt || !prompt.value.trim()) {
        toast("候选提示词不能为空", "warn");
        return;
      }
      try {
        await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/candidates/${encodeURIComponent(candidateId)}`,
          {
            method: "PATCH",
            body: {
              name: name ? name.value.trim() : "",
              prompt: prompt.value,
            },
          },
        );
        toast("候选人格已保存");
        await loadCandidates();
        paintDetail();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function deleteCandidate(candidateId) {
      if (!window.confirm("删除这个候选人格？只会删除候选，不影响线上人格。")) return;
      try {
        await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/candidates/${encodeURIComponent(candidateId)}`,
          { method: "DELETE" },
        );
        toast("候选已删除");
        selectedId = "";
        await loadCandidates();
        paintDetail();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function createPanelHtml() {
      return `<div class="ins-create" id="pr-create" hidden>
        <div class="field"><label>候选名称</label><input type="text" id="pr-name" placeholder="例如 更克制版 / 口语化版"></div>
        <div class="field"><label>候选提示词</label>
          <textarea id="pr-prompt" rows="12" spellcheck="false">${esc(currentPrompt)}</textarea>
        </div>
        <div class="ins-actions">
          <button class="btn sm primary" id="pr-create-save">${icon("plus")}创建候选</button>
          <button class="btn sm ghost" id="pr-create-cancel">取消</button>
        </div>
      </div>`;
    }

    function paintList() {
      const box = viewEl && viewEl.querySelector("#pr-cands");
      if (!box) return;
      if (!candidates.length) {
        box.innerHTML = `<div class="ins-hint">还没有候选人格。点「新建候选」会复制当前线上一份，改完后先影子跑分，再灰度。</div>`;
        return;
      }
      box.innerHTML = candidates.map(candidateRow).join("");
      box.querySelectorAll("[data-cand]").forEach((el) => {
        el.addEventListener("click", () => {
          selectedId = el.dataset.cand;
          paintList();
          paintDetail();
        });
      });
    }

    async function loadCandidates() {
      try {
        const items = await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/candidates?persona_id=${encodeURIComponent(personaId)}`,
        );
        candidates = Array.isArray(items) ? items : [];
      } catch (_) {
        candidates = [];
      }
      if (selectedId && !candidates.some((item) => item.id === selectedId)) {
        selectedId = candidates.length ? candidates[0].id : "";
      }
      paintList();
      paintDetail();
    }

    async function loadWorkbench() {
      const token = ++loadToken;
      try {
        const query = personaId ? `?persona_id=${encodeURIComponent(personaId)}` : "";
        const data = await api(`/api/instances/${encodeURIComponent(instId)}/personas/workbench${query}`);
        if (token !== loadToken || !viewEl || !viewEl.isConnected) return;
        if (!data || data.empty) {
          viewEl.innerHTML = emptyBox("这个人格库是空的", "先到「模型与人格」页创建一个人格。");
          return;
        }
        personas = Array.isArray(data.personas) ? data.personas : [];
        personaId = data.persona_id || personaId;
        currentPrompt = data.prompt || "";
        versions = Array.isArray(data.versions) ? data.versions : [];
        fillPersonaSelect();
        fillProviderSelect();
        const versionsBox = viewEl.querySelector("#pr-versions");
        if (versionsBox) versionsBox.innerHTML = versionHtml();
        bindVersions();
        await loadCandidates();
      } catch (err) {
        if (token !== loadToken) return;
        const list = viewEl.querySelector("#pr-cands");
        if (list) list.innerHTML = emptyBox("读取人格失败", err.message);
      }
    }

    function fillPersonaSelect() {
      const select = viewEl && viewEl.querySelector("#pr-persona");
      if (!select) return;
      select.innerHTML = personas.length
        ? personas.map((item) => `<option value="${esc(item.persona_id)}" ${item.persona_id === personaId ? "selected" : ""}>${esc(item.persona_id)}（${item.chars} 字）</option>`).join("")
        : `<option value="">没有可用人格</option>`;
    }

    function fillProviderSelect() {
      const select = viewEl && viewEl.querySelector("#pr-provider");
      if (!select) return;
      select.innerHTML = providers.length
        ? providers.map((item) => `<option value="${esc(item.id)}" ${item.id === providerId ? "selected" : ""}>${esc(item.model || item.id)}</option>`).join("")
        : `<option value="">没有对话模型</option>`;
    }

    function bindVersions() {
      const box = viewEl && viewEl.querySelector("#pr-versions");
      if (!box) return;
      box.querySelectorAll("[data-vdiff]").forEach((btn) => {
        btn.addEventListener("click", () => diffVersion(Number(btn.dataset.vdiff)));
      });
      box.querySelectorAll("[data-vrestore]").forEach((btn) => {
        btn.addEventListener("click", () => restoreVersion(Number(btn.dataset.vrestore)));
      });
    }

    async function diffVersion(ts) {
      const box = viewEl && viewEl.querySelector("#pr-vdiff");
      if (!box) return;
      box.innerHTML = `<div class="skeleton" style="height:90px"></div>`;
      try {
        const data = await api(
          `/api/instances/${encodeURIComponent(instId)}/personas/versions/diff?persona_id=${encodeURIComponent(personaId)}&a=${ts}&b=0`,
        );
        box.innerHTML = diffHtml(data && data.diff);
      } catch (err) {
        box.innerHTML = emptyBox("对比版本失败", err.message);
      }
    }

    async function restoreVersion(ts) {
      if (!window.confirm("恢复到这个历史版本？恢复前会自动快照当前线上内容。")) return;
      try {
        await api(`/api/instances/${encodeURIComponent(instId)}/personas/workbench/restore`, {
          method: "POST",
          body: { persona_id: personaId, ts },
        });
        toast("已恢复该版本");
        await loadWorkbench();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    async function createCandidate() {
      const name = viewEl && viewEl.querySelector("#pr-name");
      const prompt = viewEl && viewEl.querySelector("#pr-prompt");
      if (!prompt || !prompt.value.trim()) {
        toast("候选提示词不能为空", "warn");
        return;
      }
      try {
        const item = await api(`/api/instances/${encodeURIComponent(instId)}/personas/candidates`, {
          method: "POST",
          body: {
            persona_id: personaId,
            name: name ? name.value.trim() : "",
            prompt: prompt.value,
            source: "copy",
          },
        });
        toast("候选人格已创建");
        selectedId = item.id;
        const panel = viewEl.querySelector("#pr-create");
        if (panel) panel.hidden = true;
        await loadCandidates();
      } catch (err) {
        toast(err.message, "err");
      }
    }

    function bindTop() {
      const personaSelect = viewEl.querySelector("#pr-persona");
      if (personaSelect) {
        personaSelect.addEventListener("change", () => {
          personaId = personaSelect.value;
          selectedId = "";
          loadWorkbench();
        });
      }
      const providerSelect = viewEl.querySelector("#pr-provider");
      if (providerSelect) {
        providerSelect.addEventListener("change", () => {
          providerId = providerSelect.value;
        });
      }
      const refresh = viewEl.querySelector("#pr-refresh");
      if (refresh) refresh.addEventListener("click", () => loadWorkbench());
      const newBtn = viewEl.querySelector("#pr-new");
      if (newBtn) {
        newBtn.addEventListener("click", () => {
          const panel = viewEl.querySelector("#pr-create");
          if (!panel) return;
          panel.hidden = !panel.hidden;
          if (!panel.hidden) {
            const textarea = viewEl.querySelector("#pr-prompt");
            if (textarea && !textarea.value) textarea.value = currentPrompt;
            const nameInput = viewEl.querySelector("#pr-name");
            if (nameInput) nameInput.focus();
          }
        });
      }
      const saveBtn = viewEl.querySelector("#pr-create-save");
      if (saveBtn) saveBtn.addEventListener("click", createCandidate);
      const cancelBtn = viewEl.querySelector("#pr-create-cancel");
      if (cancelBtn) {
        cancelBtn.addEventListener("click", () => {
          const panel = viewEl.querySelector("#pr-create");
          if (panel) panel.hidden = true;
        });
      }
    }

    async function loadProviders() {
      try {
        const summary = await api(`/api/instances/${encodeURIComponent(instId)}/summary`).catch(() => null);
        providers = Array.isArray(summary && summary.providers)
          ? summary.providers.filter((item) => item && item.id && (!item.type || String(item.type).includes("chat")))
          : [];
      } catch (_) {
        providers = [];
      }
      if (!providers.some((item) => item.id === providerId)) {
        providerId = providers.find((item) => item.enable !== false)?.id || providers[0]?.id || "";
      }
      fillProviderSelect();
    }

    function render(view) {
      viewEl = view;
      const list = instances();
      if (!list.length) {
        view.innerHTML = emptyBox("没有可用实例", "请先在「机器人」页新增或接入一个机器人。");
        return;
      }
      const focusHit = globalThis.ManagerFocus && globalThis.ManagerFocus.consume(list);
      if (focusHit) instId = String(focusHit.id);
      else if (!instId || !list.some((item) => item.id === instId)) instId = ((globalThis.ManagerFocus && globalThis.ManagerFocus.pick(list)) || list[0]).id;
      view.innerHTML = `
        <div class="chips">
          ${list.map((item) => `<button class="chip ${item.id === instId ? "active" : ""}" data-pr-inst="${esc(item.id)}">${esc(item.name || item.id)}${item.status && item.status.running ? "" : "（未运行）"}</button>`).join("")}
        </div>
        <div class="ins-toolbar">
          <div class="field" style="margin:0;min-width:180px"><label>人格</label><select id="pr-persona"></select></div>
          <div class="field" style="margin:0;min-width:170px"><label>跑分模型</label><select id="pr-provider"></select></div>
          <button class="btn sm ghost" id="pr-refresh" style="align-self:flex-end">${icon("refresh")}刷新</button>
          <button class="btn sm primary" id="pr-new" style="align-self:flex-end">${icon("plus")}新建候选</button>
        </div>
        <div class="ins-layout">
          <section class="card ins-side">
            <div class="ins-side-head"><h3>候选池</h3><span>${icon("model")}</span></div>
            ${createPanelHtml()}
            <div id="pr-cands" class="ins-list"><div class="skeleton" style="height:160px"></div></div>
          </section>
          <div class="ins-right">
            <section class="card ins-detail" id="pr-detail">
              <div class="ins-placeholder">${icon("model")}<p>从左侧选一个候选人格，查看差异、跑分并灰度上线。</p></div>
            </section>
            <section class="card" style="margin-top:14px">
              <div class="ins-side-head"><h3>版本与快照</h3><span>最近 10 个</span></div>
              <div id="pr-versions"><div class="skeleton" style="height:90px"></div></div>
            </section>
          </div>
        </div>`;

      view.querySelectorAll("[data-pr-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.prInst;
          personaId = "";
          selectedId = "";
          candidates = [];
          versions = [];
          render(view);
        });
      });
      bindTop();
      fillPersonaSelect();
      fillProviderSelect();
      loadProviders().then(() => loadWorkbench());
    }

    return { render };
  }

  return { create, fmtTime, scoreClass };
});
