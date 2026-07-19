"""Tests for research_companion.connectors registry (Task 5)."""
from __future__ import annotations

from research_companion import connectors
from research_companion.connectors.europepmc import EuropePMCConnector
from research_companion.connectors.pubmed import PubMedConnector


def test_enabled_connectors_orders_europepmc_first():
    got = connectors.enabled_connectors(["pubmed", "europepmc"])
    assert [type(c) for c in got] == [EuropePMCConnector, PubMedConnector]


def test_enabled_connectors_ignores_unknown_and_empty():
    assert connectors.enabled_connectors([]) == []
    assert connectors.enabled_connectors(["nope"]) == []


def test_valid_connectors_set():
    assert frozenset({"europepmc", "pubmed", "dblp"}) == connectors.VALID_CONNECTORS


def test_dblp_registered_and_valid():
    from research_companion.connectors import VALID_CONNECTORS, enabled_connectors
    from research_companion.connectors.dblp import DBLPConnector
    assert "dblp" in VALID_CONNECTORS
    conns = enabled_connectors(["dblp"])
    assert len(conns) == 1 and isinstance(conns[0], DBLPConnector)


def test_enabled_connectors_registry_order_is_europepmc_pubmed_dblp():
    from research_companion.connectors import enabled_connectors
    names = [c.name for c in enabled_connectors(["dblp", "pubmed", "europepmc"])]
    assert names == ["europepmc", "pubmed", "dblp"]
