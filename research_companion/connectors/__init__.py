"""Domain connectors for biomedical scholarly sources (opt-in)."""
from __future__ import annotations

from research_companion.connectors.dblp import DBLPConnector
from research_companion.connectors.europepmc import EuropePMCConnector
from research_companion.connectors.pubmed import PubMedConnector

# Registry order = resolution/merge priority: Europe PMC first, PubMed second, DBLP third.
CONNECTORS: dict[str, type] = {
    "europepmc": EuropePMCConnector,
    "pubmed": PubMedConnector,
    "dblp": DBLPConnector,
}
VALID_CONNECTORS = frozenset(CONNECTORS)


def enabled_connectors(names) -> list:
    """Instantiate enabled connectors in registry order, ignoring unknowns."""
    wanted = set(names or [])
    return [cls() for key, cls in CONNECTORS.items() if key in wanted]
