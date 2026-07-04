"""Retrieve the paper passages most relevant to a reviewer concern (no LLM)."""
from __future__ import annotations

import math
import re

from research_companion.rebuttal.models import Passage


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) >= 4}


def retrieve_passages(concern_text: str, fulltext: str, k: int = 3) -> list[Passage]:
    concern_toks = _tokens(concern_text)
    if not concern_toks:
        return []
    scored: list[tuple[float, int, Passage]] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", fulltext) if p.strip()]
    for i, para in enumerate(paragraphs, 1):
        para_toks = _tokens(para)
        shared = concern_toks & para_toks
        if not shared:
            continue
        score = len(shared) / (1 + math.log(1 + len(para.split())))
        scored.append((score, i, Passage(location=f"para {i}", text=para, score=round(score, 4))))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [p for _, _, p in scored[:k]]
