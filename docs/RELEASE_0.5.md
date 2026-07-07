# Research Companion 0.5 — Citation Coverage

Your draft's bibliography is the ground truth for what your library should
contain. 0.5 makes the system act on it.

## Features

### Citation extraction & coverage (W5)
When you set a draft, its References section is parsed (offline — four
splitting strategies with sanity checks; falls back to the LLM extraction's
related-work list when PDF text defeats parsing, clearly labeled) and every
cited paper is matched against your library: by arXiv id, DOI, or title.

### The Citations panel
A new panel (bell-style, from the banner or the Home next-step card) lists
every cited paper with its status:
- **In library ✓** — already ingested and part of the analysis
- **Add ↓** — missing but downloadable (parsed or resolved id); one click adds
  it through the normal pipeline. **Add all (K)** queues every available one.
- **Not checked / Unresolved ?** — title-only entries; **Resolve missing**
  looks them up against CrossRef/OpenAlex with deliberately conservative
  matching (a false positive would download the wrong paper). Hover any row
  to see the raw citation string.

### The holistic-analysis disclaimer
Whenever coverage is incomplete, a slim banner appears on every view:
*"Analysis covers N of M cited papers — Add missing."* Alignments,
suggestions, and gaps are only as complete as the library they run against;
now the tool says so instead of letting partial coverage masquerade as a full
picture. The banner updates live as papers land and disappears at full
coverage (collapsible per session — it never silently goes away for good).

### Live everywhere
Coverage recomputes automatically on every draft change, paper add, folder
ingest, retry, and delete — the panel rows and the banner counts flip in real
time over the existing event stream.

## Version & compatibility

- **Python:** 3.10 – 3.13
- **Dependencies:** no new external dependencies
- **Install:** `pip install research-companion`

## 0.5.1 — automatic downloads

Cited papers now download **automatically** (user feedback: "can't it download
on its own and then present what has not been downloaded?"). On every draft or
library change, missing cited papers with a downloadable id are queued without
a click, and title-only references get one automatic resolution pass. The
Citations panel's job becomes presenting the remainder — whatever could not be
fetched stays listed as Unresolved with the raw citation on hover. A Settings
toggle ("Automatically download papers cited by your draft", on by default)
preserves cost control: each downloaded paper still costs one model extraction
call.

## 0.5.2 — it tells you what it's doing

Every background task is now visible: a spinner with a live label in the top
bar ("Downloading 1810.04805", "Checking references…", "2 tasks running"),
per-task lines in the progress dock, "Downloading…" chips on citation rows,
and the coverage banner switches to in-flight text while work is underway.
A new GET /api/jobs endpoint hydrates tabs opened mid-work. Under the hood,
every job publishes JobStarted/JobFinished lifecycle events — and chasing a
test hang exposed and fixed a latent shutdown bug (Python 3.10 asyncio
cancellation-swallowing) that had been lurking since 0.2.
