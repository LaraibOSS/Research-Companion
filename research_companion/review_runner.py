"""Run the review agent pipeline programmatically and return the report dict.

A read-only, CLI-independent runner for the MCP boundary: no store writes, no
graph rebuild, no readiness-narrative LLM call — those belong to the CLI
(`_cmd_review`), which additionally handles --serve and terminal output. The
small overlap with the CLI's agent-list wiring is deliberate and documented in
both places.

Verified against `_cmd_review` in `research_companion/cli.py` (binding
requirement of this module's task brief):
  (a) agent-list construction mirrors `_cmd_review` exactly: base 7 lanes,
      +6 LLM lanes unless `fast`, +VenueFitAgent/ComplianceAgent when a venue
      is given.
  (b) `_cmd_review` builds `AgentContext(paper_id=..., bus=Bus(log=EventLog(...)),
      data=dict(REVIEW_CONTEXT_OVERRIDES))`. This runner omits the EventLog
      (no `log=` arg to `Bus()`) since EventLog persists a run to
      `<papergraph_dir>/runs/*.jsonl` on disk, which would violate the
      read-only contract; `Bus()` alone still gives agents a working pub/sub
      bus with no disk footprint.
  (c) The venue key is `_venue` (NOT a bare `"venue"` key) — both
      `VenueFitAgent.run` and `ComplianceAgent.run` read
      `ctx.data.get("_venue")` directly.
  (d) The seam keys are `_llm`, `_lookup`, `_search` — exactly what
      `REVIEW_CONTEXT_OVERRIDES` carries in `_cmd_review`/`tests/test_cli_review.py`,
      and what `CitationAgent`/`PriorArtAgent`/`VenueFitAgent` read via
      `ctx.data.get("_lookup")`, `ctx.data.get("_search")`, `ctx.data.get("_llm")`.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable


def _build_agents(venue: str | None, fast: bool) -> list:
    # Mirrors _cmd_review's agent-list construction exactly (see cli.py).
    from research_companion.agents.benchmark import BenchmarkAgent
    from research_companion.agents.citation import CitationAgent
    from research_companion.agents.citation_polarity import CitationPolarityAgent
    from research_companion.agents.compliance import ComplianceAgent
    from research_companion.agents.confidence import ConfidenceAgent
    from research_companion.agents.ethics import EthicsAgent
    from research_companion.agents.ingest import IngestAgent
    from research_companion.agents.novelty import NoveltyAgent
    from research_companion.agents.overlap import OverlapAgent
    from research_companion.agents.priorart import PriorArtAgent
    from research_companion.agents.reproducibility import ReproducibilityAgent
    from research_companion.agents.severity import SeverityAgent
    from research_companion.agents.statsoundness import StatSoundnessAgent
    from research_companion.agents.taxonomy import TaxonomyAgent
    from research_companion.agents.venuefit import VenueFitAgent

    agents: list = [IngestAgent(), CitationAgent(), PriorArtAgent(),
                    StatSoundnessAgent(), ReproducibilityAgent(), EthicsAgent(),
                    OverlapAgent()]
    if not fast:
        agents += [NoveltyAgent(), CitationPolarityAgent(), ConfidenceAgent(),
                   BenchmarkAgent(), SeverityAgent(), TaxonomyAgent()]
    if venue:
        agents.append(VenueFitAgent())
        agents.append(ComplianceAgent())
    return agents


def run_review(paper_id: str, *, venue: str | None = None, fast: bool = False,
               llm: Callable[[str], str] | None = None,
               lookup=None, search=None) -> dict:
    """Run the review lanes for *paper_id* and return the report dict.

    Read-only: nothing is persisted. Seams (`llm`, `lookup`, `search`) inject
    fakes for tests, mirroring the CLI's context-override keys. Safe to call
    from sync code OR from inside a running event loop (FastMCP).
    """
    from research_companion.agents.base import AgentContext
    from research_companion.agents.bus import Bus
    from research_companion.agents.orchestrator import run_agents
    from research_companion.report import build_report_json
    from research_companion.store import PaperMetadata

    data: dict = {}
    # Verified: VenueFitAgent/ComplianceAgent read ctx.data["_venue"] (agents/venuefit.py,
    # agents/compliance.py), and the seam keys are _llm/_lookup/_search
    # (agents/citation.py, agents/priorart.py, agents/venuefit.py; also
    # REVIEW_CONTEXT_OVERRIDES in cli.py / tests/test_cli_review.py).
    if venue:
        data["_venue"] = venue
    if llm is not None:
        data["_llm"] = llm
    if lookup is not None:
        data["_lookup"] = lookup
    if search is not None:
        data["_search"] = search

    agents = _build_agents(venue, fast)
    # No EventLog here (unlike _cmd_review's Bus(log=EventLog(log_path))) —
    # this runner must not write anything to disk.
    ctx = AgentContext(paper_id=paper_id, bus=Bus(), data=data)

    def _execute() -> dict:
        return asyncio.run(run_agents(agents, ctx))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        results = _execute()            # plain sync context
    else:
        # A loop is already running (e.g. inside an MCP server): run the
        # pipeline on its own fresh loop in a worker thread.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            results = pool.submit(_execute).result()

    meta = PaperMetadata.load(paper_id)
    return build_report_json(paper_id, meta.title if meta else "", results)
