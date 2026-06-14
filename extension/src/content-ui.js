// ISOLATED world：UI 与编排。
// 流程：收到开关消息 -> 向 MAIN 世界请求字幕 -> 发后端翻译 ->
// 监听 <video> 时间，按时间戳叠加显示中文字幕。

const BACKEND_URL = "http://127.0.0.1:8000";

const state = {
  active: false,
  segments: [], // 原始碎片 [{ start, dur, text }]
  phrases: [], // 合并后的句子 [{ start, end, text, zh, indices }]
  videoId: "",
  lastPhraseIndex: -1,
  syncTimer: null,
  renderKey: "",
  translateToken: 0,
  cache: {}, // { 英文句子: 中文译文 }，按视频持久化
  backendCacheSnapshot: {}, // 启动时后端已有条目，用于增量同步
};

// ---------- 与 MAIN 世界通信：拉字幕 ----------

function getVideoIdFromPage() {
  return new URLSearchParams(location.search).get("v") || "";
}

function getActiveVideoId() {
  return state.videoId || getVideoIdFromPage() || "";
}

function requestCaptionsFromPage() {
  return new Promise((resolve) => {
    const reqId = String(Date.now());
    function onMsg(event) {
      if (event.source !== window) return;
      const d = event.data;
      if (!d || d.source !== "ytt-main" || d.action !== "CAPTIONS") return;
      if (d.reqId !== reqId) return;
      window.removeEventListener("message", onMsg);
      resolve(d);
    }
    window.addEventListener("message", onMsg);
    window.postMessage({ source: "ytt", action: "FETCH_CAPTIONS", reqId }, "*");
    setTimeout(() => {
      window.removeEventListener("message", onMsg);
      resolve({ error: "请求字幕超时。" });
    }, 15000);
  });
}

async function requestCaptionsFromBackend(videoId) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  let resp;
  try {
    resp = await fetch(
      `${BACKEND_URL}/captions?video_id=${encodeURIComponent(videoId)}`,
      { signal: ctrl.signal }
    );
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "后端超时（可能被限流）" : e.message);
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) {
    let detail = "HTTP " + resp.status;
    try {
      const err = await resp.json();
      detail = err.detail || detail;
    } catch (e) {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json();
}

async function requestCaptions() {
  const page = await requestCaptionsFromPage();
  if (page.segments?.length) return page;

  const videoId = page.videoId || getVideoIdFromPage();
  if (!videoId) {
    return { error: page.error || "无法识别当前视频 ID。" };
  }

  try {
    const backend = await requestCaptionsFromBackend(videoId);
    return { ...backend, method: "backend" };
  } catch (e) {
    const browserHint = page.error ? "浏览器：" + page.error + "；" : "";
    return { error: browserHint + "后端：" + e.message };
  }
}

// ---------- 碎片合并为完整句子 ----------

const SENTENCE_END = /[.!?…]["']?\s*$/;
// 一屏只显示「一小句」：控制字数、时长、碎片数，自然分页。
const MAX_PHRASE_CHARS = 64; // 英文字符上限（约 1~2 行中文）
const MAX_PHRASE_FRAGS = 6;
const MAX_PHRASE_DUR = 6; // 单句最长显示时长（秒）
const PHRASE_GAP_SEC = 0.8;

function buildPhrases(segments) {
  const phrases = [];
  let buf = null;

  function flush() {
    if (!buf || !buf.indices.length) return;
    phrases.push({
      start: buf.start,
      end: buf.end,
      text: buf.texts.join(" ").replace(/\s+/g, " ").trim(),
      zh: "",
      indices: buf.indices,
    });
    buf = null;
  }

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const prev = i > 0 ? segments[i - 1] : null;
    const gap = prev ? seg.start - (prev.start + (prev.dur || 0)) : 0;

    if (buf) {
      const joined = buf.texts.join(" ");
      const dur = seg.start + (seg.dur || 2) - buf.start;
      const hitLimit =
        buf.indices.length >= MAX_PHRASE_FRAGS ||
        joined.length + seg.text.length > MAX_PHRASE_CHARS ||
        dur > MAX_PHRASE_DUR ||
        gap > PHRASE_GAP_SEC;
      const prevEnded =
        buf.texts.length &&
        SENTENCE_END.test(buf.texts[buf.texts.length - 1].trim());
      if (hitLimit || prevEnded) flush();
    }

    if (!buf) {
      buf = { start: seg.start, end: seg.start + (seg.dur || 2), texts: [], indices: [] };
    }
    buf.texts.push(seg.text);
    buf.indices.push(i);
    buf.end = seg.start + (seg.dur || 2);
  }
  flush();
  return phrases;
}

function isValidTranslation(text, sourceText) {
  if (!text) return false;
  const src = (sourceText || "").trim();
  const tr = text.trim();
  return Boolean(tr) && tr.toLowerCase() !== src.toLowerCase();
}

function phraseDisplayEnd(phrases, idx) {
  const p = phrases[idx];
  const next = phrases[idx + 1];
  return next ? next.start : p.end + 0.5;
}

// ---------- 翻译缓存（按视频持久化，反复观看越来越全）----------

const CACHE_PREFIX = "ytt:cache:";

function cacheKey(videoId) {
  return CACHE_PREFIX + videoId;
}

// 以合并后的英文句子为键，避免分段变化导致错配（同一视频字幕稳定）。
async function loadCache(videoId) {
  if (!videoId || !chrome?.storage?.local) return {};
  try {
    const key = cacheKey(videoId);
    const obj = await chrome.storage.local.get(key);
    return obj[key] || {};
  } catch (e) {
    console.warn(LOG, "读取缓存失败:", e);
    return {};
  }
}

let _cacheSaveTimer = null;
function saveCacheDebounced(videoId, map) {
  const vid = videoId || getActiveVideoId();
  if (!vid || !chrome?.storage?.local) return;
  clearTimeout(_cacheSaveTimer);
  _cacheSaveTimer = setTimeout(() => {
    chrome.storage.local.set({ [cacheKey(vid)]: map }).catch((e) => {
      console.warn(LOG, "写入本地缓存失败:", e);
    });
  }, 800);
}

let _backendSyncTimer = null;
let _pendingBackendEntries = {};

function queueBackendCache(entries) {
  Object.assign(_pendingBackendEntries, entries);
  clearTimeout(_backendSyncTimer);
  _backendSyncTimer = setTimeout(syncBackendCache, 600);
}

async function syncBackendCache() {
  const vid = getActiveVideoId();
  const entries = _pendingBackendEntries;
  _pendingBackendEntries = {};
  if (!vid || !Object.keys(entries).length) return 0;
  try {
    const r = await fetch(`${BACKEND_URL}/cache/${encodeURIComponent(vid)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries }),
    });
    if (r.ok) {
      const d = await r.json();
      console.log(LOG, `后端缓存同步 +${d.added || 0}，共 ${d.count || 0} 条`);
      return d.added || 0;
    }
  } catch (e) {
    console.warn(LOG, "同步后端缓存失败:", e);
  }
  return 0;
}

// 把本地已有、但后端还没有的译文批量推上去（全缓存命中时也会执行）。
async function pushCacheDeltaToBackend(knownBackend = {}) {
  const vid = getActiveVideoId();
  if (!vid) return 0;

  const delta = {};
  for (const [en, zh] of Object.entries(state.cache)) {
    if (!knownBackend[en] && isValidTranslation(zh, en)) {
      delta[en] = zh;
    }
  }
  const keys = Object.keys(delta);
  if (!keys.length) return 0;

  console.log(LOG, `准备同步 ${keys.length} 条本地缓存到后端…`);
  const BATCH = 80;
  let added = 0;
  for (let i = 0; i < keys.length; i += BATCH) {
    const slice = {};
    keys.slice(i, i + BATCH).forEach((k) => (slice[k] = delta[k]));
    try {
      const r = await fetch(`${BACKEND_URL}/cache/${encodeURIComponent(vid)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: slice }),
      });
      if (r.ok) {
        const d = await r.json();
        added += d.added || 0;
      }
    } catch (e) {
      console.warn(LOG, "批量同步后端缓存失败:", e);
      break;
    }
  }
  if (added) console.log(LOG, `本地缓存已同步到后端 +${added} 条`);
  return added;
}

async function loadBackendCache(videoId) {
  if (!videoId) return {};
  try {
    const r = await fetch(`${BACKEND_URL}/cache/${encodeURIComponent(videoId)}`);
    if (!r.ok) return {};
    const d = await r.json();
    return d.entries || {};
  } catch (e) {
    console.warn(LOG, "读取后端缓存失败:", e);
    return {};
  }
}

// ---------- 后端翻译 ----------

const CHUNK_SIZE = 12; // 每块句子数（整句比碎片长，块宜小）
const CONCURRENCY = 2; // 降低并发，减轻限流
const RETRY_ROUNDS = 4; // 补偿重试轮数
const RETRY_CHUNK = 6; // 重试时用更小的块，提高成功率

async function translateChunk(texts) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 90000);
  let resp;
  try {
    resp = await fetch(`${BACKEND_URL}/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        segments: texts,
        mode: "sentence",
        video_id: getActiveVideoId() || null,
      }),
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "翻译超时" : e.message);
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) {
    let detail = "HTTP " + resp.status;
    try {
      const err = await resp.json();
      detail = err.detail || detail;
    } catch (e) {
      /* ignore */
    }
    throw new Error(detail);
  }
  const data = await resp.json();
  if (data.cached > 0 || data.translated > 0) {
    console.log(
      LOG,
      `翻译批次: 缓存命中 ${data.cached}，新译 ${data.translated}，video=${getActiveVideoId()}`
    );
  }
  return data.translations;
}

// 接受一条译文并写入：校验译文有效、长度合理，更新缓存。
function acceptTranslation(phrase, translated) {
  if (!phrase || !translated) return false;
  const tooLong = translated.length > phrase.text.length * 1.6 + 24;
  if (!isValidTranslation(translated, phrase.text) || tooLong) return false;
  phrase.zh = translated;
  state.cache[phrase.text] = translated;
  return true;
}

function untranslatedIndices() {
  const list = [];
  for (let i = 0; i < state.phrases.length; i++) {
    if (!state.phrases[i].zh) list.push(i);
  }
  return list;
}

// 翻译指定的一批句子索引（保持原文顺序的子集），分块并发。
async function translateIndices(token, indices, chunkSize) {
  const phrases = state.phrases;
  let cursor = 0;
  let firstError = null;

  async function worker() {
    while (cursor < indices.length) {
      if (!state.active || token !== state.translateToken) return;
      const begin = cursor;
      cursor += chunkSize;
      const group = indices.slice(begin, begin + chunkSize);
      const slice = group.map((gi) => phrases[gi]);
      try {
        const zhList = await translateChunk(slice.map((p) => p.text));
        if (token !== state.translateToken) return;
        const newPairs = {};
        for (let i = 0; i < slice.length; i++) {
          if (acceptTranslation(slice[i], zhList[i])) {
            newPairs[slice[i].text] = slice[i].zh;
          }
        }
        saveCacheDebounced(getActiveVideoId(), state.cache);
        if (Object.keys(newPairs).length) queueBackendCache(newPairs);
        state.renderKey = "";
        syncTick();
        const zhCount = phrases.length - untranslatedIndices().length;
        toast(`翻译进度 ${zhCount}/${phrases.length} 句`, 1000);
      } catch (e) {
        if (!firstError) firstError = e;
        console.error(LOG, "句块翻译失败:", e.message);
      }
    }
  }

  const workers = [];
  for (let i = 0; i < CONCURRENCY; i++) workers.push(worker());
  await Promise.all(workers);
  return firstError;
}

// 主流程：先用缓存填充，再翻译缺失项，并多轮补偿重试漏翻的句子。
async function translateInBackground(token) {
  const phrases = state.phrases;
  const total = phrases.length;

  // 1) 缓存命中：直接填充已有译文。
  let cached = 0;
  for (const p of phrases) {
    const hit = state.cache[p.text];
    if (hit && isValidTranslation(hit, p.text)) {
      p.zh = hit;
      cached++;
    }
  }
  if (cached) {
    console.log(LOG, `缓存命中 ${cached}/${total} 句`);
    state.renderKey = "";
    syncTick();
    toast(`缓存命中 ${cached}/${total} 句`, 1500);
  }

  // 2) 首轮：从当前播放位置优先，翻译所有缺失项。
  let missing = untranslatedIndices();
  if (missing.length === 0) {
    // 全命中本地缓存时也要把译文推到后端，否则后台永远看不到记录。
    const synced = await pushCacheDeltaToBackend(state.backendCacheSnapshot);
    if (synced) toast(`已同步 ${synced} 条到后端缓存`, 2500);
    toast(`中文字幕就绪 ${total}/${total} 句 ✓`);
    return;
  }
  // 重排顺序：把当前位置之后的排前面，优先翻译正在看的部分。
  const curIdx = state.lastPhraseIndex >= 0 ? state.lastPhraseIndex : 0;
  missing.sort((a, b) => {
    const ra = a >= curIdx ? a - curIdx : a + total;
    const rb = b >= curIdx ? b - curIdx : b + total;
    return ra - rb;
  });

  let firstError = await translateIndices(token, missing, CHUNK_SIZE);
  if (token !== state.translateToken) return;

  // 3) 补偿重试：反复翻译仍然漏掉的句子，用更小的块提高成功率。
  for (let round = 1; round <= RETRY_ROUNDS; round++) {
    if (!state.active || token !== state.translateToken) return;
    const still = untranslatedIndices();
    if (still.length === 0) break;
    console.log(LOG, `补偿第 ${round} 轮，剩余 ${still.length} 句`);
    toast(`补全漏翻：第 ${round} 轮，剩 ${still.length} 句`, 1500);
    await new Promise((r) => setTimeout(r, 600 * round)); // 退避，缓解限流
    const err = await translateIndices(token, still, RETRY_CHUNK);
    if (err) firstError = err;
  }

  if (token !== state.translateToken) return;
  saveCacheDebounced(state.videoId, state.cache);
  await pushCacheDeltaToBackend(state.backendCacheSnapshot);

  const remaining = untranslatedIndices().length;
  const zhCount = total - remaining;
  if (zhCount === 0 && firstError) {
    const hint =
      firstError.message === "Failed to fetch"
        ? "无法连接后端（请确认 python main.py 已启动）"
        : firstError.message;
    toast("翻译失败：" + hint, 8000);
  } else if (remaining > 0) {
    console.log(LOG, `翻译完成 ${zhCount}/${total}，仍有 ${remaining} 句未译`);
    toast(`已翻译 ${zhCount}/${total} 句，${remaining} 句稍后可重试`, 5000);
  } else {
    console.log(LOG, `翻译完成 ${total}/${total} 句`);
    toast(`中文字幕就绪 ${total}/${total} 句 ✓`);
  }
  state.renderKey = "";
  syncTick();
}

// ---------- 字幕叠加 ----------

function getPlayerContainer() {
  return (
    document.querySelector(".html5-video-player") ||
    document.querySelector("#movie_player")
  );
}

function ensureSubtitleEl() {
  let el = document.getElementById("ytt-subtitle");
  if (!el) {
    el = document.createElement("div");
    el.id = "ytt-subtitle";
    const container = getPlayerContainer();
    (container || document.body).appendChild(el);
  }
  return el;
}

function showSubtitle(zh, en) {
  const el = ensureSubtitleEl();
  el.innerHTML = "";
  if (!zh) {
    el.style.display = "none";
    return;
  }
  el.style.display = "block";
  const z = document.createElement("span");
  z.className = "ytt-zh";
  z.textContent = zh;
  el.appendChild(z);
  if (en) {
    const e = document.createElement("span");
    e.className = "ytt-en";
    e.textContent = en;
    el.appendChild(e);
  }
}

function getVideo() {
  return document.querySelector("video.html5-main-video, video");
}

function syncTick() {
  const video = getVideo();
  const phrases = state.phrases;
  if (!video || !phrases.length) return;

  const t = video.currentTime;
  let idx = state.lastPhraseIndex >= 0 ? state.lastPhraseIndex : 0;
  if (idx >= phrases.length) idx = 0;

  while (idx < phrases.length - 1 && t >= phraseDisplayEnd(phrases, idx)) idx++;
  while (idx > 0 && t < phrases[idx].start) idx--;
  state.lastPhraseIndex = idx;

  const phrase = phrases[idx];
  const end = phraseDisplayEnd(phrases, idx);
  const inRange = phrase && t >= phrase.start && t < end;

  if (!inRange) {
    if (state.renderKey !== "") {
      showSubtitle("", "");
      state.renderKey = "";
    }
    return;
  }

  // 整句显示：有译文则主显译文+小字英文；未译完则整句英文，避免碎片混杂。
  const hasTranslation = phrase.zh && isValidTranslation(phrase.zh, phrase.text);
  const main = hasTranslation ? phrase.zh : phrase.text;
  const sub = hasTranslation ? phrase.text : "";
  const key = idx + "|" + main + "|" + sub;
  if (key !== state.renderKey) {
    showSubtitle(main, sub);
    state.renderKey = key;
  }
}

// ---------- 提示 ----------

function ensureToastEl() {
  let el = document.getElementById("ytt-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "ytt-toast";
    document.body.appendChild(el);
  }
  return el;
}

function toast(msg, ms = 3000) {
  const el = ensureToastEl();
  el.textContent = msg;
  el.style.display = "block";
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.style.display = "none"), ms);
}

// 友好提示：未配置 LLM 时给出说明 + 一个可点击打开设置页的链接。
function toastWithSettingsLink(msg, ms = 12000) {
  const el = ensureToastEl();
  el.textContent = "";
  const text = document.createElement("div");
  text.textContent = msg;
  el.appendChild(text);
  const link = document.createElement("a");
  link.className = "ytt-toast-link";
  link.textContent = "打开设置页配置 API Key →";
  link.href = `${BACKEND_URL}/`;
  link.target = "_blank";
  link.rel = "noopener";
  el.appendChild(link);
  el.style.display = "block";
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.style.display = "none"), ms);
}

// ---------- 开关 ----------

const LOG = "[YTT]";

// 启动前检查后端与翻译配置是否就绪。
// 返回 { ok, reason }：reason ∈ "offline" | "backend_error" | "no_llm"。
async function checkBackendReady() {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 5000);
  let resp;
  try {
    resp = await fetch(`${BACKEND_URL}/health`, { signal: ctrl.signal });
  } catch (e) {
    return { ok: false, reason: "offline" };
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) return { ok: false, reason: "backend_error" };
  let data;
  try {
    data = await resp.json();
  } catch (e) {
    return { ok: false, reason: "backend_error" };
  }
  if (!data.translate_ready) return { ok: false, reason: "no_llm" };
  return { ok: true };
}

async function start() {
  console.log(LOG, "start(): 检查后端与翻译配置");
  const ready = await checkBackendReady();
  if (!ready.ok) {
    state.active = false;
    if (ready.reason === "no_llm") {
      console.warn(LOG, "翻译模型未配置，提示用户前往设置页。");
      toastWithSettingsLink(
        "尚未配置翻译模型（LLM API Key），无法翻译字幕。请先完成配置。"
      );
    } else if (ready.reason === "offline") {
      toast("无法连接后端，请先启动后端：cd backend && python main.py", 8000);
    } else {
      toast("后端异常，请检查后端日志后重试。", 8000);
    }
    return;
  }

  console.log(LOG, "start(): 开始抓取字幕");
  toast("正在抓取字幕…");
  const cap = await requestCaptions();
  console.log(LOG, "requestCaptions 返回:", cap);
  if (cap.error || !cap.segments) {
    toast(cap.error || "无法获取字幕。", 6000);
    state.active = false;
    return;
  }
  state.videoId = cap.videoId || getVideoIdFromPage() || "";
  if (!state.videoId) {
    toast("无法识别视频 ID，后端缓存将不可用。", 5000);
  }

  const via = cap.method === "backend" ? "（后端）" : "";
  const asr = cap.isGenerated ? "，自动生成" : "";
  console.log(LOG, `抓到 ${cap.segments.length} 条，首条:`, cap.segments[0]);

  // 碎片合并为句子，按句翻译、按句显示。
  state.segments = cap.segments;
  state.phrases = buildPhrases(cap.segments);
  state.lastPhraseIndex = -1;
  state.renderKey = "";
  console.log(
    LOG,
    `碎片 ${cap.segments.length} → 句子 ${state.phrases.length}，首句:`,
    state.phrases[0]
  );

  if (state.syncTimer) clearInterval(state.syncTimer);
  state.syncTimer = setInterval(syncTick, 200);
  syncTick();

  const video = getVideo();
  console.log(
    LOG,
    "启动同步，videoId=",
    getActiveVideoId(),
    "currentTime=",
    video?.currentTime
  );
  toast(
    `已获取 ${cap.segments.length} 条字幕${via}${asr}，合并为 ${state.phrases.length} 句，开始翻译…`
  );

  // 加载缓存：后端（跨会话）+ 浏览器本地，合并后优先已有译文。
  const [backendCache, localCache] = await Promise.all([
    loadBackendCache(state.videoId),
    loadCache(state.videoId),
  ]);
  state.cache = { ...backendCache, ...localCache };
  state.backendCacheSnapshot = backendCache;
  console.log(
    LOG,
    `缓存加载: 后端 ${Object.keys(backendCache).length}，本地 ${Object.keys(localCache).length}，videoId=${state.videoId}`
  );

  state.translateToken += 1;
  translateInBackground(state.translateToken);

  window.__ytt = {
    dump: () => ({
      active: state.active,
      fragments: state.segments.length,
      phrases: state.phrases.length,
      translated: state.phrases.filter((p) => p.zh).length,
      untranslated: untranslatedIndices().length,
      cacheSize: Object.keys(state.cache).length,
      videoId: state.videoId,
      lastPhraseIndex: state.lastPhraseIndex,
      currentTime: getVideo()?.currentTime,
      current: state.phrases[state.lastPhraseIndex],
      sample: state.phrases.slice(0, 3),
    }),
    // 手动补全漏翻的句子。
    retry: () => {
      state.translateToken += 1;
      translateInBackground(state.translateToken);
      return "已触发补全";
    },
    // 清除当前视频的翻译缓存。
    clearCache: async () => {
      state.cache = {};
      if (state.videoId && chrome?.storage?.local) {
        await chrome.storage.local.remove(cacheKey(state.videoId));
      }
      return "已清除缓存";
    },
    showTest: () => showSubtitle("【测试】中文字幕渲染正常", "test"),
  };
}

function stop() {
  if (state.syncTimer) clearInterval(state.syncTimer);
  state.syncTimer = null;
  state.segments = [];
  state.phrases = [];
  state.lastPhraseIndex = -1;
  state.renderKey = "";
  state.translateToken += 1;
  showSubtitle("", "");
  toast("中文字幕已关闭");
}

async function toggle() {
  state.active = !state.active;
  if (state.active) {
    await start();
  } else {
    stop();
  }
}

// 切换视频时自动清理（YouTube 是 SPA）。
let lastUrl = location.href;
setInterval(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    if (state.active) {
      stop();
      state.active = false;
    }
  }
}, 1000);

chrome.runtime.onMessage.addListener((msg) => {
  console.log(LOG, "收到消息:", msg);
  if (msg && msg.type === "YTT_TOGGLE") toggle();
});

console.log(LOG, "content-ui 已加载，按 Alt+Shift+Y 或点击扩展图标开启");
