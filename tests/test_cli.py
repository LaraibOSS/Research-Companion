"""Tests for research_companion.cli — end-to-end smoke with all I/O mocked."""
from __future__ import annotations

import json

import pytest

from research_companion import cli, extract, store


def test_help_smoke(capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "research-companion" in out
    for sub in ("add", "build", "view", "chat", "list", "remove", "stats"):
        assert sub in out


def test_version_smoke(capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "research-companion" in out.lower()


def test_list_empty_store(capsys: pytest.CaptureFixture):
    rc = cli.main(["list"])
    assert rc == 0
    assert "no papers" in capsys.readouterr().out.lower()


def test_add_local_pdf_and_list(tmp_path, fake_pdf_bytes, capsys: pytest.CaptureFixture):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    rc = cli.main(["add", str(pdf), "--title", "My Paper", "--authors", "Alice,Bob",
                   "--year", "2026"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "My Paper" in out

    rc2 = cli.main(["list"])
    assert rc2 == 0
    assert "My Paper" in capsys.readouterr().out


def test_remove_paper(tmp_path, fake_pdf_bytes, capsys):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    cli.main(["add", str(pdf), "--title", "Doomed"])
    paper_id = store.list_papers()[0].paper_id
    capsys.readouterr()

    rc = cli.main(["remove", paper_id])
    assert rc == 0
    assert "removed" in capsys.readouterr().out.lower()
    assert store.list_papers() == []


def test_build_then_stats_then_view(monkeypatch: pytest.MonkeyPatch, tmp_path,
                                     fake_pdf_bytes, sample_extraction, capsys):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    cli.main(["add", str(pdf), "--title", "GraphRAG paper"])
    capsys.readouterr()

    monkeypatch.setattr(
        extract, "_call_anthropic",
        lambda prompt, model, max_output_tokens=2048: (
            json.dumps(sample_extraction), {"input_tokens": 1, "output_tokens": 1},
        ),
    )

    rc = cli.main(["build", "--provider", "anthropic"])
    assert rc == 0
    assert store.graph_json_path().exists()
    capsys.readouterr()

    rc2 = cli.main(["stats"])
    assert rc2 == 0
    stats_text = capsys.readouterr().out
    stats = json.loads(stats_text)
    assert stats["nodes_total"] > 0
    assert stats["node_paper"] == 1

    rc3 = cli.main(["view", "--no-open"])
    assert rc3 == 0
    assert store.graph_html_path().exists()


def test_chat_one_shot_with_mocked_llm(monkeypatch, tmp_path, fake_pdf_bytes,
                                         sample_extraction, capsys):
    # Setup: add paper, mock extraction, build graph.
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    cli.main(["add", str(pdf), "--title", "GraphRAG paper"])
    monkeypatch.setattr(
        extract, "_call_anthropic",
        lambda prompt, model, max_output_tokens=2048: (
            json.dumps(sample_extraction), {"input_tokens": 1, "output_tokens": 1},
        ),
    )
    cli.main(["build"])
    capsys.readouterr()

    # Mock chat LLM.
    from research_companion import chat as chat_mod
    monkeypatch.setattr(
        chat_mod, "_call_anthropic",
        lambda system, user, model: ("GraphRAG is a method for graph-based retrieval "
                                      "[GraphRAG paper].", {"input_tokens": 50, "output_tokens": 12}),
    )

    rc = cli.main(["chat", "What is GraphRAG?"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "GraphRAG" in out


def test_compare_unknown_paper_a(capsys):
    """Comparing with unknown paper A returns error."""
    store.PaperMetadata(paper_id="arxiv:0001", title="Paper B", authors=["A"]).save()
    rc = cli.main(["compare", "arxiv:9999", "arxiv:0001"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_compare_unknown_paper_b(capsys):
    """Comparing with unknown paper B returns error."""
    store.PaperMetadata(paper_id="arxiv:0001", title="Paper A", authors=["A"]).save()
    rc = cli.main(["compare", "arxiv:0001", "arxiv:9999"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_compare_same_paper(capsys):
    """Comparing a paper to itself returns error."""
    store.PaperMetadata(paper_id="arxiv:0001", title="Paper A", authors=["A"]).save()
    rc = cli.main(["compare", "arxiv:0001", "arxiv:0001"])
    assert rc == 1
    assert "itself" in capsys.readouterr().err.lower()


def test_compare_json_output(capsys):
    """JSON output mode returns valid JSON."""
    ext_a = {
        "concepts": [{"name": "Concept A", "definition": "CA"}],
        "methods": [], "datasets": [], "claims": [], "results": [], "related_work": [],
    }
    ext_b = {
        "concepts": [{"name": "Concept B", "definition": "CB"}],
        "methods": [], "datasets": [], "claims": [], "results": [], "related_work": [],
    }
    store.PaperMetadata(paper_id="arxiv:0001", title="Paper A", authors=["A"]).save()
    store.PaperMetadata(paper_id="arxiv:0002", title="Paper B", authors=["B"]).save()
    store.save_extraction("arxiv:0001", ext_a, prompt_sha=extract.extraction_prompt_sha256())
    store.save_extraction("arxiv:0002", ext_b, prompt_sha=extract.extraction_prompt_sha256())

    rc = cli.main(["compare", "arxiv:0001", "arxiv:0002", "--json", "--no-summary"])
    assert rc == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["version"] == 1
    assert result["paper_a"]["title"] == "Paper A"
    assert result["paper_b"]["title"] == "Paper B"
    assert "Concept A" in result["only_a"]["concepts"]
    assert "Concept B" in result["only_b"]["concepts"]


def test_compare_human_output(capsys):
    """Human output shows titles, three columns, results."""
    ext_a = {
        "concepts": [{"name": "Concept A", "definition": "CA"}],
        "methods": [{"name": "Method A", "description": "MA"}],
        "datasets": [],
        "claims": [], "results": [], "related_work": [],
    }
    ext_b = {
        "concepts": [{"name": "Concept A", "definition": "CA"}],
        "methods": [],
        "datasets": [],
        "claims": [], "results": [], "related_work": [],
    }
    store.PaperMetadata(paper_id="arxiv:0001", title="Paper One", authors=["A"]).save()
    store.PaperMetadata(paper_id="arxiv:0002", title="Paper Two", authors=["B"]).save()
    store.save_extraction("arxiv:0001", ext_a, prompt_sha=extract.extraction_prompt_sha256())
    store.save_extraction("arxiv:0002", ext_b, prompt_sha=extract.extraction_prompt_sha256())

    rc = cli.main(["compare", "arxiv:0001", "arxiv:0002", "--no-summary"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Paper One" in out
    assert "Paper Two" in out
    assert "Shared" in out
    assert "Paper A" in out  # only_a
    assert "Paper B" in out  # only_b
    assert "Concept A" in out


def test_compare_no_summary_skips_llm(monkeypatch, capsys):
    """--no-summary skips LLM call."""
    ext_a = {
        "concepts": [{"name": "C", "definition": "C"}],
        "methods": [], "datasets": [], "claims": [], "results": [], "related_work": [],
    }
    store.PaperMetadata(paper_id="arxiv:0001", title="P1", authors=["A"]).save()
    store.PaperMetadata(paper_id="arxiv:0002", title="P2", authors=["B"]).save()
    store.save_extraction("arxiv:0001", ext_a, prompt_sha=extract.extraction_prompt_sha256())
    store.save_extraction("arxiv:0002", ext_a, prompt_sha=extract.extraction_prompt_sha256())

    # Use override seam to count LLM calls
    call_count = [0]
    def fake_llm(prompt):
        call_count[0] += 1
        return "Summary"
    monkeypatch.setattr(cli, "COMPARE_CONTEXT_OVERRIDES", {"llm": fake_llm})

    rc = cli.main(["compare", "arxiv:0001", "arxiv:0002", "--no-summary", "--json"])
    assert rc == 0
    assert call_count[0] == 0  # LLM not called


def test_compare_with_injected_llm(monkeypatch, capsys):
    """Compare with injected LLM (test seam) includes summary."""
    ext_a = {
        "concepts": [{"name": "C", "definition": "C"}],
        "methods": [], "datasets": [], "claims": [{"text": "Claim A"}], "results": [],
        "related_work": [],
    }
    ext_b = {
        "concepts": [],
        "methods": [], "datasets": [], "claims": [{"text": "Claim B"}], "results": [],
        "related_work": [],
    }
    store.PaperMetadata(paper_id="arxiv:0001", title="P1", authors=["A"]).save()
    store.PaperMetadata(paper_id="arxiv:0002", title="P2", authors=["B"]).save()
    store.save_extraction("arxiv:0001", ext_a, prompt_sha=extract.extraction_prompt_sha256())
    store.save_extraction("arxiv:0002", ext_b, prompt_sha=extract.extraction_prompt_sha256())

    call_count = [0]
    def fake_llm(prompt):
        call_count[0] += 1
        return "Papers differ significantly."
    monkeypatch.setattr(cli, "COMPARE_CONTEXT_OVERRIDES", {"llm": fake_llm})

    rc = cli.main(["compare", "arxiv:0001", "arxiv:0002", "--json"])
    assert rc == 0
    assert call_count[0] == 1  # LLM called
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["summary"] == "Papers differ significantly."
