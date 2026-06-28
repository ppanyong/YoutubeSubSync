"""字幕组装：碎片合并为句子、与缓存对齐、导出完整字幕。"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import translation_cache
from captions import CaptionsError, fetch_captions

SENTENCE_END = re.compile(r'[.!?…]["\']?\s*$')
MAX_PHRASE_CHARS = 64
MAX_PHRASE_FRAGS = 6
MAX_PHRASE_DUR = 6.0
PHRASE_GAP_SEC = 0.8


def build_phrases(segments: List[dict]) -> List[dict]:
    """将 YouTube 碎片字幕合并为完整句子（与扩展端 buildPhrases 逻辑一致）。"""
    phrases: List[dict] = []
    buf: Optional[dict] = None

    def flush() -> None:
        nonlocal buf
        if not buf or not buf["indices"]:
            return
        phrases.append(
            {
                "start": buf["start"],
                "end": buf["end"],
                "text": " ".join(buf["texts"]).replace("  ", " ").strip(),
                "zh": "",
                "indices": buf["indices"],
            }
        )
        buf = None

    for i, seg in enumerate(segments):
        prev = segments[i - 1] if i > 0 else None
        gap = (
            seg["start"] - (prev["start"] + (prev.get("dur") or 0))
            if prev
            else 0.0
        )

        if buf:
            joined = " ".join(buf["texts"])
            dur = seg["start"] + (seg.get("dur") or 2) - buf["start"]
            hit_limit = (
                len(buf["indices"]) >= MAX_PHRASE_FRAGS
                or len(joined) + len(seg["text"]) > MAX_PHRASE_CHARS
                or dur > MAX_PHRASE_DUR
                or gap > PHRASE_GAP_SEC
            )
            prev_ended = bool(
                buf["texts"]
                and SENTENCE_END.search(buf["texts"][-1].strip())
            )
            if hit_limit or prev_ended:
                flush()

        if not buf:
            buf = {
                "start": seg["start"],
                "end": seg["start"] + (seg.get("dur") or 2),
                "texts": [],
                "indices": [],
            }
        buf["texts"].append(seg["text"])
        buf["indices"].append(i)
        buf["end"] = seg["start"] + (seg.get("dur") or 2)

    flush()
    return phrases


def _apply_cache(phrases: List[dict], entries: Dict[str, str]) -> None:
    from translation_quality import translation_plausible

    for p in phrases:
        hit = entries.get(p["text"])
        if hit and translation_plausible(p["text"], hit):
            p["zh"] = hit


def get_ordered_phrases(
    video_id: str,
    *,
    fetch_if_missing: bool = True,
    reconcile: bool = True,
) -> tuple[List[dict], str]:
    """获取按时间排序的句子列表，并合并缓存译文。

    返回 (phrases, source)，source 为 "stored" | "rebuilt" | "cache_only"。
    """
    if reconcile and translation_cache.load_phrases(video_id):
        translation_cache.reconcile(video_id)

    stored = translation_cache.load_phrases(video_id)
    entries = translation_cache.load(video_id)

    if stored:
        phrases = [dict(p) for p in stored]
        _apply_cache(phrases, entries)
        return phrases, "stored"

    if not fetch_if_missing:
        if entries:
            phrases = [{"text": k, "zh": v, "start": 0.0, "end": 0.0} for k, v in entries.items()]
            return phrases, "cache_only"
        return [], "cache_only"

    try:
        cap = fetch_captions(video_id)
    except CaptionsError:
        if entries:
            phrases = [{"text": k, "zh": v, "start": 0.0, "end": 0.0} for k, v in entries.items()]
            return phrases, "cache_only"
        raise

    phrases = build_phrases(cap["segments"])
    _apply_cache(phrases, entries)
    return phrases, "rebuilt"


def format_srt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def phrases_to_srt(phrases: List[dict], *, bilingual: bool = False) -> str:
    """导出 SRT 格式字幕。"""
    lines: List[str] = []
    for i, p in enumerate(phrases, 1):
        start = p.get("start", 0.0)
        end = p.get("end", start + 2.0)
        zh = (p.get("zh") or "").strip()
        en = (p.get("text") or "").strip()
        body = zh if zh else en
        if bilingual and zh and en:
            body = f"{zh}\n{en}"
        if not body:
            continue
        lines.append(str(i))
        lines.append(f"{format_srt_time(start)} --> {format_srt_time(end)}")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


def phrases_to_text(phrases: List[dict], *, lang: str = "zh") -> str:
    """导出连续文本（默认中文，无译文则回退英文）。"""
    parts: List[str] = []
    for p in phrases:
        if lang == "en":
            t = (p.get("text") or "").strip()
        else:
            t = (p.get("zh") or p.get("text") or "").strip()
        if t:
            parts.append(t)
    return "\n".join(parts)


def phrase_stats(phrases: List[dict]) -> dict:
    total = len(phrases)
    translated = sum(1 for p in phrases if (p.get("zh") or "").strip())
    return {"total": total, "translated": translated, "missing": total - translated}
