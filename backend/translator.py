"""翻译引擎：逐条字幕翻译（Sequential Line Translation）。

系统性保证对齐的策略：
- 禁止批量编号翻译（模型易漂移/超前/合并）。
- 每条字幕单独一次 LLM 调用，输出一条译文。
- 滚动窗口提供 EN+ZH 前文，保证语境连贯但不混行。
- 质量 + 锚词 + meta 泄漏 + 邻句中文串句 校验，失败则保留英文原文。
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI

from translation_align import peer_pairs_for_index, translation_aligned
from translation_meta import is_meta_garbage, strip_meta_prefix
from translation_quality import translation_plausible

TARGET_LANG = os.getenv("TARGET_LANG", "zh")

_LANG_NAME = {
    "zh": "简体中文",
    "zh-Hant": "繁体中文",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
    "pt": "葡萄牙语",
}

SEQUENTIAL_MODES = frozenset({"context", "line", "sentence"})


def _target_lang_name() -> str:
    code = os.getenv("TARGET_LANG", TARGET_LANG)
    return _LANG_NAME.get(code, "简体中文")


class TranslatorError(Exception):
    pass


class LLMTranslator:
    def __init__(self) -> None:
        api_key = os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        if not api_key or api_key.startswith("sk-xxxx"):
            raise TranslatorError("未配置有效的 LLM_API_KEY，请编辑 backend/.env")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.base_url = base_url

    def translate_batch(
        self,
        segments: List[str],
        mode: str = "line",
        context_before: Optional[List[str]] = None,
        context_zh_before: Optional[List[str]] = None,
    ) -> List[str]:
        if not segments:
            return []
        mode = (mode or "line").lower()
        if mode in SEQUENTIAL_MODES:
            return self._translate_sequential(
                segments, context_before, context_zh_before
            )
        return self._translate_sequential(segments, context_before, context_zh_before)

    def _translate_sequential(
        self,
        segments: List[str],
        context_before: Optional[List[str]] = None,
        context_zh_before: Optional[List[str]] = None,
    ) -> List[str]:
        lang = _target_lang_name()
        ctx_en: List[str] = [s.strip() for s in (context_before or []) if s and s.strip()]
        ctx_zh: List[str] = list(context_zh_before or [])
        if len(ctx_zh) < len(ctx_en):
            ctx_zh = ctx_zh + [""] * (len(ctx_en) - len(ctx_zh))
        elif len(ctx_zh) > len(ctx_en):
            ctx_zh = ctx_zh[-len(ctx_en) :]

        results: List[str] = []
        for i, seg in enumerate(segments):
            seg = (seg or "").strip()
            if not seg:
                results.append(seg)
                continue

            ctx_pairs = _zip_context(ctx_en, ctx_zh)[-3:]
            zh = self._translate_one_line(seg, ctx_pairs, lang)
            peer_pairs = peer_pairs_for_index(segments, results, i, ctx_pairs)
            peers = [p[0] for p in peer_pairs]

            if (
                zh
                and zh != seg
                and translation_plausible(seg, zh)
                and translation_aligned(seg, zh, peers, peer_pairs=peer_pairs)
            ):
                results.append(zh)
                ctx_en.append(seg)
                ctx_zh.append(zh)
            else:
                results.append(seg)
                ctx_en.append(seg)
                ctx_zh.append("")
            ctx_en = ctx_en[-6:]
            ctx_zh = ctx_zh[-6:]

        return results

    def _build_system(self, lang: str, ctx_pairs: List[Tuple[str, str]]) -> str:
        system = (
            f"You translate one English subtitle line into {lang}.\n"
            f"Rules:\n"
            f"- Output ONLY the translation text\n"
            f"- No labels (EN/ZH/Translation), no quotes, no numbering, no markdown\n"
            f"- Translate ONLY the current line literally; do not add content from other lines\n"
            f"- If English is a fragment, translate the fragment; do not complete the sentence"
        )
        if ctx_pairs:
            lines = []
            for en, zh in ctx_pairs[-3:]:
                if zh:
                    lines.append(f"{en} → {zh}")
                else:
                    lines.append(en)
            system += (
                "\n\nPrior subtitle lines (reference tone only — never output these):\n"
                + "\n".join(lines)
            )
        return system

    def _translate_one_line(
        self, line_en: str, ctx_pairs: List[Tuple[str, str]], lang: str
    ) -> str:
        # 首次带上下文；泄漏或无输出时去掉上下文重试
        for pairs in (ctx_pairs, []):
            raw = self._call_llm(self._build_system(lang, pairs), line_en)
            zh = _clean_single_line(raw)
            if zh:
                zh = strip_meta_prefix(zh) or zh
            if zh and not is_meta_garbage(zh):
                return zh
        return ""

    def _call_llm(self, system: str, user: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
            )
        except AuthenticationError as e:
            raise TranslatorError(f"大模型 API Key 无效：{e.message}") from e
        except APIConnectionError as e:
            raise TranslatorError(f"无法连接大模型服务（{self.base_url}）：{e}") from e
        except APIStatusError as e:
            raise TranslatorError(f"大模型返回错误 {e.status_code}：{e.message}") from e
        return resp.choices[0].message.content or ""


_NUM_PREFIX = re.compile(r"^\s*[\[\(]?\d+[\]\)\.\:、]\s*")


def _clean_single_line(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    line = _NUM_PREFIX.sub("", line)
    if (line.startswith('"') and line.endswith('"')) or (
        line.startswith("'") and line.endswith("'")
    ):
        line = line[1:-1].strip()
    if is_meta_garbage(line):
        return ""
    return line


def _zip_context(en: List[str], zh: List[str]) -> List[Tuple[str, str]]:
    n = max(len(en), len(zh))
    pairs: List[Tuple[str, str]] = []
    for i in range(n):
        e = en[i] if i < len(en) else ""
        z = zh[i] if i < len(zh) else ""
        if e:
            pairs.append((e, z))
    return pairs


def get_translator() -> LLMTranslator:
    return LLMTranslator()
