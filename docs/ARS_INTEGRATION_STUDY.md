# ARS vs Research Companion — plain-English study & integration feasibility

Companion to `ARS_COMPARATIVE_ANALYSIS.md` (which holds the technical detail and sources).
This one answers: *what do they actually do, what can we realistically take, and what changes if we do?*

---

## 1. What ARS does, in plain English

Think of an **assembly line for writing an academic paper**, where a coding assistant is the worker and ARS is the set of laminated instruction cards taped to each station.

| Station | What happens |
|---|---|
| **Research** | Find the literature on your topic |
| **Write** | Draft the paper |
| **Review** | Seven different "reviewer personalities" attack it — a methodology reviewer, a domain expert, a devil's advocate, an editor-in-chief |
| **Revise** | Fix what they found |
| **Finalize** | Format it, and refuse to hand it over if certain checks fail |

**ARS is not a program you run.** It has no database, no interface, no graph. It is ~2,400 files of *instructions and checks* that tell Claude Code how to behave at each station. Their own README says the core skills need **no Python** — they are prompt-driven.

**Their obsession is one thing: stopping the AI from lying to you.** Nineteen versions of increasingly paranoid machinery aimed at a single failure — an AI that produces confident, well-formatted, fake scholarship.

**We are a different animal.** A real application: it stores your PDFs, builds a concept graph across them, scores your draft against the literature, and runs a lot of it with no API key at all. They wrote *procedure*; we wrote *product*.

---

## 2. The example that shows the gap

Suppose you write this sentence in your draft:

> "Graph-based retrieval reduces hallucination by 40% [Edge et al., 2024]."

*(Illustrative example — the 40% figure is invented for the purpose.)*

Now watch what each tool catches.

### What Research Companion does today

| Check | Result |
|---|---|
| Does "Edge et al. 2024" exist? | ✅ **Yes** — `refcheck/` resolves it via Crossref/OpenAlex/arXiv |
| Is it in your library? | ✅ Yes — citation coverage confirms it |
| If you quoted it, is the quote verbatim? | ✅ Yes — `verify_quote` checks character-for-character |
| **Does that paper actually say "40%"?** | ❌ **We never check this.** |

**We pass it.** Green ticks all the way down. The reference is real, the paper is real, everything resolves — and the sentence is still false, because the 40% number appears nowhere in that paper.

### What ARS does

It attaches a **locator** to the citation (a quote, page, or section — "where exactly in that paper?"), then optionally fetches that spot and asks: *does this passage support the claim being made?*

Outcome isn't a yes/no. It's one of:

| Outcome | Meaning |
|---|---|
| ✅ verified | The source says it |
| ⚠️ **unverifiable** | Paywalled/unreachable — **we genuinely don't know** |
| 🚨 fabricated | The reference doesn't exist |
| 🚨 anchorless | No locator, so nothing could be checked |
| ⚠️ tool-failure | The checker itself broke |

That middle row is the important one. **"I couldn't check" must never be shown as "it's fine"** — and equally, must never be shown as "you made this up."

### Why this matters (verified against the source)

Zhao et al. audited **111 million references**. They classify checking *whether a reference exists* — the check we do — as **"among the easiest hallucination detection problems"**, and the *real-citation-but-unsupported-claim* case as the **more prevalent and harder-to-detect** variant.

**Blunt version: we built the easy check and skipped the one that matters.**

---

## 3. Can we integrate it? Feature by feature

20 distinct capabilities. Verdict on each:

### ✅ Can integrate — 11 features

| # | Feature | Effort | Where it lives in our tool |
|---|---|---|---|
| 1 | **Epistemic signal types** (fact / heuristic / attestation) | Medium | New `signals.py`, adopted by every check |
| 2 | **Claim-level citation audit** | High | New `claim_audit.py` → Report, Draft, Brief, Citations |
| 3 | **Locator anchors** on citations | Medium | We already store section IDs + char ranges — mostly plumbing |
| 4 | **Calibration mode** (measure our own FNR/FPR) | Med-High | New `evals/` + `research-companion calibrate` |
| 5 | **Degradation registry** | Low | `docs/DEGRADATION_REGISTRY.json` + CI checker |
| 6 | **JSON-schema contracts** for artifacts | Medium | Schemas for report/alignment/coverage payloads |
| 7 | **Test-count monotonicity** CI gate | Very low | One CI script |
| 8 | **Eval harness** in CI | Med-High | `evals/gold` + `evals/heldout` |
| 9 | **Retraction checking** | Medium | `refcheck/retrieval.py` |
| 10 | **CITATION.cff + Zenodo DOI** | Trivial | Repo root |
| 11 | **Adversarial reviewer personas** | Medium | Extend `review_runner.py` lanes |

### 🔶 Can adapt, but not copy — 4 features

| Feature | Why it changes shape for us |
|---|---|
| **Multi-agent review panel** | They spawn 7 agents per review. We have deterministic lanes already — we'd add *disagreement*, not 7 more LLM calls |
| **Socratic planning dialogue** | Ours would extend the Brief, which already produces cited bullets — we'd add the *questioning* front half |
| **Style calibration** | Only useful once we hold a corpus of the user's own writing; our draft store makes this plausible later |
| **Stage-gate pipeline** | We're a UI where users jump around, not a linear pipeline. Gates become *advisories*, not blocks |

### ❌ Cannot or should not take — 5

| Feature | Why not |
|---|---|
| **Any of their actual files** | **CC BY-NC 4.0 vs our MIT.** Copying relicenses us as non-commercial. Ideas only, re-implemented |
| **AI-prose detection** | The research found **no solid evidence base**. Shipping a detector would be dishonest |
| **Prompt-only architecture** | Our deterministic no-API-key core is a genuine advantage — don't dissolve it |
| **2,400-file ceremony** | 1,049 eval files and a `.command-invariants.toml` would slow us more than protect us |
| **Score capping** | ARS rejected it themselves; our numbers should stay measurements, not policy knobs |

**Score: 11 integrate + 4 adapt = 15 of 20 usable. 5 excluded (1 legal, 4 deliberate).**

---

## 4. What actually changes after integration

Honest per-feature assessment. *Effort figures are estimates; the "what changes" column is the claim I'd defend.*

| Feature | What changes for a user | Honest size of the win |
|---|---|---|
| Epistemic signal types | A failed check can no longer *look* like a passed one, anywhere in the app | **Large** — protects every existing feature |
| Claim-level audit | The tool can say *"your source doesn't actually say that"* | **Largest single win** — a capability we simply lack |
| Locator anchors | Every citation points at an exact spot; "unanchored" becomes visible | Medium — mainly an enabler for the above |
| Calibration | Verdicts carry a measured error rate instead of a disclaimer | **Large for credibility**, invisible day-to-day |
| Degradation registry | We can *prove* the feature-off promise, not just assert it | Medium |
| Retraction checks | Warns when you cite retracted work | Medium — high value when it fires |
| Schemas + eval + CI | Users notice nothing; regressions drop | Small for users, large for us |
| DOI | The tool becomes citable in a paper | Small effort, real symbolic value |

**Overall:** this doesn't add new user-facing *features* so much as it makes the ones we have **trustworthy enough to stake a reputation on**. For an academic-integrity tool, that *is* the product.

I won't give you a "+40% better" number — it would be exactly the kind of unsupported figure this whole document is about catching.

---

## 5. ⚠️ Correcting one thing in your framing

You said these features *"will enhance our brainstorming session and can be an integral part of where someone needs suggestion around the draft."*

**Half right — and the half that's off matters for sequencing.**

**Where you're right:** the Brief's cited bullets and Directions' citation chips are exactly the kind of AI output that needs claim-auditing. If a Brief bullet says "X reduces error by 40% [Paper]", we should verify the paper says it. Same for draft suggestions.

**Where the centre of gravity actually is:** these features pay off *most* on the **Draft / Report / Citations** side, not Brainstorm.

| Surface | Benefit | Why |
|---|---|---|
| **Report** | 🟢 Highest | Every answer is a claim + citations — exactly what claim-audit checks |
| **Draft alignment** | 🟢 Highest | Evidence quotes and stance verdicts — the calibration target |
| **Citations tab** | 🟢 High | Where retraction + existence + claim checks converge |
| **Brief** | 🟡 Medium | Cited bullets benefit, but they're short and user-edited |
| **Directions** | 🟡 Medium | Citations are *grounding*, not claims about content |
| **Brainstorm search** | ⚪ Low | Retrieval, not assertion — nothing to audit |

**Why the distinction matters:** brainstorming is where the user is *exploring*, and a wrong suggestion costs a few seconds. Drafting is where a wrong citation ends up **in a submitted paper**. That's where the damage is, so that's where the machinery should land first.

**So: yes to your instinct, but sequence it Draft/Report first, Brainstorm second.**

---

## 6. What's left over — and what we do instead

Things ARS has that we've excluded, and our own answer to each:

| Their approach | Our better-fitting alternative |
|---|---|
| AI-prose detection | **Don't.** Instead: make the *citations* verifiable. Provenance beats stylometry |
| 7-agent review panel per paper | Our deterministic lanes + **one** adversarial pass. Cheaper, reproducible, works without a key |
| Prompt-only, no persistence | Our store + concept graph — we can audit *across* a corpus, which they structurally cannot |
| Linear stage gates | Advisory gates in a UI users navigate freely |
| Ceremony at scale (2,400 files) | Targeted guards. Our `viewSymbols` test is the model: one script, encodes one rule, can't regress |

### And three things we could do that they can't

1. **Corpus-level claim audit.** They audit one paper's references. We hold your whole library *and* a concept graph — we could flag when a claim contradicts other papers you already have. Nothing in ARS can do this.
2. **Keyless verification as a service.** Our MCP server already exposes verification to *other* agents. Adding claim-audit there makes us infrastructure, not just an app.
3. **Longitudinal calibration.** We have a persistent workspace, so error rates could be measured *on your own corpus over time*, not just against a static gold set.

---

## 7. Recommended sequence

1. **Cheap credibility** — `CITATION.cff` + DOI, test-count CI gate, degradation registry *(~1 day total)*
2. **Honesty machinery** — `signals.py` + migrate `refcheck` as pilot *(1–2 days)*
3. **Locator anchors** on emitted citations *(2–3 days)*
4. **Claim audit** behind a setting → Report and Draft first *(3–5 days)*
5. **Calibration** once #4 exists — otherwise there's nothing to calibrate
6. Retraction checks, reviewer personas, Socratic Brief

Steps 1–2 are worth doing regardless of whether we ever build the rest.
