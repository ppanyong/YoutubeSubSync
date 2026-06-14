// MAIN world：运行在页面上下文，可访问 YouTube 播放器内部 API。
//
// 抓取策略（按优先级）：
//   0. 拦截播放器自身的 timedtext 请求 URL（带有效 POT 令牌），
//      再用 fmt=json3 自行重拉 —— 这是当前最稳的方式，绕过 BotGuard。
//   1. Innertube get_transcript（同源）
//   2. Innertube player（ANDROID 客户端）
//   3. 播放器内嵌 captionTracks baseUrl（兜底）

(function () {
  // ---------- 0. 拦截播放器的 timedtext 请求 ----------
  // 播放器开启字幕时会请求 .../api/timedtext?...&pot=<令牌>，
  // 我们只记录这个已鉴权的 URL，之后自行带 fmt=json3 重拉。
  let capturedTimedTextUrl = "";

  function isTimedText(url) {
    return typeof url === "string" && url.includes("/api/timedtext");
  }

  (function installInterceptors() {
    const origFetch = window.fetch;
    if (origFetch && !origFetch.__yttHooked) {
      window.fetch = function (...args) {
        try {
          const input = args[0];
          const url =
            typeof input === "string" ? input : input && input.url ? input.url : "";
          if (isTimedText(url)) capturedTimedTextUrl = url;
        } catch (e) {
          /* ignore */
        }
        return origFetch.apply(this, args);
      };
      window.fetch.__yttHooked = true;
    }

    const XHR = window.XMLHttpRequest;
    if (XHR && XHR.prototype && !XHR.prototype.__yttHooked) {
      const origOpen = XHR.prototype.open;
      XHR.prototype.open = function (method, url, ...rest) {
        try {
          if (isTimedText(url)) capturedTimedTextUrl = url;
        } catch (e) {
          /* ignore */
        }
        return origOpen.call(this, method, url, ...rest);
      };
      XHR.prototype.__yttHooked = true;
    }
  })();

  function getYtcfg(key) {
    try {
      if (window.ytcfg && typeof window.ytcfg.get === "function") {
        return window.ytcfg.get(key);
      }
    } catch (e) {
      /* ignore */
    }
    return undefined;
  }

  function getApiKey() {
    return getYtcfg("INNERTUBE_API_KEY") || "";
  }

  function getClientVersion() {
    return getYtcfg("INNERTUBE_CLIENT_VERSION") || "2.20250201.00.00";
  }

  function getPlayer() {
    return document.getElementById("movie_player");
  }

  function getPlayerResponse() {
    const player = getPlayer();
    if (player && typeof player.getPlayerResponse === "function") {
      try {
        return player.getPlayerResponse();
      } catch (e) {
        /* ignore */
      }
    }
    return window.ytInitialPlayerResponse || null;
  }

  function getVideoId(resp) {
    return (
      resp?.videoDetails?.videoId ||
      new URLSearchParams(location.search).get("v") ||
      ""
    );
  }

  function pickEnglishTrack(tracks) {
    if (!tracks || !tracks.length) return null;
    const en = tracks.filter((t) => (t.languageCode || "").startsWith("en"));
    const manual = en.find((t) => t.kind !== "asr");
    return manual || en[0] || tracks[0];
  }

  // 通过播放器 API 打开字幕，促使其发起 timedtext 请求。
  function triggerCaptions() {
    const player = getPlayer();
    if (!player) return false;
    try {
      if (typeof player.loadModule === "function") player.loadModule("captions");
      let tracks = [];
      if (typeof player.getOption === "function") {
        tracks = player.getOption("captions", "tracklist") || [];
      }
      const track = pickEnglishTrack(tracks) || tracks[0];
      if (track && typeof player.setOption === "function") {
        // 先清空再设置，强制重新拉取（即使本来已开启）。
        player.setOption("captions", "track", {});
        player.setOption("captions", "track", track);
        return true;
      }
    } catch (e) {
      /* ignore */
    }
    return false;
  }

  function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function waitForCapturedUrl(timeoutMs) {
    const startUrl = capturedTimedTextUrl;
    const deadline = Date.now() + timeoutMs;
    triggerCaptions();
    while (Date.now() < deadline) {
      if (capturedTimedTextUrl && capturedTimedTextUrl !== startUrl) {
        return capturedTimedTextUrl;
      }
      await delay(150);
    }
    // 即使没有捕获到新的，旧的也可用（同一视频）。
    return capturedTimedTextUrl || "";
  }

  // ---------- 解析 ----------

  function parseJson3(json) {
    const events = json.events || [];
    const segments = [];
    for (const ev of events) {
      if (!ev.segs) continue;
      const text = ev.segs
        .map((s) => s.utf8 || "")
        .join("")
        .replace(/\n/g, " ")
        .trim();
      if (!text) continue;
      segments.push({
        start: (ev.tStartMs || 0) / 1000,
        dur: (ev.dDurationMs || 0) / 1000,
        text,
      });
    }
    return segments;
  }

  function parseXmlCaptions(xml) {
    const segments = [];
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    // 旧格式 <text start dur>
    doc.querySelectorAll("text").forEach((node) => {
      const start = parseFloat(node.getAttribute("start") || "0");
      const dur = parseFloat(node.getAttribute("dur") || "0");
      const text = decodeHtml(node.textContent || "").replace(/\n/g, " ").trim();
      if (text) segments.push({ start, dur, text });
    });
    if (segments.length) return segments;
    // srv3 格式 <p t d><s>…</s></p>
    doc.querySelectorAll("p").forEach((p) => {
      const t = parseInt(p.getAttribute("t") || "0", 10);
      const d = parseInt(p.getAttribute("d") || "0", 10);
      const text = (p.textContent || "").replace(/\n/g, " ").trim();
      if (text) segments.push({ start: t / 1000, dur: d / 1000, text });
    });
    return segments;
  }

  function decodeHtml(s) {
    const ta = document.createElement("textarea");
    ta.innerHTML = s;
    return ta.value;
  }

  function parseCaptionText(text) {
    const trimmed = (text || "").trim();
    if (!trimmed) throw new Error("字幕响应为空（YouTube 可能限制了该请求）");
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      return parseJson3(JSON.parse(trimmed));
    }
    if (trimmed.startsWith("<")) {
      return parseXmlCaptions(trimmed);
    }
    throw new Error("未知字幕格式");
  }

  function withJson3(url) {
    const u = new URL(url, location.origin);
    u.searchParams.set("fmt", "json3");
    return u.toString();
  }

  async function fetchUrlAsCaptions(url) {
    const r = await fetch(withJson3(url), { credentials: "same-origin" });
    if (!r.ok) throw new Error("timedtext HTTP " + r.status);
    const text = await r.text();
    return parseCaptionText(text);
  }

  // ---------- Innertube 兜底 ----------

  function extractParamsFromPanels(panels) {
    if (!panels || !Array.isArray(panels)) return null;
    for (const panel of panels) {
      const section = panel?.engagementPanelSectionListRenderer;
      const params =
        section?.content?.continuationItemRenderer?.continuationEndpoint
          ?.getTranscriptEndpoint?.params;
      if (params) return params;
    }
    return null;
  }

  function findTranscriptParams() {
    return (
      extractParamsFromPanels(getPlayerResponse()?.engagementPanels) ||
      extractParamsFromPanels(window.ytInitialData?.engagementPanels)
    );
  }

  async function innertubePost(endpoint, body) {
    const apiKey = getApiKey();
    const url = `/youtubei/v1/${endpoint}?prettyPrint=false${
      apiKey ? `&key=${encodeURIComponent(apiKey)}` : ""
    }`;
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${endpoint} HTTP ${r.status}`);
    return r.json();
  }

  async function fetchTranscriptParamsViaNext(videoId) {
    const data = await innertubePost("next", {
      context: { client: { clientName: "WEB", clientVersion: getClientVersion(), hl: "en" } },
      videoId,
    });
    return extractParamsFromPanels(data?.engagementPanels);
  }

  function fillDurations(segments) {
    for (let i = 0; i < segments.length - 1; i++) {
      if (!segments[i].dur) {
        segments[i].dur = Math.max(0.1, segments[i + 1].start - segments[i].start);
      }
    }
    if (segments.length && !segments[segments.length - 1].dur) {
      segments[segments.length - 1].dur = 4;
    }
    return segments;
  }

  function parseGetTranscriptResponse(data) {
    const segments = [];
    for (const action of data?.actions || []) {
      const renderer =
        action?.updateEngagementPanelAction?.content?.transcriptRenderer;
      if (!renderer) continue;
      const body =
        renderer?.body?.transcriptBodyRenderer ||
        renderer?.content?.transcriptSearchPanelRenderer?.body;
      const initialSegments =
        body?.transcriptSegmentListRenderer?.initialSegments || [];
      for (const seg of initialSegments) {
        const r = seg?.transcriptSegmentRenderer;
        if (!r) continue;
        const text =
          (r.snippet?.runs || []).map((x) => x.text).join("") ||
          r.snippet?.simpleText ||
          "";
        const startMs = parseInt(r.startMs || r.startTimeMs || "0", 10);
        if (text.trim()) segments.push({ start: startMs / 1000, dur: 0, text: text.trim() });
      }
    }
    return fillDurations(segments);
  }

  async function fetchViaGetTranscript(params) {
    const data = await innertubePost("get_transcript", {
      context: { client: { clientName: "WEB", clientVersion: getClientVersion(), hl: "en" } },
      params,
    });
    return parseGetTranscriptResponse(data);
  }

  async function fetchViaPlayerApi(videoId) {
    const data = await innertubePost("player", {
      context: { client: { clientName: "ANDROID", clientVersion: "20.10.38", hl: "en" } },
      videoId,
    });
    return data?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
  }

  // ---------- 主流程 ----------

  async function fetchCaptions() {
    const resp = getPlayerResponse();
    if (!resp) return { error: "无法读取播放器数据，请刷新页面后重试。" };
    const videoId = getVideoId(resp);
    const errors = [];

    // 策略 0：拦截播放器已鉴权的 timedtext URL（最稳）
    try {
      const url = await waitForCapturedUrl(7000);
      if (url) {
        const segments = await fetchUrlAsCaptions(url);
        if (segments.length) {
          return { segments, lang: "en", videoId, method: "intercept" };
        }
        errors.push("拦截 URL 解析为空");
      } else {
        errors.push("未捕获到播放器字幕请求（请确认该视频有字幕）");
      }
    } catch (e) {
      errors.push("拦截: " + (e.message || e));
    }

    // 策略 1：get_transcript
    try {
      let params = findTranscriptParams();
      if (!params && videoId) params = await fetchTranscriptParamsViaNext(videoId);
      if (params) {
        const segments = await fetchViaGetTranscript(params);
        if (segments.length) return { segments, lang: "en", videoId, method: "get_transcript" };
        errors.push("get_transcript 返回空内容");
      } else {
        errors.push("未找到 transcript params");
      }
    } catch (e) {
      errors.push("get_transcript: " + (e.message || e));
    }

    // 策略 2：ANDROID player API
    try {
      if (videoId) {
        const tracks = await fetchViaPlayerApi(videoId);
        const track = pickEnglishTrack(tracks);
        if (track?.baseUrl) {
          const segments = await fetchUrlAsCaptions(track.baseUrl);
          if (segments.length)
            return { segments, lang: track.languageCode, videoId, method: "player_api" };
        }
        errors.push("player API 无可用字幕轨");
      }
    } catch (e) {
      errors.push("player API: " + (e.message || e));
    }

    // 策略 3：内嵌 captionTracks
    try {
      const tracks = resp?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
      const track = pickEnglishTrack(tracks);
      if (track?.baseUrl) {
        const segments = await fetchUrlAsCaptions(track.baseUrl);
        if (segments.length)
          return { segments, lang: track.languageCode, videoId, method: "embedded_tracks" };
      }
      errors.push("内嵌字幕轨拉取失败");
    } catch (e) {
      errors.push("内嵌轨: " + (e.message || e));
    }

    return { videoId, error: "浏览器内抓取失败（" + errors.join("；") + "）" };
  }

  window.addEventListener("message", async (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== "ytt" || data.action !== "FETCH_CAPTIONS") return;
    const result = await fetchCaptions();
    window.postMessage(
      { source: "ytt-main", action: "CAPTIONS", reqId: data.reqId, ...result },
      "*"
    );
  });
})();
