"""Running chosen agents: plan, refuse clearly, execute, and keep earlier results."""
from __future__ import annotations

import json
import time

import pytest

from research_companion import store
from research_companion.agents.runner import (
    lane_summary,
    merge_report,
    plan_run,
    runnable_here,
)
from research_companion.prompts import extraction_prompt_sha256


def test_dependencies_are_added_and_reported():
    plan = plan_run(["novelty"])
    assert plan.ok
    assert plan.agents.index("ingest") < plan.agents.index("priorart") < plan.agents.index("novelty")
    assert set(plan.added) == {"ingest", "priorart"}
    assert plan.uses_model and plan.uses_network


def test_a_free_selection_uses_no_model():
    plan = plan_run(["statsoundness", "overlap"])
    assert plan.ok and not plan.uses_model and not plan.uses_network
    assert plan.agents == ["ingest", "statsoundness", "overlap"]


def test_every_problem_is_reported_at_once():
    plan = plan_run(["nonsense", "compliance", "problem", "rebuttal"])
    text = " ".join(plan.problems)
    assert not plan.ok
    assert "'nonsense'" in text
    assert "Venue rules checker needs a venue" in text
    assert "needs a problem statement" in text
    assert "only be given from the command line" in text


def test_supplied_inputs_satisfy_needs():
    plan = plan_run(["compliance", "problem"],
                    inputs={"venue": "neurips", "problem_statement": "We study X."})
    assert plan.ok


def test_an_empty_selection_is_refused():
    assert not plan_run([]).ok


def test_runnable_here_excludes_only_command_line_agents():
    assert runnable_here("statsoundness") and runnable_here("problem")
    assert not runnable_here("rebuttal")


def test_merging_keeps_earlier_lanes_and_recomputes_readiness():
    previous = {"paper_id": "p", "title": "T",
                "lanes": {"citation": {"ok": True, "error": "",
                                       "data": {"counts": {"verified": 9, "suspect": 0,
                                                           "unverified": 0}}}},
                "readiness": {"verdict": "stale"}}
    fresh = {"paper_id": "p", "title": "T",
             "lanes": {"statsoundness": {"ok": True, "error": "",
                                         "data": {"summary": {"n_tests": 0, "n_means": 0}}}}}
    merged = merge_report(previous, fresh)
    assert set(merged["lanes"]) == {"citation", "statsoundness"}
    assert merged["readiness"]["verdict"] == "ready"
    assert "statsoundness" in merged["readiness"]["coverage"]["nothing_checked"]


def test_lane_summary_states():
    assert lane_summary("x", None)["state"] == "not_run"
    assert lane_summary("x", {"ok": False, "error": "boom"}) == {
        "agent": "x", "state": "failed", "error": "boom", "headline": None}
    assert lane_summary("x", {"ok": True})["state"] == "done"


# --- through the Lab API -------------------------------------------------------

def _seed(paper_id="local:agentrun01"):
    store.PaperMetadata(paper_id=paper_id, title="A paper", authors=["A"]).save()
    store.save_text(paper_id, "Introduction. We report t(20) = 2.10, p = .049 in a test.")
    store.save_extraction(
        paper_id,
        {"concepts": [{"name": "RAG", "definition": "d"}], "methods": [], "datasets": [],
         "claims": [], "results": [], "related_work": []},
        prompt_sha=extraction_prompt_sha256())
    return paper_id


def _client(llm=None):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from research_companion.agents.bus import Bus
    from research_companion.lab_api import create_lab_app

    app = create_lab_app(Bus(), llm=llm) if llm else create_lab_app(Bus())
    app.state.agent_context_overrides = {"_lookup": lambda ref: None,
                                         "_search": lambda q: []}
    return app, TestClient(app)


def _wait_job(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_run_free_agents_and_keep_the_result(isolated_papergraph_dir):
    pid = _seed()
    _app, c = _client()
    with c:
        r = c.post("/api/agents/run", json={"paper_id": pid, "agents": ["statsoundness"]})
        assert r.status_code == 202, r.text
        assert r.json()["agents"] == ["ingest", "statsoundness"]
        assert r.json()["uses_model"] is False
        assert _wait_job(c, r.json()["job_id"])["status"] == "done"

        report = store.load_review_report(pid)
        assert report["lanes"]["statsoundness"]["ok"] is True
        listing = c.get("/api/agents", params={"paper_id": pid}).json()
        last = {a["name"]: a["last"]["state"] for a in listing["agents"]}
        assert last["statsoundness"] == "done" and last["citation"] == "not_run"


def test_a_second_run_does_not_erase_the_first(isolated_papergraph_dir):
    pid = _seed()
    _app, c = _client()
    with c:
        for agents in (["statsoundness"], ["overlap"]):
            r = c.post("/api/agents/run", json={"paper_id": pid, "agents": agents})
            _wait_job(c, r.json()["job_id"])
    assert {"statsoundness", "overlap", "ingest"} <= set(store.load_review_report(pid)["lanes"])


def test_refusals_come_back_as_a_list(isolated_papergraph_dir, monkeypatch):
    monkeypatch.setattr("research_companion.lab_api._llm_provider_configured", lambda: False)
    _app, c = _client()
    with c:
        r = c.post("/api/agents/run", json={"paper_id": "local:nope",
                                            "agents": ["novelty", "compliance"]})
    assert r.status_code == 400
    problems = r.json()["detail"]["problems"]
    assert any("not in this research" in p for p in problems)
    assert any("no model is set up" in p for p in problems)
    assert any("needs a venue" in p for p in problems)


def test_a_model_agent_runs_with_the_configured_model(isolated_papergraph_dir):
    pid = _seed()
    calls = []

    def fake_llm(prompt):
        calls.append(prompt)
        return json.dumps({"themes": []})

    _app, c = _client(llm=fake_llm)
    with c:
        r = c.post("/api/agents/run", json={"paper_id": pid, "agents": ["taxonomy"]})
        assert r.status_code == 202, r.text
        assert r.json()["uses_model"] is True
        _wait_job(c, r.json()["job_id"])
    assert "taxonomy" in store.load_review_report(pid)["lanes"]


def test_listing_reports_runnability_and_model_state(isolated_papergraph_dir):
    _app, c = _client()
    body = c.get("/api/agents").json()
    by_name = {a["name"]: a for a in body["agents"]}
    assert by_name["rebuttal"]["runnable_here"] is False
    assert by_name["statsoundness"]["runnable_here"] is True
    assert "last" not in by_name["statsoundness"]
    assert isinstance(body["model_configured"], bool)


# --- from the command line -----------------------------------------------------

def test_run_agents_command_runs_free_agents_and_saves(isolated_papergraph_dir, capsys,
                                                       monkeypatch):
    from research_companion import cli

    pid = _seed()
    monkeypatch.setattr(cli, "RUN_AGENTS_OVERRIDES",
                        {"_lookup": lambda ref: None, "_search": lambda q: []})
    assert cli.main(["run-agents", pid, "statsoundness"]) == 0
    out = capsys.readouterr().out
    assert "Also running, because the chosen agents need them: Reader" in out
    assert "ok Statistics checker" in out
    assert "paid" not in out
    assert store.load_review_report(pid)["lanes"]["statsoundness"]["ok"] is True


def test_run_agents_command_refuses_with_reasons(isolated_papergraph_dir, capsys, monkeypatch):
    from research_companion import cli

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["run-agents", "local:missing", "novelty", "compliance"]) == 1
    err = capsys.readouterr().err
    assert "not in this research" in err
    assert "no model key is set" in err
    assert "needs a venue" in err


def test_the_two_formerly_unreachable_agents_can_now_run(isolated_papergraph_dir, capsys,
                                                         monkeypatch):
    from research_companion import cli

    pid = _seed()
    monkeypatch.setattr(cli, "RUN_AGENTS_OVERRIDES", {
        "_lookup": lambda ref: None, "_search": lambda q: [],
        "_llm": lambda prompt: json.dumps({"refined_statement": "R", "gaps": [],
                                           "suggestions": []}),
    })
    # The new-work watcher searches recent work; keep it offline.
    monkeypatch.setattr("research_companion.discover.search_topic_with_fallback",
                        lambda q, **kw: [])
    rc = cli.main(["run-agents", pid, "tracker", "problem",
                   "--problem-statement", "Retrieval adds latency.", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["lanes"]["tracker"]["ok"] is True
    assert "problem" in payload["lanes"]
    assert rc in (0, 1)


# --- what a finished agent says ------------------------------------------------

def test_headlines_state_what_was_found_and_the_denominator():
    from research_companion.agents.headlines import headline

    assert headline("citation", {"counts": {"verified": 9, "suspect": 1, "unverified": 2}}) == (
        "9 found, 1 with mismatched details, 2 not found, of 12 references.")
    assert headline("citation", {"counts": {}}) == "No references were found to check."
    assert headline("statsoundness", {"summary": {"text": "no parseable statistics found"}}) == (
        "No parseable statistics found.")
    assert headline("compliance", {"checks": [{"status": "skipped"}]}) == (
        "No venue rule could be applied.")
    assert headline("compliance", {"checks": [{"status": "ok"}, {"status": "finding"}]}) == (
        "1 problem in 2 rules checked.")
    assert headline("novelty", {"counts": {"novel": 1, "unassessed": 2}}) == (
        "1 novel, 2 unassessed.")
    assert headline("venuefit", {"skipped": True, "reason": "unknown venue: x"}) == (
        "Not assessed: unknown venue: x.")


def test_an_unknown_or_malformed_result_gets_no_headline():
    from research_companion.agents.headlines import headline

    assert headline("problem", {"anything": 1}) is None
    assert headline("citation", None) is None
    assert headline("citation", {"counts": "not a dict"}) is None


def test_lane_summary_carries_the_headline():
    lane = {"ok": True, "data": {"count": 3}}
    assert lane_summary("priorart", lane)["headline"] == "Found 3 related papers."
