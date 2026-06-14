"""YoutubeSubSync 后端：字幕翻译服务（MVP）。

提供 `/captions` 服务端字幕抓取与 `/translate` 批量翻译接口。
扩展优先在浏览器内抓字幕；失败时回退到 `/captions`（youtube-transcript-api）。
后续阶段在此基础上新增 `/ws/asr` 流式语音识别端点（faster-whisper）。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import httpx
import openai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

import config  # noqa: E402
import translation_cache  # noqa: E402
from captions import CaptionsError, fetch_captions  # noqa: E402
from settings_page import SETTINGS_HTML  # noqa: E402
from translator import TranslatorError, get_translator  # noqa: E402

app = FastAPI(title="YoutubeSubSync Backend", version="0.1.0")

# 开发期允许任意来源（扩展 content script 从 youtube.com 发起请求）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 批量大小：一次发给翻译引擎的最大片段数，过大易超时/错位。
BATCH_SIZE = 40


class TranslateRequest(BaseModel):
    segments: List[str]
    mode: Optional[str] = "fragment"  # "fragment" | "sentence"
    video_id: Optional[str] = None  # 传入则启用按视频的服务端缓存


class TranslateResponse(BaseModel):
    translations: List[str]
    cached: int = 0  # 本次命中缓存的条数
    translated: int = 0  # 本次实际调用引擎翻译的条数


class ConfigPayload(BaseModel):
    """配置项；所有字段可选，便于部分更新与“留空保留原值”。"""

    LLM_BASE_URL: Optional[str] = None
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: Optional[str] = None
    TARGET_LANG: Optional[str] = None


class CaptionSegment(BaseModel):
    start: float
    dur: float
    text: str


class CaptionsResponse(BaseModel):
    segments: List[CaptionSegment]
    lang: str
    videoId: str
    isGenerated: bool = False  # True 表示 YouTube 自动生成字幕（ASR）


class CacheMergeRequest(BaseModel):
    entries: Dict[str, str]  # 英文原文 -> 中文译文


@app.get("/captions", response_model=CaptionsResponse)
def captions(video_id: str, lang: Optional[str] = None):
    try:
        langs = [lang] if lang else None
        result = fetch_captions(video_id, langs)
    except CaptionsError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@app.get("/health")
def health():
    llm_key = os.getenv("LLM_API_KEY", "")
    llm_ok = bool(llm_key) and not llm_key.startswith("sk-xxxx")
    return {
        "status": "ok",
        "llm_configured": llm_ok,
        "translate_ready": llm_ok,
        "target_lang": os.getenv("TARGET_LANG", "zh"),
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/settings", response_class=HTMLResponse)
def settings_page():
    """返回简洁的中文配置设置页。"""
    return HTMLResponse(SETTINGS_HTML)


@app.get("/config")
def get_config():
    """读取当前配置（敏感字段已脱敏）。"""
    return config.get_config_masked()


@app.post("/config")
def post_config(payload: ConfigPayload):
    """保存配置：写回 .env 并热更新环境变量，立即生效。"""
    return config.save_config(payload.model_dump())


def _classify_error(exc: Exception) -> str:
    """把异常转成中文可读的错误信息，区分鉴权/连接/超时等。"""
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return "鉴权失败（401/403）：API Key 无效或权限不足"
    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException)):
        return "请求超时：服务地址无响应，请检查网络或 Base URL"
    if isinstance(exc, (openai.APIConnectionError, httpx.ConnectError)):
        return "连接失败：无法访问服务地址，请检查 Base URL 是否正确"
    if isinstance(exc, openai.APIStatusError):
        code = getattr(exc, "status_code", "")
        if code in (401, 403):
            return f"鉴权失败（{code}）：API Key 无效或权限不足"
        return f"服务返回错误（HTTP {code}）：{str(exc)[:200]}"
    if isinstance(exc, TranslatorError):
        msg = str(exc)
        if "401" in msg or "403" in msg:
            return f"鉴权失败：{msg}"
        return msg
    return f"测试失败：{type(exc).__name__}: {str(exc)[:200]}"


@app.post("/config/test")
def test_config(payload: ConfigPayload):
    """用当前/提交的配置做一次最小翻译测试（翻译 ["Hello"]）。"""
    cfg = config.resolve_test_config(payload.model_dump())

    # 临时把待测配置写入环境变量，测试后恢复，避免影响进程现状。
    saved = {k: os.environ.get(k) for k in cfg}
    for key, value in cfg.items():
        os.environ[key] = value
    try:
        translator = get_translator()
        result = translator.translate_batch(["Hello"])
        return {"ok": True, "engine": "llm", "translation": result}
    except Exception as exc:  # 统一转为中文错误，避免 500 崩溃
        return {"ok": False, "engine": "llm", "error": _classify_error(exc)}
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


@app.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest):
    try:
        translator = get_translator()
    except TranslatorError as e:
        raise HTTPException(status_code=503, detail=str(e))

    segments = req.segments
    mode = (req.mode or "fragment").lower()

    # 1) 缓存命中：仅把未命中的片段送去翻译，省 LLM 调用。
    cache_map = translation_cache.load(req.video_id) if req.video_id else {}
    results: List[Optional[str]] = [None] * len(segments)
    todo_idx: List[int] = []
    for i, seg in enumerate(segments):
        hit = cache_map.get(seg)
        if hit:
            results[i] = hit
        else:
            todo_idx.append(i)

    cached_count = len(segments) - len(todo_idx)
    last_error: Optional[str] = None
    new_pairs: dict = {}

    # 2) 未命中的批量翻译，结果回填并写入缓存。
    for b in range(0, len(todo_idx), BATCH_SIZE):
        idx_chunk = todo_idx[b : b + BATCH_SIZE]
        texts = [segments[i] for i in idx_chunk]
        try:
            zh = translator.translate_batch(texts, mode=mode)
        except TranslatorError as e:
            last_error = str(e)
            zh = texts  # 失败回退原文
        for j, i in enumerate(idx_chunk):
            val = zh[j] if j < len(zh) else segments[i]
            results[i] = val
            # 缓存中文译文（与原文不同且含汉字）。
            if req.video_id and val and _should_cache(segments[i], val):
                new_pairs[segments[i]] = val

    if req.video_id and new_pairs:
        try:
            translation_cache.update(req.video_id, new_pairs)
        except ValueError:
            pass  # 非法 video_id：跳过缓存，不影响翻译返回

    final = [r if r is not None else segments[i] for i, r in enumerate(results)]

    # 全部未命中且全部翻译失败时，返回 502 提示。
    if last_error and cached_count == 0 and all(
        r == o for r, o in zip(final, segments)
    ):
        raise HTTPException(status_code=502, detail=last_error)

    return TranslateResponse(
        translations=final,
        cached=cached_count,
        translated=len(todo_idx),
    )


# ---------- 缓存浏览 / 清理 ----------


@app.get("/cache")
def cache_list():
    """列出所有已缓存视频的概要与全局统计。"""
    return {"stats": translation_cache.stats(), "videos": translation_cache.list_videos()}


def _should_cache(src: str, dst: str) -> bool:
    """判断是否应写入缓存：译文与原文不同且含中文。"""
    if not dst or dst.strip() == src.strip():
        return False
    return any("\u4e00" <= c <= "\u9fff" for c in dst)


@app.post("/cache/{video_id}")
def cache_merge(video_id: str, req: CacheMergeRequest):
    """合并写入某视频的翻译缓存（扩展端同步用）。"""
    filtered = {k: v for k, v in req.entries.items() if _should_cache(k, v)}
    if not filtered:
        return {"ok": True, "videoId": video_id, "count": len(translation_cache.load(video_id)), "added": 0}
    try:
        count = translation_cache.update(video_id, filtered)
        return {"ok": True, "videoId": video_id, "count": count, "added": len(filtered)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/cache/{video_id}")
def cache_view(video_id: str):
    """查看单个视频的全部缓存条目（英文 -> 中文）。"""
    entries = translation_cache.get_entries(video_id)
    return {"videoId": video_id, "count": len(entries), "entries": entries}


@app.delete("/cache/{video_id}")
def cache_delete(video_id: str):
    """清除单个视频缓存。"""
    ok = translation_cache.clear_video(video_id)
    return {"ok": ok, "videoId": video_id}


@app.delete("/cache")
def cache_clear_all():
    """清除全部缓存。"""
    n = translation_cache.clear_all()
    return {"ok": True, "removed": n}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
