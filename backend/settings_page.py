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
</style>
</head>
<body>
  <nav class="nav">
    <a href="#settings">翻译设置</a>
    <a href="#cache">翻译缓存</a>
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
    <p class="sub">字幕翻译按视频 ID 缓存在后端，反复观看复用缓存，节省 LLM 调用。</p>
    <p class="stat" id="cacheStat">加载中…</p>

    <div class="row" style="margin-top: 0;">
      <button class="btn-test" id="btnRefresh">刷新列表</button>
      <button class="btn-test btn-danger" id="btnClearAll" style="color:#f87171;border-color:rgba(239,68,68,.4)">清空全部缓存</button>
    </div>

    <div id="cacheView"></div>
    <div class="msg" id="cacheMsg"></div>
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
        '<span class="meta">' + v.count + " 条 · " + fmtBytes(v.bytes) + " · " + fmtTime(v.updated) + "</span>";
      const btnView = document.createElement("button");
      btnView.className = "mini";
      btnView.textContent = "查看";
      btnView.onclick = () => viewEntries(v.videoId);
      const btnDel = document.createElement("button");
      btnDel.className = "mini danger";
      btnDel.textContent = "删除";
      btnDel.onclick = () => deleteVideo(v.videoId);
      item.appendChild(btnView);
      item.appendChild(btnDel);
      list.appendChild(item);
    }
    cacheView.appendChild(list);
  } catch (e) {
    showCacheMsg("err", "读取缓存失败：" + e);
  }
}

async function viewEntries(videoId) {
  try {
    const r = await fetch("/cache/" + encodeURIComponent(videoId));
    const d = await r.json();
    const box = document.createElement("div");
    box.className = "entries";
    const entries = d.entries || {};
    const keys = Object.keys(entries);
    if (!keys.length) {
      box.innerHTML = '<div class="entry empty">该视频暂无缓存条目。</div>';
    } else {
      for (const en of keys) {
        const row = document.createElement("div");
        row.className = "entry";
        row.innerHTML = '<div class="en">' + esc(en) + '</div><div class="zh">' + esc(entries[en]) + "</div>";
        box.appendChild(row);
      }
    }
    // 把条目展示在列表下方（替换上一次的展开）。
    const old = document.getElementById("entriesBox");
    if (old) old.remove();
    box.id = "entriesBox";
    cacheView.appendChild(box);
    showCacheMsg("info", "正在查看 " + videoId + " 的 " + keys.length + " 条缓存");
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
</script>
</body>
</html>
"""
