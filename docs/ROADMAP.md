# Roadmap — papergraph → Universal Research Evaluator

Phased plan derived from `RESEARCH_EVALUATOR_PLAN.md` (evidence), `COMPETITOR_ARCHITECTURES.md` (what to borrow/beat), and `NOVELTY_ENGINE_SPEC.md` (Tier-1 detail).

Legend: 🟢 ship first · 🟡 differentiator · 🔵 reach/moat

---

## Phase 1 — Novelty MVP (the wedge)
*Goal: a researcher runs `papergraph novelty <paper>` and gets a cited, evidence-verified novelty assessment + a clean bibliography check.*

- 🟢 **#1 Reference validator** (`refcheck/`) — validate the paper's own bibliography against CrossRef/OpenAlex/S2/arXiv/DBLP; flag suspect/unverified refs. LLM-free, ship first.
- 🟢 **#2 Contribution extraction** (`novelty/contributions.py`) — extract `ContributionClaim`s + per-claim prior-work queries; new SHA-cached prompt.
- 🟢 **#3 Multi-source prior-art retrieval** (`novelty/retrieval.py`) — OpenAlex/arXiv/CrossRef/DBLP behind one interface + canonical-ID dedup + temporal filter.
- 🟢 **#4 Evidence verifier** (`novelty/verify.py`) — anchor-match every quote vs fulltext; demote unverified. *Gate before report.*
- 🟡 **#5 Contribution-level comparison** (`novelty/compare.py`) — claim × {prior art, papergraph neighborhood}; polarity-typed matches; two-stage retrieve-then-LLM.
- 🟡 **#6 Novelty report + graph view + CLI** — aggregate verdicts, interactive graph via `viz.py`, `papergraph novelty` command.

## Phase 2 — Reviewer critique + venue fit
- 🟡 **#7 Scope/venue-fit checker** — match contributions+abstract against target venue scope & recent accepted papers (KG retrieval). *Targets the #1–2 desk-rejection cause.*
- 🟡 **#8 Reviewer-style critique engine** — AgentReview 5-phase multi-agent pass: methodology, rationale, discussion, fatal-flaw detection, with adversarial self-check to counter LLM leniency.
- 🟡 **#9 Severity-ranked actionable report** — OpenJudge Criticality-Verification pattern: rank issues so authors fix what matters first.
- 🟡 **#10 Framing/structure advisor** — IMRaD section parse (GraphMind pattern) + section-by-section guidance.

## Phase 3 — Universal reach + integrity
- 🔵 **#11 Cross-discipline venue knowledge base** — encode venue requirements beyond CS/biomed (hardest, least-solved; needs its own design pass).
- 🔵 **#12 Reproducibility / data-availability checker** — data/code links, methods completeness; reporting checklists (EQUATOR/PRISMA/CONSORT) where applicable.
- 🔵 **#13 Plagiarism / ethics-declaration checks** — round out the 10-reason rejection taxonomy.
- 🔵 **#14 Accuracy benchmark** — human-labeled validation set; measure novelty-verdict precision/recall vs reviewers.

---

## Importable issues

To create these as real GitHub issues, point me at the repo you own (`gh repo set-default`) and I'll run the block below. They're authored so each maps to one spec component and is independently shippable.

```bash
# Phase 1
gh issue create --title "Reference validator (deterministic, LLM-free)" \
  --label "phase-1,tier-1" \
  --body "Validate the paper's bibliography against CrossRef/OpenAlex/S2/arXiv/DBLP. Per-ref status verified/suspect/unverified with reason. Deterministic pre-filters; escalate only ambiguous refs. See docs/NOVELTY_ENGINE_SPEC.md Component 5. Tests: golden good/bad bibliographies."

gh issue create --title "Contribution-claim extraction" \
  --label "phase-1,tier-1" \
  --body "Add CONTRIBUTION_PROMPT (SHA-cached) extracting ContributionClaim{text,kind,evidence_quote,evidence_location,prior_work_query}. Reuse extract.py LLM plumbing. Spec: Component 1. Tests: golden files on examples/."

gh issue create --title "Multi-source prior-art retrieval + canonical dedup" \
  --label "phase-1,tier-1" \
  --body "PriorArtRetriever protocol; OpenAlex/arXiv/CrossRef/DBLP impls + wrap existing S2. canonical_id=md5(normalize_title); temporal year_max filter; cache raw responses. Spec: Component 2. Tests: mock APIs, deterministic dedup/temporal."

gh issue create --title "Evidence verifier (anti-hallucination gate)" \
  --label "phase-1,tier-1,quality" \
  --body "verify_quote(quote,fulltext): exact→normalized→anchor/fuzzy match + location. Unverified claims demoted, never shown as fact. Spec: Component 4. Pure-function unit tests."

gh issue create --title "Contribution-level novelty comparison" \
  --label "phase-1,tier-1" \
  --body "Compare each claim vs retrieved prior art AND papergraph neighborhood (via chat.py _bfs/_render_subgraph). Polarity-typed matches (extends/supports/contrasts/refutes/mentions). Two-stage retrieve-then-LLM. NoveltyVerdict output. Spec: Component 3."

gh issue create --title "Novelty report + graph view + CLI" \
  --label "phase-1,tier-1" \
  --body "Aggregate verdicts into cited per-claim report; interactive graph via viz.py colored by polarity; 'papergraph novelty <id> --venue <slug>'. Spec: Component 6. Integration test on one example paper."

# Phase 2
gh issue create --title "Scope/venue-fit checker" --label "phase-2,tier-1" \
  --body "Match contributions+abstract against target venue scope & recent accepted papers. Targets #1-2 desk-rejection cause."
gh issue create --title "Reviewer-style critique engine (multi-agent)" --label "phase-2,tier-2" \
  --body "AgentReview 5-phase pass with adversarial self-check vs LLM leniency. Methodology/rationale/discussion/fatal-flaw."
gh issue create --title "Severity-ranked actionable report" --label "phase-2,tier-2" \
  --body "OpenJudge Criticality-Verification: classify issues by severity."
gh issue create --title "Framing/structure advisor (IMRaD)" --label "phase-2,tier-2" \
  --body "IMRaD section classification + section-by-section framing guidance."

# Phase 3
gh issue create --title "Cross-discipline venue knowledge base" --label "phase-3,tier-3,research" \
  --body "Encode venue requirements beyond CS/biomed. Hardest gap; needs design pass."
gh issue create --title "Reproducibility / data-availability checker" --label "phase-3,tier-3" \
  --body "Data/code links, methods completeness, EQUATOR/PRISMA/CONSORT where applicable."
gh issue create --title "Plagiarism / ethics-declaration checks" --label "phase-3,tier-3" \
  --body "Round out the 10-reason rejection taxonomy."
gh issue create --title "Novelty-accuracy benchmark" --label "phase-3,tier-3,quality" \
  --body "Human-labeled validation set; measure verdict precision/recall vs human reviewers."
```
