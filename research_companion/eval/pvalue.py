"""Permutation p-value for the novelty-agreement rank correlation.

Two-sided test: how often does a random pairing of the two score lists produce
a |Spearman rho| at least as large as the observed one? Seeded and dependency-free.
"""
from __future__ import annotations

import random

from research_companion.eval.novelty_openreview import rank_correlation


def permutation_pvalue(a: list[float], b: list[float], *,
                       n_perm: int = 10_000, seed: int = 42) -> float:
    observed = abs(rank_correlation(a, b))
    rng = random.Random(seed)
    b_shuffled = list(b)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(b_shuffled)
        if abs(rank_correlation(a, b_shuffled)) >= observed:
            hits += 1
    # +1 correction avoids p == 0 from finite permutations
    return (hits + 1) / (n_perm + 1)
