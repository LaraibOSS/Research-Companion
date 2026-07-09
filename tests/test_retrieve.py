"""Tests for research_companion/retrieve.py — hybrid BM25+embedding fusion.

The degradation contract is the core: with no embed_query and no HF_TOKEN,
rank_units ordering must be identical to raw BM25 ordering (v0.2 behavior).
"""
from __future__ import annotations

import pytest

from research_companion import store
from research_companion.rank import BM25
from research_companion.retrieve import cosine, rank_units


def _units(*token_lists, paper_id="arxiv:1", text="body text"):
    return [
        {
            "paper_id": paper_id,
            "paper_title": f"Paper {paper_id}",
            "section_id": f"s{i + 1}",
            "section_title": f"Sec {i + 1}",
            "tokens": list(toks),
            "text": text,
        }
        for i, toks in enumerate(token_lists)
    ]


class TestCosine:
    def test_identical_vectors(self):
        assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_orthogonal(self):
        assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_norm(self):
        assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_length_mismatch(self):
        assert cosine([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


class TestBm25OnlyDegradation:
    """No embed_query, no HF_TOKEN => ordering identical to raw BM25."""

    def test_order_matches_raw_bm25(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        units = _units(
            ["graph", "retrieval", "augmented"],
            ["vector", "database", "retrieval"],
            ["unrelated", "biology", "cells"],
            ["graph", "graph", "retrieval", "knowledge"],
        )
        q = ["graph", "retrieval"]
        raw = BM25([u["tokens"] for u in units]).score(q)
        expected_order = [i for i, s in sorted(
            ((i, s) for i, s in enumerate(raw) if s > 0),
            key=lambda t: (-t[1], t[0]))]

        ranked = rank_units("graph retrieval", q, units, k=10)
        assert all(r["mode"] == "bm25" for r in ranked)
        got_order = [units.index(r["unit"]) for r in ranked]
        assert got_order == expected_order
        # scores are the raw BM25 values in bm25-only mode
        for r, idx in zip(ranked, got_order, strict=True):
            assert r["score"] == pytest.approx(raw[idx])

    def test_zero_score_units_excluded(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        units = _units(["alpha"], ["beta"])
        ranked = rank_units("alpha", ["alpha"], units, k=5)
        assert len(ranked) == 1
        assert ranked[0]["unit"]["section_id"] == "s1"

    def test_k_limits(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        units = _units(*([["term"]] * 5))
        ranked = rank_units("term", ["term"], units, k=2)
        assert len(ranked) == 2


class TestHybridFusion:
    def _seed_vectors(self, paper_id, section_vecs, model="sentence-transformers/all-MiniLM-L6-v2"):
        # units from _units have no chunk_index -> chunk_index 0 -> "sid#0"
        store.save_embeddings(paper_id, {
            "embed_model": model,
            "vectors": {store.embedding_key(sid, 0): {"text_sha256": "x", "vector": v}
                        for sid, v in section_vecs.items()},
        })

    def test_fusion_hand_math(self):
        # three units; bm25 hits s1 & s2; cosine favors s3 strongly
        units = _units(["query", "term"], ["query"], ["nothing", "shared"])
        self._seed_vectors("arxiv:1", {"s1": [1.0, 0.0], "s2": [0.0, 1.0], "s3": [1.0, 0.0]})
        embed_query = lambda q: [1.0, 0.0]  # noqa: E731

        ranked = rank_units("query term", ["query", "term"], units, k=3,
                            embed_query=embed_query)
        assert all(r["mode"] == "hybrid" for r in ranked)
        by_sid = {r["unit"]["section_id"]: r for r in ranked}
        # s3 has bm25 0 but cosine 1.0 -> included via cosine pool (the semantic case)
        assert "s3" in by_sid
        # hand math: pool = {s1, s2, s3}; bm25 raw: s1 > s2 > 0, s3 = 0
        # bm25_norm: s1=1.0, s3=0.0; cosine: s1=1.0, s2=0.0, s3=1.0
        # fused: s1 = 0.5*1 + 0.5*1 = 1.0 ; s3 = 0.5*0 + 0.5*1 = 0.5
        assert by_sid["s1"]["score"] == pytest.approx(1.0)
        assert by_sid["s3"]["score"] == pytest.approx(0.5)
        assert ranked[0]["unit"]["section_id"] == "s1"

    def test_max_equals_min_gives_half(self):
        units = _units(["same"], ["same"])
        self._seed_vectors("arxiv:1", {"s1": [1.0], "s2": [1.0]})
        ranked = rank_units("same", ["same"], units, k=2, embed_query=lambda q: [1.0])
        # identical bm25 and cosine everywhere -> both signals normalize to 0.5
        for r in ranked:
            assert r["score"] == pytest.approx(0.5)

    def test_tie_breaks_by_index(self):
        units = _units(["tok"], ["tok"])
        self._seed_vectors("arxiv:1", {"s1": [1.0], "s2": [1.0]})
        ranked = rank_units("tok", ["tok"], units, k=2, embed_query=lambda q: [1.0])
        assert [r["unit"]["section_id"] for r in ranked] == ["s1", "s2"]

    def test_embed_query_error_falls_back_to_bm25(self):
        units = _units(["query"], ["other"])
        self._seed_vectors("arxiv:1", {"s1": [1.0]})

        def boom(q):
            raise RuntimeError("HF down")

        ranked = rank_units("query", ["query"], units, k=2, embed_query=boom)
        assert all(r["mode"] == "bm25" for r in ranked)
        assert len(ranked) == 1

    def test_no_cached_vectors_means_bm25_mode(self):
        units = _units(["query"], ["query", "extra"])
        ranked = rank_units("query", ["query"], units, k=2, embed_query=lambda q: [1.0])
        assert all(r["mode"] == "bm25" for r in ranked)

    def test_missing_vector_unit_competes_via_bm25(self):
        units = _units(["query", "strong", "match"], ["query"])
        # only s2 has a vector
        self._seed_vectors("arxiv:1", {"s2": [1.0]})
        ranked = rank_units("query", ["query"], units, k=2, embed_query=lambda q: [1.0])
        assert all(r["mode"] == "hybrid" for r in ranked)
        sids = [r["unit"]["section_id"] for r in ranked]
        assert "s1" in sids and "s2" in sids

    def test_result_shape(self):
        units = _units(["query"])
        self._seed_vectors("arxiv:1", {"s1": [1.0]})
        ranked = rank_units("query", ["query"], units, k=1, embed_query=lambda q: [1.0])
        r = ranked[0]
        assert set(r.keys()) == {"unit", "score", "bm25", "cosine", "mode"}
        assert isinstance(r["bm25"], float) and isinstance(r["cosine"], float)


class TestChunkLevelVectorLoading:
    """_load_unit_vectors keys by (section_id, chunk_index) so two chunks of
    the same section get their OWN vectors, and legacy keys miss gracefully."""

    def _chunk_units(self):
        # two chunks of ONE section s1 (chunk_index 0 and 1)
        return [
            {"paper_id": "arxiv:1", "paper_title": "P", "section_id": "s1",
             "section_title": "S", "tokens": ["query"], "text": "c0", "chunk_index": 0},
            {"paper_id": "arxiv:1", "paper_title": "P", "section_id": "s1",
             "section_title": "S", "tokens": ["query"], "text": "c1", "chunk_index": 1},
        ]

    def test_two_chunks_one_section_get_distinct_vectors(self):
        from research_companion.retrieve import _load_unit_vectors
        store.save_embeddings("arxiv:1", {
            "embed_model": "m",
            "vectors": {
                store.embedding_key("s1", 0): {"text_sha256": "x", "vector": [1.0, 0.0]},
                store.embedding_key("s1", 1): {"text_sha256": "y", "vector": [0.0, 1.0]},
            },
        })
        vecs = _load_unit_vectors(self._chunk_units(), "m")
        assert vecs[0] == [1.0, 0.0]
        assert vecs[1] == [0.0, 1.0]

    def test_missing_chunk_vector_absent_no_error(self):
        from research_companion.retrieve import _load_unit_vectors
        # only chunk 0 seeded; chunk 1 must simply be absent (BM25 fallback)
        store.save_embeddings("arxiv:1", {
            "embed_model": "m",
            "vectors": {
                store.embedding_key("s1", 0): {"text_sha256": "x", "vector": [1.0, 0.0]},
            },
        })
        vecs = _load_unit_vectors(self._chunk_units(), "m")
        assert vecs.get(0) == [1.0, 0.0]
        assert 1 not in vecs

    def test_legacy_bare_key_misses_falls_back(self):
        from research_companion.retrieve import _load_unit_vectors
        # legacy payload keyed by bare section_id -> composite lookup misses
        store.save_embeddings("arxiv:1", {
            "embed_model": "m",
            "vectors": {"s1": {"text_sha256": "x", "vector": [1.0, 0.0]}},
        })
        vecs = _load_unit_vectors(self._chunk_units(), "m")
        assert vecs == {}
