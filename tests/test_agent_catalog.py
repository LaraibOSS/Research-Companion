"""The agent catalogue must describe the agents that exist, as they behave.

A catalogue is prose and declarations about code. Nothing at runtime checks
either, so both would drift into confident fiction. These tests read each
agent's source and hold the card to it.
"""
from __future__ import annotations

import inspect
import re

import pytest

from research_companion.agents import catalog
from research_companion.agents.catalog import (
    CARDS,
    COSTS,
    EXTERNAL_INPUTS,
    STAGES,
    agent_classes,
    contract_problems,
)

_READ = re.compile(r'ctx\.data(?:\.get\(|\[)\s*"(_[a-z_]+)"')
_WRITE = re.compile(r'ctx\.data\[\s*"(_[a-z_]+)"\s*\]\s*=')


def _source_keys(cls) -> tuple[set[str], set[str]]:
    src = inspect.getsource(inspect.getmodule(cls))
    writes = set(_WRITE.findall(src))
    return set(_READ.findall(src)) - writes, writes


def test_the_contracts_are_sound():
    assert contract_problems() == []


def test_every_agent_has_exactly_one_card():
    names = [c.name for c in CARDS]
    assert len(names) == len(set(names))
    assert set(names) == set(agent_classes())


@pytest.mark.parametrize("card", CARDS, ids=lambda c: c.name)
def test_declared_keys_match_what_the_code_reads_and_writes(card):
    reads, writes = _source_keys(agent_classes()[card.name])
    assert set(card.reads) == reads, f"{card.name}: card reads differ from the source"
    assert set(card.writes) == writes, f"{card.name}: card writes differ from the source"


@pytest.mark.parametrize("card", CARDS, ids=lambda c: c.name)
def test_cost_is_not_understated(card):
    src = inspect.getsource(inspect.getmodule(agent_classes()[card.name]))
    if '"_llm"' in src:
        assert card.cost == "model"
    elif any(k in src for k in ('"_lookup"', '"_search"', '"_search_recent"')):
        assert card.cost == "network"
    else:
        assert card.cost == "free"


@pytest.mark.parametrize("card", CARDS, ids=lambda c: c.name)
def test_cards_are_written_for_a_reader(card):
    assert card.stage in STAGES and card.cost in COSTS
    assert card.title and card.title[0].isupper()
    assert card.does.endswith(".") and len(card.does) <= 140
    # Plain words: the internal names and jargon stay out of the description.
    for term in ("ctx", "LLM", "DAG", "blackboard", "_llm", "pipeline"):
        assert term not in card.does


def test_reachability_claims_match_the_commands_that_build_agent_lists():
    """`reachable_from` says which commands start an agent. Hold it to the two
    places that construct agent lists."""
    from research_companion import review_runner

    in_review = {a.name for a in review_runner._build_agents(venue="neurips", fast=False)}
    for card in CARDS:
        assert ("review" in card.reachable_from) == (card.name in in_review), card.name

    cli_src = inspect.getsource(__import__("research_companion.cli", fromlist=["x"]))
    for card in CARDS:
        cls_name = agent_classes()[card.name].__name__
        assert bool(card.reachable_from) == (f"{cls_name}(" in cli_src), card.name


def test_a_read_from_an_agent_not_depended_on_is_reported(monkeypatch):
    """The failure the contract exists to catch: reading a value whose writer
    may not have run yet."""
    bad = tuple(
        c if c.name != "ethics" else catalog.AgentCard(
            "ethics", c.title, c.does, c.stage, c.cost, reads=("_priorart_papers",))
        for c in CARDS)
    monkeypatch.setattr(catalog, "CARDS", bad)
    problems = contract_problems()
    assert any("ethics: reads _priorart_papers from priorart without depending" in p
               for p in problems)


def test_handoffs_name_what_is_passed():
    edges = {(e["from"], e["to"]): e for e in catalog.handoffs()}
    assert "_priorart_papers" in edges[("priorart", "novelty")]["passes"]
    assert edges[("citation", "severity")]["passes"] == ["citation"]
    # A hand-off through an indirect dependency is marked as such.
    assert edges[("ingest", "benchmark")]["direct"] is True
    assert all(e["from"] != e["to"] for e in edges.values())


def test_catalog_rows_are_json_safe_and_in_stage_order():
    import json

    rows = catalog.catalog()
    json.dumps(rows)
    order = [STAGES.index(r["stage"]) for r in rows]
    assert order == sorted(order)
    assert {r["name"] for r in rows} == set(agent_classes())
    assert all(k not in EXTERNAL_INPUTS for r in rows for k in r["writes"])
