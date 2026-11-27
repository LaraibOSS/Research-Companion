"""Regenerate tests/js/fixtures_home_path.json from the real Lab endpoints.

The Home path (pathHelpers.js) decides which research stage is done from what
the Lab serves: GET /api/papers, /api/lab, /api/gaps, /api/brainstorm/session
and /api/agents?paper_id=<draft>. Hand-written fixtures have encoded assumed
shapes in this project before, so these are produced by building a throwaway
research in a temp directory, step by step, and recording what each endpoint
actually returns at every step. Nothing touches the user's real store, and no
model is called: extractions, gap themes and agent results are written to the
store directly, the way the paid pipeline would leave them.

    python scripts/generate_home_path_fixtures.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "tests" / "js" / "fixtures_home_path.json"


def _extraction() -> dict:
    return {
        "concepts": [{"name": "Speculative decoding", "definition": "Draft then verify"}],
        "methods": [{"name": "KV cache compression", "description": "Smaller cache"}],
        "datasets": [], "claims": [], "results": [], "related_work": [],
    }


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="rc-home-path-")
    os.environ["RESEARCH_COMPANION_DIR"] = str(pathlib.Path(tmp) / "root")
    os.environ.pop("RESEARCH_COMPANION_WORKSPACE", None)

    from fastapi.testclient import TestClient

    from research_companion import graph, store, workspaces
    from research_companion.agents.bus import Bus
    from research_companion.gaps import _papers_sha
    from research_companion.lab_api import create_lab_app
    from research_companion.prompts import (
        extraction_prompt_sha256,
        gap_prompt_sha256,
        gap_resolution_prompt_sha256,
        gap_synthesis_prompt_sha256,
    )

    store._reset_workspace_caches()
    workspaces.create_workspace("Home path fixture")
    reg = store.load_registry()
    workspaces.activate_workspace(reg["workspaces"][0]["id"])
    store._reset_workspace_caches()
    store.papergraph_dir().mkdir(parents=True, exist_ok=True)

    client = TestClient(create_lab_app(Bus(), llm=None))

    def paper(pid: str, title: str, *, extracted: bool) -> None:
        store.PaperMetadata(paper_id=pid, title=title, authors=["A. Author"],
                            year=2024, added_at="2026-01-01T00:00:00Z").save()
        store.save_text(pid, f"Full text of {title}. " * 20)
        if extracted:
            store.save_extraction(pid, _extraction(), prompt_sha=extraction_prompt_sha256())

    def snapshot(note: str) -> dict:
        lab = client.get("/api/lab").json()
        draft_id = lab.get("draft_id")
        agents = client.get("/api/agents", params={"paper_id": draft_id}).json() if draft_id else None
        if agents is not None:
            # Only the fields the path reads; the full catalogue is already
            # pinned by fixtures_agents.json and model_configured depends on
            # the machine that ran this script.
            agents = {"agents": [{"name": a["name"], "stage": a["stage"],
                                  "cost": a["cost"], "last": a.get("last")}
                                 for a in agents["agents"]]}
        lab = {k: lab[k] for k in ("draft_id", "paper_count", "node_count", "edge_count")}
        return {
            "note": note,
            "papers": client.get("/api/papers").json(),
            "lab": lab,
            "gaps": client.get("/api/gaps").json(),
            "brainstorm": client.get("/api/brainstorm/session").json(),
            "agents": agents,
        }

    cases: dict[str, dict] = {}
    cases["empty"] = snapshot("A new research with nothing in it.")

    # Two papers added but not read: one still pending (no extraction), one
    # whose PDF could not be obtained (a failure record).
    paper("arxiv:2401.00001", "Fast Inference via Speculation", extracted=False)
    paper("arxiv:2401.00002", "Paged Attention", extracted=False)
    store.record_failure("arxiv:2401.00002", {"stage": "sections", "paper_id": "arxiv:2401.00002",
                                              "error": "no PDF on disk for arxiv:2401.00002"})
    cases["collected_unread"] = snapshot("Papers added; none read yet.")

    # One paper read (extraction saved) but the graph not rebuilt yet.
    store.save_extraction("arxiv:2401.00001", _extraction(), prompt_sha=extraction_prompt_sha256())
    cases["read_no_graph"] = snapshot("A paper is read, but the graph is still empty.")

    graph.save_graph(graph.build_graph())
    cases["understood"] = snapshot("A paper is read and mapped into the graph.")

    # Per-paper gaps exist, but they were never grouped into themes.
    store.save_gaps("arxiv:2401.00001", {
        "prompt_sha256": gap_prompt_sha256(), "computed_at": "2026-01-02T00:00:00Z",
        "no_gap_sections": False,
        "gaps": [{"gap_id": "g1", "statement": "Does not evaluate long contexts.",
                  "kind": "limitation",
                  "evidence": {"quote": "", "verified": False, "match": ""}}],
    })
    cases["gaps_unthemed"] = snapshot("Per-paper gaps exist; no themes yet.")

    p_sha = _papers_sha([m.paper_id for m in store.list_papers()])
    store.save_gap_synthesis({
        "gap_prompt_sha256": gap_prompt_sha256(),
        "resolution_prompt_sha256": gap_resolution_prompt_sha256(),
        "papers_sha256": p_sha,
        "synthesis_prompt_sha256": gap_synthesis_prompt_sha256(),
        "computed_at": "2026-01-02T00:00:00Z",
        "themes": [{"theme_id": "t1", "title": "Long-context evaluation", "gap_ids": ["g1"]}],
    })
    cases["gaps_themed"] = snapshot("Open problems grouped into themes.")

    # A separate research path: directions generated in Brainstorm, no themes.
    client.put("/api/brainstorm/session", json={"session": {
        "v": 1, "topic": "LLM inference", "rawDirections": [{"id": "d1", "title": "Adaptive drafting"}],
        "directionsHasGenerated": True}})
    cases["directions"] = snapshot("Directions generated in Brainstorm.")

    # A draft is added but not read yet.
    paper("local:draft0001", "My Draft", extracted=False)
    store.set_draft_paper_id("local:draft0001")
    cases["draft_unread"] = snapshot("A draft is set; it has not been read.")

    store.save_extraction("local:draft0001", _extraction(), prompt_sha=extraction_prompt_sha256())
    cases["draft_read"] = snapshot("The draft is read; no checks have run.")

    # Only the Reader ran: that loads the paper, it checks nothing.
    store.save_review_report("local:draft0001", {
        "paper_id": "local:draft0001", "title": "My Draft",
        "lanes": {"ingest": {"ok": True, "error": "", "data": {}}},
    })
    cases["draft_reader_only"] = snapshot("Only the Reader agent has run on the draft.")

    store.save_review_report("local:draft0001", {
        "paper_id": "local:draft0001", "title": "My Draft",
        "lanes": {
            "ingest": {"ok": True, "error": "", "data": {}},
            "statsoundness": {"ok": False, "error": "no statistics found", "data": None},
        },
    })
    cases["draft_check_failed"] = snapshot("A check ran on the draft and failed.")

    store.save_review_report("local:draft0001", {
        "paper_id": "local:draft0001", "title": "My Draft",
        "lanes": {
            "ingest": {"ok": True, "error": "", "data": {}},
            "citation": {"ok": True, "error": "", "data": {
                "counts": {"verified": 3, "unverified": 1, "suspect": 0},
                "references": []}},
        },
    })
    cases["draft_checked"] = snapshot("The reference checker has run on the draft.")

    OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
