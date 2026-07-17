"""Deterministic advisory nudges. Pure; no network, no LLM."""
from __future__ import annotations

from research_companion.refcheck.validate import Reference


def connectors_nudge(references: list[Reference], *, connectors_enabled: bool,
                      discipline: str | None) -> str | None:
    """Suggest enabling biomedical connectors when the paper looks biomedical
    and they are off. Returns one line, or None."""
    if connectors_enabled:
        return None
    pmid_refs = sum(1 for r in references if getattr(r, "pmid", None) or getattr(r, "pmcid", None))
    is_biomed = (discipline or "").lower() in {"biomedical", "biology", "medicine"}
    if pmid_refs == 0 and not is_biomed:
        return None
    detail = (f"{pmid_refs} reference(s) look biomedical"
              if pmid_refs else "this paper looks biomedical")
    return (f"{detail} — enable the PubMed/Europe PMC connectors to verify them "
            f"(`--connectors europepmc,pubmed` or Settings ▸ Connectors).")
