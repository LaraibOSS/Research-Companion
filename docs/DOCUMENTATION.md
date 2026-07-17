# Research Companion — Full Documentation

**Version 0.7.1 · MIT License · https://github.com/Laraib-Hasan-Future/Research-Companion**

This is the single consolidated reference for Research Companion: what it is, how
it is built, every feature it ships, and where it is going. For task-oriented
usage see [USER_MANUAL.md](USER_MANUAL.md); for the ingestion internals see
[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md); for the plan of record see
[ROADMAP.md](ROADMAP.md).

---

## 1. Overview & identity

Research Companion is a **local-first, open-source** tool for writing and
evaluating research papers. You give it papers — your own draft and the
literature around it — and a team of specialized agents reads them, builds a
shared knowledge graph, and answers the questions every author and reviewer
faces: *Are my references real? Is my contribution novel? Which papers support
or threaten my draft, and where? Have I read everything my bibliography cites?
Does the paper fit its venue? Is the work reproducible?*

Its single organizing principle is **verifiability**. Every verdict carries
evidence you can check; every quote is verified verbatim against the source
text; deterministic computation is preferred over LLM guesswork; and when
something cannot be verified, the tool says so on screen rather than hiding it.

**Key properties**
- **Local-first** — all state is plain files under `~/.research-companion/`.
  No database, no required server beyond the local Lab.
- **Deterministic-first** — most checks (references, reproducibility, ethics,
  severity, strength, suggestions, timeline, retrieval fallback) run with no LLM
  and no network, so they are cheap, reproducible, and inspectable.
- **Verifiable** — grounded Q&A with `[S#]` citations, verbatim quote checking,
  char-span provenance to the exact source passage, an append-only event audit
  log, and reference validation against authoritative external records.
- **Honest about limits** — no misconduct/plagiarism claims, no semantic
  entailment, no autonomous code execution.

---

## 2. Installation & quickstart

```bash
pip install research-companion          # base CLI
pip install "research-companion[server]"  # + the web Lab (FastAPI/uvicorn)
pip install "research-companion[docling]" # + layout-aware parsing / OCR

# CLI quickstart
research-companion add https://arxiv.org/abs/2410.05779
research-companion build                 # LLM extraction (cached) + build the graph
research-companion view                  # interactive HTML graph
research-companion chat "what are the main approaches?"

# The Research Lab (browser workspace)
research-companion lab serve             # http://127.0.0.1:8765
```

- **Python:** `>=3.10,<3.14`.
- **Keys:** `ANTHROPIC_API_KEY` (default provider) or `OPENAI_API_KEY`; optional
  `HF_TOKEN` for semantic search. Stored in a local `.env`, never committed.
- **Offline demos (zero-key):** `python examples/demo_offline.py` (full review +
  rebuttal), `python examples/demo_lab_offline.py` (Lab event replay).

---

## 3. End-to-end workflow

Research Companion spans the paper lifecycle:

1. **Ideation / organization** — isolated *Researches* (workspaces).
2. **Discovery** — `discover` (Semantic Scholar topic search + citation expansion).
3. **Ingestion** — add arXiv/DOI/S2 IDs or PDFs; folder ingest; Docling/pypdfium.
4. **Knowledge graph** — concepts/methods/datasets/claims/results merged across papers.
5. **Q&A** — quote-grounded answers with `[S#]` citations and reader jump-to-span.
6. **Citation verification** — coverage (bibliography as ground truth) + placement.
7. **Novelty & alignment** — claim-level novelty vs prior art; draft alignment.
8. **Reviewer-grade checks** — venue-fit, severity ranking, reproducibility, ethics.
9. **Rebuttal** — grounded point-by-point reviewer responses.

---

## 4. Architecture

### 4.1 Data flow

A paper flows: **ingestion → text extraction → sectioning → LLM structured
extraction → graph delta → alignment/strength → retrieval → agents → report/UI.**

- **Ingestion** — `fetch.py::add_paper` pulls from arXiv/DOI/Semantic Scholar/local
  PDF. PDFs are parsed by `parsers/` (pypdfium2 default; docling optional).
- **Sectioning + extraction** — `sections.py` builds the section tree; `extract.py`
  does LLM structured entity extraction, cached on a prompt SHA.
- **Graph** — `graph.py::build_graph` merges per-paper entities into a cross-paper
  NetworkX graph persisted as `graph.json`.
- **Retrieval** — `qa.py` builds a section-unit index; `retrieve.py::rank_units`
  ranks (BM25 + optional embeddings) and returns grounded answers with `[S#]`
  citations and char-span provenance.
- **Agents** — the review DAG runs analysis agents over a paper.
- **Report** — `report.py` turns agent results into a self-contained HTML+JSON report.

### 4.2 The async agent runtime

The review is a small, dependency-ordered team of agents:

- **`agents/base.py`** — the `Agent` ABC (`name`, `role`, `depends_on`, async
  `run(ctx)`), plus `AgentContext` (holds `paper_id`, `bus`, a shared `data`
  blackboard) and `AgentResult`.
- **`agents/orchestrator.py`** — `run_agents()` validates the DAG (Kahn's
  algorithm; cycle/duplicate/unknown-dependency checks) and runs every ready agent
  concurrently via `asyncio.gather`. **Failure isolation is the contract:** one
  agent's exception never kills the run; dependents of a failed agent are skipped
  with an explicit `"dependency failed: <dep>"` reason.
- **`agents/bus.py`** — an in-process async pub/sub `Bus` with full history,
  mirroring every event to an optional append-only `EventLog`.
- **`agents/events.py`** — typed events (`AgentStarted`, `Finding`, `AgentDone`,
  `AgentError`, plus Lab pipeline events) and the JSONL `EventLog` audit trail.

`cli.py::_cmd_review` builds the agent list, wires a `Bus(log=EventLog(...))`, and
runs `asyncio.run(run_agents(...))`, persisting the report and a per-run JSONL log
under `~/.research-companion/…/runs/`.

### 4.3 Persistence — JSON store, no database

`store.py` keeps all state as files under `RESEARCH_COMPANION_DIR` (default
`~/.research-companion/`). Global state (`.env`, `settings.json`, workspace
registry) lives at the root; each workspace lives under `workspaces/<id>/`:

- `papers/<id-dirname>/` — one dir per paper: `paper.pdf`, `metadata.json`,
  `text.txt`, `extraction.json`, plus cached `sections`, `structure`, `alignment`,
  `strength`, `embeddings`, `gaps`, and the review report.
- `graph.json` (merged NetworkX graph) + `graph.html` (viz) at the workspace root.
- `runs/*.jsonl` — per-review agent event logs.

A **paper record** (`PaperMetadata`) holds `paper_id`, `title`, `authors`, `year`,
`abstract`, `source_url`, `arxiv_categories`, `added_at`, `parse_source`
(`pypdfium` / `docling` / `docling+ocr`), and `ocr_used`. Files are written
atomically (tmp + `os.replace`). There is **no SQL/NoSQL database**; the only
datastore-like dependency is NetworkX (in-memory, serialized to JSON).

### 4.4 Retrieval internals

- **BM25 (in-memory)** — `rank.py`: Okapi BM25 (`k1=1.5`, `b=0.75`), lowercase
  alphanumeric tokenization (≥3 chars, minus stopwords). Built fresh per query.
- **Chunking with char provenance** — `chunking.py::chunk_section` splits sections
  into ~1200-char overlapping windows (150 overlap) on paragraph/sentence
  boundaries; each chunk carries **absolute** `char_start`/`char_end` so
  `paper_text[char_start:char_end] == chunk_text` (exact reader highlighting).
- **Hybrid ranking** — `retrieve.py::rank_units` fuses `0.5·BM25 + 0.5·cosine` via
  per-pool min-max normalization; embeddings are optional HuggingFace vectors
  (`embed.py`, gated on `HF_TOKEN`, cached per sub-chunk). **Deterministic
  degradation:** with no token/vectors it falls back to raw BM25 order bit-for-bit
  and tags results `mode: "bm25"` vs `"hybrid"`; it never raises for embedding
  reasons.

### 4.5 The Lab server

- **App factory** — `lab_api.py::create_lab_app(bus, *, llm=None)` builds a FastAPI
  app; FastAPI/uvicorn are lazily imported so the base package needs neither.
- **Serving** — `serve_lab(port=8765)` runs uvicorn on `127.0.0.1`; `GET /` returns
  the SPA `index.html`; static assets mount at `/static`.
- **API surface** — ~50 `/api` endpoints: papers CRUD/upload/retry, draft +
  citations (resolve/link) + placement, sections, graph, ingest (+scan), jobs,
  failures, align, ask, compare, settings, suggestions, workspaces, saved views,
  gaps, temporal, journey, search, converse, and `GET /api/events` (SSE stream).
- **Frontend** — a hand-rolled vanilla-JS SPA under `lab/static/js/`
  (`store.js`/`reducer.js`/`router.js`/`main.js`, `sse.js`, `components/*`,
  `views/*`).

---

## 5. Feature catalog

### 5.1 CLI reference

| Command | Purpose |
|---|---|
| `add <target…> [-f FILE]` | Add arXiv/DOI/S2/local-PDF paper(s); batch from file |
| `build [--provider] [--model] [--force]` | LLM entity extraction (cached) + build graph |
| `cost-estimate` | Projected API cost for the next build |
| `view [--no-open]` | Render/open the interactive HTML graph |
| `chat ["question"] [--depth N]` | Graph-traversal RAG Q&A with citations (one-shot or REPL) |
| `search <query> [-k KIND] [-n N]` | Keyword search over graph nodes |
| `list` / `remove <id>` / `stats` | Library management + graph statistics |
| `export [--format md\|csv\|json\|obsidian]` | Export the graph to portable formats |
| `discover [topic] [--expand] [--add]` | Semantic Scholar topic search / citation expansion |
| `refcheck <id> [--json]` | Validate references vs CrossRef/OpenAlex |
| `check-stats <id> [--json]` | Recompute reported p-values (Statcheck) + GRIM mean check |
| `check-overlap <id> [--external] [--json]` | Near-duplicate passages vs the library (external is opt-in/consent-gated) |
| `export-bib [--format bibtex\|ris] [-o FILE]` | Export the library as BibTeX/RIS |
| `import-bib <file.bib>` | Import a Zotero/Mendeley `.bib` into the library |
| `cite-tex <file.tex> [--bib FILE]` | Resolve a LaTeX draft's `\cite` keys against a `.bib` |
| `mcp serve [--transport stdio\|sse]` | Run the MCP trust-layer server (verification tools for external agents) |
| `review <id> [--fast] [--report DIR] [--serve] [--venue SLUG]` | Run the review team |
| `rebuttal <id> [--reviews FILE] [--tone …]` | Grounded point-by-point reviewer replies |
| `set-draft [id] [--clear] [--show]` | Designate/clear/show the draft paper |
| `align <id> [--against DRAFT]` | Score a paper against the draft |
| `ask ["question"] [-k N] [--section ID]` | BM25-retrieved section Q&A with `[S#]` sources |
| `compare <A> <B>` | Entity/results overlap + optional LLM narrative |
| `gaps [--refresh]` / `timeline` | Research-gap analysis / temporal overview |
| `workspace list\|create\|use` | Manage isolated research workspaces |
| `lab serve\|ingest\|failures` | The web Lab (server, folder ingest, failure list) |

### 5.2 Agents

| Agent | name | LLM? | Produces |
|---|---|---|---|
| `IngestAgent` | ingest | deterministic | graph node/edge counts (seeds the blackboard) |
| `CitationAgent` | citation | deterministic (API) | verified / suspect / unverified references |
| `PriorArtAgent` | priorart | deterministic (API) | related papers found via scholarly search |
| `NoveltyAgent` | novelty | **LLM** | per-claim novelty verdicts + verified evidence |
| `ConfidenceAgent` | confidence | deterministic | per-claim confidence score + uncertainty band |
| `BenchmarkAgent` | benchmark | deterministic | suggested evaluation benchmarks |
| `StatSoundnessAgent` | statsoundness | deterministic | recomputed p-values + GRIM mean checks |
| `OverlapAgent` | overlap | deterministic | near-duplicate passages vs the local library |
| `ReproducibilityAgent` | reproducibility | deterministic | reproducibility level (high/med/low) + gaps |
| `EthicsAgent` | ethics | deterministic | present / missing integrity declarations |
| `SeverityAgent` | severity | deterministic | findings ranked critical/major/minor |
| `VenueFitAgent` | venuefit | LLM (grounded) | venue-fit verdict + desk-reject risk |
| `RebuttalAgent` | rebuttal | **LLM** | grounded reviewer replies + verified spans |
| `ProblemStatementAgent` | problem | **LLM** | refined problem statement (library-level) |
| `TrackerAgent` | tracker | deterministic | new-related-work sweep (library-level) |

Dependencies are declared via `depends_on`; `review` wires ingest + citation +
priorart + statsoundness + reproducibility + ethics + overlap always-on, adds
novelty + confidence + benchmark + severity unless `--fast`, and adds venuefit when
`--venue` is given.

### 5.3 The Research Lab UI

- **Views** — Home (journey + next-best-action), Library (cards/list, filters),
  Graph (live vis.js growth, Draft/Explore modes), Draft (alignment cards), Ask,
  Compare, Timeline (+ gaps), Suggestions, Settings, Researches.
- **Panels/components** — Citation Coverage (`citationsPanel.js`), Citation
  Placement (`placementPanel.js`), Reader (`reader.js`, char-offset highlight),
  Companion chat (`conversePanel.js`), Suggestions (`suggestionsPanel.js`), ingest
  modal + progress dock, welcome/key-prompt dialog, workspace switcher, toasts.

### 5.4 Key end-user features

- **Ingestion pipeline** — pluggable parser layer; pypdfium2 default, optional
  Docling for layout/reading-order/tables/figures and forced full-page OCR.
  Docling runs in an **isolated subprocess** so a native crash/timeout falls back
  to pypdfium instead of killing the Lab; truncated parses fall back too. Folder
  ingest with pre-scan + per-file selection.
- **Library / dedup / metadata** — cross-source de-duplication (same paper via
  arXiv and as a local PDF); auto-extracted title/authors/year with a "Needs
  metadata" fallback and manual edit; OCR badge.
- **Citation coverage & placement** — your draft's bibliography as ground truth
  (in-library vs missing, one-click add, partial-coverage disclaimer); placement
  checks each `[n]` and author-year citation is in the right section.
- **Quote-grounded Q&A** — section-scoped answers with `[S#]` citations; verbatim
  quote verification surfaces `unverified_quotes`; click a citation to open the
  reader at the exact char span.
- **Alignment & strength** — per-section strengthens/challenges/alternative
  verdicts with verified evidence quotes; deterministic strength scoring.
- **Reviewer-grade checks (0.6)** — venue-fit, severity ranking, reproducibility,
  and integrity declarations (see §5.2 and [RELEASE_0.6.md](RELEASE_0.6.md)).
- **Rebuttal** — splits reviews, groups duplicate concerns, quotes only real
  passages (unground spans flagged), assembles a planned-revisions changelog.
- **Reports** — self-contained `report.html` + `report.json`; live SSE dashboard.
- **Interoperability** — BibTeX/RIS export of the library (`export-bib`), `.bib`
  import from Zotero/Mendeley (`import-bib`), and LaTeX `\cite`-key resolution
  against a `.bib` (`cite-tex`) — deterministic, in `research_companion/interop/`.
- **MCP trust-layer** — `research-companion mcp serve` exposes four deterministic,
  key-free tools (`verify_citation`, `ground_claim`, `citation_coverage`,
  `search_library`) to external agents over MCP. Logic in
  `research_companion/mcp_tools.py`; SDK wiring in `mcp_server.py` (optional `[mcp]`
  extra, lazily imported); versioned schemas in `docs/mcp-schemas/`.
- **Near-duplicate detection** — `research-companion check-overlap` flags passages
  that near-duplicate another paper in your **own library** (deterministic k-word
  shingling + containment, `research_companion/overlap.py`), with char-span
  provenance. Local-only by default; an opt-in, consent-gated external-provider seam
  (`check-overlap --external`) exists for web-corpus checking but ships no provider
  and sends nothing off-machine without an explicitly registered provider + consent.

---

## 6. Tech stack & dependencies

- **Build:** setuptools ≥68. **Python:** `>=3.10,<3.14`.
- **Runtime deps:** `anthropic>=0.40`, `openai>=1.40`, `pypdfium2>=4`,
  `httpx>=0.27`, `networkx>=3.0`, `jinja2>=3.1`, `feedparser>=6.0`.
- **Optional extras:** `server`/`demo` = `fastapi>=0.110` + `uvicorn>=0.29`;
  `docling` = `docling>=2`; `mcp` = `mcp>=1.0` (the MCP trust-layer server);
  `dev` = pytest, pytest-asyncio, ruff, fastapi, uvicorn.
- **Entry point:** `research-companion = research_companion.cli:main`.
- **Version:** single source of truth in `pyproject.toml`; `__init__.py` reads
  installed metadata so `--version` never drifts.
- **Tests:** pytest (`testpaths=["tests"]`, `asyncio_mode="auto"`, a `slow`
  marker) — 1,780+ Python tests; `node --test tests/js/*.test.mjs` — 638 JS tests.
- **Lint:** ruff (line-length 110, `E501` ignored, select `E,F,I,B,UP,SIM`).

---

## 7. Design principles

- **Local-first** — plain files, in-memory graph, no DB, no required server.
- **Deterministic-first** — deterministic engines are foregrounded; retrieval
  degrades bit-for-bit to pure BM25 when embeddings are unavailable.
- **Verifiability** — grounded answers, verbatim quote checks, `refcheck` against
  authoritative records, and a typed append-only event audit trail.
- **Char-span provenance** — absolute offsets thread from chunking → Q&A → reader
  so the exact evidence span is highlightable.
- **Honesty boundaries** — failures surface honestly (`text_quality`,
  `IngestFailed`, `FAILED` lanes); checks report only what they compute and skip
  ambiguous cases rather than guess.

---

## 8. Roadmap — where this is going

Shipped through **0.7.1**: the full novelty MVP (Phase 1), reviewer critique +
venue fit (Phase 2), universal reach + integrity (Phase 3 — venue KB,
reproducibility, integrity declarations), a deterministic **statistical soundness**
checker (Statcheck + GRIM), **interoperability** (BibTeX/RIS export, `.bib` import,
LaTeX `\cite`-key resolution), the **MCP trust-layer server** (four deterministic
key-free tools), and **near-duplicate detection** (`check-overlap`: local shingling
overlap vs your library, with an opt-in consent-gated external seam). This completes
the roadmap's integrity track. See [ROADMAP.md](ROADMAP.md).

Future work (undated):

- **Cost-gated MCP tools** — `ask_library` / `review_draft` behind an explicit
  budget/keys boundary (the v2 MCP schema).
- **Domain connectors** — PubMed / Europe PMC / DBLP.
- **Semantic (paraphrase) overlap** — embedding-based near-duplicate, beyond the
  current lexical shingling.

**Out of scope (non-goals):** misconduct/fraud claims, semantic entailment,
autonomous code execution, cloud/multi-user, GRIMMER/SPRITE (SD-level) and full
LaTeX rendering.
