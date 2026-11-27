---
name: literature-scout
description: "Use when someone asks what they should read on a topic, wants papers on a subject, asks for a starting reading list, related work, or 'what has been published on X', or wants to find papers that cite or are cited by papers already in their library. Searches the Semantic Scholar catalogue and returns candidate papers ranked by citation count. No LLM calls, no cost."
---

# /literature-scout

Answer one question: **what should I read on this topic?**

Searches a public scholarly catalogue (Semantic Scholar) for papers on a topic and returns a list of **candidates to read**. No model calls and no API cost. It needs network access, and the topic text is sent to Semantic Scholar — say so if the topic looks like an unpublished idea the user may not want to share.

## Usage

```
/literature-scout <topic>                         # e.g. /literature-scout graph-based RAG
/literature-scout <topic> --year-min 2023         # recent work only
/literature-scout --expand --workspace <name>     # follow citations of papers already in a library
```

## What the result is — and what it is not

This is the most important thing to get right in the report.

- It is **a list of candidates**, not a survey. It is one catalogue's answer to one search phrase. Different wording finds different papers.
- It is **not exhaustive**. Only **Semantic Scholar** is searched by this command. Work it does not index, or indexes under different words, will not appear.
- It is **ranked by citation count**, highest first. That favours older, well-known papers. A paper from last month has had no time to be cited, so recent work sits low or falls off the list. Offer `--year-min` when the user wants what is new.
- Citation count measures attention, not quality or relevance. Say "most-cited among the results", never "the best papers" or "the most important papers".
- An empty result is **not** proof that nothing has been written on the topic. It means this search, in this catalogue, returned nothing new.

## The two rules

These are the project's core promise. Follow them in every report.

- **A check that did not run is never presented as a pass.** A search that was refused or failed is reported as *not searched* (not checked) — never as "nothing has been published on this".
- **Something not found is never called fabricated.** If a paper the user expected is missing from the list, that says this search did not surface it, not that the paper does not exist or is fake.

## Workspace safety

Research Companion writes to a **global** store with named workspaces, not the current folder. Set the workspace inline on every command:

```bash
RESEARCH_COMPANION_WORKSPACE=scout-scratch research-companion <cmd> ...
```

PowerShell has no inline env-var prefix — use the Bash tool, or set `$env:RESEARCH_COMPANION_WORKSPACE` and restore it afterwards.

`discover` without `--add` **reads** the workspace (to leave out papers already in it) and writes nothing. Only use a different workspace when the user explicitly names one with `--workspace <name>` (a skill argument, not a CLI flag: it means setting `RESEARCH_COMPANION_WORKSPACE=<name>` instead of `scout-scratch`) — they would do that so papers they already have are left out of the list, or to use `--expand`.

**Never pass `--add` unless the user asks for the papers to be added.** It downloads every result into the workspace.

## What You Must Do When Invoked

If no topic was given and `--expand` was not asked for, ask what topic to search. Do not invent one.

### Step 1 — search

```bash
RESEARCH_COMPANION_WORKSPACE=scout-scratch research-companion discover "<topic>" --json
```

Options that exist (use only these):

| flag | effect |
|---|---|
| `-n N` / `--limit N` | how many papers to return (default 20) |
| `--year-min YEAR` | earliest publication year (topic search only) |
| `--year-max YEAR` | latest publication year (topic search only) |
| `--expand` | instead of a topic, follow the references and citations of papers already in the workspace |
| `--min-citations N` | with `--expand` only: leave out papers with fewer citations (default 5) |
| `--add` | add every result to the workspace — only when the user asks |

`--expand` needs papers in the workspace, so it only makes sense with the user's own `--workspace <name>`. In the empty scratch workspace it stops with `no papers in store. Add some first, then use --expand.` — report that, do not treat it as an empty result.

Progress goes to stderr (`searching Semantic Scholar for "<topic>"...`). Judge success by the exit code and valid JSON on stdout.

### Step 2 — read the output

`--json` prints a list. Each entry:

```json
{
  "title": "...",
  "authors": ["..."],
  "year": 2023,
  "citation_count": 412,
  "arxiv_id": "<arXiv id or null>",
  "doi": null,
  "s2_id": "...",
  "pmid": null,
  "pmcid": null,
  "url": "https://www.semanticscholar.org/paper/...",
  "abstract": "...",
  "venue": "ICML",
  "source": "search",
  "add_cmd": "research-companion add <arXiv id, DOI, or S2 id>"
}
```

- `source` — `search` for a topic search; with `--expand`, `reference` (a paper the user's papers cite) or `citation` (a paper that cites them).
- `abstract` and `venue` can be empty strings: the catalogue had none. Say "no abstract available", do not write one.
- `add_cmd` — the exact command to add that paper to a library later.

### Step 3 — the outcomes that are not a list

**The catalogue refused or failed.** A traceback ending in `RuntimeError: Semantic Scholar search failed: ... '429 ...'` with exit code 1 means Semantic Scholar rate-limited the request (its anonymous pool is shared). **The search did not run.** Report it as *not searched*, never as "no papers found". Suggest trying again in a minute; a free Semantic Scholar API key set as `S2_API_KEY` raises the limit. Any other `Semantic Scholar search failed` message is the same kind of outcome: not searched.

**Nothing new.** `research-companion: no new papers found via topic search.` (exit 0) means the search ran and returned nothing that is not already in the workspace. In the scratch workspace that means the catalogue matched nothing for this wording. Suggest different or broader words. Do not say the topic has no literature.

### Step 4 — report

Lead with what was searched and where, then the list. Suggested shape:

```
Reading candidates — "speculative decoding" (2023 onward)
Searched: Semantic Scholar only · 20 results · ranked by citation count

  1. <title>
     <first author> et al., <year> · <venue> · <citation_count> citations · arXiv:<arxiv_id>
     One line taken from the abstract on what it does.
  2. ...

Not covered by this search
  – Other catalogues (OpenAlex, arXiv, PubMed) were not searched
  – Papers described with different words than "speculative decoding"
  – Very recent work ranks low: it has had no time to be cited

To add one to a library: <its add_cmd>
```

Rules:

- **Always name the catalogue that answered** (Semantic Scholar) and say it is the only one searched.
- Call the results **candidates to read**, never "the literature", "all the papers", or "a complete survey".
- Summarise a paper only from its `abstract`. If the abstract is empty, say so — never describe a paper you have only the title of as if you had read it.
- If the user asks whether a specific paper exists or is real, that is a different question — point them to `/refcheck`.
- If a search was not run (rate limit, network failure), the report says **not searched**, and gives no list.

## What this does NOT do

Say it in one closing line. It does not read the papers, judge their quality, or check that the list is complete. It finds candidates; deciding what is worth reading is the researcher's call.

## Cleanup

`discover` without `--add` writes nothing, so the scratch workspace stays empty. If papers were added at the user's request and they want them gone:

```bash
research-companion workspace remove scout-scratch
```

Do not remove anything automatically.
