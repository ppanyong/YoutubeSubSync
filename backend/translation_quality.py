"""译文质量校验：防止错位、超前翻译、prompt 泄漏、合并多句。"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

from translation_meta import is_meta_garbage

_CLAUSE_RE = re.compile(r"[.!?。！？…]+")


def _clause_count(text: str) -> int:
    t = (text or "").strip()
    if not t:
        return 0
    n = len(_CLAUSE_RE.findall(t))
    return max(n, 1)


def translation_plausible(src: str, dst: str) -> bool:
    src = (src or "").strip()
    dst = (dst or "").strip()
    if not src or not dst:
        return False
    if is_meta_garbage(dst):
        return False
    if src.lower() == dst.lower():
        return False
    sl, dl = len(src), len(dst)
    max_ratio = 2.0 if sl < 45 else 2.2
    if dl > sl * max_ratio + 16:
        return False
    if sl > 40 and dl < sl * 0.12:
        return False
    src_c = _clause_count(src)
    dst_c = _clause_count(dst)
    if dst_c > src_c:
        return False
    if sl < 25 and dl > sl * 2.0 + 12 and dst_c >= 2:
        return False
    return True


def translation_valid(
    src: str,
    dst: str,
    peer_srcs: Optional[Iterable[str]] = None,
    peer_zhs: Optional[Iterable[str]] = None,
    peer_pairs: Optional[Iterable[Tuple[str, str]]] = None,
) -> bool:
    from translation_align import translation_aligned

    if not translation_plausible(src, dst):
        return False
    if peer_srcs is not None and not translation_aligned(
        src, dst, peer_srcs, peer_zhs=peer_zhs, peer_pairs=peer_pairs
    ):
        return False
    return True
