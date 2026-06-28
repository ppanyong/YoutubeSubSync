"""翻译缓存：按视频 ID 持久化翻译数据。

数据模型（schema v2）：
- **phrases**（主数据）：按时间排序的句子 [{start, end, text, zh}, ...]
- **entries**（派生索引）：由 phrases 自动生成的 {英文: 译文}，仅供 /translate 快速命中
- **captionFingerprint**：字幕轨指纹，用于检测 YouTube 更新字幕后使旧缓存失效

设计原则：phrases 是唯一真相源；entries 不得独立增长，否则会出现「条目 vs 完整字幕」不一致。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set

from translation_quality import translation_plausible, translation_valid
from translation_meta import is_meta_garbage

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
CACHE_SCHEMA_VERSION = 2

# videoId 安全字符校验，避免路径穿越。
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_lock = threading.Lock()


def _ensure_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_id(video_id: str) -> str:
    vid = (video_id or "").strip()
    if not _SAFE_ID.match(vid):
        raise ValueError("非法的 video_id")
    return vid


def _path(video_id: str) -> Path:
    return CACHE_DIR / f"{_safe_id(video_id)}.json"


def _read_raw(video_id: str) -> dict:
    try:
        p = _path(video_id)
    except ValueError:
        return {}
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load(video_id: str) -> Dict[str, str]:
    """读取某视频的缓存映射；不存在返回空字典。"""
    data = _read_raw(video_id)
    entries = data.get("entries", {})
    return entries if isinstance(entries, dict) else {}


def load_phrases(video_id: str) -> List[dict]:
    """读取已保存的有序句子列表（含时间戳与译文）。"""
    data = _read_raw(video_id)
    phrases = data.get("phrases", [])
    if not isinstance(phrases, list):
        return []
    out: List[dict] = []
    for p in phrases:
        if isinstance(p, dict) and p.get("text"):
            out.append(
                {
                    "start": float(p.get("start") or 0),
                    "end": float(p.get("end") or 0),
                    "text": str(p["text"]),
                    "zh": str(p.get("zh") or ""),
                }
            )
    return out


def _phrase_text_set(phrases: List[dict]) -> Set[str]:
    return {(p.get("text") or "").strip() for p in phrases if (p.get("text") or "").strip()}


def filter_to_phrases(
    mapping: Dict[str, str], phrase_texts: Set[str]
) -> Dict[str, str]:
    """丢弃不属于当前句子表的键（防止过期 entries 写入）。"""
    if not phrase_texts:
        return dict(mapping or {})
    return {
        k: v
        for k, v in (mapping or {}).items()
        if (k or "").strip() in phrase_texts and v
    }


def caption_fingerprint(segments: List[dict]) -> str:
    """字幕轨指纹：片段数 + 首尾内容，用于检测 YouTube 更新字幕。"""
    if not segments:
        return ""
    parts = [str(len(segments))]
    for s in segments[:20]:
        parts.append(f"{float(s.get('start', 0)):.3f}:{(s.get('text') or '').strip()}")
    parts.append((segments[-1].get("text") or "").strip())
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def integrity(video_id: str) -> dict:
    """检查 entries 与 phrases 是否一致。"""
    data = _read_raw(video_id)
    entries = data.get("entries", {})
    phrases = data.get("phrases", [])
    if not isinstance(entries, dict):
        entries = {}
    if not isinstance(phrases, list):
        phrases = []
    phrase_texts = _phrase_text_set(phrases)
    orphan_entries = (
        [k for k in entries if k not in phrase_texts] if phrase_texts else []
    )
    missing_zh = sum(
        1
        for p in phrases
        if isinstance(p, dict)
        and (p.get("text") or "").strip()
        and not (p.get("zh") or entries.get(p.get("text"), "")).strip()
    )
    return {
        "ok": len(orphan_entries) == 0
        and (not phrase_texts or len(entries) <= len(phrase_texts)),
        "phraseCount": len(phrases),
        "entryCount": len(entries),
        "orphanEntries": len(orphan_entries),
        "missingTranslation": missing_zh,
        "schemaVersion": data.get("schemaVersion", 1),
        "captionFingerprint": data.get("captionFingerprint", ""),
    }


def _entries_from_phrases(
    phrases: List[dict], extra: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """从有序句子重建 entries，丢弃不合理/错位/泄漏译文。"""
    out: Dict[str, str] = {}
    texts = [(p.get("text") or "").strip() for p in phrases]

    def _peer_pairs_for(i: int) -> List[tuple]:
        return [
            (texts[j], (phrases[j].get("zh") or "").strip())
            for j in range(len(phrases))
            if j != i and texts[j]
        ]

    for i, p in enumerate(phrases):
        text = texts[i]
        zh = (p.get("zh") or "").strip()
        peers = [t for j, t in enumerate(texts) if j != i and t]
        peer_pairs = _peer_pairs_for(i)
        if text and zh and translation_valid(text, zh, peers, peer_pairs=peer_pairs):
            out[text] = zh
    if extra:
        phrase_texts = set(texts)
        for k, v in extra.items():
            k = (k or "").strip()
            v = (v or "").strip()
            if k not in phrase_texts or not v:
                continue
            idx = texts.index(k) if k in texts else -1
            if idx >= 0:
                peers = [t for j, t in enumerate(texts) if j != idx and t]
                peer_pairs = _peer_pairs_for(idx)
                if translation_valid(k, v, peers, peer_pairs=peer_pairs):
                    out[k] = v
            elif translation_plausible(k, v):
                out[k] = v
    return out


def sanitize_phrases(phrases: List[dict]) -> tuple[List[dict], int]:
    """清除不合理、prompt 泄漏或与其他行错位的 zh。"""
    removed = 0
    out: List[dict] = []
    texts = [(p.get("text") or "").strip() for p in phrases]
    for i, p in enumerate(phrases):
        item = dict(p)
        text = texts[i]
        zh = (item.get("zh") or "").strip()
        peers = [t for j, t in enumerate(texts) if j != i and t]
        peer_pairs = [
            (texts[j], (phrases[j].get("zh") or "").strip())
            for j in range(len(phrases))
            if j != i and texts[j]
        ]
        if zh and not translation_valid(text, zh, peers, peer_pairs=peer_pairs):
            item["zh"] = ""
            removed += 1
        out.append(item)
    return out, removed


def reconcile(video_id: str) -> dict:
    """清理过期 entries 与明显错位的译文。返回清理统计。"""
    _ensure_dir()
    with _lock:
        data = _read_raw(video_id)
        phrases_raw = data.get("phrases", [])
        if not isinstance(phrases_raw, list) or not phrases_raw:
            return {
                "before": len(data.get("entries", {})),
                "after": len(data.get("entries", {})),
                "removed": 0,
                "badTranslations": 0,
            }
        phrases = load_phrases(video_id)
        sanitized, bad = sanitize_phrases(phrases)
        existing = data.get("entries", {})
        if not isinstance(existing, dict):
            existing = {}
        before = len(existing)
        cleaned = _entries_from_phrases(sanitized)
        removed = before - len(cleaned)
        needs_schema = data.get("schemaVersion", 1) < CACHE_SCHEMA_VERSION
        if removed <= 0 and bad <= 0 and not needs_schema:
            return {
                "before": before,
                "after": before,
                "removed": 0,
                "badTranslations": 0,
            }
        payload: dict = {
            "videoId": _safe_id(video_id),
            "schemaVersion": CACHE_SCHEMA_VERSION,
            "entries": cleaned,
            "phrases": [
                {
                    "start": p.get("start", 0),
                    "end": p.get("end", 0),
                    "text": p.get("text", ""),
                    "zh": p.get("zh", ""),
                }
                for p in sanitized
            ],
            "captionFingerprint": data.get("captionFingerprint", ""),
        }
        p = _path(video_id)
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8"
        )
        return {
            "before": before,
            "after": len(cleaned),
            "removed": max(removed, 0),
            "badTranslations": bad,
        }


def reconcile_all() -> dict:
    """扫描全部缓存文件并 reconcile。返回汇总。"""
    _ensure_dir()
    fixed = 0
    removed = 0
    bad = 0
    for p in CACHE_DIR.glob("*.json"):
        r = reconcile(p.stem)
        if r.get("removed", 0) > 0 or r.get("badTranslations", 0) > 0:
            fixed += 1
            removed += r.get("removed", 0)
            bad += r.get("badTranslations", 0)
    return {"videosFixed": fixed, "entriesRemoved": removed, "badTranslationsCleared": bad}


def _carry_translations(
    new_phrases: List[dict], old_entries: Dict[str, str]
) -> List[dict]:
    """字幕轨变更时，尽量保留文本完全一致的旧译文。"""
    for p in new_phrases:
        text = (p.get("text") or "").strip()
        if not p.get("zh") and text in old_entries:
            p["zh"] = old_entries[text]
    return new_phrases


def update(
    video_id: str,
    mapping: Dict[str, str],
    phrases: Optional[List[dict]] = None,
    caption_fingerprint: Optional[str] = None,
) -> int:
    """写入缓存。有 phrases 时以之为准重建 entries；仅有 mapping 时不得写入未知键。"""
    _ensure_dir()
    with _lock:
        data = _read_raw(video_id)
        existing = data.get("entries", {})
        if not isinstance(existing, dict):
            existing = {}
        stored_phrases_raw = data.get("phrases", [])
        stored_texts = (
            _phrase_text_set(stored_phrases_raw)
            if isinstance(stored_phrases_raw, list)
            else set()
        )

        filtered = {
            k: v
            for k, v in (mapping or {}).items()
            if k and v and translation_plausible(k, v) and not is_meta_garbage(v)
        }

        fp_changed = False
        phrase_list = None
        if phrases:
            phrase_list = [
                {
                    "start": p.get("start", 0),
                    "end": p.get("end", 0),
                    "text": (p.get("text") or "").strip(),
                    "zh": (p.get("zh") or filtered.get(p.get("text", ""), "")
                           or existing.get(p.get("text", ""), "")),
                }
                for p in phrases
                if p.get("text")
            ]
            old_fp = data.get("captionFingerprint", "")
            if caption_fingerprint and old_fp and old_fp != caption_fingerprint:
                fp_changed = True
                phrase_list = _carry_translations(phrase_list, existing)
            existing = _entries_from_phrases(phrase_list, filtered)
        else:
            # 仅增量 entries：若已有 phrases，拒绝写入不在句子表中的键
            if stored_texts:
                filtered = filter_to_phrases(filtered, stored_texts)
                for src, dst in filtered.items():
                    existing[src] = dst
                # 同步回 phrases 中的 zh
                if isinstance(stored_phrases_raw, list):
                    for p in stored_phrases_raw:
                        if isinstance(p, dict):
                            t = (p.get("text") or "").strip()
                            if t in filtered:
                                p["zh"] = filtered[t]
                    phrase_list = None  # use updated stored below
            else:
                for src, dst in filtered.items():
                    existing[src] = dst

        payload: dict = {
            "videoId": _safe_id(video_id),
            "schemaVersion": CACHE_SCHEMA_VERSION,
            "entries": existing,
            "captionFingerprint": caption_fingerprint
            or data.get("captionFingerprint", ""),
        }
        if phrase_list:
            payload["phrases"] = [
                {
                    "start": p["start"],
                    "end": p["end"],
                    "text": p["text"],
                    "zh": p["zh"] or existing.get(p["text"], ""),
                }
                for p in phrase_list
            ]
            payload["entries"] = _entries_from_phrases(payload["phrases"])
        elif isinstance(stored_phrases_raw, list) and stored_phrases_raw:
            payload["phrases"] = stored_phrases_raw
            payload["entries"] = _entries_from_phrases(
                [
                    {
                        "text": (p.get("text") or "").strip(),
                        "zh": (p.get("zh") or existing.get(p.get("text", ""), "")),
                    }
                    for p in stored_phrases_raw
                    if isinstance(p, dict) and p.get("text")
                ]
            )
        if fp_changed:
            payload["entries"] = _entries_from_phrases(
                [
                    {"text": p["text"], "zh": p.get("zh", "")}
                    for p in payload.get("phrases", [])
                ]
            )

        p = _path(video_id)
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8"
        )
        return len(payload["entries"])


def save_phrases(video_id: str, phrases: List[dict]) -> int:
    """保存有序句子并同步 entries 映射。"""
    mapping = {
        p["text"]: p["zh"]
        for p in phrases
        if p.get("text") and p.get("zh")
    }
    return update(video_id, mapping, phrases=phrases)


def list_videos() -> List[dict]:
    """列出所有已缓存视频的概要（id、条数、字节、修改时间）。"""
    _ensure_dir()
    items = []
    for p in sorted(CACHE_DIR.glob("*.json")):
        try:
            stat = p.stat()
            data = json.loads(p.read_text(encoding="utf-8"))
            entries = data.get("entries", {})
            phrases = data.get("phrases", [])
            entry_n = len(entries) if isinstance(entries, dict) else 0
            phrase_n = len(phrases) if isinstance(phrases, list) else 0
            integrity_info = (
                integrity(p.stem)
                if phrase_n
                else {"orphanEntries": 0, "ok": True}
            )
            items.append(
                {
                    "videoId": p.stem,
                    "count": phrase_n or entry_n,
                    "entryCount": entry_n,
                    "phraseCount": phrase_n,
                    "stale": not integrity_info.get("ok", True),
                    "orphanEntries": integrity_info.get("orphanEntries", 0),
                    "bytes": stat.st_size,
                    "updated": int(stat.st_mtime),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    items.sort(key=lambda x: x["updated"], reverse=True)
    return items


def get_entries(video_id: str) -> Dict[str, str]:
    """查看某视频的全部缓存条目。"""
    return load(video_id)


def clear_video(video_id: str) -> bool:
    """清除单个视频缓存；删除成功返回 True。"""
    try:
        p = _path(video_id)
    except ValueError:
        return False
    with _lock:
        if p.exists():
            p.unlink()
            return True
    return False


def clear_all() -> int:
    """清除全部缓存，返回删除的文件数。"""
    _ensure_dir()
    n = 0
    with _lock:
        for p in CACHE_DIR.glob("*.json"):
            try:
                p.unlink()
                n += 1
            except OSError:
                continue
    return n


def stats() -> dict:
    """全局统计：视频数、总条目数、总字节。"""
    videos = list_videos()
    return {
        "videos": len(videos),
        "entries": sum(v["count"] for v in videos),
        "bytes": sum(v["bytes"] for v in videos),
    }
