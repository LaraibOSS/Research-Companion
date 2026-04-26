"""Tests for papergraph.cli — end-to-end smoke with all I/O mocked."""
from __future__ import annotations

import json

import pytest

from papergraph import cli, extract, fetch, prompts, store


def test_help_smoke(capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "papergraph" in out
    for sub in ("add", "build", "view", "chat", "list", "remove", "stats"):
        assert sub in out


def test_version_smoke(capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "papergraph" in out.lower()


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
    from papergraph import chat as chat_mod
    monkeypatch.setattr(
        chat_mod, "_call_anthropic",
        lambda system, user, model: ("GraphRAG is a method for graph-based retrieval "
                                      "[GraphRAG paper].", {"input_tokens": 50, "output_tokens": 12}),
    )

    rc = cli.main(["chat", "What is GraphRAG?"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "GraphRAG" in out
