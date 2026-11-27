"""One plain line per agent result: what it found, with its denominator.

"Done" tells a researcher nothing. Each agent returns its own data shape; this
reads that shape and says what happened in words, including when there was
nothing to examine. It never interprets beyond the numbers the agent returned,
and an unknown or malformed shape yields None (the page then shows no line)
rather than a guess.
"""
from __future__ import annotations

from collections.abc import Callable


def _n(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _ingest(d: dict) -> str:
    return f"Read the paper. Your library graph now has {_plural(_n(d.get('graph_nodes')), 'node')}."


def _priorart(d: dict) -> str:
    n = _n(d.get("count"))
    return f"Found {_plural(n, 'related paper')}." if n else "The search found no related papers."


def _citation(d: dict) -> str:
    c = d.get("counts") or {}
    total = _n(c.get("verified")) + _n(c.get("suspect")) + _n(c.get("unverified"))
    if not total:
        return "No references were found to check."
    return (f"{_n(c.get('verified'))} found, {_n(c.get('suspect'))} with mismatched details, "
            f"{_n(c.get('unverified'))} not found, of {total} references.")


def _summary_text(d: dict) -> str | None:
    s = d.get("summary")
    if isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"]:
        text = s["text"]
        return text[0].upper() + text[1:] + ("" if text.endswith(".") else ".")
    return None


def _compliance(d: dict) -> str:
    checks = d.get("checks") or []
    applied = [c for c in checks if c.get("status") in ("ok", "finding")]
    if not applied:
        return "No venue rule could be applied."
    findings = [c for c in applied if c.get("status") == "finding"]
    if not findings:
        return f"No problems in the {_plural(len(applied), 'rule')} that applied."
    return f"{_plural(len(findings), 'problem')} in {_plural(len(applied), 'rule')} checked."


def _reproducibility(d: dict) -> str:
    code, data = len(d.get("code_links") or []), len(d.get("data_links") or [])
    stmt = "an availability statement" if d.get("has_availability_statement") \
        else "no availability statement"
    return (f"{_plural(code, 'code link')}, {_plural(data, 'data link')}, {stmt}. "
            f"Level: {d.get('level') or 'unknown'}.")


def _ethics(d: dict) -> str:
    present = len(d.get("present") or [])
    missing = d.get("missing_expected") or []
    line = f"{_plural(present, 'declaration')} found."
    if missing:
        line += f" Expected but missing: {', '.join(str(m) for m in missing)}."
    return line


def _counts_line(d: dict, order: tuple[str, ...], nothing: str) -> str:
    c = d.get("counts") or {}
    parts = [f"{_n(c.get(k))} {k.replace('_', ' ')}" for k in order if _n(c.get(k))]
    return ", ".join(parts) + "." if parts else nothing


def _novelty(d: dict) -> str:
    return _counts_line(d, ("novel", "incremental", "overlaps", "anticipated", "unassessed"),
                        "No contribution could be assessed.")


def _severity(d: dict) -> str:
    return _counts_line(d, ("critical", "major", "minor"), "Nothing to rank.")


def _taxonomy(d: dict) -> str:
    n = _n(d.get("count"))
    return f"Grouped related work into {_plural(n, 'theme')}." if n else "No themes formed."


def _benchmark(d: dict) -> str:
    n = len(d.get("suggestions") or [])
    return f"Suggested {_plural(n, 'benchmark')}." if n else "No benchmarks to suggest."


def _venuefit(d: dict) -> str | None:
    if d.get("skipped"):
        return f"Not assessed: {d.get('reason') or 'no venue'}."
    fit = d.get("fit")
    return f"Fit with the venue: {fit}." if fit else None


def _tracker(d: dict) -> str:
    n = _n(d.get("count"))
    return f"Found {_plural(n, 'recent paper')} on this topic." if n else "No recent papers found."


def _confidence(d: dict) -> str:
    n = len(d.get("claims") or [])
    return f"Scored {_plural(n, 'claim')}." if n else "No claims to score."


def _citation_polarity(d: dict) -> str:
    n = len(d.get("citations") or [])
    return f"Labelled {_plural(n, 'citation')}." if n else "No citations to label."


_HEADLINES: dict[str, Callable[[dict], str | None]] = {
    "ingest": _ingest,
    "priorart": _priorart,
    "citation": _citation,
    "statsoundness": _summary_text,
    "overlap": _summary_text,
    "compliance": _compliance,
    "reproducibility": _reproducibility,
    "ethics": _ethics,
    "novelty": _novelty,
    "severity": _severity,
    "taxonomy": _taxonomy,
    "benchmark": _benchmark,
    "venuefit": _venuefit,
    "tracker": _tracker,
    "confidence": _confidence,
    "citation_polarity": _citation_polarity,
}


def headline(agent: str, data: dict | None) -> str | None:
    """A plain sentence for one agent's successful result, or None."""
    fn = _HEADLINES.get(agent)
    if fn is None or not isinstance(data, dict):
        return None
    try:
        return fn(data)
    except Exception:  # noqa: BLE001 - a malformed result shows no line, never a wrong one
        return None
