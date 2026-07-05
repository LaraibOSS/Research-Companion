# Release 0.2.0 — Research Lab

## What's new

### Research Lab UI
A live-growing knowledge-graph workspace served at `http://127.0.0.1:8765`.
Drop a folder of PDFs via `lab ingest <folder>` or the in-browser Add button;
papers stream into the graph in real time over SSE.

### Section-wise subgraphs
Each paper is split into logical sections before entity extraction.  The graph
carries section metadata on `contains` edges, enabling focussed subgraph
queries (`GET /api/graph?section=<id>`).  The Ask command uses section context
for token-efficient, targeted answers.

### Draft alignment verdicts
Set one paper as your draft (`set-draft <paper-id>`); every other paper is
then scored and tagged `strengthens | challenges | alternative` against each
draft section.  Verified evidence quotes are grounded against the paper text.

### Evidence-strength colours
Papers receive a strength score (0–1) that drives a three-band colour scheme
(strong / moderate / weak) visible in both the graph and the library list.

### Ask (section-scoped Q&A)
`research-companion ask "<question>" [--section <id>]` answers from the
section subgraph, returning cited sources and flagging unverified quotes as
`CHECK`.

### Compare
`research-companion compare <paper-a> <paper-b>` produces a structured
dimension-by-dimension comparison table.

### Folder ingest pipeline
`research-companion lab ingest <folder>` scans for PDFs, runs the full
extract → section → strength → alignment pipeline, and streams progress over
SSE so the UI can display live updates.

### SSE event log
Every ingest session appends typed events (paper_added, section_tree_built,
section_extracted, graph_delta, alignment_ready, strength_updated,
ingest_failed, ingest_progress, job_done) to
`~/.research-companion/lab_events.jsonl`.

---

## Breaking / cache note

The entity-extraction prompt SHA changed in 0.2 to support section-level
fields.  Each existing paper will be **re-extracted once** on the next
`build` or `lab ingest` run; cached extractions from 0.1 are not reused.
To pre-warm the cache: `research-companion build --force`.

---

## Install matrix

| Use case | Install command |
|---|---|
| Core CLI (add/build/chat/view/export) | `pip install research-companion` |
| Lab server + UI | `pip install "research-companion[server]"` |
| Everything (dev/test) | `pip install "research-companion[dev]"` |

Python 3.10 – 3.13 supported.

---

## Zero-key demo

```bash
python examples/demo_lab_offline.py
```

Replays the fixture event stream, prints a narrative of papers added, sections
built, graph deltas, and failure/retry hints — no API keys, no network.
