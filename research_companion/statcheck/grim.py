"""GRIM test — Granularity-Related Inconsistency of Means.

A mean of ``N`` integer observations can only take the values ``k / N`` for
integer ``k``. If a paper reports a mean to ``d`` decimal places that no such
``k / N`` rounds to, the mean is arithmetically impossible given the stated
sample size. This is a pure arithmetic check — deterministic and LLM-free.

We are deliberately conservative: when the granularity ``1 / N`` is finer than
the reported rounding unit (large ``N``), every value is reachable, so the check
reports *possible* rather than guessing.
"""
from __future__ import annotations


def count_decimals(mean_str: str) -> int:
    """Number of decimal places in a reported mean string (e.g. '3.40' -> 2)."""
    mean_str = mean_str.strip()
    if "." not in mean_str:
        return 0
    return len(mean_str.split(".", 1)[1].rstrip())


def grim_possible(mean_str: str, n: int, n_items: int = 1) -> bool:
    """Return True if *mean_str* is arithmetically achievable for *n* observations.

    Args:
        mean_str: the reported mean exactly as written (its decimals matter).
        n: the number of observations the mean is over.
        n_items: number of integer items averaged per observation (a composite
            scale of ``n_items`` Likert items has granularity ``1/(n*n_items)``).

    A mean is *possible* when some integer numerator ``k`` gives ``k/N`` within
    half a rounding unit of the reported value, where ``N = n * n_items``.
    """
    n_total = n * n_items
    if n_total <= 0:
        return True  # cannot check without a valid N
    mean = float(mean_str)
    decimals = count_decimals(mean_str)
    tol = 0.5 * (10.0 ** -decimals) + 1e-9
    k = round(mean * n_total)
    for candidate_k in (k - 1, k, k + 1):
        if candidate_k < 0:
            continue
        if abs(candidate_k / n_total - mean) <= tol:
            return True
    return False
