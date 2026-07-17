"""Agent role/summary strings must respect the honesty boundary — no overclaims.

The project's identity is "never claim more than we compute": an unverified
citation is not "fabricated", and PriorArtAgent finds related work but does not
write the knowledge graph. These regressions lock that wording.
"""
from research_companion.agents.citation import CitationAgent
from research_companion.agents.priorart import PriorArtAgent


def test_citation_role_does_not_overclaim_fabrication():
    role = CitationAgent.role.lower()
    assert "fabricated" not in role, \
        "unverified != fabricated; report verified/suspect/unverified"
    assert "verified" in role


def test_priorart_role_and_summary_do_not_claim_graph_mapping():
    role = PriorArtAgent.role.lower()
    assert "onto the graph" not in role and "maps it onto" not in role, \
        "PriorArtAgent returns related work; it does not write the knowledge graph"
