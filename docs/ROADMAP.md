# Roadmap — papergraph → Universal Research Evaluator

Phased plan derived from `RESEARCH_EVALUATOR_PLAN.md` (evidence), `COMPETITOR_ARCHITECTURES.md` (what to borrow/beat), and `NOVELTY_ENGINE_SPEC.md` (Tier-1 detail).

Legend: 🟢 ship first · 🟡 differentiator · 🔵 reach/moat
Status: ✅ shipped · 🟠 partial · ⬜ not started

> **Status note (v0.5.17).** Most of Phase 1–2 shipped, but under a different
> module layout than the original plan named. The plan referenced a dedicated
> `novelty/` package (`contributions.py`, `retrieval.py`, `verify.py`,
> `compare.py`); in practice the work landed as a **multi-agent pipeline** under
> `research_companion/agents/` plus supporting top-level modules. The mapping
> below records where each item actually lives so the roadmap tracks the code.

---

## Phase 1 — Novelty MVP (the wedge)
*Goal: a researcher gets a cited, evidence-verified novelty assessment + a clean bibliography check.*

- ✅ 🟢 **#1 Reference validator** — validates the paper's bibliography against CrossRef/OpenAlex/S2/arXiv/DBLP; flags suspect/unverified refs. LLM-free. → `research_companion/refcheck/` (`parse.py`, `retrieval.py`, `matching.py`, `validate.py`); CLI `research-companion refcheck`.
- ✅ 🟢 **#2 Contribution extraction** — extracts contribution/problem claims + evidence. → `research_companion/agents/problem.py` (`ProblemStatementAgent`) + `research_companion/extract.py`.
- ✅ 🟢 **#3 Multi-source prior-art retrieval** — OpenAlex/arXiv/CrossRef/DBLP + canonical-ID dedup + temporal filter. → `research_companion/agents/priorart.py` + `research_companion/refcheck/retrieval.py`.
- ✅ 🟢 **#4 Evidence verifier** — anchor/exact→normalized→fuzzy quote match vs fulltext; unverified quotes demoted. → `research_companion/rebuttal/verify.py` (`verify_quote`, `locate_quote`).
- ✅ 🟡 **#5 Contribution-level comparison** — claim × prior art / papergraph neighborhood; polarity-typed matches. → `research_companion/agents/novelty.py` (`NoveltyAgent`) + `research_companion/compare.py`.
- ✅ 🟡 **#6 Novelty report + graph view + CLI** — aggregated verdicts, interactive graph, CLI. → `research_companion/report.py`, `research_companion/viz.py`, CLI `review` / `compare`; lab dashboard.

## Phase 2 — Reviewer critique + venue fit
- ⬜ 🟡 **#7 Scope/venue-fit checker** — match contributions+abstract against target venue scope & recent accepted papers (KG retrieval). *Targets the #1–2 desk-rejection cause.* **Not started** — no venue/scope model exists yet. Highest-value remaining Phase 2 item.
- ✅ 🟡 **#8 Reviewer-style critique engine** — multi-agent pass (methodology/rationale/discussion/fatal-flaw) with confidence scoring. → `research_companion/agents/orchestrator.py` coordinating `novelty` / `priorart` / `citation` / `problem` / `confidence` agents; CLI `review`.
- 🟠 🟡 **#9 Severity-ranked actionable report** — **partial.** Per-claim confidence + uncertainty bands ship (`research_companion/agents/confidence.py`, `score_claim`; Confidence column in `report.py`), but issues are **not yet ranked by severity/criticality** so authors can fix what matters first. Remaining: an explicit severity classifier over findings.
- ✅ 🟡 **#10 Framing/structure advisor** — IMRaD section parse + section-by-section guidance. → `research_companion/sections.py` + `research_companion/alignment.py`; CLI `align`.

## Phase 3 — Universal reach + integrity
- ⬜ 🔵 **#11 Cross-discipline venue knowledge base** — encode venue requirements beyond CS/biomed. Hardest, least-solved; needs its own design pass. **Not started** (blocks #7 beyond CS).
- ⬜ 🔵 **#12 Reproducibility / data-availability checker** — data/code links, methods completeness; EQUATOR/PRISMA/CONSORT where applicable. **Not started.**
- ⬜ 🔵 **#13 Plagiarism / ethics-declaration checks** — round out the 10-reason rejection taxonomy. **Not started.**
- ✅ 🔵 **#14 Accuracy benchmark** — labeled validation harness measuring verdict quality vs reviewers. → `research_companion/eval/` (`novelty_openreview.py`, `citation_pr.py`, `pvalue.py`) + `research_companion/agents/benchmark.py`; results in `eval/results/`.

---

## What's genuinely open

The wedge (Phase 1) and most of the reviewer pipeline (Phase 2) are shipped. The
remaining, independently-shippable work:

1. **#7 Scope/venue-fit checker** (🟡, biggest lever) — targets the top desk-rejection cause.
2. **#9 Severity ranking** (🟠, finish the partial) — layer a criticality classifier over existing findings.
3. **#11 Cross-discipline venue KB** (🔵) — design pass first; unblocks #7 outside CS/biomed.
4. **#12 Reproducibility checker** (🔵).
5. **#13 Plagiarism / ethics checks** (🔵).

### Importable issues (remaining only)

To create these as GitHub issues, point at the repo you own (`gh repo set-default`) and run:

```bash
gh issue create --title "Scope/venue-fit checker" --label "phase-2,tier-1" \
  --body "Match contributions+abstract against target venue scope & recent accepted papers. Targets #1-2 desk-rejection cause. Build on agents/priorart.py retrieval + KG neighborhood."
gh issue create --title "Severity-ranked actionable report" --label "phase-2,tier-2" \
  --body "Classify findings by severity/criticality on top of the existing confidence scores (agents/confidence.py) so authors fix what matters first. OpenJudge Criticality-Verification pattern."
gh issue create --title "Cross-discipline venue knowledge base" --label "phase-3,tier-3,research" \
  --body "Encode venue requirements beyond CS/biomed. Hardest gap; needs a design pass. Unblocks the venue-fit checker outside CS."
gh issue create --title "Reproducibility / data-availability checker" --label "phase-3,tier-3" \
  --body "Data/code links, methods completeness, EQUATOR/PRISMA/CONSORT where applicable."
gh issue create --title "Plagiarism / ethics-declaration checks" --label "phase-3,tier-3" \
  --body "Round out the 10-reason rejection taxonomy."
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
