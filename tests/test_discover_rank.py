"""tests/test_discover_rank.py — transparent ranking for discovery results.

Pure and offline: no network, no LLM.
"""
from __future__ import annotations

from research_companion.discover_rank import (
    DEFAULT_RANK,
    RANK_MODES,
    is_top_venue,
    rank_results,
    top_venue_name,
)


def _row(title, cites, year, venue=""):
    return {"title": title, "citation_count": cites, "year": year, "venue": venue}


def test_recognizes_venues_in_the_forms_sources_actually_report():
    assert top_venue_name("NeurIPS") == "NeurIPS"
    assert top_venue_name("Proc. of ACL 2024") == "ACL"
    assert top_venue_name("Conference on Empirical Methods (EMNLP)") == "EMNLP"
    assert is_top_venue("ICML")


def test_does_not_match_substrings_of_unrelated_words():
    # "acl" inside "Practical" must not make this a top venue
    assert top_venue_name("Practical Computing Weekly") is None
    assert top_venue_name("") is None
    assert top_venue_name(None) is None
    assert not is_top_venue("Some Random Workshop")


def test_citations_mode_orders_by_citation_count():
    rows = [_row("a", 10, 2020), _row("b", 5000, 2015), _row("c", 300, 2022)]
    assert [r["title"] for r in rank_results(rows, "citations")] == ["b", "c", "a"]


def test_venue_mode_puts_recognized_venues_first():
    rows = [_row("big-unknown", 5000, 2015, "Unknown Workshop"),
            _row("small-top", 12, 2025, "NeurIPS")]
    assert [r["title"] for r in rank_results(rows, "venue")] == ["small-top", "big-unknown"]


def test_balanced_surfaces_a_top_venue_without_burying_a_dominant_paper():
    rows = [_row("big-unknown", 5000, 2015, "Unknown Workshop"),
            _row("small-top", 12, 2025, "NeurIPS"),
            _row("mid", 300, 2022, "")]
    order = [r["title"] for r in rank_results(rows, "balanced")]
    # the dominant paper still wins, but the top-venue paper clears the mid-tier
    assert order[0] == "big-unknown"
    assert order.index("small-top") < order.index("mid")


def test_annotates_every_row_for_the_ui_badge():
    rows = [_row("a", 1, 2024, "ICLR"), _row("b", 1, 2024, "Nowhere")]
    out = rank_results(rows, "venue")
    by_title = {r["title"]: r for r in out}
    assert by_title["a"]["is_top_venue"] is True
    assert by_title["a"]["top_venue"] == "ICLR"
    assert by_title["b"]["is_top_venue"] is False
    assert by_title["b"]["top_venue"] is None


def test_ordering_is_deterministic_and_total():
    rows = [_row("b", 10, 2020), _row("a", 10, 2020), _row("c", 10, 2020)]
    first = [r["title"] for r in rank_results([dict(r) for r in rows], "balanced")]
    second = [r["title"] for r in rank_results([dict(r) for r in rows], "balanced")]
    assert first == second == ["a", "b", "c"]   # ties fall back to title


def test_unknown_mode_falls_back_and_never_raises():
    rows = [_row("a", 1, 2024)]
    assert rank_results(rows, "nonsense") == rank_results(rows, DEFAULT_RANK)
    assert rank_results(None, "citations") == []
    assert rank_results([{"title": "x"}, "junk", None], "venue")  # non-dicts dropped
    assert DEFAULT_RANK in RANK_MODES
