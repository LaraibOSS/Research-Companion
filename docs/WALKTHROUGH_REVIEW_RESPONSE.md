# Review response — the walkthrough as a research workflow

A decision record. An external reviewer read [`WALKTHROUGH.md`](WALKTHROUGH.md) as a
research workflow rather than as documentation, rated the feature set ~8.5/10 and the
end-to-end flow ~6.5–7/10, and proposed a restructure into six phases plus a set of
wording and feature changes.

This records what was verified, what was accepted, what was declined, and why.

---

## Verdict

**The review is high quality and largely correct — but it misattributes most of the
problem. A substantial share of it is a review of the documentation, not the
software.**

The reviewer's own closing line is the accurate diagnosis:

> the technical architecture appears more coherent than the user journey currently
> communicates

What they could not see, without code access, is how much of that incoherence the
walkthrough itself introduced. In four places the shipped product is **more**
epistemically careful than the document made it look.

The correct response was therefore mostly to fix the documentation, not to
restructure working code.

---

## Method

Every claim that could be checked against the source was checked before being
accepted or rejected. The reviewer had only the document; the point of this pass was
to establish which criticisms survive contact with the implementation.

| review claim | verdict from source | evidence |
|---|---|---|
| "Does novelty only search my library?" | **No — it searches externally** | `novelty_check.py` calls `discover.search_topic_with_fallback` (Semantic Scholar / OpenAlex / arXiv) |
| "Stop using binary Novel / Not Novel" | **Already graded** | `_VERDICTS = {novel, incremental, overlaps, anticipated}` |
| "Venue rules need year versioning" | **Confirmed gap** | `venues.json` has no `year`, `updated`, or `source` field |
| "Say corpus density, not field crowdedness" | **Product overclaims too** | `helpContent.js`: "where the field clusters" |
| "Soften Gaps' *real open problem*" | **Product already careful** | statuses `open / partially / addressed`; `addressed + unverified` is downgraded to `partially` |
| "82% reads as confidence" | **Product already labels it** | Report caption: "Relevance & stance are AI judgements — not independently verified" |

---

## A. Correct, and the product needs changing

**Venue-year versioning.** Confirmed. A desk-reject checker is only as trustworthy
as the vintage of its rules, and nothing in the knowledge base records which year a
venue's requirements were captured or when they were last checked. Conference rules
change annually. This is the most concrete product gap the review found.

**"Field clusters" in the graph help text.** Six quantisation papers make
quantisation look dominant regardless of the actual literature. The measurement is
corpus density; the wording says field.

**"Verified quote."** The product has a *separate feature* — claim audit — for
whether a source supports a claim. Naming the verbatim-match check "verified"
collapses the exact distinction that feature exists to preserve.

**GRIM applicability.** GRIM applies to means of bounded integer items and rarely to
ML results. "Not applicable" and "passed" must not be rendered alike.

**Consolidated Submission Readiness.** Five integrity signals already exist and
currently end in five separate places. Consolidating them gives the pipeline an
ending. Accepted as a real addition.

---

## B. Correct, but the document was the problem

These were fixed in the documentation. No code changed.

**The open-web contradiction — the reviewer's best catch, and a genuine error.**

The walkthrough asserted:

> It does not read the open web. Every answer comes from your library.

and separately described novelty checking against "real prior work". The reviewer
spotted the contradiction and asked which was true.

**The absolute was wrong.** Novelty deliberately queries public catalogues, because
screening novelty against only the papers the researcher already chose would be
circular. A correct design was flattened into a false rule, and the reviewer then had
to reason about a contradiction that did not exist in the product.

Replaced with two precise statements:

- nothing is answered from model memory; every claim traces to a document
- Ask, Compare, Report, Gaps and draft alignment read **only** the library —
  discovery, novelty and reference checking query public catalogues

**Novelty presented as binary.** The document mentioned only "a novel verdict",
implying yes/no. The product already grades four outcomes. The document undersold it.

**Gaps overclaimed.** The document said a theme repeated by six papers "is a real
open problem". Six papers can name a limitation a seventh has since solved. The
product already tracks `open / partially / addressed` — the document mentioned the
flags, then wrote a sentence that ignored them.

**Percentages read as confidence.** `82%` is a retrieval relevance score, not a
probability that a paper supports you. The Report tab already says so on screen; the
document did not.

**Ordering.** The document numbered 19 steps in an order that put Reader at 9,
Timeline at 10 and Gaps at 11 — after a direction had been chosen and a draft begun.
The Directions diagram in the same document showed *gaps feeding directions*. That
was the clearest inconsistency in the walkthrough, and it was purely a narrative
artifact: the Lab is tabbed, and nothing in the product enforces an order.

---

## C. Declined

**The Evidence Ledger.** The reviewer's flagship new feature, and the one thing here
worth arguing about.

Proposed shape:

| Claim | Sources | Supporting | Contradicting | Status |
|---|---|---|---|---|
| KV compression reduces memory | 7 | 6 | 1 | **Supported** |

Deciding that one passage supports one claim is exactly what `claim_audit` does — at
a single anchored passage, with an explicit bias toward "unclear", because at
realistic miscitation rates a confident-but-noisy checker gets ignored and takes the
real findings down with it.

Aggregating those deliberately hedged judgements into a corpus-wide **Status**
multiplies the uncertainty and then renders the result as the most authoritative
-looking object in the product. It would contradict the philosophy the review spends
a page praising.

A ledger of *"this claim is mentioned by 7 papers, here they are"* — no verdict
column — is defensible and cheap. The verdict column is not.

**Research Scope object.** A container that only pays off once downstream modules
consume it. Ceremony until then; deferred rather than rejected.

**Weighting the graph by user quality labels.** Labels for *filtering* are fine.
Turning a researcher's priors into invisible weighting math replaces one bias with a
less visible one.

**Six phases as a forced wizard.** Accepted as documentation structure and
information architecture; rejected as enforced product flow. The tab model is a
strength, which the review implicitly concedes when it argues Ask and Compare are
cross-cutting utilities rather than stages.

---

## Changes made

Documentation only. `WALKTHROUGH.md` restructured into six phases with 17 steps and a
separate utilities group.

| change | effect |
|---|---|
| Reader moved **Step 9 → Step 5** | the researcher inspects what was extracted *before* anything derives from it |
| Gaps moved **Step 11 → Step 8** | gaps now precede directions, matching how the product actually computes them |
| Timeline moved **Step 10 → Step 7** | structure of the field, then its evolution, then its open problems |
| Ask / Compare / Report / skills | regrouped as **anytime utilities**, not chronological stages |
| Novelty renamed **Novelty screen** | states it searches externally, lists all four graded outcomes |
| Open-web rule | replaced with two precise, correct statements |
| Graph section | corpus density, with the six-quantisation-papers illustration |
| Gaps section | "recurring stated gap" plus the status table already in the product |
| Alignment section | "verified" defined as *text match*, distinguished from entailment |
| Relevance figures | `relevance 0.82`, not `82%` |
| Journey diagram | rebuilt around phases; utilities beside the pipeline, which also resolves the reviewer's "diagram skips steps" note |

Validation: 17 steps, no dangling cross-references, no broken anchors, 23 guard tests
passing, PDF rebuilt with all 9 diagrams.

---

## Remaining, in priority order

| priority | item | why |
|---|---|---|
| **P1** | Venue-year versioning + visible "rules updated" date | a deterministic check is only as reliable as its rule vintage |
| **P1** | statcheck: applicable / not applicable / could not parse / passed / failed | GRIM rarely applies to ML; silence must not read as a pass |
| **P1** | "Corpus density" wording in `helpContent.js` | the product makes the same overclaim the document did |
| **P1** | Rename "verified quote" in the UI | preserves the distinction claim audit exists for |
| **P2** | Submission Readiness dashboard | gives the pipeline a single ending |
| **P2** | Corpus coverage indicator (exploratory / broad / systematic) | every downstream signal inherits corpus bias |
| **P3** | Multi-dimensional direction ranking | more defensible than one opaque score |
| **—** | Evidence ledger, scope object, graph weighting | declined or deferred, see section C |

---

## The general lesson

The review found four places where the documentation was less careful than the code.
That is a specific failure mode worth naming: **a product can be honest and still be
misrepresented by its own documentation**, and readers — including expert reviewers —
will attribute the documentation's overclaims to the product.

The walkthrough's guard tests now check that commands and venues exist, that every
tab is covered, and that the not-checked and not-fabricated rules survive edits. They
do not, and largely cannot, check that a sentence overclaims. That remains a review
question, which is the argument for having had this one.
