# Academic Research Skills (ARS) — comparative analysis & adoption plan

**Target analysed:** [`Imbad0202/academic-research-skills`](https://github.com/Imbad0202/academic-research-skills) — v3.19.0, ~42.3k stars, 2,410 files, Zenodo DOI `10.5281/zenodo.20696614`, last updated 2026-08-13.
**Compared against:** this repo (Research Companion, v0.7.x, MIT).
**Written:** 2026-08-13.

---

## 0. Read this first — the licensing wall

> **ARS is licensed CC BY-NC 4.0. This repo is MIT.**
>
> Those licences are **not compatible in the direction we care about.** CC BY-NC forbids commercial use and carries attribution obligations; MIT permits commercial use. We therefore **cannot copy any ARS file, schema, prompt, rubric, or prose into this repo** — not their JSON schemas, not their protocol markdown, not their prompt text. Doing so would silently relicense our project and make it non-commercial.
>
> **What we *can* take:** ideas, architecture, and technique. Facts and methods are not copyrightable; a specific expression of them is. Every item in this plan must be **independently re-implemented from the concept**, in our own words and our own code. Where an idea traces to a public paper (Lu et al., Zhao et al., Ren et al.), we cite the paper — not ARS.
>
> Anywhere ARS's design genuinely inspired ours, credit it in prose (`docs/`) as prior art. That is courtesy and honesty, and it costs us nothing legally.

**Action:** treat this document as the *only* place ARS is quoted, and keep quotes to short descriptive paraphrase. Do not paste ARS content into source files.

---

## 1. What ARS actually is (and what it is not)

ARS is **not a competing application**. It is a suite of four **Claude Code skills** — prompt-driven protocols, plus supporting scripts — that turn a coding agent into an academic research assistant:

| Skill | Role |
|---|---|
| `deep-research` | Literature search & synthesis |
| `academic-paper` | Drafting/writing |
| `academic-paper-reviewer` | Multi-agent peer review (7 reviewer agents + EiC + synthesizer) |
| `academic-pipeline` | Stage orchestration across the four |

Its own README states the core skills are *"prompt-driven"* and need **no Python**. Python appears only for optional hardening and helper commands.

**We are a different category:** a local-first Python/FastAPI application with a persistent store, a concept knowledge graph, a browser UI, an MCP server, and deterministic analysis that runs with no API key.

**Why the comparison is still worth doing:** ARS has spent 19 minor versions solving one problem far more rigorously than we have — *how do you stop an AI research tool from lying to its user?* That is precisely the discipline this repo has been pursuing by hand all along. They have turned it into typed, testable machinery. That machinery is the prize.

---

## 2. Capability matrix

| Capability | ARS | Research Companion | Gap |
|---|---|---|---|
| Literature search | ✅ prompt-driven | ✅ S2/OpenAlex/connectors, ranked, venue-aware | — we're stronger |
| Concept knowledge graph over your own corpus | ❌ | ✅ core differentiator | — we're stronger |
| Runs with **no API key** | ⚠️ partial | ✅ deterministic core | — we're stronger |
| Browser workspace / persistent store | ❌ | ✅ | — we're stronger |
| MCP server for other agents | ❌ | ✅ 4 keyless tools | — we're stronger |
| Draft ↔ literature alignment scoring | ❌ | ✅ | — we're stronger |
| Verbatim quote verification | ✅ | ✅ `rebuttal/verify.py`, `alignment.py` | parity |
| Citation **existence** verification | ✅ multi-resolver | ✅ `refcheck/` | parity |
| **Claim-level citation audit** (does the source *support* the claim?) | ✅ opt-in `ARS_CLAIM_AUDIT` | ❌ | **major gap** |
| **Self-measured error rates** (FNR/FPR vs gold set) | ✅ calibration mode | ❌ | **major gap** |
| **Typed epistemic classes** for every signal | ✅ schema-enforced | ⚠️ prose only | **major gap** |
| **Machine-readable degradation registry** | ✅ + CI checker | ⚠️ tests only, no registry | **gap** |
| JSON-schema artifact contracts | ✅ ~dozens | ❌ | **gap** |
| Eval harness (gold / held-out / calibration) | ✅ 1,049 files | ❌ | **gap** |
| Retraction / tortured-phrase signals | ✅ | ⚠️ overlap + compliance only | gap |
| Style calibration (learn author voice) | ✅ | ❌ | opportunity |
| AI-prose detection ("writing quality check") | ✅ | ❌ | opportunity |
| Multi-agent adversarial review | ✅ 7 agents | ⚠️ single review pipeline w/ lanes | opportunity |
| Socratic planning dialogue | ✅ `/ars-plan` | ⚠️ Brief is adjacent | opportunity |
| Multi-language docs | ✅ 5 languages | ❌ | low priority |
| DOI / citable release | ✅ Zenodo | ❌ | quick win |

---

## 3. The five things genuinely worth taking

Ranked by value-to-effort **for us specifically**.

### 3.1 The epistemic-class contract — *the single biggest idea in the repo*

ARS separates three claims that must never be collapsed, and enforces it in a schema:

| Class | What it establishes |
|---|---|
| **deterministic fact** | What a named resolver returned, at a recorded time — *not* whether the work is genuine |
| **heuristic advisory** | A rule or model matched — *never a factual finding on its own* |
| **process attestation** | A check was *run* — *not the result of that check* |

And the rule that follows: **`check_status` and `finding` are independent.** "Not checked", "unknown" and "degraded" must all render as **unresolved — never as clean**. An API outage is not evidence of existence, and equally not evidence of fabrication.

**Why this matters to us more than anything else here.** We have spent this entire development cycle enforcing exactly this instinct by hand — labelling RCS scores as model judgments, captioning coverage as a BM25 heuristic, badging quotes verified/unverified, never printing "verified" for an AI verdict. **But ours is prose discipline, not machinery.** Nothing stops the next contributor (or the next me) from rendering a failed check as a clean tick. ARS made it a type.

**Where it lands:** a new `research_companion/signals.py` defining our own three-class carrier, adopted first by `refcheck/`, `citations_coverage.py`, `alignment.py`, `rcs.py`, `coverage.py`, `novelty_check.py`. Then a test that fails if any surface renders an unresolved signal as clean.

**Effort:** medium. **Value:** very high — it hardens the property we already market.

### 3.2 Claim-level citation audit (the "L3" gap)

We verify two things today: that a citation **exists** (`refcheck/`) and that a quote appears **verbatim** in the source (`verify_quote`). We never verify the thing that actually matters: **does the cited paper support the claim being made?**

**The literature is unusually direct about this being the gap that matters.** Zhao et al. (arXiv:2605.07723) audited 111M references across 2.5M papers, estimated ~146,932 hallucinated citations for 2025, and found **78.8% pass arXiv moderation** with **85.3% persisting into the published record**. Critically, they class reference-*existence* checking as *"among the easiest hallucination detection problems"* while naming the real-citation/unsupported-claim variant the *"more prevalent and harder-to-detect"* one.

**Read plainly: the check we already do is the easy one. The one we skip is the one that matters.**

#### The design detail that makes or breaks this

ARS does **not** emit a boolean "citation ok". Its finalizer uses an 8-row matrix that structurally separates **"cannot verify"** from **"verified false"**:

| Outcome | Cause | Severity |
|---|---|---|
| verified | source retrieved, claim supported | — |
| **unverifiable** | paywall / not retrievable | LOW — *never* reported as fabrication |
| **fabricated** | reference not found at all | HIGH |
| **anchorless** | no locator to check against | HIGH |
| **tool-failure** | audit itself broke | MED |

This is the same principle as §3.1 applied to one feature: **an outage is not evidence of fabrication.** If we ship a boolean, a paywalled paper becomes a false accusation against the user's own citation — the worst failure this feature could have.

#### Optimise for false-positive rate, not recall

**HALLMARK** (arXiv:2607.18360) found that for citation verification the **FPR, not recall, decides deployability**: an FPR spread of 0.050–0.702 across tools produces a ~7× precision gap at a ~2% base rate. An independent benchmark (arXiv:2607.22693) found RefChecker achieved the *lowest* false-negative rate (0 missed problematic refs) while producing **48 false positives on valid references**.

At realistic base rates, a noisy claim-auditor is worse than none: it trains the user to ignore it. **Target FPR first**, and make every uncertain verdict "unverifiable", not "unsupported".

#### Enabling mechanism: typed locator anchors

ARS attaches a typed anchor to every citation marker with a closed enum (`quote` / `page` / `section` / `paragraph` / `none`). Two payoffs: verbatim verification becomes a **mechanical substring check** rather than a semantic judgment, and **"anchorless" becomes a detectable failure class** instead of a silent gap. We already have section tilings and char ranges — we are closer to this than to anything else in this document.

#### Resolver pattern

RefChecker (arXiv:2607.00738) uses a **cascade**: deterministic multi-source match first, LLM escalation only for what survives, with consensus-of-absence before flagging. PaperOrchestra (arXiv:2604.05018) uses **verify-then-admit** — a reference cannot enter the citation pool until it resolves. Both are cheaper and more accurate than asking a model to judge every reference.

**Where it lands:** a new `research_companion/claim_audit.py`, wired into (a) the Report's per-question citations, (b) draft alignment evidence, (c) the Brief's bullets, (d) `refcheck` as an extra tier. Strictly opt-in (LLM calls + fetches), advisory-only, never an automatic block.

**Effort:** high. **Value:** very high — the most credible thing we could add, squarely in our positioning.

> ⚠️ **Verified as specified and implemented — not as effective.** The research confirmed ARS's mechanism exists in code (`claim_audit_finalizer.py`, schema, e2e tests), but found **no independent efficacy evidence** for it. Adopt the architecture; do not inherit the assumption that it works. That is what §3.3 is for.

### 3.3 Calibration mode — measure our own error rate

ARS's framing is the sharpest sentence in the repo: *our reviewer has an error profile too, and an ordinary review does not measure it.*

Verified against the primary source (Lu et al., 2026, *Nature* 651:914–919, DOI 10.1038/s41586-026-10265-5): the automated reviewer reaches **balanced accuracy 0.69 ±0.04** with a **strongly asymmetric profile — FPR 0.45 ±0.10 vs FNR 0.17 ±0.08**, measured against ICLR/OpenReview ground truth. A single aggregate score hides that asymmetry completely; two reviewers with identical accuracy can fail in opposite directions.

Two design details worth stealing outright (as concepts):
- **Gold-label isolation** — ground-truth labels must not enter the judging context; join them only after the verdict is frozen. Otherwise you measure leakage, not accuracy.
- **NOT COMPUTABLE discipline** — never print a `±X` when only a subset was annotated; report `annotated_n=n/N` and `missing=` explicitly.

**Where it lands:** `evals/` (new) + a `research-companion calibrate` CLI. Targets: readiness verdict, alignment stance, RCS relevance/stance, novelty verdict.

**Effort:** medium-high (needs a gold set — realistically user-supplied). **Value:** high — it converts "we label our AI honestly" into "we can tell you how often it is wrong."

### 3.4 Machine-readable degradation registry

We already honour a degradation contract (feature off ⇒ byte-identical) and have `test_*_degradation.py` files. ARS goes further: a **registry file** listing every degradation mechanism — what fails, the degraded state emitted, the diagnostic marker, who consumes it, the terminal-policy effect — where each row **points at its authority** (a verbatim anchor in the owning file, never a line number, so it survives drift) and lists the tests that pin it. A CI script checks the registry against reality.

Their explicit design note is worth internalising: the registry **indexes, it never re-authors** — semantics live in exactly one place so the registry cannot drift into a second source of truth.

**Where it lands:** `docs/DEGRADATION_REGISTRY.json` + `scripts/check_degradation_registry.py` in CI. Rows for: connectors off, no API key, embeddings unavailable, Docling absent, catalogue outage (429), missing PDF, no year on a paper, semantic overlap off.

**Effort:** low-medium. **Value:** high — cheap, and it directly protects our headline promise.

### 3.5 Eval harness in CI

ARS ships `evals/{gold,heldout,calibration}` and CI gates including an eval harness, spec-consistency, freshness checks, command invariants, and **test-count monotonicity** (test count may never decrease).

**Where it lands:** `evals/` with fixture corpora; extend `.github/workflows/ci.yml`. Start with the cheapest, highest-value gate: **test-count monotonicity** — one script, catches silent test deletion forever.

**Effort:** low to start, high to complete. **Value:** medium-high.

---

## 4. Secondary opportunities

| Idea | Where it lands | Effort | Notes |
|---|---|---|---|
| **Retraction status** on cited works | `refcheck/retrieval.py` (Crossref/Retraction Watch) | med | Must be a *typed* signal: "not checked" ≠ "not retracted" |
| **Tortured-phrase detection** (paper-mill signal) | `research_companion/integrity` alongside `overlap.py` | low | Heuristic advisory only — never a verdict |
| **Style calibration** (learn the author's voice from past work) | new; feeds `report_export`/`scaffold` | med | Complements our draft tooling |
| **AI-prose quality check** | new, deterministic-first | med | Framed as "make it better", never "hide AI use" |
| **Multi-agent adversarial review** | extend `review_runner.py` lanes | med | We have lanes; they have *personas* that disagree (devil's advocate, domain, methodology) |
| **Socratic planning dialogue** | extend the Brief | med | Our Brief already produces cited bullets; a dialogue that interrogates the *question* is the missing front half |
| **Zenodo DOI + `CITATION.cff`** | repo root | **trivial** | Makes the tool citable in a paper — high symbolic value for an academic audience |
| **Multi-language README** | `docs/` | low | Their 5 languages plausibly drive a real share of those 42k stars |

---

## 4b. Where the research found *nothing* — treat these as unproven

The adversarial pass (112 agents, 2-of-3 refutations required to kill a claim) returned **no surviving verified evidence** for four of the angles investigated:

- **Trust-chain provenance frontmatter**
- **Tortured-phrase detection** as an effective paper-mill signal
- **Degradation registries / feature-off contracts** as an established industry practice
- **AI-prose detection and style calibration**

This does not mean they are bad ideas — §3.4's degradation registry is still cheap and useful *for us*, on its own merits. It means **there is no external evidence base to lean on**, so we should build them as our own conventions and not describe them as best practice. Detection of AI-generated prose in particular has a weak and contested evidence base; **we should not ship an "AI-written?" detector**, and the honest framing ARS itself uses — *improve the writing, don't hide the AI* — is the only defensible one.

Related: the claim that PaperOrchestra *"eliminates fabricated references"* was **refuted** — the source sentence is design intent, not a measured result. Useful reminder when we write our own README.

---

## 5. What we should **not** copy

Being deliberate about this matters as much as the adoption list.

- **Their prompt-only architecture.** Our deterministic, keyless core is a genuine differentiator; do not dissolve it into prompts.
- **The ceremony-to-substance ratio.** 2,410 files, 1,049 of them evals, and a `.command-invariants.toml`. For a repo our size that overhead would slow us more than it protects us. **Adopt the mechanisms, not the volume.**
- **Score capping as a universal lever.** ARS explicitly *rejected* it in favour of tri-state outcomes + advisory suffixes. We should reject it too — our RCS/coverage numbers should stay honest measurements, not policy knobs.
- **Non-commercial licensing.** Ours stays MIT.
- **Their `README` as a model.** It is enormous. Ours is already best-in-class per our own standard; keep it.

---

## 6. What we already do better (don't over-correct)

Worth stating plainly so this analysis doesn't read as one-way admiration:

1. **A real concept knowledge graph** over the user's own PDFs — ARS has nothing comparable.
2. **Deterministic core with no API key** — a large fraction of our value needs no model at all.
3. **A persistent workspace** (library, drafts, sessions, notes, journey) vs. per-invocation prompt runs.
4. **Draft↔literature alignment with per-section stance and verified evidence** — the feature we built the whole Draft tab around.
5. **An MCP server** exposing keyless verification to *other* agents — ARS is a consumer of Claude Code, not a provider to it.
6. **Shipping UI**, not just protocol.

---

## 7. The plan

Phased so each phase ships independently and nothing depends on a phase that may be cut.

### Phase 1 — Honesty machinery (highest value, mostly cheap)
1. **`signals.py`** — our own three-class epistemic carrier (fact / heuristic / attestation) with `check_status` independent of `finding`. Never renders unresolved as clean.
2. **Migrate existing signals** onto it: `refcheck`, `citations_coverage`, `coverage`, `rcs`, `alignment`, `novelty_check`.
3. **Guard test** — fails if any UI surface renders an unresolved signal as clean. (Analogous to our `viewSymbols` guard: encode the rule so it cannot regress.)
4. **`DEGRADATION_REGISTRY.json`** + CI checker, rows for every feature-off path we already promise.
5. **`CITATION.cff`** + Zenodo DOI.

*Exit:* our honesty claims are machine-enforced, not prose-enforced.

### Phase 2 — Claim-level audit (flagship)
6. **Locator anchors** — every citation we emit carries a resolvable pointer (paper id + section id + char range). We already have section tilings; this is mostly plumbing.
7. **`claim_audit.py`** — opt-in pass: fetch the anchored source, judge whether it supports the claim, emit a typed advisory (`claim-not-supported`, `anchorless`, `fabricated-reference`).
8. **Surface it** in Report citations, alignment evidence, and Brief bullets — advisory, never an auto-block.
9. **Docs** — state plainly that this is a model judgment with a measured error rate (see Phase 3), not proof.

*Exit:* we can answer "does this citation actually support this sentence?" — the question our competitors' users don't even get to ask.

### Phase 3 — Calibration
10. **`evals/`** scaffolding: gold / held-out split, fixture corpora, leakage guard.
11. **`research-companion calibrate`** — measures FNR/FPR/balanced accuracy for readiness verdict, alignment stance, RCS, novelty, and the Phase-2 claim audit.
12. **Gold-label isolation** enforced in code, plus **NOT COMPUTABLE** discipline (`annotated_n=n/N`, never a subset-derived `±X`).
13. Surface the measured profile in the UI beside the relevant verdicts.

*Exit:* every AI judgment we show can carry a measured error rate instead of a disclaimer alone.

### Phase 4 — CI hardening
14. **Test-count monotonicity** gate (cheapest, do it first, possibly pull into Phase 1).
15. **Eval harness** in CI on the gold set.
16. **Spec/doc consistency** check — our `docs/` claims vs. actual behaviour.
17. **Freshness check** for the venue KB and connector endpoints.

### Phase 5 — Content & reach
18. Retraction signals; tortured-phrase advisory.
19. Style calibration; AI-prose quality check.
20. Adversarial reviewer personas layered on `review_runner.py`.
21. Socratic planning front-end for the Brief.
22. Multi-language README.

---

## 8. Immediate next actions

| # | Action | Effort | Phase |
|---|---|---|---|
| 1 | `CITATION.cff` + Zenodo DOI | 30 min | 1 |
| 2 | Test-count monotonicity CI gate | 1 h | 1/4 |
| 3 | `DEGRADATION_REGISTRY.json` + checker | half day | 1 |
| 4 | `signals.py` + migrate `refcheck` as the pilot | 1–2 days | 1 |
| 5 | Locator anchors on emitted citations | 2–3 days | 2 |
| 6 | `claim_audit.py` behind a setting | 3–5 days | 2 |

**Recommended start: #1–#4.** They are cheap, they harden the promise we already make to users, and they are prerequisites for the flagship claim-audit work.

---

## 9. Sources

- ARS repo (structure, README, `shared/bibliographic_integrity_signals.md`, `shared/contracts/degradation_registry.json`, `academic-paper-reviewer/references/calibration_mode_protocol.md`), read 2026-08-13 at v3.19.0.
- Lu et al. (2026), *Nature* 651:914–919 — The AI Scientist; automated-reviewer error profile (Table 1).
- Zhao et al. (2026), arXiv:2605.07723 — 111M-reference audit; ~146,932 hallucinated citations estimated for 2025.
- Ren et al. (2026), arXiv:2607.13104 — *Self-Improvements in Modern Agentic Systems: A Survey*; evaluator independence, calibration against a verifiable subset.
- Song et al. (2026), arXiv:2604.05018 — PaperOrchestra.

*Primary-literature claims above are as reported in the ARS README and have not been independently verified against the papers themselves; verify before citing them in our own docs.*
