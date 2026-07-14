"""Orchestrate extraction -> recomputation -> verdict for statistical soundness.

For each reported NHST test we recompute the p-value from the statistic and
degrees of freedom and compare it to what was reported, honoring the reporting
style (``=`` vs ``<``/``>``) and rounding. The output is deliberately modest: a
*reporting inconsistency*, optionally one that flips the significance decision at
alpha = .05 — never a claim of error or misconduct. Ambiguity is handled
conservatively: an unknown tail is accepted if the report is consistent under
either one- or two-tailed testing, and the rounding of the reported statistic is
folded into a plausible-p interval so borderline rounding never trips a flag.
"""
from __future__ import annotations

from research_companion.statcheck.distributions import (
    chi2_pvalue,
    f_pvalue,
    normal_two_tailed,
    r_two_tailed,
    t_two_tailed,
)
from research_companion.statcheck.extract import extract_means, extract_stat_tests
from research_companion.statcheck.grim import count_decimals, grim_possible

ALPHA = 0.05
_TWO_TAILED_TYPES = {"t", "z", "r"}


def _p_at(test: dict, magnitude: float, tail: str) -> float:
    tt = test["test_type"]
    if tt == "F":
        return f_pvalue(magnitude, test["df1"], test["df2"])
    if tt == "chi2":
        return chi2_pvalue(magnitude, test["df"])
    if tt == "t":
        p2 = t_two_tailed(magnitude, test["df"])
    elif tt == "z":
        p2 = normal_two_tailed(magnitude)
    elif tt == "r":
        p2 = r_two_tailed(magnitude, test["df"])
    else:  # pragma: no cover - guarded by extractor
        raise ValueError(f"unknown test type {tt!r}")
    return p2 if tail == "two" else p2 / 2.0


def _p_interval(test: dict, tail: str) -> tuple[float, float]:
    """Plausible recomputed-p interval, accounting for rounding of the statistic."""
    decimals = count_decimals(test["statistic_str"].lstrip("+-"))
    half = 0.5 * (10.0 ** -decimals)
    mag = abs(test["statistic"])
    lo = max(mag - half, 0.0)
    hi = mag + half
    p_hi = _p_at(test, hi, tail)   # larger statistic -> smaller p
    p_lo = _p_at(test, lo, tail)   # smaller statistic -> larger p
    return (min(p_hi, p_lo), max(p_hi, p_lo))


def _matches(op: str, reported: float, reported_decimals: int,
             pmin: float, pmax: float) -> bool:
    tol = 0.5 * (10.0 ** -reported_decimals) + 1e-9
    if op == "=":
        return (pmin - tol) <= reported <= (pmax + tol)
    if op == "<":
        # "p < X" is consistent if the true p can be below X.
        return pmin <= reported + tol
    if op == ">":
        # "p > X" is consistent if the true p can be above X.
        return pmax >= reported - tol
    return False


def _reported_significant(op: str, reported: float) -> bool | None:
    if op == "=":
        return reported < ALPHA
    if op == "<":
        return True if reported <= ALPHA else None
    if op == ">":
        return False if reported >= ALPHA else None
    return None


def _recomputed_significant(pmin: float, pmax: float) -> bool | None:
    if pmax < ALPHA:
        return True
    if pmin >= ALPHA:
        return False
    return None  # interval straddles alpha


def _classify(test: dict) -> dict:
    reported = test["p_reported"]
    op = test["p_operator"]
    rdec = max(count_decimals(test["p_reported_str"]), 2)

    tails = ("two", "one") if test["test_type"] in _TWO_TAILED_TYPES else ("two",)
    assumptions: list[str] = []
    matched = False
    used_tail = "two"
    for tail in tails:
        pmin, pmax = _p_interval(test, tail)
        if _matches(op, reported, rdec, pmin, pmax):
            matched = True
            used_tail = tail
            break
    # Primary (two-tailed) interval and point drive display + decision logic.
    pmin2, pmax2 = _p_interval(test, "two")
    recomputed_point = _p_at(test, abs(test["statistic"]), "two")

    if matched:
        status = "consistent"
        severity = "info"
        if test["test_type"] in _TWO_TAILED_TYPES and used_tail == "one":
            assumptions.append("assumed one-tailed")
        elif test["test_type"] in _TWO_TAILED_TYPES:
            assumptions.append("assumed two-tailed")
    else:
        rep_sig = _reported_significant(op, reported)
        rec_sig = _recomputed_significant(pmin2, pmax2)
        if rep_sig is not None and rec_sig is not None and rep_sig != rec_sig:
            status = "decision_inconsistent"
            severity = "high"
        else:
            status = "inconsistent"
            severity = "medium"
        if test["test_type"] in _TWO_TAILED_TYPES:
            assumptions.append("checked one- and two-tailed")

    finding = {
        "test_type": test["test_type"],
        "statistic": test["statistic"],
        "p_operator": op,
        "p_reported": reported,
        "recomputed_p": round(recomputed_point, 5),
        "recomputed_p_range": [round(pmin2, 5), round(pmax2, 5)],
        "status": status,
        "severity": severity,
        "assumptions": assumptions,
        "raw": test["raw"],
        "char_start": test["char_start"],
        "char_end": test["char_end"],
    }
    for key in ("df", "df1", "df2"):
        if key in test:
            finding[key] = test[key]
    return finding


def _grim_finding(mean: dict) -> dict:
    possible = grim_possible(mean["mean_str"], mean["n"])
    return {
        "test_type": "mean",
        "mean": mean["mean"],
        "n": mean["n"],
        "status": "consistent" if possible else "impossible_mean",
        "severity": "info" if possible else "high",
        "assumptions": ["GRIM assumes single integer items (scale points unknown)"],
        "raw": mean["raw"],
        "char_start": mean["char_start"],
        "char_end": mean["char_end"],
    }


def check_stats(fulltext: str) -> dict:
    """Run the statistical-soundness checks over *fulltext*.

    Returns a JSON-safe dict:
      {findings: [...], summary: {n_tests, n_inconsistent, n_decision_inconsistent,
       n_impossible_means, n_means, text}}
    """
    text = fulltext or ""
    findings = [_classify(t) for t in extract_stat_tests(text)]
    grim_findings = [_grim_finding(m) for m in extract_means(text)]

    n_tests = len(findings)
    n_decision = sum(1 for f in findings if f["status"] == "decision_inconsistent")
    n_inconsistent = sum(1 for f in findings if f["status"] == "inconsistent")
    n_means = len(grim_findings)
    n_impossible = sum(1 for f in grim_findings if f["status"] == "impossible_mean")

    total_bad = n_decision + n_inconsistent
    parts = []
    if n_tests:
        parts.append(f"{total_bad} of {n_tests} reported tests inconsistent")
        if n_decision:
            parts.append(f"{n_decision} flip the significance decision")
    if n_impossible:
        parts.append(f"{n_impossible} of {n_means} reported means arithmetically impossible")
    text_summary = "; ".join(parts) if parts else (
        "no statistical inconsistencies found" if n_tests or n_means
        else "no parseable statistics found")

    return {
        "findings": findings + grim_findings,
        "summary": {
            "n_tests": n_tests,
            "n_inconsistent": n_inconsistent,
            "n_decision_inconsistent": n_decision,
            "n_means": n_means,
            "n_impossible_means": n_impossible,
            "text": text_summary,
        },
    }
