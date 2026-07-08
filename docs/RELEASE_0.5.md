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

## 0.5.3 — the provider you chose is the provider it uses

Fixes an ingestion failure where the pipeline could call the wrong LLM
provider: it read a raw environment variable (defaulting to Anthropic) while
the Settings screen wrote to settings.json, so a machine configured for
OpenAI in the UI could still attempt Anthropic auth and fail every paper at
the extract step. The pipeline now resolves provider and model through the
same settings chain as the Settings screen (settings.json, then environment,
then default). Also hardened after the fix: citation-coverage recompute and
resolve no longer clobber each other's saves (a lock serializes both
writers), and paper deletion on Windows retries briefly when a background
read momentarily holds a file open (WinError 32).

## 0.5.4 — deletion everywhere

Users could archive a research but couldn't find how to *delete* anything —
deletion existed but hid in a drawer. 0.5.4 puts it in plain sight:

- **Delete a research** from the Researches screen: a trash button on every
  card, archived included. The confirmation names the research and its paper
  count. Deleting the research you're currently in auto-switches you to
  another one (Main preferred) and reloads; the action is blocked with a
  clear message while a background job is running. Crash-safe on the backend:
  the registry saves in two phases, and Windows locked-file deletes retry.
- **Remove a paper** is now a visible button on every library card and every
  list-view row (previously: the drawer and failed cards only). All three
  surfaces share one flow.
- Deleting the paper marked as **draft ★** clears the draft flag
  automatically (the delete response carries `draft_cleared`).
- **Unset draft** button in the paper drawer (setting was previously
  one-way).
- **Clear chat** button in the Companion panel, per thread — deletes the
  server-side conversation; safe when nothing was persisted yet.

**New API:** `DELETE /api/workspaces/{id}` →
`{"removed", "active", "switched"}`; `DELETE /api/conversations/{id}`.

**Upgrade notes:** none — purely additive; no store or settings changes.

## 0.5.5 — the banner stays in its lane

The "Analysis covers N of M cited papers" banner occupied a layout row in
every view except the graph, which is a viewport overlay pinned just below
the topbar — so on the Graph screen the banner painted straight over the
Draft/Explore toggle and the sections panel. The overlay now offsets itself
per visible banner. Banners are fixed-height single-line (long text
ellipsizes instead of wrapping into the content), the graph's floating
panels size themselves against the canvas rather than the viewport, and
scrollbars app-wide are thin and theme-colored instead of the heavy
platform-gray default. CSS-only; no behavior changes.

## 0.5.6 — read it yourself

Until now the Lab could tell you *about* a paper — its sections, its
alignment, the quotes it was cited for — but never let you actually **read**
it in place. 0.5.6 adds a reader across the Lab so the source is always one
click from the claim about it.

- **Open a section.** Click a section in the **draft view** or in the
  **graph** section list and a reading overlay opens the draft's extracted
  text, scrolled to that section and highlighted, with a
  section-navigation rail down the side to jump between sections.
- **Open a paper.** Click a paper — the graph's *"Read paper"* node action, a
  **Read** button on library cards and list rows, or the same button in the
  paper drawer — to read its full extracted text with the same section nav.
- **Quote → source.** Click a **verified evidence quote** on a draft
  alignment card and the cited paper opens with that exact quote highlighted.
  Location is whitespace- and case-insensitive; if the quote can't be located
  in the text the paper still opens, with a notice instead of a silent miss.
- **View original PDF.** Every reader carries a **"View original PDF"** link
  that opens the stored PDF in a new tab. Papers with **no extracted text**
  (e.g. scanned PDFs) don't show a blank pane — they show a clear empty-state
  that points you to the PDF.
- **New API (read-only):** `GET /api/papers/{id}/text?q=<quote>` returns the
  extracted text (with the located quote's offsets when `q` is given) and
  `GET /api/papers/{id}/pdf` streams the stored PDF.

**Upgrade notes:** none — purely additive; no store or settings changes.
