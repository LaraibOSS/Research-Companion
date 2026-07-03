# Building a Universal Pre-Submission Research Evaluator
### Evidence-based feature plan & roadmap

> Synthesized from a deep-research pass (5 angles · 26 sources · 127 claims extracted · 25 adversarially verified, 23 confirmed). Every load-bearing claim below is cited. Two claims were refuted and excluded (see end).

---

## 1. Is the problem real? (Yes — and it's large)

The whole premise of the tool rests on one question: *do enough papers fail for reasons a pre-submission tool could catch?* The evidence says yes, decisively.

| Finding | Evidence | Confidence |
|---|---|---|
| **Lack of novelty is the #1 desk-rejection cause** | Menon et al. 2022 (Indian J. Psych. Medicine), 627 desk rejections: novelty/originality = 46.3% overall, 51.8% of desk rejections. Corroborated across fields: hospitality 60.3%, paediatrics 54.5%, accounting/finance ~80%. | High (3-0) |
| **A huge share never reaches reviewers** | *Parasites & Vectors* desk-rejects 39% pre-review; *JAMA Internal Medicine* rejected 78% without review (2017). | High (3-0) |
| **Rejections cluster into a discrete, checkable taxonomy** | 10 pre-review reasons: out of scope, local-interest-only, no novelty, weak design, incomplete methods/reporting, data-availability, ethics, poor presentation, poor English, plagiarism. Post-review leaders: methodology 50.7%, weak writing 45.2%, poor discussion 30.4%, weak rationale 28.1%, fatal design flaws 25.8%. | High (3-0 / 2-1) |
| **Scope/venue mismatch is a top trigger** | Out-of-scope = 17.4% of desk rejections (IJPM); 35% — the single largest category — in *Transportation Research Part D* (2023). | High (3-0) |
| **Reproducibility failure is cross-disciplinary** | Baker 2016 (Nature, n=1,576): >70% failed to reproduce others' work, >50% their own; a majority in *every* field (chemistry 87%, biology 77%, physics/eng 69%, medicine 67%). | High (2-1) |

**Takeaway:** The failure modes are finite, well-documented, and span disciplines. That is exactly the surface a hybrid tool can target.

---

## 2. The competitive gap (what to beat)

The market splits cleanly into two camps that **nobody has unified**:

### Camp A — Deterministic compliance checkers (strong, but no scientific judgment)
- **Paperpal Manuscript Check** — 30+ language/technical compliance checks (ethics declarations, formatting, metadata, tables/figures, citations); reference suggestions from 250M+ articles, 10,000+ citation styles. **But:** independent review (Manusights 2026) confirms it *"does not assess novelty against competing literature"* and gives *"writing-quality feedback,"* not *"editor-and-peer-reviewer-grade scientific critique."* (3-0)
- **Penelope.ai** — 30+ configurable compliance checks (Ethics, Formatting/Structure, References, Title-page, EQUATOR/PRISMA/CONSORT reporting checklists). Its own `/checks` page states checks focus on *"formatting, structure, compliance... rather than scientific merit. There are no checks for novelty, scientific contribution, or content quality critique."* (3-0)
- **ACL Pubcheck** (OSS) — deterministic LaTeX/PDF linting against ACL `.sty`: fonts, margins, author formatting, page limits, malformed citations. The canonical open-source venue-linter pattern.

### Camp B — Novelty/critique research systems (smart, but single-purpose & CS-only)
- **OpenNovelty** (arXiv 2601.01576, Jan 2026) — LLM agentic novelty assessment: extract contribution claims → retrieve prior work → contribution-level comparison → cited report. *"Grounds all assessments in retrieved real papers, ensuring verifiable judgments."* Deployed on 500+ ICLR 2026 submissions. (3-0)
- **GraphMind** (EMNLP 2025 demo, arXiv 2510.15706) — open-source, hybrid LLM + retrieval + **knowledge-graph view**; integrates arXiv + Semantic Scholar; links a paper's contributions to prior work for novelty assessment. **The closest existing analog to a papergraph-powered tool — and a direct competitor.** (3-0)
- **AgentReview** (EMNLP 2024) — first LLM peer-review *simulation*: 5 phases (review, rebuttal, reviewer-AC discussion, meta-review, decision), 3 agent roles, 53,800+ generated reviews. Blueprint for the reviewer-critique engine. (3-0)
- **OpenJudge** (AgentScope, Jan 2026) — 5-stage pipeline: Safety → Correctness → Scholarly Review → Criticality Verification → **Bibliography Validation against CrossRef**. A genuine hybrid (LLM + deterministic API lookups). (3-0)
- **RefChecker** (Russinovich, MIT) — citation validation against Semantic Scholar, OpenAlex, CrossRef, DBLP, ACL Anthology; 3-stage hybrid: deterministic pre-filters (author-overlap <60%, identifier conflicts, broken URLs) → LLM web search → reverification. (3-0)

> ### The gap, in one line
> **Camp A does compliance but not science; Camp B does novelty/critique but isn't integrated with venue-compliance linting, and is almost entirely CS/AI-only.** The winning tool unifies all three (novelty + venue-bar fit + framing guidance) with *verifiable, citation-grounded* output — and does it for *every* discipline. The papergraph knowledge-graph foundation is the natural substrate for the novelty/prior-art layer.

---

## 3. Proposed architecture (hybrid, validated by the field)

The hybrid design isn't speculative — every layer below already exists in a shipping system. The contribution is **unifying them** on a knowledge-graph spine.

```
                      ┌─────────────────────────────────────────────┐
                      │            PAPER INGEST (any discipline)      │
                      │  PDF/LaTeX/docx → sections, claims, refs, KG  │  ← papergraph foundation
                      └───────────────┬─────────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
┌───────────────────┐      ┌───────────────────────┐     ┌────────────────────────┐
│ DETERMINISTIC      │      │ LLM REASONING          │     │ KNOWLEDGE-GRAPH /        │
│ LINTERS (rules)    │      │ (agentic, multi-stage) │     │ RAG NOVELTY ENGINE       │
│                    │      │                        │     │                          │
│ • venue formatting │      │ • reviewer-style       │     │ • extract contribution   │
│   (ACL-pubcheck    │      │   critique (AgentReview│     │   claims                 │
│   pattern)         │      │   5-phase pattern)     │     │ • retrieve prior art     │
│ • reference        │      │ • methodology &        │     │   (S2/OpenAlex/arXiv/    │
│   validation       │      │   rationale critique   │     │   CrossRef/DBLP)         │
│   (RefChecker:     │      │ • framing/structure    │     │ • contribution-level     │
│   S2/OpenAlex/     │      │   suggestions          │     │   comparison → graph     │
│   CrossRef/DBLP)   │      │ • venue/scope fit      │     │ • cited novelty report   │
│ • reporting        │      │   judgment             │     │   (OpenNovelty/GraphMind │
│   checklists       │      │                        │     │   pattern)               │
│   (EQUATOR/PRISMA/ │      │                        │     │                          │
│   CONSORT)         │      │                        │     │                          │
└─────────┬──────────┘      └───────────┬────────────┘     └───────────┬──────────────┘
          └───────────────────────────────┼───────────────────────────┘
                                           ▼
                          ┌────────────────────────────────┐
                          │ VERIFICATION & SCORING LAYER     │
                          │ • every claim → evidence chain   │
                          │ • severity classification        │
                          │ • adversarial self-check         │
                          │   (counter leniency bias)        │
                          └────────────────┬─────────────────┘
                                           ▼
                          ┌────────────────────────────────┐
                          │ SUBMISSION-READINESS REPORT      │
                          │ novelty score + venue-fit + gaps │
                          │ + framing fixes, all cited       │
                          └────────────────────────────────┘
```

**Two design rules the research makes non-negotiable:**

1. **Everything must be verifiable / citation-grounded.** OpenNovelty's whole differentiator is grounding in retrieved real papers so humans can validate, not trust a black box. A score with no evidence chain is a liability, not a feature.
2. **Counter LLM leniency bias.** Fetched evidence (arXiv 2501.10326) warns LLM reviewers tend to accept author claims uncritically, treat strengths as summarization, and miss deep flaws. Deterministic checks + adversarial verification must backstop the LLM — never ship raw LLM critique as ground truth.

---

## 4. Feature set, prioritized

### Tier 0 — Foundation (you already have most of this)
- **KG ingestion** of paper → contributions, claims, references, entities. *papergraph already builds cross-paper concept graphs with typed citation edges — this is your moat.*
- Retrieval connectors: **Semantic Scholar, OpenAlex, arXiv, CrossRef, DBLP, ACL Anthology** (all proven in RefChecker/GraphMind).

### Tier 1 — MVP (highest evidence-to-effort ratio)
1. **Deterministic reference validator** — RefChecker pattern: flag unverified refs, <60% author overlap, identifier conflicts, broken URLs, retracted citations. *Pure win, no LLM risk.*
2. **Venue/scope-fit checker** — match abstract+contributions against the target venue's scope & recent accepted papers (KG retrieval). Targets the #1–#2 desk-rejection cause.
3. **Novelty assessment (graph+RAG)** — OpenNovelty/GraphMind pattern on the papergraph spine: extract claims → retrieve prior art → contribution-level comparison → **cited** novelty report with a graph view of "what's new vs. what exists."
4. **Reporting-checklist linter** — EQUATOR/PRISMA/CONSORT for applicable fields; ACL/IEEE/venue formatting for CS. (Penelope/Paperpal/ACL-pubcheck patterns.)

### Tier 2 — Differentiators
5. **Reviewer-style critique engine** — AgentReview 5-phase multi-agent simulation: methodology, rationale, discussion, fatal-flaw detection (the exact post-review rejection leaders). With adversarial self-check to fight leniency bias.
6. **Framing/structure advisor** — section-by-section guidance ("your contribution claim isn't supported by §4"), targeting weak-writing (45%) and weak-rationale (28%) rejections.
7. **Severity-ranked, actionable report** — OpenJudge's Criticality Verification pattern: classify each issue by severity so authors fix what matters first.

### Tier 3 — Reach & moat
8. **Cross-discipline venue knowledge base** — the hardest, least-solved piece (see gaps). Encode venue requirements beyond CS/biomed.
9. **Reproducibility/data-availability checker** — targets the 60–80% reproducibility crisis; check for data/code links, methods completeness.
10. **Plagiarism/integrity & ethics-declaration checks** — round out the 10-reason taxonomy.

---

## 5. Honest gaps & open questions (from the research itself)

- **Pricing was not captured for any competitor** — the competitive teardown's pricing dimension is an open data gap. Validate before positioning on price. (Only incidental ref: Manusights $39.)
- **Discipline skew:** nearly all validated novelty/critique tools (OpenNovelty, GraphMind, AgentReview, OpenJudge) are **CS/AI-only** (ICLR/ACL/EMNLP). Empirical rejection data skews biomedical. **Direct evidence for humanities & non-CS STEM venue requirements is thin** — the "universal" ambition is where you'll innovate *and* where the data is weakest. Treat non-CS venue encoding as genuine R&D, not a config file.
- **Unvalidated accuracy:** no measured false-positive/false-negative rates for the LLM novelty assessors vs. human reviewers. You'll need your own benchmark + human validation set.
- **Vendor self-reports:** Paperpal's "30+ checks / 250M articles / 10,000 styles" and Penelope's "30+ checks" are marketing figures, not independently audited.

### Two claims that were REFUTED (do not build on these)
- ✗ *"69.8% of rejections happen at desk stage within a 3-day median"* (1-2) — not supported.
- ✗ *"OpenJudge has no venue/discipline tailoring"* (0-3) — refuted; it does adapt.

---

## 6. Recommended next step

Build **Tier 1 item #3 (graph+RAG novelty assessment)** first as a thin vertical slice on top of papergraph — it's your strongest differentiator, directly leverages what you already have, and GraphMind proves the exact pattern works as an open-source web tool. Wrap it with the deterministic reference validator (#1, zero LLM risk) to immediately deliver verifiable value.

---

*Sources (primary): Menon et al. 2022 · Dantas-Torres 2022 (Parasites & Vectors) · JAMA Intern. Med. 2017 · Baker 2016 (Nature) · Transportation Research Part D 2023 · Paperpal · Penelope.ai · OpenNovelty (arXiv 2601.01576) · GraphMind (arXiv 2510.15706, EMNLP 2025) · AgentReview (arXiv 2406.12708, EMNLP 2024) · OpenJudge (AgentScope) · RefChecker · ACL Pubcheck.*
