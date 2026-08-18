---
name: submission-check
description: "Use when someone asks whether a paper is ready to submit, will get desk-rejected, meets a venue's formatting or section requirements, or whether its reported statistics are internally consistent. Runs Research Companion's deterministic pre-submission checks (venue compliance, statcheck/GRIM, self-overlap) on a PDF and reports findings by severity. No LLM calls, no cost."
---

# /submission-check

Answer one question about a paper: **would this get desk-rejected?**

Runs three deterministic checks and reports what a program editor would catch before a reviewer ever sees it. No model calls, no API cost, nothing sent off-machine.

## Usage

```
/submission-check <paper.pdf> --venue neurips        # full check against a venue
/submission-check <paper.pdf>                        # stats + overlap only (no venue rules)
/submission-check <paper.pdf> --venue icml --workspace my-research
                                                     # compare overlap against a real library
/submission-check --venues                           # list supported venues
```

## What it checks

| check | what it catches | cost |
|---|---|---|
| **venue compliance** | page limit, abstract length, required sections (limitations, broader impact, ethics, reproducibility, funding) | free |
| **statcheck + GRIM** | reported p-values that don't match their test statistic; means impossible for the stated sample size | free |
| **self-overlap** | passages near-duplicating another paper in the library (self-plagiarism / dual submission) | free |

## What it does NOT check

Say this plainly in the output. It does not read the science, judge novelty, check citations exist (that is `refcheck`), verify claims against sources, or check figures, tables, or the reference-list format. A clean result means *no desk-reject trigger was detected by these three checks* — not that the paper is good or that it will be accepted.

## Supported venues

`neurips` `icml` `iclr` `aaai` `acl` `emnlp` `cvpr` `kdd` `sigir` `nature` `science` `pnas` `nature-medicine` `nature-physics` `the-lancet` `bioinformatics` `prl` `psych-science` `aer`

If the user names a venue not in this list, say so and offer the closest match — do not silently substitute one.

## Workspace safety — read before running anything

Research Companion writes to a **global** store with named workspaces, not to the current folder. Adding a paper into whichever workspace happens to be active would pollute the user's real research.

**Every command below must set `RESEARCH_COMPANION_WORKSPACE` inline**, so the user's active workspace is never touched:

```bash
RESEARCH_COMPANION_WORKSPACE=submission-scratch research-companion <cmd> ...
```

PowerShell has no inline env-var prefix — use the Bash tool for these commands, or set `$env:RESEARCH_COMPANION_WORKSPACE` and restore it afterwards.

Only use a different workspace when the user explicitly passes `--workspace <name>`, which they would do to make the overlap check meaningful (see Step 4).

## What You Must Do When Invoked

If invoked with `--venues` and nothing else, print the venue list above and stop.

If no PDF path was given, ask for one. Do not guess a file.

### Step 1 — add the paper to the scratch workspace

```bash
RESEARCH_COMPANION_WORKSPACE=submission-scratch research-companion add "<path/to/paper.pdf>"
```

Capture the printed paper id (`local:xxxxxxxxxxxx`). Every later command needs it. If `add` fails, stop and report the error — do not continue with a guessed id.

### Step 2 — know what to expect (extraction is automatic)

Text extraction happens automatically on the first check that needs it — a local parse, no model, no network. Two things to expect:

**The first check can take 20–60 seconds** while the parser loads OCR models, and prints to stderr:

```
research-companion: extracting text from local:xxxx (local parse, no model calls)...
```

Tell the user it is working rather than letting it look hung.

**Expect harmless noise on stderr.** The OCR stack prints `[INFO] ... RapidOCR ...` lines and often `AttributeError: 'MessageFactory' object has no attribute 'GetPrototype'` (a protobuf mismatch inside a dependency). **These are not failures.** Judge success by the exit code and by valid JSON on stdout — never by the presence of the word "Error" in stderr.

If a check reports `no text for <id> and none could be extracted`, the PDF is a scan or is unreadable. Say so plainly: the stats and overlap checks are then *not checked*, not clean.

### Step 3 — the checks

Run both, with `--json` so you parse structure rather than prose.

**3a. Venue compliance** (only if `--venue` was given). Works immediately after `add` — it reads the PDF directly:

```bash
RESEARCH_COMPANION_WORKSPACE=submission-scratch research-companion check-compliance "<PAPER_ID>" --venue <venue> --json
```

Each entry has `check`, `status` (`ok` / `finding` / `skipped`), `severity` (`desk_reject` / lower / null), `message`, `detail`.

**`skipped` is not `ok`.** A skipped check ran nothing and must appear under NOT CHECKED in the report, never under CLEAN. Two skips are normal and expected here:

- `abstract_word_limit` — that venue publishes no abstract limit. Genuinely nothing to check; say so.
- `citation_completeness` — needs `research-companion build`, which **costs model calls**. Do not run it as part of this skill. Report it as not checked, and mention it is available if the user wants to pay for it.

**3b. Statistics** (triggers extraction on first run — see Step 2):

```bash
RESEARCH_COMPANION_WORKSPACE=submission-scratch research-companion check-stats "<PAPER_ID>" --json
```

Returns `findings[]` and a `summary` with `n_tests`, `n_inconsistent`, `n_decision_inconsistent`, `n_means`, `n_impossible_means`.

`n_tests: 0` with `"no parseable statistics found"` means **nothing was checked** — not that the statistics are fine. Report it that way. This is the single most likely thing to be misread as a pass.

### Step 4 — overlap (know what it can and cannot tell you)

```bash
RESEARCH_COMPANION_WORKSPACE=submission-scratch research-companion check-overlap "<PAPER_ID>" --json
```

In a fresh scratch workspace this **always** returns `"no other library papers to compare against"`, because there is nothing to compare with. That is not a pass. Report it as *not checked*, and tell the user how to make it real:

> Overlap was not checked — the scratch workspace has no other papers. To check against your own library, re-run with `--workspace <your-research-name>`.

List their workspaces with `research-companion workspace list` if they ask which to use.

Never add their paper into a real workspace without them asking for it via `--workspace`.

### Step 5 — report

Lead with a one-line verdict, then findings **ordered by severity, worst first**. Suggested shape:

```
Submission check — <paper title> vs <venue>

BLOCKING (desk-reject risk)
  ✗ No limitations section — NeurIPS requires one of: limitations

WORTH FIXING
  ⚠ Abstract is 312 words (limit 250)

CHECKED, CLEAN
  ✓ 9 pages, within the 9-page limit
  ✓ 14 statistical tests, all internally consistent

NOT CHECKED
  – Self-overlap: no other papers in the scratch workspace
  – Citation completeness: needs `build` (costs model calls)
  – Abstract length: NeurIPS publishes no abstract word limit
  – Citations exist: run refcheck separately
```

Rules for the report:

- **Never present "not checked" as "clean."** Keep the two groups visually separate. A skipped check that reads as a pass is worse than no check at all.
- If there are zero blocking findings, say so directly — do not hedge a clean result into sounding risky.
- Quote the venue rule (`detail`) for each blocking finding, so the user can act without looking it up.
- Say what was not covered (novelty, citations, figures, reference formatting) in one closing line.

## Cleanup

The scratch workspace persists, which makes re-checking the same paper fast. If the user wants it gone:

```bash
research-companion workspace remove submission-scratch
```

Do not remove it automatically.
