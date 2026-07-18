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
    assert frozenset({"europepmc", "pubmed"}) == connectors.VALID_CONNECTORS
