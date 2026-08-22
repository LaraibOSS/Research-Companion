# Evidence semantics — architecture decision record

Began as a response to an external review of [`WALKTHROUGH.md`](WALKTHROUGH.md) and
became a decision record for the product's evidence model, which is where four rounds
of review converged.

Organised by topic, not by round. Each section states the decision reached, not the
path to it. Every claim about current behaviour was verified against source — which is
why successive rounds reached different conclusions.

**If you are implementing this:** §1 is the schema and must be settled first; the
backlog at the end is ordered by dependency, not by value. Where this record and the
code disagree, the code has been right every time so far — check before changing.

---

## Verdict

**Most of what was first identified as architectural problems were documentation
problems.** The product is more epistemically careful than the walkthrough made it
look; in four places the document undersold behaviour that was already implemented.

**The highest-leverage remaining work is not a feature.** The system's differentiator
is that it separates *known · inferred · not found · not checked · unresolved*. That
separation is modelled precisely in one file and expressed ad hoc nearly everywhere
else.

Two models exist, both good, and **they do not reference each other**:

| model | file | adoption |
|---|---|---|
| epistemic state — did it run, what did it conclude | `signals.py` | **1 of ~8** checkers |
| document provenance — paper, section, character offsets | `locator.py` | not linked to signals |
| prompt provenance — which prompt produced a heuristic result | `prompts.py` `*_prompt_sha256()` | not carried on signals |

`claim_audit.py` is the only module using the first two, and it drops the link.
Connecting them turns the model from *finding + execution state* into *finding +
execution state + provenance*, which is what an audit trail requires — with the
caveat that provenance generalises past documents (§1, Change 3): a catalogue record,
a query, a venue rule are all evidence.

**The theme for the next iteration is consistency, not capability:** make the type
system, the checker outputs, the UI language and the documentation express one
contract.

### How the review rated it

The useful part is the separation, not the numbers.

| area | assessment |
|---|---|
| core feature architecture | 9 / 10 |
| epistemic design / research integrity | 9 / 10 |
| research workflow concept | 8.5–9 / 10 |
| product UX / information architecture | 8 / 10 |
| walkthrough **before** these fixes | 6.5–7 / 10 |
| walkthrough **after** these fixes | 8.5–9 / 10 |

The original headline — *"the feature set is stronger than the flow"* — held for the
document and not for the software.

Best one-line description of the architecture, reached in round 2:

> **A non-linear research workspace with a recommended research lifecycle.**

Recommended journey: discovery → understanding → opportunity → development →
verification. Everything stays reachable at any time — compare papers before opening
the graph, check citations mid-draft, return to discovery after choosing a direction.

---

## Verified against source

| claim | verdict | evidence |
|---|---|---|
| "Does novelty only search my library?" | **No — searches externally** | `novelty_check.py` → `discover.search_topic_with_fallback` |
| "Stop using binary Novel / Not Novel" | **Already graded** | `_VERDICTS = {novel, incremental, overlaps, anticipated}` |
| "Unify status vocabulary across checkers" | **Vocabulary exists; adoption does not** | `signals.py` imported by `claim_audit.py` only |
| "Signal should carry provenance" | **Provenance model exists, unlinked** | no reference to `locator` in `signals.py` |
| "Venue rules need year versioning" | **Confirmed gap** | `venues.json` has no `year` / `updated` / `source` |
| "Say corpus density, not field crowdedness" | **Product overclaims too** | `helpContent.js`: "where the field clusters" |
| "Soften Gaps' *real open problem*" | **Product already careful** | `open / partially / addressed`; unverified downgraded |
| "82% reads as confidence" | **Product already labels it** | "AI judgements — not independently verified" |
| "`Finding` is too claim-specific" | **Partly — `name` carries the proposition** | `claim_audit` sets `name = "claim_supported"` |
| "Is no-anchor `NOT_CHECKED` or `DEGRADED`?" | **`DEGRADED` — code already correct** | anchorless routes through `signals.could_not_check()` |
| "Heuristic results need version provenance" | **Mechanism exists, unattached** | `prompts.py`: `extraction_/novelty_/claim_audit_prompt_sha256()` |

---

## 1. The Signal model

The centre of the whole review.

### Current state

```python
@dataclass(frozen=True)
class Signal:
    name: str
    epistemic_class: EpistemicClass   # deterministic / heuristic / attestation
    check_status: CheckStatus         # CHECKED NOT_CHECKED DEGRADED UNKNOWN
    finding: Finding                  # SUPPORTED CONTRADICTED UNRESOLVED
    detail: str = ""                  # free text
    source: str = ""                  # the CHECKER name, not the document
    evidence: dict = ...
```

Two **orthogonal** axes, which is the design's strength:

| axis | question |
|---|---|
| `check_status` | did the verification process run? |
| `finding` | what did the evidence allow it to conclude? |

```text
CHECKED         → SUPPORTED | CONTRADICTED | UNRESOLVED
NOT_CHECKED     → UNRESOLVED
DEGRADED        → UNRESOLVED
UNKNOWN         → UNRESOLVED
```

Enforced, not merely documented: a Signal whose status is incomplete but whose finding
is not `UNRESOLVED` raises `SignalError` at construction. **A check that did not finish
cannot carry a conclusion.**

A flat vocabulary — `PASS / FAIL / NOT APPLICABLE / COULD NOT PARSE / NOT CHECKED` —
was proposed and **rejected**: it conflates the two axes. *Parse failed* says nothing
about whether a claim is true; *unsupported* says nothing about whether the checker
completed.

### Is `Finding` too claim-specific to generalise?

The strongest objection raised against this plan: `SUPPORTED / CONTRADICTED /
UNRESOLVED` reads naturally for claim audit, but does *"DOI and title match the
catalogue record"* really mean `SUPPORTED`? Does *"page count exceeds the limit"* mean
`CONTRADICTED`? The worry is that forcing six domains into one vocabulary creates a
new semantic mismatch at the type level — the very thing the migration is meant to
remove.

**Mostly resolved by a property the model already has: `Signal.name` is the
proposition.** `claim_audit` sets `name = "claim_supported"`. The name states *what
was tested*; `finding` states *whether it holds*. Read that way, the axis generalises
cleanly:

| checker | proposition (`name`) | adverse outcome |
|---|---|---|
| claim audit | `claim_supported` | `CONTRADICTED` |
| refcheck | `reference_exists` | `CONTRADICTED` |
| statcheck | `statistics_internally_consistent` | `CONTRADICTED` |
| compliance | `meets_page_limit` | `CONTRADICTED` |
| overlap | `passage_is_original` | `CONTRADICTED` |

A proposed alternative — a domain-specific `outcome` plus a common `disposition` —
was **declined**: it re-introduces per-checker vocabularies one layer down, which is
what the migration exists to remove.

**Naming discipline this implies:** name the proposition so that `SUPPORTED` always
means *no problem found*. `passage_is_original`, not `overlap_detected`. Otherwise
`CONTRADICTED` means "good" in one checker and "bad" in another, and the canonical
renderer cannot colour anything.

### But measurements are not signals

The objection **does** hold for one case, and the fix is to narrow the model's scope
rather than widen its vocabulary.

Report coverage produces *"17 of 24 retrieved relevant passages were cited."* There is
no proposition there — nothing is supported or contradicted. It is a measurement with
a denominator.

| kind | answers | example |
|---|---|---|
| **Signal** | did we establish X? | `reference_exists` → `CONTRADICTED` |
| **Metric** | how much? | coverage `17/24` |

Forcing a metric into `Signal` would mean an optional `value` field that is null for
almost every signal, and a `finding` that has to be `UNRESOLVED` forever. **Coverage
is therefore removed from the migration list** — it stays a metric, reported with its
raw numerator and denominator, and the honesty rule that already applies to it (a BM25
heuristic, not ground truth) is a copy concern, not a Signal one.

This is a correction to an earlier version of this record, which listed coverage as
`Signal + raw counts`.

### Change 1 — add `NOT_APPLICABLE`

A real conceptual gap, not a UI nicety.

| status | meaning |
|---|---|
| `NOT_CHECKED` | we did not run it |
| `DEGRADED` | we ran it and could not complete it |
| `NOT_APPLICABLE` | **new** — running it is meaningless for this artifact |

GRIM on a machine-learning paper is the case: not skipped, not broken, simply not
applicable to the statistics reported. Must join `INCOMPLETE_STATUSES` so the invariant
continues to hold.

### Change 2 — structured `reason`, so status stays small

Everything explaining *why* must not become a status, or the enum grows
`PARSE_FAILED`, `DOWNLOAD_FAILED`, `NO_TEXT`, `TIMEOUT` and stops being a model.

| field | answers | example |
|---|---|---|
| `check_status` | what epistemic state? | `DEGRADED` |
| `reason` | why? | `PARSE_FAILED` |

```text
DEGRADED        + SOURCE_UNAVAILABLE
DEGRADED        + NO_ANCHOR
NOT_CHECKED     + USER_DISABLED
NOT_APPLICABLE  + STATISTIC_TYPE_UNSUPPORTED
```

The UI reasons about status; `reason` is diagnostics. Today this lives in free-text
`detail`, so nothing can group or count it.

**Formal definitions**, because `NOT_CHECKED` and `DEGRADED` are otherwise easy to
confuse:

| status | definition |
|---|---|
| `CHECKED` | ran to completion and produced a conclusion |
| `NOT_CHECKED` | never attempted — feature off, no key, not requested |
| `DEGRADED` | **attempted**, could not produce a valid conclusion |
| `NOT_APPLICABLE` | does not conceptually apply to this artifact |
| `UNKNOWN` | state cannot be reconstructed — deserialisation and migration only, never produced by normal execution |

An earlier draft of this record listed `NOT_CHECKED + NO_ANCHOR`, which contradicts
those definitions: the audit *was* requested and failed on a missing prerequisite.
**The shipped code already gets this right** — `claim_audit` routes anchorless
citations through `signals.could_not_check()`, which is `DEGRADED + UNRESOLVED`. The
spec was wrong, not the implementation.

### Change 3 — provenance: wire in `locator.py`

`locator.py` already resolves a claim to paper, section and character offsets, ranks
anchor strength `QUOTE > SECTION > PAPER > NONE`, and can re-resolve later. `Signal`
does not reference it. `claim_audit.py` uses both and discards the connection:
`_result()` sets `source="claim_audit"`, then the Locator resolves the passage text and
is dropped.

> **Trap.** `Signal.source` today means *which checker produced this*, not *which
> document the evidence came from*. Adding provenance means redefining that field or
> adding another. It is the first thing anyone will assume wrongly.

**But provenance is not always a document location.** Once `Signal` is universal, the
evidence behind it varies by checker:

| checker | evidence is |
|---|---|
| claim audit | paper + section + quote offsets |
| refcheck | a CrossRef / OpenAlex / arXiv catalogue record |
| novelty | database + query string + retrieved candidate |
| compliance | a venue rule at a stated version |
| overlap | **two** document locations |

So the field cannot be `locator: Locator`. It needs a small union — `DocumentLocator`
(wrapping the existing `locator.py` unchanged), `CatalogueRecord`, `VenueRule`,
`SearchQuery`, `ExternalMatch` — held as a list, since overlap needs two.

**And the subject is not the evidence.** These are different things and collapsing
them loses the audit trail:

```text
subject   bibliography entry #17          evidence  CrossRef 10.xxxx/xxxx
subject   claim in Introduction ¶3        evidence  Smith et al. §4.2 chars 841–1027
```

Target:

```text
Signal
  name            claim_supported
  epistemic_class HEURISTIC_ADVISORY
  check_status    CHECKED
  finding         SUPPORTED
  reason          -
  subject         EvidenceRef(...)     what was checked
  evidence        [EvidenceRef(...)]   what it was checked against
  checker         claim-audit
  checker_version 1.4.2
  prompt_sha      <sha256>
  checked_at      2026-08-22T...
```

**Version provenance matters for heuristic signals specifically.** `EpistemicClass`
already distinguishes deterministic from heuristic; a heuristic result is only
reproducible if you know which model and prompt produced it. The mechanism already
exists — `prompts.py` exposes `extraction_prompt_sha256()`, `novelty_prompt_sha256()`,
`citation_polarity_prompt_sha256()` and others — it is simply not carried on the
Signal. Another capability present but unconnected.

### Change 4 — adopt it everywhere

| checker | current shape | target |
|---|---|---|
| `claim_audit` | `Signal` | unchanged — reference implementation |
| `refcheck` | `verified / suspect / unverified` + reasons | `Signal` per reference |
| `statcheck` | findings + summary text | `Signal` per test |
| `check-compliance` | `ok / finding / skipped` + severity | `Signal` + requirement tier |
| `check-overlap` | findings + summary | `Signal` per passage |
| report coverage | `pct / cited / relevant_available` | **stays a metric** — see above |

### Change 5 — one canonical renderer

Unifying the backend is not sufficient. Without a single rendering component the same
Signal surfaces as *Verified* on one screen, *Passed* on another, *Clean* on a third —
the divergence removed from the backend, reintroduced one view at a time.

The prototype exists: `claimAuditHelpers.js` maps one signal type to
`{label, tone, title, isAdverse}` as a pure, DOM-free, testable module consumed by both
Report and Draft. Generalising it from claim-audit outcomes to `(check_status, finding)`
pairs is the work — not a new architecture.

```text
CHECKERS → Signal → canonical renderer → every surface
                                          audit · refs · stats
                                          compliance · overlap
                                          submission readiness
```

---

## 2. Venue rule provenance

A deterministic check is only as trustworthy as the vintage of its rules, and
conference requirements change annually. `venues.json` records none of this.

```yaml
slug: aaai-2027-main
name: AAAI-27 Main Technical Track
venue: AAAI
year: 2027
track: Main Technical Track
rules_version: 2026-08-01
source: official CFP
last_verified: 2026-08-15
```

Surfaced as `AAAI-27 Main Technical Track · rules verified 15 Aug 2026`, so a stale
rule set is visible rather than silently trusted.

Each rule also carries a **tier**, because not everything is machine-checkable:

| tier | example | renders as |
|---|---|---|
| hard requirement | page limit, required sections | pass / fail |
| recommendation | suggested structure | advisory |
| cannot check automatically | anonymity, formatting fidelity | **check manually** — never a pass |

**Design for per-rule provenance even if v1 stores it per venue.** A page limit may
come from the author kit while the anonymity rule comes from the CFP; a researcher
should eventually be able to ask *"why are you telling me this is required?"* and get
the source.

---

## 3. Discovery depth

Nearly every downstream signal is conditioned on the corpus, so the dominant
uncertainty is often not *"was the model right?"* but *"was the evidence universe
complete?"*

**Named "discovery depth", not "coverage".** What is measured is how much discovery
and expansion work was performed — not what fraction of the relevant literature was
found. Even `expanded` establishes nothing about completeness. "Coverage" stays
reserved for places with a real denominator, such as report coverage. This is the
epistemic-copy rule (EP001) applied to this record's own earlier wording.

Computed from **search actions, never corpus size** — 50 manually added papers are not
better searched than 15 seeds plus two rounds of citation expansion.

| label | earned by |
|---|---|
| **seed** | manual additions or a single keyword search |
| **exploratory** | multiple searches or search strategies executed |
| **expanded** | at least one graph expansion — references, citations, related work |

Deliberately **not** "systematic": that is a methodological term of art, and claiming
it without reproducible search protocols would be the exact overclaim the rest of the
product avoids.

Expose the raw facts so the label is shorthand rather than a hidden heuristic:

```text
18 papers · 3 searches · 2 citation-expansion rounds · last discovery 21 Aug
```

Caption it *descriptive, not a guarantee of exhaustiveness.*

---

## 4. Novelty screen

Already graded, already searches externally. What is missing is definition and
auditability.

| outcome | definition |
|---|---|
| **novel** | no substantively similar work found within the searched sources |
| **incremental** | prior work substantially overlaps, but a meaningful extension appears present |
| **overlaps** | major components of the proposed contribution already exist |
| **anticipated** | existing work appears to contain essentially the proposed contribution |

Every result retains **search scope · sources queried · retrieval date · closest
matches · the query strings themselves**. Results change dramatically with how a
contribution is translated into queries, so the researcher must be able to audit what
was actually searched for, not merely which databases.

Internal enum values stay; **display labels change**, because several of them read as
verdicts rather than as search outcomes:

| enum | display label |
|---|---|
| `novel` | No close match found |
| `incremental` | Extension of close prior work |
| `overlaps` | Substantial overlap found |
| `anticipated` | Very close prior work found |

The internal vocabulary is load-bearing in code and tests; the user-facing word is
not. `anticipated` in particular is opaque to a reader who has not seen the
definition.

---

## 5. Submission Readiness

Solves a narrative problem, not only a dashboard one: the pipeline has a strong
beginning and a fragmented end — citations, stats, overlap, venue, export.

**No composite score.** `Readiness: 87%` would destroy the epistemic discipline built
everywhere else. Report counts, grouped by actionability:

| group | contents | costs the researcher effort? |
|---|---|---|
| **Needs attention** | adverse findings — problems actually found | yes |
| **Needs manual review** | `DEGRADED`, or not automatable | yes |
| **Not checked** | relevant, not yet run | maybe |
| **Not applicable** | `NOT_APPLICABLE` — no meaning for this artifact | **no** |
| **Checked, no issue found** | completed, nothing adverse | no |

An earlier draft grouped `NOT_APPLICABLE` under *needs manual review*. That was wrong
and contradicted the reason for adding the status: if GRIM does not apply to an ML
result, there is nothing for the researcher to review. **`NOT_APPLICABLE` must never
increase the action count.** The last two groups can share a collapsed section
visually, but not semantically.

```text
Citation integrity · Claim grounding · Statistical checks
Originality · Venue compliance

4 issues requiring attention
2 checks could not be completed
31 checks passed
```

Grouping by actionability keeps *could not complete* visible instead of letting it
drift into the pass column.

---

## 6. Evidence Map

Navigation over existing data. **No aggregate truth column.**

| research claim | sources | supporting | challenging | unclear | coverage |
|---|---|---|---|---|---|
| KV compression reduces memory | 7 | 4 | 1 | 2 | 7 papers |

Every number clicks through to the passages and their individual audit states.

**Must not invite arithmetic.** Rendering `4 supporting` green against `1 challenging`
red makes the reader compute *4 > 1, therefore true* — a verdict reached visually after
being deliberately withheld in the data. Lead with the landscape:

```text
7 relevant passages
4 supporting · 1 challenging · 2 unresolved
```

The purpose is *show me the evidence landscape*, not *vote on the claim*.

**This is a visual-epistemics requirement, not a copy one, so it belongs in component
tests.** If a later UI change renders 7 green against 2 red, an aggregate verdict has
been recreated visually even though the database deliberately contains none.

Cost note: the underlying results already exist in claim audit, alignment evidence and
report citations. The work is **keying** — they are stored per artifact, not per claim.

---

## 7. Epistemic copy lint

The most useful idea to come out of the review, and it came from the first response's
closing lesson rather than the original critique.

Guard tests can check that commands exist, that venues resolve, that every tab is
covered. They largely **cannot** detect prose that subtly overclaims — which is exactly
what happened: the walkthrough flattened nuanced behaviour into simpler language and
made the product look less rigorous than it is.

Ships as **coded warnings, not a banned-word list**, so contributors learn the
reasoning:

```text
EP001  "the field"
       Potential corpus-to-world overclaim. Confirm the metric is based on
       external literature rather than the active corpus.

EP002  "verified"
       Specify what was verified: existence, text match, entailment, metadata.

EP003  "no prior work exists"
       Prefer "no close prior work found in the sources searched."

EP004  "passed"
       Not for a check that did not run or does not apply.

EP005  "fake" / "fabricated" citation
       A catalogue miss is not fabrication.

EP006  "real open problem"
       Prefer "recurring stated gap".
```

Every rule has already been violated once — four of them by the walkthrough, before
review caught them.

**Advisory, with suppression.** These phrases are legitimate in context: "the field"
is correct when the statistic really does come from external catalogue results. A
linter that cannot be overridden gets satisfied by rewriting valid prose, which is
worse than not having it. Suppression must state a reason, so the exception is
reviewable:

```text
<!-- epistemic-lint: allow EP001
     reason: this count comes from complete OpenAlex results, not the corpus -->
```

---

## Declined

**Aggregate truth verdicts.** The original Evidence Ledger carried a corpus-wide
**Status** column. Aggregating `claim_audit`'s deliberately hedged per-passage
judgements into one authoritative label compresses uncertainty precisely where the
product's value is refusing to. Withdrawn by the reviewer once argued; the navigational
version in §6 is the accepted form.

**Invisible graph weighting from subjective quality labels.** Filtering by
include/exclude, core/peripheral, year, venue or type is useful. Turning a researcher's
priors into weighting *inside the graph algorithm* replaces a visible bias with a
hidden one.

**Forced sequential wizard.** The six phases are accepted as mental model, onboarding
and documentation structure — not as a workflow state machine. The tab model is a
strength, conceded implicitly by the argument that Ask and Compare are cross-cutting.

**Research Scope object — deferred, not rejected.** Ceremony until retrieval or
analysis consumes it. It becomes meaningful when the system can say *"this paper was
retrieved but falls outside your stated scope."*

---

## Documentation changes, done

| item | outcome |
|---|---|
| Ordering | Reader **9 → 5**, Timeline **10 → 7**, Gaps **11 → 8** |
| Ask / Compare / Report | regrouped as utilities, not stages |
| Open-web contradiction | replaced with two precise rules |
| Novelty presented as binary | renamed **Novelty screen**; four outcomes documented |
| Gaps "real open problem" | "recurring stated gap" + the status table |
| "field crowdedness" | corpus density |
| "verified quote" | defined as *text match*, distinguished from entailment |
| `82%` | `relevance 0.82` |

---

## Backlog

Ordered by **dependency**, not value. The correction that matters: *do not build
Submission Readiness before the Signal migration.* Built first it becomes an adapter
over `verified · suspect · ok · finding · skipped · unverified · coverage_pct` — a
translation layer written only to be deleted.

| # | work | why here |
|---|---|---|
| **done** | documentation fixes above | the bulk of round 1 |
| ~~1~~ | ~~Outcome model: `name` as proposition, measurements excluded~~ | **shipped** — `is_adverse` added; coverage stays a metric |
| ~~2~~ | ~~Provenance contract: `EvidenceRef` union, subject vs evidence~~ | **shipped** — `DocumentRef` · `CatalogueRef` · `VenueRuleRef` · `QueryRef` |
| ~~3~~ | ~~`NOT_APPLICABLE`, structured `reason`, formal status definitions~~ | **shipped** — plus `NEEDS_ATTENTION_STATUSES` and 3 invariants |
| ~~4~~ | ~~Migrate refcheck, statcheck, compliance, overlap~~ | **shipped** — `checker_signals.py`, additive adapters |
| ~~5~~ | ~~Canonical renderer~~ | **shipped** — `signalHelpers.js`; fixtures generated from the Python model |
| **6** | Epistemic-copy lint, advisory with suppression | stops docs and UI drifting back |
| **7** | Venue provenance + requirement tiers | highest-risk deterministic checker |
| **8** | UI wording: corpus density, text-match verified | quick wins, no dependencies |
| **9** | Discovery-depth indicator | improves interpretation of everything upstream |
| **10** | Submission Readiness | cheap after 3–5, expensive before |
| **11** | Direction-ranking dimensions, no composite score | useful, not foundational |
| **12** | Evidence Map | needs 2 for per-claim keying |
| later | Research Scope | only when retrieval consumes it |
| rejected | graph weighting · forced wizard · aggregate verdicts · domain outcome vocabularies | see Declined |

**Items 1–4 shipped** (3050 tests green). The envelope is settled in `signals.py` and
all four deterministic checkers now emit it via `checker_signals.py`, additively —
native shapes untouched, so nothing downstream changed.

Three things the migration surfaced, recorded because they were invisible in the
native shapes:

- **refcheck asks two questions and reported one status.** `suspect` means the work
  exists but the details disagree → `reference_exists` SUPPORTED plus
  `reference_details_match` CONTRADICTED.
- **compliance spelled two opposite facts "skipped."** A rule the venue does not have
  is `NOT_APPLICABLE`; a rule we could not evaluate is `NOT_CHECKED`. Unrecognised
  skip reasons default to needing attention.
- **Two states that looked clean are not.** statcheck with no parseable statistics and
  overlap with no other papers are both `NOT_APPLICABLE` — `is_clean` False,
  `needs_attention` False.

**Item 5 shipped** — `signalHelpers.js` (JS suite 1003 green). It consumes the flags
Python computes rather than re-deriving them, so the two cannot drift, and its
fixtures are serialised from real `Signal`s rather than hand-written.

**Known follow-up:** `claimAuditHelpers.js` still exists alongside it, because the
claim-audit endpoint emits its domain `outcome` vocabulary rather than a serialised
Signal. Two renderers is the thing being removed, so migrating that endpoint is the
next step — after which item 10 (Submission Readiness) is mostly `groupSignals()` plus
markup.

**Items 1–2 were schema decisions and had to precede migration.** An earlier ordering put
provenance at #9, after six checkers had already moved to the new envelope — which
would have meant migrating everything twice. Settle the shape first; individual
checkers may leave `evidence` empty at first.

Items 1–6 are the theme. None is a new research feature, and together they are worth
more than anything below them.

---

## Lessons

**A product can be honest and still be misrepresented by its own documentation.** The
early rounds were shaped by wording, not behaviour, and an expert reviewer reasonably
attributed the document's overclaims to the software. Four of six round-1 issues
dissolved on contact with the source.

**Verify before agreeing.** Accepting round 1 at face value would have produced work to
add a feature that already existed, restructure a UI that was not at fault, and build a
ledger that would have undermined the product's central principle.

**Consistency work outranks feature work.** The differentiator is the separation
between known, inferred, not found and not checked. It is modelled precisely in one
file and expressed ad hoc nearly everywhere else. Closing that gap is worth more than
any single feature on the list.

### The pattern underneath all of it: built, correct, unconnected

Four rounds of review looking for missing capability kept finding the same thing
instead — a capability that **exists, is well designed, and is wired to nothing**.

| capability | where it lives | what it is not connected to |
|---|---|---|
| epistemic state model | `signals.py` | 7 of 8 checkers |
| document provenance | `locator.py` | `signals.py` — never referenced |
| prompt versioning | `prompts.py` `*_prompt_sha256()` | the signals whose reproducibility depends on it |
| signal rendering | `claimAuditHelpers.js` | every surface except claim audit |
| graded novelty outcomes | `novelty_check.py` | the documentation, which described it as binary |
| gap status downgrade | gaps pipeline | the documentation, which called a theme "a real open problem" |

Six instances, found by reading source rather than by reasoning about the product.
None is a missing feature. Every one is a missing connection.

That explains why the backlog contains no new research capability and why it is
ordered the way it is. The components are good; what is absent is the wiring between
them, and — in two cases — between the software and its own description of itself.

The failure mode is specific and worth naming, because it is invisible from outside:
**a system can be architecturally coherent and still present as incoherent**, because
coherence lives in connections and users only ever see surfaces.
