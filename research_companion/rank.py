"""BM25 ranking for section-scoped retrieval.

Provides:
    STOPWORDS  -- frozenset of common English stopwords (was private _STOP in chat.py)
    tokenize   -- lowercase alphanum tokenizer, len>=3, minus STOPWORDS
    BM25       -- standard Okapi BM25 scorer
"""
from __future__ import annotations

import math
import re

# ---------------------------------------------------------------------------
# Stopwords (moved from chat.py; chat.py now imports from here)
# ---------------------------------------------------------------------------

STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "is", "are",
    "what", "which", "how", "why", "do", "does", "did", "this", "that", "these",
    "those", "with", "from", "by", "as", "be", "been", "being", "was", "were",
    "it", "its", "they", "them", "their", "there", "here", "we", "you",
})


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def tokenize(s: str) -> list[str]:
    """Return lowercase alphanumeric tokens (length >= 3) minus STOPWORDS."""
    words = re.findall(r"[a-z0-9]+", s.lower())
    return [w for w in words if len(w) >= 3 and w not in STOPWORDS]


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

class BM25:
    """Standard Okapi BM25 scorer.

    Args:
        docs:  Corpus as a list of token lists.
        k1:    Term-frequency saturation parameter (default 1.5).
        b:     Length normalisation parameter (default 0.75).
    """

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._n = len(docs)

        if self._n == 0:
            self._avgdl = 0.0
            self._df: dict[str, int] = {}
            self._doc_tfs: list[dict[str, int]] = []
            self._doc_lens: list[int] = []
            return

        self._doc_lens = [len(doc) for doc in docs]
        self._avgdl = sum(self._doc_lens) / self._n

        # Document-frequency: how many docs contain each term
        self._df: dict[str, int] = {}
        for doc in docs:
            for term in set(doc):
                self._df[term] = self._df.get(term, 0) + 1

        # Term-frequency per document
        self._doc_tfs: list[dict[str, int]] = []
        for doc in docs:
            tf: dict[str, int] = {}
            for term in doc:
                tf[term] = tf.get(term, 0) + 1
            self._doc_tfs.append(tf)

    def score(self, query: list[str]) -> list[float]:
        """Return one BM25 score per document in the corpus.

        Returns [] for empty corpus; zeros for empty or non-matching query.
        """
        if self._n == 0:
            return []

        scores = [0.0] * self._n

        if not query:
            return scores

        for term in query:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            # IDF — standard Okapi formula with smoothing
            idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)
            for i, tf_map in enumerate(self._doc_tfs):
                tf = tf_map.get(term, 0)
                if tf == 0:
                    continue
                dl = self._doc_lens[i]
                denom = tf + self.k1 * (1.0 - self.b + self.b * dl / self._avgdl)
                scores[i] += idf * (tf * (self.k1 + 1.0)) / denom

        return scores
