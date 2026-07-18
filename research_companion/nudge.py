"""Deterministic advisory nudges. Pure; no network, no LLM."""
from __future__ import annotations

from research_companion.refcheck.validate import Reference

CS_DISCIPLINES = {"machine_learning", "nlp", "computer_vision", "data_mining_ir"}
_BIOMED_CONNECTORS = {"europepmc", "pubmed"}
_BIOMED_DISCIPLINES = {"biomedical", "biology", "medicine"}


def connectors_nudge(references: list[Reference], *, enabled: set[str],
                      discipline: str | None, n_unverified: int = 0) -> str | None:
    """Suggest enabling a domain connector when it would help and it is off.

    Biomedical suggestion takes precedence over the DBLP/CS one. Returns one
    line, or None.
    """
    enabled = set(enabled or ())
    disc = (discipline or "").lower()

    # Biomedical: paper looks biomedical and neither biomedical connector is on.
    if not (_BIOMED_CONNECTORS & enabled):
        pmid_refs = sum(1 for r in references
                        if getattr(r, "pmid", None) or getattr(r, "pmcid", None))
        if pmid_refs or disc in _BIOMED_DISCIPLINES:
            detail = (f"{pmid_refs} reference(s) look biomedical"
                      if pmid_refs else "this paper looks biomedical")
            return (f"{detail} — enable the PubMed/Europe PMC connectors to verify them "
                    f"(`--connectors europepmc,pubmed` or Settings ▸ Connectors).")

    # DBLP/CS: a CS paper with unverified refs and DBLP off.
    if "dblp" not in enabled and disc in CS_DISCIPLINES and n_unverified > 0:
        return (f"{n_unverified} reference(s) are unverified and this looks like a CS paper "
                f"— enable the DBLP connector to check them "
                f"(`--connectors dblp` or Settings ▸ Connectors).")

    return None
