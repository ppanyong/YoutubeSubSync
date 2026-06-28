"""YoutubeSubSync 后端：字幕翻译服务（MVP）。

提供 `/captions` 服务端字幕抓取与 `/translate` 批量翻译接口。
扩展优先在浏览器内抓字幕；失败时回退到 `/captions`（youtube-transcript-api）。
后续阶段在此基础上新增 `/ws/asr` 流式语音识别端点（faster-whisper）。
"""

from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional

import httpx
import openai
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

import config  # noqa: E402
import content_summary  # noqa: E402
import translation_cache  # noqa: E402
from translation_quality import translation_plausible, translation_valid  # noqa: E402
from captions import CaptionsError, fetch_captions  # noqa: E402
from settings_page import SETTINGS_HTML  # noqa: E402
from summary_page import render_article_page  # noqa: E402
import subtitle  # noqa: E402
from translator import TranslatorError, get_translator  # noqa: E402

# 上下文完整重译时每块句子数（比实时翻译块更大，利于连贯）。
CONTEXT_BATCH_SIZE = 8

_retranslate_jobs: Dict[str, dict] = {}
_retranslate_lock = threading.Lock()

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
    mode: Optional[str] = "line"  # line=逐条翻译（推荐）；legacy: context/sentence/fragment
    video_id: Optional[str] = None
    context_before: Optional[List[str]] = None  # 前文英文
    context_zh_before: Optional[List[str]] = None  # 前文已有译文（与 context_before 对齐）


class TranslateResponse(BaseModel):
    translations: List[str]
    cached: int = 0  # 本次命中缓存的条数
    translated: int = 0  # 本次实际调用引擎翻译的条数


class ValidatePair(BaseModel):
    src: str
    dst: str
    peers: Optional[List[str]] = None


class ValidateRequest(BaseModel):
    pairs: List[ValidatePair]


class ValidateResponse(BaseModel):
    results: List[bool]


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


class SummaryPhrase(BaseModel):
    text: Optional[str] = ""
    zh: Optional[str] = ""
    start: Optional[float] = None
    end: Optional[float] = None


class CacheMergeRequest(BaseModel):
    entries: Dict[str, str] = {}  # 英文原文 -> 中文译文
    phrases: Optional[List[SummaryPhrase]] = None  # 有序句子（含时间戳）
    caption_fingerprint: Optional[str] = None  # 字幕轨指纹，变更时迁移可保留的译文


class RetranslateRequest(BaseModel):
    force: bool = False
    mode: Optional[str] = "line"


class SummaryGenerateRequest(BaseModel):
    phrases: Optional[List[SummaryPhrase]] = None
    total_phrases: Optional[int] = None
    translated_phrases: Optional[int] = None
    force: bool = False


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
    mode = (req.mode or "line").lower()

    # 1) 缓存命中
    cache_map = translation_cache.load(req.video_id) if req.video_id else {}
    results: List[Optional[str]] = [None] * len(segments)
    todo_idx: List[int] = []
    for i, seg in enumerate(segments):
        hit = cache_map.get(seg)
        peers = [s for j, s in enumerate(segments) if j != i]
        if hit and translation_valid(seg, hit, peers):
            results[i] = hit
        else:
            todo_idx.append(i)

    cached_count = len(segments) - len(todo_idx)
    last_error: Optional[str] = None
    new_pairs: dict = {}

    # 2) 未命中的批量翻译，结果回填并写入缓存。
    ctx_en = req.context_before
    ctx_zh = req.context_zh_before
    for b in range(0, len(todo_idx), BATCH_SIZE):
        idx_chunk = todo_idx[b : b + BATCH_SIZE]
        texts = [segments[i] for i in idx_chunk]
        try:
            zh = translator.translate_batch(
                texts,
                mode=mode,
                context_before=ctx_en,
                context_zh_before=ctx_zh,
            )
        except TranslatorError as e:
            last_error = str(e)
            zh = texts
        ctx_en = (list(ctx_en or []) + texts)[-6:]
        ctx_zh = (
            list(ctx_zh or [])
            + [z if z != texts[k] else "" for k, z in enumerate(zh)]
        )[-6:]
        for j, i in enumerate(idx_chunk):
            val = zh[j] if j < len(zh) else segments[i]
            results[i] = val
            peer_pairs = [
                (segments[k], (results[k] or "") if results[k] != segments[k] else "")
                for k in range(len(segments))
                if k != i
            ]
            peers = [p[0] for p in peer_pairs]
            if req.video_id and val and _should_cache(segments[i], val, peers, peer_pairs):
                new_pairs[segments[i]] = val

    if req.video_id and new_pairs:
        try:
            phrases = translation_cache.load_phrases(req.video_id)
            if phrases:
                allowed = translation_cache._phrase_text_set(phrases)
                new_pairs = translation_cache.filter_to_phrases(new_pairs, allowed)
                if new_pairs:
                    for p in phrases:
                        t = p.get("text", "")
                        if t in new_pairs:
                            p["zh"] = new_pairs[t]
                    translation_cache.save_phrases(req.video_id, phrases)
            elif new_pairs:
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


@app.post("/translate/validate", response_model=ValidateResponse)
def validate_translations(req: ValidateRequest):
    """批量校验译文是否与对应英文字幕对齐（领域无关启发式，单一真相源）。"""
    results = [
        translation_valid(p.src, p.dst, p.peers or []) for p in (req.pairs or [])
    ]
    return ValidateResponse(results=results)


# ---------- 缓存浏览 / 清理 ----------


@app.get("/cache")
def cache_list():
    """列出所有已缓存视频的概要与全局统计。"""
    maintenance = translation_cache.reconcile_all()
    return {
        "stats": translation_cache.stats(),
        "videos": translation_cache.list_videos(),
        "maintenance": maintenance,
    }


@app.get("/cache/{video_id}/integrity")
def cache_integrity(video_id: str):
    """检查某视频缓存数据一致性。"""
    translation_cache.reconcile(video_id)
    return {"videoId": video_id, **translation_cache.integrity(video_id)}


def _should_cache(
    src: str,
    dst: str,
    peer_srcs: Optional[List[str]] = None,
    peer_pairs: Optional[List[tuple]] = None,
) -> bool:
    """判断是否应写入缓存。"""
    if not translation_valid(src, dst, peer_srcs, peer_pairs=peer_pairs):
        return False
    return any("\u4e00" <= c <= "\u9fff" for c in dst)


@app.post("/cache/{video_id}")
def cache_merge(video_id: str, req: CacheMergeRequest):
    """合并写入某视频的翻译缓存（扩展端同步用）。"""
    filtered = {k: v for k, v in (req.entries or {}).items() if _should_cache(k, v)}
    phrase_list = None
    if req.phrases:
        phrase_list = [
            {
                "start": p.start or 0,
                "end": p.end or 0,
                "text": p.text or "",
                "zh": p.zh or filtered.get(p.text or "", ""),
            }
            for p in req.phrases
            if p.text
        ]
    if not filtered and not phrase_list:
        return {
            "ok": True,
            "videoId": video_id,
            "count": len(translation_cache.load(video_id)),
            "added": 0,
        }
    try:
        count = translation_cache.update(
            video_id,
            filtered,
            phrases=phrase_list,
            caption_fingerprint=req.caption_fingerprint,
        )
        return {"ok": True, "videoId": video_id, "count": count, "added": len(filtered)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/cache/{video_id}/subtitle")
def cache_subtitle(video_id: str, format: str = "text"):
    """按时间顺序组装完整字幕（text | srt | bilingual）。"""
    try:
        phrases, source = subtitle.get_ordered_phrases(video_id)
    except CaptionsError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not phrases:
        raise HTTPException(status_code=404, detail="暂无字幕数据")
    stats = subtitle.phrase_stats(phrases)
    fmt = (format or "text").lower()
    if fmt == "srt":
        body = subtitle.phrases_to_srt(phrases)
    elif fmt == "bilingual":
        body = subtitle.phrases_to_srt(phrases, bilingual=True)
    elif fmt == "en":
        body = subtitle.phrases_to_text(phrases, lang="en")
    else:
        body = subtitle.phrases_to_text(phrases, lang="zh")
    return {
        "videoId": video_id,
        "source": source,
        "stats": stats,
        "format": fmt,
        "body": body,
        "phrases": phrases,
    }


def _run_retranslate_job(video_id: str, force: bool, mode: str) -> None:
    with _retranslate_lock:
        _retranslate_jobs[video_id] = {"status": "running", "translated": 0, "total": 0}
    try:
        translator = get_translator()
        phrases, _ = subtitle.get_ordered_phrases(video_id)
        if not phrases:
            raise TranslatorError("暂无字幕数据")

        todo_idx = [
            i
            for i, p in enumerate(phrases)
            if force or not (p.get("zh") or "").strip()
        ]
        with _retranslate_lock:
            _retranslate_jobs[video_id]["total"] = len(todo_idx)

        if not todo_idx:
            with _retranslate_lock:
                _retranslate_jobs[video_id] = {
                    "status": "done",
                    "translated": 0,
                    "total": 0,
                    "stats": subtitle.phrase_stats(phrases),
                    "message": "已全部翻译，无需重译",
                }
            return

        translated_count = 0
        last_error: Optional[str] = None

        for b in range(0, len(todo_idx), CONTEXT_BATCH_SIZE):
            idx_chunk = todo_idx[b : b + CONTEXT_BATCH_SIZE]
            first = idx_chunk[0]
            ctx_en = [phrases[j]["text"] for j in range(max(0, first - 3), first)]
            ctx_zh = [
                phrases[j].get("zh") or ""
                for j in range(max(0, first - 3), first)
            ]
            texts = [phrases[i]["text"] for i in idx_chunk]
            try:
                zh_list = translator.translate_batch(
                    texts,
                    mode=mode or "line",
                    context_before=ctx_en,
                    context_zh_before=ctx_zh,
                )
            except TranslatorError as e:
                last_error = str(e)
                zh_list = texts
            for j, i in enumerate(idx_chunk):
                val = zh_list[j] if j < len(zh_list) else phrases[i]["text"]
                peer_pairs = [
                    (phrases[k]["text"], phrases[k].get("zh") or "")
                    for k in range(len(phrases))
                    if k != i and phrases[k].get("text")
                ]
                peers = [p[0] for p in peer_pairs]
                if _should_cache(phrases[i]["text"], val, peers, peer_pairs):
                    phrases[i]["zh"] = val
                    translated_count += 1
            with _retranslate_lock:
                _retranslate_jobs[video_id]["translated"] = translated_count

        translation_cache.save_phrases(video_id, phrases)
        result = {
            "status": "done",
            "translated": translated_count,
            "total": len(todo_idx),
            "stats": subtitle.phrase_stats(phrases),
        }
        if last_error and translated_count == 0:
            result["status"] = "failed"
            result["error"] = last_error
        with _retranslate_lock:
            _retranslate_jobs[video_id] = result
    except Exception as e:
        with _retranslate_lock:
            _retranslate_jobs[video_id] = {"status": "failed", "error": str(e)}


@app.post("/cache/{video_id}/retranslate")
def cache_retranslate(
    video_id: str, req: RetranslateRequest, background_tasks: BackgroundTasks
):
    """对整段字幕做上下文块翻译，后台异步执行（设置页「完整重译」）。"""
    try:
        get_translator()
    except TranslatorError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        phrases, _ = subtitle.get_ordered_phrases(video_id)
    except CaptionsError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not phrases:
        raise HTTPException(status_code=404, detail="暂无字幕数据")

    with _retranslate_lock:
        job = _retranslate_jobs.get(video_id)
        if job and job.get("status") == "running":
            return {"ok": True, "videoId": video_id, "status": "running"}

    mode = (req.mode or "context").lower()
    background_tasks.add_task(_run_retranslate_job, video_id, req.force, mode)
    return {"ok": True, "videoId": video_id, "status": "running"}


@app.get("/cache/{video_id}/retranslate/status")
def cache_retranslate_status(video_id: str):
    with _retranslate_lock:
        job = _retranslate_jobs.get(video_id)
    if not job:
        return {"videoId": video_id, "status": "idle"}
    return {"videoId": video_id, **job}


@app.get("/cache/{video_id}")
def cache_view(video_id: str):
    """查看单个视频的有序句子与缓存统计（与完整字幕一致）。"""
    translation_cache.reconcile(video_id)
    entries = translation_cache.get_entries(video_id)
    try:
        phrases, source = subtitle.get_ordered_phrases(video_id, reconcile=False)
    except CaptionsError:
        phrases = translation_cache.load_phrases(video_id)
        source = "stored" if phrases else "cache_only"
    stats = subtitle.phrase_stats(phrases) if phrases else {
        "total": len(entries),
        "translated": len(entries),
        "missing": 0,
    }
    return {
        "videoId": video_id,
        "count": stats["total"],
        "entryCount": len(entries),
        "entries": entries,
        "phrases": phrases,
        "stats": stats,
        "source": source,
    }


@app.delete("/cache/{video_id}")
def cache_delete(video_id: str):
    """清除单个视频缓存。"""
    ok = translation_cache.clear_video(video_id)
    content_summary.delete_summary(video_id)
    return {"ok": ok, "videoId": video_id}


@app.delete("/cache")
def cache_clear_all():
    """清除全部缓存。"""
    n = translation_cache.clear_all()
    for s in content_summary.list_summaries():
        content_summary.delete_summary(s["videoId"])
    return {"ok": True, "removed": n}


# ---------- 内容小结 ----------


def _run_summary_job(
    video_id: str,
    phrases: Optional[List[dict]],
    total_phrases: Optional[int],
    translated_phrases: Optional[int],
    force: bool,
) -> None:
    try:
        content_summary.generate(
            video_id,
            phrases=phrases,
            total_phrases=total_phrases,
            translated_phrases=translated_phrases,
            force=force,
        )
    except content_summary.SummaryError as e:
        # 错误已写入 summaries JSON，无需再抛。
        pass


@app.get("/summaries")
def summaries_list():
    """列出所有已生成（或生成中）的内容小结。"""
    return {"summaries": content_summary.list_summaries()}


@app.get("/summary/{video_id}")
def summary_get(video_id: str):
    """获取某视频小结元数据与 Markdown 正文。"""
    data = content_summary.load(video_id)
    if not data:
        raise HTTPException(status_code=404, detail="暂无内容小结")
    return data


@app.get("/summary/{video_id}/article", response_class=HTMLResponse)
def summary_article(video_id: str):
    """渲染可阅读的文章页。"""
    data = content_summary.load(video_id)
    if not data or data.get("status") != "ready" or not data.get("markdown"):
        raise HTTPException(status_code=404, detail="小结尚未生成或生成失败")
    return HTMLResponse(
        render_article_page(
            video_id=video_id,
            title=data.get("title") or "",
            markdown=data.get("markdown") or "",
            entry_count=data.get("entryCount", 0),
            updated=data.get("updatedAt"),
        )
    )


@app.post("/summary/{video_id}/generate")
def summary_generate(
    video_id: str,
    req: SummaryGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """触发内容小结生成（后台异步）。扩展在翻译全部完成后调用。"""
    existing = content_summary.load(video_id)
    if (
        existing
        and existing.get("status") == "generating"
        and not req.force
    ):
        return {"ok": True, "videoId": video_id, "status": "generating"}

    phrases = (
        [p.model_dump() for p in req.phrases] if req.phrases else None
    )
    # 同步校验：条数过少或未完成时直接 400。
    try:
        line_count = content_summary.validate_generate_request(
            video_id,
            phrases=phrases,
            total_phrases=req.total_phrases,
            translated_phrases=req.translated_phrases,
        )
    except content_summary.SummaryError as e:
        raise HTTPException(status_code=400, detail=str(e))

    content_summary.mark_generating(video_id, line_count)
    background_tasks.add_task(
        _run_summary_job,
        video_id,
        phrases,
        req.total_phrases,
        req.translated_phrases,
        req.force,
    )
    return {"ok": True, "videoId": video_id, "status": "generating"}


@app.delete("/summary/{video_id}")
def summary_delete(video_id: str):
    ok = content_summary.delete_summary(video_id)
    return {"ok": ok, "videoId": video_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
