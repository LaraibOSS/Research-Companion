"""LaTeX citation reading — deterministic, no dependencies.

Extracts ``\\cite``-family keys from a ``.tex`` source and resolves them against a
parsed ``.bib`` file, so a LaTeX-native draft gets the same citation-coverage
signal the Lab gives a PDF draft — which of the works you cite you actually have
bibliography entries for — without needing a compiled PDF.
"""
from __future__ import annotations

import re

from research_companion.interop.bibtex import parse_bibtex

# \cite, \citep, \citet, \citealp, \citeauthor, \parencite, \textcite, \footcite,
# \autocite, \Cite, ... with optional [pre][post] options and a * variant.
_CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|parencite|"
    r"textcite|autocite|footcite|smartcite|Cite|Citep|Citet)\*?"
    r"(?:\[[^\]]*\])*"
    r"\{([^}]*)\}",
    re.IGNORECASE,
)

# Strip LaTeX comments (unescaped %) so commented-out citations are ignored.
_COMMENT_RE = re.compile(r"(?<!\\)%.*")


def extract_cite_keys(tex: str) -> list[str]:
    """Return the ordered, de-duplicated list of cite keys used in *tex*."""
    tex = tex or ""
    tex = _COMMENT_RE.sub("", tex)
    keys: list[str] = []
    seen: set[str] = set()
    for m in _CITE_RE.finditer(tex):
        for raw in m.group(1).split(","):
            key = raw.strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def resolve_tex_citations(tex: str, bib_text: str) -> dict:
    """Resolve a draft's cite keys against a ``.bib`` file.

    Returns a JSON-safe dict:
      {cited_keys, resolved (keys with a bib entry), missing (keys without one),
       unused (bib keys never cited), coverage ("R of C cited keys resolved")}.
    """
    cited = extract_cite_keys(tex)
    entries = parse_bibtex(bib_text or "")
    by_key = {e["key"]: e for e in entries}

    resolved = [k for k in cited if k in by_key]
    missing = [k for k in cited if k not in by_key]
    unused = [e["key"] for e in entries if e["key"] not in set(cited)]

    return {
        "cited_keys": cited,
        "resolved": resolved,
        "missing": missing,
        "unused": unused,
        "coverage": f"{len(resolved)} of {len(cited)} cited keys resolved",
    }
