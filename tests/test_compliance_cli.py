"""End-to-end tests for the `research-companion check-compliance` CLI command."""
from __future__ import annotations

import json

from research_companion import cli, store


def test_check_compliance_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "load_text", lambda pid: "Introduction\nBody")
    monkeypatch.setattr(store, "load_sections", lambda pid: None)
    monkeypatch.setattr(store, "pdf_page_count", lambda pid: 20)
    args = cli._build_parser().parse_args(
        ["check-compliance", "p", "--venue", "neurips", "--json"])
    rc = args.func(args)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["venue"] == "neurips" and "checks" in payload


def test_check_compliance_requires_venue(capsys):
    # unknown venue -> exit 1 with message
    args = cli._build_parser().parse_args(["check-compliance", "p", "--venue", "nope"])
    rc = args.func(args)
    assert rc == 1
    assert "venue" in capsys.readouterr().err.lower()


def test_check_compliance_unknown_venue_lists_valid_slugs(capsys):
    # The error must point at real, inline venue slugs instead of the
    # non-existent `research-companion venue list` command.
    from research_companion.venues import list_venues

    args = cli._build_parser().parse_args(["check-compliance", "p", "--venue", "nope"])
    rc = args.func(args)
    assert rc == 1
    err = capsys.readouterr().err
    assert "venue list" not in err
    for v in list_venues():
        assert v.slug in err


def test_check_compliance_readable_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "load_text", lambda pid: "Introduction\nBody")
    monkeypatch.setattr(store, "load_sections", lambda pid: None)
    monkeypatch.setattr(store, "pdf_page_count", lambda pid: 20)
    args = cli._build_parser().parse_args(["check-compliance", "p", "--venue", "neurips"])
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "verify against the venue" in out.lower()
