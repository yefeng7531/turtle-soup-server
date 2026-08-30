/* 海龟汤 AI 工坊 — 前端逻辑 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
let TOKEN = localStorage.getItem("tt_token") || "";
let SETTINGS = null;          // /api/settings 返回的脱敏配置
let CURRENT_SOUP = null;      // 主持模式当前谜题
let HOST_SESSION = null;

/* ---------------- 基础：请求 / 提示 ---------------- */

async function api(path, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json", "X-Auth-Token": TOKEN }, opts.headers || {});
  const resp = await fetch(path, Object.assign({}, opts, { headers }));
  if (resp.status === 401) { showLock(); throw new Error("需要登录"); }
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  return resp.json();
}

let toastTimer = null;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), isErr ? 6000 : 2600);
}

async function sseFetch(url, body, onEvent) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": TOKEN },
    body: JSON.stringify(body),
  });
  if (resp.status === 401) { showLock(); throw new Error("需要登录"); }
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const raw = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 2);
      if (raw.startsWith("data:")) {
        try { onEvent(JSON.parse(raw.slice(5))); } catch (e) { /* 忽略坏帧 */ }
      }
    }
  }
}

/* ---------------- 锁屏 ---------------- */

function showLock() {
  $("#lock").classList.remove("hidden");
  localStorage.removeItem("tt_token");
  TOKEN = "";
}

async function tryUnlock() {
  const pwd = $("#lockPassword").value;
  if (!pwd) return;
  try {
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pwd }) });
    if (!r.ok) throw new Error();
    const data = await r.json();
    TOKEN = data.token;
    localStorage.setItem("tt_token", TOKEN);
    $("#lock").classList.add("hidden");
    $("#lockError").classList.add("hidden");
    boot();
  } catch (e) {
    $("#lockError").classList.remove("hidden");
  }
}
$("#lockBtn").onclick = tryUnlock;
$("#lockPassword").addEventListener("keydown", (e) => { if (e.key === "Enter") tryUnlock(); });

/* ---------------- 视图切换 ---------------- */

function switchView(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  $$(".view").forEach((v) => v.classList.add("hidden"));
  $("#view-" + name).classList.remove("hidden");
  if (name === "history") loadHistory();
  if (name === "host") refreshHostSoupSelect();
  if (name === "settings") loadSettings();
}
$$(".tab").forEach((t) => t.onclick = () => switchView(t.dataset.view));

/* ---------------- 设置页 ---------------- */

async function loadSettings() {
  SETTINGS = await api("/api/settings");
  const c = SETTINGS.chat, i = SETTINGS.image;

  const chatSel = $("#chatProvider");
  chatSel.innerHTML = Object.entries(SETTINGS.chat_presets)
    .map(([k, v]) => `<option value="${k}">${v.name}</option>`).join("");
  chatSel.value = c.provider;

  const imgSel = $("#imageProvider");
  imgSel.innerHTML = Object.entries(SETTINGS.image_presets)
    .map(([k, v]) => `<option value="${k}">${v.name}</option>`).join("");
  imgSel.value = i.provider;

  applyChatPreset(c, false);
  applyImagePreset(i, false);
  $("#chatTemp").value = c.temperature ?? 0.8;
  $("#tempVal").textContent = $("#chatTemp").value;
  $("#hostEnabled").checked = SETTINGS.host_enabled;
  $("#chatKeyState").textContent = c.has_key ? `(已保存，尾号 ${c.key_tail})` : "(未设置)";
  $("#imageKeyState").textContent = i.has_key ? `(已保存，尾号 ${i.key_tail})` : "(未设置)";
  $("#noPasswordBanner").classList.toggle("hidden", SETTINGS.access_password_set);
}

function applyChatPreset(c, fromUser = true) {
  const key = fromUser ? $("#chatProvider").value : (c.provider || "deepseek");
  const p = SETTINGS.chat_presets[key] || {};
  if (fromUser || !$("#chatBaseUrl").value) $("#chatBaseUrl").value = p.base_url || "";
  if (!fromUser) $("#chatBaseUrl").value = c.base_url || p.base_url || "";
  if (!fromUser) $("#chatApiKey").value = "";
  if (!fromUser) $("#chatModel").value = c.model || "";
  $("#chatModelList").innerHTML = (p.models || []).map((m) => `<option value="${m}">`).join("");
  $("#chatPresetHint").innerHTML = p.key_url
    ? `还没有 Key？<a href="${p.key_url}" target="_blank">去 ${p.name} 官网获取 →</a>（模型名建议：${(p.models || []).join(" / ") || "查看平台模型列表"}）`
    : (key === "ollama" ? "本地模型无需 Key，确保 Ollama 已启动即可。"
      : key === "custom" ? "填写任意 OpenAI 兼容平台的 /v1 接口地址与模型名。" : "");
  if (fromUser) $("#chatModel").value = (p.models || [])[0] || "";
  if (fromUser) $("#chatModelChips").innerHTML = "";
}

function applyImagePreset(i, fromUser = true) {
  const key = fromUser ? $("#imageProvider").value : (i.provider || "none");
  const p = SETTINGS.image_presets[key] || {};
  $("#imageConfig").classList.toggle("hidden", key === "none");
  if (fromUser || !$("#imageBaseUrl").value) $("#imageBaseUrl").value = p.base_url || "";
  if (!fromUser) $("#imageBaseUrl").value = i.base_url || p.base_url || "";
  if (!fromUser) $("#imageApiKey").value = "";
  if (!fromUser) $("#imageModel").value = i.model || "";
  if (!fromUser) $("#imageSize").value = i.size || "1024x1024";
  $("#imageModelList").innerHTML = (p.models || []).map((m) => `<option value="${m}">`).join("");
  $("#imagePresetHint").innerHTML = p.key_url
    ? `还没有 Key？<a href="${p.key_url}" target="_blank">去火山引擎/对应平台获取 →</a>（模型名：${(p.models || []).join(" / ")}）`
    : (key === "pollinations" ? "无需注册无需 Key，直接可用。" : key === "custom" ? "填写 OpenAI 兼容的 /v1 生图接口。" : "");
  if (fromUser) $("#imageModel").value = (p.models || [])[0] || "";
  if (fromUser) $("#imageModelChips").innerHTML = "";
}

$("#chatProvider").onchange = () => applyChatPreset(null, true);
$("#imageProvider").onchange = () => applyImagePreset(null, true);
$("#chatTemp").oninput = () => $("#tempVal").textContent = $("#chatTemp").value;

async function saveSettings() {
  const body = {
    chat: { provider: $("#chatProvider").value, base_url: $("#chatBaseUrl").value.trim(),
            api_key: $("#chatApiKey").value.trim(), model: $("#chatModel").value.trim(),
            temperature: parseFloat($("#chatTemp").value) },
    image: { provider: $("#imageProvider").value, base_url: $("#imageBaseUrl").value.trim(),
             api_key: $("#imageApiKey").value.trim(), model: $("#imageModel").value.trim(),
             size: $("#imageSize").value.trim() || "1024x1024" },
    host_enabled: $("#hostEnabled").checked,
  };
  const np = $("#newPassword").value;
  if (np) body.new_password = np;
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
    $("#newPassword").value = "";
    toast("设置已保存 ✔");
    await loadSettings();
    $("#noPasswordBanner").classList.toggle("hidden", SETTINGS.access_password_set);
  } catch (e) { toast("保存失败：" + e.message, true); }
}
$("#saveSettingsBtn").onclick = saveSettings;

async function testChat() {
  const el = $("#testChatResult");
  el.className = "test-result"; el.textContent = "测试中…";
  await saveSettings();
  try {
    const r = await api("/api/test/chat", { method: "POST" });
    el.className = "test-result " + (r.ok ? "ok" : "fail");
    el.textContent = r.message;
  } catch (e) { el.className = "test-result fail"; el.textContent = e.message; }
}
async function testImage() {
  const el = $("#testImageResult");
  el.className = "test-result"; el.textContent = "测试中（实际生成一张小图，可能需要十几秒）…";
  await saveSettings();
  try {
    const r = await api("/api/test/image", { method: "POST" });
    el.className = "test-result " + (r.ok ? "ok" : "fail");
    el.textContent = r.message;
  } catch (e) { el.className = "test-result fail"; el.textContent = e.message; }
}
$("#testChatBtn").onclick = testChat;
$("#testImageBtn").onclick = testImage;
$("#clearPasswordBtn").onclick = async () => {
  if (!confirm("确定清除访问口令？本地使用没问题，公网部署时请勿清除。")) return;
  await api("/api/settings", { method: "POST", body: JSON.stringify({ clear_password: true }) });
  toast("口令已清除"); await loadSettings();
};

/* ---- 获取模型列表：填完 URL/Key 一键拉取，点选即可，杜绝模型名填错/漏填 ---- */

function bindModelFetcher({ btn, input, list, chips, section }) {
  btn.onclick = async () => {
    const orig = btn.textContent;
    btn.disabled = true; btn.textContent = "获取中…";
    try {
      const baseUrl = (section === "chat" ? $("#chatBaseUrl") : $("#imageBaseUrl")).value.trim();
      const apiKey = (section === "chat" ? $("#chatApiKey") : $("#imageApiKey")).value.trim();
      const r = await api("/api/models", { method: "POST",
        body: JSON.stringify({ section, base_url: baseUrl, api_key: apiKey }) });
      if (!r.ok) return toast(r.message, true);
      input.innerHTML = "";  // 清掉旧的 datalist
      list.innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
      chips.innerHTML = r.models.map((m) => `<button type="button" class="chip" data-m="${esc(m)}">${esc(m)}</button>`).join("");
      chips.querySelectorAll(".chip").forEach((ch) =>
        ch.onclick = () => { input.value = ch.dataset.m; });
      if (!input.value && r.models.length > 0 && r.models.length <= 5) input.value = r.models[0];
      toast(`已获取 ${r.models.length} 个模型，点击名称即可选用`);
    } catch (e) {
      toast("获取失败：" + e.message, true);
    } finally {
      btn.disabled = false; btn.textContent = orig;
    }
  };
}
bindModelFetcher({ btn: $("#fetchModelsBtn"), input: $("#chatModel"), list: $("#chatModelList"), chips: $("#chatModelChips"), section: "chat" });
bindModelFetcher({ btn: $("#fetchImageModelsBtn"), input: $("#imageModel"), list: $("#imageModelList"), chips: $("#imageModelChips"), section: "image" });

/* ---------------- 生成页 ---------------- */

function segVal(id) { return $("#" + id + " button.active")?.dataset.v; }
$$("#genre button, #taste button, #difficulty button").forEach((b) =>
  b.onclick = () => { b.parentElement.querySelectorAll("button").forEach((x) => x.classList.remove("active")); b.classList.add("active"); });
$("#theme").onchange = () => $("#themeCustom").classList.toggle("hidden", $("#theme").value !== "自定义");

const STAGE_NAMES = { base: "① 构思汤底", surface: "② 反推汤面与配套", judge: "③ AI 质检", revise: "③ 质检回炉修订", image: "④ 生成插图" };
let genBusy = false;

async function generate() {
  if (genBusy) return;
  const theme = $("#theme").value === "自定义" ? ($("#themeCustom").value.trim() || "自定义") : $("#theme").value;
  const reqs = {
    theme, genre: segVal("genre"), taste: segVal("taste"), difficulty: segVal("difficulty"),
    count: Math.max(1, Math.min(5, parseInt($("#count").value) || 1)),
    use: $("#use").value, custom: $("#custom").value.trim(), with_image: $("#withImage").checked,
  };
  genBusy = true;
  $("#generateBtn").disabled = true;
  $("#generateBtn").textContent = "🫕 熬汤中…";
  $("#progressPanel").classList.remove("hidden");
  $("#results").innerHTML = "";
  $("#stageList").innerHTML = "";
  $("#logList").innerHTML = "";

  try {
    await sseFetch("/api/generate", reqs, (ev) => {
      if (ev.type === "progress" || ev.type === "stage") {
        const name = ev.type === "progress" ? `— 第 ${ev.index + 1}/${ev.total} 篇 —` : (STAGE_NAMES[ev.stage] || ev.stage);
        let item = document.getElementById("stage-" + (ev.type === "progress" ? "p" + ev.index : ev.stage + ev.index));
        if (!item) {
          item = document.createElement("div");
          item.className = "stage-item"; item.id = "stage-" + (ev.type === "progress" ? "p" + ev.index : ev.stage + ev.index);
          item.innerHTML = `<span class="dot"></span><span>${name}</span>`;
          $("#stageList").appendChild(item);
        }
        $$("#stageList .stage-item").forEach((x) => x.classList.remove("running"));
        item.classList.add("running");
      } else if (ev.type === "log") {
        const d = document.createElement("div");
        d.textContent = "· " + ev.message;
        if (ev.level === "warn") d.className = "warn";
        $("#logList").appendChild(d);
        $("#logList").scrollTop = 1e9;
      } else if (ev.type === "soup") {
        $$("#stageList .stage-item").forEach((x) => { x.classList.remove("running"); x.classList.add("done"); });
        $("#results").prepend(renderSoupCard(ev.data, ev.id, ev.image));
      } else if (ev.type === "done") {
        addLog("✔ " + ev.message, "");
      } else if (ev.type === "error") {
        addLog("✖ " + ev.message, "err");
        toast(ev.message, true);
      }
    });
  } catch (e) {
    addLog("✖ " + e.message, "err");
    toast(e.message, true);
  } finally {
    genBusy = false;
    $("#generateBtn").disabled = false;
    $("#generateBtn").textContent = "🐢 开始出汤";
  }
}
function addLog(text, cls) {
  const d = document.createElement("div");
  d.textContent = "· " + text;
  if (cls) d.className = cls;
  $("#logList").appendChild(d);
  $("#logList").scrollTop = 1e9;
}
$("#generateBtn").onclick = generate;

/* ---------------- 汤品卡片渲染 ---------------- */

function renderSoupCard(d, id, imagePath) {
  const el = document.createElement("div");
  el.className = "soup-card";
  const m = d.meta || {};
  const judgeBadge = m.judge_pass
    ? `<span class="badge judge-pass">质检通过${m.judge_rounds ? `（回炉${m.judge_rounds}轮）` : ""}</span>`
    : `<span class="badge judge-fixed">质检未完全通过</span>`;
  const badges = Object.entries(d.badges || {}).map(([k, v]) => `<span class="badge">${k}·${v}</span>`).join("");
  const qaRows = (d.qa || []).map((q) => `<tr><td>${esc(q.q)}</td><td>${esc(q.a)}</td></tr>`).join("");
  const hintLabels = ["提示 1（方向）", "提示 2（缩小范围）", "提示 3（临门一脚）"];
  el.innerHTML = `
    <div class="soup-head">
      <div>
        <div class="soup-title">🐢 ${esc(d.title)}</div>
        <div class="badges">${badges}${judgeBadge}</div>
      </div>
    </div>
    <div class="soup-body ${imagePath ? "with-img" : ""}">
      <div>
        <div class="surface-text">${esc(d.surface)}</div>
        <div class="sec-title">🔑 关键线索点</div>
        <ol class="clue-list">${(d.clues || []).map((c) => `<li>${esc(c)}</li>`).join("")}</ol>
        <details class="sec"><summary>🍲 汤底（通关后公布）</summary><div class="sec-inner">${esc(d.base).replace(/\n/g, "<br>")}</div></details>
        <details class="sec"><summary>💡 递进提示（卡住时逐级给）</summary><div class="sec-inner"><ul class="hint-list">${(d.hints || []).map((h, i) => `<li><b>${hintLabels[i] || "提示" + (i + 1)}：</b>${esc(h)}</li>`).join("")}</ul></div></details>
        <details class="sec"><summary>❓ 预判问答表（${(d.qa || []).length} 条速查）</summary><div class="sec-inner"><table class="qa-table"><tr><th>玩家可能的问题</th><th>回答</th></tr>${qaRows}</table></div></details>
        ${d.tips ? `<details class="sec"><summary>🎙️ 主持贴士</summary><div class="sec-inner" style="line-height:1.9;font-size:14px;">${esc(d.tips).split("；").map((t) => "· " + esc(t)).join("<br>")}</div></details>` : ""}
        ${(d.hook_titles || []).length ? `<div class="sec-title">✂️ 备选标题（发布用）</div><ul class="clue-list">${d.hook_titles.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
        ${(m.judge_warnings || []).length ? `<div class="warn-list">⚠ ${m.judge_warnings.map(esc).join("<br>⚠ ")}</div>` : ""}
      </div>
      ${imagePath ? `<div class="soup-img"><img src="/output/${imagePath.split(/[\\\\/]/).pop()}" alt="汤面插图" loading="lazy"></div>` : ""}
    </div>
    <div class="soup-actions">
      <button class="btn" data-act="copy">📋 复制全文</button>
      <button class="btn" data-act="export">⬇ 导出 .md</button>
      ${id ? `<button class="btn" data-act="host">🎙️ 用这篇开局</button>` : ""}
      <button class="btn ghost" data-act="regen">🔄 换配方重出</button>
    </div>`;
  el.querySelector('[data-act="copy"]').onclick = () => {
    navigator.clipboard.writeText(soupToMarkdown(d)).then(() => toast("已复制完整主持包 ✔"));
  };
  if (el.querySelector('[data-act="export"]'))
    el.querySelector('[data-act="export"]').onclick = () => id ? location.href = `/api/soups/${id}/export` : toast("导出前请先保存到历史", true);
  const hostBtn = el.querySelector('[data-act="host"]');
  if (hostBtn) hostBtn.onclick = () => startHostWithSoup(id);
  el.querySelector('[data-act="regen"]').onclick = () => {
    switchView("generate");
    toast("已切到出汤页，可调整配方重新生成");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  return el;
}

function esc(s) { return (s ?? "").toString().replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

function soupToMarkdown(d) {
  const L = [];
  L.push(`# 🐢 海龟汤：《${d.title}》`, "");
  L.push(`## 🥣 汤面`, "", d.surface, "");
  L.push(`## 🍲 汤底`, "", d.base, "");
  L.push(`## 🔑 关键线索点`, "", ...(d.clues || []).map((c, i) => `${i + 1}. ${c}`), "");
  if ((d.hints || []).length) L.push(`## 💡 递进提示`, "", ...(d.hints || []).map((h, i) => `- 提示${i + 1}：${h}`), "");
  if ((d.qa || []).length) {
    L.push(`## ❓ 预判问答`, "", "| 玩家可能的问题 | 回答 |", "| --- | --- |");
    d.qa.forEach((q) => L.push(`| ${q.q} | ${q.a} |`));
    L.push("");
  }
  if (d.tips) L.push(`## 🎙️ 主持贴士`, "", ...d.tips.split("；").map((t) => "- " + t), "");
  return L.join("\n");
}

/* ---------------- 历史汤库 ---------------- */

async function loadHistory() {
  const list = await api("/api/soups");
  const box = $("#historyList");
  $("#historyEmpty").classList.toggle("hidden", list.length > 0);
  box.innerHTML = "";
  list.forEach((s) => {
    const d = s.data, b = d.badges || {};
    const item = document.createElement("div");
    item.className = "history-item";
    item.innerHTML = `
      <div class="hi-title">🐢 ${esc(d.title)}${s.has_image ? " 🖼" : ""}</div>
      <div class="badges">${Object.values(b).map((v) => `<span class="badge">${esc(v)}</span>`).join("")}</div>
      <div class="hi-preview">${esc(s.preview)}…</div>
      <div class="hi-meta">${esc(s.created_at)}</div>
      <div class="hi-actions">
        <button class="btn" data-act="view">查看</button>
        <button class="btn" data-act="host">开局</button>
        <button class="btn ghost" data-act="export">导出</button>
        <button class="btn ghost" data-act="del">删除</button>
      </div>`;
    item.querySelector('[data-act="view"]').onclick = async () => {
      const full = await api("/api/soups/" + s.id);
      $("#modalContent").innerHTML = "";
      $("#modalContent").appendChild(renderSoupCard(full.data, full.id, full.image_path));
      $("#modal").classList.remove("hidden");
    };
    item.querySelector('[data-act="host"]').onclick = () => startHostWithSoup(s.id);
    item.querySelector('[data-act="export"]').onclick = () => location.href = `/api/soups/${s.id}/export`;
    item.querySelector('[data-act="del"]').onclick = async () => {
      if (!confirm(`删除《${d.title}》？不可恢复。`)) return;
      await api("/api/soups/" + s.id, { method: "DELETE" });
      loadHistory();
    };
    box.appendChild(item);
  });
}
$("#refreshHistory").onclick = loadHistory;

/* ---------------- AI 主持 ---------------- */

async function refreshHostSoupSelect() {
  const list = await api("/api/soups");
  const sel = $("#hostSoupSelect");
  sel.innerHTML = `<option value="">— 选择 —</option>` +
    list.map((s) => `<option value="${s.id}">${esc(s.data.title)}（${s.created_at}）</option>`).join("");
}

async function startHostWithSoup(id) {
  switchView("host");
  $("#hostSoupSelect").value = id;
  await startHost({ soup_id: id });
}

async function startHost(body) {
  try {
    const r = await api("/api/host/start", { method: "POST", body: JSON.stringify(body) });
    HOST_SESSION = { id: r.session_id, soup_id: body.soup_id || null, pack: body.surface ? body : null };
    $("#hostSetup").classList.add("hidden");
    $("#hostPlay").classList.remove("hidden");
    $("#hostTitle").textContent = "🎙️ 游戏中";
    $("#hostSurfaceBox").textContent = r.surface || "（汤面见聊天记录）";
    $("#hostChat").innerHTML = "";
    addMsg("host", r.greeting);
    $("#hostInput").focus();
  } catch (e) { toast(e.message, true); }
}

$("#hostStartBtn").onclick = () => {
  const soupId = $("#hostSoupSelect").value;
  if (soupId) return startHost({ soup_id: parseInt(soupId) });
  const surface = $("#hostSurface").value.trim(), base = $("#hostBase").value.trim();
  if (!surface || !base) return toast("请选择历史汤品，或同时填写汤面与汤底", true);
  startHost({
    surface, base,
    clues: $("#hostClues").value.split("\n").map((x) => x.trim()).filter(Boolean),
    hints: $("#hostHints").value.split("\n").map((x) => x.trim()).filter(Boolean),
    title: "自定汤",
  });
};

function addMsg(role, text) {
  const d = document.createElement("div");
  d.className = "msg " + role;
  d.textContent = text;
  $("#hostChat").appendChild(d);
  $("#hostChat").scrollTop = 1e9;
  return d;
}

async function hostSend(presetText) {
  const input = $("#hostInput");
  const text = (presetText || input.value).trim();
  if (!text || !HOST_SESSION) return;
  input.value = "";
  addMsg("player", text);
  const replyEl = addMsg("host", "…");
  let acc = "";
  try {
    await sseFetch(`/api/host/${HOST_SESSION.id}/chat`,
      { message: text, soup_id: HOST_SESSION.soup_id, pack: HOST_SESSION.pack },
      (ev) => {
        if (ev.type === "chunk") { acc += ev.text; replyEl.textContent = acc; $("#hostChat").scrollTop = 1e9; }
        else if (ev.type === "error") { replyEl.textContent = acc || ("出错：" + ev.message); toast(ev.message, true); }
      });
    if (/通关|公布/.test(acc)) replyEl.classList.add("win");
    if (!acc) replyEl.textContent = "（主持人沉默了…请重试）";
  } catch (e) { replyEl.textContent = "出错：" + e.message; }
}
$("#hostSendBtn").onclick = () => hostSend();
$("#hostInput").addEventListener("keydown", (e) => { if (e.key === "Enter") hostSend(); });
$("#hostGiveupBtn").onclick = () => hostSend("我放弃了，公布答案");
$("#hostExitBtn").onclick = () => {
  HOST_SESSION = null;
  $("#hostPlay").classList.add("hidden");
  $("#hostSetup").classList.remove("hidden");
};

/* ---------------- 启动 ---------------- */

async function boot() {
  try {
    await api("/api/state");
    await loadSettings();      // 未设口令时会在 loadSettings 里显示提醒横幅
    await refreshHostSoupSelect();
  } catch (e) { /* 401 已由 showLock 处理 */ }
}
boot();
