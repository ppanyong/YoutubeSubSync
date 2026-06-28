"""内容小结：基于已翻译字幕生成深度文章式小结。

- 每个视频一个 JSON：backend/summaries/<videoId>.json
- 扩展在翻译全部完成后可触发 POST /summary/{id}/generate
- 也可在后台设置页手动生成 / 查看文章
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI

import subtitle
import translation_cache
from translator import TranslatorError

BASE_DIR = Path(__file__).resolve().parent
SUMMARY_DIR = BASE_DIR / "summaries"

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_lock = threading.Lock()

# 单次送入模型的字幕上限（字符），超出则分段摘要再合并。
_MAX_INPUT_CHARS = 14000
_CHUNK_CHARS = 6000


class SummaryError(Exception):
    pass


def _ensure_dir() -> None:
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)


def _safe_id(video_id: str) -> str:
    vid = (video_id or "").strip()
    if not _SAFE_ID.match(vid):
        raise ValueError("非法的 video_id")
    return vid


def _path(video_id: str) -> Path:
    return SUMMARY_DIR / f"{_safe_id(video_id)}.json"


def load(video_id: str) -> Optional[dict]:
    try:
        p = _path(video_id)
    except ValueError:
        return None
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write(video_id: str, payload: dict) -> dict:
    _ensure_dir()
    with _lock:
        p = _path(video_id)
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return payload


def list_summaries() -> List[dict]:
    _ensure_dir()
    items = []
    for p in sorted(SUMMARY_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            stat = p.stat()
            items.append(
                {
                    "videoId": data.get("videoId", p.stem),
                    "status": data.get("status", "unknown"),
                    "title": data.get("title") or "",
                    "entryCount": data.get("entryCount", 0),
                    "updated": int(data.get("updatedAt") or stat.st_mtime),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    items.sort(key=lambda x: x["updated"], reverse=True)
    return items


def delete_summary(video_id: str) -> bool:
    try:
        p = _path(video_id)
    except ValueError:
        return False
    with _lock:
        if p.exists():
            p.unlink()
            return True
    return False


def _get_llm_client() -> tuple[OpenAI, str]:
    import os

    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    if not api_key or api_key.startswith("sk-xxxx"):
        raise SummaryError("未配置有效的 LLM_API_KEY")
    return OpenAI(api_key=api_key, base_url=base_url), model


def _call_llm(system: str, user: str, max_tokens: int = 4096) -> str:
    client, model = _get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
    except AuthenticationError as e:
        raise SummaryError(f"API Key 无效：{e.message}") from e
    except APIConnectionError as e:
        raise SummaryError(f"无法连接大模型服务：{e}") from e
    except APIStatusError as e:
        raise SummaryError(f"大模型返回错误 {e.status_code}：{e.message}") from e
    return (resp.choices[0].message.content or "").strip()


def _build_transcript(
    phrases: Optional[List[dict]] = None, video_id: Optional[str] = None
) -> tuple[str, int]:
    """从有序句对或缓存构建中文字幕全文。返回 (正文, 句数)。"""
    lines: List[str] = []
    if phrases:
        for p in phrases:
            zh = (p.get("zh") or "").strip()
            if zh:
                lines.append(zh)
    elif video_id:
        try:
            phrases, _ = subtitle.get_ordered_phrases(video_id, fetch_if_missing=False)
            if phrases:
                for p in phrases:
                    zh = (p.get("zh") or "").strip()
                    if zh:
                        lines.append(zh)
            else:
                entries = translation_cache.get_entries(video_id)
                for zh in entries.values():
                    z = (zh or "").strip()
                    if z:
                        lines.append(z)
        except Exception:
            entries = translation_cache.get_entries(video_id)
            for zh in entries.values():
                z = (zh or "").strip()
                if z:
                    lines.append(z)
    text = "\n".join(lines)
    return text, len(lines)


def _chunk_text(text: str, size: int) -> List[str]:
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # 尽量在句号/换行处切断。
            cut = text.rfind("\n", start, end)
            if cut <= start:
                cut = text.rfind("。", start, end)
            if cut <= start:
                cut = text.rfind(".", start, end)
            if cut > start:
                end = cut + 1
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


def _summarize_chunk(chunk: str, part_idx: int, total: int) -> str:
    system = (
        "你是资深内容分析师。请阅读以下视频字幕片段（中文），提炼该段的核心信息。"
        "输出 3-6 条要点，每条一行，用「- 」开头。不要编造字幕中没有的内容。"
    )
    user = f"这是第 {part_idx}/{total} 段字幕：\n\n{chunk}"
    return _call_llm(system, user, max_tokens=1200)


def _merge_to_article(chunk_notes: List[str], transcript_sample: str) -> str:
    joined = "\n\n".join(
        f"### 分段要点 {i + 1}\n{n}" for i, n in enumerate(chunk_notes)
    )
    system = (
        "你是擅长写深度内容解读的专栏作者。根据视频字幕要点，写一篇结构完整、有洞察力的中文文章。\n"
        "要求：\n"
        "1) 使用 Markdown 格式；\n"
        "2) 包含一级标题（# ）、导语、3-5 个小节（## ）、关键洞察（可用列表）、结语；\n"
        "3) 内容要有深度：提炼观点、逻辑脉络、争议或启示，而非简单复述；\n"
        "4) 语气专业但易读，适合快速掌握视频精华；\n"
        "5) 不要输出与字幕无关的臆测，可标注「视频中提到」；\n"
        "6) 全文 800-2000 字。"
    )
    user = (
        "以下是按段提炼的字幕要点：\n\n"
        f"{joined}\n\n"
        "字幕开头片段（供把握语境）：\n"
        f"{transcript_sample[:2000]}"
    )
    return _call_llm(system, user, max_tokens=4096)


def _summarize_direct(transcript: str) -> str:
    system = (
        "你是擅长写深度内容解读的专栏作者。根据以下完整视频字幕（中文），"
        "写一篇结构完整、有洞察力的中文文章。\n"
        "要求：\n"
        "1) 使用 Markdown 格式；\n"
        "2) 包含一级标题（# ）、导语、3-5 个小节（## ）、关键洞察（可用列表）、结语；\n"
        "3) 内容要有深度：提炼观点、逻辑脉络、争议或启示，而非简单复述；\n"
        "4) 语气专业但易读；\n"
        "5) 不要编造字幕中没有的内容；\n"
        "6) 全文 800-2000 字。"
    )
    user = f"视频字幕全文：\n\n{transcript}"
    return _call_llm(system, user, max_tokens=4096)


def _extract_title(markdown: str, video_id: str) -> str:
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return f"视频 {video_id} 内容小结"


def mark_generating(video_id: str, entry_count: int) -> dict:
    """标记为生成中，供 API 层在投递后台任务前调用。"""
    vid = _safe_id(video_id)
    existing = load(vid)
    now = int(time.time())
    return _write(
        vid,
        {
            "videoId": vid,
            "status": "generating",
            "title": (existing or {}).get("title", ""),
            "entryCount": entry_count,
            "createdAt": (existing or {}).get("createdAt", now) if existing else now,
            "updatedAt": now,
            "error": "",
            "markdown": "",
        },
    )


def validate_generate_request(
    video_id: str,
    phrases: Optional[List[dict]] = None,
    total_phrases: Optional[int] = None,
    translated_phrases: Optional[int] = None,
) -> int:
    """校验是否可生成小结，返回字幕句数。"""
    _safe_id(video_id)
    _, line_count = _build_transcript(phrases, video_id)
    if line_count < 3:
        raise SummaryError("字幕条数过少（至少 3 句），无法生成有意义的小结")
    if total_phrases and translated_phrases is not None:
        if translated_phrases < max(1, total_phrases - 1):
            raise SummaryError(
                f"字幕尚未全部翻译完成（{translated_phrases}/{total_phrases}）"
            )
    return line_count


def generate(
    video_id: str,
    *,
    phrases: Optional[List[dict]] = None,
    total_phrases: Optional[int] = None,
    translated_phrases: Optional[int] = None,
    force: bool = False,
) -> dict:
    """生成或重新生成某视频的内容小结。同步执行（由 API 层放后台任务）。"""
    vid = _safe_id(video_id)
    existing = load(vid)

    if not force and existing:
        st = existing.get("status")
        if st == "generating":
            return existing
        if st == "ready":
            old_count = existing.get("entryCount", 0)
            new_count = translated_phrases or (phrases and len(phrases)) or 0
            if new_count and old_count and new_count <= old_count:
                return existing

    transcript, line_count = _build_transcript(phrases, vid)
    if line_count < 3:
        raise SummaryError("字幕条数过少（至少 3 句），无法生成有意义的小结")

    # 若扩展上报了完成度，要求全部译完（允许 1 句误差）。
    if total_phrases and translated_phrases is not None:
        if translated_phrases < max(1, total_phrases - 1):
            raise SummaryError(
                f"字幕尚未全部翻译完成（{translated_phrases}/{total_phrases}）"
            )

    now = int(time.time())
    _write(
        vid,
        {
            "videoId": vid,
            "status": "generating",
            "title": existing.get("title", "") if existing else "",
            "entryCount": line_count,
            "createdAt": existing.get("createdAt", now) if existing else now,
            "updatedAt": now,
            "error": "",
            "markdown": "",
        },
    )

    try:
        if len(transcript) <= _MAX_INPUT_CHARS:
            markdown = _summarize_direct(transcript)
        else:
            chunks = _chunk_text(transcript, _CHUNK_CHARS)
            notes = [
                _summarize_chunk(c, i + 1, len(chunks)) for i, c in enumerate(chunks)
            ]
            markdown = _merge_to_article(notes, transcript)

        title = _extract_title(markdown, vid)
        payload = {
            "videoId": vid,
            "status": "ready",
            "title": title,
            "entryCount": line_count,
            "createdAt": existing.get("createdAt", now) if existing else now,
            "updatedAt": int(time.time()),
            "error": "",
            "markdown": markdown,
        }
        return _write(vid, payload)
    except (SummaryError, TranslatorError) as e:
        _write(
            vid,
            {
                "videoId": vid,
                "status": "failed",
                "title": "",
                "entryCount": line_count,
                "createdAt": existing.get("createdAt", now) if existing else now,
                "updatedAt": int(time.time()),
                "error": str(e),
                "markdown": "",
            },
        )
        raise
