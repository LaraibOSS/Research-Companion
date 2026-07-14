"""Deterministic extraction of reported NHST statistics and means from text.

Regex-based, LLM-free, and carrying absolute ``char_start``/``char_end`` offsets
into the source text (the same provenance convention used across the codebase) so
a flagged statistic can be highlighted in the reader. Only clearly-structured
APA-style reports are matched; anything ambiguous is left unmatched rather than
guessed at.
"""
from __future__ import annotations

import re

# A numeric literal: optional sign, optional leading digits, optional decimals.
# Accepts APA style with no leading zero (".04").
_NUM = r"[-+]?\d*\.?\d+"
_POP = r"[<>=]"          # p-value relational operator
_SEP = r"\s*[;,]?\s*"    # optional separator between statistic and 'p'

_T_RE = re.compile(
    rf"\bt\s*\(\s*(?P<df>\d+(?:\.\d+)?)\s*\)\s*=\s*(?P<stat>{_NUM})"
    rf"{_SEP}p\s*(?P<pop>{_POP})\s*(?P<p>{_NUM})",
    re.IGNORECASE,
)
_F_RE = re.compile(
    rf"\bF\s*\(\s*(?P<df1>\d+(?:\.\d+)?)\s*,\s*(?P<df2>\d+(?:\.\d+)?)\s*\)\s*=\s*(?P<stat>{_NUM})"
    rf"{_SEP}p\s*(?P<pop>{_POP})\s*(?P<p>{_NUM})",
    re.IGNORECASE,
)
_CHI2_RE = re.compile(
    r"(?:χ²|χ2|chi[-\s]?squared?|chi2|X²|X2)"
    rf"\s*\(\s*(?P<df>\d+)\s*(?:,\s*[Nn]\s*=\s*\d+\s*)?\)\s*=\s*(?P<stat>{_NUM})"
    rf"{_SEP}p\s*(?P<pop>{_POP})\s*(?P<p>{_NUM})",
    re.IGNORECASE,
)
_R_RE = re.compile(
    rf"\br\s*\(\s*(?P<df>\d+)\s*\)\s*=\s*(?P<stat>{_NUM})"
    rf"{_SEP}p\s*(?P<pop>{_POP})\s*(?P<p>{_NUM})",
    re.IGNORECASE,
)
_Z_RE = re.compile(
    rf"\bz\s*=\s*(?P<stat>{_NUM}){_SEP}p\s*(?P<pop>{_POP})\s*(?P<p>{_NUM})",
    re.IGNORECASE,
)

# Mean tied to a sample size within a short window (conservative for GRIM).
# The gap allows typical stat punctuation and decimals (e.g. "SD = 0.8") but a
# period only when it is a decimal point — never a sentence break — so a mean and
# an unrelated N in a later sentence are not paired.
_MEAN_RE = re.compile(
    r"\bM\s*=\s*(?P<mean>\d+\.\d+)"
    r"(?:[^.]|\.(?=\d)){0,40}?"
    r"\b[Nn]\s*=\s*(?P<n>\d+)",
)


def _finding(match: re.Match, test_type: str, **fields) -> dict:
    return {
        "test_type": test_type,
        "statistic": float(match.group("stat")),
        "statistic_str": match.group("stat"),
        "p_operator": match.group("pop"),
        "p_reported": float(match.group("p")),
        "p_reported_str": match.group("p"),
        "raw": match.group(0),
        "char_start": match.start(),
        "char_end": match.end(),
        **fields,
    }


def extract_stat_tests(text: str) -> list[dict]:
    """Extract reported NHST tests (t, F, chi2, r, z) with provenance offsets.

    Returns a list of dicts sorted by ``char_start``; each has ``test_type``,
    ``statistic``, ``p_operator`` (< > =), ``p_reported``, ``df``/``df1``/``df2``
    as applicable, ``raw``, and ``char_start``/``char_end``.
    """
    text = text or ""
    out: list[dict] = []
    for m in _T_RE.finditer(text):
        out.append(_finding(m, "t", df=float(m.group("df"))))
    for m in _F_RE.finditer(text):
        out.append(_finding(m, "F", df1=float(m.group("df1")), df2=float(m.group("df2"))))
    for m in _CHI2_RE.finditer(text):
        out.append(_finding(m, "chi2", df=float(m.group("df"))))
    for m in _R_RE.finditer(text):
        out.append(_finding(m, "r", df=float(m.group("df"))))
    for m in _Z_RE.finditer(text):
        out.append(_finding(m, "z", df=None))
    # Drop matches whose span is contained in an earlier (longer) match — e.g. a
    # bare 'z=' picked up inside a fuller report — keeping the widest one.
    out.sort(key=lambda d: (d["char_start"], -(d["char_end"] - d["char_start"])))
    kept: list[dict] = []
    last_end = -1
    for d in out:
        if d["char_start"] < last_end:
            continue
        kept.append(d)
        last_end = d["char_end"]
    return kept


def extract_means(text: str) -> list[dict]:
    """Extract reported means explicitly tied to a sample size (for GRIM).

    Conservative: only matches ``M = x.xx`` when an ``N = k`` / ``n = k`` appears
    within a short window, so unrelated means and sizes are never paired.
    Returns dicts with ``mean_str``, ``mean``, ``n``, ``raw``, and offsets.
    """
    text = text or ""
    out: list[dict] = []
    for m in _MEAN_RE.finditer(text):
        out.append({
            "mean_str": m.group("mean"),
            "mean": float(m.group("mean")),
            "n": int(m.group("n")),
            "raw": m.group(0),
            "char_start": m.start(),
            "char_end": m.end(),
        })
    return out
