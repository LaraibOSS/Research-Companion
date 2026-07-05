"""Tests for research_companion.rank — BM25 ranking module.

Strict TDD: tests written before implementation.
"""
from __future__ import annotations

import math

import pytest


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_lowercases_input(self):
        from research_companion.rank import tokenize
        tokens = tokenize("GraphRAG BM25 Test")
        assert "graphrag" in tokens
        assert "bm25" in tokens
        assert "test" in tokens

    def test_filters_short_tokens_under_3(self):
        from research_companion.rank import tokenize
        # "is", "a" should be filtered
        tokens = tokenize("is a graph")
        assert "is" not in tokens
        # "a" is definitely < 3 chars
        assert "a" not in tokens
        assert "graph" in tokens

    def test_filters_stopwords(self):
        from research_companion.rank import tokenize, STOPWORDS
        # Pick a stopword that is >= 3 chars
        sw = next(s for s in STOPWORDS if len(s) >= 3)
        tokens = tokenize(f"graph {sw} method")
        assert sw not in tokens
        assert "graph" in tokens
        assert "method" in tokens

    def test_alphanumeric_only(self):
        from research_companion.rank import tokenize
        tokens = tokenize("hello, world! foo-bar baz123")
        # punctuation stripped; "hello" kept, "world" kept
        assert "hello" in tokens
        assert "world" in tokens
        assert "baz123" in tokens
        # dash is not alphanum, so foo and bar are separate tokens if len >= 3
        assert "foo" in tokens
        assert "bar" in tokens

    def test_empty_string(self):
        from research_companion.rank import tokenize
        assert tokenize("") == []

    def test_only_stopwords_and_short(self):
        from research_companion.rank import tokenize
        # All tokens either < 3 chars or stopwords
        tokens = tokenize("a the is")
        assert tokens == []


# ---------------------------------------------------------------------------
# STOPWORDS exported from rank.py
# ---------------------------------------------------------------------------

class TestStopwords:
    def test_stopwords_is_frozenset(self):
        from research_companion.rank import STOPWORDS
        assert isinstance(STOPWORDS, frozenset)

    def test_stopwords_nonempty(self):
        from research_companion.rank import STOPWORDS
        assert len(STOPWORDS) > 5

    def test_stopwords_contains_common_words(self):
        from research_companion.rank import STOPWORDS
        for word in ("the", "and", "for"):
            assert word in STOPWORDS


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

class TestBM25:
    def test_empty_corpus(self):
        from research_companion.rank import BM25
        bm = BM25([])
        assert bm.score([]) == []
        assert bm.score(["graph"]) == []

    def test_single_doc_nonempty_query(self):
        from research_companion.rank import BM25
        bm = BM25([["graph", "neural", "network"]])
        scores = bm.score(["graph"])
        assert len(scores) == 1
        assert scores[0] > 0.0

    def test_empty_query_returns_zeros(self):
        from research_companion.rank import BM25
        bm = BM25([["graph", "neural"], ["text", "retrieval"]])
        scores = bm.score([])
        assert scores == [0.0, 0.0]

    def test_rare_term_beats_common_term(self):
        """Doc with rare shared term should score higher than doc with common term."""
        from research_companion.rank import BM25

        # Build a corpus where "rare" appears in only one doc
        # and "common" appears in many docs.
        docs = []
        # Add 10 docs with "common"
        for _ in range(10):
            docs.append(["common", "filler", "text"])
        # Add 1 doc with "rare"
        docs.append(["rare", "unique", "term"])
        # Add 1 doc with both
        docs.append(["common", "rare"])

        bm = BM25(docs)
        query = ["rare"]  # IDF of "rare" >> IDF of "common"
        scores = bm.score(query)
        # The doc with "rare" only (index 10) should beat common-only docs (indices 0-9)
        assert scores[10] > scores[0], (
            f"Doc with rare term (score={scores[10]:.3f}) should beat "
            f"common-only doc (score={scores[0]:.3f})"
        )

    def test_doc_with_more_query_terms_scores_higher(self):
        from research_companion.rank import BM25
        # Two docs; one has more overlapping query terms
        doc_good = ["graph", "neural", "network", "method", "approach"]
        doc_poor = ["graph", "filler", "noise"]
        bm = BM25([doc_good, doc_poor])
        scores = bm.score(["graph", "neural", "method"])
        assert scores[0] > scores[1]

    def test_k1_b_defaults_are_sane(self):
        from research_companion.rank import BM25
        bm = BM25([["graph"]])
        # k1 should be 1.5 and b 0.75 per spec
        assert bm.k1 == 1.5
        assert bm.b == 0.75

    def test_scores_length_matches_corpus(self):
        from research_companion.rank import BM25
        docs = [["a", "b"], ["c", "d"], ["e", "f"]]
        bm = BM25(docs)
        scores = bm.score(["a"])
        assert len(scores) == 3

    def test_non_matching_query_returns_zeros(self):
        from research_companion.rank import BM25
        bm = BM25([["graph", "neural"], ["text", "retrieval"]])
        scores = bm.score(["zxqwerty"])
        assert all(s == 0.0 for s in scores)


# ---------------------------------------------------------------------------
# chat.py still imports STOPWORDS from rank after the move
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fix 3 — hand-computed BM25 numeric test
# ---------------------------------------------------------------------------

class TestBM25Numeric:
    def test_single_doc_single_term_exact_score(self):
        """Hand-computed BM25 score for trivial corpus: docs=[["apple"]], query=["apple"].

        Given:
            N=1, df("apple")=1
            idf = log((1 - 1 + 0.5) / (1 + 0.5) + 1) = log(0.5/1.5 + 1) = log(1/3 + 1) = log(4/3)
            tf=1, dl=1, avgdl=1
            denom = tf + k1*(1 - b + b*dl/avgdl) = 1 + 1.5*(1 - 0.75 + 0.75*1) = 1 + 1.5*1 = 2.5
            score = idf * (tf * (k1+1)) / denom = log(4/3) * (1 * 2.5) / 2.5 = log(4/3)
        """
        from research_companion.rank import BM25
        bm = BM25([["apple"]])
        scores = bm.score(["apple"])
        assert len(scores) == 1
        # idf = log((N - df + 0.5)/(df + 0.5) + 1) = log(0.5/1.5 + 1) = log(4/3)
        expected_idf = math.log((1 - 1 + 0.5) / (1 + 0.5) + 1.0)
        # numerator = tf * (k1 + 1) = 1 * 2.5 = 2.5
        # denom = tf + k1*(1 - b + b*dl/avgdl) = 1 + 1.5*(1-0.75+0.75) = 1 + 1.5 = 2.5
        expected_score = expected_idf * (1 * (1.5 + 1.0)) / (1 + 1.5 * (1.0 - 0.75 + 0.75 * 1.0 / 1.0))
        assert scores[0] == pytest.approx(expected_score)


class TestChatStillUsesRankStopwords:
    def test_chat_question_terms_uses_rank_stopwords(self):
        """chat._question_terms should still filter stopwords after refactor."""
        from research_companion.chat import _question_terms
        terms = _question_terms("What is the main approach to graph RAG?")
        assert "what" not in terms
        assert "the" not in terms
        assert "is" not in terms
        assert "graph" in terms
        assert "rag" in terms
