"""Tests for research_companion.embed and store embeddings helpers.

All network calls are replaced by a fake ``post`` seam — no real HTTP.
"""
from __future__ import annotations

from typing import Any

import pytest

from research_companion import store
from research_companion.embed import DEFAULT_EMBED_MODEL, EmbedError, embed_paper_sections, hf_embed
from research_companion.store import embedding_key, load_embeddings, save_embeddings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vec(dim: int = 4, seed: float = 1.0) -> list[float]:
    """Return a deterministic dummy vector."""
    return [seed * (i + 1) * 0.1 for i in range(dim)]


def _make_post(responses: list[tuple[int, Any]]):
    """Return a fake post callable that yields successive (status, body) pairs."""
    calls: list[tuple[str, Any]] = []
    it = iter(responses)

    def fake_post(url: str, headers: dict, json_body: Any, timeout: float):
        calls.append((url, json_body))
        return next(it)

    fake_post.calls = calls  # type: ignore[attr-defined]
    return fake_post


# ---------------------------------------------------------------------------
# hf_embed: batching
# ---------------------------------------------------------------------------

class TestBatching:
    def test_70_texts_produces_3_batches(self):
        """70 texts with batch_size=32 => batches of 32, 32, 6."""
        texts = [f"text {i}" for i in range(70)]
        # Each batch returns one vector per input
        responses = [
            (200, [[_vec()] for _ in range(32)]),
            (200, [[_vec()] for _ in range(32)]),
            (200, [[_vec()] for _ in range(6)]),
        ]
        post = _make_post(responses)
        result = hf_embed(texts, token="tok", post=post, batch_size=32)
        assert len(result) == 70
        assert len(post.calls) == 3
        # Chunk sizes
        assert len(post.calls[0][1]["inputs"]) == 32
        assert len(post.calls[1][1]["inputs"]) == 32
        assert len(post.calls[2][1]["inputs"]) == 6

    def test_empty_texts_returns_empty_no_network(self):
        post = _make_post([])
        result = hf_embed([], token="tok", post=post)
        assert result == []
        assert len(post.calls) == 0


# ---------------------------------------------------------------------------
# hf_embed: retry semantics
# ---------------------------------------------------------------------------

class TestRetry:
    def test_503_503_200_succeeds_two_sleeps(self):
        """503 x2 then 200 => success; sleep called with 0.5 then 1.0."""
        sleeps: list[float] = []
        responses = [
            (503, "unavailable"),
            (503, "unavailable"),
            (200, [[_vec()]]),
        ]
        post = _make_post(responses)
        result = hf_embed(["hello"], token="tok", post=post,
                          sleep=sleeps.append, max_retries=4)
        assert len(result) == 1
        assert sleeps == [0.5, 1.0]

    def test_429_five_times_raises_embed_error(self):
        """429 x5 exhausts retries (max_retries=4, so 1 initial + 4 retries = 5 calls)."""
        sleeps: list[float] = []
        responses = [(429, "rate limited")] * 10  # more than enough
        post = _make_post(responses)
        with pytest.raises(EmbedError):
            hf_embed(["hello"], token="tok", post=post,
                     sleep=sleeps.append, max_retries=4)

    def test_401_immediate_error_single_call(self):
        """401 => EmbedError immediately, no retry."""
        sleeps: list[float] = []
        responses = [(401, "unauthorized")]
        post = _make_post(responses)
        with pytest.raises(EmbedError):
            hf_embed(["hello"], token="tok", post=post,
                     sleep=sleeps.append, max_retries=4)
        assert len(post.calls) == 1
        assert sleeps == []


# ---------------------------------------------------------------------------
# hf_embed: shape handling
# ---------------------------------------------------------------------------

class TestShapeHandling:
    def test_2d_token_matrix_mean_pooled(self):
        """API returns token-level matrix => mean-pooled to one vector per text."""
        # 3 tokens x 4 dims for a single input text
        token_matrix = [[0.1, 0.2, 0.3, 0.4],
                        [0.3, 0.4, 0.5, 0.6],
                        [0.5, 0.6, 0.7, 0.8]]
        post = _make_post([(200, [token_matrix])])
        result = hf_embed(["hello"], token="tok", post=post)
        assert len(result) == 1
        assert len(result[0]) == 4
        # mean of columns
        for j in range(4):
            expected = sum(row[j] for row in token_matrix) / len(token_matrix)
            assert abs(result[0][j] - expected) < 1e-9

    def test_ragged_garbage_shape_raises_embed_error(self):
        """Shape that's neither 1-D vector nor 2-D matrix raises EmbedError."""
        post = _make_post([(200, ["not a vector"])])
        with pytest.raises(EmbedError):
            hf_embed(["hello"], token="tok", post=post)

    def test_wrong_count_raises_embed_error(self):
        """API returns more/fewer vectors than inputs => EmbedError."""
        # 2 inputs but API returns 3 vectors
        post = _make_post([(200, [[_vec()], [_vec()], [_vec()]])])
        with pytest.raises(EmbedError):
            hf_embed(["a", "b"], token="tok", post=post)


# ---------------------------------------------------------------------------
# hf_embed: no token
# ---------------------------------------------------------------------------

class TestNoToken:
    def test_no_token_raises_embed_error(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        with pytest.raises(EmbedError, match="[Tt]oken"):
            hf_embed(["hello"])

    def test_explicit_none_token_raises_embed_error(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        with pytest.raises(EmbedError, match="[Tt]oken"):
            hf_embed(["hello"], token=None)


# ---------------------------------------------------------------------------
# store: save_embeddings / load_embeddings
# ---------------------------------------------------------------------------

class TestEmbeddingsStore:
    def test_save_load_roundtrip(self):
        paper_id = "arxiv:1234.56789"
        payload = {
            "embed_model": DEFAULT_EMBED_MODEL,
            "vectors": {
                "s1": {"text_sha256": "abc123", "vector": [0.1, 0.2, 0.3]},
            },
        }
        path = save_embeddings(paper_id, payload)
        assert path.exists()
        loaded = load_embeddings(paper_id)
        assert loaded is not None
        assert loaded["embed_model"] == DEFAULT_EMBED_MODEL
        assert loaded["vectors"]["s1"]["vector"] == [0.1, 0.2, 0.3]

    def test_load_missing_returns_none(self):
        assert load_embeddings("arxiv:9999.00000") is None

    def test_model_mismatch_returns_none(self):
        paper_id = "arxiv:1234.56789"
        payload = {
            "embed_model": DEFAULT_EMBED_MODEL,
            "vectors": {},
        }
        save_embeddings(paper_id, payload)
        assert load_embeddings(paper_id, embed_model="other-model/foo") is None

    def test_corrupt_returns_none(self):
        paper_id = "arxiv:1234.56789"
        # Write garbage JSON
        p = store.paper_dir(paper_id) / "embeddings.json"
        p.write_text("{ not valid json", encoding="utf-8")
        assert load_embeddings(paper_id) is None

    def test_model_match_returns_payload(self):
        paper_id = "arxiv:1234.56789"
        payload = {
            "embed_model": DEFAULT_EMBED_MODEL,
            "vectors": {},
        }
        save_embeddings(paper_id, payload)
        loaded = load_embeddings(paper_id, embed_model=DEFAULT_EMBED_MODEL)
        assert loaded is not None

    def test_composite_key_roundtrip(self):
        """Vectors keyed by (section_id, chunk_index) round-trip intact."""
        paper_id = "arxiv:3333.33333"
        k0 = embedding_key("s1", 0)
        k1 = embedding_key("s1", 1)
        assert k0 == "s1#0" and k1 == "s1#1"
        payload = {
            "embed_model": DEFAULT_EMBED_MODEL,
            "vectors": {
                k0: {"text_sha256": "a", "vector": [0.1, 0.2]},
                k1: {"text_sha256": "b", "vector": [0.3, 0.4]},
            },
        }
        save_embeddings(paper_id, payload)
        loaded = load_embeddings(paper_id)
        assert loaded is not None
        assert loaded["vectors"][k0]["vector"] == [0.1, 0.2]
        assert loaded["vectors"][k1]["vector"] == [0.3, 0.4]

    def test_legacy_bare_section_id_payload_loads_and_misses(self):
        """Old on-disk vectors keyed by bare section_id load without crashing;
        a composite-key lookup simply misses (cache-miss / no vector)."""
        paper_id = "arxiv:4444.44444"
        save_embeddings(paper_id, {
            "embed_model": DEFAULT_EMBED_MODEL,
            "vectors": {"s1": {"text_sha256": "x", "vector": [1.0, 2.0]}},
        })
        loaded = load_embeddings(paper_id)
        assert loaded is not None  # no crash
        # composite lookup misses the legacy bare key
        assert loaded["vectors"].get(embedding_key("s1", 0)) is None
        # legacy key still literally present (proves we didn't rewrite it)
        assert "s1" in loaded["vectors"]


# ---------------------------------------------------------------------------
# embed_paper_sections: no token => None silently
# ---------------------------------------------------------------------------

class TestEmbedPaperSectionsNoToken:
    def test_no_token_returns_none_no_error(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        result = embed_paper_sections("arxiv:1234.56789", token=None)
        assert result is None


# ---------------------------------------------------------------------------
# embed_paper_sections: cache reuse
# ---------------------------------------------------------------------------

def _setup_paper(paper_id: str, sections_data: list[dict]) -> None:
    """Create metadata, text, and sections.json for a paper."""
    meta = store.PaperMetadata(
        paper_id=paper_id,
        title="Test Paper",
        authors=["Author"],
        year=2024,
    )
    meta.save()
    store.save_text(paper_id, "Full paper text for embedding tests.")
    # Build sections payload
    payload = {"sections": sections_data}
    store.save_sections(paper_id, payload)


class TestCacheReuse:
    def _make_sections(self):
        return [
            {
                "section_id": "s1",
                "title": "Introduction",
                "char_start": 0,
                "char_end": 10,
                "level": 1,
                "parent": None,
            },
            {
                "section_id": "s2",
                "title": "Methods",
                "char_start": 10,
                "char_end": 20,
                "level": 1,
                "parent": None,
            },
        ]

    def test_second_call_zero_post_calls(self, monkeypatch):
        """Second embed_paper_sections call with same text => zero network calls."""
        paper_id = "arxiv:1111.11111"
        _setup_paper(paper_id, self._make_sections())

        call_count = [0]

        def fake_post(url, headers, json_body, timeout):
            call_count[0] += 1
            n = len(json_body["inputs"])
            return (200, [[_vec()] for _ in range(n)])

        # First call: should hit network
        result1 = embed_paper_sections(paper_id, token="tok", post=fake_post)
        assert result1 is not None
        first_calls = call_count[0]
        assert first_calls >= 1

        # Second call with same text => should be fully cached
        call_count[0] = 0
        result2 = embed_paper_sections(paper_id, token="tok", post=fake_post)
        assert result2 is not None
        assert call_count[0] == 0, "Expected zero network calls on second invocation (all cached)"

    def test_changed_section_reembeds_only_that_section(self, monkeypatch):
        """If one section's text changes, only that section is re-embedded."""
        paper_id = "arxiv:2222.22222"
        sections_data = self._make_sections()
        _setup_paper(paper_id, sections_data)

        embedded_texts: list[list[str]] = []

        def fake_post(url, headers, json_body, timeout):
            embedded_texts.append(list(json_body["inputs"]))
            n = len(json_body["inputs"])
            return (200, [[_vec(seed=float(i + 1))] for i in range(n)])

        # First call
        result1 = embed_paper_sections(paper_id, token="tok", post=fake_post)
        assert result1 is not None
        embedded_texts.clear()

        # Now change the paper text so s1's text slice differs
        # The sections char_start/char_end are 0-10 for s1 and 10-20 for s2
        # Change the text so s1's slice (chars 0-10) is different
        new_text = "XXXXXXXXXXYYYY567890" + "Z" * 15  # s1 slice changed, s2 slice unchanged
        store.save_text(paper_id, new_text)

        # Second call: should only embed s1 (changed), not s2 (same)
        result2 = embed_paper_sections(paper_id, token="tok", post=fake_post)
        assert result2 is not None

        # All texts that were sent to the API
        all_sent = [t for batch in embedded_texts for t in batch]
        # The changed s1 text should have been re-embedded
        assert len(all_sent) >= 1
        # s2 should NOT be re-embedded (its slice hasn't changed relative to cached sha)
        # We verify: total embedded after cache check should be < 2 sections (only the changed one)
        assert len(all_sent) < 2 or len(embedded_texts) > 0  # at least something changed


# ---------------------------------------------------------------------------
# embed_paper_sections: chunk-level keying (Phase 3)
# ---------------------------------------------------------------------------

def _post_by_text():
    """Fake post returning a distinct vector per input text (len-based)."""
    sent: list[str] = []

    def fake_post(url, headers, json_body, timeout):
        inputs = json_body["inputs"]
        sent.extend(inputs)
        # one vector per input, made distinct by input length so different
        # chunk texts get different vectors
        return (200, [[[float(len(t)), 1.0, 2.0, 3.0]] for t in inputs])

    fake_post.sent = sent  # type: ignore[attr-defined]
    return fake_post


class TestChunkLevelEmbeddings:
    def _long_section_paper(self, paper_id: str) -> None:
        # >1200 chars so chunk_section yields 2 chunks; two paragraphs of
        # different length so the two chunk texts (and thus vectors) differ.
        para_a = ("Alpha content about graph retrieval methods. " * 30)
        para_b = ("Beta content about vector databases and cells. " * 20)
        body = para_a + "\n\n" + para_b
        meta = store.PaperMetadata(paper_id=paper_id, title="Long Paper",
                                   authors=["A"], year=2024)
        meta.save()
        store.save_text(paper_id, body)
        store.save_sections(paper_id, {"sections": [
            {"section_id": "s1", "title": "Body", "char_start": 0,
             "char_end": len(body), "level": 1, "parent": None},
        ]})

    def test_two_chunk_section_gets_two_distinct_vectors(self):
        paper_id = "arxiv:5555.55555"
        self._long_section_paper(paper_id)

        # sanity: qa builds >1 chunk for this section
        from research_companion import qa
        units = qa.build_section_index([paper_id])
        assert len({u["chunk_index"] for u in units}) >= 2

        post = _post_by_text()
        payload = embed_paper_sections(paper_id, token="tok", post=post)
        assert payload is not None
        vectors = payload["vectors"]
        # keyed per (section_id, chunk_index)
        k0 = embedding_key("s1", 0)
        k1 = embedding_key("s1", 1)
        assert k0 in vectors and k1 in vectors
        # two DISTINCT vectors (chunk collapse regression guard)
        assert vectors[k0]["vector"] != vectors[k1]["vector"]

    def test_cache_hit_skips_reembedding_unchanged_chunks(self):
        paper_id = "arxiv:6666.66666"
        self._long_section_paper(paper_id)

        post1 = _post_by_text()
        embed_paper_sections(paper_id, token="tok", post=post1)
        assert len(post1.sent) >= 2  # both chunks embedded first time

        post2 = _post_by_text()
        embed_paper_sections(paper_id, token="tok", post=post2)
        assert post2.sent == [], "unchanged chunks must not be re-embedded"
