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

## What the review concluded

Round 2 separated the assessment into three things the first round had treated as
one. The separation is the useful part; the numbers are the reviewer's.

| area | assessment |
|---|---|
| core feature architecture | 9 / 10 |
| epistemic design / research integrity | 9 / 10 |
| research workflow concept | 8.5–9 / 10 |
| product UX / information architecture | 8 / 10 |
| walkthrough **before** these fixes | 6.5–7 / 10 |
| walkthrough **after** these fixes | 8.5–9 / 10 |

The original headline — *"the feature set is stronger than the flow"* — held for the
document and not for the software. That distinction is the whole result of the
exchange.

Round 2 also produced a better one-line description of the architecture than either
side started with:

> **A non-linear research workspace with a recommended research lifecycle.**

Recommended journey: discovery → understanding → opportunity → development →
verification. Everything remains reachable at any time. A researcher must be able to
compare papers before opening the graph, check citations mid-draft, return to
discovery after choosing a direction, or read a paper at any point.

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

## Specifications for the accepted work

Recorded concretely so the backlog can be executed without re-reading the exchange.

### Venue rule versioning

`venues.json` entries gain provenance. A deterministic check is only as trustworthy
as the vintage of its rules, and conference requirements change annually.

```yaml
slug: aaai-2027-main
name: AAAI-27 Main Technical Track
venue: AAAI
year: 2027
track: Main Technical Track
rules_version: 2026-08-01
source: official CFP            # url or citation
last_verified: 2026-08-15
```

Surfaced in output as `AAAI-27 Main Technical Track · rules verified 15 Aug 2026`,
so a stale rule set is visible rather than silently trusted.

Checks additionally report a **tier**, because not everything is machine-checkable:

| tier | example |
|---|---|
| hard requirement | page limit, required sections |
| recommendation | suggested structure |
| cannot check automatically | anonymity, formatting fidelity |

`cannot check automatically` must render as *check manually*, never as a pass.

### Status vocabulary — adopt `signals.py`, do not invent one

Target: every deterministic checker emits `Signal`s instead of an ad-hoc shape.

| checker | current | target |
|---|---|---|
| `claim_audit` | `Signal` | unchanged (reference implementation) |
| `refcheck` | `verified / suspect / unverified` + reasons | `Signal` per reference |
| `statcheck` | findings + summary text | `Signal` per test |
| `check-compliance` | `ok / finding / skipped` + severity | `Signal` + tier |
| `check-overlap` | findings + summary | `Signal` per passage |
| report coverage | `pct / cited / relevant_available` | `Signal` + raw counts |

One addition to the model:

```python
class CheckStatus(str, Enum):
    CHECKED = "checked"
    NOT_CHECKED = "not_checked"        # never attempted
    NOT_APPLICABLE = "not_applicable"  # NEW - meaningless for this input
    DEGRADED = "degraded"              # attempted, could not finish
    UNKNOWN = "unknown"
```

`NOT_APPLICABLE` must join `INCOMPLETE_STATUSES`, so the existing invariant keeps
holding: a check that did not conclude cannot carry a finding.

### Novelty class definitions

Each outcome gets a stated definition rather than a bare label:

| outcome | definition |
|---|---|
| **novel** | no substantively similar work found within the searched sources |
| **incremental** | prior work substantially overlaps, but a meaningful extension appears present |
| **overlaps** | major components of the proposed contribution already exist |
| **anticipated** | existing work appears to contain essentially the proposed contribution |

Every result retains **search scope, sources queried, retrieval date, and closest
matches**. Those are what make it a screen rather than an opinion.

### Corpus coverage indicator

Persistent, e.g. `18 papers · exploratory corpus`.

| label | meaning |
|---|---|
| **seed** | a handful of starting papers |
| **exploratory** | searched, not expanded |
| **expanded** | citation / reference traversal performed |

Deliberately **not** "systematic" — that is a methodological term of art, and
claiming it without reproducible search protocols would be the exact kind of
overclaim the rest of the product avoids.

The label must be **computed** from observable state (seed count, expansion rounds,
traversal performed), never self-declared. A label the user picks is a preference
wearing a measurement's clothes. Caption it: *descriptive, not a guarantee of
exhaustiveness.*

### Submission Readiness

One view, five cards, **no single green/red verdict**:

```
Citation integrity · Claim grounding · Statistical checks
Originality · Venue compliance

4 issues requiring attention
2 checks could not be completed
31 checks passed
```

Reporting counts rather than a score preserves the distinction the product is built
on: *could not complete* never collapses into *passed*.

### Evidence Map

Navigation over existing data. **No aggregate truth column.**

| research claim | sources | supporting | challenging | unclear | coverage |
|---|---|---|---|---|---|
| KV compression reduces memory | 7 | 4 | 1 | 2 | 7 papers |

Every number clicks through to the passages and their individual audit states. The
counts are navigation, not a verdict — which is the difference between this and the
rejected ledger.

Cost note: the underlying results already exist in claim audit, alignment evidence
and report citations. The work is **keying** — those results are stored per artifact,
not per claim.

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
