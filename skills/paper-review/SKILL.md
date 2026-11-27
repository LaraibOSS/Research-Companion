---
name: paper-review
description: "Use when someone asks what a reviewer would say about their draft, wants a pre-submission review of their own paper, asks whether a draft is ready to submit and wants more than formatting checks (references, statistics, reproducibility, declarations, related work), or asks for a readiness verdict. Runs Research Companion's review team on a PDF. The fast review makes no model calls but needs a one-time paid extraction; the full review makes paid model calls and runs only when the user agrees."
---

# /paper-review

Answer one question: **what would a reviewer flag in this draft?**

Runs Research Companion's review team on a paper and reports one readiness verdict — **ready / revise / not ready / not assessed** — with the findings behind it and, just as important, the list of checks that did not run or had nothing to examine.

## Usage

```
/paper-review <paper.pdf>                       # fast review (default)
/paper-review <paper.pdf> --venue neurips       # also check that venue's rules
/paper-review <paper.pdf> --full                # full review: paid model calls, asks first
/paper-review <paper_id>                        # a paper already in the scratch workspace
```

`--full` is a skill argument, not a CLI flag: it means running `review` **without** `--fast`.

## The two rules

These are the project's core promise. Follow them in every report.

- **A check that did not run is never presented as a pass.** A review lane that failed, was not run, or had nothing to examine appears under NOT CHECKED, never under clean. "Ready" is only ever "ready on the checks that ran", and you list the ones that did not.
- **Something not found is never called fabricated.** The reference lane reports references it could not find in public catalogues. Real books, theses and recent preprints land there routinely. Say "could not be found — check by hand", never "fake" or "fabricated".

## What it costs — say this before running anything

| step | what it does | cost |
|---|---|---|
| `add` | stores the PDF | free |
| `build` | extracts the paper's claims, methods and reference list with a model. **The review cannot start without it.** Needed once per paper; later runs reuse it. | **paid** — one model call per paper not yet extracted. Run `cost-estimate` first. |
| `review --fast` | references (looked up online), related work search (online), statistics, reproducibility, declarations, self-overlap | free — no model calls (network lookups only) |
| `review --fast --venue <v>` | adds the venue's formatting rules (free) **and a venue-fit judgement that calls the model once** | **one paid model call** |
| `review` (full, no `--fast`) | adds novelty against related work, how each citation is used, related-work themes, benchmark suggestions, confidence and severity ranking | **paid** — several model calls |

So the honest summary for the user is: **the fast review is free once the paper has been extracted, and the extraction itself is a small paid step.** Never run `build`, the full review, or `--venue` with `review` without the user agreeing to the cost. Each needs a model key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) set in their environment — do not print its value.

If the user wants venue rules without any model call, run the free `check-compliance` command instead (the `/submission-check` skill does this).

## Workspace safety

Research Companion writes to a **global** store with named workspaces, not the current folder. The review saves its report into the workspace. Set the workspace inline on every command:

```bash
RESEARCH_COMPANION_WORKSPACE=review-scratch research-companion <cmd> ...
```

PowerShell has no inline env-var prefix — use the Bash tool, or set `$env:RESEARCH_COMPANION_WORKSPACE` and restore it afterwards. Only use a different workspace if the user explicitly names one (they might, to make the self-overlap check compare against their own library).

## What You Must Do When Invoked

If no PDF or paper id was given, ask. Do not guess a file.

### Step 1 — add the paper (skip if a paper id was given)

```bash
RESEARCH_COMPANION_WORKSPACE=review-scratch research-companion add "<path/to/paper.pdf>"
```

Capture the printed id (`local:xxxxxxxxxxxx`). If `add` fails, stop and report it.

### Step 2 — the one-time extraction (paid: ask first)

See what it will cost:

```bash
RESEARCH_COMPANION_WORKSPACE=review-scratch research-companion cost-estimate
```

It prints `Already cached` and `Needing extraction` counts and an `Estimated cost`. If `Needing extraction` is 0, skip to Step 3 — nothing will be charged. Otherwise tell the user the estimate and ask. Only after a yes:

```bash
RESEARCH_COMPANION_WORKSPACE=review-scratch research-companion build
```

`build` extracts **every** un-extracted paper in the workspace, not only this one — another reason to keep to the scratch workspace. If the user says no, stop: the review cannot run, and that is the report ("not reviewed — needs a one-time extraction"). Point them to `/submission-check` and `/refcheck`, which need no extraction.

### Step 3 — run the review

Default, free once extracted:

```bash
RESEARCH_COMPANION_WORKSPACE=review-scratch research-companion review "<PAPER_ID>" --fast --json
```

Options that exist (use only these): `--venue <slug>` (adds one model call, see the cost table), `--connectors europepmc,pubmed,dblp` (extra catalogues for the reference lane; use `europepmc` for biomedical papers), `--report <dir>` (also writes `report.html` and `report.json` there), `--provider anthropic|openai` and `--model <name>` (choose the model for paid lanes). Do not use `--serve` from a skill; it starts a web server that blocks.

Run the **full** review (drop `--fast`) only when the user has asked for it after hearing that it makes paid model calls.

Expect a minute or more: references and related work are looked up online one by one.

**Exit code 1 is not "the review crashed".** It means at least one lane failed; the JSON is still printed on stdout. Read it.

### Step 4 — read the output

```json
{
  "paper_id": "local:...",
  "title": "...",
  "lanes": {
    "citation": {"ok": true, "error": "", "data": {"counts": {"verified": 30, "suspect": 1, "unverified": 3}, "references": ["..."]}},
    "overlap":  {"ok": true, "error": "", "data": {}},
    "ingest":   {"ok": false, "error": "no extraction for local:...; run `research-companion build` first", "data": {}}
  },
  "generated_by": "research-companion",
  "readiness": {
    "verdict": "revise",
    "summary": "Revise — 2 item(s) to review, no hard blockers; overlap: no other papers to compare against; venue/compliance checks not run — pass --venue; novelty lane not run — remove --fast",
    "blockers": [{"lane": "compliance", "severity": "blocker", "title": "...", "action": "..."}],
    "warnings": [{"lane": "citation", "severity": "warning", "title": "3 reference(s) unverified or suspect", "action": "Verify or correct these citations."}],
    "coverage": {
      "ran": ["citation", "statsoundness", "reproducibility", "ethics"],
      "not_run": ["compliance", "novelty", "venuefit"],
      "failed": [],
      "nothing_checked": {"overlap": "no other papers to compare against"}
    }
  }
}
```

**The readiness verdict:**

| verdict | means |
|---|---|
| `not_ready` | at least one blocker — a venue rule that causes desk rejection |
| `revise` | warnings to review, no blockers |
| `ready` | the checks listed in `coverage.ran` found nothing to fix — **and only those** |
| `not_assessed` | every check that returned had nothing to examine (no references parsed, no statistics found, no venue rule applied). Nothing was established. |

**`coverage` is the denominator. Read all four parts:**

- `ran` — checks that examined something. Only these support the verdict.
- `not_run` — checks that were not part of this run. Under `--fast`, `novelty` is always here; without `--venue`, `compliance` and `venuefit` are.
- `failed` — checks that errored. Their findings are **not** in the verdict. Look up `lanes.<name>.error` for the reason (often a network failure for `citation`).
- `nothing_checked` — checks that ran but had nothing to look at, each with the reason. In a scratch workspace, `overlap` is always here: there are no other papers to compare against.

**No `readiness` block at all** means nothing assessable ran — usually because `ingest` failed (`no extraction for ...; run research-companion build first`), and every other lane then reports `dependency failed: ingest`. Report it as **not reviewed**, and go back to Step 2.

### Step 5 — report

Lead with the verdict **and its denominator in the same line**. Suggested shape:

```
Review — <paper title>
REVISE · based on 4 checks that ran (references, statistics, reproducibility, declarations)

TO REVIEW
  ⚠ [citation] 3 reference(s) unverified or suspect — verify or correct these citations
       (not found is not proof of fabrication: check them by hand)
  ⚠ [reproducibility] Weak reproducibility (low level or no availability statement)
       — add code/data links and an availability statement

NOT CHECKED
  – Self-overlap: no other papers to compare against
  – Venue rules: not run — re-run with --venue (adds one model call) or use /submission-check
  – Novelty against related work: not run — part of the full review (paid)
```

Rules:

- **Never report "ready" on its own.** Always "ready, based on the N checks that ran", followed by the NOT CHECKED list.
- If `verdict` is `ready` but `coverage.nothing_checked` or `coverage.failed` is non-empty, say plainly that those checks established nothing. A review whose only "clean" lanes examined nothing is not a clean review.
- **`not_assessed` is not a pass.** Say "not assessed — the checks that ran had nothing to examine", and list why from `nothing_checked`.
- Blockers first, quoted with their `action`. If there are none, say so directly.
- For the reference lane, use the same wording as `/refcheck`: unverified means "could not be found", never fake.
- If `readiness.narrative` is present (an opt-in setting, full review only), it is a model-written summary of the same items — label it as such, and never let it override the computed verdict.

## What this does NOT check

Say it in one closing line. It does not judge whether the science is right, whether the experiments support the claims, or whether the writing is clear. It is a pre-submission screen for things a reviewer or editor would catch mechanically, not a substitute for a human reviewer.

## Cleanup

The scratch workspace keeps the extraction, so re-reviewing after edits is free if the PDF is the same. Remove it only if asked:

```bash
research-companion workspace remove review-scratch
```
