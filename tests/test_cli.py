"""Tests for research_companion.cli — end-to-end smoke with all I/O mocked."""
from __future__ import annotations

import json

import pytest

from research_companion import cli, extract, store

# ---------------------------------------------------------------------------
# _glyph — shared status-glyph vocabulary (consistency pass)
# ---------------------------------------------------------------------------

def test_glyph_mapping_covers_each_command_vocabulary():
    # ok
    assert cli._glyph("verified") == "OK"
    assert cli._glyph("consistent") == "OK"
    assert cli._glyph("addressed") == "OK"
    # warn — one consistent symbol, standing in for the old "??"/"[~]" mix
    assert cli._glyph("suspect") == "!!"
    assert cli._glyph("inconsistent") == "!!"
    assert cli._glyph("warning") == "!!"
    assert cli._glyph("partially") == "!!"
    # fail
    assert cli._glyph("unverified") == "XX"
    assert cli._glyph("decision_inconsistent") == "XX"
    assert cli._glyph("desk_reject") == "XX"
    # neutral / unknown falls back to neutral
    assert cli._glyph("skipped") == "--"
    assert cli._glyph("open") == "--"
    assert cli._glyph("totally-unrecognized-status") == "--"


def test_auto_add_discovered_error_has_tool_prefix(capsys):
    """_auto_add_discovered's failure line must start with the research-companion
    prefix, not the old bare '  x failed: ...'."""

    class _FetchError(Exception):
        pass

    class _Result:
        arxiv_id = "1234.5678"
        doi = None
        s2_id = None
        title = "Some Paper"

    def _add_paper_fn(target):
        raise _FetchError("network unavailable")

    added, failed = cli._auto_add_discovered([_Result()], _add_paper_fn, _FetchError)
    assert added == 0
    assert failed == 1
    err = capsys.readouterr().err
    assert err.strip().startswith("research-companion:")
    assert "failed" in err.lower()


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


# ---------------------------------------------------------------------------
# check-stats subcommand — standardized status glyphs
# ---------------------------------------------------------------------------

def test_check_stats_inconsistent_uses_standard_warn_glyph(capsys):
    """An 'inconsistent' finding must print the shared WARN glyph ("!!"),
    not the old per-command "??" literal."""
    pid = "local:cli_check_stats_001"
    store.PaperMetadata(
        paper_id=pid, title="Stats Paper", authors=["Author"],
        added_at="2024-01-01T00:00:00Z",
    ).save()
    # Recomputed p ~ .04 (significant); reported .001 also significant ->
    # plain "inconsistent" (not a decision flip).
    store.save_text(pid, "t(48) = 2.10, p = .001")

    rc = cli.main(["check-stats", pid])
    assert rc == 0
    out = capsys.readouterr().out
    assert "inconsistent" in out.lower()
    assert "!!" in out
    assert "??" not in out


# ---------------------------------------------------------------------------
# gaps subcommand (W3-T9)
# ---------------------------------------------------------------------------

def test_gaps_json_empty_store(capsys):
    """gaps --json with empty store returns valid shape."""
    rc = cli.main(["gaps", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "papers" in data
    assert "draft_addresses" in data
    assert "stale" in data
    assert data["papers"] == []


def test_gaps_human_stale_message(capsys):
    """gaps (human mode) with no gaps data prints stale message."""
    rc = cli.main(["gaps"])
    assert rc == 0
    out = capsys.readouterr().out
    # Either stale message or no gaps message
    assert "gaps" in out.lower()


def test_gaps_human_mode_uses_standard_warn_glyph(capsys):
    """gaps (human mode) maps a 'partially' resolution to the shared WARN glyph
    ("!!") and no longer emits the old per-command "[~]" literal."""
    from research_companion.prompts import gap_prompt_sha256

    pid = "local:cli_gaps_glyph_001"
    store.PaperMetadata(
        paper_id=pid,
        title="Glyph Gaps Paper",
        authors=["Author"],
        year=2021,
        added_at="2024-01-01T00:00:00Z",
    ).save()
    gid = "gap_glyph_1"
    store.save_gaps(pid, {
        "prompt_sha256": gap_prompt_sha256(),
        "computed_at": "2024-01-01T00:00:00Z",
        "no_gap_sections": False,
        "gaps": [{
            "gap_id": gid,
            "statement": "Cannot handle edge cases.",
            "kind": "limitation",
            "evidence": {"quote": "Cannot handle edge cases.", "verified": True, "match": "exact"},
        }],
    })
    store.save_gap_resolution({
        "gap_prompt_sha256": gap_prompt_sha256(),
        "resolution_prompt_sha256": "irrelevant-for-this-test",
        "papers_sha256": "irrelevant-for-this-test",
        "resolutions": {
            gid: {"status": "partially", "resolved_by": None,
                  "rationale": "Partially addressed."},
        },
    })

    rc = cli.main(["gaps"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "!!" in out
    assert "[~]" not in out


def test_gaps_refresh_with_injected_llm(monkeypatch, capsys):
    """gaps --refresh uses GAPS_CONTEXT_OVERRIDES['llm']."""
    # Create a paper with limitations section
    pid = "local:cli_gaps_001"
    text = (
        "Introduction\nSome intro.\n\n"
        "Limitations\nWe could not scale this approach. "
        "Scalability remains a challenge.\n"
    )
    store.PaperMetadata(
        paper_id=pid,
        title="CLI Gaps Paper",
        authors=["Author"],
        year=2021,
        added_at="2024-01-01T00:00:00Z",
    ).save()
    store.save_text(pid, text)
    # Save sections with a Limitations section
    store.save_sections(pid, {
        "version": 1,
        "text_sha256": "sha_cli",
        "method": "heuristic",
        "sections": [
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": text.find("Limitations")},
            {"section_id": "s2", "title": "Limitations", "level": 1,
             "parent": None, "char_start": text.find("Limitations"), "char_end": len(text)},
        ],
    })

    call_count = [0]

    def fake_llm(prompt: str) -> str:
        call_count[0] += 1
        return json.dumps({
            "gaps": [],
            "status": "open",
            "resolved_by": None,
            "rationale": "Not addressed.",
            "evidence_quote": "",
        })

    monkeypatch.setattr(cli, "GAPS_CONTEXT_OVERRIDES", {"llm": fake_llm})
    rc = cli.main(["gaps", "--refresh", "--json"])
    assert rc == 0
    assert call_count[0] >= 1, "LLM must be called during refresh"
    out = capsys.readouterr().out
    # Output includes status messages before JSON; find the JSON object
    brace_idx = out.find("{")
    assert brace_idx != -1, f"No JSON found in output: {out!r}"
    data = json.loads(out[brace_idx:])
    assert "papers" in data


# ---------------------------------------------------------------------------
# timeline subcommand (W3-T9)
# ---------------------------------------------------------------------------

def test_timeline_json_empty_store(capsys):
    """timeline --json with empty store returns valid shape."""
    rc = cli.main(["timeline", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "years" in data
    assert "papers_per_year" in data
    assert "tracks" in data
    assert "skipped_papers_without_year" in data
    assert "truncated_tracks" in data


def test_timeline_human_empty_store(capsys):
    """timeline (human mode) with empty store prints message."""
    rc = cli.main(["timeline"])
    assert rc == 0
    out = capsys.readouterr().out
    assert len(out) >= 0  # just doesn't crash


def test_timeline_json_with_papers(tmp_path, fake_pdf_bytes, monkeypatch, capsys,
                                    sample_extraction):
    """timeline --json with papers that have years returns tracks."""
    from research_companion import extract as _ext

    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    cli.main(["add", str(pdf), "--title", "Timeline Paper", "--year", "2022"])
    capsys.readouterr()

    monkeypatch.setattr(
        _ext, "_call_anthropic",
        lambda prompt, model, max_output_tokens=2048: (
            json.dumps(sample_extraction), {"input_tokens": 1, "output_tokens": 1},
        ),
    )
    cli.main(["build", "--provider", "anthropic"])
    capsys.readouterr()

    rc = cli.main(["timeline", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "years" in data
    assert isinstance(data["years"], list)
    assert "tracks" in data
