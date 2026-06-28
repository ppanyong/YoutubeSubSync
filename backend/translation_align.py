"""字幕译文对齐校验（领域无关的通用启发式）。

检测：邻行英文/中文泄漏、半句过度翻译、discourse 结构、prompt 垃圾输出。
"""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional, Set, Tuple

from linguistic_rules import discourse_mismatch
from translation_meta import is_meta_garbage

_STOP = frozenset(
    """
    a an the and or but if in on at to for of is are was were be been being
    have has had do does did will would could should can may might must shall
    that this these those it its they them we you he she i my your our their
    with from by as not no so just like what when where which who how all
    about into over after before than then very also still even only
    """.split()
)

_QUOTED = re.compile(r'"([^"]{2,})"|\'([^\']{2,})\'')
_CAP_WORD = re.compile(r"\b[A-Z][a-z]{2,}\b")
_WORD = re.compile(r"\b[a-zA-Z]{4,}\b")
_LATIN_IN_TEXT = re.compile(r"[A-Za-z]{3,}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_SENTENCE_END = re.compile(r'[.!?…]["\']?\s*$')
_FRAGMENT_TAIL = re.compile(
    r"\b(to|and|or|the|a|an|we|you|they|have|has|is|are|was|were|if|when|that|this)\s*$",
    re.I,
)


def extract_anchors(text: str) -> Set[str]:
    """从英文行提取领域无关的特征词（专名、引号词、较长实词）。"""
    t = (text or "").strip()
    if not t:
        return set()
    out: Set[str] = set()
    for m in _QUOTED.finditer(t):
        w = (m.group(1) or m.group(2) or "").strip().lower()
        if w:
            out.add(w)
    for w in _CAP_WORD.findall(t):
        low = w.lower()
        if low not in _STOP:
            out.add(low)
    for w in _WORD.findall(t):
        low = w.lower()
        if low not in _STOP:
            out.add(low)
    return out


def _cjk_spans(text: str, min_len: int = 4) -> List[str]:
    return [m.group(0) for m in _CJK_RUN.finditer(text or "") if len(m.group(0)) >= min_len]


def _peer_foreign_anchors(src: str, peer_srcs: Iterable[str]) -> Set[str]:
    mine = extract_anchors(src)
    foreign: Set[str] = set()
    for peer in peer_srcs:
        p = (peer or "").strip()
        if not p or p == (src or "").strip():
            continue
        foreign |= extract_anchors(p) - mine
    return foreign


def _latin_tokens(text: str) -> Set[str]:
    return {m.lower() for m in _LATIN_IN_TEXT.findall(text or "")}


def _foreign_latin_leak(src: str, dst: str, peer_srcs: Iterable[str]) -> bool:
    dst_latin = _latin_tokens(dst)
    if not dst_latin:
        return False
    src_latin = _latin_tokens(src)
    for anchor in _peer_foreign_anchors(src, peer_srcs):
        low = anchor.lower()
        if len(low) >= 4 and low in dst_latin and low not in src_latin:
            return True
    return False


def _foreign_phrase_leak(src: str, dst: str, peer_srcs: Iterable[str]) -> bool:
    src_l = (src or "").lower()
    dst_latin_blob = " ".join(_LATIN_IN_TEXT.findall(dst or "")).lower()
    if not dst_latin_blob:
        return False
    for peer in peer_srcs:
        p = (peer or "").strip().lower()
        if not p or p == src_l:
            continue
        words = re.findall(r"[a-z']+", p)
        for n in (4, 3, 2):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i : i + n])
                if len(phrase) < 8 or phrase in src_l:
                    continue
                if phrase in dst_latin_blob:
                    return True
    return False


def _cjk_only(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fff]", "", text or "")


def _longest_common_cjk_run(a: str, b: str, min_len: int = 4) -> int:
    """返回两串 CJK 字符的最长公共子串长度（>= min_len 才计数）。"""
    if not a or not b:
        return 0
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k >= min_len and k > best:
                best = k
    return best


def _peer_cjk_leak(
    src: str, dst: str, peer_pairs: Iterable[Tuple[str, str]]
) -> bool:
    """邻句中文大段复用 → 串句（如 sci-fi 句配成 Anthropic 食堂）。"""
    d = (dst or "").strip()
    d_cjk = _cjk_only(d)
    if len(d_cjk) < 4:
        return False
    src_a = extract_anchors(src)
    sl = len((src or "").strip())
    for peer_en, peer_zh in peer_pairs:
        pe = (peer_en or "").strip()
        pz = (peer_zh or "").strip()
        if not pe or not pz or pe == (src or "").strip():
            continue
        if is_meta_garbage(pz):
            continue
        pz_cjk = _cjk_only(pz)
        if len(pz_cjk) < 4:
            continue
        overlap_en = len(src_a & extract_anchors(pe))
        # 开头相同且英文几乎无关 → 高概率串句
        for prefix in range(min(10, len(pz_cjk), len(d_cjk)), 2, -1):
            if pz_cjk[:prefix] != d_cjk[:prefix]:
                continue
            if overlap_en == 0 and prefix >= 3 and len(d_cjk) >= 8:
                return True
            if overlap_en <= 1 and prefix >= 5:
                return True
            if overlap_en <= 1 and prefix >= 4 and len(d_cjk) > sl * 0.8 + 8:
                return True
        common = _longest_common_cjk_run(pz_cjk, d_cjk, min_len=4)
        if common >= 10 and overlap_en <= 2:
            return True
        if common >= 7 and overlap_en <= 1:
            return True
        if common >= 5 and overlap_en == 0 and len(d_cjk) > max(sl, 12):
            return True
        for span in _cjk_spans(pz, min_len=4):
            if span in d and overlap_en <= 1 and len(span) >= 5:
                return True
    return False


def _context_merge_overtranslate(src: str, dst: str) -> bool:
    """短英文片段却译成含多个分句的长中文（合并多句）。"""
    s = (src or "").strip()
    d = (dst or "").strip()
    if not s or not d:
        return False
    sl, dl = len(s), len(d)
    if sl >= 55:
        return False
    clauses = len(re.findall(r"[。！？；]", d))
    if sl < 35 and dl > sl * 2.4 + 24 and clauses >= 2:
        return True
    if sl < 25 and dl > sl * 2.8 + 18:
        return True
    return False


def _fragment_overtranslate(src: str, dst: str) -> bool:
    s = (src or "").strip()
    d = (dst or "").strip()
    if not s or not d or _SENTENCE_END.search(s):
        return False
    if _FRAGMENT_TAIL.search(s):
        if len(d) > len(s) * 1.2 + 6:
            return True
        if re.search(r"[。！？]$", d) and len(d) > 12:
            return True
    return False


def _llm_verify_alignment(src: str, dst: str, peer_srcs: Iterable[str]) -> bool:
    if os.getenv("TRANSLATE_ALIGN_VERIFY", "").lower() not in ("1", "true", "yes"):
        return True
    try:
        from translator import get_translator
    except Exception:
        return True
    peers = [p.strip() for p in peer_srcs if p and p.strip() and p.strip() != src.strip()]
    ctx = "\n".join(f"- {p}" for p in peers[:6]) if peers else "（无）"
    system = (
        "你是字幕对齐审核员。只回答 YES 或 NO。\n"
        "问题：中文是否只翻译了「本行英文」的字面内容，没有提前翻译上下文其他行的信息？"
    )
    user = f"本行英文：\n{src}\n\n其他英文行（上下文）：\n{ctx}\n\n中文译文：\n{dst}"
    try:
        translator = get_translator()
        ans = translator._call_llm(system, user).strip().upper()
        return ans.startswith("Y")
    except Exception:
        return True


def _normalize_peer_pairs(
    peer_srcs: Iterable[str],
    peer_zhs: Optional[Iterable[str]] = None,
    peer_pairs: Optional[Iterable[Tuple[str, str]]] = None,
) -> List[Tuple[str, str]]:
    if peer_pairs is not None:
        return [(a, b or "") for a, b in peer_pairs if (a or "").strip()]
    srcs = [s for s in peer_srcs if (s or "").strip()]
    if peer_zhs is None:
        return [(s, "") for s in srcs]
    zhs = list(peer_zhs)
    if len(zhs) < len(srcs):
        zhs = zhs + [""] * (len(srcs) - len(zhs))
    return list(zip(srcs, zhs[: len(srcs)]))


def translation_aligned(
    src: str,
    dst: str,
    peer_srcs: Iterable[str],
    peer_zhs: Optional[Iterable[str]] = None,
    peer_pairs: Optional[Iterable[Tuple[str, str]]] = None,
) -> bool:
    if not (dst or "").strip():
        return False
    if is_meta_garbage(dst):
        return False
    pairs = _normalize_peer_pairs(peer_srcs, peer_zhs, peer_pairs)
    peer_en_only = [a for a, _ in pairs] if pairs else list(peer_srcs)
    if _foreign_latin_leak(src, dst, peer_en_only):
        return False
    if _foreign_phrase_leak(src, dst, peer_en_only):
        return False
    if pairs and _peer_cjk_leak(src, dst, pairs):
        return False
    if discourse_mismatch(src, dst):
        return False
    if _fragment_overtranslate(src, dst):
        return False
    if _context_merge_overtranslate(src, dst):
        return False
    if not _llm_verify_alignment(src, dst, peer_en_only):
        return False
    return True


def peers_for_index(segments: List[str], index: int) -> List[str]:
    return [s for j, s in enumerate(segments) if j != index and (s or "").strip()]


def peer_pairs_for_index(
    segments: List[str],
    translations: List[str],
    index: int,
    context_pairs: Optional[List[Tuple[str, str]]] = None,
) -> List[Tuple[str, str]]:
    """构建对齐校验用的 (英文, 译文) 邻句对（含滚动上下文）。"""
    out: List[Tuple[str, str]] = []
    for j, s in enumerate(segments):
        if j == index or not (s or "").strip():
            continue
        z = ""
        if j < len(translations) and translations[j] and translations[j] != s:
            z = translations[j]
        out.append((s, z))
    if context_pairs:
        src_set = {(s or "").strip() for s in segments}
        for en, zh in context_pairs:
            if (en or "").strip() and (en or "").strip() not in src_set:
                out.append((en, zh or ""))
    return out
