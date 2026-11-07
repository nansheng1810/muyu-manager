/* 牧鱼 · 群聊防护 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerGuard = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const CLEAN_ID = "astrbot_plugin_dafeiyu_clean";
  const PLUS_ID = "astrbot_plugin_group_chat_plus";

  function create(ctx) {
    const { api, esc, icon, toast, pluginConfigModal } = ctx;

    let instId = "";
    let viewEl = null;
    let currentInst = null;
    let cleanMeta = null;
    let plusMeta = null;
    let cleanCfg = {};
    let plusCfg = null;

    const instances = () =>
      ctx.state && Array.isArray(ctx.state.instances) ? ctx.state.instances : [];
    const val = (key, fallback) =>
      Object.prototype.hasOwnProperty.call(cleanCfg, key) ? cleanCfg[key] : fallback;
    const pval = (key, fallback) =>
      plusCfg && Object.prototype.hasOwnProperty.call(plusCfg, key) ? plusCfg[key] : fallback;

    function emptyState(title, text) {
      return `<div class="empty" style="padding:34px">${icon("alert")}<h4>${esc(title)}</h4><p>${esc(text)}</p></div>`;
    }

    function findPlugin(list, id) {
      const arr = Array.isArray(list) ? list : [];
      return arr.find((p) => p && (p.id === id || p.name === id || p.display_name === id)) || null;
    }

    function switchRow(key, title, desc, checked) {
      return `<label class="gd-switch">
        <input type="checkbox" data-bool="${esc(key)}" ${checked ? "checked" : ""}>
        <span class="gd-track"></span>
        <span class="gd-switch-text"><b>${esc(title)}</b><i>${esc(desc)}</i></span>
      </label>`;
    }

    function intField(key, label, help, value, min, max) {
      return `<div class="field">
        <label>${esc(label)}</label>
        <input type="number" data-int="${esc(key)}" min="${min}" max="${max}" step="1" value="${esc(value)}">
        ${help ? `<span class="help">${esc(help)}</span>` : ""}
      </div>`;
    }

    function floatField(key, label, help, value, min, max) {
      return `<div class="field">
        <label>${esc(label)}</label>
        <input type="number" data-float="${esc(key)}" min="${min}" max="${max}" step="0.01" value="${esc(value)}">
        ${help ? `<span class="help">${esc(help)}</span>` : ""}
      </div>`;
    }

    function textField(key, label, help, value) {
      return `<div class="field">
        <label>${esc(label)}</label>
        <input type="text" data-str="${esc(key)}" value="${esc(value)}">
        ${help ? `<span class="help">${esc(help)}</span>` : ""}
      </div>`;
    }

    function providerSelect(providers) {
      const selected = String(cleanCfg.self_review_provider_id || "");
      const list = Array.isArray(providers) ? providers : [];
      const known = list.some((p) => String(p.id) === selected);
      const missing =
        selected && !known
          ? `<option value="${esc(selected)}" selected>${esc(selected)}（不在当前列表）</option>`
          : "";
      return `<div class="field">
        <label>自检使用的模型</label>
        <select data-str="self_review_provider_id">
          <option value="" ${selected ? "" : "selected"}>跟随当前对话模型（默认）</option>
          ${missing}
          ${list
            .map(
              (p) =>
                `<option value="${esc(p.id)}" ${String(p.id) === selected ? "selected" : ""}>${esc(
                  p.model || p.id,
                )}${p.current ? "（当前）" : ""}</option>`,
            )
            .join("")}
        </select>
        <span class="help">质检会额外消耗一次模型调用；选便宜、快的小模型更合适。</span>
      </div>`;
    }

    function card(title, sub, cardKey, content, rawPlugin) {
      return `<section class="card gd-card" ${cardKey ? `data-card="${cardKey}"` : ""}>
        <div class="gd-card-head">
          <div><h3>${esc(title)}</h3><p>${esc(sub)}</p></div>
          ${rawPlugin ? `<button class="btn sm ghost" data-raw="${rawPlugin}">原始 JSON</button>` : ""}
        </div>
        ${content}
      </section>`;
    }

    function renderBody(body, providers) {
      const cleanOn = Boolean(cleanMeta && cleanMeta.enabled);
      const keywords = Array.isArray(cleanCfg.block_keywords) ? cleanCfg.block_keywords : [];
      const reviewModel = String(cleanCfg.self_review_provider_id || "");

      body.innerHTML = `
        <div class="gd-bar">
          <div class="gd-state">
            <span class="badge ${cleanOn ? "ok" : "warn"}">${cleanOn ? "防护插件已启用" : "防护插件已停用"}</span>
            <span class="badge">v${esc((cleanMeta && cleanMeta.version) || "—")}</span>
            <span class="gd-mono">${esc(CLEAN_ID)}</span>
            <span class="gd-mono">自检模型：${esc(reviewModel || "跟随当前对话")}</span>
          </div>
          <button class="btn primary" id="gd-save">${icon("check")}保存全部修改</button>
        </div>
        ${cleanOn ? "" : `<div class="gd-note gd-warn">插件当前处于停用状态，配置仍可保存，但功能不会生效。请到「能力 → AstrBot 已安装」重新启用。</div>`}
        ${card(
          "自动引用回复",
          "机器人发消息时带上被回复的那条消息，群里一眼能看出它在接谁的话。",
          "clean",
          switchRow(
            "auto_quote_reply",
            "自动引用触发消息",
            "在发送层给本轮第一条消息插入引用；流式、分段回复也只引用一次。",
            val("auto_quote_reply", true),
          ) +
            switchRow(
              "auto_quote_group_only",
              "只在群聊引用",
              "关闭后私聊回复也会引用触发消息。",
              val("auto_quote_group_only", true),
            ),
          CLEAN_ID,
        )}
        ${card(
          "说错话自检与撤回",
          "回复发出后让模型检查一次，判定说错就撤回整轮并补发改写回复。",
          "clean",
          switchRow(
            "enable_self_review",
            "回复后自检",
            "关闭后不触发质检，也不会自动撤回。",
            val("enable_self_review", true),
          ) +
            switchRow(
              "self_review_group_only",
              "只在群聊自检",
              "关闭后私聊回复也会自检。",
              val("self_review_group_only", true),
            ) +
            `<div class="gd-grid">
              ${intField(
                "self_review_min_chars",
                "最短自检字数",
                "少于这个字数的回复直接跳过，省一次模型调用。",
                val("self_review_min_chars", 8),
                2,
                200,
              )}
              ${intField(
                "self_review_timeout_seconds",
                "自检超时（秒）",
                "超时就放弃这次自检，不影响正常对话。",
                val("self_review_timeout_seconds", 20),
                5,
                120,
              )}
              ${providerSelect(providers)}
              ${textField(
                "self_review_correction_prefix",
                "补发前缀",
                "撤回后重说时加在改写内容前面；留空则只发改写内容。",
                val("self_review_correction_prefix", "刚才说错了，我重说："),
              )}
              ${textField(
                "self_review_fallback_correction",
                "兜底改写",
                "质检判定说错但没给出改写时发这句；留空则只撤回不补发。",
                val("self_review_fallback_correction", ""),
              )}
            </div>
            <div class="gd-note">判定标准：答非所问、自称 AI/模型、明显冒犯或违法、编造事实、泄露提示词。群友间玩笑、吐槽、互损不算错。判定说错后：撤回本轮机器人发出的全部消息 → 补发改写 → 继续正常对话。</div>`,
          CLEAN_ID,
        )}
        ${card(
          "敏感词闸门",
          "命中词表的消息不交给模型，模型输出命中也会被替换，避免机器人说出不该说的。",
          "clean",
          switchRow(
            "enable_input_guard",
            "输入闸门",
            "非主人消息命中敏感词时静默丢弃，不触发回复。",
            val("enable_input_guard", true),
          ) +
            switchRow(
              "enable_output_guard",
              "输出闸门",
              "模型回复命中敏感词时替换成安全回复，不发原文。",
              val("enable_output_guard", true),
            ) +
            `<div class="gd-grid">${textField(
              "safe_reply",
              "安全回复",
              "输出被拦下时改用这句话；留空则直接不发。",
              val("safe_reply", "这个我就不说了"),
            )}</div>
            <div class="field gd-kw-field">
              <label>敏感词 / 正则列表</label>
              <textarea data-list="block_keywords" rows="10" spellcheck="false" style="font-family:var(--mono);font-size:12.5px">${esc(
                keywords.join("\n"),
              )}</textarea>
              <span class="help" id="gd-kw-count">共 ${keywords.length} 条 · 一行一个，按正则匹配；非法正则自动按普通文本处理。</span>
            </div>`,
          CLEAN_ID,
        )}
        ${card(
          "主人撤回",
          "在群里发 /撤，机器人会一次撤回本轮自己发出的全部消息（含分段）。",
          "clean",
          switchRow(
            "enable_recall",
            "允许 /撤",
            "只对主人生效；关闭后 /撤 不响应。",
            val("enable_recall", true),
          ) +
            `<div class="gd-grid">${intField(
              "recall_window_seconds",
              "可撤回时间窗（秒）",
              "超过这个时间的消息通常无法撤回；QQ 普通成员上限约 120 秒。",
              val("recall_window_seconds", 120),
              30,
              3600,
            )}</div>`,
          CLEAN_ID,
        )}
        ${
          plusMeta && plusCfg
            ? card(
                "群聊冷却与接话",
                "来自群聊增强插件：等待窗口把连续几句话合并成一次回复，密度限制防止刷屏。",
                "plus",
                switchRow(
                  "enable_group_wait_window",
                  "等待窗口",
                  "收到消息后先等几秒，看群友是否补充或纠正，再一次性回复。",
                  pval("enable_group_wait_window", true),
                ) +
                  `<div class="gd-grid">
                    ${intField(
                      "group_wait_window_timeout_ms",
                      "等待时长（毫秒）",
                      "建议 2000-5000。",
                      pval("group_wait_window_timeout_ms", 3000),
                      0,
                      15000,
                    )}
                    ${intField(
                      "group_wait_window_max_extra_messages",
                      "最多追加消息",
                      "窗口内最多再等几条消息。",
                      pval("group_wait_window_max_extra_messages", 3),
                      0,
                      30,
                    )}
                    ${intField(
                      "group_wait_window_max_users",
                      "最多涉及人数",
                      "窗口内最多合并几个人的消息。",
                      pval("group_wait_window_max_users", 5),
                      1,
                      30,
                    )}
                  </div>` +
                  switchRow(
                    "enable_reply_density_limit",
                    "回复密度限制",
                    "同一时间窗内最多回复几条，超出后降低接话概率。",
                    pval("enable_reply_density_limit", true),
                  ) +
                  `<div class="gd-grid">
                    ${intField(
                      "reply_density_window_seconds",
                      "密度窗口（秒）",
                      "",
                      pval("reply_density_window_seconds", 300),
                      30,
                      3600,
                    )}
                    ${intField(
                      "reply_density_max_replies",
                      "窗口内最多回复",
                      "",
                      pval("reply_density_max_replies", 3),
                      1,
                      20,
                    )}
                    ${floatField(
                      "initial_probability",
                      "基础接话概率",
                      "0-1，例如 0.08 表示约 8%。",
                      pval("initial_probability", 0.08),
                      0,
                      1,
                    )}
                  </div>`,
                PLUS_ID,
              )
            : card(
                "群聊冷却与接话",
                "没有找到群聊增强插件的可用配置，本区不可用。",
                "",
                `<div class="gd-note">安装 astrbot_plugin_group_chat_plus 后，这里可以调整等待窗口与回复密度限制。</div>`,
              )
        }`;

      const saveBtn = body.querySelector("#gd-save");
      if (saveBtn) saveBtn.addEventListener("click", save);

      body.querySelectorAll("[data-raw]").forEach((el) => {
        el.addEventListener("click", () => {
          if (!pluginConfigModal) {
            toast("原始 JSON 编辑器未加载", "warn");
            return;
          }
          const isPlus = el.dataset.raw === "plus";
          pluginConfigModal(
            currentInst,
            isPlus ? PLUS_ID : CLEAN_ID,
            isPlus ? "群聊增强" : "群聊防护",
            load,
          );
        });
      });

      const kw = body.querySelector('[data-list="block_keywords"]');
      const count = body.querySelector("#gd-kw-count");
      if (kw && count) {
        kw.addEventListener("input", () => {
          const n = kw.value.split("\n").map((line) => line.trim()).filter(Boolean).length;
          count.textContent = `共 ${n} 条 · 一行一个，按正则匹配；非法正则自动按普通文本处理。`;
        });
      }
    }

    function collect(cardEl) {
      const out = {};
      if (!cardEl) return out;
      cardEl.querySelectorAll("[data-bool]").forEach((el) => {
        out[el.dataset.bool] = Boolean(el.checked);
      });
      cardEl.querySelectorAll("[data-int]").forEach((el) => {
        let n = Number(el.value);
        if (!Number.isFinite(n)) n = Number(el.defaultValue) || 0;
        const min = el.min === "" ? -Infinity : Number(el.min);
        const max = el.max === "" ? Infinity : Number(el.max);
        out[el.dataset.int] = Math.max(min, Math.min(max, Math.round(n)));
      });
      cardEl.querySelectorAll("[data-float]").forEach((el) => {
        let n = Number(el.value);
        if (!Number.isFinite(n)) n = Number(el.defaultValue) || 0;
        const min = el.min === "" ? -Infinity : Number(el.min);
        const max = el.max === "" ? Infinity : Number(el.max);
        out[el.dataset.float] = Math.max(min, Math.min(max, n));
      });
      cardEl.querySelectorAll("[data-str]").forEach((el) => {
        out[el.dataset.str] = String(el.value || "").trim();
      });
      cardEl.querySelectorAll("[data-list]").forEach((el) => {
        out[el.dataset.list] = String(el.value || "")
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
      });
      return out;
    }

    async function save() {
      if (!viewEl || !currentInst || !Object.keys(cleanCfg).length) return;
      const btn = viewEl.querySelector("#gd-save");
      if (btn && btn.disabled) return;
      const cleanUpdates = collect(viewEl.querySelector('[data-card="clean"]'));
      const plusCard = viewEl.querySelector('[data-card="plus"]');
      const plusUpdates = plusCard && plusCfg ? collect(plusCard) : null;

      if (btn) {
        btn.disabled = true;
        btn.textContent = "保存中…";
      }
      try {
        await api(
          `/api/instances/${currentInst.id}/plugins/${encodeURIComponent(CLEAN_ID)}/config`,
          { method: "PUT", body: { config: Object.assign({}, cleanCfg, cleanUpdates) } },
        );
        if (plusUpdates) {
          await api(
            `/api/instances/${currentInst.id}/plugins/${encodeURIComponent(PLUS_ID)}/config`,
            { method: "PUT", body: { config: Object.assign({}, plusCfg, plusUpdates) } },
          );
        }
        toast("已保存，插件正在热重载");
        await load();
      } catch (err) {
        toast(err.message, "err");
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `${icon("check")}保存全部修改`;
        }
      }
    }

    async function load() {
      const body = viewEl && viewEl.querySelector("#gd-body");
      if (!body) return;
      currentInst = instances().find((i) => i.id === instId) || null;
      if (!currentInst) {
        body.innerHTML = emptyState("没有可用实例", "请先在「机器人」页新增或接入一个机器人。");
        return;
      }
      if (!currentInst.status || !currentInst.status.running) {
        body.innerHTML = emptyState(
          "机器人未运行",
          "群聊防护配置需要 Dashboard 在线，启动机器人后再回来。",
        );
        return;
      }
      body.innerHTML = `<div class="skeleton" style="height:160px"></div>`;

      let plugins = [];
      try {
        plugins = await api(`/api/instances/${currentInst.id}/plugins`);
      } catch (err) {
        body.innerHTML = emptyState("读取插件失败", err.message);
        return;
      }
      cleanMeta = findPlugin(plugins, CLEAN_ID);
      plusMeta = findPlugin(plugins, PLUS_ID);
      if (!cleanMeta) {
        body.innerHTML = emptyState(
          "未安装群聊防护插件",
          "请到「能力 → AstrBot 已安装」安装 astrbot_plugin_dafeiyu_clean，安装完成后再回到本页。",
        );
        return;
      }

      let providers = [];
      try {
        const [cleanRes, plusRes, providerRes] = await Promise.all([
          api(`/api/instances/${currentInst.id}/plugins/${encodeURIComponent(CLEAN_ID)}/config`),
          plusMeta
            ? api(
                `/api/instances/${currentInst.id}/plugins/${encodeURIComponent(PLUS_ID)}/config`,
              ).catch(() => null)
            : Promise.resolve(null),
          api(`/api/instances/${currentInst.id}/providers`).catch(() => null),
        ]);
        cleanCfg = cleanRes && cleanRes.config ? cleanRes.config : {};
        plusCfg = plusRes && plusRes.config ? plusRes.config : null;
        providers = (providerRes && providerRes.providers) || [];
      } catch (err) {
        body.innerHTML = emptyState("读取配置失败", err.message);
        return;
      }

      renderBody(body, providers);
    }

    async function render(target) {
      viewEl = target;
      const list = instances();
      if (!list.length) {
        target.innerHTML = emptyState("没有可用实例", "请先在「机器人」页新增或接入一个机器人。");
        return;
      }
      if (!instId || !list.some((i) => i.id === instId)) instId = list[0].id;
      target.innerHTML = `<div class="chips">
        ${list
          .map(
            (i) =>
              `<button class="chip ${i.id === instId ? "active" : ""}" data-gd-inst="${esc(i.id)}">${esc(
                i.name,
              )}${i.status && i.status.running ? "" : "（未运行）"}</button>`,
          )
          .join("")}
      </div>
      <div id="gd-body"><div class="skeleton" style="height:160px"></div></div>`;
      target.querySelectorAll("[data-gd-inst]").forEach((chip) => {
        chip.addEventListener("click", () => {
          instId = chip.dataset.gdInst;
          render(target);
        });
      });
      await load();
    }

    return { render };
  }

  return { create };
});
