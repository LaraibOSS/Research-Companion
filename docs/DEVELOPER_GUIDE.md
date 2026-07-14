# Developer Guide — the ingestion pipeline

This guide is for contributors. It explains how a PDF becomes searchable,
graphed, verifiable knowledge inside Research Companion — module by module —
and how to extend or test that path. For the *why* behind the current design
(and the alternatives that were rejected), see the decision report at
`docs/superpowers/specs/2026-07-09-ingestion-architecture.md`. For the
user-facing behavior, see `docs/USER_MANUAL.md`.

Research Companion is **local-first**: everything lives as plain files under
`~/.research-companion/workspaces/<id>/` — JSON per paper plus an in-memory
BM25 index and an optional embeddings file. There is no database and no server
process beyond the local Lab. Keep that constraint in mind when adding
features: prefer a small per-paper JSON file over a new service.

---

## 1. The pipeline at a glance

A single paper flows through `ingest_one` in
`research_companion/lab/__init__.py`, stage by stage. Stages 2+ each publish an
event on the async `Bus` (the Lab's SSE stream) so the UI can react live.

```
PDF bytes
  └─▶ Stage 2  text + sections
        pdf_to_text (pluggable parser)         research_companion/parsers/
        text_quality gate  ── fails ─▶ forced full-page OCR fallback (docling)
        record parse provenance (parse_source / ocr_used)
        build_section_tree (heuristic) or parser-provided sections
  └─▶ Stage 3  extract         concepts / methods / datasets / claims / results (LLM)
  └─▶ Stage 4  graph           merge entities into the cross-paper knowledge graph
  └─▶ Stage 5  alignment       stance of this paper vs the draft (non-fatal)
  └─▶ Stage 6  strength        deterministic strength score (non-fatal)
  └─▶ Stage 7  embeddings      chunk-level vectors, if a model is configured (non-fatal)
  └─▶ Stage 8  clear_failure   on success, drop any prior failure record
```

Stages 2–4 are fatal (a failure records an `IngestFailed` and stops the paper);
5–7 are best-effort enrichments. Retrieval and Q&A read the artifacts these
stages persist — they are not part of `ingest_one` itself.

The **offline spine** (everything except the LLM extraction, graph, alignment,
and remote embeddings) runs with no network and no API key: parse → quality
gate → provenance → sections → chunks → BM25. That spine is exactly what the
end-to-end test in `tests/test_ingestion_e2e.py` exercises (§9).

---

## 2. The parser layer — `research_companion/parsers/`

Parsing is pluggable behind a tiny protocol so the rest of the system never
imports a PDF library directly.

- **`base.py`** — `ParsedDoc(text, sections, tables, figures, meta)` is the
  uniform output; the `Parser` protocol is just `.parse(pdf_path) -> ParsedDoc`
  plus a `.name`. `text_quality(text)` is the honesty gate: it returns
  `{"ok", ...}` where `ok` requires `char_count >= MIN_CHARS` (200) and
  `alpha_ratio >= MIN_ALPHA_RATIO` (0.5). `ParserError` wraps backend failures.
- **`pypdfium.py`** — `PypdfiumParser` (`name = "pypdfium"`), the default.
  BSD/Apache-licensed, no system deps, handles single- and most multi-column
  layouts. Text-only (no structural sections) — sectioning is then heuristic.
- **`docling_parser.py`** — `DoclingParser` (`name = "docling"`, or
  `"docling+ocr"` when constructed with `full_page_ocr=True`). Optional
  (`pip install research-companion[docling]`); all docling imports are lazy so
  a base install never pays for it. Brings layout-aware reading order, real
  document structure (sections/tables/figure captions), and OCR.
- **`__init__.py`** — `get_parser(name=None)` resolves the backend in this
  order: explicit `name` → `RESEARCH_COMPANION_PARSER` env var → docling if
  importable → pypdfium. `find_spec` keeps the docling probe import-free.

### Adding a parser
1. Implement a class with `.name` and `.parse(pdf_path) -> ParsedDoc` in a new
   module under `parsers/`. Keep heavy imports lazy (inside `parse`).
2. Populate `ParsedDoc.text` always; fill `sections`/`tables`/`figures` only if
   your backend recovers real structure (else leave them empty and let the
   heuristic sectioner run).
3. Register it in `get_parser`. Add a unit test mirroring
   `tests/test_parsers_docling.py` (mock the backend; don't download models in
   the default suite — gate real conversions behind the `slow` marker).

The test suite pins `RESEARCH_COMPANION_PARSER=pypdfium` (autouse conftest
fixture) so tests are deterministic and offline regardless of what's installed.

---

## 3. The quality gate + OCR fallback

A scanned/image-only PDF has no text layer. Rather than silently ingesting an
empty `text.txt` and quietly breaking search, Stage 2 runs `text_quality` on
the extracted text. If it fails:

1. Publish an `IngestProgress` phase-note
   (`"OCR-ing scanned PDF (may take a few minutes)…"`) — the UI shows this
   without disturbing an in-progress folder-import bar (see the reducer's
   phase-note handling in `lab/static/js/reducer.js`).
2. Call `extract.ocr_fallback_parse(meta)`, which re-parses with
   `DoclingParser(full_page_ocr=True)`. It returns `None` when docling is not
   installed — letting the caller distinguish "OCR unavailable → advise install"
   (`EMPTY_TEXT_ERROR`) from "OCR ran but still empty" (`OCR_FAILED_ERROR`).
3. If OCR recovers usable text, continue as success; otherwise record an
   `IngestFailed` with the honest reason.

OCR is slow (minutes/paper) and only ever runs on this failure path — the
digital-PDF happy path never pays for it.

---

## 4. Parse provenance

Stage 2 records **how** the text was produced, additively on `PaperMetadata`
(`store.py`): `parse_source` (`"pypdfium"` / `"docling"` / `"docling+ocr"`) and
`ocr_used` (bool). Rules that matter if you touch this code:

- Set provenance only when a parse actually ran this pass. `get_paper_parsed`
  serves cached text **without** re-running the parser, so a re-ingest of an
  already-OCR'd paper must **never downgrade** a prior `ocr_used=True` — that
  would drop the OCR badge from a paper whose on-disk text is still OCR-derived.
- Both fields have safe defaults, so metadata written before they existed loads
  fine (`PaperMetadata.load` → `cls(**data)`).
- They surface through `_build_paper_summary` (`lab_api.py`) on both
  `GET /api/papers` and `PATCH /api/papers/{id}`; the library UI renders a quiet
  `OCR` badge when `ocr_used` is true.

---

## 5. Sectioning — `research_companion/sections.py`

`build_and_save_sections(paper_id)` returns a `list[Section]` and persists
`sections.json` (keyed by a text SHA, so it's rebuilt when the text changes).
If the parser supplied structural sections they win; otherwise
`build_section_tree(text)` runs the heuristic sectioner (all-caps and numbered
headings, with a whole-document fallback). Each `Section` carries absolute
`char_start`/`char_end` offsets into the paper text — the backbone of all
downstream provenance. `is_boilerplate(title)` filters out References /
Acknowledgements etc. so they don't pollute retrieval.

---

## 6. Chunking — `research_companion/chunking.py`

`chunk_section(text, sec_char_start, *, target_chars=1200, overlap_chars=150,
min_tail=400)` splits one section into overlapping sub-chunks, each carrying an
**absolute** char offset (`sec_char_start` + local offset) so a chunk can be
mapped back to an exact span in the original text. Fixed-size chunking that
ignored section boundaries was rejected — it shredded context and broke
citation grounding. Bad params raise `ValueError` (fail loud).

---

## 7. Retrieval & embeddings

- **Units:** `qa.build_section_index(paper_ids)` produces one retrieval unit per
  *(paper × section × chunk)*. Each unit has `paper_id, paper_title, section_id,
  section_title, text, tokens, entity_labels, char_start, char_end,
  chunk_index`. Crucially, `tokens` are built from the **full chunk** (plus
  section title + entity labels), not a leading slice — so content deep in a
  long section is visible to BM25.
- **Tokenizer:** `research_companion/rank.py` `tokenize()` is the single token
  space. Build query tokens with the *same* function that indexed the units, or
  BM25 scores are meaningless.
- **Ranking:** `retrieve.rank_units(question, q_tokens, units, ...)` scores BM25
  and, when embeddings exist and a query embedder is available, blends in dense
  cosine (`mode="hybrid"`); with neither it is pure BM25 (`mode="bm25"`). The
  dense path activates only when an embedding model is configured (e.g. an
  `HF_TOKEN` is present) — so the offline path is BM25.
- **Embeddings:** `embed.embed_paper_sections` (Stage 7) computes one vector per
  chunk, keyed by `store.embedding_key(section_id, chunk_index)` and saved to
  `embeddings.json`. Remote (HF) and entirely optional.

---

## 8. Per-paper storage layout

Each paper is a directory under the active workspace. The files a contributor
will meet:

| File | Written by | Contents |
|------|-----------|----------|
| `metadata.json` | `PaperMetadata.save` | title, authors, year, source, `parse_source`, `ocr_used` |
| `paper.pdf` | `save_pdf` | the original PDF bytes |
| `text.txt` | `save_text` (Stage 2) | extracted plain text |
| `sections.json` | `build_and_save_sections` | section tree + method + text SHA |
| `structure.json` | `_persist_structure` | parser-recovered tables/figures (best-effort) |
| `extraction.json` | Stage 3 | concepts/methods/datasets/claims/results (+ prompt SHA) |
| `embeddings.json` | Stage 7 | chunk-keyed vectors |
| `strength.json`, `alignment.json`, `graph.json`, `report.json`, `gaps.json` | later stages / features | enrichments |

Workspace-level files (`config.json`, `settings.json`, `failed.json`,
`workspaces.json`) live above the per-paper dirs. Failures are recorded in
`failed.json` and cleared on a later successful ingest (Stage 8).

---

## 9. Testing ingestion

- **End-to-end (offline):** `tests/test_ingestion_e2e.py` runs the real spine on
  a committed fixture with **no mocks** — real pypdfium extraction → quality
  gate → provenance → heuristic sections → retrieval units → BM25 ranking that
  must surface the targeted section. This is the "does ingestion actually work"
  regression net; keep it green.
- **The fixture:** `tests/fixtures/sample_paper.pdf` is a small, committed,
  text-layer mini-paper (Abstract / Introduction / Methods / Results /
  Conclusion / References). Regenerate it with
  `python tests/fixtures/make_sample_paper.py` if you change what the test
  needs — then re-probe what pypdfium actually extracts and update assertions to
  the real text, never to the source strings (extraction can reorder/space
  text, and uses `\r\n` line breaks).
- **Stage-level:** `tests/test_lab_ingest.py` covers `ingest_one` stage by stage
  with the parser/OCR seams mocked (fast, deterministic) — including the OCR
  fallback branches and provenance persistence. Use these seams when you need to
  simulate a scanned PDF without real OCR.
- **Gates:** `python -m pytest -q`, `node --test tests/js/*.test.mjs`,
  `ruff check research_companion tests examples`.

---

## 10. Conventions

- Local-first: no new services or databases; persist as per-paper JSON.
- Fail honestly: surface real reasons (`IngestFailed`, `text_quality`), never a
  silent empty success.
- Provenance everywhere: keep absolute char offsets flowing from sections →
  chunks → citations so answers can be verified against the source span.
- Keep heavy/optional imports lazy so a base install stays lean and offline.

---

## 11. The review-side deterministic checks (the "add a checker" pattern)

The review team's integrity checks — reference validation, statistical soundness
(planned), reproducibility, ethics declarations, severity ranking, venue-fit — all
follow one repeatable shape. If you are adding a new deterministic check, copy it:

1. **A pure logic module** — network-free, LLM-free, fully unit-testable, with
   char-span provenance where it flags text. Examples:
   `research_companion/refcheck/` (bibliography validation),
   `research_companion/reproducibility.py` (code/data-availability scan),
   `research_companion/ethics.py` (integrity-declaration detection),
   `research_companion/venues.py` (venue KB + `topic_overlap`, loaded from the
   packaged `research_companion/data/venues.json` — extend the KB by editing JSON,
   no code change).
2. **A thin `Agent`** in `research_companion/agents/` that wraps the pure module,
   reads the paper from the blackboard, publishes a `Finding` on the `Bus`, and
   returns its result in `AgentResult.data`. Model it on
   `agents/benchmark.py` (deterministic) — e.g. `agents/reproducibility.py`,
   `agents/ethics.py`, `agents/severity.py` (`rank_findings`),
   `agents/venuefit.py`. Wire it into the `review` DAG in `cli.py::_cmd_review`
   (always-on for cheap deterministic checks; gate behind a flag only when it costs
   an LLM call or a required argument, as `venuefit` does behind `--venue`).
3. **Report rendering** — extend `report.py` (`build_report_json` + the HTML) with
   the check's section. `severity.rank_findings()` classifies the collected signals
   critical/major/minor and renders them worst-first at the top.
4. **Tests** — deterministic golden tests per module (`tests/test_reproducibility.py`,
   `tests/test_ethics.py`, `tests/test_severity.py`, `tests/test_venues.py`,
   `tests/test_venuefit.py`) plus an agent-wiring test
   (`tests/test_agents_*.py`) and a `report.py` inclusion test.

The honesty line is binding: report only what you compute (a "reporting
inconsistency" or a "missing declaration", never "misconduct" or "plagiarism");
skip ambiguous cases rather than guess.
