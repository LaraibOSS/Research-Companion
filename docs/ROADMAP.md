# Roadmap — papergraph → Universal Research Evaluator

Phased plan grounded in `RESEARCH_EVALUATOR_PLAN.md` (evidence) and `COMPETITOR_ARCHITECTURES.md` (what to borrow/beat).

Legend: 🟢 ship first · 🟡 differentiator · 🔵 reach/moat
Status: ✅ shipped · 🟠 partial · ⬜ not started

> **Status note.** Phase 1 and Phase 2 are complete; Phase 3 is mostly complete
> (only the plagiarism half of #13 remains). The work landed as a
> **multi-agent pipeline** under `research_companion/agents/` plus supporting
> top-level modules, not the dedicated `novelty/` package the original plan
> named. The mapping below records where each item actually lives so the roadmap
> tracks the code.

---

## Phase 1 — Novelty MVP (the wedge)
*Goal: a researcher gets a cited, evidence-verified novelty assessment + a clean bibliography check.*

- ✅ 🟢 **#1 Reference validator** — validates the paper's bibliography against CrossRef/OpenAlex/S2/arXiv/DBLP; flags suspect/unverified refs. LLM-free. → `research_companion/refcheck/` (`parse.py`, `retrieval.py`, `matching.py`, `validate.py`); CLI `research-companion refcheck`.
- ✅ 🟢 **#2 Contribution extraction** — extracts contribution/problem claims + evidence. → `research_companion/agents/problem.py` (`ProblemStatementAgent`) + `research_companion/extract.py`.
- ✅ 🟢 **#3 Multi-source prior-art retrieval** — OpenAlex/arXiv/CrossRef/DBLP + canonical-ID dedup + temporal filter. → `research_companion/agents/priorart.py` + `research_companion/refcheck/retrieval.py`.
- ✅ 🟢 **#4 Evidence verifier** — anchor/exact→normalized→fuzzy quote match vs fulltext; unverified quotes demoted. → `research_companion/rebuttal/verify.py` (`verify_quote`, `locate_quote`).
- ✅ 🟡 **#5 Contribution-level comparison** — claim × prior art / papergraph neighborhood; polarity-typed matches. → `research_companion/agents/novelty.py` (`NoveltyAgent`) + `research_companion/compare.py`.
- ✅ 🟡 **#6 Novelty report + graph view + CLI** — aggregated verdicts, interactive graph, CLI. → `research_companion/report.py`, `research_companion/viz.py`, CLI `review` / `compare`; lab dashboard.

## Phase 2 — Reviewer critique + venue fit — COMPLETE
- ✅ 🟡 **#7 Scope/venue-fit checker** — matches contributions+abstract against a venue's scope with a deterministic topic-overlap prefilter grounding an LLM fit verdict (strong/moderate/weak/out_of_scope + desk-reject risk). → `research_companion/venues.py` (CS/ML registry + `topic_overlap`) + `research_companion/agents/venuefit.py` (`VenueFitAgent`, `normalize_verdict`); CLI `review --venue <slug>`. Cross-discipline coverage tracked as #11.
- ✅ 🟡 **#8 Reviewer-style critique engine** — multi-agent pass (methodology/rationale/discussion/fatal-flaw) with confidence scoring. → `research_companion/agents/orchestrator.py` coordinating `novelty` / `priorart` / `citation` / `problem` / `confidence` agents; CLI `review`.
- ✅ 🟡 **#9 Severity-ranked actionable report** — findings are now classified into critical/major/minor and ranked worst-first (OpenJudge Criticality-Verification pattern) on top of the existing confidence scores. → `research_companion/agents/severity.py` (`rank_findings`, `SeverityAgent`); rendered at the top of `report.py`.
- ✅ 🟡 **#10 Framing/structure advisor** — IMRaD section parse + section-by-section guidance. → `research_companion/sections.py` + `research_companion/alignment.py`; CLI `align`.

## Phase 3 — Universal reach + integrity
- ✅ 🔵 **#11 Cross-discipline venue knowledge base** — data-driven KB (`research_companion/data/venues.json`, 19 venues across 9 disciplines: ML, NLP, vision, data-mining/IR, biomedical, physics, psychology, economics, general) with per-venue scope, reporting checklists, and desk-reject rules; loaded by `venues.py` with a discipline model (`infer_discipline`, `suggest_alternatives`, `venues_for_discipline`). Feeds the venue-fit checker (#7) beyond CS/biomed and grounds its verdicts in real venue requirements. Extending it needs no code change — see `docs/VENUE_KB.md`.
- ✅ 🔵 **#12 Reproducibility / data-availability checker** — deterministic scan for public code/data links, availability statements, methods-completeness signals, and EQUATOR/PRISMA/CONSORT-family checklists → high/medium/low level + gaps. → `research_companion/reproducibility.py` + `research_companion/agents/reproducibility.py` (`ReproducibilityAgent`); rendered in `report.py`.
- 🟠 🔵 **#13 Plagiarism / ethics-declaration checks** — **partial.** Integrity-declaration detection ships (funding, conflict-of-interest, author contributions, ethics/IRB approval, informed consent). → `research_companion/ethics.py` + `research_companion/agents/ethics.py` (`EthicsAgent`); rendered in `report.py`. **Deferred:** true plagiarism/near-duplicate detection, which needs an external similarity corpus/service.
- ✅ 🔵 **#14 Accuracy benchmark** — labeled validation harness measuring verdict quality vs reviewers. → `research_companion/eval/` (`novelty_openreview.py`, `citation_pr.py`, `pvalue.py`) + `research_companion/agents/benchmark.py`; results in `eval/results/`.

---

## What's genuinely open

Phase 1, **all of Phase 2**, and **most of Phase 3** are shipped. The only
remaining item:

1. **#13 Plagiarism / near-duplicate detection** (🔵, finish the partial) — the declaration side ships (`ethics.py`); true plagiarism needs an external similarity corpus/service. Design the integration boundary and privacy model before building.

Ongoing (no code, data authoring): grow the venue KB (`docs/VENUE_KB.md`) with
more venues/disciplines as needed — this is expected maintenance, not a blocking
roadmap item.

### Importable issues (remaining only)

To create these as GitHub issues, point at the repo you own (`gh repo set-default`) and run:

```bash
gh issue create --title "Plagiarism / near-duplicate detection" --label "phase-3,tier-3,research" \
  --body "Declaration detection ships (ethics.py). Add true plagiarism/near-duplicate detection via an external similarity corpus/service; design the integration boundary and privacy model first."
```

## Known issues carried past v0.3.0 — RESOLVED

All three carried-forward issues were fixed in the roadmap-known-issues pass:

- ✅ **settings.embed_model is persisted but not consumed** — now wired through
  `qa`/`converse` ranking and the embedding backfill (arg → settings →
  `DEFAULT_EMBED_MODEL`); the "needs backfill" check is model-aware, so switching
  models re-embeds rather than silently falling back to BM25.
- ✅ **Gap-relevance threshold meant different things in BM25 vs hybrid mode** —
  `gaps._relevance_score()` now normalizes the prefilter score to a
  mode-independent `[0, 1]` (hybrid passes through; raw BM25 saturates via
  `s/(s+1)`), so `sim_threshold` has consistent meaning with or without an HF token.
- ✅ **publish.yml re-runs hard-fail on existing PyPI files** — `twine upload`
  now uses `--skip-existing`, making re-runs of a successful publish idempotent.
