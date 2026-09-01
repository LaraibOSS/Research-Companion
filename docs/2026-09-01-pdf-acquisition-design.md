# PDF acquisition — design

**Date:** 2026-09-01
**Status:** approved, not yet implemented
**Scope:** phase 1 (sections 1–4 + the alignment fix); phase 2 deferred and sized separately

---

## 1. The problem, and what it actually is

Papers were failing to download, in enough volume to threaten Brainstorm: a
discovery surface that finds papers you cannot then add is worse than no
discovery surface. The proposed remedy was a web crawler.

The failure data says otherwise. Across every workspace on disk, `failed.json`
holds 17 records, 12 distinct DOIs:

| | count |
|---|---|
| arXiv papers failed | **0** |
| DOI papers failed | **17** (all of them) |
| Publishers involved | ACM (`10.1145`) and IEEE (`10.1109`) — only these two |

Every recorded reason is the same string:

```
no PDF on disk for doi:10.1145/3732941
```

That string is false, in the specific sense that matters: it is not what went
wrong. Traced end to end:

1. `add_doi` (`fetch.py:238`) tries `doi.org` directly — fails.
2. **The OA locator runs and succeeds.** `oa_locator.py` chains
   s2 → unpaywall → openalex → arxiv and correctly returns
   `https://dl.acm.org/doi/pdf/10.1145/3732941`.
3. `_download_pdf` (`fetch.py:121`) requests it and receives **HTTP 403,
   `text/html`**. Verified directly against two of these URLs using the tool's
   exact `USER_AGENT`; adding a `mailto:` changes nothing.
4. `_try_download_pdf` (`fetch.py:160`) catches `HTTPStatusError`,
   `TimeoutException` and `FetchError` alike and returns `None`. **The status
   code does not survive.** 404, 403, timeout, DNS failure, HTML body and size
   cap all become the same value.
5. Metadata is saved; no PDF. Later `extract.py:133` raises
   `FileNotFoundError("no PDF on disk for …")`, caught by the catch-all at
   `lab/__init__.py:258` and recorded under `stage: "sections"`.

**Those ACM articles are open access.** ACM says so; OpenAlex says so. What
refused us is a bot filter, not a paywall. The error told the user a file was
missing when the truth was that the free file was found and the door was shut.

This is the third instance of the pattern recorded as §8 of
`WALKTHROUGH_REVIEW_RESPONSE.md` — *errors must name their own cause* — and the
most expensive one so far, because the misreport pointed at building an entire
subsystem that is not needed.

### 1.1 What the 12 failures actually are

Established by querying OpenAlex and Crossref, and by fetching the candidate
URLs directly:

| category | n | state | recoverable |
|---|:--:|---|---|
| ACM, open access, **403 to robots** | 5 | free to read | not by fetching harder |
| IEEE paywalled, **arXiv preprint exists** | 2 | `TAPAS`→`2501.02600`, `NeuPIMs`→`2403.00579` | **yes, automatically** |
| IEEE paywalled, no free copy anywhere | 5 | genuinely unavailable | only via the user's own access |

## 2. Non-goals

**No headless-browser or impersonating fetch of publisher PDFs.** Rejected on
three grounds, in order of weight:

1. ACM and IEEE terms explicitly prohibit automated downloading. Shipping it in
   an MIT-licensed tool aimed at academics makes the tool a liability inside the
   institutions it is for.
2. The realistic failure mode is an IP ban, which would break the arXiv path —
   the one that currently succeeds 100% of the time.
3. **It has the same ceiling as the approach we are taking.** 5 of the 12 papers
   have no free copy in existence. No browser conjures a file that is not there.
   Both approaches top out at 7 of 12; only one of them risks anything.

**No folder-first workflow.** Requiring users to pre-supply PDFs would break
Brainstorm, whose promise is finding papers you did not already have. A folder
lane exists here as an accelerant for the residue, never as the primary path.

## 3. Decisions taken

| # | decision | rationale |
|---|---|---|
| D1 | Recover what APIs legally can; hand the rest to the user's browser | The 403'd papers open fine for a person. Use the access the user already has rather than defeating a control. |
| D2 | Metadata-only papers become first-class and clearly marked | An unobtainable paper should contribute what its evidence supports, not vanish silently. **Phase 2.** |
| D3 | The download watcher is **armed by a click**, time-boxed | Narrowest exposure. Observation is tied to an action the user took, not running continuously over their downloads. |

## 4. Architecture

Four components. Components 1–2 know nothing about the UI; components 3–4 know
nothing about HTTP. `acquire.py` returns a value — it never records a failure,
never enqueues anything, never touches the store. That boundary is what makes
the network-facing half testable without a network.

```
┌─ 1. acquire.py ──────────────────────────────┐
│  one chain, one typed outcome                │
│  native → doi.org → index sweep (ranked)     │
│         → arXiv-by-title → PMC-by-title      │
│  returns Acquisition, never None             │
└──────────────────┬───────────────────────────┘
        got bytes  │  didn't
        ┌──────────┴──────────┐
        ▼                     ▼
┌────────────────┐  ┌─────────────────────────┐
│ normal ingest  │  │ 2. Acquisition outcome  │
│ (unchanged)    │  │    persisted + surfaced │
└────────────────┘  └───────────┬─────────────┘
                  human_can_help│  │ nothing to do
                   ┌────────────┘  └──────────┐
                   ▼                          ▼
      ┌─────────────────────────┐  ┌──────────────────────────┐
      │ 3. "Needs you" queue    │  │ 4. metadata-only papers   │
      │    + armed watcher      │  │    first-class (phase 2)  │
      └─────────────────────────┘  └──────────────────────────┘
```

## 5. Component 1 — the resolution chain (`acquire.py`)

Consolidates acquisition logic currently scattered across `add_arxiv`,
`add_doi` and `add_s2`, each of which has its own ad-hoc fallback.

**What happens to `fetch.py`.** The `add_*` functions stay and keep their
metadata responsibilities — parsing identifiers, calling Crossref / arXiv / S2 /
PubMed, writing `PaperMetadata`. What they hand off is the PDF: each one's
bespoke download-and-fallback block is replaced by a single
`acquire.acquire(meta) -> Acquisition` call. `add_paper`'s routing
(`fetch.py:557`) is unchanged, and `oa_locator.py` is absorbed into `acquire.py`
rather than kept alongside it, so there is one place that decides where a PDF
comes from. `_download_pdf` and its guardrails (SSRF validation, 50 MB cap,
redirect cap, magic-byte check) move across intact — they are correct and are
not what failed.

### 5.1 Host-class ranking

The core change. The locator today reads only `best_oa_location` — a single URL
chosen by OpenAlex for bibliographic quality, not for whether a robot may fetch
it. That is how it arrives at `dl.acm.org` and stops. Instead: collect **all**
candidate URLs, dedupe, and try them in host-class order.

| rank | class | rationale | examples |
|:--:|---|---|---|
| 1 | `native` | already works; never fails today | arXiv, PMC / EuropePMC |
| 2 | `repository` | exist to be harvested; robot-friendly | institutional repos, Zenodo, CORE, HAL |
| 3 | `preprint` | open by construction | bioRxiv, SSRN, OpenReview |
| 4 | `publisher` | most likely to refuse — last, not first | ACM, IEEE, Springer, Elsevier |

### 5.2 Source order

Stop as soon as bytes arrive.

1. **Native identifier** — arXiv PDF, PMC full text. Unchanged.
2. **`doi.org` direct** — cheap; occasionally redirects to a free PDF.
3. **Index sweep** — s2 `openAccessPdf`, Unpaywall `best_oa_location`, OpenAlex
   **`locations[]`** (all, not just `best_`). Collect → dedupe → rank → try.
4. **arXiv title search** — *new*. The existing arXiv provider
   (`oa_locator.py:168`) only fires when another service volunteers an arXiv ID,
   so it never finds a preprint by title. This step alone recovers `TAPAS` and
   `NeuPIMs`.
5. **PMC title search** — the same, for biomedical work.

### 5.3 Retry policy

There are no retries anywhere today (`fetch.py:121` has no loop), so a single
transient 503 permanently fails an add. Adding them, **the error class decides**:

- **Retry** — 3 attempts, exponential backoff with jitter, honour `Retry-After`:
  timeout, connection reset, `429`, `5xx`.
- **Never retry** — `403`, `404`, non-PDF body. These are definitive answers.
  Retrying a `403` is indistinguishable from an attack and is exactly how a
  host-level block becomes an IP-level one.

### 5.4 Rate limiting and politeness

No throttle exists on the add path, and citation auto-add fires
`_queue_add_paper` in a tight loop with zero spacing
(`lab_api.py:1808-1813`) — a 40-reference bibliography arrives at arXiv as a
burst. Add a **per-host token bucket**.

Put `contact_email` in the `User-Agent`. Verified not to move ACM, but it is the
documented etiquette for arXiv, Crossref, Unpaywall and OpenAlex, and is the
difference between being allowlisted and throttled.

### 5.5 Worked trace

```
10.1145/3676641.3716025  (TAPAS)
  native             — no arXiv/PMC id on record
  doi.org            — 403
  s2 openAccessPdf   — none
  unpaywall          — none
  openalex           — 1 location: dl.acm.org        [publisher, rank 4]
  → try dl.acm.org   — 403, definitive, no retry
  arXiv title search — "TAPAS: Thermal- and Power-Aware Scheduling…"
                       → arXiv 2501.02600            [native, rank 1]
  → fetch            — 200, %PDF-  ✓
```

Expected against the 12: **2 obtained**, **5 classified `BLOCKED_BY_HOST`**,
**5 classified `PAYWALLED`**. The chain's honest ceiling is 2; the other 10 are
components 3 and 4.

## 6. Component 2 — the typed outcome

```python
@dataclass(frozen=True)
class Acquisition:
    obtained: bool
    reason: AcquireReason | None      # None iff obtained
    attempts: tuple[Attempt, ...]     # every URL tried, in order
    source: EvidenceRef | None        # where the bytes came from

@dataclass(frozen=True)
class Attempt:
    url: str
    host_class: HostClass             # native | repository | preprint | publisher
    status: int | None                # HTTP status, or None if never reached
    outcome: str                      # "pdf" | "403" | "not-pdf" | "timeout" | …
```

### 6.1 The taxonomy

Six reasons, because six genuinely different situations currently share one
sentence.

| reason | what happened | who can fix it |
|---|---|---|
| `BLOCKED_BY_HOST` | a free copy exists; host refused a robot (403/429) | **the user, in their browser** |
| `PAYWALLED` | no free copy found; subscription required | the user, *if* they have access |
| `NO_LOCATION_FOUND` | no index knows of any copy | the user, if it is on disk |
| `SOURCE_UNAVAILABLE` | network/timeout, survived retries | the machine, later |
| `NOT_A_PDF` | HTML or junk where a PDF was promised | possibly the user |
| `NOT_ATTEMPTED` | no usable identifier | the user |

`human_can_help` is a **computed property on the Python object**, never derived
in JS — the same rule already established for `is_clean` / `needs_attention` in
`signalHelpers.js`. One source of truth for queue membership. Explicitly:

```python
human_can_help = reason is not SOURCE_UNAVAILABLE
```

`SOURCE_UNAVAILABLE` is the only reason the machine owns; everything else goes
to the queue. `PAYWALLED` **is included**: we cannot know whether a given user
has institutional access, and the honest move is to offer the action and let
them find out rather than decide on their behalf that they cannot.

### 6.2 Relationship to `signals.py`

`Acquisition` **borrows** the `Reason` vocabulary and the `EvidenceRef`
provenance types but is a **separate type**. A `Signal` asserts a proposition
about a paper; `Acquisition` records the outcome of an operation. Same
discipline, different noun. This deliberately avoids both a second vocabulary
and a category error.

### 6.3 Persistence

Additive, as `checker_signals.py` was. Records in `failed.json` grow an
`acquisition` block beside the existing `stage` / `error` / `paper_id` / `at` /
`oa_links` keys, so every current reader keeps working:

```json
{"stage": "add", "error": "...", "paper_id": "doi:10.1145/3732941",
 "at": "...Z", "oa_links": [...],
 "acquisition": {"reason": "blocked_by_host", "human_can_help": true,
                 "attempts": [...], "last_tried": "...Z"}}
```

### 6.4 Three holes closed here

1. **A failed add currently vanishes.** `_add_paper_task` never calls
   `record_failure` (`lab_api.py:1189-1202`) and the reducer discards the job
   status (`reducer.js:317`). After the toast fades there is no trace anywhere.
   This is why none of this was diagnosable from the UI.
2. **`add_arxiv` hard-raises** (`fetch.py:409`) — no metadata, no failure
   record, no Find-PDF affordance. It must degrade the way `add_doi` does.
3. **Re-adding never retries the PDF.** DOI and S2 short-circuit on metadata
   alone (`fetch.py:247`, `:340`), so a metadata-only paper cannot recover by
   being added again.

### 6.5 Copy

Every reason maps to a sentence naming the cause:

> **Open access — but ACM blocks automated downloads.**
> Your browser can fetch this. Tried 4 sources. `[ Open at publisher ↗ ]`

> **IEEE requires a subscription.** No free copy found in 5 sources.
> If you are on a university network, your browser may have access.
> `[ Open at publisher ↗ ]`

**The string "no PDF on disk" must never reach a user again.** It is the symptom,
observed three steps downstream of the cause.

## 7. Component 3 — the queue and the armed watcher

### 7.1 The queue is a filter, not a new tab

Library already has `All / Strong / Moderate / Weak / Unscored / Failed` chips.
Add **`Needs you`**, populated by `human_can_help`. Papers the machine will
retry itself never appear; neither do papers nothing can fix. One new chip and a
count in the existing badge — no new navigation.

### 7.2 Lifecycle

```
1. click [ Open at publisher ↗ ] on TAPAS
2. browser opens dl.acm.org           (the user's session, the user's access)
3. client → POST /api/acquire/arm { paper_ids: [TAPAS], ttl: 600 }
4. server polls downloads_dir for *.pdf created AFTER step 3
5. new file → identify → match?
     ├ matches TAPAS          → attach, ingest, disarm, SSE
     ├ matches another queued → attach to that one
     └ matches nothing        → report it, touch nothing
6. TTL expires → stop polling, forget
```

Arming is **additive**: clicking three papers puts all three in one window, and
each click extends it. That matches the real usage pattern — working the queue
in a burst.

**Which URL step 2 opens**, in order: the highest-ranked candidate from
`Acquisition.attempts` that a browser can use (for the ACM cases this is the
`dl.acm.org` URL that 403'd us — it opens fine for a person), else
`https://doi.org/<doi>`, else the paper's recorded `url`. When there is no URL
at all — `NOT_ATTEMPTED`, no identifier — the row shows the upload control only
and no "Open at publisher" button, since there is nowhere to send the user.

**Default TTL 10 minutes.** Publisher pages are slow and sometimes interpose a
login.

### 7.3 Identification — three tiers, cheapest first

All three already exist in the codebase.

1. **Filename** — `store.py:428-429` already extracts arXiv IDs and DOIs from
   names. Free. ACM names downloads `3732941.pdf`, which *is* the DOI suffix, so
   this tier often wins outright.
2. **Page-1 text** — `extract.ensure_text()` parses model-free; scan for the DOI
   or arXiv ID.
3. **Title match** — reuse `title_is_cited` from `refcheck/matching.py`, the
   longest-contiguous-run matcher already hardened on this exact class of
   problem (21 → 39 verified references on a real paper).

**A file matching nothing produces no action.** It reports *"caught
`report-2024.pdf` — doesn't match anything you're waiting for"* and leaves the
file untouched: not added, not moved, not deleted. Guessing here is how a
watcher becomes something the user disables.

### 7.4 Privacy invariants

Testable, not merely intended:

- Polls **only** while armed, with a visible countdown and a disarm control.
- Only files whose mtime is **after** the arming instant.
- Only `*.pdf`.
- Reads **page 1 only**, and only to extract identifiers.
- A file matching nothing is never copied, moved or ingested.
- Nothing leaves the machine.

### 7.5 Practical robustness

- Browsers write `foo.pdf.crdownload` / `.part` and rename on completion. Those
  extensions are ignored, and a file is only considered once its size is stable
  across two polls — otherwise a half-written PDF is claimed and recorded as a
  parse failure for a file that was fine.
- **No new dependency.** Polling one directory once a second for ten minutes is
  cheaper than `watchdog` and behaves identically on Windows, macOS and Linux.
- **The watcher is an accelerant, never a dependency.** If it cannot run —
  permissions, an unusual setup, a browser saving elsewhere — the existing
  upload button on the paper card still does the job. Nothing in the design
  assumes it works.

### 7.6 Configuration and CLI parity

One setting, `downloads_dir`, defaulting to the OS downloads folder; detected,
shown, editable.

`find-pdf` exists only in the Lab UI today — no CLI, no MCP tool. Add
`research-companion acquire <paper_id>` and `research-companion acquire --all`,
plus a queue listing. The watcher is inherently interactive and stays Lab-only.

## 8. Component 4 — metadata-only papers (phase 2)

Deferred. Recorded here so phase 1 does not foreclose it.

**One new property, `evidence_depth`** — orthogonal, computed in Python,
consumed by the UI, never re-derived there:

```
full_text  → the PDF was read; sections, quotes, offsets exist
abstract   → title + abstract + venue + year only
metadata   → title + venue + year
```

Principle: *let a paper contribute what its evidence supports, and label the
difference at every point of use.* An abstract is the authors' own statement of
their contribution. It cannot support a quote.

| surface | today | phase 2 |
|---|---|---|
| Graph | silently absent (`graph.py:91-94`) | node from abstract-derived concepts, visually distinct |
| Ask | silently absent (`qa.py:89-91`) | abstract retrievable; answer states *"2 papers contributed abstract only"* |
| Timeline | absent | present via abstract-derived concepts, marked |
| Coverage | works | unchanged |
| Reader | 404 | states *why*, offers the queue action |

Two rules to enforce:

1. **A citation to an abstract can never look like a citation to a section.**
   The product promise is "down to the paper *and section*". An abstract-derived
   citation has no section and no offsets; it must render differently and must
   not be clickable-to-passage. Getting this wrong quietly devalues every real
   citation.
2. **Counts must not conflate depths.** "Grounded in 6 sources across 2 papers"
   cannot silently include abstract-only sources on equal footing.

### 8.1 The alignment fix ships in phase 1

`alignment.py:252-256` catches the missing text, sets `cand_text = ""`, and asks
the model anyway — producing a confident stance and relevance score **from the
title alone**, with nothing in the payload marking it. That is the same failure
as `"no PDF on disk"`: an output indistinguishable from its siblings, resting on
far less.

Phase 1 behaviour: **score from the abstract when one exists, marked; refuse
when only a title exists.** Abstract-based alignment is defensible. Title-only
is not.

## 9. Testing

**The network layer is testable without a network.** `acquire.py` takes an
injected HTTP transport (`httpx.MockTransport`), making every path — 403, 429,
timeout, HTML-instead-of-PDF, oversized body, redirect chains — a table-driven
unit test. Host-class ranking and candidate dedup are pure functions.

**Four pinned invariants**, each a failure this project has already had:

1. **A 403 is never retried.** One assertion; the difference between a tool
   institutions can install and one that gets a campus IP blocked.
2. **No reason maps to "not found" wording unless nothing was found.** Mirroring
   `test_parser_failure_reporting.py`: walk every `AcquireReason` through the
   copy map and assert a `BLOCKED_BY_HOST` message contains none of *no PDF*,
   *not found*, *missing*. The fourth-instance guard.
3. **The watcher's privacy properties.** Not armed → zero reads. File older than
   the arming instant → ignored. Non-matching file → byte-identical and in place
   afterwards, asserted rather than assumed.
4. **Partial downloads.** `.crdownload` ignored; a growing file is not claimed
   until its size is stable.

**Matching is separated from polling** — tier 1/2/3 logic is a pure function
over `(filename, page1_text, queued_papers)`, tested with no filesystem. Only
the poll loop needs `tmp_path`.

**JS fixtures generated from the Python model**, as with `fixtures_signals.json`.
Hand-written fixtures have encoded assumed shapes four times in this project.

**Live verification against the real 12.** A script running the chain over those
DOIs, asserting the split: 2 obtained, 5 `BLOCKED_BY_HOST`, 5 `PAYWALLED`. Every
significant bug in this codebase was found by running on real data.

## 10. Phasing

**Phase 1** — sections 5, 6, 7, plus §8.1:

- `acquire.py`: chain, host-class ranking, title search, retry policy, rate limiting
- `Acquisition` type, taxonomy, `human_can_help`, additive persistence
- Three holes closed (add-failure recording, `add_arxiv` degradation, re-add retry)
- Honest copy for every reason
- `Needs you` filter, `POST /api/acquire/arm`, armed watcher, `downloads_dir`
- CLI parity: `research-companion acquire`
- Alignment refuses to score from a bare title

**Phase 2** — section 8, sized after the queue has been used. Its value depends
on how many papers remain stuck, which depends on institutional access. Building
the elaborate version first would be guessing.

## 11. Success criteria

- No user-facing message reports a symptom where a cause is known.
- The 12 known failures classify as 2 / 5 / 5, verified live.
- A transient 5xx no longer permanently fails an add.
- A `403` is never retried, verified by test.
- A queued paper is recoverable in one click plus one browser download.
- The watcher observes nothing while disarmed, verified by test.
- Brainstorm results that cannot be auto-fetched land in the queue rather than
  disappearing.
