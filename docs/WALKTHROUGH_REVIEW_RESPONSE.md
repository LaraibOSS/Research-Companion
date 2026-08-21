# Review response — decision record

An external reviewer read [`WALKTHROUGH.md`](WALKTHROUGH.md) as a research workflow
rather than as documentation, proposed a restructure and a set of feature changes;
that response was reviewed in turn against the source, and the reviewer then revised
their assessment. This records what two rounds settled, what was declined, and why.

Every checkable claim was verified against the implementation before being accepted
or rejected. That is the reason the two rounds reached different conclusions.

---

## Verdict

**Most of what the first round identified as architectural problems were
documentation problems.** The product is more epistemically careful than the
walkthrough made it look — in four places the document undersold behaviour that was
already implemented.

The reviewer reached the same conclusion independently in round 2 and withdrew the
recommendations that were already built. What survives is a short list of real gaps,
and one finding that neither round started with.

**The highest-leverage remaining work is not a feature.** It is making the evidence
semantics consistent across code, CLI, UI and docs — and the canonical vocabulary for
that already exists in `signals.py`, adopted by exactly one module.

---

## Verified against source

| claim | verdict | evidence |
|---|---|---|
| "Does novelty only search my library?" | **No — searches externally** | `novelty_check.py` → `discover.search_topic_with_fallback` (S2 / OpenAlex / arXiv) |
| "Stop using binary Novel / Not Novel" | **Already graded** | `_VERDICTS = {novel, incremental, overlaps, anticipated}` |
| "Venue rules need year versioning" | **Confirmed gap** | `venues.json` has no `year`, `updated` or `source` field |
| "Say corpus density, not field crowdedness" | **Product overclaims too** | `helpContent.js`: "where the field clusters" |
| "Soften Gaps' *real open problem*" | **Product already careful** | `open / partially / addressed`; `addressed + unverified` → `partially` |
| "82% reads as confidence" | **Product already labels it** | Report caption: "AI judgements — not independently verified" |
| "Unify status vocabulary across checkers" | **Vocabulary exists, adoption does not** | `signals.py` defines it; imported by `claim_audit.py` **only** |

---

## The finding neither round started with

Round 2 proposed a single status vocabulary for every deterministic checker:

> PASS · FAIL · NOT APPLICABLE · COULD NOT PARSE · NOT CHECKED
>
> "A researcher learns the epistemic language once and then understands every
> checker."

The instinct is right and the payoff is real. Two corrections.

**The vocabulary already exists, and is better than the proposal.** `signals.py`
separates two *orthogonal* axes that the flat list conflates:

| axis | values | question it answers |
|---|---|---|
| `CheckStatus` | `CHECKED` · `NOT_CHECKED` · `DEGRADED` · `UNKNOWN` | did the check run? |
| `Finding` | `SUPPORTED` · `CONTRADICTED` · `UNRESOLVED` | what did it conclude? |

In the flat list, `NOT APPLICABLE` and `COULD NOT PARSE` are *statuses* while `PASS`
and `FAIL` are *findings*. Collapsing them loses the distinction the whole product is
built on, and it is currently enforced rather than merely documented — a `Signal`
whose status is incomplete but whose finding is not `UNRESOLVED` raises `SignalError`
at construction. A check that did not finish **cannot** report a conclusion.

Adopting the flat list would be a regression. Adopting `signals.py` everywhere is the
actual work.

**The gap is adoption, not design.** `signals.py` is imported by one module. Reference
checking, statcheck, compliance, overlap and coverage each report an ad-hoc shape, so
the same idea — *we could not check this* — is expressed differently five times.

This reframes several round-2 items: statcheck applicability, venue check states and
Submission Readiness are not five wording fixes but **one adoption pass**, after which
the dashboard is mostly a rendering of signals that already agree.

**One genuine addition falls out of it.** `CheckStatus` has no `NOT_APPLICABLE`. GRIM
on a machine-learning paper is not `NOT_CHECKED` (we chose not to run it) and not
`DEGRADED` (we tried and failed) — the check is *meaningless for this input*. The
review's GRIM point exposes a real hole in the model.

---

## Settled across both rounds

### Accepted — documentation, done

| item | outcome |
|---|---|
| Ordering: Reader → graph → timeline → gaps → directions | Reader **9 → 5**, Timeline **10 → 7**, Gaps **11 → 8** |
| Ask / Compare / Report as utilities, not stages | regrouped; also fixes "the diagram skips steps" |
| Open-web contradiction | replaced with two precise rules |
| Novelty presented as binary | renamed **Novelty screen**; all four outcomes documented |
| Gaps "real open problem" | "recurring stated gap" + the status table already in the product |
| "field crowdedness" | corpus density, with the six-quantisation-papers illustration |
| "verified quote" | defined as a *text match*, distinguished from entailment |
| `82%` | `relevance 0.82` — a retrieval score, not a confidence |

### Accepted — product, outstanding

| item | note |
|---|---|
| **Venue year / track / source / last-verified** | plus hard requirement vs recommendation vs cannot-check-automatically |
| **`NOT_APPLICABLE` status + statcheck states** | GRIM rarely applies to ML; silence must not read as a pass |
| **`signals.py` adoption across checkers** | the unification round 2 asked for; vocabulary already canonical |
| **Corpus coverage indicator** | round 2 elevated this to P1, correctly — see below |
| **Submission Readiness** | and **not** a single green/red score |
| **"Corpus density" in `helpContent.js`** | the product makes the same overclaim the document did |
| **Rename "verified quote" in the UI** | text-match badge separate from claim-support verdict |

### Accepted from round 2, revised from round 1

**Evidence Map, not Evidence Ledger.** Round 1 proposed a table with a corpus-wide
**Status** column. That was declined: aggregating `claim_audit`'s deliberately hedged
per-passage judgements into one authoritative-looking verdict compresses uncertainty
precisely where the product's value is refusing to.

Round 2 withdrew the Status column and proposed a navigational version instead —
supporting / challenging / unclear passage *counts*, each clicking through to the
passages and their individual audit states. That version exposes the uncertainty
rather than collapsing it, and is accepted in principle.

Cost note: it is largely a *view* over data that already exists (claim-audit results,
alignment evidence, report citations). The real work is keying — those results are
currently per-artifact, not per-claim.

**Corpus coverage elevated, and named more honestly.** Round 2 moved this up on the
grounds that nearly every downstream signal is conditioned on the corpus, so the
dominant uncertainty is often not *"was the model right?"* but *"was the evidence
universe complete?"* — which is correct, and a stronger argument than round 1's.

It also self-corrected the labels: **Seed / Exploratory / Expanded** rather than
"Systematic", because systematic review is a methodological term of art and claiming
it without reproducible search protocols would be exactly the kind of overclaim the
rest of the product avoids. Accepted, including the correction.

Added condition: the label must be *computed* from something observable (seed count,
expansion rounds, citation/reference traversal), not self-declared. A label a user
picks is a preference, not a coverage measure.

**Novelty class definitions.** Each of the four outcomes gets an explicit definition,
and every result retains its search scope, sources, retrieval date and closest
matches. Accepted — that is what makes a screen defensible rather than an opinion.

---

## Declined

**Invisible graph weighting from subjective quality labels.** Filtering by
include/exclude, core/peripheral, year, venue or type is fine and useful. Turning a
researcher's priors into weighting *inside the graph algorithm* replaces a visible
bias with a hidden one. Round 2 agreed.

**Forced sequential wizard.** The six phases are accepted as mental model, onboarding
and documentation structure — not as a workflow state machine. The tab model is a
strength, which round 1 implicitly conceded by arguing Ask and Compare are
cross-cutting. Round 2 converged on the same framing: *a non-linear research
workspace with a recommended lifecycle.*

**Research Scope object — deferred, not rejected.** Ceremony until retrieval or
analysis actually consumes it. It becomes meaningful when the system can say *"this
paper was retrieved but falls outside your stated scope"* — at which point it is
worth building.

---

## Epistemic copy invariants

The most useful idea to come out of either round, and it came from the closing lesson
of the first response rather than from the original review.

Guard tests can check that commands exist, that venues resolve, that every tab is
covered. They largely **cannot** detect prose that subtly overclaims. That is exactly
the failure that occurred here: the walkthrough flattened nuanced behaviour into
simpler language and made the product look less rigorous than it is.

Proposed as a lint over documentation and UI strings — not semantic testing, just
flagging phrases that require human review:

| never say | when the truth is |
|---|---|
| "the field" | measured only over the corpus |
| "verified" | without stating *what* was verified |
| "no prior work exists" | no match found in the sources searched |
| "passed" | no applicable check ran |
| "fake" / "fabricated" citation | not found in the catalogues searched |
| "real open problem" | a recurring *stated* gap |

Every one of these has already been violated once — four of them by the walkthrough,
before review caught them. That is the argument for mechanising it.

---

## Backlog

| priority | item |
|---|---|
| **done** | walkthrough ordering, open-web contradiction, novelty framing, corpus-vs-field, gaps wording, quote semantics, relevance figures |
| **P1** | `signals.py` adoption across checkers + `NOT_APPLICABLE` status |
| **P1** | venue year / track / source / last-verified, and requirement tiers |
| **P1** | statcheck applicability states |
| **P1** | "corpus density" and "text-match verified" in the UI |
| **P1** | epistemic copy lint |
| **P2** | corpus coverage indicator (Seed / Exploratory / Expanded, computed) |
| **P2** | Submission Readiness, reporting counts rather than one verdict |
| **P2** | direction-ranking dimensions, without a composite truth score |
| **P3** | Evidence Map — navigation only, no aggregate verdict |
| **later** | Research Scope, once retrieval consumes it |
| **rejected** | invisible graph weighting; forced wizard |

---

## Lessons

**A product can be honest and still be misrepresented by its own documentation.** Both
rounds of review were shaped by wording, not behaviour, and an expert reviewer
reasonably attributed the document's overclaims to the software. Four of the six
issues in round 1 dissolved on contact with the source.

**Verify before agreeing.** Accepting round 1 at face value would have produced work
to add a feature that already existed, restructure a UI that was not at fault, and
build a ledger that would have undermined the product's central principle.

**The consistency work outranks the feature work.** The system's differentiator is
that it separates what is known, inferred, not found and not checked. That separation
is modelled precisely in one file and expressed ad-hoc nearly everywhere else.
Closing that gap is worth more than any single feature on this list.
