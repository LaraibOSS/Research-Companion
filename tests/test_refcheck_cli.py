"""End-to-end tests for the `research-companion refcheck` CLI command.

The authoritative lookup is monkeypatched, so no network is hit.
"""
from __future__ import annotations

import json

import pytest

from research_companion import cli, store
from research_companion.prompts import extraction_prompt_sha256
from research_companion.refcheck import retrieval


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


def test_refcheck_cli_suspect_uses_standard_warn_glyph(monkeypatch: pytest.MonkeyPatch, capsys):
    """A 'suspect' verdict (record found but title mismatched) must print the
    shared WARN glyph ("!!"), not the old per-command "??" literal."""
    paper_id = _seed_paper_with_refs(["Some Real Paper Title From 2020"])

    def _lookup(ref):
        return {"title": "A Completely Unrelated Record Title", "authors": [],
                "year": 2020, "doi": None, "arxiv_id": None}

    monkeypatch.setattr(retrieval, "default_lookup", lambda: _lookup)

    rc = cli.main(["refcheck", paper_id])
    assert rc == 0
    out = capsys.readouterr().out
    assert "suspect" in out.lower()
    assert "!!" in out
    assert "??" not in out


def test_refcheck_cli_errors_when_no_extraction(capsys):
    rc = cli.main(["refcheck", "local:doesnotexist"])
    assert rc == 1
    assert "build" in capsys.readouterr().err.lower()


def test_parse_connectors_flag():
    assert cli._parse_connectors_arg("europepmc,pubmed") == ["europepmc", "pubmed"]
    assert cli._parse_connectors_arg(None) is None
    assert cli._parse_connectors_arg("") is None


def test_parse_connectors_comma_only_means_use_settings():
    assert cli._parse_connectors_arg(" , ") is None


def test_parse_connectors_rejects_unknown():
    import pytest
    with pytest.raises(SystemExit):
        cli._parse_connectors_arg("nope")
