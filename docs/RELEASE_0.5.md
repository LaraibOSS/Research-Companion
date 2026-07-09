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

## 0.5.7 — real paper metadata

Until now an uploaded PDF entered your library with only a filename and no
year — so it never appeared on the timeline, and citation coverage could only
recognise it by title. 0.5.7 makes each paper's real bibliographic identity
first-class, extracted automatically and correctable by hand.

- **Automatic extraction.** The per-paper analysis now reads each paper's
  **title, authors, and year** from its own text and fills them in
  automatically — no more filename-only entries.
- **One-time backfill.** Existing papers are backfilled on startup and when
  you open a workspace: any paper that has extracted text but is missing a
  year is re-read once to recover its metadata. Scanned PDFs with no
  extractable text are skipped (there is nothing to read).
- **Timeline sees them.** Because the timeline needs years, papers that were
  previously yearless now appear on it once their metadata is filled in.
- **Smarter citation matching.** Citation coverage now recognises a cited
  paper as already-in-library by **first-author surname + exact year**, not
  just by title — so "Add N missing" stops nagging about papers you already
  have under a slightly different title.
- **No duplicate downloads.** Before auto-downloading a resolved citation, the
  app checks the library (by id, title, and author+year) and skips the
  download when you already have the paper.
- **Manual metadata entry.** Every paper still missing authors or a year
  shows an amber **"Needs metadata"** indicator, and a banner tells you how
  many need attention. An **Edit metadata** form in the paper drawer lets you
  set the title, authors, and year by hand (year constrained to 1900–2100).
- **New API:** `PATCH /api/papers/{id}` — update a paper's title, authors,
  and/or year.

**Upgrade notes:** none — purely additive; no store or settings migration.
The extraction prompt changed, so papers re-extract once on first open,
backfilling their metadata as a side effect.

## 0.5.8 — link a citation to a paper you already have

Citation coverage could recognise a cited reference automatically (by arXiv
ID, DOI, title, or author+year), but when the automatic match missed — a
reference worded differently from the paper's real title, say — there was no
way to tell the app *"this cited reference is that paper I already have."*
0.5.8 adds that link, from either side of the relationship.

- **From the Citations panel.** Every not-in-library citation row now carries
  a **"Link…"** control that opens an **inline dropdown** of your library
  papers — the papers still needing metadata are listed first, since they are
  the likeliest missing matches. Pick one and the citation is linked to that
  paper. A disclaimer on the picker notes that the titles and years shown come
  from your draft's citations, not from the papers themselves, so you choose
  on the citation's terms.
- **From a paper's drawer.** The same link can be made from the paper side: a
  **"This is a cited reference…"** picker in the library paper's drawer lets
  you attach it to one of your draft's citations.
- **Durable manual link.** Linking marks the citation **In library** and the
  mark holds: it survives coverage recomputes and reverts only if you delete
  the paper it points to. A manual link is a deliberate statement, not a guess
  the next recompute is free to overwrite.
- **Year backfill for the timeline.** Linking **backfills the paper's year**
  from the citation (year only) when the paper had none, so a previously
  yearless paper appears on the **timeline** straight away. Authors are left
  untouched — fill those in via **Edit metadata** when you want them.
- **New API:** `POST /api/draft/citations/link` — link a cited reference to a
  library paper.

Also in this release: a test-isolation leak was fixed — the suite now restores
`os.environ` per test so one test's environment changes can no longer bleed
into another.

**Upgrade notes:** none — purely additive; no store or settings migration.

## 0.5.9 — robust ingestion

Ingestion used a single hard-wired PDF reader (pypdf), had no OCR, and — worst
of all — a scanned PDF that yielded no text still "succeeded", entering your
library as an empty-text paper that quietly polluted retrieval. 0.5.9 rebuilds
the front of the pipeline around a pluggable parser layer and makes an
unreadable PDF fail honestly.

- **Pluggable parser layer** (`research_companion/parsers/`). The pipeline no
  longer hard-codes a PDF reader; it asks `get_parser()` for one. The default
  is **pypdfium2** (permissive licence, better layout fidelity than the old
  pypdf). Set `RESEARCH_COMPANION_PARSER=pypdfium|docling` to choose explicitly.
- **Optional Docling engine** — `pip install research-companion[docling]`. When
  the `docling` package is importable it is auto-selected, giving **layout-aware
  reading order** (fixes multi-column papers), **real document sections**,
  captured **tables and figures**, and **OCR for scanned/image PDFs**. Docling
  and its torch stack are imported lazily, so installing the extra never slows
  the digital-PDF path and not installing it costs nothing.
- **Honest empty-text quality gate.** Extracted text now passes a cheap quality
  check (length + alphabetic ratio). A scanned/unreadable PDF is marked
  **failed** with a clear message — *"No extractable text — the PDF appears to
  be scanned/image-only. Install the OCR engine (pip install
  research-companion[docling]) or add the paper's metadata by hand."* — instead
  of silently succeeding with empty text. **Retrieval no longer indexes
  empty-text papers.**
- **OCR fallback for scanned PDFs.** When the normal parse fails the gate and
  Docling is installed, the pipeline retries once with **forced full-page OCR**
  (a separate, slower converter used only on this fallback path). Verified live:
  a real scanned paper that extracted 0 characters recovered 35,411 characters
  and 17 sections through this path. If OCR still recovers nothing (corrupt or
  genuinely text-free PDF), the paper fails with an honest message rather than a
  false success.
- **Docling sections win downstream.** When Docling returns real sections they
  are persisted and used in place of the heuristic sectioner (the heuristic
  remains the fallback). Tables and figures are captured to `structure.json`
  (not yet surfaced in the UI — a future phase).

A full audit and the architecture decision behind keeping the design
local-first are written up in
`docs/superpowers/specs/2026-07-09-ingestion-architecture.md`.

**Upgrade notes:** none — purely additive; no store or settings migration. The
`[docling]` extra is optional; without it ingestion behaves as before except
that scanned PDFs now fail honestly instead of entering empty.

## 0.5.10 — sharper retrieval

A retrieval unit used to be one whole section, and — a real latent defect —
its BM25 tokens were built from only the **first 300 characters** of that
section. A long section's opening paragraph was searchable; everything past
it was invisible to keyword search no matter how relevant. 0.5.10 fixes the
recall gap and gives every retrieved span exact provenance.

- **Section-aware sub-chunking** (`research_companion/chunking.py`). Long
  sections are split into overlapping, boundary-aware windows (~1200 chars,
  150-char overlap) instead of being kept as one blob. Each chunk prefers to
  end on a paragraph or sentence boundary rather than an arbitrary hard cut,
  and a short trailing chunk is merged into its predecessor instead of
  standing alone. A section at or below the target size still yields exactly
  one chunk, so short sections are unaffected.
- **The full-text tokenization fix.** BM25 now tokenizes the **entire text of
  each chunk**, not the first 300 characters of the section it came from — so
  content deep in a long section is finally findable by keyword search.
- **Char-level evidence provenance.** Every chunk carries **absolute**
  character offsets (`char_start`, `char_end`) into the paper's full text plus
  a `chunk_index`, so retrieval sources cite precise, verifiable spans instead
  of "somewhere in this section" — the same offsets the reader (section 11 of
  the User Manual) uses to highlight exactly what was retrieved.

**Upgrade notes:** none — purely additive; no store or settings migration.
Existing papers benefit automatically the next time their sections are
retrieved.

## 0.5.11 — verifiable answers

0.5.10 gave every chunk exact char-level provenance; 0.5.11 puts that
provenance to work at the two places you actually read an answer, and
finishes wiring semantic retrieval down to the same chunk granularity.

- **Clickable citation → reader span jump.** Clicking a `[n]` citation chip
  in **Ask** or the **Companion** no longer just opens the cited paper — it
  opens the reader **scrolled to and highlighting the exact passage** the
  answer drew from, using the citation's absolute character offsets. This is
  the "verify it yourself" moment for Q&A that the reader (0.5.6) and
  alignment quotes already had. Falls back to opening at the section, or the
  paper, when offsets are absent or degenerate (e.g. older data).
- **Chunk-level embeddings.** Semantic (embedding) retrieval now keys vectors
  per `(section, chunk)` instead of per section, so each sub-chunk of a long
  section is scored on its own content instead of inheriting one vector for
  the whole section. This completes the Phase 2 sub-chunking work
  (0.5.10) for the embedding path; only active when a Hugging Face token is
  configured — the BM25 fallback is unchanged.

**Upgrade notes:** none — purely additive; no store or settings migration.

## 0.5.12 — knowledge-graph provenance

The knowledge graph has always merged shared entities across papers (five
papers mentioning GraphRAG = one node), but the graph never told you *which*
papers those were — the shared-ness was implicit in the merge, not visible.
0.5.12 makes it explicit.

- **Provenance on every entity node.** Concept, method, dataset, claim, and
  result nodes now record the set of papers they appear in (`papers` +
  `paper_count`), tracked as entities are extracted and merged during graph
  build.
- **"Appears in N papers."** The graph's node detail panel shows this count
  plus the contributing papers by name — click a concept, method, or dataset
  and see at a glance which of your papers share it, without leaving the
  graph.

**Upgrade notes:** none — purely additive; no graph restructure, no store or
settings migration.

## 0.5.13 — cleanup

Internal housekeeping — no user-facing feature.

- **Dependency trim.** Dropped the unused `pypdf` runtime dependency; the PDF
  backend has been pypdfium2 since 0.5.9, so a base install is a touch leaner.
- **Dead-code removal.** Removed a never-imported frontend module (`icons.js`)
  and its stale test, and fixed a stranded JSDoc comment in `readerHelpers.js`.
- **Test-isolation fix.** A module-global `asyncio.Lock` was leaking across
  test event loops, occasionally flaking the retry-pipeline test; the lock now
  resets per test so the suite is reliably green.

**Upgrade notes:** none — purely internal; no store or settings migration.

## 0.5.14 — ingestion transparency

You could already trust *that* a paper was ingested; now you can see *how*.

- **A clear OCR-in-progress state.** When a scanned/image-only PDF fails the
  text-quality gate, the Lab falls back to forced full-page OCR (since 0.5.9).
  That step is slow, and the progress indicator used to blank out while it ran
  — looking stalled. It now shows **"OCR-ing scanned PDF (may take a few
  minutes)…"** without disturbing an in-progress folder-import bar, and the
  same message surfaces on the activity indicator during a single add.
- **Per-paper parse provenance.** Every paper now records which parser produced
  its text (`pypdfium`, `docling`, or `docling+ocr`) and whether OCR was used.
  Papers read via OCR carry a quiet **OCR** badge in the library (card and list
  views) — a low-confidence signal that the text came from image recognition,
  not an embedded text layer. Digital PDFs show no badge; the norm stays
  uncluttered.
- **Honest on re-ingest.** Re-adding a paper whose text is already cached no
  longer clears its OCR provenance — the badge sticks to the paper it describes.

**Upgrade notes:** none — additive metadata fields with safe defaults; papers
ingested before 0.5.14 simply show no parse badge until re-ingested.
