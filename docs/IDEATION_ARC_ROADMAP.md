# Research Companion — Ideation Arc: Decisions, Options & Enhancements

**Purpose:** A record of what shipped in the Phase-2 ideation arc, the design forks where more than one option existed (and which I chose and why), what's deliberately **not** built yet, and a prioritized menu of enhancements for the next "everything" version — for you to review, test, and pick from.

**Status:** the entire arc (2a → 2e) is built, reviewed, and merged into `main` (`LaraibOSS/Research-Companion`). Every slice held the standing guardrails: **no new dependencies**, honesty/citation-required, never-500 endpoints, full test gate + per-task + whole-branch review, commits as `Laraib Hasan` with no AI trailer.

---

## 1. What shipped (all merged)

| Slice | Feature | PR | The idea in one line |
|---|---|---|---|
| 2a | Topic discovery | #51 | Type a topic → find real papers (S2/OpenAlex), optionally AI-expand the query, add to your library. |
| 2b | Research Directions | #52 | Grounded, ranked "directions you could pursue," cited to your library + concept graph + gaps. |
| 2c | Novelty Gate | #53 | Per-direction "has anyone done this?" → verdict + the real closest prior works. |
| 2d | Draft this direction | #54 | Scaffold a chosen direction into a real draft outline that enters today's draft pipeline. |
| 2e-1 | Deep-Research Report | #55 | Topic → grounded sub-questions → per-question **cited** synthesis (reusing `qa.answer`) as a background job. |
| 2e-2 | RCS evidence scoring | #56 | Score each cited chunk for relevance + supports/contradicts, as honest model-judgment badges. |
| 2e-3 | Coverage / saturation % | #57 | How much of the relevant library each answer actually draws on (LLM-free, always-on). |
| 2e-4 | Editable research plan | #58 | Review/edit/add/remove/reorder the questions before the (expensive) answering pass. |
| 2e-5 | Report export | #59 | One-click Download (.md), carrying the same honesty caveats as the UI. |

The Brainstorm tab is the front door of the arc; the Report tab is its deliverable.

---

## 2. Key design decisions (the forks — options weighed → what I chose)

Each of these had a real alternative. I picked the option I'd defend; the alternatives are here so you can overrule any of them for the "everything" version.

1. **Brainstorm as its own tab vs. a mode inside "Add papers".** → **Dedicated tab.** The ideation arc grows many sections (directions, novelty, draft, report); a modal inside Add-papers would need relocating almost immediately. (You explicitly steered this one.)
2. **Directions grounding: library-only / discovery-only / both.** → **Both** (library concepts+graph+gaps ∪ the 2a discovery results). Works for a brand-new brainstormer (cold) *and* a returning corpus-holder (warm), degrading gracefully.
3. **Novelty gate: reuse the whole-paper `NoveltyAgent` pipeline vs. a small synchronous per-direction function.** → **Small function reusing just `COMPARISON_PROMPT` + `search_topic_with_fallback`.** The Agent is `ctx`-shaped and CLI-wired; a synchronous function matched 2a/2b and added no machinery.
4. **Report: synchronous vs. background job.** → **202 background job + SSE** (a report is many LLM calls) — while 2a–2d stayed synchronous (one call each). Modeled on the existing gaps-refresh job.
5. **RCS scoring: fold into report generation (always) vs. a separate opt-in pass.** → **Opt-in `POST /api/report/score-evidence`** — it costs one LLM call per section, so regenerating a report stays cheap and scoring is a deliberate, separately-costed action.
6. **Coverage: opt-in vs. always-on.** → **Always-on, folded into the report job** — because it's **LLM-free** (pure BM25 retrieval math), gating it behind a click would add friction for no cost saving.
7. **Coverage metric: "% of the whole library used" (a vanity number) vs. relative to the search's own relevance set.** → **Relative to the search's relevance set** (threshold 0.35, the same gate `gaps`/`directions` use). The vanity number conflates irrelevant papers with missed evidence — dishonest. Shown with raw `cited/relevant_available` counts so it's auditable.
8. **Editable plan: split `refresh(topic)` into plan-only (smaller diff) vs. keep the one-shot and add a new plan endpoint + additive `questions` field.** → **Backward-compatible: new `POST /api/report/plan` + optional `questions` on refresh.** The one-shot "generate + answer" path stays byte-identical (no 2e-1/2/3 regressions); the plan step is purely additive.
9. **Export: markdown-only vs. markdown + self-contained HTML.** → **Markdown-only.** `report.py`'s HTML renderer is hard-wired to the paper-*review* lane shape (zero reuse for the report), so HTML would be a whole new renderer for marginal benefit over a `.md` a researcher can open/paste anywhere.
10. **Honesty framing everywhere.** → Every AI judgment (novelty verdict, RCS relevance/stance, coverage %) is **labeled a model/heuristic judgment via `tip()` tooltips and captions, never "verified"**, and the export carries those same caveats — so a shared artifact is never more "verified" than the app. RCS badges are deliberately visually distinct from the code-verified green "✓ verified" badge.

---

## 3. Deliberately not built yet (deferred) — with a recommendation

1. **A/B landing entry on Home (Brainstorm-from-an-idea vs. I-have-a-draft).** *The one piece of the original Phase-2 vision I did not build autonomously* — it reworks the **Home surface**, which you've been particular about visually, and you said you want to "test first" before the everything-version. **Recommended as the next slice, but with your design eye.** Options for how:
   - **(a) A first-run-only chooser** — the two entry cards appear only when there's no research/draft yet; once you're working, Home is the normal dashboard. *(My pick — lowest disruption to the dashboard you already liked, and it's exactly where a new user needs the fork.)*
   - **(b) A permanent two-card hero** on Home above the dashboard.
   - **(c) A lightweight banner/CTA** linking to Brainstorm vs. the draft upload, no layout change.
2. **Self-contained HTML export of the report** — a nicer shareable artifact than `.md`; needs a new small renderer. Low priority (markdown covers the need).
3. **External-search-fed report** — today's report synthesizes over **your library** (honest, dependency-free). Broadening it to ingest discovered/searched papers into the corpus before synthesis is a meatier, separate capability.

---

## 4. Enhancements for the "everything" version (prioritized menu)

Pick any subset; a few carry real trade-offs (flagged with options).

**High value, low risk**
- **Guided ideation flow** — a soft wizard that threads discovery → directions → novelty → draft/report so a new user is led through the arc instead of finding each tab. (No new deps; pure UI orchestration.)
- **Fix the flaky CI test** — `test_simplify_falls_back_to_raw_text_without_sections` intermittently fails across Python versions (a JSON-parse hiccup in the simplify job). Harden it so CI is deterministic. (Small, worth doing.)
- **Persist RCS/coverage/novelty across re-runs** — today re-running a report clears prior RCS scores (documented). A per-question/citation cache keyed on content SHAs would avoid recompute. (Mirrors the gaps-synthesis cache; no new deps.)

**High value, a real trade-off (options)**
- **Semantic retrieval on by default** (better directions/novelty/coverage/report grounding). Today retrieval is BM25 with optional embeddings.
  - **(a)** Ship local `sentence-transformers` as an **opt-in** feature (already an optional extra) — best quality, but it's a heavy optional dependency to install. *(My pick for the everything-version: opt-in, off by default, so the no-deps core is untouched.)*
  - **(b)** Stay BM25-only (zero deps, current behavior).
  - **(c)** A tiny local TF-IDF/embedding shim (no big dep) — middle ground, more code to own.
- **Novelty/directions caching** — avoid re-hitting S2/OpenAlex + the LLM on repeat checks. **(a)** in-memory per-session (simplest), **(b)** disk cache keyed on topic+corpus SHA (survives restarts). *(My pick: (a) first — matches the ephemeral design; add (b) only if repeat-cost becomes real.)*

**Nice-to-have**
- **Plan-time library staleness hint** — flag when the library changed since a draft plan was made (answers are already grounded in the *current* library, so this is a soft cue, not a correctness fix).
- **HTML/PDF report export** (see §3.2).
- **Coverage "no relevant material" caption variant in the export** (the UI has a 0-denominator variant the `.md` doesn't mirror — cosmetic).

**Operational (your own actions, from the pre-public checklist)**
- Rotate the two `.env` keys and revoke `PYPI_API_TOKEN` before flipping the repo public — tracked separately, needs you.

---

## 5. Suggested sequence for the everything-version
1. **A/B landing** (§3.1, option a) — with your Home-design input.
2. **Guided ideation flow** (§4) — ties the arc together.
3. **Semantic retrieval opt-in** (§4) — the biggest quality lever; opt-in keeps the core dep-free.
4. Persistence/caching (§4) — polish once the flows are settled.
5. Fix the flaky test (§4) whenever convenient.

Everything above is a proposal — tell me which to keep, drop, or reprioritize after you've tested the shipped arc.
