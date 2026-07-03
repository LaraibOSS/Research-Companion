# Design: papergraph — Agentic, Verifiable Research Companion (EMNLP 2026 Demo)

**Date:** 2026-06-29 · **Target:** EMNLP 2026 System Demonstrations, deadline **2026-07-10** (AoE)
**Status:** Approved by user (design + architecture A + roster + delivery + evaluation)

## 1. Goal & demo story

`pip install papergraph` → `papergraph review draft.pdf --serve`. A team of specialized agents
analyzes a paper draft in parallel; a browser dashboard shows every agent live; the output is an
interactive report where **every verdict links to its evidence**. One-line pitch:
*"A team of agents you can watch — and verify."*

CFP hard requirements this design satisfies:
- **Live demo or installable package (strict):** pip-installable CLI + local dashboard.
- **Evaluation (strict):** two automatic evaluations + case studies (+ optional user study).
- 6-page paper, ≤2.5-min screencast, single-blind, in-person (Budapest).

## 2. Architecture: custom async in-process agent orchestra

New package `papergraph/agents/`. Four runtime units, all small and unit-testable:

| Unit | Responsibility |
|---|---|
| `events.py` | Typed events: `AgentStarted`, `Finding`, `AgentMessage`, `AgentDone`, `AgentError`. JSON-serializable; appended to a JSONL **event log** — the audit trail. |
| `bus.py` | In-process async pub/sub. Agents publish; orchestrator + dashboard subscribe. |
| `base.py` | `Agent` protocol: `name`, `role` (plain-English sentence, shown in UI), `depends_on: list[str]`, `async run(ctx) -> AgentResult`. `ctx` = paper/store handles, graph, bus, LLM client (mockable). |
| `orchestrator.py` | Resolves dependency DAG; runs all ready agents concurrently (`asyncio`); feeds results to dependents; a failing agent marks its lane failed without killing the run. |

Explicitly **not** adopting LangGraph/CrewAI/AutoGen (heavy deps, weaker testability and paper
story) and not process-per-agent (kills pip-install simplicity).

## 3. Agent roster (uniform contract; thin wrappers)

Tier 1 = demo-critical. Tier 2 = built after tier 1 is polished; if the clock wins, the paper
lists them as in-progress.

| Agent | Tier | Depends on | Wraps / does | Output |
|---|---|---|---|---|
| IngestAgent | 1 | — | existing `fetch`+`extract`+`graph` | paper node + knowledge graph |
| CitationAgent | 1 | Ingest | existing `refcheck` | verified / suspect / fabricated per reference |
| PriorArtAgent | 1 | Ingest | existing `discover` + `refcheck.retrieval` | related-work map on the KG |
| BenchmarkAgent | 1 | PriorArt | mines KG: what do related papers evaluate on | ranked benchmark/dataset suggestions |
| NoveltyAgent | 1 | PriorArt | `NOVELTY_ENGINE_SPEC.md` (contribution extraction → comparison → evidence verify) | per-claim verdict + closest prior |
| ConfidenceAgent | 1 | Citation, Novelty | aggregates evidence per claim → score **with uncertainty band** (wider when evidence thin/conflicting) + one-line rationale | per-claim confidence card |
| RebuttalAgent | 1 | Ingest (+ reviews file) | approved rebuttal design (segment → classify → retrieve → draft → verify; tone control; changelog; dedup) | grounded point-by-point replies |
| ProblemStatementAgent | 2 | PriorArt | refines a stated research problem against KG gap structure; suggests next steps | refined statement + step plan |
| TrackerAgent | 2 | PriorArt | one-shot "what's new since?" arXiv/S2 sweep (scheduled tracking = future work) | new-related-work alerts |
| ReportAgent | 1 | all | assembles final HTML + JSON | the deliverable |

## 4. Confidence model

Per claim: gather evidence items (citation verdicts touching the claim, novelty comparison
results, verified evidence spans), each mapped to a signal in [0,1] with a fixed weight
(verified evidence span 1.0 · novelty comparison 0.8 · citation verdict 0.6).
**Score** = weighted mean of signals. **Band** = half-width `0.5/sqrt(n) + 0.5·stdev(signals)`,
clamped to [0.05, 0.5] — few or disagreeing signals → wide band. Every card shows score, band,
and the contributing evidence links. Deterministic, unit-testable; exact constants may be tuned
during evaluation but the formula shape is fixed.

## 5. Dashboard & report

FastAPI + SSE streaming the event log. One static HTML page (vanilla JS, no build step):
- **Live view:** agent lanes (status, latest finding), message feed.
- **Final report:** existing `viz.py` interactive graph + verdict panels + confidence cards +
  rebuttal drafts. Also written to `report.html` + `report.json` without `--serve`.

CLI: `papergraph review <paper> [--reviews f] [--serve] [--json] [--tone ...]` following the
existing `cli.py` subparser pattern.

## 6. Extensibility (honest "plugins/APIs" story)

Three seams, documented — not a plugin manager:
1. **Agent registry** — third parties subclass `Agent` and register; the orchestrator picks it up.
2. **Retriever protocol** — CrossRef/OpenAlex today; S2/arXiv/DBLP drop in (`refcheck.retrieval`).
3. **LLM layer** — existing dual backend (Anthropic/OpenAI) via env keys.

## 7. Evaluation plan (paper §5)

1. **Citation-validator P/R (automatic):** corrupt real bibliographies with known fabrications /
   wrong DOIs / author swaps → precision/recall table.
2. **Novelty vs OpenReview (automatic):** ~25 ICLR papers with public reviews; correlate verdicts
   + bands against reviewer novelty opinions.
3. **Case studies:** 2 worked examples from demo prep.
4. **User study (only if tier 1 lands by day 8):** 3–5 researchers, usefulness ratings + comments.

## 8. Testing

Same discipline as `refcheck` (46 tests, TDD): bus/orchestrator/confidence/dedup pure and
exhaustively tested; every LLM-touching agent tested with mocked clients (pattern:
`tests/test_extract.py`, `tests/test_chat_and_viz.py`); one end-to-end run with all LLMs mocked
asserting the full event log + report. Full suite (currently 112) stays green.

## 9. Schedule (11 days)

| Days | Work |
|---|---|
| 1–2 | Runtime (events/bus/base/orchestrator) + Ingest/Citation/PriorArt agents |
| 3–5 | NoveltyAgent (from spec), ConfidenceAgent + bands, BenchmarkAgent |
| 5–6 | RebuttalAgent, dashboard + report |
| 7 | Tier 2: ProblemStatementAgent, TrackerAgent (thin) |
| 8–9 | Evaluations; packaging; video script + recording |
| 10–11 | 6-page paper; buffer; submit |

**Cut line:** tier 2 slips → "in progress" in paper. Tier 1 depth is never sacrificed.

## 10. Reuse map (build nothing twice)

- `store.py` (`PaperMetadata`, extraction cache), `fetch.py`, `extract.py` (`get_paper_text`,
  LLM clients), `graph.py`, `chat.py` (`_bfs`, `_score_nodes`, `_render_subgraph`), `viz.py`,
  `discover.py`, `refcheck/*` (validate, retrieval, parse, matching), `prompts.py` SHA pattern,
  `cli.py` subparser pattern.
