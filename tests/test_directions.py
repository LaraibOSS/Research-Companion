"""Tests for research_companion.directions and its DIRECTIONS_PROMPT triad.

Pipeline under test (mirrors research_companion/gaps.py's synthesize_gaps
shape): _collect_grounding (pure) -> one DIRECTIONS_PROMPT call ->
_assemble_directions (pure, drops invented citation keys) -> rank_directions
(pure, deterministic score, stable sort) -> synthesize_directions
(orchestrator).
"""

from __future__ import annotations

import json

import networkx as nx

# ---------------------------------------------------------------------------
# DIRECTIONS_PROMPT triad (feat/brainstorm-directions, Task 1)
# ---------------------------------------------------------------------------

def test_directions_prompt_sha256_is_stable_and_64_hex_chars():
    from research_companion.prompts import directions_prompt_sha256
    sha = directions_prompt_sha256()
    assert sha == directions_prompt_sha256()
    assert len(sha) == 64
    int(sha, 16)  # raises ValueError if not hex


def test_format_directions_prompt_substitutes_topic_and_grounding_block():
    from research_companion.prompts import format_directions_prompt
    rendered = format_directions_prompt(
        topic="graph neural networks for code",
        grounding_block="- [p:arxiv:2401.00001] Some Paper (2024).",
    )
    assert "graph neural networks for code" in rendered
    assert "[p:arxiv:2401.00001] Some Paper (2024)." in rendered
    assert "<<TOPIC>>" not in rendered
    assert "<<GROUNDING_BLOCK>>" not in rendered


# ---------------------------------------------------------------------------
# _underexplored_concepts
# ---------------------------------------------------------------------------

def _concept_graph(counts: dict[str, int]) -> nx.Graph:
    """Build a minimal graph with one concept node per (name, paper_count)."""
    G = nx.Graph()
    for name, count in counts.items():
        G.add_node(f"concept::{name}", kind="concept", label=name, paper_count=count)
    return G


def test_underexplored_concepts_empty_graph_returns_empty():
    from research_companion.directions import _underexplored_concepts
    assert _underexplored_concepts(nx.Graph()) == []
    assert _underexplored_concepts(None) == []


def test_underexplored_concepts_ignores_zero_and_non_concept_nodes():
    from research_companion.directions import _underexplored_concepts
    G = _concept_graph({"a": 1, "b": 0})
    G.add_node("paper::x", kind="paper", label="X")
    out = _underexplored_concepts(G)
    names = [c["name"] for c in out]
    assert "a" in names
    assert "b" not in names  # paper_count 0 is not eligible
    assert "X" not in names  # not a concept node


def test_underexplored_concepts_returns_bottom_third_by_paper_count_stable():
    from research_companion.directions import _underexplored_concepts
    # 9 concepts, paper_count 1..9 -> bottom third = 3 lowest.
    G = _concept_graph({f"c{i}": i for i in range(1, 10)})
    out = _underexplored_concepts(G)
    assert [c["name"] for c in out] == ["c1", "c2", "c3"]
    assert [c["paper_count"] for c in out] == [1, 2, 3]


def test_underexplored_concepts_capped_at_cap():
    from research_companion.directions import _underexplored_concepts
    # 30 concepts, all paper_count=1 -> bottom third = 10, capped at cap=5.
    G = _concept_graph({f"c{i}": 1 for i in range(30)})
    out = _underexplored_concepts(G, cap=5)
    assert len(out) == 5


def test_underexplored_concepts_ties_broken_by_name_for_determinism():
    from research_companion.directions import _underexplored_concepts
    G = _concept_graph({"zeta": 1, "alpha": 1, "beta": 1})
    out = _underexplored_concepts(G)
    assert [c["name"] for c in out] == ["alpha", "beta", "zeta"]


# ---------------------------------------------------------------------------
# _collect_grounding
# ---------------------------------------------------------------------------

def test_collect_grounding_all_empty_returns_empty_block_and_index():
    from research_companion.directions import _collect_grounding
    block, index = _collect_grounding(
        "", [], library_papers=[], graph=None, gap_synthesis=None)
    assert block == ""
    assert index == {}


def test_collect_grounding_library_paper_gets_stable_p_key():
    from research_companion.directions import _collect_grounding
    lib = [{"paper_id": "arxiv:2401.00001", "title": "GraphRAG", "year": 2024,
            "abstract": "A method for graph retrieval.", "concepts": ["Graph Retrieval"]}]
    block, index = _collect_grounding(
        "graph retrieval", [], library_papers=lib, graph=None, gap_synthesis=None)
    assert "p:arxiv:2401.00001" in index
    assert index["p:arxiv:2401.00001"]["kind"] == "paper"
    assert index["p:arxiv:2401.00001"]["title"] == "GraphRAG"
    assert index["p:arxiv:2401.00001"]["paper_id"] == "arxiv:2401.00001"
    assert "[p:arxiv:2401.00001]" in block
    assert "GraphRAG" in block


def test_collect_grounding_dedupes_library_and_seed_by_identity_library_wins():
    from research_companion.directions import _collect_grounding
    lib = [{"paper_id": "doi:10.1/xyz", "title": "Library Copy", "year": 2022,
            "abstract": "", "concepts": []}]
    seeds = [{"title": "Seed Copy", "year": 2022, "abstract": "", "doi": "10.1/xyz",
              "arxiv_id": None, "s2_id": None, "pmid": None, "pmcid": None}]
    block, index = _collect_grounding(
        "topic", seeds, library_papers=lib, graph=None, gap_synthesis=None)
    paper_keys = [k for k in index if k.startswith("p:")]
    assert len(paper_keys) == 1
    assert index[paper_keys[0]]["title"] == "Library Copy"  # library iterated first, wins
    assert index[paper_keys[0]]["paper_id"] == "doi:10.1/xyz"


def test_collect_grounding_seed_only_paper_has_null_paper_id():
    from research_companion.directions import _collect_grounding
    seeds = [{"title": "Seed Only", "year": 2021, "abstract": "", "doi": "10.1/abc",
              "arxiv_id": None, "s2_id": None, "pmid": None, "pmcid": None}]
    _, index = _collect_grounding(
        "topic", seeds, library_papers=[], graph=None, gap_synthesis=None)
    paper_keys = [k for k in index if k.startswith("p:")]
    assert len(paper_keys) == 1
    assert index[paper_keys[0]]["paper_id"] is None


def test_collect_grounding_includes_underexplored_concepts_with_c_key():
    from research_companion.directions import _collect_grounding
    G = _concept_graph({"sparse thing": 1})
    block, index = _collect_grounding(
        "topic", [], library_papers=[], graph=G, gap_synthesis=None)
    keys = [k for k in index if k.startswith("c:")]
    assert len(keys) == 1
    assert index[keys[0]]["kind"] == "concept"
    assert index[keys[0]]["name"] == "sparse thing"
    assert "Underexplored concept: sparse thing" in block


def test_collect_grounding_includes_open_and_partial_gaps_not_addressed():
    from research_companion.directions import _collect_grounding
    gap_synthesis = {"themes": [
        {"theme_id": "theme_aaa", "title": "Missing benchmark", "bullet": "No shared benchmark exists.",
         "status": "open"},
        {"theme_id": "theme_bbb", "title": "Partial eval", "bullet": "Evaluation is incomplete.",
         "status": "partial"},
        {"theme_id": "theme_ccc", "title": "Already fixed", "bullet": "This was addressed.",
         "status": "addressed"},
    ]}
    block, index = _collect_grounding(
        "topic", [], library_papers=[], graph=None, gap_synthesis=gap_synthesis)
    gap_keys = sorted(k for k in index if k.startswith("g:"))
    assert gap_keys == ["g:theme_aaa", "g:theme_bbb"]
    assert index["g:theme_aaa"]["bullet"] == "No shared benchmark exists."
    assert "No shared benchmark exists." in block


def test_collect_grounding_empty_gap_synthesis_none_is_safe():
    from research_companion.directions import _collect_grounding
    block, index = _collect_grounding(
        "topic", [], library_papers=[], graph=None, gap_synthesis=None)
    assert index == {}
    assert block == ""


# ---------------------------------------------------------------------------
# _assemble_directions
# ---------------------------------------------------------------------------

def _paper_index_entry(paper_id="arxiv:2401.00001", title="Some Paper", year=2023):
    return {"kind": "paper", "title": title, "year": year, "paper_id": paper_id,
            "abstract": "", "concepts": []}


def test_assemble_directions_maps_grounded_in_keys_to_citations():
    from research_companion.directions import _assemble_directions
    index = {"p:arxiv:2401.00001": _paper_index_entry()}
    llm_result = {"directions": [{
        "title": "Extend method X", "rationale": "Because Some Paper shows Y.",
        "direction_type": "extend_method", "grounded_in": ["p:arxiv:2401.00001"],
    }]}
    out = _assemble_directions(llm_result, index)
    assert len(out) == 1
    d = out[0]
    assert d["title"] == "Extend method X"
    assert d["direction_type"] == "extend_method"
    assert d["citations"] == [{"kind": "paper", "paper_id": "arxiv:2401.00001",
                                "title": "Some Paper", "year": 2023}]
    assert d["grounding_count"] == 1
    assert d["recency"] == 2023
    assert d["direction_id"].startswith("dir_")


def test_assemble_directions_drops_invented_keys():
    from research_companion.directions import _assemble_directions
    index = {"p:arxiv:2401.00001": _paper_index_entry()}
    llm_result = {"directions": [{
        "title": "Direction", "rationale": "r", "direction_type": "other",
        "grounded_in": ["p:arxiv:2401.00001", "p:invented:9999"],
    }]}
    out = _assemble_directions(llm_result, index)
    assert len(out[0]["citations"]) == 1  # invented key silently dropped
    assert out[0]["grounding_count"] == 1


def test_assemble_directions_keeps_zero_grounding_direction_flagged():
    from research_companion.directions import _assemble_directions
    index = {"p:arxiv:2401.00001": _paper_index_entry()}
    llm_result = {"directions": [{
        "title": "All invented", "rationale": "r", "direction_type": "other",
        "grounded_in": ["p:totally:invented"],
    }]}
    out = _assemble_directions(llm_result, index)
    assert len(out) == 1  # kept, not discarded
    assert out[0]["citations"] == []
    assert out[0]["grounding_count"] == 0
    assert out[0]["recency"] == 0


def test_assemble_directions_grounding_count_is_distinct_papers_only():
    from research_companion.directions import _assemble_directions
    index = {
        "p:arxiv:2401.00001": _paper_index_entry(paper_id="arxiv:2401.00001"),
        "c:sparse": {"kind": "concept", "name": "sparse", "paper_count": 1},
        "g:theme_aaa": {"kind": "gap", "theme_id": "theme_aaa", "title": "Gap", "bullet": "b"},
    }
    llm_result = {"directions": [{
        "title": "Mixed", "rationale": "r", "direction_type": "cross_pollination",
        "grounded_in": ["p:arxiv:2401.00001", "c:sparse", "g:theme_aaa"],
    }]}
    out = _assemble_directions(llm_result, index)
    assert len(out[0]["citations"]) == 3  # all three kinds kept in citations
    assert out[0]["grounding_count"] == 1  # only the paper counts toward grounding_count


def test_assemble_directions_recency_is_max_cited_paper_year():
    from research_companion.directions import _assemble_directions
    index = {
        "p:a": _paper_index_entry(paper_id="a", year=2019),
        "p:b": _paper_index_entry(paper_id="b", year=2023),
    }
    llm_result = {"directions": [{
        "title": "T", "rationale": "r", "direction_type": "other",
        "grounded_in": ["p:a", "p:b"],
    }]}
    out = _assemble_directions(llm_result, index)
    assert out[0]["recency"] == 2023


def test_assemble_directions_unknown_type_falls_back_to_other():
    from research_companion.directions import _assemble_directions
    llm_result = {"directions": [{
        "title": "T", "rationale": "r", "direction_type": "not_a_real_type", "grounded_in": [],
    }]}
    out = _assemble_directions(llm_result, {})
    assert out[0]["direction_type"] == "other"


def test_assemble_directions_skips_entries_with_no_title():
    from research_companion.directions import _assemble_directions
    llm_result = {"directions": [
        {"title": "", "rationale": "r", "direction_type": "other", "grounded_in": []},
        {"title": "Real one", "rationale": "r", "direction_type": "other", "grounded_in": []},
    ]}
    out = _assemble_directions(llm_result, {})
    assert [d["title"] for d in out] == ["Real one"]


def test_assemble_directions_direction_id_is_deterministic_and_norm_insensitive():
    from research_companion.directions import _assemble_directions
    llm_result_a = {"directions": [{"title": "Extend BM25", "rationale": "r",
                                     "direction_type": "other", "grounded_in": []}]}
    llm_result_b = {"directions": [{"title": "  extend   bm25  ", "rationale": "r2",
                                     "direction_type": "other", "grounded_in": []}]}
    id_a = _assemble_directions(llm_result_a, {})[0]["direction_id"]
    id_b = _assemble_directions(llm_result_b, {})[0]["direction_id"]
    assert id_a == id_b  # same normalized title -> same id, regardless of casing/whitespace


def test_assemble_directions_empty_or_malformed_input_returns_empty():
    from research_companion.directions import _assemble_directions
    assert _assemble_directions({"directions": []}, {}) == []
    assert _assemble_directions({}, {}) == []
    assert _assemble_directions({"directions": "not-a-list"}, {}) == []
    assert _assemble_directions({"directions": [None, "not-a-dict"]}, {}) == []


# ---------------------------------------------------------------------------
# rank_directions
# ---------------------------------------------------------------------------

def _direction(title="T", grounding_count=0, recency=0, direction_type="other"):
    return {"direction_id": f"dir_{title}", "title": title, "rationale": "r",
            "direction_type": direction_type, "citations": [],
            "grounding_count": grounding_count, "recency": recency}


def test_rank_directions_higher_grounding_count_ranks_first():
    from research_companion.directions import rank_directions
    low = _direction("low", grounding_count=1, recency=2020)
    high = _direction("high", grounding_count=3, recency=2020)
    ranked = rank_directions([low, high])
    assert [d["title"] for d in ranked] == ["high", "low"]


def test_rank_directions_score_formula_is_exact():
    from research_companion.directions import rank_directions
    d = _direction("d", grounding_count=2, recency=2010, direction_type="open_gap")
    ranked = rank_directions([d])
    # 3.0*2 + 0.1*(2010-2000) + 2.0 (open_gap bonus) = 6 + 1.0 + 2.0 = 9.0
    assert ranked[0]["score"] == 9.0


def test_rank_directions_type_weight_bonus_open_gap_and_underexplored_concept():
    from research_companion.directions import rank_directions
    base = _direction("base", grounding_count=1, recency=2000, direction_type="other")
    gap = _direction("gap", grounding_count=1, recency=2000, direction_type="open_gap")
    concept = _direction("concept", grounding_count=1, recency=2000, direction_type="underexplored_concept")
    cross = _direction("cross", grounding_count=1, recency=2000, direction_type="cross_pollination")
    ranked = rank_directions([base, cross, concept, gap])
    assert [d["title"] for d in ranked] == ["gap", "concept", "cross", "base"]


def test_rank_directions_zero_grounding_sinks_to_bottom():
    from research_companion.directions import rank_directions
    grounded = _direction("grounded", grounding_count=1, recency=2024)
    ungrounded = _direction("ungrounded", grounding_count=0, recency=2024)
    ranked = rank_directions([ungrounded, grounded])
    assert [d["title"] for d in ranked] == ["grounded", "ungrounded"]


def test_rank_directions_stable_sort_ties_keep_llm_order():
    from research_companion.directions import rank_directions
    a = _direction("a", grounding_count=1, recency=2020)
    b = _direction("b", grounding_count=1, recency=2020)
    c = _direction("c", grounding_count=1, recency=2020)
    ranked = rank_directions([a, b, c])
    assert [d["title"] for d in ranked] == ["a", "b", "c"]


def test_rank_directions_does_not_mutate_input():
    from research_companion.directions import rank_directions
    d = _direction("d", grounding_count=1, recency=2020)
    rank_directions([d])
    assert "score" not in d


def test_rank_directions_empty_list_returns_empty():
    from research_companion.directions import rank_directions
    assert rank_directions([]) == []


# ---------------------------------------------------------------------------
# synthesize_directions
# ---------------------------------------------------------------------------

def test_synthesize_directions_empty_topic_empty_grounding_no_llm_call():
    from research_companion.directions import synthesize_directions

    def exploding_llm(prompt: str) -> str:
        raise AssertionError("llm must not be called when grounding is fully empty")

    out = synthesize_directions("", [], library_papers=[], graph=None,
                                 gap_synthesis=None, llm=exploding_llm)
    assert out["directions"] == []
    assert out["topic"] == ""
    assert "generated_from_sha" in out
    assert out["llm_error"] is None


def test_synthesize_directions_topic_only_no_grounding_still_calls_llm():
    from research_companion.directions import synthesize_directions
    calls = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"directions": []})

    out = synthesize_directions("some topic", [], library_papers=[], graph=None,
                                 gap_synthesis=None, llm=fake_llm)
    assert len(calls) == 1
    assert "some topic" in calls[0]
    assert out["directions"] == []
    # A successful call that legitimately yields zero directions is NOT an
    # error -- llm_error must stay None so the caller shows the empty state,
    # not a retry banner.
    assert out["llm_error"] is None


def test_synthesize_directions_happy_path_with_stub_llm():
    from research_companion.directions import synthesize_directions
    lib = [{"paper_id": "arxiv:2401.00001", "title": "GraphRAG", "year": 2024,
            "abstract": "Graph-based retrieval.", "concepts": ["Graph Retrieval"]}]

    def fake_llm(prompt: str) -> str:
        assert "p:arxiv:2401.00001" in prompt
        return json.dumps({"directions": [{
            "title": "Extend GraphRAG to code",
            "rationale": "Apply graph retrieval to source-code search.",
            "direction_type": "new_application",
            "grounded_in": ["p:arxiv:2401.00001"],
        }]})

    out = synthesize_directions("graph retrieval", [], library_papers=lib, graph=None,
                                 gap_synthesis=None, llm=fake_llm)
    assert out["topic"] == "graph retrieval"
    assert len(out["directions"]) == 1
    d = out["directions"][0]
    assert d["title"] == "Extend GraphRAG to code"
    assert d["grounding_count"] == 1
    assert d["score"] > 0


def test_synthesize_directions_malformed_json_returns_empty_list_no_raise():
    from research_companion.directions import synthesize_directions

    def bad_llm(prompt: str) -> str:
        return "not json at all"

    out = synthesize_directions("topic", [], library_papers=[], graph=None,
                                 gap_synthesis=None, llm=bad_llm)
    assert out["directions"] == []
    # A parse failure is a retryable failure -> surfaced via llm_error.
    assert out["llm_error"]


def test_synthesize_directions_llm_exception_returns_empty_list_no_raise():
    from research_companion.directions import synthesize_directions

    def raising_llm(prompt: str) -> str:
        raise RuntimeError("provider unreachable")

    out = synthesize_directions("topic", [], library_papers=[], graph=None,
                                 gap_synthesis=None, llm=raising_llm)
    assert out["directions"] == []
    # The call failure is surfaced (not swallowed silently) so the endpoint
    # can show a retry banner instead of a false empty result.
    assert out["llm_error"] and "provider unreachable" in out["llm_error"]


def test_synthesize_directions_strips_markdown_code_fences():
    from research_companion.directions import synthesize_directions

    def fenced_llm(prompt: str) -> str:
        return "```json\n" + json.dumps({"directions": [{
            "title": "Fenced", "rationale": "r", "direction_type": "other", "grounded_in": [],
        }]}) + "\n```"

    out = synthesize_directions("topic", [], library_papers=[], graph=None,
                                 gap_synthesis=None, llm=fenced_llm)
    assert [d["title"] for d in out["directions"]] == ["Fenced"]


def test_synthesize_directions_none_llm_degrades_to_empty_list():
    from research_companion.directions import synthesize_directions
    out = synthesize_directions("topic", [], library_papers=[], graph=None,
                                 gap_synthesis=None, llm=None)
    assert out["directions"] == []


def test_synthesize_directions_seeds_only_no_library_still_grounds():
    from research_companion.directions import synthesize_directions
    seeds = [{"title": "Seed Paper", "year": 2023, "abstract": "", "doi": "10.1/xyz",
              "arxiv_id": None, "s2_id": None, "pmid": None, "pmcid": None}]

    def fake_llm(prompt: str) -> str:
        assert "p:doi:10.1/xyz" in prompt
        return json.dumps({"directions": [{
            "title": "From seed", "rationale": "r", "direction_type": "other",
            "grounded_in": ["p:doi:10.1/xyz"],
        }]})

    out = synthesize_directions("", seeds, library_papers=[], graph=None,
                                 gap_synthesis=None, llm=fake_llm)
    assert len(out["directions"]) == 1
    assert out["directions"][0]["citations"][0]["paper_id"] is None  # not in the library
