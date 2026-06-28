"""译文元信息 / Prompt 泄漏检测（领域无关）。

模型偶发回显 prompt 标记、前缀或空壳输出；此处集中判定并供翻译/缓存/校验复用。
"""

from __future__ import annotations

import re

# 整句即为垃圾（直接拒收）
_GARBAGE_FULL = re.compile(
    r"^[\s\*]*("
    r"翻译\s*[:：]|"
    r"translation\s*[:：]|"
    r"请翻译这一行|"
    r"请翻译以下|"
    r"do not translate|"
    r"reference only|"
    r"prior subtitle|"
    r"前文[，,]?仅供理解|"
    r"不要重译|"
    r"不要输出|"
    r"不要翻译|"
    r"ZH\s*[:：]\s*[\[【]?前文|"
    r"EN\s*[:：]\s*"
    r")",
    re.I,
)

# 含任一即拒收
_GARBAGE_ANYWHERE = re.compile(
    r"前文[，,]?仅供理解|"
    r"不要重译[、,]?不要输出|"
    r"请翻译这一行|"
    r"请翻译以下|"
    r"reference only, do NOT output|"
    r"Prior subtitle lines",
    re.I,
)

# 仅前缀 + 极短内容
_PREFIX_STUB = re.compile(
    r"^[\s\*]*(?:翻译\s*[:：]|translation\s*[:：]|ZH\s*[:：])\s*"
    r"(?:[\[【].*?[】\]]|\.\.\.|…)?\s*$",
    re.I,
)

# 过短且无中文实义
_TOO_SHORT = re.compile(r"^[\s\*翻译：:ZHEN\s\.\…]{0,12}$")


def is_meta_garbage(dst: str) -> bool:
    """译文是否为 prompt 泄漏 / 空壳 / 无效占位。"""
    d = (dst or "").strip()
    if not d:
        return True
    if _TOO_SHORT.match(d):
        return True
    if _GARBAGE_FULL.match(d):
        return True
    if _GARBAGE_ANYWHERE.search(d):
        return True
    if _PREFIX_STUB.match(d):
        return True
    # 模型回显 XML / 标签
    if re.search(r"</?(?:context|prior|subtitle|translation)[^>]*>", d, re.I):
        return True
    return False


def strip_meta_prefix(dst: str) -> str:
    """去掉常见前缀后若为空则视为垃圾。"""
    d = (dst or "").strip()
    d = re.sub(r"^[\s\*]*(?:翻译\s*[:：]|translation\s*[:：]|ZH\s*[:：])\s*", "", d, flags=re.I)
    d = re.sub(r"^[\s\*]+", "", d)
    if not d or is_meta_garbage(d):
        return ""
    return d
