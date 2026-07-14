"""Deterministic reproducibility / data-availability checker (Phase 3 #12).

Scans a paper's fulltext (and, optionally, its references) for the artifacts
that make a result reproducible: public code, public data, an availability
statement, methods-completeness signals, and reporting-checklist mentions
(EQUATOR family). Entirely LLM-free and pure so it is cheap and unit-testable.
"""
from __future__ import annotations

import re

# --- Link detectors ---------------------------------------------------------
# Code hosting.
_CODE_HOST_RE = re.compile(
    r"https?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org)/[^\s)\]}>,\"']+",
    re.IGNORECASE,
)
# Public data / artifact repositories (incl. dataset DOIs).
_DATA_HOST_RE = re.compile(
    r"https?://(?:www\.)?(?:zenodo\.org|osf\.io|figshare\.com|datadryad\.org|"
    r"dataverse\.[^\s/]+|huggingface\.co/datasets|kaggle\.com/(?:datasets|competitions)|"
    r"doi\.org/10\.5281|physionet\.org)[^\s)\]}>,\"']*",
    re.IGNORECASE,
)

# --- Statement / signal detectors -------------------------------------------
_AVAILABILITY_RE = re.compile(
    r"(code (?:is|are|will be)?\s*(?:publicly\s+)?available|"
    r"data availability|available (?:at|on|from)\s+https?://|"
    r"we (?:release|open[- ]?source|make (?:our )?(?:code|data) available)|"
    r"our code (?:and|/)?\s*(?:data)?\s*(?:is|are|will be)|"
    r"reproduc(?:e|ibility|ible)|artifact(?:s)? (?:are )?available|"
    r"supplementary (?:material|code))",
    re.IGNORECASE,
)

# Methods-completeness signals: each maps to a name -> compiled pattern.
_METHOD_SIGNALS = {
    "hyperparameters": re.compile(r"hyper[- ]?parameter", re.IGNORECASE),
    "training_details": re.compile(r"(training (?:details|procedure|setup)|learning rate|batch size|epochs?)", re.IGNORECASE),
    "compute": re.compile(r"(gpu|tpu|v100|a100|compute (?:budget|resources)|wall[- ]?clock)", re.IGNORECASE),
    "random_seed": re.compile(r"(random seed|fixed seed|seed(?:s)? (?:were|was|are|is) set|reproducib)", re.IGNORECASE),
    "dataset_details": re.compile(r"(train(?:ing)?/(?:val(?:idation)?|test) split|dataset (?:split|statistics)|number of (?:samples|examples))", re.IGNORECASE),
}

# Reporting checklists (EQUATOR network + ML cards).
_CHECKLISTS = {
    "PRISMA": re.compile(r"\bPRISMA\b"),
    "CONSORT": re.compile(r"\bCONSORT\b"),
    "STROBE": re.compile(r"\bSTROBE\b"),
    "ARRIVE": re.compile(r"\bARRIVE\b"),
    "datasheet": re.compile(r"datasheet(?:s)? for datasets", re.IGNORECASE),
    "model_card": re.compile(r"model card", re.IGNORECASE),
}


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def assess_reproducibility(fulltext: str, references: list[dict] | None = None) -> dict:
    """Assess reproducibility signals in *fulltext*.

    Returns a JSON-safe dict:
      {code_links, data_links, has_availability_statement, signals{name:bool},
       checklists[], level ("high"|"medium"|"low"), missing[]}
    """
    text = fulltext or ""
    # Include reference titles/urls in the link scan (some links live in refs).
    if references:
        text = text + "\n" + "\n".join(
            str(r.get("title", "")) for r in references if isinstance(r, dict))

    code_links = _dedup_keep_order(_CODE_HOST_RE.findall(text))
    data_links = _dedup_keep_order(_DATA_HOST_RE.findall(text))
    has_stmt = bool(_AVAILABILITY_RE.search(text))
    signals = {name: bool(rx.search(text)) for name, rx in _METHOD_SIGNALS.items()}
    checklists = [name for name, rx in _CHECKLISTS.items() if rx.search(text)]

    n_signals = sum(signals.values())
    score = (
        (1 if code_links else 0)
        + (1 if data_links else 0)
        + (1 if has_stmt else 0)
        + (1 if n_signals >= 2 else 0)
    )
    level = "high" if score >= 3 else ("medium" if score >= 1 else "low")

    missing: list[str] = []
    if not code_links:
        missing.append("No public code repository link found")
    if not data_links:
        missing.append("No public data/artifact repository link found")
    if not has_stmt:
        missing.append("No explicit code/data availability statement found")
    if n_signals < 2:
        missing.append("Methods lack reproducibility details (hyperparameters, "
                       "compute, seeds, splits)")

    return {
        "code_links": code_links,
        "data_links": data_links,
        "has_availability_statement": has_stmt,
        "signals": signals,
        "checklists": checklists,
        "level": level,
        "missing": missing,
    }
