"""tests/test_brief.py — pure unit tests for research_companion/brief.py
(Brainstorm Brief: grounded, cited bullet outline). No network/LLM — the llm
callable is a stub."""
from __future__ import annotations

import json

from research_companion.brief import (
    _assemble_brief,
    _collect_paper_grounding,
    synthesize_brief,
)

PAPERS = [
    {"paper_id": "arxiv:1", "title": "Zep: Temporal KG", "year": 2025,
     "abstract": "episodic memory graph", "concepts": ["Temporal Knowledge Graph"]},
    {"paper_id": "arxiv:2", "title": "LongMemEval", "year": 2024,
     "abstract": "benchmark for long-term recall", "concepts": ["Long-term recall"]},
]


def test_collect_grounding_indexes_papers_with_keys():
    block, index = _collect_paper_grounding(PAPERS)
    assert len(index) == 2
    # every index key appears in the grounding block, tagged [p:...]
    for key in index:
        assert key.startswith("p:")
        assert f"[{key}]" in block


def test_assemble_drops_invented_and_uncited_bullets():
    _, index = _collect_paper_grounding(PAPERS)
    key = next(iter(index))
    llm_result = {"sections": [
        {"title": "Background", "bullets": [
            {"text": "grounded point", "grounded_in": [key]},
            {"text": "invented cite", "grounded_in": ["p:does-not-exist"]},
            {"text": "no cite at all", "grounded_in": []},
            {"text": "", "grounded_in": [key]},
        ]},
        {"title": "", "bullets": [{"text": "x", "grounded_in": [key]}]},  # no title -> dropped
    ]}
    sections = _assemble_brief(llm_result, index)
    assert len(sections) == 1
    assert sections[0]["title"] == "Background"
    # only the grounded, non-empty bullet survives
    assert [b["text"] for b in sections[0]["bullets"]] == ["grounded point"]
    assert sections[0]["bullets"][0]["citations"][0]["paper_id"] in {"arxiv:1", "arxiv:2"}


def test_synthesize_happy_path():
    def fake_llm(prompt: str) -> str:
        assert "[p:" in prompt  # grounding block present
        return json.dumps({"sections": [
            {"title": "Background", "bullets": [
                {"text": "TKGs store episodic memory", "grounded_in": ["p:arxiv:1"]},
            ]},
        ]})

    out = synthesize_brief("temporal knowledge graphs", PAPERS, llm=fake_llm)
    assert out["llm_error"] is None
    assert out["brief_id"].startswith("brief_")
    assert len(out["sections"]) == 1
    assert out["sections"][0]["bullets"][0]["citations"][0]["paper_id"] == "arxiv:1"


def test_empty_grounding_skips_llm_call():
    called = []
    out = synthesize_brief("topic", [], llm=lambda p: called.append(1) or "{}")
    assert out["sections"] == []
    assert out["llm_error"] is None
    assert called == []  # no papers -> nothing to cite -> no LLM call


def test_llm_failure_sets_llm_error_never_raises():
    def boom(prompt: str) -> str:
        raise RuntimeError("model down")

    out = synthesize_brief("t", PAPERS, llm=boom)
    assert out["sections"] == []
    assert "model down" in out["llm_error"]


def test_brief_id_is_deterministic_for_same_topic_and_direction():
    a = synthesize_brief("graph retrieval", [], llm=lambda p: "{}")
    b = synthesize_brief("graph retrieval", [], llm=lambda p: "{}")
    assert a["brief_id"] == b["brief_id"]
    c = synthesize_brief("graph retrieval", [],
                         direction={"title": "X"}, llm=lambda p: "{}")
    assert c["brief_id"] != a["brief_id"]
