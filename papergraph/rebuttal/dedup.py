"""Group near-duplicate concerns raised by different reviewers."""
from __future__ import annotations

from papergraph.rebuttal.models import Concern
from papergraph.refcheck.matching import title_similarity


def group_concerns(concerns: list[Concern], threshold: float = 0.55) -> list[list[str]]:
    groups: list[list[Concern]] = []
    for c in concerns:
        for g in groups:
            if title_similarity(c.text, g[0].text) >= threshold:
                g.append(c)
                break
        else:
            groups.append([c])
    return [[c.concern_id for c in g] for g in groups]
