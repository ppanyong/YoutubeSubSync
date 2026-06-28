"""配置设置页的静态 HTML（原生 HTML + JS）。"""

SETTINGS_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>YouTube 实时中文字幕 · 翻译设置</title>
<style>
  :root {
    --bg: #0f172a; --card: #1e293b; --line: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #6366f1; --accent2: #22c55e;
    --danger: #ef4444;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    display: flex; flex-direction: column; align-items: center;
    justify-content: flex-start; padding: 40px 16px 60px;
  }
  .wrap { width: 100%; max-width: 560px; }
  .nav {
    width: 100%; max-width: 560px; margin-bottom: 16px;
    display: flex; gap: 10px; font-size: 13px;
  }
  .nav a {
    color: #a5b4fc; text-decoration: none; padding: 6px 12px;
    border: 1px solid var(--line); border-radius: 8px;
  }
  .nav a:hover { border-color: var(--accent); }
  .card {
    width: 100%; max-width: 560px; background: var(--card);
    border: 1px solid var(--line); border-radius: 16px; padding: 28px 26px;
    box-shadow: 0 20px 50px rgba(0,0,0,.35);
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; margin: 0 0 22px; }
  .group { margin-bottom: 18px; }
  .group-title {
    font-size: 13px; color: var(--muted); text-transform: uppercase;
    letter-spacing: .04em; margin: 18px 0 10px; border-top: 1px solid var(--line);
    padding-top: 16px;
  }
  label { display: block; font-size: 13px; margin: 12px 0 6px; }
  input, select {
    width: 100%; background: #0f172a; border: 1px solid var(--line);
    color: var(--text); border-radius: 9px; padding: 10px 12px; font-size: 14px;
    outline: none; transition: border-color .15s;
  }
  input:focus, select:focus { border-color: var(--accent); }
  .hint { font-size: 12px; color: var(--muted); margin-top: 5px; }
  .row { display: flex; flex-direction: column; gap: 10px; margin-top: 22px; }
  button {
    flex: 1; border: none; border-radius: 10px; padding: 12px; font-size: 14px;
    font-weight: 600; cursor: pointer; transition: opacity .15s, transform .05s;
  }
  button:active { transform: translateY(1px); }
  .btn-save { background: var(--accent); color: #fff; }
  .btn-test { background: transparent; color: var(--text); border: 1px solid var(--line); }
  button:disabled { opacity: .55; cursor: default; }
  .msg { margin-top: 16px; font-size: 13px; border-radius: 9px; padding: 11px 13px;
    display: none; white-space: pre-wrap; word-break: break-word; }
  .msg.ok { background: rgba(34,197,94,.12); color: #4ade80; border: 1px solid rgba(34,197,94,.4); display: block; }
  .msg.err { background: rgba(239,68,68,.12); color: #f87171; border: 1px solid rgba(239,68,68,.4); display: block; }
  .msg.info { background: rgba(99,102,241,.12); color: #a5b4fc; border: 1px solid rgba(99,102,241,.4); display: block; }
  .stat { color: var(--muted); font-size: 13px; margin: 0 0 14px; }
  .stat b { color: var(--text); }
  .vlist { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow: auto; }
  .vitem {
    display: flex; align-items: center; gap: 10px; background: #0f172a;
    border: 1px solid var(--line); border-radius: 9px; padding: 9px 11px; font-size: 13px;
  }
  .vitem .vid { font-family: ui-monospace, monospace; color: #a5b4fc; }
  .vitem .meta { color: var(--muted); margin-left: auto; white-space: nowrap; }
  .vitem a { color: #93c5fd; text-decoration: none; }
  .mini {
    border: 1px solid var(--line); background: transparent; color: var(--text);
    border-radius: 7px; padding: 5px 9px; font-size: 12px; font-weight: 600; cursor: pointer;
  }
  .mini.danger { color: #f87171; border-color: rgba(239,68,68,.4); }
  .empty { color: var(--muted); font-size: 13px; padding: 12px 0; }
  .entries {
    margin-top: 12px; max-height: 320px; overflow: auto; font-size: 13px;
    border: 1px solid var(--line); border-radius: 9px;
  }
  .entry { padding: 9px 11px; border-bottom: 1px solid var(--line); }
  .entry:last-child { border-bottom: none; }
  .entry .en { color: var(--muted); }
  .entry .zh { color: var(--text); margin-top: 3px; }
  .subtitle-box {
    margin-top: 12px; padding: 12px 14px; background: #0f172a;
    border: 1px solid var(--line); border-radius: 9px; max-height: 360px; overflow: auto;
    font-size: 13px; line-height: 1.65; white-space: pre-wrap; word-break: break-word;
  }
  .subtitle-meta { color: var(--muted); font-size: 12px; margin: 8px 0 10px; }
  .subtitle-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 0; }
  .btn-accent { background: var(--accent2); color: #0f172a; }
  .badge {
    display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 999px;
    font-weight: 600; margin-left: 6px;
  }
  .badge.ready { background: rgba(34,197,94,.15); color: #4ade80; }
  .badge.generating { background: rgba(99,102,241,.15); color: #a5b4fc; }
  .badge.failed { background: rgba(239,68,68,.15); color: #f87171; }
  .badge.none { background: rgba(148,163,184,.12); color: var(--muted); }
</style>
</head>
<body>
  <nav class="nav">
    <a href="#settings">翻译设置</a>
    <a href="#cache">翻译缓存</a>
    <a href="#summaries">内容小结</a>
  </nav>

  <div class="wrap">
  <div class="card" id="settings">
    <h1>翻译引擎设置</h1>
    <p class="sub">在此填写模型访问地址与 Key，保存后立即生效，无需重启后端。</p>

    <label for="target_lang">翻译目标语言</label>
    <select id="target_lang">
      <option value="zh">简体中文</option>
      <option value="zh-Hant">繁体中文</option>
      <option value="ja">日语</option>
      <option value="ko">韩语</option>
      <option value="fr">法语</option>
      <option value="de">德语</option>
      <option value="es">西班牙语</option>
      <option value="ru">俄语</option>
      <option value="pt">葡萄牙语</option>
    </select>
    <div class="hint">字幕将翻译成所选语言，保存后立即生效。</div>

    <div class="group-title">LLM 配置</div>
    <label for="llm_base">LLM Base URL</label>
    <input id="llm_base" placeholder="https://api.openai.com/v1" />
    <div class="hint">OpenAI: https://api.openai.com/v1 ；智谱GLM: https://open.bigmodel.cn/api/paas/v4</div>

    <label for="llm_key">LLM API Key</label>
    <input id="llm_key" type="password" placeholder="留空表示不修改" />

    <label for="llm_model">LLM Model</label>
    <input id="llm_model" placeholder="gpt-4o-mini" />

    <div class="row">
      <button class="btn-save" id="btnSave">保存</button>
      <button class="btn-test" id="btnTest">测试连接</button>
    </div>
    <div class="msg" id="msg"></div>
  </div>

  <div class="card" id="cache" style="margin-top: 22px;">
    <h1>翻译缓存</h1>
    <p class="sub">字幕按视频 ID 缓存在后端。可查看按时间顺序组装的完整字幕，并一键做上下文完整重译（比逐句翻译更连贯）。</p>
    <p class="stat" id="cacheStat">加载中…</p>

    <div class="row" style="margin-top: 0;">
      <button class="btn-test" id="btnRefresh">刷新列表</button>
      <button class="btn-test btn-danger" id="btnClearAll" style="color:#f87171;border-color:rgba(239,68,68,.4)">清空全部缓存</button>
    </div>

    <div id="cacheView"></div>
    <div class="msg" id="cacheMsg"></div>
  </div>

  <div class="card" id="summaries" style="margin-top: 22px;">
    <h1>内容小结</h1>
    <p class="sub">当某视频字幕全部翻译完成后，系统会基于字幕自动生成一篇有深度的内容解读文章。</p>
    <p class="stat" id="summaryStat">加载中…</p>

    <div class="row" style="margin-top: 0;">
      <button class="btn-test" id="btnSummaryRefresh">刷新列表</button>
    </div>

    <div id="summaryView"></div>
    <div class="msg" id="summaryMsg"></div>
  </div>
  </div>

<script>
const $ = (id) => document.getElementById(id);
const msg = $("msg");

function showMsg(type, text) {
  msg.className = "msg " + type;
  msg.textContent = text;
}

async function loadConfig() {
  try {
    const r = await fetch("/config");
    const c = await r.json();
    $("llm_base").value = c.LLM_BASE_URL || "";
    $("llm_model").value = c.LLM_MODEL || "";
    $("target_lang").value = c.TARGET_LANG || "zh";
    $("llm_key").placeholder = c.LLM_API_KEY_SET
      ? ("已设置（" + c.LLM_API_KEY_MASKED + "），留空不修改") : "未设置";
  } catch (e) {
    showMsg("err", "读取配置失败：" + e);
  }
}

function collect() {
  return {
    LLM_BASE_URL: $("llm_base").value.trim(),
    LLM_API_KEY: $("llm_key").value,
    LLM_MODEL: $("llm_model").value.trim(),
    TARGET_LANG: $("target_lang").value,
  };
}

$("btnSave").onclick = async () => {
  $("btnSave").disabled = true;
  showMsg("info", "保存中…");
  try {
    const r = await fetch("/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    showMsg("ok", "已保存并生效。");
    $("llm_key").value = "";
    await loadConfig();
  } catch (e) {
    showMsg("err", "保存失败：" + e);
  } finally {
    $("btnSave").disabled = false;
  }
};

$("btnTest").onclick = async () => {
  $("btnTest").disabled = true;
  showMsg("info", "正在测试连接（翻译 \"Hello\"）…");
  try {
    const body = collect();
    const r = await fetch("/config/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.ok) {
      showMsg("ok", "测试成功（" + d.engine + "）：Hello → " + (d.translation || []).join(" / "));
    } else {
      showMsg("err", "测试失败（" + (d.engine || "") + "）：" + d.error);
    }
  } catch (e) {
    showMsg("err", "测试请求失败：" + e);
  } finally {
    $("btnTest").disabled = false;
  }
};

loadConfig();

// ---------- 翻译缓存管理 ----------

const cacheStat = $("cacheStat");
const cacheView = $("cacheView");
const cacheMsg = $("cacheMsg");

function showCacheMsg(type, text) {
  cacheMsg.className = "msg " + type;
  cacheMsg.textContent = text;
}

function fmtBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(2) + " MB";
}

function fmtTime(sec) {
  try { return new Date(sec * 1000).toLocaleString(); } catch (e) { return ""; }
}

function esc(s) {
  return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

async function loadCacheList() {
  cacheView.innerHTML = "";
  cacheMsg.className = "msg";
  try {
    const r = await fetch("/cache");
    const d = await r.json();
    const s = d.stats || { videos: 0, entries: 0, bytes: 0 };
    cacheStat.innerHTML =
      "已缓存 <b>" + s.videos + "</b> 个视频，共 <b>" + s.entries +
      "</b> 条译文，占用 <b>" + fmtBytes(s.bytes) + "</b>";

    if (!d.videos || !d.videos.length) {
      cacheView.innerHTML =
        '<div class="empty">暂无缓存。请先在 YouTube 用扩展开启字幕翻译（需刷新扩展后才会写入后端缓存），然后点「刷新列表」。</div>';
      return;
    }
    const list = document.createElement("div");
    list.className = "vlist";
    for (const v of d.videos) {
      const item = document.createElement("div");
      item.className = "vitem";
      item.innerHTML =
        '<a class="vid" href="https://www.youtube.com/watch?v=' + encodeURIComponent(v.videoId) +
        '" target="_blank">' + esc(v.videoId) + "</a>" +
        (v.stale ? '<span class="badge failed" title="entries 与 phrases 不一致">不一致</span>' : "") +
        '<span class="meta">' + v.count + " 句 · " + fmtBytes(v.bytes) + " · " + fmtTime(v.updated) + "</span>";
      const btnSub = document.createElement("button");
      btnSub.className = "mini";
      btnSub.textContent = "完整字幕";
      btnSub.onclick = () => viewSubtitle(v.videoId);
      const btnRetrans = document.createElement("button");
      btnRetrans.className = "mini btn-accent";
      btnRetrans.style.cssText = "background:rgba(34,197,94,.2);color:#4ade80;border-color:rgba(34,197,94,.4)";
      btnRetrans.textContent = "完整重译";
      btnRetrans.onclick = () => retranslateVideo(v.videoId, false);
      const btnView = document.createElement("button");
      btnView.className = "mini";
      btnView.textContent = "条目";
      btnView.onclick = () => viewEntries(v.videoId);
      const btnDel = document.createElement("button");
      btnDel.className = "mini danger";
      btnDel.textContent = "删除";
      btnDel.onclick = () => deleteVideo(v.videoId);
      item.appendChild(btnSub);
      item.appendChild(btnRetrans);
      item.appendChild(btnView);
      item.appendChild(btnDel);
      list.appendChild(item);
    }
    cacheView.appendChild(list);
  } catch (e) {
    showCacheMsg("err", "读取缓存失败：" + e);
  }
}

function removeEntriesBox() {
  const old = document.getElementById("entriesBox");
  if (old) old.remove();
}

async function viewSubtitle(videoId) {
  removeEntriesBox();
  showCacheMsg("info", "正在加载完整字幕…");
  try {
    const r = await fetch("/cache/" + encodeURIComponent(videoId) + "/subtitle?format=text");
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "HTTP " + r.status);
    const box = document.createElement("div");
    box.id = "entriesBox";
    const st = d.stats || {};
    box.innerHTML =
      '<div class="subtitle-meta">视频 ' + esc(videoId) +
      " · 共 " + (st.total || 0) + " 句 · 已译 " + (st.translated || 0) +
      " · 来源 " + esc(d.source || "") + "</div>" +
      '<div class="subtitle-box">' + esc(d.body || "") + "</div>" +
      '<div class="subtitle-actions">' +
      '<button class="mini" id="btnDlSrt">下载 SRT</button>' +
      '<button class="mini" id="btnForceRetrans">强制全部重译</button>' +
      "</div>";
    cacheView.appendChild(box);
    $("btnDlSrt").onclick = () => downloadSubtitle(videoId, "srt");
    $("btnForceRetrans").onclick = () => retranslateVideo(videoId, true);
    showCacheMsg("ok", "已加载完整字幕（" + (st.translated || 0) + "/" + (st.total || 0) + " 句已译）");
  } catch (e) {
    showCacheMsg("err", "加载字幕失败：" + e);
  }
}

async function downloadSubtitle(videoId, format) {
  try {
    const r = await fetch("/cache/" + encodeURIComponent(videoId) + "/subtitle?format=" + format);
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "HTTP " + r.status);
    const blob = new Blob([d.body || ""], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = videoId + ".srt";
    a.click();
    URL.revokeObjectURL(a.href);
    showCacheMsg("ok", "已下载 " + videoId + ".srt");
  } catch (e) {
    showCacheMsg("err", "下载失败：" + e);
  }
}

async function retranslateVideo(videoId, force) {
  const label = force ? "强制全部重译" : "完整重译";
  if (!confirm("确定对视频 " + videoId + " 执行「" + label + "」？\n将使用上下文块翻译，可能需要数分钟。")) return;
  showCacheMsg("info", label + "已启动，后台处理中…");
  try {
    const r = await fetch("/cache/" + encodeURIComponent(videoId) + "/retranslate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: !!force, mode: "line" }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || d.message || "HTTP " + r.status);
    await pollRetranslate(videoId, label);
  } catch (e) {
    showCacheMsg("err", label + "失败：" + e);
  }
}

async function pollRetranslate(videoId, label) {
  for (let i = 0; i < 600; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const r = await fetch("/cache/" + encodeURIComponent(videoId) + "/retranslate/status");
    const d = await r.json();
    if (d.status === "running") {
      const prog = d.total ? " " + (d.translated || 0) + "/" + d.total : "";
      showCacheMsg("info", label + "进行中…" + prog);
      continue;
    }
    if (d.status === "done") {
      showCacheMsg("ok", label + "完成：新译 " + (d.translated || 0) + " 句，" +
        (d.stats ? d.stats.translated + "/" + d.stats.total + " 句已就绪" : d.message || ""));
      await viewSubtitle(videoId);
      await loadCacheList();
      return;
    }
    if (d.status === "failed") {
      showCacheMsg("err", label + "失败：" + (d.error || "未知错误"));
      return;
    }
    if (d.status === "idle") break;
  }
  showCacheMsg("info", label + "仍在后台运行，请稍后点「完整字幕」查看结果。");
}

async function viewEntries(videoId) {
  try {
    const r = await fetch("/cache/" + encodeURIComponent(videoId));
    const d = await r.json();
    const box = document.createElement("div");
    box.className = "entries";
    const phrases = d.phrases || [];
    const st = d.stats || {};
    if (!phrases.length) {
      box.innerHTML = '<div class="entry empty">该视频暂无缓存条目。</div>';
    } else {
      for (const p of phrases) {
        const row = document.createElement("div");
        row.className = "entry";
        const en = p.text || "";
        const zh = p.zh || "";
        row.innerHTML =
          '<div class="en">' + esc(en) + "</div>" +
          '<div class="zh">' + (zh ? esc(zh) : '<span style="color:var(--muted)">（未译）</span>') + "</div>";
        box.appendChild(row);
      }
    }
    removeEntriesBox();
    box.id = "entriesBox";
    cacheView.appendChild(box);
    const removed = (d.entryCount || 0) - (d.count || 0);
    const staleNote = removed > 0 ? "，已忽略 " + removed + " 条过期缓存" : "";
    showCacheMsg(
      "info",
      "按时间顺序 " + (st.total || phrases.length) + " 句 · 已译 " +
        (st.translated || 0) + staleNote
    );
  } catch (e) {
    showCacheMsg("err", "查看失败：" + e);
  }
}

async function deleteVideo(videoId) {
  if (!confirm("确定删除视频 " + videoId + " 的翻译缓存？")) return;
  try {
    const r = await fetch("/cache/" + encodeURIComponent(videoId), { method: "DELETE" });
    const d = await r.json();
    showCacheMsg(d.ok ? "ok" : "err", d.ok ? "已删除 " + videoId : "删除失败");
    await loadCacheList();
  } catch (e) {
    showCacheMsg("err", "删除失败：" + e);
  }
}

$("btnRefresh").onclick = loadCacheList;
$("btnClearAll").onclick = async () => {
  if (!confirm("确定清空全部翻译缓存？此操作不可恢复。")) return;
  try {
    const r = await fetch("/cache", { method: "DELETE" });
    const d = await r.json();
    showCacheMsg("ok", "已清空全部缓存（删除 " + (d.removed || 0) + " 个视频）");
    await loadCacheList();
  } catch (e) {
    showCacheMsg("err", "清空失败：" + e);
  }
};

loadCacheList();

// ---------- 内容小结 ----------

const summaryStat = $("summaryStat");
const summaryView = $("summaryView");
const summaryMsg = $("summaryMsg");

function showSummaryMsg(type, text) {
  summaryMsg.className = "msg " + type;
  summaryMsg.textContent = text;
}

function summaryBadge(status) {
  const map = {
    ready: '<span class="badge ready">已完成</span>',
    generating: '<span class="badge generating">生成中</span>',
    failed: '<span class="badge failed">失败</span>',
  };
  return map[status] || '<span class="badge none">未生成</span>';
}

async function loadSummaryList() {
  summaryView.innerHTML = "";
  summaryMsg.className = "msg";
  try {
    const [sumR, cacheR] = await Promise.all([
      fetch("/summaries"),
      fetch("/cache"),
    ]);
    const sumD = await sumR.json();
    const cacheD = await cacheR.json();
    const summaries = sumD.summaries || [];
    const videos = cacheD.videos || [];
    const sumMap = {};
    for (const s of summaries) sumMap[s.videoId] = s;

    const ready = summaries.filter((s) => s.status === "ready").length;
    summaryStat.innerHTML =
      "共 <b>" + summaries.length + "</b> 条记录，已完成 <b>" + ready + "</b> 篇";

    if (!videos.length) {
      summaryView.innerHTML =
        '<div class="empty">暂无缓存视频。请先在 YouTube 用扩展看完并翻译字幕，完成后会自动生成小结。</div>';
      return;
    }

    const list = document.createElement("div");
    list.className = "vlist";
    for (const v of videos) {
      const s = sumMap[v.videoId];
      const item = document.createElement("div");
      item.className = "vitem";
      const title = s && s.title ? esc(s.title) : esc(v.videoId);
      item.innerHTML =
        '<a class="vid" href="https://www.youtube.com/watch?v=' + encodeURIComponent(v.videoId) +
        '" target="_blank">' + esc(v.videoId) + "</a>" +
        '<span class="meta">' + v.count + " 条字幕" + summaryBadge(s && s.status) + "</span>";

      if (s && s.status === "ready") {
        const btnRead = document.createElement("button");
        btnRead.className = "mini";
        btnRead.textContent = "阅读小结";
        btnRead.onclick = () => window.open("/summary/" + encodeURIComponent(v.videoId) + "/article", "_blank");
        item.appendChild(btnRead);
      } else if (s && s.status === "generating") {
        const btnWait = document.createElement("button");
        btnWait.className = "mini";
        btnWait.textContent = "生成中…";
        btnWait.disabled = true;
        item.appendChild(btnWait);
      } else {
        const btnGen = document.createElement("button");
        btnGen.className = "mini";
        btnGen.textContent = s && s.status === "failed" ? "重新生成" : "生成小结";
        btnGen.onclick = () => generateSummary(v.videoId, true);
        item.appendChild(btnGen);
      }

      if (s) {
        const btnDel = document.createElement("button");
        btnDel.className = "mini danger";
        btnDel.textContent = "删除";
        btnDel.onclick = () => deleteSummary(v.videoId);
        item.appendChild(btnDel);
      }

      list.appendChild(item);
      // 副标题行
      if (s && s.title) {
        const sub = document.createElement("div");
        sub.className = "hint";
        sub.style.margin = "0 0 4px 4px";
        sub.textContent = s.title;
        list.appendChild(sub);
      }
    }
    summaryView.appendChild(list);
  } catch (e) {
    showSummaryMsg("err", "读取小结列表失败：" + e);
  }
}

async function generateSummary(videoId, force) {
  showSummaryMsg("info", "正在提交生成任务…");
  try {
    const r = await fetch("/summary/" + encodeURIComponent(videoId) + "/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: !!force }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "HTTP " + r.status);
    showSummaryMsg("ok", "已提交，正在后台生成（约 1-3 分钟）。请稍后刷新列表。");
    await loadSummaryList();
    // 生成中时自动轮询
    if (d.status === "generating") pollSummary(videoId);
  } catch (e) {
    showSummaryMsg("err", "生成失败：" + e);
  }
}

async function pollSummary(videoId) {
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 5000));
    try {
      const r = await fetch("/summary/" + encodeURIComponent(videoId));
      if (!r.ok) continue;
      const d = await r.json();
      if (d.status === "ready") {
        showSummaryMsg("ok", "小结已生成：" + (d.title || videoId));
        await loadSummaryList();
        return;
      }
      if (d.status === "failed") {
        showSummaryMsg("err", "生成失败：" + (d.error || "未知错误"));
        await loadSummaryList();
        return;
      }
    } catch (e) { /* ignore */ }
  }
  showSummaryMsg("info", "仍在生成中，请稍后手动刷新。");
}

async function deleteSummary(videoId) {
  if (!confirm("确定删除视频 " + videoId + " 的内容小结？")) return;
  try {
    const r = await fetch("/summary/" + encodeURIComponent(videoId), { method: "DELETE" });
    const d = await r.json();
    showSummaryMsg(d.ok ? "ok" : "err", d.ok ? "已删除小结" : "删除失败");
    await loadSummaryList();
  } catch (e) {
    showSummaryMsg("err", "删除失败：" + e);
  }
}

$("btnSummaryRefresh").onclick = loadSummaryList;
loadSummaryList();
</script>
</body>
</html>
"""
