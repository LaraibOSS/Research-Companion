"""Pure semantic-overlap math (fake vectors only; no network, no model)."""
import math

from research_companion.semoverlap import (
    DEFAULT_SEMANTIC_MIN_CHARS,
    DEFAULT_SEMANTIC_THRESHOLD,
    _best_matches,
    merge_overlap_results,
    semantic_near_duplicate_passages,
)

LONG = "x" * DEFAULT_SEMANTIC_MIN_CHARS  # meets the min length


def _unit(sec="s1", idx=0, text=LONG, start=0, end=200):
    return {"section_id": sec, "chunk_index": idx, "text": text,
            "char_start": start, "char_end": end}


def test_paraphrase_pair_flagged_and_orthogonal_not():
    target_units = [_unit()]
    target_vectors = {"s1#0": [1.0, 0.1, 0.0]}
    corpus = [("lib:1",
               [_unit(sec="c1"), _unit(sec="c2")],
               {"c1#0": [1.0, 0.12, 0.0],   # near-parallel -> high cosine
                "c2#0": [0.0, 0.0, 1.0]})]  # orthogonal
    res = semantic_near_duplicate_passages(target_units, target_vectors, corpus)
    assert len(res["findings"]) == 1
    f = res["findings"][0]
    assert f["matched_paper_id"] == "lib:1"
    assert f["method"] == "semantic"
    assert f["matched_section_id"] == "c1"
    assert f["char_start"] == 0 and f["char_end"] == 200
    assert res["summary"]["n_passages"] == 1


def test_threshold_boundary():
    # cos(theta) just under vs just over the default threshold
    th = DEFAULT_SEMANTIC_THRESHOLD
    under = [1.0, math.tan(math.acos(th - 0.01)), 0.0]
    over = [1.0, math.tan(math.acos(th + 0.01)), 0.0]
    target_units = [_unit()]
    tv = {"s1#0": [1.0, 0.0, 0.0]}
    res_u = semantic_near_duplicate_passages(
        target_units, tv, [("p", [_unit(sec="c")], {"c#0": under})])
    res_o = semantic_near_duplicate_passages(
        target_units, tv, [("p", [_unit(sec="c")], {"c#0": over})])
    assert res_u["findings"] == []
    assert len(res_o["findings"]) == 1


def test_short_chunk_and_missing_vector_skipped():
    target_units = [_unit(text="short"), _unit(sec="s2")]  # s2 has no vector
    res = semantic_near_duplicate_passages(
        target_units, {"s1#0": [1.0, 0.0]}, [("p", [_unit(sec="c")], {"c#0": [1.0, 0.0]})])
    assert res["findings"] == []  # s1#0 too short, s2#0 vectorless


def test_empty_corpus_no_findings():
    res = semantic_near_duplicate_passages([_unit()], {"s1#0": [1.0, 0.0]}, [])
    assert res["findings"] == [] and res["summary"]["n_passages"] == 0


def test_zero_vector_skipped():
    res = semantic_near_duplicate_passages(
        [_unit()], {"s1#0": [0.0, 0.0]}, [("p", [_unit(sec="c")], {"c#0": [1.0, 0.0]})])
    assert res["findings"] == []


def test_numpy_and_stdlib_paths_identical(monkeypatch):
    tvecs = [[1.0, 0.0, 0.0], [0.6, 0.8, 0.0]]
    cvecs = [[0.8, 0.6, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]
    with_np = _best_matches(tvecs, cvecs)
    import research_companion.semoverlap as so
    monkeypatch.setattr(so, "_numpy", lambda: None)
    without_np = _best_matches(tvecs, cvecs)
    assert [(i, round(s, 10)) for i, s in with_np] == \
           [(i, round(s, 10)) for i, s in without_np]


def test_merge_tags_and_range_overlap_dedupe():
    lexical = {"findings": [
        {"matched_paper_id": "lib:1", "score": 0.7,
         "char_start": 100, "char_end": 600, "snippet": "lex"}],
        "summary": {"n_passages": 1, "papers": ["lib:1"], "max_score": 0.7,
                    "text": "1 passage(s) ..."}}
    semantic = {"findings": [
        # overlaps the lexical range for the SAME paper -> dropped
        {"matched_paper_id": "lib:1", "score": 0.9, "char_start": 500,
         "char_end": 1700, "snippet": "s1", "method": "semantic",
         "matched_section_id": "c1"},
        # same range but DIFFERENT paper -> kept
        {"matched_paper_id": "lib:2", "score": 0.85, "char_start": 500,
         "char_end": 1700, "snippet": "s2", "method": "semantic",
         "matched_section_id": "c2"},
        # disjoint range, same paper -> kept
        {"matched_paper_id": "lib:1", "score": 0.88, "char_start": 3000,
         "char_end": 4200, "snippet": "s3", "method": "semantic",
         "matched_section_id": "c3"}],
        "summary": {"n_passages": 3, "papers": ["lib:1", "lib:2"],
                    "max_score": 0.9, "text": "..."}}
    merged = merge_overlap_results(lexical, semantic)
    methods = [(f["matched_paper_id"], f["method"]) for f in merged["findings"]]
    assert methods == [("lib:1", "lexical"), ("lib:2", "semantic"), ("lib:1", "semantic")]
    assert merged["summary"]["n_passages"] == 3
    assert merged["summary"]["n_semantic"] == 2
    assert merged["summary"]["papers"] == ["lib:1", "lib:2"]
    assert "paraphrased" in merged["summary"]["text"]


def test_merge_with_no_semantic_findings_keeps_lexical_text_shape():
    lexical = {"findings": [], "summary": {
        "n_passages": 0, "papers": [], "max_score": 0.0,
        "text": "no near-duplicate passages found"}}
    semantic = {"findings": [], "summary": {
        "n_passages": 0, "papers": [], "max_score": 0.0, "text": "none"}}
    merged = merge_overlap_results(lexical, semantic)
    assert merged["summary"]["n_semantic"] == 0
    assert merged["summary"]["text"] == "no near-duplicate passages found"
