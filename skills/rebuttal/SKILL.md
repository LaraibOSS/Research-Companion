---
name: rebuttal
description: "Use when someone has received peer reviews and wants help answering them: drafting a rebuttal or author response, replying to reviewer comments point by point, or planning revisions from reviews. Splits the reviews into individual concerns for free, then drafts a reply to each one grounded in quotes from the paper and checks that every quote really appears in it. Drafting makes paid model calls and runs only when the user agrees."
---

# /rebuttal

Answer one question: **how do I answer these reviews?**

Splits the reviewers' comments into individual concerns, then drafts a reply to each one, grounded in passages from the paper, with a list of planned revisions. Every quotation in a draft reply is checked against the paper's own text.

**The drafts are drafts.** They are a starting point for the author to verify, correct and rewrite — never a response to send as-is. Say this in every report.

## What it costs — say this before running anything

| step | what it does | cost |
|---|---|---|
| splitting the reviews (`--emit-segments`) | breaks the review text into one concern per item | free — no model, no network |
| `build` | the one-time extraction the drafting step needs. Needed once per paper. | **paid** — run `cost-estimate` first |
| drafting (`--segments` or `--reviews` without `--emit-segments`) | classifies each concern and drafts a reply | **paid** — up to two model calls per concern (one to classify it, one to draft the reply). Setting a concern's `kind` yourself skips the classify call. |

So 12 concerns means up to 24 model calls. Tell the user the number of concerns and that each costs up to two calls **before** drafting, and wait for a yes. Drafting needs a model key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) set in their environment — do not print its value. If they say no, the free segmentation is still useful on its own: it is a clean, numbered list of what each reviewer asked.

## The two rules

These are the project's core promise. Follow them in every report.

- **A check that did not run is never presented as a pass.** A reply whose quotes were not all found in the paper is reported as *quotes not confirmed*, and a reply that quotes nothing is reported as *no quotes to check* (not checked) — never as verified.
- **Something not found is never called fabricated.** A quote that could not be matched in the extracted text may be a paraphrase, a line broken across a page, or text inside a table or figure the parser did not read. Say "could not be found in the paper's text — check it", never "the model made this up".

## Workspace safety

Research Companion writes to a **global** store with named workspaces, not the current folder. Set the workspace inline on every command:

```bash
RESEARCH_COMPANION_WORKSPACE=rebuttal-scratch research-companion <cmd> ...
```

PowerShell has no inline env-var prefix — use the Bash tool, or set `$env:RESEARCH_COMPANION_WORKSPACE` and restore it afterwards. Only use a different workspace if the user explicitly names one that already holds their paper.

## What You Must Do When Invoked

You need two things: the paper (a PDF or a paper id) and the reviews. If the reviews were pasted into the conversation, save them to a plain text file first. If either is missing, ask. Do not guess a file.

### Step 1 — add the paper (skip if a paper id was given)

```bash
RESEARCH_COMPANION_WORKSPACE=rebuttal-scratch research-companion add "<path/to/paper.pdf>"
```

Capture the printed id (`local:xxxxxxxxxxxx`). If `add` fails, stop and report it.

### Step 2 — split the reviews (free)

```bash
RESEARCH_COMPANION_WORKSPACE=rebuttal-scratch research-companion rebuttal "<PAPER_ID>" --reviews "<reviews.txt>" --emit-segments "<segments.json>"
```

This makes no model call. It prints `wrote N segment(s) to <segments.json>` and writes a list like:

```json
[
  {"concern_id": "R1.1", "reviewer": "R1", "text": "The evaluation uses only one dataset, ...", "kind": ""},
  {"concern_id": "R2.1", "reviewer": "R2", "text": "The statistical test used for Table 2 is not stated ...", "kind": ""}
]
```

Splitting is by simple rules: a line starting `Reviewer 1` / `R1:` starts a new reviewer, and numbered or bulleted items and blank lines separate concerns. Show the user the list and ask them to check it — two concerns run together, or one split in half, is common with free-form reviews. Fix the file if they ask (merge, split, delete, or reword items).

Optionally set `kind` on a concern to one of `factual_error`, `misunderstanding`, `valid_weakness`, `clarification`. A concern whose `kind` is set skips the classify call. Any other value is ignored and the concern is classified by the model.

### Step 3 — the one-time extraction (paid: ask first)

```bash
RESEARCH_COMPANION_WORKSPACE=rebuttal-scratch research-companion cost-estimate
```

If `Needing extraction` is 0, nothing will be charged; go on. Otherwise tell the user the estimate, ask, and only after a yes:

```bash
RESEARCH_COMPANION_WORKSPACE=rebuttal-scratch research-companion build
```

### Step 4 — draft the replies (paid: ask first)

Tell the user: N concerns, up to 2 model calls each. After a yes:

```bash
RESEARCH_COMPANION_WORKSPACE=rebuttal-scratch research-companion rebuttal "<PAPER_ID>" --segments "<segments.json>" --tone balanced --json
```

Options that exist (use only these): `--tone deferential|balanced|firm` (default `balanced`; ask which the user wants if they have a preference), `--provider anthropic|openai`, `--model <name>`. `--reviews <file>` without `--emit-segments` drafts straight from the raw reviews, skipping the user's check of the split — prefer `--segments`.

**If it fails:**

- `rebuttal failed: dependency failed: ingest` — the paper has not been extracted. Go back to Step 3.
- `rebuttal failed: rebuttal: LLM returned invalid JSON for ...` — the model's answer could not be read. Nothing was drafted; report it as *not drafted*, and offer to retry.
- `rebuttal failed: no concerns found in reviews` — the reviews file had nothing the splitter recognised.

### Step 5 — read the output

```json
{
  "drafts": [
    {
      "concern_id": "R1.1",
      "reply": "We thank the reviewer. As stated in Section 4, \"we evaluate on ...\" ...",
      "cited_passages": [{"location": "...", "text": "...", "score": 0.42}],
      "verified": true,
      "unverified_spans": [],
      "planned_revision": "Add a second dataset to Section 5.",
      "evidence_status": "verified"
    }
  ],
  "changelog": ["Add a second dataset to Section 5."],
  "groups": [["R1.1"], ["R1.2", "R2.3"]],
  "concerns": [{"concern_id": "R1.1", "reviewer": "R1", "text": "...", "kind": "valid_weakness"}]
}
```

**Read `evidence_status`, not `verified`.** `verified` is also `true` when a reply quotes nothing at all, because there was nothing to contradict.

| `evidence_status` | means |
|---|---|
| `verified` | every quotation in the reply (15 characters or longer) was found in the paper's text |
| `unverified` | at least one quotation was **not** found; those are listed in `unverified_spans` |
| `no_quotes` | the reply quotes nothing from the paper, so nothing could be checked |

`verified` means *the quoted words are in the paper*. It does **not** mean the reply is correct, that the quote supports the argument, or that the planned revision is adequate. That judgement is the author's.

- `kind` on each concern — how it was classified (`factual_error`, `misunderstanding`, `valid_weakness`, `clarification`). It is a model's judgement; the author may disagree.
- `groups` — concerns that look alike (by wording), so one answer may cover several.
- `changelog` — the distinct planned revisions, which becomes the author's to-do list.

### Step 6 — report

Suggested shape:

```
Rebuttal drafts — <paper title>
5 concerns from 2 reviewers · 3 quotes confirmed · 1 not confirmed · 1 quotes nothing
These are DRAFTS for you to check and rewrite — not a response to send.

R1.1 (valid weakness) — quotes confirmed in the paper
  <reply>
  Planned revision: <planned_revision>

R1.2 (misunderstanding) — QUOTES NOT CONFIRMED
  <reply>
  Could not be found in the paper's text: "<span>"
  Check these against the PDF before using this reply.

R2.1 (clarification) — no quotes to check (not checked)
  <reply>

Planned revisions (your to-do list)
  - ...
```

Rules:

- Lead with the counts by `evidence_status`, so the denominator is visible.
- Put the `unverified_spans` right under the reply they belong to. Never drop them.
- Never describe a draft as "verified" when its status is `no_quotes`.
- Never edit a reply to make it sound more confident than the draft, and never add quotes of your own.
- If concerns were grouped, say which ones, so the author can answer them together.

## What this does NOT do

Say it in one closing line. It does not run new experiments, check that the planned revisions are feasible, or judge whether a reviewer is right. It drafts; the author decides what is true and what to send.

## Cleanup

The scratch workspace keeps the extraction, so drafting again (for example with a different tone) costs only the drafting calls. Remove it only if asked:

There is **no command** that removes it. A workspace chosen with `RESEARCH_COMPANION_WORKSPACE` is never added to the workspace list (so `research-companion workspace list` does not show it); it is just a folder:

```
~/.research-companion/workspaces/rebuttal-scratch
```

(under `$RESEARCH_COMPANION_DIR/workspaces/` instead, if that variable is set). To remove it, delete that one folder — show the user the full path and get a yes first. Never delete any other folder there: each one is one of the user's researches.
