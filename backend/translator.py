"""翻译引擎：LLM（OpenAI 兼容）批量翻译实现。

设计要点：
- translate_batch 接收一组英文片段，返回等长的中文片段列表。
- LLM 走「带编号」协议：每条字幕加 [序号]，要求模型逐条对应翻译，
  解析时按编号回填、缺失项用原文兜底，保证返回长度始终与输入一致。
  （YouTube 自动字幕高度碎片化，模型易合并多条，编号对齐可避免错位/整批失败。）
- 失败时回退为原文，保证字幕流水线不中断。
"""

from __future__ import annotations

import os
import re
from typing import List

from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI


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


def _target_lang_name() -> str:
    code = os.getenv("TARGET_LANG", TARGET_LANG)
    return _LANG_NAME.get(code, "简体中文")


class TranslatorError(Exception):
    pass


class LLMTranslator:
    """使用 OpenAI 兼容接口的 LLM 翻译（支持 GLM 等，通过 base_url 切换）。"""

    def __init__(self) -> None:
        api_key = os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        if not api_key or api_key.startswith("sk-xxxx"):
            raise TranslatorError("未配置有效的 LLM_API_KEY，请编辑 backend/.env")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.base_url = base_url

    def translate_batch(self, segments: List[str], mode: str = "fragment") -> List[str]:
        if not segments:
            return []
        if mode == "sentence":
            return self._translate_sentences(segments)
        return self._translate_fragments(segments)

    def _translate_sentences(self, segments: List[str]) -> List[str]:
        """整句翻译：输入为合并后的完整句子，输出等长目标语言句。"""
        lang = _target_lang_name()
        numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(segments))
        system = (
            f"你是专业的视频字幕翻译。输入为编号的完整英文句子，请逐句翻译成自然流畅的{lang}。\n"
            "要求：\n"
            f"1) 每行输出格式 [序号] {lang}译文，序号与输入一一对应；\n"
            "2) 保留全部序号，不合并、不拆分；\n"
            f"3) 口语化、符合{lang}习惯，保留专有名词；\n"
            "4) 只输出译文行，不要解释。"
        )
        user = f"共 {len(segments)} 句：\n{numbered}"
        content = self._call_llm(system, user)
        return _align_numbered(content, segments)

    def _translate_fragments(self, segments: List[str]) -> List[str]:
        lang = _target_lang_name()
        numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(segments))
        system = (
            f"你是专业的视频字幕翻译，把英文字幕逐条翻译成{lang}。\n"
            "输入每行格式为 [序号] 英文。你必须遵守：\n"
            f"1) 逐条翻译，每行输出格式为 [序号] {lang}译文，序号与输入一一对应；\n"
            "2) 必须保留全部序号，绝不合并、拆分、增加或删除任何一条；\n"
            "3) 这些是字幕碎片，可能不成完整句子，请按该片段字面翻译；\n"
            "4) 只输出译文行，不要任何解释或多余文本。"
        )
        user = f"共 {len(segments)} 条，请逐条翻译：\n{numbered}"
        content = self._call_llm(system, user)
        return _align_numbered(content, segments)

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


# 匹配 [0] 译文 / 0. 译文 / 0: 译文 / (0) 译文 等编号行。
_NUM_RE = re.compile(r"^\s*[\[\(]?(\d+)[\]\)\.\:、]\s*(.*)$")


def _align_numbered(content: str, segments: List[str]) -> List[str]:
    """按编号把模型输出回填到对应位置；缺失或解析失败的条目保留原文。

    始终返回与 segments 等长的列表，避免字幕错位或整批失败。
    """
    result = list(segments)
    filled = 0
    for raw in content.splitlines():
        m = _NUM_RE.match(raw)
        if not m:
            continue
        idx = int(m.group(1))
        text = (m.group(2) or "").strip()
        if 0 <= idx < len(result) and text:
            result[idx] = text
            filled += 1
    # filled == 0 说明模型完全没按编号返回：保留全部原文，不中断流水线。
    return result


def get_translator() -> LLMTranslator:
    return LLMTranslator()
