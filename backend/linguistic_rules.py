"""语言对级别的结构规则（非领域词表）。

仅描述「译文起首句式 ↔ 源语言 cue」等跨语言习惯，不绑定具体话题词汇。
"""

from __future__ import annotations

import re
from typing import List, Tuple

# (target_lang 译文起首, source_lang 需出现的 cue)
DISCOURSE_BY_PAIR: dict[tuple[str, str], List[Tuple[re.Pattern, re.Pattern]]] = {
    ("zh", "en"): [
        (re.compile(r"^(比如|例如|像是)"), re.compile(r"\b(like|such as|for example|e\.g\.)\b", re.I)),
        (re.compile(r"^(所以|因此|因而)"), re.compile(r"\b(so|therefore|thus|hence)\b", re.I)),
        (re.compile(r"^这是"), re.compile(r"\b(this is|that's|it is)\b", re.I)),
        (re.compile(r"^存在"), re.compile(r"\b(there is|there are|there's)\b", re.I)),
    ],
}


def discourse_mismatch(
    src: str, dst: str, source_lang: str = "en", target_lang: str = "zh"
) -> bool:
    rules = DISCOURSE_BY_PAIR.get((target_lang, source_lang), [])
    for zh_pat, en_pat in rules:
        if zh_pat.search((dst or "").strip()) and not en_pat.search(src or ""):
            return True
    return False
