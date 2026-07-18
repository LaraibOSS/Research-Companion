import asyncio
import json

from research_companion import store
from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.citation_polarity import CitationPolarityAgent


def _run(agent, ctx):
    return asyncio.run(agent.run(ctx))


def _ctx(paper_id, data):
    return AgentContext(paper_id=paper_id, bus=Bus(), data=data)


def test_verified_stance_kept_unverified_demoted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "load_text", lambda pid: "We build on Lewis. Unrelated sentence.")
    ext = {"related_work": ["Lewis et al. 2020", "Ghost 1999"], "paper_meta": {"title": "T"}}
    def fake_llm(prompt):
        return json.dumps({"citations": [
            {"cite": "Lewis et al. 2020", "polarity": "based_on",
             "evidence_quote": "We build on Lewis.", "rationale": "x"},
            {"cite": "Ghost 1999", "polarity": "refutation",
             "evidence_quote": "quote that is not in the text", "rationale": "y"},
        ]})
    ctx = _ctx("arxiv:1", {"_extraction": ext, "_llm": fake_llm})
    res = _run(CitationPolarityAgent(), ctx)
    assert res.ok
    by = {c["cite"]: c for c in res.data["citations"]}
    assert by["Lewis et al. 2020"]["polarity"] == "based_on" and by["Lewis et al. 2020"]["verified"] is True
    # unverified evidence -> demoted to mention
    assert by["Ghost 1999"]["polarity"] == "mention" and by["Ghost 1999"]["verified"] is False
    # sidecar persisted with the same verdicts
    side = store.load_citation_polarity("arxiv:1")
    assert side["Lewis et al. 2020"]["polarity"] == "based_on"
    assert side["Ghost 1999"]["polarity"] == "mention"


def test_no_related_work_no_llm_call(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "load_text", lambda pid: "text")
    def boom(prompt):
        raise AssertionError("LLM must not be called when related_work is empty")
    ctx = _ctx("arxiv:2", {"_extraction": {"related_work": [], "paper_meta": {"title": "T"}}, "_llm": boom})
    res = _run(CitationPolarityAgent(), ctx)
    assert res.ok and res.data["citations"] == []
