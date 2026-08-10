"""Tests for research_companion.rcs — Report Evidence Scoring (RCS),
slice 2e-2 -- and its RCS_PROMPT triad.

Pipeline under test: _chunk_text (slice a citation's REAL cited text out of
store.load_text[char_start:char_end], defensive -> "" never raises) ->
_chunks_block (numbered, truncated, skips unscorable/empty-text citations)
-> score_section (one RCS_PROMPT LLM call per section, batched like
gaps.synthesize_gaps; never raises) -> _normalize_scores (drop invented
refs, clamp relevance, normalize stance) -> score_report (pure
orchestration over a saved report's sections; never raises).

HONESTY: a citation whose chunk can't be loaded is left unscored -- never
a guessed score. The LLM may only score listed refs; an invented ref is
dropped. RCS is a MODEL JUDGMENT, never "verified".
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# RCS_PROMPT triad (Task 1)
# ---------------------------------------------------------------------------

def test_rcs_prompt_sha256_is_stable_and_64_hex_chars():
    from research_companion.prompts import rcs_prompt_sha256
    sha = rcs_prompt_sha256()
    assert sha == rcs_prompt_sha256()
    assert len(sha) == 64
    int(sha, 16)  # raises ValueError if not hex


def test_format_rcs_prompt_substitutes_all_placeholders():
    from research_companion.prompts import format_rcs_prompt
    rendered = format_rcs_prompt(
        question="What retrieval methods does the library use?",
        answer="BM25 and dense retrieval are used [S1].",
        chunks_block="[0] Paper One -- some chunk text.",
    )
    assert "What retrieval methods does the library use?" in rendered
    assert "BM25 and dense retrieval are used [S1]." in rendered
    assert "[0] Paper One -- some chunk text." in rendered
    assert "<<QUESTION>>" not in rendered
    assert "<<ANSWER>>" not in rendered
    assert "<<CHUNKS_BLOCK>>" not in rendered



# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------

def test_chunk_text_slices_real_text():
    from research_companion.rcs import _chunk_text

    citation = {"paper_id": "p1", "char_start": 6, "char_end": 11}
    text = _chunk_text(citation, load_text_fn=lambda pid: "Hello world, more." if pid == "p1" else None)
    assert text == "world"


def test_chunk_text_none_load_text_returns_empty():
    from research_companion.rcs import _chunk_text
    text = _chunk_text({"paper_id": "p1", "char_start": 0, "char_end": 5},
                        load_text_fn=lambda pid: None)
    assert text == ""


def test_chunk_text_missing_paper_id_returns_empty():
    from research_companion.rcs import _chunk_text
    text = _chunk_text({"char_start": 0, "char_end": 5}, load_text_fn=lambda pid: "text")
    assert text == ""


def test_chunk_text_out_of_range_offsets_return_empty():
    from research_companion.rcs import _chunk_text
    text = _chunk_text({"paper_id": "p1", "char_start": 100, "char_end": 200},
                        load_text_fn=lambda pid: "short text")
    assert text == ""


def test_chunk_text_reversed_offsets_return_empty():
    from research_companion.rcs import _chunk_text
    text = _chunk_text({"paper_id": "p1", "char_start": 10, "char_end": 2},
                        load_text_fn=lambda pid: "some longer text here")
    assert text == ""


def test_chunk_text_non_dict_citation_returns_empty():
    from research_companion.rcs import _chunk_text
    assert _chunk_text("not a dict", load_text_fn=lambda pid: "text") == ""


def test_chunk_text_load_text_fn_raising_returns_empty_no_raise():
    from research_companion.rcs import _chunk_text

    def raising_loader(pid):
        raise RuntimeError("disk error")

    text = _chunk_text({"paper_id": "p1", "char_start": 0, "char_end": 5}, load_text_fn=raising_loader)
    assert text == ""


# ---------------------------------------------------------------------------
# _chunks_block
# ---------------------------------------------------------------------------

def test_chunks_block_builds_numbered_block_and_ref_mapping():
    from research_companion.rcs import _chunks_block

    citations = [{"paper_title": "Paper One"}, {"paper_title": "Paper Two"}]
    chunk_texts = ["Hello world", "Goodbye now"]
    block, ref_to_index = _chunks_block(citations, chunk_texts)
    assert block == "[0] Paper One -- Hello world\n[1] Paper Two -- Goodbye now"
    assert ref_to_index == {0: 0, 1: 1}


def test_chunks_block_skips_empty_chunk_text_citations():
    from research_companion.rcs import _chunks_block

    citations = [{"paper_title": "P0"}, {"paper_title": "P1"}, {"paper_title": "P2"}]
    chunk_texts = ["Real text here", "", "More real text"]
    block, ref_to_index = _chunks_block(citations, chunk_texts)
    assert block == "[0] P0 -- Real text here\n[1] P2 -- More real text"
    assert ref_to_index == {0: 0, 1: 2}


def test_chunks_block_truncates_long_chunk_text():
    from research_companion.rcs import _chunks_block

    long_text = "x" * 500
    block, ref_to_index = _chunks_block([{"paper_title": "P0"}], [long_text])
    assert block == "[0] P0 -- " + "x" * 400
    assert ref_to_index == {0: 0}


def test_chunks_block_untitled_when_no_paper_title():
    from research_companion.rcs import _chunks_block
    block, ref_to_index = _chunks_block([{}], ["some text"])
    assert block == "[0] Untitled -- some text"


def test_chunks_block_empty_when_all_citations_unscorable():
    from research_companion.rcs import _chunks_block
    block, ref_to_index = _chunks_block([{"paper_title": "P0"}], [""])
    assert block == ""
    assert ref_to_index == {}


# ---------------------------------------------------------------------------
# _normalize_scores
# ---------------------------------------------------------------------------

def test_normalize_scores_drops_out_of_range_refs():
    from research_companion.rcs import _normalize_scores
    parsed = {"scores": [
        {"ref": 0, "relevance": 0.5, "stance": "supports", "rationale": "ok"},
        {"ref": 5, "relevance": 0.9, "stance": "supports", "rationale": "invented"},
    ]}
    out = _normalize_scores(parsed, {0, 1})
    assert out == {0: {"relevance": 0.5, "stance": "supports", "rationale": "ok"}}


def test_normalize_scores_clamps_relevance():
    from research_companion.rcs import _normalize_scores
    parsed = {"scores": [
        {"ref": 0, "relevance": 5.0, "stance": "supports", "rationale": "ok"},
        {"ref": 1, "relevance": -3.0, "stance": "neutral", "rationale": "ok"},
    ]}
    out = _normalize_scores(parsed, {0, 1})
    assert out[0]["relevance"] == 1.0
    assert out[1]["relevance"] == 0.0


def test_normalize_scores_normalizes_unknown_stance_to_neutral():
    from research_companion.rcs import _normalize_scores
    parsed = {"scores": [{"ref": 0, "relevance": 0.5, "stance": "bogus", "rationale": "ok"}]}
    out = _normalize_scores(parsed, {0})
    assert out[0]["stance"] == "neutral"


def test_normalize_scores_non_list_scores_returns_empty():
    from research_companion.rcs import _normalize_scores
    assert _normalize_scores({"scores": "not a list"}, {0}) == {}
    assert _normalize_scores({"not_scores": []}, {0}) == {}
    assert _normalize_scores("not a dict", {0}) == {}
    assert _normalize_scores(None, {0}) == {}


def test_normalize_scores_coerces_rationale_to_str():
    from research_companion.rcs import _normalize_scores
    parsed = {"scores": [{"ref": 0, "relevance": 0.5, "stance": "neutral", "rationale": 42}]}
    out = _normalize_scores(parsed, {0})
    assert out[0]["rationale"] == "42"


def test_normalize_scores_skips_non_dict_entries_and_missing_ref():
    from research_companion.rcs import _normalize_scores
    parsed = {"scores": [
        "not a dict",
        {"relevance": 0.5, "stance": "supports", "rationale": "no ref"},
        {"ref": 0, "relevance": 0.5, "stance": "supports", "rationale": "ok"},
    ]}
    out = _normalize_scores(parsed, {0})
    assert out == {0: {"relevance": 0.5, "stance": "supports", "rationale": "ok"}}


# ---------------------------------------------------------------------------
# score_section
# ---------------------------------------------------------------------------

def _stub_load_text(paper_texts):
    def _load(paper_id):
        return paper_texts.get(paper_id)
    return _load


def test_score_section_attaches_rcs_per_real_chunk():
    from research_companion.rcs import score_section

    citations = [
        {"paper_id": "p1", "paper_title": "Paper One", "char_start": 0, "char_end": 11},
        {"paper_id": "p2", "paper_title": "Paper Two", "char_start": 0, "char_end": 5},
    ]
    load_text_fn = _stub_load_text({"p1": "Hello world, more text here.", "p2": None})

    def fake_llm(prompt: str) -> str:
        assert "[0] Paper One" in prompt
        assert "Hello world" in prompt
        return json.dumps({"scores": [
            {"ref": 0, "relevance": 0.9, "stance": "supports", "rationale": "Directly relevant."},
        ]})

    results = score_section(
        "What is discussed?", "It discusses X.", citations,
        load_text_fn=load_text_fn, llm=fake_llm,
    )
    assert results[0] == {"relevance": 0.9, "stance": "supports", "rationale": "Directly relevant."}
    assert results[1] is None  # p2's load_text_fn returned None -> no loadable chunk


def test_score_section_no_scorable_chunks_skips_llm_call():
    from research_companion.rcs import score_section

    def exploding_llm(prompt):
        raise AssertionError("must not be called")

    citations = [{"paper_id": "p1", "char_start": 0, "char_end": 10}]
    load_text_fn = _stub_load_text({})  # p1 not found -> None

    results = score_section("Q", "A", citations, load_text_fn=load_text_fn, llm=exploding_llm)
    assert results == [None]


def test_score_section_malformed_llm_json_returns_all_none_no_raise():
    from research_companion.rcs import score_section

    citations = [{"paper_id": "p1", "char_start": 0, "char_end": 5}]
    load_text_fn = _stub_load_text({"p1": "Hello world"})

    def bad_llm(prompt):
        return "not json"

    results = score_section("Q", "A", citations, load_text_fn=load_text_fn, llm=bad_llm)
    assert results == [None]


def test_score_section_llm_raises_returns_all_none_no_raise():
    from research_companion.rcs import score_section

    citations = [{"paper_id": "p1", "char_start": 0, "char_end": 5}]
    load_text_fn = _stub_load_text({"p1": "Hello world"})

    def raising_llm(prompt):
        raise RuntimeError("provider down")

    results = score_section("Q", "A", citations, load_text_fn=load_text_fn, llm=raising_llm)
    assert results == [None]


def test_score_section_drops_invented_ref():
    from research_companion.rcs import score_section

    citations = [{"paper_id": "p1", "char_start": 0, "char_end": 5}]
    load_text_fn = _stub_load_text({"p1": "Hello world"})

    def fake_llm(prompt):
        return json.dumps({"scores": [
            {"ref": 0, "relevance": 0.5, "stance": "neutral", "rationale": "ok"},
            {"ref": 99, "relevance": 1.0, "stance": "supports", "rationale": "invented"},
        ]})

    results = score_section("Q", "A", citations, load_text_fn=load_text_fn, llm=fake_llm)
    assert results == [{"relevance": 0.5, "stance": "neutral", "rationale": "ok"}]


def test_score_section_llm_none_returns_all_none():
    from research_companion.rcs import score_section

    citations = [{"paper_id": "p1", "char_start": 0, "char_end": 5}]
    load_text_fn = _stub_load_text({"p1": "Hello world"})

    results = score_section("Q", "A", citations, load_text_fn=load_text_fn, llm=None)
    assert results == [None]


def test_score_section_empty_citations_returns_empty_list():
    from research_companion.rcs import score_section
    results = score_section("Q", "A", [], load_text_fn=lambda p: None, llm=lambda p: "{}")
    assert results == []


def test_score_section_strips_markdown_code_fences():
    from research_companion.rcs import score_section

    citations = [{"paper_id": "p1", "char_start": 0, "char_end": 5}]
    load_text_fn = _stub_load_text({"p1": "Hello world"})

    def fenced_llm(prompt):
        return "```json\n" + json.dumps({"scores": [
            {"ref": 0, "relevance": 0.4, "stance": "contradicts", "rationale": "ok"},
        ]}) + "\n```"

    results = score_section("Q", "A", citations, load_text_fn=load_text_fn, llm=fenced_llm)
    assert results == [{"relevance": 0.4, "stance": "contradicts", "rationale": "ok"}]
