"""翻译缓存：按视频 ID 持久化「英文原文 -> 中文译文」映射。

- 每个视频一个 JSON 文件：backend/cache/<videoId>.json
- 命中缓存即可跳过 LLM 调用，跨会话/设备（同后端）复用，显著省钱省时。
- 提供浏览（列出/查看）与清理（单个/全部）能力。
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"

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


def load(video_id: str) -> Dict[str, str]:
    """读取某视频的缓存映射；不存在返回空字典。"""
    try:
        p = _path(video_id)
    except ValueError:
        return {}
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        entries = data.get("entries", {})
        return entries if isinstance(entries, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def update(video_id: str, mapping: Dict[str, str]) -> int:
    """合并写入缓存（仅写非空译文）。返回写入后的总条数。"""
    if not mapping:
        return len(load(video_id))
    _ensure_dir()
    with _lock:
        existing = load(video_id)
        for src, dst in mapping.items():
            if src and dst:
                existing[src] = dst
        p = _path(video_id)
        payload = {"videoId": _safe_id(video_id), "entries": existing}
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8"
        )
        return len(existing)


def list_videos() -> List[dict]:
    """列出所有已缓存视频的概要（id、条数、字节、修改时间）。"""
    _ensure_dir()
    items = []
    for p in sorted(CACHE_DIR.glob("*.json")):
        try:
            stat = p.stat()
            data = json.loads(p.read_text(encoding="utf-8"))
            entries = data.get("entries", {})
            items.append(
                {
                    "videoId": p.stem,
                    "count": len(entries) if isinstance(entries, dict) else 0,
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
