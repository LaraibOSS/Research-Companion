---
name: refcheck
description: "Use when someone asks whether a paper's citations or references are real, whether a bibliography contains hallucinated or fabricated references, whether an AI-written draft's citations can be trusted, or asks to verify/check the references in a PDF or paper. Looks every reference up in CrossRef, OpenAlex and arXiv. No LLM calls, no cost."
---

# /refcheck

Answer one question: **do this paper's references actually exist?**

Every reference in the bibliography is looked up in authoritative catalogues (CrossRef, OpenAlex, arXiv). No model calls — the bibliography is parsed deterministically and each entry is a catalogue lookup. Network access is required; nothing is sent to an LLM.

This is the check that catches **hallucinated citations** — plausible-looking references to papers that were never written. It is the most common failure in AI-assisted writing and the hardest to spot by eye.

## Usage

```
/refcheck <paper.pdf>                          # check a PDF's bibliography
/refcheck <paper.pdf> --connectors europepmc   # add biomedical catalogues
/refcheck <paper_id>                           # a paper already in a library
```

## The three verdicts — and what they actually mean

This matters more than anything else in this skill. **Getting this wrong turns a useful tool into an accusation machine.**

| verdict | means | does NOT mean |
|---|---|---|
| `verified` | a matching record was found, and the title/identifiers agree | — |
| `suspect` | a record was found, but a detail disagrees (title, authors, DOI) | that the reference is fake — usually a typo, a preprint-vs-published mismatch, or a shortened title |
| `unverified` | **no matching record was found in the catalogues searched** | that the paper does not exist |

**`unverified` is not proof of fabrication.** Perfectly real references land here routinely:

- books, book chapters, and theses
- workshop papers, technical reports, standards
- very recent preprints not yet indexed
- non-English venues and regional journals
- anything outside CrossRef/OpenAlex/arXiv coverage (biomedical often needs `--connectors europepmc`)

So report `unverified` as **"could not be found — check this one by hand"**, never as "this citation is fake". If several unverified entries share a pattern (all from one publisher, all very recent), say so — that points at coverage, not fabrication.

A run where the catalogues could not be reached at all reports that distinctly. Network failure is not evidence against a reference.

## Workspace safety

Research Companion writes to a **global** store with named workspaces, not the current folder. Adding a paper into whatever workspace is active would pollute the user's real research.

**Set the workspace inline on every command:**

```bash
RESEARCH_COMPANION_WORKSPACE=refcheck-scratch research-companion <cmd> ...
```

PowerShell has no inline env-var prefix — use the Bash tool, or set `$env:RESEARCH_COMPANION_WORKSPACE` and restore it after. Only use a different workspace if the user explicitly names one.

## What You Must Do When Invoked

If no PDF or paper id was given, ask. Do not guess a file.

### Step 1 — add the paper (skip if a `local:`/`arxiv:` id was given)

```bash
RESEARCH_COMPANION_WORKSPACE=refcheck-scratch research-companion add "<path/to/paper.pdf>"
```

Capture the printed id (`local:xxxxxxxxxxxx`). If `add` fails, stop and report it — never continue with a guessed id.

### Step 2 — run the check

```bash
RESEARCH_COMPANION_WORKSPACE=refcheck-scratch research-companion refcheck "<PAPER_ID>" --json
```

Text is extracted automatically on first use — a local parse, no model. **Expect 20–60 seconds** on the first run while the parser loads, then one network lookup per reference, so a 40-reference paper takes a couple of minutes. Say that up front rather than letting it look hung.

**Harmless stderr noise**: `[INFO] ... RapidOCR ...` lines and sometimes `AttributeError: 'MessageFactory' object has no attribute 'GetPrototype'` (a protobuf mismatch in a dependency). **Not failures.** Judge by exit code and valid JSON on stdout.

For biomedical papers add `--connectors europepmc` (also `pubmed`, `dblp`) — without it, PubMed-indexed references land in `unverified` for lack of coverage rather than because they are wrong.

**Two non-zero exits are normal outcomes, not errors. Report them as findings:**

```
no bibliography found in <id>. Looked for a References/Bibliography heading
```
No reference section was detected. Usually one of: the paper genuinely has none (a poster, an abstract, a slide deck); the bibliography is in a separate file; or the PDF is a scan and the heading never made it into the text. Say which you think it is, and offer the paid alternative explicitly as a choice — `research-companion build` uses a model to extract the reference list and **costs model calls**. Never run it without asking.

```
no extraction and no readable text for <id>
```
Nothing could be read from the PDF at all — almost always a scanned or image-only document. The default parser does no OCR. Report it as *not checked*; do not present it as a paper with no problems.

In both cases the exit code is 1 and stdout is empty. Do not report "the check failed" — report what was found, which is that there was nothing to check.

### Step 3 — read the output

```json
{
  "paper_id": "local:demo",
  "source": "text",
  "unparsed_count": 1,
  "unparsed": ["9"],
  "counts": {"verified": 1, "suspect": 0, "unverified": 1},
  "references": [
    {"title": "...", "status": "verified", "reasons": [], "doi": null, "arxiv_id": "1706.03762"}
  ]
}
```

- `source` — `text` means the bibliography was read from the paper itself; `extraction` means a previously built reference list was used.
- `unparsed` — lines in the bibliography that could **not** be read as references. **These were never checked.** They are part of the denominator and must appear in the report.

### Step 4 — report

Lead with the number that matters — how many could not be found — then group. Suggested shape:

```
Reference check — <paper title>
38 references · 34 verified · 1 suspect · 3 not found

NOT FOUND — verify these by hand (3)
  ? Zzyzx Q. Nonexistent. A paper that was never written anywhere. 2099.
  ? Kumar & Osei. Regional adaptation strategies. Accra Univ. Press, 2019.
  ? Lin et al. Scaling laws for retrieval. 2026.
  Not proof they are fake — books, workshop papers, and very recent
  preprints are often simply not indexed.

DETAIL MISMATCH (1)
  ! Smith et al. Deep nets for X — record title differs; check the year and title

NOT CHECKED
  – 1 bibliography line could not be parsed: "9"

VERIFIED (34)
  ✓ all found in CrossRef / OpenAlex / arXiv
```

Rules:

- **Never call an unverified reference fake, fabricated, or hallucinated.** Say "could not be found" and give the reason it might be missing.
- Put unverified entries **first** — they are what the user needs to act on — but keep the framing neutral.
- Always report `unparsed`. A summary over 38 of 42 references that presents as complete is the failure this whole check exists to prevent.
- If every reference is verified, say so plainly without hedging.
- If a run reports the catalogues were unreachable, report that as **not checked**, never as unverified.

## What this does NOT check

Say it in one closing line. It checks that references **exist**, not that they say what the paper claims they say. For that, the claim-audit in the Lab UI checks a cited passage against the claim it supports.

## Cleanup

The scratch workspace persists so re-checks are fast. Remove it only if asked:

```bash
research-companion workspace remove refcheck-scratch
```
