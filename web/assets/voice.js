/* 牧鱼 · 语音（驰风 Breeze TTS） */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerVoice = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DAILY_MOODS = [
    ["calm", "平静"],
    ["happy", "开心"],
    ["low", "低落"],
    ["annoyed", "烦躁"],
    ["angry", "生气"],
  ];
  const GROUP_MOODS = ["开心", "难过", "生气", "惊讶", "疑惑", "无语", "兴奋"];

  function create(ctx) {
    const { api, esc, icon, toast, confirmDialog, openModal, closeModal, state } = ctx;
    let instId = "";
    let audioUrl = "";

    function instances() {
      return (state && state.instances) || [];
    }

    function url(suffix) {
      return `/api/instances/${encodeURIComponent(instId)}/voice${suffix || ""}`;
    }

    function revoke() {
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
        audioUrl = "";
      }
    }

    function badge(ok, text) {
      return `<span class="badge ${ok ? "ok" : "warn"}">${esc(text)}</span>`;
    }

    function statusCard(data) {
      const plugin = data.plugin || {};
      const provider = data.provider || {};
      const tts = data.tts || {};
      const running = plugin.installed && plugin.enabled && tts.enabled;
      return `<div class="card">
        <div class="section-head" style="margin:0 0 10px"><h2>语音状态</h2>
          <span class="side">${running ? "正在用驰风 Breeze 把回复转成语音" : "尚未开启语音回复"}</span></div>
        <div class="auto-meta" style="gap:8px;flex-wrap:wrap">
          ${badge(plugin.installed, plugin.installed ? `插件已安装 ${esc(plugin.version || "")}` : "插件未安装")}
          ${badge(plugin.enabled, plugin.enabled ? "插件已启用" : "插件未启用")}
          ${badge(provider.exists, provider.exists ? "提供商已配置" : "提供商未配置")}
          ${badge(tts.enabled, tts.enabled ? "语音回复已开启" : "语音回复已关闭")}
        </div>
        ${data.provider_error ? `<p class="hint-text" style="color:var(--bad);margin-top:8px">${esc(data.provider_error)}</p>` : ""}
        <div class="auto-toolbar" style="margin-top:12px">
          <div class="left">
            ${!plugin.installed || !plugin.enabled ? `<button class="btn sm primary" id="v-install">${icon("download")}安装语音插件</button>` : ""}
            ${plugin.installed && plugin.update_available ? `<button class="btn sm ghost" id="v-update">${icon("refresh")}更新插件 ${esc(plugin.builtin_version || "")}</button>` : ""}
            <button class="btn sm primary" id="v-save">${icon("check")}保存并开启</button>
            ${tts.enabled ? `<button class="btn sm ghost" id="v-disable">${icon("stop")}关闭语音回复</button>` : ""}
          </div>
          <div class="right"><span class="side">保存时会把配置写入 AstrBot 提供商与全局 TTS 设置</span></div>
        </div>
      </div>`;
    }

    function presetCard(data) {
      const presets = data.presets || [];
      const waves = [4, 9, 6, 13, 8, 16, 11, 7, 14, 5, 10, 6];
      const tiles = presets.map((preset) => {
        const applied = Boolean(preset.applied);
        const traits = (preset.traits || [])
          .map((tag) => `<span>${esc(tag)}</span>`)
          .join("");
        return `<div class="voice-preset ${applied ? "applied" : ""}">
          <div class="voice-preset-orb">${icon("mic")}</div>
          <div class="voice-preset-main">
            <div class="voice-preset-title">
              <h3>${esc(preset.name)}</h3>
              ${preset.label ? `<span class="badge accent">${esc(preset.label)}</span>` : ""}
              ${applied ? `<span class="badge ok">${icon("check")}当前使用</span>` : ""}
            </div>
            <p>${esc(preset.summary)}</p>
            ${traits ? `<div class="voice-preset-tags">${traits}</div>` : ""}
          </div>
          <div class="voice-preset-side">
            <div class="voice-preset-wave">${waves.map((height) => `<i style="height:${height}px"></i>`).join("")}</div>
            <span class="side">${preset.duration ? `${esc(preset.duration)} 秒参考音频` : "自带参考音频"}</span>
            <div class="voice-preset-actions">
              <button class="btn sm ${applied ? "ghost" : "primary"}" data-preset="${esc(preset.id)}" ${applied ? "disabled" : ""}>
                ${applied ? `${icon("check")}已应用` : `${icon("mic")}应用预设`}
              </button>
              <button class="btn sm ghost" data-preset-edit="${esc(preset.id)}" title="编辑这个人声预设">${icon("edit")}</button>
            </div>
          </div>
        </div>`;
      }).join("");
      return `<div class="card" style="margin-top:14px">
        <div class="section-head" style="margin:0 0 10px"><h2>人声预设</h2>
          <span class="side">自带参考音频，应用后音色会被锁定，不再每句漂移</span></div>
        <div class="auto-toolbar" style="margin-bottom:10px">
          <div class="left"><button class="btn sm primary" id="v-preset-new">${icon("plus")}新增预设</button></div>
          <div class="right"><span class="side">新预设会用当前实例的参考音频，创建后可继续修改</span></div>
        </div>
        ${tiles ? `<div class="voice-preset-grid">${tiles}</div>` : `<p class="hint-text">还没有人声预设；先在下方上传参考音频，再点「新增预设」。</p>`}
        <p class="hint-text" style="margin:10px 0 0">应用预设会复制参考音频到该实例，并写入音色描述与逐字稿；不会改动 API Key、触发概率和语音开关。</p>
      </div>`;
    }

    function moodCard(data) {
      const provider = data.provider || {};
      const mood = data.mood || {};
      const tones = mood.tones || provider.mood_tones || {};
      const sync = provider.mood_sync_enabled !== false;
      const group = provider.mood_group_enabled !== false;
      const current = !mood.available
        ? "读不到心情"
        : mood.mood_enabled
          ? `${mood.label || mood.mood || "平静"}${mood.intensity ? ` · 强度 ${mood.intensity}` : ""}`
          : "每日心情已关闭";
      const toneRow = ([key, label]) => `<label class="hint-text voice-mood-tone">
        <span>${esc(label)}</span>
        <input class="input" data-mood-tone="${esc(key)}" value="${esc(tones[key] || "")}" placeholder="这个情绪下的语气提示">
      </label>`;
      return `<div class="card" style="margin-top:14px">
        <div class="section-head" style="margin:0 0 10px"><h2>情绪联动</h2>
          <span class="side">按每日心情和群聊情绪切换语音语气</span></div>
        <div class="auto-meta" style="gap:8px;flex-wrap:wrap">
          ${badge(Boolean(mood.available && mood.mood_enabled), `当前心情：${current}`)}
          ${badge(group, group ? "群聊情绪优先" : "只读每日心情")}
          ${badge(sync, sync ? "情绪联动已开启" : "情绪联动已关闭")}
        </div>
        <label class="hint-text" style="display:flex;gap:8px;align-items:center;margin-top:10px">
          <input type="checkbox" id="v-mood-sync" ${sync ? "checked" : ""}> 开启情绪联动（同一句话在不同心情下语气不同）
        </label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px">
          <label class="hint-text">管理器地址<input class="input" id="v-mood-url" value="${esc(provider.mood_manager_url || "http://127.0.0.1:7311")}"></label>
          <label class="hint-text">实例 ID<input class="input" id="v-mood-inst" value="${esc(provider.mood_instance_id || "")}" placeholder="留空自动使用当前实例"></label>
          <label class="hint-text">心情缓存（秒）<input class="input" id="v-mood-cache" type="number" min="5" max="300" value="${esc(provider.mood_cache_seconds ?? 20)}"></label>
          <label class="hint-text" style="display:flex;gap:8px;align-items:center">
            <input type="checkbox" id="v-mood-group" ${group ? "checked" : ""}> 优先使用群聊情绪
          </label>
        </div>
        <div class="auto-toolbar" style="margin-top:10px">
          <div class="left"><button class="btn sm ghost" id="v-mood-refresh">${icon("refresh")}刷新当前心情</button></div>
          <div class="right"><span class="side" id="v-mood-current">当前心情：${esc(current)}</span></div>
        </div>
        <div class="voice-mood-grid">${DAILY_MOODS.map(toneRow).join("")}</div>
        <details style="margin-top:8px">
          <summary class="side" style="cursor:pointer">群聊情绪语气（group_chat_plus）</summary>
          <div class="voice-mood-grid">${GROUP_MOODS.map((label) => toneRow([label, label])).join("")}</div>
        </details>
        <p class="hint-text" style="margin:10px 0 0">语音插件每句话会读取当前心情，把对应语气拼在音色描述后面；换心情会生成独立缓存，不会串音。管理器写不到心情时自动退回原音色。</p>
      </div>`;
    }

    function endpointChips(data) {
      const provider = data.provider || {};
      const current = String(provider.api_base || "").replace(/\/+$/, "");
      const endpoints = data.endpoints || [];
      if (!endpoints.length) return "";
      return `<div class="voice-endpoints" id="v-endpoints">${endpoints.map((item) => `
        <button type="button" class="voice-endpoint ${current === item.value ? "active" : ""}" data-endpoint="${esc(item.value)}">
          <strong>${esc(item.label)}</strong>
          <span>${esc(item.hint)}</span>
          <em data-state>待检测</em>
        </button>`).join("")}</div>`;
    }

    function formCard(data) {
      const provider = data.provider || {};
      const tts = data.tts || {};
      const keyPlaceholder = provider.has_key
        ? `已保存（${provider.key_masked || "••••"}），留空不修改`
        : "粘贴 Breeze API Key";
      return `<div class="card" style="margin-top:14px">
        <div class="section-head" style="margin:0 0 10px"><h2>语音参数</h2><span class="side">音色设计留空则使用默认音色</span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div class="hint-text" style="grid-column:1 / -1;display:block">语音服务地址
            ${endpointChips(data)}
            <input class="input" id="v-base" value="${esc(provider.api_base || "https://tts.chifengvtc.com")}">
            <span class="side" style="margin-top:6px;display:block">选择连接方式后，点「保存并开启」才会生效；检测只代表管理器这台机器能否连到端口。</span>
          </div>
          <label class="hint-text">API Key<input class="input" id="v-key" type="password" autocomplete="off" placeholder="${esc(keyPlaceholder)}"></label>
          <label class="hint-text">音色描述（instruction）
            <input class="input" id="v-instruction" placeholder="例如：一位温柔自信的年轻女性，声音清晰，语气亲切。" value="${esc(provider.instruction || "")}"></label>
          <label class="hint-text">cfg_scale<input class="input" id="v-cfg" type="number" min="0" max="30" step="0.5" value="${esc(provider.cfg_scale ?? 4)}"></label>
          <label class="hint-text">seed<input class="input" id="v-seed" type="number" value="${esc(provider.seed ?? 42)}"></label>
          <label class="hint-text">超时（秒）<input class="input" id="v-timeout" type="number" min="30" max="900" value="${esc(provider.timeout ?? 300)}"></label>
          <label class="hint-text">触发概率（0~1）<input class="input" id="v-prob" type="number" min="0" max="1" step="0.1" value="${esc(tts.trigger_probability ?? 1)}"></label>
          <label class="hint-text" style="grid-column:1 / -1;display:flex;gap:8px;align-items:center">
            <input type="checkbox" id="v-cache" ${provider.cache_enabled !== false ? "checked" : ""}> 缓存已合成的语音（推荐）
          </label>
          <label class="hint-text">缓存条数上限<input class="input" id="v-cache-entries" type="number" min="1" max="2000" value="${esc(provider.cache_max_entries ?? 200)}"></label>
          <label class="hint-text">缓存容量上限（MB）<input class="input" id="v-cache-mb" type="number" min="10" max="2000" value="${esc(provider.cache_max_mb ?? 200)}"></label>
          <label class="hint-text" style="grid-column:1 / -1;display:flex;gap:8px;align-items:center">
            <input type="checkbox" id="v-dual" ${tts.dual_output ? "checked" : ""}> 同时保留文字回复（dual_output）
          </label>
        </div>
        <div style="margin-top:12px;padding:12px;border:1px dashed var(--line);border-radius:10px">
          <div class="section-head" style="margin:0 0 8px"><h2 style="font-size:14px">参考音频（声音克隆）</h2>
            <span class="side">可选；上传后按下方逐字稿克隆音色</span></div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input class="input" id="v-ref-path" style="flex:1;min-width:220px" readonly value="${esc(provider.ref_audio || "")}" placeholder="未上传参考音频">
            <button class="btn sm ghost" id="v-ref-upload">${icon("plus")}上传音频</button>
            <button class="btn sm ghost" id="v-ref-clear">${icon("trash")}清除</button>
            <input type="file" id="v-ref-file" accept=".wav,.mp3,.m4a,.flac,.ogg,audio/*" hidden>
          </div>
          <label class="hint-text" style="display:block;margin-top:8px">参考音频逐字稿（ref_text）
            <input class="input" id="v-ref-text" placeholder="参考音频里说的完整文字。" value="${esc(provider.ref_text || "")}"></label>
        </div>
      </div>`;
    }

    function formatBytes(bytes) {
      const value = Number(bytes) || 0;
      if (value < 1024) return `${value} B`;
      if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
      return `${(value / 1024 / 1024).toFixed(1)} MB`;
    }

    function cacheCard(data) {
      const cache = data.cache || {};
      if (!cache.available) {
        return `<div class="card" style="margin-top:14px">
          <div class="section-head" style="margin:0 0 10px"><h2>语音缓存</h2><span class="side">仅本地实例可统计</span></div>
          <p class="hint-text">该实例没有本地目录，管理器读不到缓存文件；缓存仍会在机器人所在机器上自动生效。</p>
        </div>`;
      }
      const total = (Number(cache.hits) || 0) + (Number(cache.misses) || 0);
      const rate = total ? Math.round(((Number(cache.hits) || 0) / total) * 100) : 0;
      return `<div class="card" style="margin-top:14px">
        <div class="section-head" style="margin:0 0 10px"><h2>语音缓存</h2>
          <span class="side">${cache.enabled ? "相同文本第二次回复直接复用音频" : "当前已关闭缓存"}</span></div>
        <div class="voice-cache-stats">
          <div><strong>${cache.entries}</strong><span>条已缓存</span></div>
          <div><strong>${formatBytes(cache.bytes)}</strong><span>占用空间</span></div>
          <div><strong>${cache.hits}</strong><span>次命中</span></div>
          <div><strong>${rate}%</strong><span>命中率</span></div>
        </div>
        <div class="auto-toolbar" style="margin-top:12px">
          <div class="left"><button class="btn sm ghost" id="v-cache-clear" ${cache.entries ? "" : "disabled"}>${icon("trash")}清空缓存</button></div>
          <div class="right"><span class="side">上限 ${cache.max_entries} 条 / ${cache.max_mb} MB，满了自动淘汰最久未用的</span></div>
        </div>
        <p class="hint-text" style="margin:8px 0 0">缓存键包含文本、音色描述、参考音频和 cfg/seed，换音色不会串音。首次生成仍要请求 TTS，之后相同文本只复制本地文件。</p>
      </div>`;
    }

    function previewCard() {
      return `<div class="card" style="margin-top:14px">
        <div class="section-head" style="margin:0 0 10px"><h2>试听</h2><span class="side">直接调用语音服务，不经过 AstrBot</span></div>
        <textarea class="input" id="v-text" rows="2" style="width:100%;resize:vertical">欢迎来到驰风车队，比赛即将开始。</textarea>
        <div class="auto-toolbar" style="margin-top:10px">
          <div class="left"><button class="btn sm primary" id="v-preview">${icon("pulse")}生成试听</button></div>
          <div class="right"><span class="side">长文本可能需要几十秒</span></div>
        </div>
        <audio id="v-audio" controls hidden style="width:100%;margin-top:10px"></audio>
      </div>`;
    }

    async function probeEndpoints(view) {
      const box = view.querySelector("#v-endpoints");
      if (!box) return;
      try {
        const items = await api(url("/endpoints"));
        box.querySelectorAll("[data-endpoint]").forEach((chip) => {
          const value = chip.getAttribute("data-endpoint");
          const item = (items || []).find((entry) => entry.value === value);
          const stateNode = chip.querySelector("[data-state]");
          if (!item || !stateNode) return;
          stateNode.className = item.reachable ? "ok" : "off";
          stateNode.textContent = item.reachable ? `可达 · ${item.ms}ms` : "不可达";
          if (!item.reachable && item.error) chip.title = item.error;
        });
      } catch (_) {
        /* 探测失败不打扰用户 */
      }
    }

    async function load(view) {
      revoke();
      const box = view.querySelector("#v-body");
      if (!box) return;
      if (!instId) {
        box.innerHTML = `<div class="empty" style="padding:26px">${icon("bots")}<h4>还没有机器人</h4><p>先到总览新增一个实例。</p></div>`;
        return;
      }
      box.innerHTML = `<div class="skeleton" style="height:260px"></div>`;
      try {
        const data = await api(url());
        if (!view.isConnected) return;
        box.innerHTML = `${statusCard(data)}${presetCard(data)}${moodCard(data)}${cacheCard(data)}${formCard(data)}${previewCard()}`;
        bind(view, data);
        probeEndpoints(view);
      } catch (err) {
        if (!view.isConnected) return;
        box.innerHTML = `<div class="empty" style="padding:26px">${icon("alert")}<h4>读取语音状态失败</h4><p>${esc(err.message)}</p><p class="hint-text">请确认该机器人的 AstrBot 已启动。</p></div>`;
      }
    }

    function presetPayload(modal) {
      const read = (id) => String(modal.querySelector(id)?.value || "").trim();
      const traits = read("#vp-traits").split(/[，,、\s]+/).filter(Boolean);
      return {
        name: read("#vp-name"),
        label: read("#vp-label"),
        summary: read("#vp-summary"),
        traits,
        instruction: read("#vp-instruction"),
        ref_text: read("#vp-ref-text"),
        cfg_scale: Number(read("#vp-cfg") || 4),
        seed: Number(read("#vp-seed") || 42),
      };
    }

    function openPresetEditor(view, data, preset) {
      const provider = data.provider || {};
      const editing = Boolean(preset);
      const value = (key, fallback) => esc(preset && preset[key] !== undefined ? preset[key] : fallback);
      const traits = preset ? (preset.traits || []).join("，") : "";
      const audioInfo = editing
        ? `${esc(preset.duration ? `${preset.duration} 秒` : "自带")}参考音频，可替换`
        : "创建时会复制当前实例正在使用的参考音频";
      openModal({
        title: editing ? "编辑人声预设" : "新增人声预设",
        sub: editing
          ? "修改后，已经应用这条预设的实例需要再点一次「应用预设」才会用上新参数。"
          : "用当前实例的参考音频创建一条新预设；创建后可以继续编辑。",
        wide: true,
        body: `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <label class="hint-text">名称<input class="input" id="vp-name" placeholder="例如：大肥鱼 · 深海软语" value="${value("name", "")}"></label>
          <label class="hint-text">标签<input class="input" id="vp-label" placeholder="专属 / 自定义" value="${value("label", "自定义")}"></label>
          <label class="hint-text" style="grid-column:1 / -1">简介
            <textarea class="input" id="vp-summary" rows="2" style="width:100%;resize:vertical" placeholder="一句话说明这条声音的气质。">${value("summary", "")}</textarea></label>
          <label class="hint-text" style="grid-column:1 / -1">特征标签（用逗号分隔）
            <input class="input" id="vp-traits" value="${esc(traits)}" placeholder="少女感，慵懒，贴麦"></label>
          <label class="hint-text" style="grid-column:1 / -1">音色描述（instruction）
            <textarea class="input" id="vp-instruction" rows="3" style="width:100%;resize:vertical" placeholder="声音的年龄、性别、语速、情绪等描述。">${value("instruction", provider.instruction || "")}</textarea></label>
          <label class="hint-text" style="grid-column:1 / -1">参考音频逐字稿（ref_text）
            <textarea class="input" id="vp-ref-text" rows="2" style="width:100%;resize:vertical" placeholder="参考音频里说的完整文字，必须逐字一致。">${value("ref_text", provider.ref_text || "")}</textarea></label>
          <label class="hint-text">cfg_scale<input class="input" id="vp-cfg" type="number" min="0" max="30" step="0.5" value="${value("cfg_scale", provider.cfg_scale ?? 4)}"></label>
          <label class="hint-text">seed<input class="input" id="vp-seed" type="number" value="${value("seed", provider.seed ?? 42)}"></label>
        </div>
        <div class="voice-preset-audio">
          <div><span class="side">参考音频：</span><span id="vp-audio-info">${audioInfo}</span></div>
          ${editing ? `<button class="btn sm ghost" id="vp-audio">${icon("plus")}替换音频</button>
            <input type="file" id="vp-file" accept=".wav,.mp3,.m4a,.flac,.ogg,audio/*" hidden>` : ""}
        </div>`,
        footer: `${editing ? `<button class="btn danger" id="vp-delete">${icon("trash")}删除预设</button>` : ""}
          <button class="btn ghost" data-close>取消</button>
          <button class="btn primary" id="vp-save">${icon("check")}${editing ? "保存修改" : "创建预设"}</button>`,
        onMount: (modal) => {
          modal.querySelector("#vp-save").addEventListener("click", async () => {
            const button = modal.querySelector("#vp-save");
            button.disabled = true;
            try {
              const payload = presetPayload(modal);
              if (!payload.name) throw new Error("请填写预设名称");
              if (!payload.ref_text) throw new Error("请填写参考音频逐字稿");
              if (editing) {
                await api(url(`/presets/${encodeURIComponent(preset.id)}`), { method: "PUT", body: payload });
                toast("人声预设已保存");
              } else {
                await api(url("/presets"), { method: "POST", body: payload });
                toast("人声预设已创建");
              }
              closeModal();
              load(view);
            } catch (err) {
              toast(err.message, "err");
              button.disabled = false;
            }
          });

          modal.querySelector("#vp-audio")?.addEventListener("click", () => {
            modal.querySelector("#vp-file")?.click();
          });
          modal.querySelector("#vp-file")?.addEventListener("change", async (event) => {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            try {
              const res = await fetch(
                url(`/presets/${encodeURIComponent(preset.id)}/ref-audio?name=${encodeURIComponent(file.name)}`),
                { method: "POST", body: file },
              );
              const json = await res.json().catch(() => ({}));
              if (!res.ok || json.status === "error") {
                throw new Error(json.message || `上传失败（HTTP ${res.status}）`);
              }
              modal.querySelector("#vp-audio-info").textContent = `已替换为 ${file.name}`;
              toast("预设参考音频已替换");
            } catch (err) {
              toast(err.message, "err");
            } finally {
              event.target.value = "";
            }
          });

          modal.querySelector("#vp-delete")?.addEventListener("click", async () => {
            if (!await confirmDialog("删除预设", `删除「${preset.name}」及自带参考音频？已经应用到实例的配置不会变。`)) return;
            try {
              await api(url(`/presets/${encodeURIComponent(preset.id)}`), { method: "DELETE" });
              closeModal();
              toast("人声预设已删除");
              load(view);
            } catch (err) {
              toast(err.message, "err");
            }
          });
        },
      });
    }

    function payload(view) {
      const tones = {};
      view.querySelectorAll("[data-mood-tone]").forEach((input) => {
        const key = input.getAttribute("data-mood-tone");
        if (key) tones[key] = String(input.value || "").trim();
      });
      const data = {
        api_base: String(view.querySelector("#v-base").value || "").trim(),
        instruction: String(view.querySelector("#v-instruction").value || "").trim(),
        cfg_scale: Number(view.querySelector("#v-cfg").value || 4),
        seed: Number(view.querySelector("#v-seed").value || 42),
        timeout: Number(view.querySelector("#v-timeout").value || 300),
        trigger_probability: Number(view.querySelector("#v-prob").value || 1),
        dual_output: Boolean(view.querySelector("#v-dual").checked),
        cache_enabled: Boolean(view.querySelector("#v-cache").checked),
        cache_max_entries: Number(view.querySelector("#v-cache-entries").value || 200),
        cache_max_mb: Number(view.querySelector("#v-cache-mb").value || 200),
        ref_audio: String(view.querySelector("#v-ref-path").value || "").trim(),
        ref_text: String(view.querySelector("#v-ref-text").value || "").trim(),
        mood_sync_enabled: Boolean(view.querySelector("#v-mood-sync")?.checked),
        mood_group_enabled: Boolean(view.querySelector("#v-mood-group")?.checked),
        mood_manager_url: String(view.querySelector("#v-mood-url")?.value || "").trim(),
        mood_instance_id: String(view.querySelector("#v-mood-inst")?.value || "").trim(),
        mood_cache_seconds: Number(view.querySelector("#v-mood-cache")?.value || 20),
        mood_tones: tones,
      };
      const key = String(view.querySelector("#v-key").value || "").trim();
      if (key) data.api_key = key;
      return data;
    }

    function bindEndpoints(view) {
      const base = view.querySelector("#v-base");
      const chips = Array.from(view.querySelectorAll("[data-endpoint]"));
      if (!base || !chips.length) return;
      const sync = () => {
        const current = String(base.value || "").trim().replace(/\/+$/, "");
        chips.forEach((chip) => {
          chip.classList.toggle("active", chip.getAttribute("data-endpoint") === current);
        });
      };
      chips.forEach((chip) => {
        chip.addEventListener("click", () => {
          base.value = chip.getAttribute("data-endpoint") || "";
          sync();
        });
      });
      base.addEventListener("input", sync);
    }

    function bind(view, data) {
      view.querySelector("#v-install")?.addEventListener("click", async () => {
        const button = view.querySelector("#v-install");
        button.disabled = true;
        button.textContent = "安装中…";
        try {
          await api(url("/install"), { method: "POST", body: {} });
          toast("语音插件已安装");
          load(view);
        } catch (err) {
          toast(err.message, "err");
          button.disabled = false;
          button.innerHTML = `${icon("download")}安装语音插件`;
        }
      });

      view.querySelector("#v-update")?.addEventListener("click", async () => {
        const button = view.querySelector("#v-update");
        button.disabled = true;
        button.textContent = "更新中…";
        try {
          await api(url("/install?force=true"), { method: "POST", body: {} });
          toast("语音插件已更新");
          load(view);
        } catch (err) {
          toast(err.message, "err");
          button.disabled = false;
          button.innerHTML = `${icon("refresh")}更新插件`;
        }
      });

      view.querySelectorAll("[data-preset]").forEach((button) => {
        button.addEventListener("click", async () => {
          const presetId = button.getAttribute("data-preset");
          const original = button.innerHTML;
          button.disabled = true;
          button.textContent = "应用中…";
          try {
            await api(url(`/presets/${encodeURIComponent(presetId)}`), { method: "POST", body: {} });
            toast("人声预设已应用");
            load(view);
          } catch (err) {
            toast(err.message, "err");
            button.disabled = false;
            button.innerHTML = original;
          }
        });
      });

      view.querySelectorAll("[data-preset-edit]").forEach((button) => {
        const preset = (data.presets || []).find(
          (item) => item.id === button.getAttribute("data-preset-edit"),
        );
        if (!preset) return;
        button.addEventListener("click", () => openPresetEditor(view, data, preset));
      });

      view.querySelector("#v-preset-new")?.addEventListener("click", () => {
        const provider = data.provider || {};
        if (!String(provider.ref_audio || "").trim()) {
          toast("当前实例还没有参考音频，请先在下方上传", "err");
          return;
        }
        openPresetEditor(view, data, null);
      });

      bindEndpoints(view);

      view.querySelector("#v-mood-refresh")?.addEventListener("click", async () => {
        const button = view.querySelector("#v-mood-refresh");
        const node = view.querySelector("#v-mood-current");
        button.disabled = true;
        try {
          const mood = await api(url("/mood"));
          const text = !mood.available
            ? "读不到心情"
            : mood.mood_enabled
              ? `${mood.label || mood.mood || "平静"}${mood.intensity ? ` · 强度 ${mood.intensity}` : ""}`
              : "每日心情已关闭";
          if (node) node.textContent = `当前心情：${text}`;
          toast(`当前心情：${text}`);
        } catch (err) {
          toast(err.message, "err");
        } finally {
          button.disabled = false;
        }
      });

      view.querySelector("#v-save")?.addEventListener("click", async () => {
        const button = view.querySelector("#v-save");
        button.disabled = true;
        try {
          await api(url(), { method: "PUT", body: payload(view) });
          toast("语音回复已开启");
          load(view);
        } catch (err) {
          toast(err.message, "err");
          button.disabled = false;
        }
      });

      view.querySelector("#v-disable")?.addEventListener("click", async () => {
        if (!await confirmDialog("关闭语音回复", "关闭后机器人只返回文字，配置会保留。")) return;
        try {
          await api(url("/disable"), { method: "POST", body: {} });
          toast("语音回复已关闭");
          load(view);
        } catch (err) { toast(err.message, "err"); }
      });

      view.querySelector("#v-cache-clear")?.addEventListener("click", async () => {
        if (!await confirmDialog("清空语音缓存", "清空后相同文本需要重新请求 TTS，第一次回复会变慢。")) return;
        try {
          await api(url("/cache"), { method: "DELETE" });
          toast("语音缓存已清空");
          load(view);
        } catch (err) {
          toast(err.message, "err");
        }
      });

      view.querySelector("#v-preview")?.addEventListener("click", async () => {
        const text = String(view.querySelector("#v-text").value || "").trim();
        if (!text) return toast("请先输入试听文字", "err");
        const button = view.querySelector("#v-preview");
        button.disabled = true;
        button.textContent = "生成中…";
        try {
          const body = payload(view);
          body.text = text;
          const res = await fetch(url("/preview"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          if (!res.ok) {
            let message = `试听失败（HTTP ${res.status}）`;
            try {
              const json = await res.json();
              message = json.message || json.detail || message;
            } catch (_) { /* ignore */ }
            throw new Error(message);
          }
          const blob = await res.blob();
          revoke();
          audioUrl = URL.createObjectURL(blob);
          const player = view.querySelector("#v-audio");
          player.src = audioUrl;
          player.hidden = false;
          player.play().catch(() => { /* 浏览器可能阻止自动播放 */ });
          toast("试听已生成");
        } catch (err) {
          toast(err.message, "err");
        } finally {
          button.disabled = false;
          button.innerHTML = `${icon("pulse")}生成试听`;
        }
      });

      view.querySelector("#v-ref-upload")?.addEventListener("click", () => {
        view.querySelector("#v-ref-file")?.click();
      });
      view.querySelector("#v-ref-file")?.addEventListener("change", async (event) => {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        try {
          const res = await fetch(
            `/api/instances/${encodeURIComponent(instId)}/voice/ref-audio?name=${encodeURIComponent(file.name)}`,
            { method: "POST", body: file },
          );
          const json = await res.json().catch(() => ({}));
          if (!res.ok || json.status === "error") {
            throw new Error(json.message || `上传失败（HTTP ${res.status}）`);
          }
          view.querySelector("#v-ref-path").value = json.data.path;
          toast("参考音频已保存");
        } catch (err) {
          toast(err.message, "err");
        } finally {
          event.target.value = "";
        }
      });
      view.querySelector("#v-ref-clear")?.addEventListener("click", async () => {
        if (!await confirmDialog("清除参考音频", "清除后语音会使用默认音色或音色描述。")) return;
        try {
          await api(url("/ref-audio"), { method: "DELETE" });
          view.querySelector("#v-ref-path").value = "";
          toast("参考音频已清除");
        } catch (err) { toast(err.message, "err"); }
      });
    }

    function render(view) {
      revoke();
      view.innerHTML = `
        <div class="auto-toolbar">
          <div class="left" style="display:flex;gap:8px;align-items:center">
            <select class="input" id="v-inst" style="min-width:180px">${instances().map((item) => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")}</select>
            <button class="btn sm ghost" id="v-refresh">${icon("refresh")}刷新</button>
          </div>
          <div class="right"><span class="side">回复文字会自动转成 wav 语音</span></div>
        </div>
        <div id="v-body"><div class="skeleton" style="height:260px"></div></div>
        <p class="hint-text">语音使用驰风 Breeze TTS（multipart + X-API-Key）。插件只负责注册提供商，开关与参数由本页写入 AstrBot。</p>`;
      const select = view.querySelector("#v-inst");
      if (select) {
        const focused = (globalThis.ManagerFocus && globalThis.ManagerFocus.consume(instances()))
          || (globalThis.ManagerFocus && globalThis.ManagerFocus.pick(instances()));
        instId = (focused && focused.id) || select.value || (instances()[0] && instances()[0].id) || "";
        select.value = instId;
        select.addEventListener("change", () => {
          instId = select.value;
          load(view);
        });
      }
      view.querySelector("#v-refresh")?.addEventListener("click", () => load(view));
      load(view);
    }

    function leave() {
      revoke();
    }

    return { render, leave };
  }

  return { create };
});
