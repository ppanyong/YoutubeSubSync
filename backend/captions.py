"""服务端字幕抓取：使用 youtube-transcript-api（内部走 ANDROID 客户端，
规避 YouTube 对 WEB 客户端的 BotGuard/POT 限制）。

浏览器内抓取失败时由此兜底。后端与浏览器同 IP，成功率最高。
"""

from __future__ import annotations

from typing import List, Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


class CaptionsError(Exception):
    pass


# 优先英文（含各地区变体），其次任意可翻译语言。
_PREFERRED_LANGS = ["en", "en-US", "en-GB"]


def fetch_captions(video_id: str, languages: Optional[List[str]] = None) -> dict:
    if not video_id:
        raise CaptionsError("缺少 video_id")

    api = YouTubeTranscriptApi()
    langs = languages or _PREFERRED_LANGS

    try:
        fetched, is_generated = _fetch_best(api, video_id, langs)
    except (TranscriptsDisabled, NoTranscriptFound):
        raise CaptionsError("该视频没有可用字幕（含自动生成字幕）")
    except VideoUnavailable:
        raise CaptionsError("视频不可用")
    except Exception as e:
        raise CaptionsError(f"抓取字幕失败：{e}")

    segments = [
        {"start": s.start, "dur": s.duration, "text": s.text.replace("\n", " ").strip()}
        for s in fetched.snippets
        if s.text.strip()
    ]
    if not segments:
        raise CaptionsError("字幕内容为空")

    return {
        "segments": segments,
        "lang": fetched.language_code,
        "videoId": video_id,
        "isGenerated": is_generated,  # True = YouTube 自动生成（ASR）
    }


def _fetch_best(api: YouTubeTranscriptApi, video_id: str, langs: List[str]):
    """优先英文；含自动生成字幕（ASR）。返回 (FetchedTranscript, is_generated)。"""
    transcript_list = api.list(video_id)

    # 1. 人工英文字幕
    try:
        t = transcript_list.find_manually_created_transcript(langs)
        return t.fetch(), False
    except NoTranscriptFound:
        pass

    # 2. 自动英文字幕（ASR）—— 多数视频只有这一种
    try:
        t = transcript_list.find_generated_transcript(langs)
        return t.fetch(), True
    except NoTranscriptFound:
        pass

    # 3. 任意语言的人工字幕
    for t in transcript_list:
        if not t.is_generated:
            try:
                return t.fetch(), False
            except Exception:
                continue

    # 4. 任意语言的自动生成字幕
    for t in transcript_list:
        if t.is_generated:
            try:
                return t.fetch(), True
            except Exception:
                continue

    raise NoTranscriptFound(video_id, langs, transcript_list)
