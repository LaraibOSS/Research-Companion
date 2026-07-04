"""Tests for the permutation p-value used in the novelty-agreement eval."""
from __future__ import annotations

from research_companion.eval.novelty_openreview import rank_correlation
from research_companion.eval.pvalue import permutation_pvalue


def test_perfect_correlation_small_p():
    a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    b = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    rho = rank_correlation(a, b)
    p = permutation_pvalue(a, b, n_perm=2000, seed=7)
    assert rho == 1.0
    assert p < 0.05


def test_unrelated_large_p():
    a = [1, 2, 3, 4, 5, 6, 7, 8]
    b = [5, 1, 7, 3, 8, 2, 6, 4]
    p = permutation_pvalue(a, b, n_perm=2000, seed=7)
    assert p > 0.05


def test_deterministic_for_seed():
    a = [1, 2, 3, 4, 5, 6]
    b = [2, 1, 4, 3, 6, 5]
    assert permutation_pvalue(a, b, seed=42) == permutation_pvalue(a, b, seed=42)
