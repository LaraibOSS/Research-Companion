"""End-to-end tests for the `papergraph refcheck` CLI command.

The authoritative lookup is monkeypatched, so no network is hit.
"""
from __future__ import annotations

import json

import pytest

from papergraph import cli, store
from papergraph.prompts import extraction_prompt_sha256
from papergraph.refcheck import retrieval


def _seed_paper_with_refs(related_work: list[str]) -> str:
    paper_id = "local:deadbeef0001"
    store.PaperMetadata(paper_id=paper_id, title="Citing Paper", authors=["Author"]).save()
    store.save_extraction(
        paper_id,
        {"concepts": [], "methods": [], "datasets": [], "related_work": related_work},
        prompt_sha=extraction_prompt_sha256(),
    )
    return paper_id


def _stub_lookup_known_title(title_substr: str):
    """A default_lookup() replacement: returns a record only for a known title."""
    def _make():
        def _lookup(ref):
            if title_substr.lower() in ref.title.lower():
                return {"title": ref.title, "authors": [], "year": 2017,
                        "doi": None, "arxiv_id": None}
            return None
        return _lookup
    return _make


def test_refcheck_cli_reports_counts(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed_paper_with_refs(
        ["Attention Is All You Need", "A Fabricated Nonexistent Paper Title"]
    )
    monkeypatch.setattr(retrieval, "default_lookup",
                        _stub_lookup_known_title("Attention Is All You Need"))

    rc = cli.main(["refcheck", paper_id])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "verified" in out
    assert "unverified" in out


def test_refcheck_cli_json_output(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed_paper_with_refs(["Attention Is All You Need"])
    monkeypatch.setattr(retrieval, "default_lookup",
                        _stub_lookup_known_title("Attention Is All You Need"))

    rc = cli.main(["refcheck", paper_id, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["verified"] == 1
    assert len(payload["references"]) == 1
    assert payload["references"][0]["status"] == "verified"


def test_refcheck_cli_errors_when_no_extraction(capsys):
    rc = cli.main(["refcheck", "local:doesnotexist"])
    assert rc == 1
    assert "build" in capsys.readouterr().err.lower()
