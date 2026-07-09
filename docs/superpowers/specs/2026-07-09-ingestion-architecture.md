# Research Companion — Ingestion Audit & Architecture Decision Report

**Date:** 2026-07-09 · **Scope:** research-paper ingestion, storage, retrieval, knowledge graph, and the phased hardening program that begins with v0.5.9.

This document is the written audit and architecture decision the product's
ingestion overhaul is based on. It records *what was broken*, *what is already
good*, *what we deliberately are not building*, and *the phased plan*.

## 1. Current architecture (as-is)

Research Companion is a **local-first, single-user** research workspace. There
is no server and no database:

- **Storage:** plain files under a per-workspace directory
  (`~/.research-companion/workspaces/<id>/`). Each paper has `metadata.json`,
  `text.txt`, `sections.json`, `extraction.json` (entities), `alignment.json`,
  `strength.json`, `embeddings.json`, and (new) `structure.json`. Coverage,
  graph, config, and conversations are per-workspace JSON.
- **Knowledge graph:** a `networkx` graph persisted to JSON — concept / method /
  dataset / claim / result nodes plus stance edges (strengthens / challenges /
  alternative) against the draft. Powers the graph view, timeline, and
  alignment cards.
- **Retrieval:** section-as-chunk index built in memory per query; BM25 base
  with optional hybrid fusion against Hugging Face embeddings
  (`all-MiniLM-L6-v2`, remote API) when `HF_TOKEN` is set; pure BM25 otherwise.
- **UI:** a FastAPI "Lab" serving a vanilla-JS SPA (library, graph, timeline,
  reader, citations/placement panels).
- **LLM:** Anthropic or OpenAI via their SDKs, for entity/claim extraction,
  alignment, answers, and (v0.5.7+) paper-metadata backfill.

Dependencies are deliberately lightweight and pure-pip: `pypdf`→`pypdfium2`,
`httpx`, `networkx`, `jinja2`, `feedparser`, the two LLM SDKs; FastAPI/uvicorn
only for the Lab. No database, no local ML model in the base install.

## 2. Audit — what was broken (fixed in v0.5.9)

1. **Single, weak PDF extractor.** Text came only from
   `pypdf.page.extract_text()` — layout-unaware, no column handling, **no OCR**.
   Scanned/image PDFs returned an empty string.
2. **Silent-success on empty text (the serious defect).** Nothing guarded empty
   extraction: the paper was marked **done** with an empty `text.txt`, produced
   one "Full Text" section and an empty graph contribution, and — because
   retrieval skipped only papers whose text file was *missing*, not *empty* —
   polluted the index with a zero-signal unit. The failure was invisible, and it
   cascaded into every downstream symptom users hit: empty timeline, missing
   metadata, failed citation matching, "Needs metadata" papers.
3. **Heuristic-only sectioning at ingest.** The LLM section fallback existed but
   was not wired into the pipeline, so multi-column / complex layouts collapsed
   to a single chunk.

## 3. What is already good (do not rebuild)

- The **knowledge graph** the original brief proposed "adding" already exists,
  with roughly the proposed node/edge taxonomy.
- **Local-first storage** is the right choice for a single-user tool and is a
  core part of the "install and run" value proposition.
- Retrieval, citation coverage, the reader, manual metadata + citation linking,
  and the timeline are all in reasonable shape.

## 4. Architecture Decision — options compared

| Option | Verdict | Why |
|---|---|---|
| **Local RAG (files + in-memory BM25 + optional embeddings)** | **CHOSEN** | Zero-config, `pip install` and run; correct for single-user; already in place and working. |
| Database-backed RAG (Postgres/pgvector, Neo4j, Qdrant, Weaviate) | **Rejected** | Adds a service to install and operate; breaks easy onboarding and the demo story; **no single-user benefit**. |
| Knowledge-graph RAG | **Already present** | The networkx concept graph + stance alignment is the KG layer; deepening it is optional (Phase 4), not foundational. |
| Graphify-style graph rebuild | **Not adopted** | The existing concept-level graph already covers the useful cases; a rebuild is churn without payoff here. |
| **Hybrid (parser + vector + KG + metadata store), local-first** | **This is what we have** | The v0.5.9 pluggable parser completes the hybrid; everything stays file-based and local. |

**Decision:** keep the **local-first hybrid**. The only justified future
storage change, *if* a library ever grows to thousands of papers, is an
**embedded** index (SQLite FTS or LanceDB) — still zero-service. **Never** a
server database.

**Ingestion engine decision (v0.5.9):** a pluggable parser layer.
- Default **pypdfium2** (BSD/Apache, pure-pip) — better than pypdf, no system
  binaries.
- Optional **Docling** (`pip install research-companion[docling]`, MIT) —
  layout-aware reading order, real sections, tables/figures, and OCR. Auto-used
  when installed; selectable via `RESEARCH_COMPANION_PARSER`.
- **PyMuPDF was rejected** despite its quality: it is AGPL-licensed and the
  project is MIT.
- **OCR is a fallback, not the default path.** A fast text probe runs first;
  only when a PDF yields no usable text does the pipeline invoke Docling with
  forced full-page OCR (slow, ~minutes/paper, but the only way to read
  image-only scans). Digital PDFs never pay the OCR cost.
- **Honesty gate:** a PDF that yields no text even after OCR (or with no OCR
  engine installed) is marked **failed** with an actionable message, never
  silently "done."

*Verified live:* a real scanned paper (ScispaCy) that extracted 0 characters
now extracts ~35k characters and 17 sections via the OCR fallback, recovering
the true title and authors.

## 5. Phased program

- **Phase 1 — Robust ingestion (v0.5.9, DONE).** Pluggable parser, pypdfium2
  default, Docling optional engine, empty-text quality gate, OCR fallback for
  scans, retrieval no longer indexes empty papers.
- **Phase 2 — Chunking & metadata.** Section-aware sub-chunking with preserved
  provenance (paper/section/page/offset); richer metadata capture from parsed
  structure; surface parsed tables/figures.
- **Phase 3 — Retrieval & citations.** Reranking, metadata/section filters,
  multi-paper and claim-level retrieval; stronger citation grounding.
- **Phase 4 — Knowledge-graph deepening (optional).** More edge types
  (uses_method, evaluates_on, reports_metric), provenance + confidence on nodes,
  entity de-duplication.
- **Phase 5 — Project cleanup.** Remove dead files, tighten module boundaries,
  consistent naming.
- **Phase 6 — Targeted UI.** Make ingestion status/failures first-class
  (per-paper parse quality, OCR progress, structure preview).
- **Phase 7 — Docs & tests.** Expand the manual, developer guide, and an
  end-to-end ingestion test flow with a sample fixture.

Each phase ships as its own reviewed, tested, green release so the running tool
is never left broken.
