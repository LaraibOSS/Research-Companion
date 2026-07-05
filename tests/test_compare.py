"""Tests for research_companion.compare — pairwise paper comparison.

Strict TDD: tests written before implementation.
"""
from __future__ import annotations

import json

import pytest

from research_companion import store
from research_companion.prompts import extraction_prompt_sha256


# ---------------------------------------------------------------------------
# Helpers: fabricate papers with cached extractions
# ---------------------------------------------------------------------------

def _make_paper(
    paper_id: str,
    title: str,
    authors: list[str] | None = None,
    extraction: dict | None = None,
) -> str:
    """Create a paper with metadata and optional cached extraction."""
    if authors is None:
        authors = ["Author A"]
    meta = store.PaperMetadata(paper_id=paper_id, title=title, authors=authors, year=2024)
    meta.save()
    if extraction is not None:
        store.save_extraction(paper_id, extraction, prompt_sha=extraction_prompt_sha256())
    return paper_id


class TestComparePapers:
    """Test suite for compare_papers function."""

    def test_unknown_paper_a_raises_valueerror(self):
        """Comparing with unknown paper A raises ValueError."""
        from research_companion.compare import compare_papers
        _make_paper("arxiv:2001", "Paper B")
        with pytest.raises(ValueError):
            compare_papers("arxiv:9999", "arxiv:2001")

    def test_unknown_paper_b_raises_valueerror(self):
        """Comparing with unknown paper B raises ValueError."""
        from research_companion.compare import compare_papers
        _make_paper("arxiv:2001", "Paper A")
        with pytest.raises(ValueError):
            compare_papers("arxiv:2001", "arxiv:9999")

    def test_same_paper_raises_valueerror(self):
        """Comparing a paper to itself raises ValueError."""
        from research_companion.compare import compare_papers
        _make_paper("arxiv:2001", "Paper A")
        with pytest.raises(ValueError):
            compare_papers("arxiv:2001", "arxiv:2001")

    def test_basic_comparison_with_no_extraction(self):
        """Compare two papers with no extraction (empty entity sets)."""
        from research_companion.compare import compare_papers
        _make_paper("arxiv:2001", "Paper A")
        _make_paper("arxiv:2002", "Paper B")
        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        # Check return shape
        assert result["version"] == 1
        assert result["paper_a"]["paper_id"] == "arxiv:2001"
        assert result["paper_a"]["title"] == "Paper A"
        assert result["paper_b"]["paper_id"] == "arxiv:2002"
        assert result["paper_b"]["title"] == "Paper B"

        # Empty entity sets
        assert result["shared"]["concepts"] == []
        assert result["shared"]["methods"] == []
        assert result["shared"]["datasets"] == []
        assert result["only_a"]["concepts"] == []
        assert result["only_b"]["concepts"] == []

        # No results (no extraction)
        assert result["results"] == []

        # No summary (llm=None)
        assert result["summary"] is None

    def test_shared_concepts_detected_by_normalization(self):
        """Shared concepts detected via _norm (case-insensitive, no punctuation)."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [
                {"name": "Graph RAG", "definition": "A graph-based RAG approach"},
            ],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        ext_b = {
            "concepts": [
                {"name": "GraphRAG", "definition": "Graph-based retrieval"},  # Different spelling
            ],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        # Should detect as shared (both normalize to "graphrag")
        assert len(result["shared"]["concepts"]) == 1
        assert result["shared"]["concepts"][0] == "Graph RAG"  # First-seen spelling
        assert result["only_a"]["concepts"] == []
        assert result["only_b"]["concepts"] == []

    def test_unique_entities_in_only_sets(self):
        """Entities unique to each paper listed in only_a/only_b."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [
                {"name": "Transformer", "definition": "Attention-based model"},
                {"name": "Graph Neural Network", "definition": "A GNN"},
            ],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        ext_b = {
            "concepts": [
                {"name": "Transformer", "definition": "Attention-based"},  # Shared
                {"name": "LSTM", "definition": "Recurrent architecture"},  # Only in B
            ],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        shared = result["shared"]["concepts"]
        only_a = result["only_a"]["concepts"]
        only_b = result["only_b"]["concepts"]

        assert "Transformer" in shared
        assert "Graph Neural Network" in only_a
        assert "LSTM" in only_b

    def test_entities_sorted_case_insensitively(self):
        """Entity lists sorted case-insensitively."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [
                {"name": "Zebra", "definition": "Animal"},
                {"name": "apple", "definition": "Fruit"},
                {"name": "banana", "definition": "Fruit"},
            ],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        ext_b = {
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)
        concepts = result["only_a"]["concepts"]

        # Should be sorted case-insensitively: apple, banana, Zebra
        assert concepts == ["apple", "banana", "Zebra"]

    def test_results_union_pair_both_papers(self):
        """Results: union of (metric, dataset) pairs, both values present."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [],
            "methods": [],
            "datasets": [
                {"name": "HotpotQA", "description": "Multi-hop QA dataset"},
            ],
            "claims": [],
            "results": [
                {"metric": "F1", "value": "85.2", "dataset": "HotpotQA"},
            ],
            "related_work": [],
        }
        ext_b = {
            "concepts": [],
            "methods": [],
            "datasets": [
                {"name": "HotpotQA", "description": "QA dataset"},
            ],
            "claims": [],
            "results": [
                {"metric": "F1", "value": "87.1", "dataset": "HotpotQA"},
            ],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        results = result["results"]
        assert len(results) == 1
        assert results[0]["metric"] == "F1"
        assert results[0]["dataset"] == "HotpotQA"
        assert results[0]["value_a"] == "85.2"
        assert results[0]["value_b"] == "87.1"

    def test_results_null_when_only_in_one_paper(self):
        """Results: value is null for paper that doesn't have the metric/dataset pair."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [],
            "methods": [],
            "datasets": [
                {"name": "HotpotQA", "description": "QA"},
                {"name": "SQuAD", "description": "SQuAD"},
            ],
            "claims": [],
            "results": [
                {"metric": "F1", "value": "85.2", "dataset": "HotpotQA"},
                {"metric": "F1", "value": "90.0", "dataset": "SQuAD"},
            ],
            "related_work": [],
        }
        ext_b = {
            "concepts": [],
            "methods": [],
            "datasets": [
                {"name": "HotpotQA", "description": "QA"},
            ],
            "claims": [],
            "results": [
                {"metric": "F1", "value": "87.1", "dataset": "HotpotQA"},
            ],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        results = {(r["metric"], r["dataset"]): r for r in result["results"]}

        # SQuAD F1 only in A
        assert results[("F1", "SQuAD")]["value_a"] == "90.0"
        assert results[("F1", "SQuAD")]["value_b"] is None

    def test_results_sorted_by_metric_then_dataset(self):
        """Results sorted by (metric, dataset) tuple."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [
                {"metric": "ROUGE-L", "value": "0.45", "dataset": "XSum"},
                {"metric": "F1", "value": "85.0", "dataset": "SQuAD"},
                {"metric": "Accuracy", "value": "92.0", "dataset": "MNLI"},
            ],
            "related_work": [],
        }
        ext_b = {
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        results = result["results"]
        # Sorted: (Accuracy, MNLI), (F1, SQuAD), (ROUGE-L, XSum)
        assert results[0]["metric"] == "Accuracy"
        assert results[1]["metric"] == "F1"
        assert results[2]["metric"] == "ROUGE-L"

    def test_malformed_results_skipped(self):
        """Malformed result entries (missing metric field) are skipped."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [
                {"metric": "F1", "value": "85.0", "dataset": "SQuAD"},
                {"value": "87.0", "dataset": "SQuAD"},  # Missing metric
            ],
            "related_work": [],
        }
        ext_b = {
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        # Should only include the well-formed result
        assert len(result["results"]) == 1
        assert result["results"][0]["metric"] == "F1"

    def test_missing_extraction_for_one_paper(self):
        """Missing extraction for B -> B's entity sets empty, no crash."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [
                {"name": "Concept1", "definition": "C1"},
            ],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B")  # No extraction

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        # A's entities are in only_a
        assert result["only_a"]["concepts"] == ["Concept1"]
        assert result["only_b"]["concepts"] == []
        assert result["shared"]["concepts"] == []

    def test_summary_none_when_llm_none(self):
        """Summary is null when llm=None."""
        from research_companion.compare import compare_papers
        _make_paper("arxiv:2001", "Paper A")
        _make_paper("arxiv:2002", "Paper B")

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)
        assert result["summary"] is None

    def test_summary_generated_when_llm_provided(self):
        """Summary generated and llm called when llm provided."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [{"name": "Concept A", "definition": "CA"}],
            "methods": [{"name": "Method A", "description": "MA"}],
            "datasets": [],
            "claims": [{"text": "Claim A"}],
            "results": [],
            "related_work": [],
        }
        ext_b = {
            "concepts": [{"name": "Concept B", "definition": "CB"}],
            "methods": [],
            "datasets": [],
            "claims": [{"text": "Claim B"}],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        calls = []
        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return "This is a comparison."

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=fake_llm)

        # LLM should have been called
        assert len(calls) == 1
        # Both titles should be in the prompt
        assert "Paper A" in calls[0]
        assert "Paper B" in calls[0]
        # Summary should be present
        assert result["summary"] == "This is a comparison."

    def test_summary_null_if_llm_raises(self):
        """Summary is null if llm raises, but deterministic part intact."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [{"name": "Concept A", "definition": "CA"}],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B")

        def failing_llm(prompt: str) -> str:
            raise RuntimeError("LLM failed")

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=failing_llm)

        # Summary null but everything else intact
        assert result["summary"] is None
        assert result["only_a"]["concepts"] == ["Concept A"]

    def test_results_normalization_matches_graph(self):
        """Results use normalized (metric, dataset) matching _norm."""
        from research_companion.compare import compare_papers

        ext_a = {
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [
                {"metric": "F-1", "value": "85.0", "dataset": "Hot-Pot-QA"},
            ],
            "related_work": [],
        }
        ext_b = {
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [
                {"metric": "f1", "value": "87.0", "dataset": "hotpotqa"},
            ],
            "related_work": [],
        }
        _make_paper("arxiv:2001", "Paper A", extraction=ext_a)
        _make_paper("arxiv:2002", "Paper B", extraction=ext_b)

        result = compare_papers("arxiv:2001", "arxiv:2002", llm=None)

        # Should recognize as same pair despite different normalization
        assert len(result["results"]) == 1
        assert result["results"][0]["value_a"] == "85.0"
        assert result["results"][0]["value_b"] == "87.0"
