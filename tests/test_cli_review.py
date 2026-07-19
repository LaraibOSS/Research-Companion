"""End-to-end test for `research-companion review` — all network injected, no LLM."""
from __future__ import annotations

import json

import pytest

from research_companion import cli, store
from research_companion.discover import DiscoveredPaper
from research_companion.prompts import extraction_prompt_sha256


def _seed():
    paper_id = "local:review00001"
    store.PaperMetadata(paper_id=paper_id, title="Graph RAG Survey", authors=["A"]).save()
    store.save_extraction(
        paper_id,
        {"concepts": [{"name": "RAG", "definition": "d"}], "methods": [], "datasets": [],
         "claims": [], "results": [],
         "related_work": ["Attention Is All You Need", "A Fabricated Paper Title"]},
        prompt_sha=extraction_prompt_sha256(),
    )
    return paper_id


def _overrides():
    def lookup(ref):
        if "attention" in ref.title.lower():
            return {"title": ref.title, "authors": [], "year": 2017,
                    "doi": None, "arxiv_id": None}
        return None

    def search(query):
        return [DiscoveredPaper(title="GraphRAG", authors=[], year=2024, citation_count=5,
                                arxiv_id="2404.00001", doi=None, s2_id=None, url="")]

    def llm(prompt):
        if '"evidence_quote"' in prompt:
            return json.dumps({"claims": []})
        return json.dumps({"verdict": "novel", "confidence": 0.9,
                           "closest_prior": [], "rationale": "r"})

    return {"_lookup": lookup, "_search": search, "_llm": llm}


def test_review_cli_runs_all_agents(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id])
    out = capsys.readouterr().out
    assert rc == 0
    for lane in ("ingest", "citation", "priorart"):
        assert lane in out
    assert "1 verified" in out and "1 unverified" in out
    assert "1 related papers" in out


def test_review_cli_json(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["paper_id"] == paper_id
    assert payload["agents"]["citation"]["ok"] is True
    assert payload["agents"]["citation"]["data"]["counts"]["verified"] == 1
    # Minor 1 fix: the --json stdout payload must carry the same readiness
    # synthesis as the persisted store copy / report.json, not just the raw
    # per-agent results.
    assert "verdict" in payload["readiness"]


def test_review_cli_json_omits_readiness_when_no_source_lane_ran(capsys):
    # No extraction seeded: ingest fails, every other lane fails as a
    # dependency-of-ingest, so build_readiness() has nothing assessable and
    # returns {}. The --json payload must NOT add a null/empty readiness key
    # in that case (mirrors build_report_json's omit-when-empty contract).
    rc = cli.main(["review", "local:nothere", "--json"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert "readiness" not in payload


def test_review_cli_fails_without_extraction(capsys):
    rc = cli.main(["review", "local:nothere"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out


def _full_overrides():
    ov = _overrides()

    def llm(prompt):
        if '"evidence_quote"' in prompt:
            return json.dumps({"claims": [{"text": "We propose X.", "kind": "method",
                                           "evidence_quote": "We propose X"}]})
        return json.dumps({"verdict": "novel", "confidence": 0.9,
                           "closest_prior": [], "rationale": "r"})

    ov["_llm"] = llm
    return ov


def test_review_cli_full_pipeline_six_lanes(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    store.save_text(paper_id, "Body. We propose X here.")
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _full_overrides())
    rc = cli.main(["review", paper_id])
    out = capsys.readouterr().out
    assert rc == 0
    for lane in ("ingest", "citation", "priorart", "novelty", "confidence", "benchmark"):
        assert lane in out


def test_review_cli_fast_skips_llm_lanes(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--fast"])
    out = capsys.readouterr().out
    assert rc == 0
    # Only check the per-lane summary section: the submission-readiness verdict
    # (added in a later feature) legitimately notes "novelty lane not run —
    # remove --fast" as an honest coverage caveat, which is not a lane result.
    lane_summary = out.split("Submission readiness:")[0]
    assert "novelty" not in lane_summary
    assert "confidence" not in lane_summary
    assert "benchmark" not in lane_summary


def test_review_writes_run_event_log(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--fast"])
    assert rc == 0
    runs = list((store.papergraph_dir() / "runs").glob("*.jsonl"))
    assert runs, "expected a run event log"
    first = json.loads(runs[0].read_text(encoding="utf-8").splitlines()[0])
    assert first["event"] in ("agent_started", "finding")


def test_review_report_flag_writes_html_and_json(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    out_dir = tmp_path / "rep"
    rc = cli.main(["review", paper_id, "--fast", "--report", str(out_dir)])
    assert rc == 0
    assert (out_dir / "report.html").exists() and (out_dir / "report.json").exists()
    payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["lanes"]["citation"]["ok"] is True
    assert "report.html" in capsys.readouterr().out


def test_review_serve_uses_injected_server_and_completes(monkeypatch, capsys):
    paper_id = _seed()
    launched = {}

    def fake_runner(app, port):
        launched["port"] = port

    ov = _overrides()
    ov["_server_runner"] = fake_runner
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", ov)
    rc = cli.main(["review", paper_id, "--fast", "--serve", "--port", "9999"])
    out = capsys.readouterr().out
    assert rc == 0
    assert launched["port"] == 9999
    assert "127.0.0.1:9999" in out
    # Critical 2: injected runner must NOT print the blocking Ctrl+C message
    assert "Ctrl+C" not in out


def _seed_with_id(pid: str):
    """Seed a paper with a specific paper_id (for DOI / slash-containing IDs)."""
    store.PaperMetadata(paper_id=pid, title="DOI Paper Test", authors=["A"]).save()
    store.save_extraction(
        pid,
        {"concepts": [{"name": "RAG", "definition": "d"}], "methods": [], "datasets": [],
         "claims": [], "results": [],
         "related_work": ["Attention Is All You Need", "A Fabricated Paper Title"]},
        prompt_sha=extraction_prompt_sha256(),
    )
    return pid


def test_review_doi_id_creates_run_log(monkeypatch: pytest.MonkeyPatch, capsys):
    """Critical 1: DOI paper_id with '/' must not crash on run-log creation."""
    doi_pid = "doi:10.1145/12345.67890"
    _seed_with_id(doi_pid)
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", doi_pid, "--fast"])
    assert rc == 0
    # A run log must exist and its filename must not contain the raw '/' char.
    runs = list((store.papergraph_dir() / "runs").glob("*.jsonl"))
    doi_runs = [r for r in runs if "doi__10_1145_12345_67890" in r.name]
    assert doi_runs, f"expected a DOI run log, found: {[r.name for r in runs]}"


def test_review_always_persists_store_copy(monkeypatch: pytest.MonkeyPatch, capsys):
    """review always writes a store copy via store.save_review_report (no --report flag)."""
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--fast"])
    assert rc == 0
    # The store copy must exist and be valid JSON with the paper_id
    loaded = store.load_review_report(paper_id)
    assert loaded is not None, "expected a persisted review report in the store"
    assert loaded.get("paper_id") == paper_id


def test_review_persists_store_copy_even_without_report_flag(
    monkeypatch: pytest.MonkeyPatch, capsys
):
    """review stores a copy regardless of --report flag being absent."""
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    # No --report flag
    rc = cli.main(["review", paper_id, "--fast"])
    assert rc == 0
    # load_review_report should find the persisted copy
    loaded = store.load_review_report(paper_id)
    assert loaded is not None
    assert "lanes" in loaded or "agents" in loaded or "paper_id" in loaded


def test_readiness_line_not_ready_shows_blockers():
    readiness = {
        "verdict": "not_ready",
        "blockers": [{"lane": "compliance", "severity": "blocker",
                      "title": "no limitations section detected", "action": "Fix it."}],
        "warnings": [],
        "coverage": {"ran": ["compliance"], "not_run": [], "failed": []},
        "summary": "Not ready — 1 blocker(s) to fix",
    }
    line = cli._readiness_line(readiness)
    assert "NOT READY" in line
    assert "Not ready" in line
    assert "compliance" in line
    assert "no limitations section detected" in line


def test_readiness_line_falsy_returns_empty_string():
    assert cli._readiness_line(None) == ""
    assert cli._readiness_line({}) == ""


# ---------------------------------------------------------------------------
# readiness_narrative attachment (Task 3)
#
# Finding: `_seed()` + `_overrides()` already yields a readiness with a
# warning, with no adjustment needed. `_seed()`'s related_work has two
# entries: "Attention Is All You Need" (found by the stub `lookup`, so
# verified) and "A Fabricated Paper Title" (not found, so unverified).
# readiness._extract_citation() flags `unverified + suspect > 0` as a
# citation warning, so build_readiness() returns verdict "revise" with one
# warning — the nothing-to-narrate gate in _attach_readiness_narrative
# (readiness with no blockers/warnings) is never hit by this stub. No extra
# citation-count tweak was required.
# ---------------------------------------------------------------------------

NARRATIVE_JSON = ('{"take": "Address the blocker first.", '
                  '"plan": ["Fix the compliance blocker"]}')


def _narrative_settings(on: bool):
    from research_companion.settings import DEFAULTS
    s = dict(DEFAULTS)
    s["readiness_narrative"] = on
    return s


def test_narrative_attached_to_json_and_persisted_report(monkeypatch, capsys):
    # setting on + fake narrative llm -> narrative in --json AND the stored report
    paper_id = _seed()
    ov = _overrides()
    ov["_narrative_llm"] = lambda p: NARRATIVE_JSON
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", ov)
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _narrative_settings(True))
    saved = {}
    monkeypatch.setattr("research_companion.store.save_review_report",
                        lambda pid, rep: saved.update({pid: rep}))
    cli.main(["review", paper_id, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["readiness"]["narrative"]["take"] == "Address the blocker first."
    stored = saved[paper_id]
    assert stored["readiness"]["narrative"] == payload["readiness"]["narrative"]


def test_narrative_absent_when_setting_off(monkeypatch, capsys):
    paper_id = _seed()
    ov = _overrides()
    calls = []
    ov["_narrative_llm"] = lambda p: calls.append(p) or NARRATIVE_JSON
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", ov)
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _narrative_settings(False))
    cli.main(["review", paper_id, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "narrative" not in (payload.get("readiness") or {})
    assert calls == []  # llm never invoked when the setting is off


def test_narrative_skipped_under_fast(monkeypatch, capsys):
    paper_id = _seed()
    calls = []
    ov = _overrides()
    ov["_narrative_llm"] = lambda p: calls.append(p) or NARRATIVE_JSON
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", ov)
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _narrative_settings(True))
    cli.main(["review", paper_id, "--fast", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "narrative" not in (payload.get("readiness") or {})
    assert calls == []  # llm never invoked under --fast


def test_terminal_prints_take_on_readable_path(monkeypatch, capsys):
    paper_id = _seed()
    ov = _overrides()
    ov["_narrative_llm"] = lambda p: NARRATIVE_JSON
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", ov)
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _narrative_settings(True))
    cli.main(["review", paper_id])
    out = capsys.readouterr().out
    assert "Reviewer's take: Address the blocker first." in out
