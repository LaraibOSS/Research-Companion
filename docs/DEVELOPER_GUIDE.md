# Developer Guide — the ingestion pipeline

This guide is for contributors. It explains how a PDF becomes searchable,
graphed, verifiable knowledge inside Research Companion — module by module —
and how to extend or test that path. For the user-facing behavior, see
`docs/USER_MANUAL.md`.

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
(Statcheck/GRIM), reproducibility, ethics declarations, near-duplicate/overlap,
severity ranking, venue-fit — all follow one repeatable shape. If you are adding a new deterministic check, copy it:

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

---

## 12. Domain connectors (add a scholarly source)

A connector lives in `research_companion/connectors/` and implements the
`Connector` protocol (`base.py`): `resolve(ref)` for citation verification,
`search(query, *, limit)` for prior art, and `fetch_fulltext(ident)` for OA
text. Network stays in injectable `_*` functions (tests monkeypatch them);
parsers are pure. Register the class in `CONNECTORS` (`connectors/__init__.py`)
and add its name to the settings validation set. Connectors are opt-in
(`settings.connectors`, off by default), so the tool is byte-identical when
none are enabled. Ships today: `europepmc.py` (primary), `pubmed.py`, and
`dblp.py` (`name="dblp"`) — the authoritative CS bibliography; `resolve` +
`search` against the free, key-free DBLP API, but metadata-only:
`fetch_fulltext` always returns `None` (DBLP has no full text). A good
reference for a metadata-only connector implementation.

---

## 13. Graph enrichment — citation polarity + prior-art taxonomy

Two additive enrichments on top of the base cross-paper graph and the
prior-art lane, both built to **degrade to today's behavior** when their
inputs are absent (see `tests/test_graph_enrichment_degradation.py`).

- **Citation polarity sidecar** — `research_companion/agents/citation_polarity.py`
  (`CitationPolarityAgent`) classifies each `related_work` citation into
  `based_on` / `support` / `contrast` / `refutation` / `mention`, grounded by a
  verbatim evidence quote (`_verify_quote`); an unverified or out-of-vocabulary
  polarity is demoted to `mention`. The result is persisted per paper via
  `store.save_citation_polarity` to `citation_polarity.json` (not inline on
  `extraction.json`, so it can be recomputed independently) and read back with
  `store.load_citation_polarity`.
- **`build_graph` attach** — `research_companion/graph.py` reads the sidecar
  (`load_citation_polarity(meta.paper_id)`) while building `cites` edges and
  sets `attrs["polarity"]` only when a mapping entry exists for that citation
  string; with no sidecar the edge is exactly the untyped `{"relation":
  "cites"}` edge from before. `serialize_graph` and `graph_stats` mirror
  this: an edge only gets a `"polarity"` key, and `graph_stats` only gets
  `edge_cites_<polarity>` sub-counts, when the underlying edge data actually
  carries a polarity.
- **Prior-art taxonomy** — `research_companion/taxonomy.py` is a pure,
  network-free, LLM-optional module: `cluster_papers` groups prior-art papers
  into connected components by keyword-overlap Jaccard (deterministic, no
  LLM), and `build_taxonomy` labels each cluster (keyword label by default, or
  an LLM one-liner when an `llm` callable is passed — any LLM failure falls
  back to the keyword label). A single component or all-singletons collapses
  to one `"Related work"` group rather than a degenerate one-cluster-per-paper
  tree.
- **`TaxonomyAgent`** — `research_companion/agents/taxonomy.py`, modeled on the
  checker-agent pattern in §11: depends on `priorart`, converts the retrieved
  papers to plain dicts, calls `build_taxonomy` (passing `ctx.data.get("_llm")`
  straight through — `None` means keyword labels, never a fabricated default),
  and returns `{"groups": [...], "count": N}` in `AgentResult.data`.
- **Rendering** — `report.py` renders a "Citation Stance" section from the
  `citation_polarity` lane and a "Prior-art taxonomy" nested list from the
  `taxonomy` lane, both purely additive: when those lanes are absent (or the
  report predates them), neither heading appears in the rendered HTML.

---

## 14. Desk-reject compliance linter (structured venue rules)

`research_companion/compliance.py` is another instance of the §11 "add a
checker" pattern, applied to venue submission rules instead of paper content:

- **Pure checks** — `check_compliance(venue, *, fulltext, sections=None,
  abstract=None, references=None, page_count=None)` runs five independent,
  network-free checks (page limit, abstract word limit, required sections,
  anonymization leaks, citation completeness) and returns
  `{"venue", "checks", "counts", "disclaimer"}`. Each check reads its own
  `Venue` field and self-skips (`status: "skipped"`) when that field is unset
  or its input is missing, rather than guessing or erroring — a
  partially-populated venue KB degrades to fewer checks, never a crash. A
  finding's `severity` is always `"desk_reject"` or `"warning"`; every result
  carries the fixed `DISCLAIMER` that KB rules are approximations to verify
  against the venue's current CFP.
- **Structured venue fields** — `research_companion/venues.py`'s `Venue`
  dataclass carries the rule fields the checks read: `page_limit`,
  `abstract_word_limit`, `required_sections` (a tuple of synonym-group
  tuples, e.g. `(("limitations", "broader impact"),)`), and `anonymized`.
  All default to "unset" (`None` / empty / `False`), so existing venues in
  `research_companion/data/venues.json` need no migration — add the fields to
  a venue entry only when you know the venue's actual rules; the linter skips
  the rest.
- **`ComplianceAgent`** — `research_companion/agents/compliance.py`, gated
  behind `--venue` like `venuefit` (§11): with no venue it returns an empty,
  always-`ok` result rather than running; with a venue it loads sections/
  abstract/references/PDF page count from the store and calls
  `check_compliance`. Wired into `review`'s DAG in `cli.py::_cmd_review` and
  exposed standalone via the `check-compliance` CLI command
  (`cli.py::_cmd_check_compliance`).
- **Rendering + degradation** — `report.py` renders a "Venue compliance
  (desk-reject linter)" section from the `compliance` lane; when that lane is
  absent from the report (no `--venue` was passed), no such heading appears —
  see `tests/test_compliance_degradation.py` for the characterization test.

## 15. Submission-readiness synthesis

`research_companion/readiness.py` is report-level, not a pipeline agent: it
runs inside `report.build_report_json` (never in the DAG in `cli.py`) and has
no `Agent` wrapper. `build_readiness(lanes)` is a pure function — no LLM, no
network — that reads whichever SOURCE lanes are present in the report's
`lanes` dict (`compliance`, `citation`, `novelty`, `reproducibility`,
`ethics`, `statsoundness`, `venuefit`, `overlap`) and synthesizes one verdict
plus a prioritized, cross-lane action list.

- **Per-lane extractors** — one pure `_extract_<lane>(data)` function per
  source lane turns that lane's already-computed result into zero or more
  `{"lane", "severity", "title", "action"}` items. Each extractor only reads
  fields the lane already produces; it never re-derives or re-scores
  anything.
- **The deterministic blocker principle** — only `_extract_compliance` can
  emit `severity: "blocker"`, and only for a `desk_reject`-severity finding;
  every other extractor emits `"warning"` at most. The derived `severity`
  lane (heuristic critical/major/minor ranking) is deliberately **not** read
  here — reading it would double-count findings already surfaced elsewhere
  and let a heuristic score gate the verdict. `novelty` IS read directly.
  `verdict` is `"not_ready"` if any blockers exist, else `"revise"` if any
  warnings exist, else `"ready"`.
- **Coverage caveats, not fabricated findings** — lanes that didn't run
  (absent, `--fast`/no `--venue`, or `ok: False`) are reported honestly in
  `coverage.{ran,not_run,failed}` and folded into the summary sentence (e.g.
  "novelty lane not run — remove --fast"); they never produce a blocker or
  warning item, since there is nothing to report.
- **Degradation** — `build_readiness({})` and the no-source-lane case both
  return `{}`; `build_report_json` only sets `report["readiness"]` when the
  result is truthy, and `render_report_html` only emits the "Submission
  readiness" banner when that key is present. See
  `tests/test_readiness_degradation.py` for the characterization test.

## 16. Semantic (paraphrase) overlap

`research_companion/semoverlap.py` complements the lexical shingler in
`overlap.py` with an opt-in embedding pass: instead of matching shared
n-grams, it compares passage embeddings by cosine similarity, catching
reworded or translated reuse that shingling can't see.

- **Pure math over injected vectors** — `semantic_near_duplicate_passages`
  and `merge_overlap_results` never touch an embedding model or the network;
  they take already-computed vectors (or already-computed findings) as
  arguments, so every test runs offline with fakes and never imports
  `sentence_transformers` or `numpy`. `_best_matches` uses a numpy matrix
  multiply when numpy happens to be importable, with a byte-identical
  stdlib-loop fallback otherwise.
- **`embed.resolve_embedder(*, model, allow_remote, token=None)`** —
  resolves a batched embedding backend in a fixed order: local
  `sentence-transformers` (`_load_local_model`, import-guarded) first; if
  that's unavailable, the Hugging Face Inference API, but **only** with both
  `allow_remote=True` *and* a token (`HF_TOKEN` or explicit); otherwise
  `None`, and the caller skips the semantic pass entirely. Loading the local
  model downloads the model **weights** from the HF hub on first use (cached
  thereafter) — the local path is not offline on first run, but it never
  sends passage *text* anywhere. The remote path sends both the draft's and
  the library's passage text to the HF API — that's the scope of the
  consent, not just the draft.
- **`semoverlap.collect_semantic_findings(paper_id, corpus_ids, *, embed_fn,
  embed_model, threshold=..., min_chars=...)`** — the single orchestration
  entry point shared by `agents/overlap.py::OverlapAgent._maybe_semantic`
  and the `check-overlap --semantic` CLI (`cli.py::_cmd_check_overlap`).
  I/O (embedding via `embed.embed_sections_with`, cache-aware) lives here;
  the comparison math stays pure in `semantic_near_duplicate_passages`.
  Exceptions propagate — each caller decides its own fallback.
  The per-paper `embeddings.json` cache is backend-agnostic by `embed_model` id:
  vectors cached from the HF API and vectors computed locally under the same
  model id are treated as compatible (same weights; sub-1e-6 float variance
  cannot move a 0.83 cosine decision).
- **Range-overlap dedupe** — `merge_overlap_results(lexical, semantic)`
  drops a semantic finding whose char range overlaps a *lexical* finding for
  the same matched paper (that region is already surfaced by the cheaper
  lexical check); semantic-vs-semantic overlaps are kept. The recomputed
  summary gains `n_semantic`.
- **Settings** — `semantic_overlap` (off by default), `semantic_overlap_allow_remote`
  (off by default), `semantic_overlap_threshold` (default
  `DEFAULT_SEMANTIC_THRESHOLD = 0.83`), validated in `settings.py`.
- **Degradation, pinned by tests** — with `semantic_overlap` off (the
  default), `OverlapAgent._maybe_semantic` returns the *same object* it was
  given (asserted with `is`), so the always-on overlap lane's output is
  byte-identical to before this feature existed. Any exception anywhere in
  the semantic path (no backend resolved, embedding failure, etc.) is
  swallowed and falls back to the lexical-only result — the always-on lane
  never crashes because of an opt-in pass. See the agent-side and CLI-side
  characterization tests for both the off-path identity and the
  failure-fallback behavior.

Like the lexical lane, semantic findings surface as `severity: warning` in the readiness synthesis — never a blocker, and never labeled "plagiarism" (the honest label stays *near-duplicate / paraphrase of library paper X*); only compliance desk-reject findings can block.

## 17. Readiness LLM narrative

`research_companion/readiness_narrative.py` is an opt-in LLM pass that sits on
top of the deterministic submission-readiness verdict from §15: a short
"reviewer's take" plus a prioritized fix plan, generated once per review and
attached to `report["readiness"]["narrative"]`. `readiness.py` itself is not
touched by this feature — it stays pure, no-LLM, no-network, exactly as
described in §15.

- **The grounding guardrail (dict-only diet)** — `generate_readiness_narrative`
  takes the already-built `readiness` dict and nothing else: no paper text, no
  lane internals, no retrieval. `prompts.format_readiness_narrative_prompt`
  serializes only that dict into the prompt, so the model can rephrase and
  reorder the existing `blockers`/`warnings` punch-list but has no channel to
  introduce a finding the deterministic lanes didn't already produce. This is
  the same "narrate, don't re-derive" discipline as `_extract_<lane>` in §15,
  one layer up.
- **The `{take, plan}` contract + caps** — `_validate` requires `take` to be a
  non-empty string and `plan` to be a list of strings, or the whole result is
  discarded (`None`). On success it truncates defensively even though the
  prompt already asks for bounded output: `take` to `_TAKE_MAX_CHARS = 800`
  chars, `plan` to `_PLAN_MAX_ITEMS = 6` items of at most
  `_PLAN_ITEM_MAX_CHARS = 300` chars each (blank items dropped before the
  slice). `_default_llm` requests `max_output_tokens=1024` from whichever
  provider (`RESEARCH_COMPANION_PROVIDER`) is configured.
- **Degrade to `None` everywhere** — no readiness, or a readiness with no
  blockers and no warnings (a clean "ready" needs no essay), returns `None`
  before the LLM is ever invoked (spy-tested: zero calls on the skip paths).
  Any failure past that point — missing provider key, network error, invalid
  JSON, wrong shape — is caught by a single broad `except Exception` in
  `generate_readiness_narrative` and also degrades to `None`. There is no
  partial narrative: it's the full `{take, plan}` dict or nothing.
- **The attach-once-before-persistence rule** — `cli.py::_attach_readiness_narrative`
  is gated on the `readiness_narrative` setting (default `False`), skipped
  when `args.fast` is set (no LLM lanes run under `--fast`), and skipped when
  the readiness dict has nothing to narrate. It mutates the already-built
  report's `readiness` dict in place, and is called exactly once on the `_rep`
  object built for the always-persisted store copy in `_cmd_review`; the
  `--report` path reuses that same `_rep` instead of rebuilding the report and
  calling the narrative a second time, so the persisted store report,
  `report.json`, `--json` output, and the HTML render all carry the identical
  narrative (or its identical absence). Any exception inside
  `_attach_readiness_narrative` is swallowed — the narrative is optional and
  never breaks the review.
- **Settings and test seam** — `readiness_narrative` (off by default),
  validated as a boolean in `settings.py`. Tests inject a fake LLM via
  `REVIEW_CONTEXT_OVERRIDES["_narrative_llm"]`, the same override-bag pattern
  used elsewhere in `cli.py` for offline, deterministic characterization
  tests — no real provider call is ever made in the suite.
- **Rendering is display-only** — the terminal summary and the HTML report
  render `narrative.take`/`narrative.plan` when present, but nothing
  downstream (suggestions, revision tracking, confidence scoring) reads
  `report["readiness"]["narrative"]`; removing it changes what a human reads,
  not what the tool decides. With the setting off, or on any failure, output
  is byte-identical to before this feature existed.

## 18. Cost-gated MCP tools (v2)

`ask_library` (cited LLM Q&A over the library) and `review_draft` (the
reviewer-style agent pipeline, read-only) extend the MCP trust-layer server
(`mcp_server.py` + `mcp_tools.py`, four deterministic key-free tools —
`verify_citation`/`ground_claim`/`citation_coverage`/`search_library`) beyond
those four. They are LLM-backed and therefore costed, so they only ever join
the server behind a **triple boundary**, and every call is still capped
individually.

- **The triple boundary** — `mcp_server.py::costed_tools_active()` is `True`
  only when *both* (a) the `mcp_costed_tools` setting is on (default `False`)
  *and* (b) `cost.configured_provider()` finds an LLM key matching the
  **resolved** provider (`RESEARCH_COMPANION_PROVIDER`, default `"anthropic"`,
  and its matching key env var — a key for the *other* provider does not
  count, since it would only fail at call time). `active_tool_names()`
  exposes the tool set `create_server()` would register right now without
  needing the `mcp` SDK installed, which is how the registration gating is
  unit-tested. With either half of the boundary off, `create_server()`
  registers only `TOOL_HANDLERS` (the original four); with both on, it also
  registers `COSTED_TOOL_HANDLERS` (`ask_library`, `review_draft`). A default
  `mcp serve` — the setting is off by default — is therefore byte-identical
  to the v1 (four-tool) server.
- **The per-call cap is the third gate, independent of the first two** —
  even with the boundary open, `mcp_tools.py` estimates each call's cost
  *before* doing any work and refuses (never raises) once the estimate
  exceeds `mcp_cost_cap_usd` (default `$1.00`, validated in `settings.py` to
  `[0, 100]`). The refusal shape is `{"error": "...", "estimated_cost_usd":
  <float>, "cap_usd": <float>}` — structured, not an exception, so a calling
  agent can branch on it. There is no spend ledger: the cap is evaluated
  per-call from a fresh estimate every time, with no running total across
  calls.
- **The estimate math (`cost.py` + `mcp_tools.py`)** — `cost.estimate_cost`
  prices `(input_tokens, output_tokens, provider)` off a small per-provider
  `PRICING` table (a coarse guardrail, not the provider's actual invoiced
  rate) and `cost.chars_to_tokens` applies the repo's standing ~4-chars/token
  heuristic. `ask_library`'s input estimate is `char_budget` (the
  `char_budget` setting, default 8000 — an upper bound on the context
  `qa.answer` assembles internally) plus the question's length, chars, at a
  fixed `_ASK_OUTPUT_TOKENS = 2048` output budget. `review_draft`'s estimate
  is lane-based: `fast=True` estimates `$0` (no LLM lanes run); otherwise
  `n_lanes = _N_LLM_LANES_FULL` (6 — novelty, citation_polarity, confidence,
  benchmark, severity, taxonomy) `+ 1` when a `venue` is given (the
  `VenueFitAgent` LLM lane), each lane capped at
  `_REVIEW_INPUT_CHARS_PER_LANE = 20_000` chars of the paper's fulltext
  (mirroring `NoveltyAgent`'s own fulltext cap) and
  `_REVIEW_OUTPUT_TOKENS_PER_LANE = 2048` output tokens. Both estimates use
  `_provider_for_estimate()` — the resolved provider from
  `cost.configured_provider()`, falling back to `"anthropic"` pricing if
  unresolved (estimate-only; the gate above already required a real key to
  reach this code). **Caveat for the novelty lane:** it issues one LLM call
  per extracted claim, so actual cost scales with claim count and can exceed
  the pre-call estimate — the cap is a safety rail, not a hard guarantee.
- **Restart asymmetry:** registration of costed tools is decided at server startup
  (`create_server`), but the cap (`mcp_cost_cap_usd`) is re-read on every call. Changing
  `mcp_costed_tools` or adding/removing the key does NOT change which tools a running
  server exposes — restart `mcp serve` for that; only cap changes apply live.
- **`review_runner.run_review` — read-only, async-safe** — a CLI-independent
  runner that mirrors `_cmd_review` in `cli.py`'s agent-list construction
  exactly (base 7 lanes, +6 LLM lanes unless `fast`,
  +`VenueFitAgent`/`ComplianceAgent` when a venue is given) but never writes
  to the store and never rebuilds the
  graph. It builds `Bus()` with **no** `EventLog` (unlike `_cmd_review`'s
  `Bus(log=EventLog(log_path))`), since `EventLog` persists a run to
  `<papergraph_dir>/runs/*.jsonl` on disk — a bare `Bus()` still gives agents
  a working pub/sub bus with no disk footprint. Context data uses the same
  seam keys as `REVIEW_CONTEXT_OVERRIDES` in `cli.py` (`_venue`, `_llm`,
  `_lookup`, `_search`), so tests inject fakes exactly as `test_cli_review.py`
  does. Because FastMCP may already be running its own event loop,
  `run_review` calls `asyncio.get_running_loop()` first: outside a loop it
  runs the pipeline with a plain `asyncio.run`; inside one, it runs the
  pipeline on a fresh loop in a one-worker `ThreadPoolExecutor` instead of
  raising `RuntimeError: asyncio.run() cannot be called from a running event
  loop`.
- **Never raises to the MCP caller** — both tools wrap their estimate step
  and their execution step in broad `except Exception` and return
  `{"error": str(exc)}` instead of propagating, so a missing key, a network
  failure, a malformed provider response, or an unknown `paper_id` degrades
  to a JSON error dict rather than crashing the server process.
- **v1/v2 schema files** — `docs/mcp-schemas/tools.v1.json` stays the
  unchanged four-tool set; `docs/mcp-schemas/tools.v2.json` is the six-tool
  superset (the same four plus `ask_library`/`review_draft`, documented as
  gated on the setting + key + cap). `mcp serve` itself always builds from
  the live registry (`TOOL_HANDLERS` + `COSTED_TOOL_HANDLERS` when active);
  the schema files are a static reference for agent authors, not something
  the server reads at runtime.

## 19. The reader's "Original (PDF)" tab

The reader (`research_companion/lab/static/js/components/reader.js`) shows a
paper two ways: **Original** (the typeset PDF, rendered by a vendored PDF.js
viewer) and **Text** (the existing exact-offset extracted-text view,
unchanged). Original is the default tab for any paper with a stored PDF; a
paper with no PDF gets the Text tab only, byte-identical to before this
feature.

### Architecture

- **Pure helpers** — `research_companion/lab/static/js/readerPdfHelpers.js` is
  DOM-free and unit-tested under `node:test`
  (`tests/js/readerPdfHelpers.test.mjs`):
  - `buildViewerUrl(paperId, { quote })` builds the same-origin viewer URL
    (`/static/vendor/pdfjs/web/viewer.html?file=<paper PDF URL>`), appending a
    `#search=<phrase>&phrase=true` fragment — PDF.js's own find-controller
    query syntax — only when a normalized quote is non-empty.
  - `normalizeQuoteForSearch(quote)` turns an evidence quote into a search
    phrase PDF.js can actually match: collapses whitespace, heals line-break
    hyphenation (`word-\nword` → `wordword`), strips wrapping quote
    marks/ellipses, and caps the result at 12 words (a long quote rarely
    matches as one contiguous PDF text run, so search on a short anchor
    instead).
  - `readerTabs(hasPdf)` returns `{ tabs, active }` — `['original', 'text']`
    with `active: 'original'` when the paper has a PDF, `['text']` with
    `active: 'text'` otherwise. This is the single source of truth for tab
    defaulting; the component never computes it inline.
  - `findMissState(events, timeoutFired)` reduces a list of PDF.js find
    events into `'found' | 'missed' | 'pending'` — see below.
- **The component** (`components/reader.js`) renders the tab strip only when
  `readerTabs(...).tabs.length > 1`, lazily creates a same-origin `<iframe>`
  pointed at `buildViewerUrl(...)` the first time the Original tab is
  activated, and never recreates it on subsequent tab flips within the same
  reader open — flipping tabs just toggles `hidden` on the PDF pane vs. the
  text body.

### Quote → in-PDF highlight, and honest miss detection

When the reader is opened with a quote (e.g. clicking a verified evidence
quote on an alignment card, or a citation chip), the Original tab's iframe
loads with the `#search=...&phrase=true` fragment, which drives PDF.js's own
find controller to search and highlight on load — no page-guessing, no
custom rendering of PDF content.

Because the fragment search runs asynchronously inside the vendored viewer,
the reader listens to `window.PDFViewerApplication.eventBus` inside the
iframe (reached via `iframe.contentWindow`, guarded with `try/catch` for any
cross-origin/attachment failure) for `updatefindmatchescount` and
`updatefindcontrolstate` events, and folds them through `findMissState`. If
no match is confirmed within `PDF_MISS_TIMEOUT_MS` (4000 ms), a muted,
dismissible notice appears in the PDF pane: *"Couldn't locate this quote in
the PDF — the Text tab has it highlighted."* This is best-effort — it never
claims the quote will always be found, and it degrades to just showing the
PDF unhighlighted rather than failing the tab.

**Failure mode:** if the iframe's `load` event fires but
`PDFViewerApplication` never attaches within `PDF_INIT_GRACE_MS` (500 ms), or
the iframe fires its own `error` event, the reader treats the viewer as
failed: it auto-switches to the Text tab and shows an error toast ("PDF
viewer failed to load — showing text view"). The Text tab is always
byte-identical to the pre-existing reader, so this is a safe fallback, not a
degraded experience.

### The vendor directory contract

`research_companion/lab/static/vendor/pdfjs/` vendors a **trimmed subset** of
Mozilla's official prebuilt `pdfjs-<version>-dist.zip` release asset — files
are copied as-is from the release archive, nothing rebuilt or modified. It is
served same-origin at `/static/vendor/pdfjs/web/viewer.html` (same no-cache
`Cache-Control` convention as the rest of `lab/static/`) so there is no
cross-origin iframe, no CDN dependency, and no network call at read time.

- **`VERSION.txt`** (in that directory) is the source of truth: it records
  the pinned version, the exact release-asset URL it was fetched from, and
  the full list of what was kept vs. trimmed from the release archive (with
  the reason for each trim — mostly source maps and the rarely-needed
  scripting sandbox bundle). Read it before touching anything under
  `vendor/pdfjs/`.
- **`LICENSE`** — the Apache License 2.0 text, kept in-tree per pdf.js's own
  license terms.
- **Packaging** — `pyproject.toml`'s `[tool.setuptools.package-data]` includes
  `"lab/static/vendor/pdfjs/**/*"` as its own nested glob (in addition to the
  existing `lab/static/vendor/*`, which does not recurse into
  subdirectories), so the whole vendored tree ships inside both the wheel and
  the sdist. `tests/test_packaging.py::test_pdfjs_viewer_covered` pins that
  the viewer HTML and the worker script are each covered by some glob, and
  the CI workflow (`.github/workflows/ci.yml`) additionally builds a real
  wheel and sdist and asserts `lab/static/vendor/pdfjs/web/viewer.html` is
  actually present inside the installed package — a packaging-glob typo would
  fail CI, not just look right in the source tree.
- **Serving** — `tests/test_lab_api.py::TestStaticMount::test_vendored_pdfjs_viewer_served`
  pins that `GET /static/vendor/pdfjs/web/viewer.html` returns 200 with the
  same `no-cache` header as other static assets.

### Upgrading the vendored PDF.js version

There is no fetch script — this is a deliberate one-time-per-upgrade manual
step, not an automated dependency:

1. Download the new release asset from Mozilla's releases page:
   `https://github.com/mozilla/pdf.js/releases/download/v<X.Y.Z>/pdfjs-<X.Y.Z>-dist.zip`.
2. Replace the vendored subset under `lab/static/vendor/pdfjs/`, preserving
   the same directory layout (`build/`, `web/`, `web/cmaps/`,
   `web/standard_fonts/`, `web/locale/en-US/`) and the same trim list
   recorded in `VERSION.txt` (drop `*.map` files, `pdf.sandbox.mjs`,
   `web/debugger.*`, the bundled sample PDF, and every locale directory
   except `en-US`) — re-verify the trim list against the new release in case
   file names or sizes changed.
3. Update `VERSION.txt`: the version number, the release URL, and the kept/
   trimmed lists if anything about the archive's contents changed.
4. Run the full gate (below) — it re-checks packaging coverage and serving,
   but not that the viewer actually renders a PDF, which is a manual step.
5. Manually verify: open the Lab, open a paper that has a PDF (Original tab
   should be the default and load), and click a verified evidence quote to
   confirm it still gets located and highlighted in the new viewer version.

### Testing split

Pure logic (`readerPdfHelpers.js`) is fully covered by
`tests/js/readerPdfHelpers.test.mjs` under `node:test` — URL building, quote
normalization, tab defaulting, and miss-state reduction are all exercised
without a browser. The DOM-dependent parts (iframe creation, tab switching,
`eventBus` wiring, load-failure fallback) are not unit-tested — they depend
on the real PDF.js viewer's runtime behavior inside an iframe — and are
verified manually per the upgrade procedure above and whenever
`components/reader.js` changes in this area.

## 20. Finding open-access PDFs online

When a paper's PDF can't be downloaded (a paywalled DOI, an S2 entry with no
direct file), `research_companion/oa_locator.py` gives it one more chance by
asking the open-access aggregators the tool already trusts for either a
direct PDF or a landing page you can follow yourself. It never scrapes a
paywall and never bypasses one — only open, key-free aggregator APIs and
plain links.

### The locator

`locate_pdf(meta, *, settings=None, providers=DEFAULT_PROVIDERS, extra_ids=None) -> OaLocation(pdf_url, links, source)`:

- **Provider order (stops at the first direct PDF):** `s2` (Semantic
  Scholar's `openAccessPdf` field) → `unpaywall` (only when the paper has a
  DOI **and** the `contact_email` setting is non-empty) → `openalex` (a DOI
  lookup, or a title search when there's no DOI) → `arxiv` (only for an
  arXiv id an *earlier* provider just surfaced — e.g. S2's
  `externalIds.ArXiv` field — never the paper's own arXiv id, which the
  caller would already have tried directly).
- **Links stop accumulating once a PDF is found.** The loop checks
  `pdf_url is not None` at the *top* of each iteration, so a provider whose
  own turn finds the PDF still contributes its own landing-page link first
  (each branch calls `add_link(...)` before checking whether it got a
  `pdf_url`), but every later provider in the order never runs at all — no
  fetch, no link (`tests/test_oa_locator.py::test_locate_stops_at_first_pdf`
  asserts `calls == ["s2"]` when `s2` hits: `unpaywall`/`openalex` are never
  even called). Separately, and unconditionally after the loop exits either
  way, `locate_pdf` appends a `"DOI page"` link (when there's a DOI) and a
  `"Google Scholar"` search link (when there's a title) — both pure string
  formatting, no HTTP call, so they're present on a hit or a miss. A caller
  that only wants the direct PDF reads `pdf_url`; a caller building a "try
  these instead" UI reads `links`.
- **Identifiers** come from `meta.paper_id`'s namespace prefix
  (`doi:`/`arxiv:`/`s2:`, via `_derive_ids`), overlaid with any `extra_ids`
  the caller already resolved (e.g. `fetch.add_s2` passes the DOI/arXiv ids
  Semantic Scholar's own metadata surfaced, so the locator doesn't have to
  re-discover them).
- **Seams:** every network call lives in a module-level `_fetch_s2` /
  `_fetch_unpaywall` / `_fetch_openalex` function, all routed through
  `_get_json`, which wraps the request in a single broad `except Exception`
  and returns `None` on **any** failure — bad status, timeout, malformed
  JSON, whatever. Parsers (`_parse_s2`, `_parse_unpaywall`, `_parse_openalex`)
  are pure functions over already-fetched dicts. Tests monkeypatch the
  `_fetch_*` functions directly and never touch the network — see
  `tests/test_oa_locator.py`.

### Etiquette

- **≤3 HTTP GETs per lookup.** `s2`, `unpaywall`, `openalex` each cost at
  most one GET, and the loop stops at the first direct `pdf_url`; `arxiv`
  never makes a request — it only formats a URL from an id another provider
  already returned. Worst case (no hit anywhere) is exactly one GET per one
  of those three providers, three total.
- **`contact_email` is the polite identifier.** Unpaywall's API requires a
  contact email on every request; rather than send a placeholder, the
  locator skips the Unpaywall step entirely when the `contact_email` setting
  (`settings.py`, default `""`) is empty — s2/openalex/arxiv still run. This
  is the *only* provider the setting affects.
- **1s spacing between papers in a batch.** The sweep endpoint (below) awaits
  `asyncio.sleep(1.0)` between targets so a "find all" run doesn't hammer the
  aggregator APIs back-to-back for a whole library's worth of failures.

### Everything degrades

Any failure anywhere in the locator — a provider down, a malformed response,
an unresolvable identifier — means *that provider contributes nothing*, not
a crash: `_get_json` catches it and returns `None`, the parser sees `None`
and returns an all-`None` dict, and `locate_pdf` moves on to the next
provider (or returns an `OaLocation()` with no `pdf_url` and no `links` if
every provider whiffed). Callers add a second belt: `fetch.add_doi` and
`fetch.add_s2` (`fetch.py`) call `locate_pdf` inside their own
`try/except Exception: OaLocation()` **after** their direct download attempt
(DOI URL / arXiv+DOI) fails, so even a bug inside the locator can never
break the add path — it falls back to the metadata-only save with the exact
same warning text as before this feature (`tests/test_fetch.py`'s
`test_add_doi_locator_exception_falls_back_to_metadata_only` /
`test_add_s2_locator_exception_falls_back_to_metadata_only` pin this
byte-identically).

### Wired into ingest, the Lab, and the sweep

- **`fetch.add_doi` / `fetch.add_s2`** consult the locator only as a
  fallback after their own direct attempt fails — same behavior as always
  when the direct attempt already succeeds.
- **`POST /api/papers/{id}/find-pdf`** (`lab_api.py`) locates a PDF for one
  already-failed paper: `404` when there's no failure record for that id at
  all, `409` when the failure isn't a missing-PDF one (`_is_missing_pdf_failure`
  — mirrors `lab/static/js/libraryHelpers.js`'s `isMissingPdfFailure`, the
  same two wordings, "no PDF on disk" / "PDF not found" — reused rather than
  re-implemented so the button's visibility and the endpoint's gate never
  drift apart). Otherwise it returns `202` with a job id. A **hit** downloads
  the PDF, saves it, and re-runs `_retry_paper_task` — the same retry-flow
  job `/retry` uses, not a separate ingest path. A **miss** (`_FindPdfMiss`,
  raised by `_find_pdf_for_failure`) persists the located `links` onto the
  failure record via `store.record_failure` (a read-modify-write that
  preserves the original `error`/`stage`/`paper_id`) as `oa_links`, publishes
  an `IngestFailed` so the Library card re-renders with them, and completes
  the job `"done"` (not `"failed"`) with detail
  `"no open-access PDF found (N links)"` — a miss is a completed search, not
  an error.
- **`POST /api/papers/find-pdfs`** sweeps every missing-PDF failure
  sequentially, 1s apart (see Etiquette). It's registered *before* the
  `{paper_id:path}` routes so `"find-pdfs"` is never captured as a paper id
  (the same ordering trick as `POST /api/papers/upload`).
  `app.state.find_pdf_sweep_running` guards against overlapping sweeps
  (`409` while one is running, set synchronously before the background task
  starts); `{"count": 0}` (200) when there's nothing to do; one paper's
  miss/error never stops the rest.
- **Summary plumbing:** `_build_paper_summary` (`lab_api.py`) reads
  `oa_links` off the matching failure record and includes it on every
  `GET /api/papers` entry, so the Library can render the links line without
  a second request.

### UI

`research_companion/lab/static/js/oaLinkHelpers.js` is the pure, DOM-free
layer (`node:test`-covered in `tests/js/oaLinkHelpers.test.mjs`):

- `findPdfAffordance(paper)` → `'hidden' | 'button' | 'button-with-links'`,
  gated on `status === 'failed'` and `isMissingPdfFailure(paper.failure_reason)`.
- `oaLinksLine(links)` validates and caps the list at 5 entries, dropping
  anything that isn't `{label: string, url: http(s)-string}` (blocks
  `javascript:` and other unsafe schemes a malformed locator response might
  carry).
- `pollDecision({status, error, consecutiveFailures, elapsedPolls})` drives
  the job-poll loop in `views/library.js`: bounded to `MAX_POLLS = 120`
  (~2 minutes at roughly 1 poll/second), gives up after
  `MAX_CONSECUTIVE_FAILURES = 5` in a row, and a `404` always stops
  immediately (the job record is gone) even if the poll-count cap was also
  hit.

Both `components/paperCard.js` (grid) and `views/library.js` (list) render
the same affordance from these helpers: a **Find PDF** button next to
**Upload PDF** on a failed, missing-PDF paper, and — once a search has come
back with a miss that still found candidate links — a muted
*"Not freely available — try:"* line with up to 5 links (`target="_blank"
rel="noopener"`). The Library header's **"Find PDFs for all missing (n)"**
button posts to the sweep endpoint and is recomputed (count, visibility,
enabled state) on every papers refresh. Settings gained a **Contact email**
field (`contact_email`, empty by default) wired straight to the setting
above — the UI hint is explicit that leaving it blank only skips the
Unpaywall lookup, nothing else.

## 21. The reader's "Simplified" tab

A third reader tab turns a paper's **existing analysis** into plain-English
bullets — no new LLM call, no network, on by default the moment a paper has
been analyzed. An optional **"Simplify further"** button asks the LLM for a
tighter rewrite, once, cached to disk. The tab is a *display-only*
comprehension aid: nothing it produces ever feeds Ask, Draft, or citations.

### Tab defaulting

`readerTabs(hasPdf, hasSimplified = false)`
(`research_companion/lab/static/js/readerPdfHelpers.js`) grew a second
parameter and now returns three shapes:

- `hasPdf` → `{ tabs: ['original', 'simplified', 'text'], active: 'original' }`
  — Original stays the default for any paper with a stored PDF, unchanged
  from §19.
- `!hasPdf && hasSimplified` → `{ tabs: ['simplified', 'text'], active:
  'simplified' }` — a paper with no stored PDF at all (added by DOI or
  Semantic Scholar ID whose download failed; a scanned PDF still has a stored
  file and keeps the Original tab, so it never reaches this branch) lands on
  Simplified once it has been analyzed.
- `!hasPdf && !hasSimplified` → `{ tabs: ['simplified', 'text'], active:
  'text' }` — an un-analyzed, PDF-less paper still gets the tab (so the
  empty-state copy and the Simplify path are reachable), but defaults to Text
  since there is nothing to show yet.

`hasSimplified` is `!!(simplifiedResponse && simplifiedResponse.has_extraction)`
— the component (`components/reader.js`) has to prefetch `GET /simplified`
for PDF-less papers *before* it can pick a default tab, since `has_extraction`
isn't part of the `/text` payload. PDF papers skip this prefetch entirely:
they always default to Original regardless of analysis state, so the extra
GET would be wasted.

### Pure model — `readerSimplifiedHelpers.js`

DOM-free, `node:test`-covered (`tests/js/readerSimplifiedHelpers.test.mjs`):

- **`simplifiedModel(extraction)`** turns a stored `extraction.json` payload
  into `{ groups: [{ title, bullets: [{ text, sectionId }] }] }`. Exactly four
  possible groups, always in this order, each omitted entirely when empty:
  - **"What this paper is about"** ← `concepts` (`name — definition`)
  - **"Key claims"** ← `claims` (`text`)
  - **"How they did it"** ← `methods` (`name — description`) followed by
    `datasets` (`"Dataset: " + name — description`) in the same group
  - **"What they found"** ← `results` (`metric: value (dataset)`, the
    parenthetical omitted when there's no dataset)
  - `related_work` is never read — it's citation data, not something to
    summarize as a finding.
  - Never throws: `null`/non-object input, or an extraction with none of the
    five keys, yields `{ groups: [] }`; any bullet missing its own text is
    dropped rather than rendered blank.
- **`simplifiedDisplayState({ hasExtraction, rewrite, providerConfigured })`**
  → `{ view: 'auto' | 'rewrite' | 'empty', showButton }`. `view` is
  `'rewrite'` whenever a cached rewrite object is truthy (regardless of
  `providerConfigured` — an already-cached rewrite still displays even if the
  key was since removed), else `'auto'` when there's an extraction, else
  `'empty'`. `showButton` is `providerConfigured && hasExtraction`, and it
  gates only the **standalone** "Simplify further" button
  (`reader.js`'s `standaloneButtonHtml`, shown when `view !== 'rewrite'`) —
  it never runs when there's nothing to feed the summarizer. The rewrite
  view's **"Regenerate"** button is a separate, deliberately looser gate:
  `resp.provider_configured` alone (`reader.js`, the `provenanceParts`
  block), with no `hasExtraction` check. A cached rewrite can outlive its
  extraction — a prompt-sha bump invalidates `load_extraction` while
  `simplified.json` still holds an older rewrite (the same situation the
  adjacent "Show auto summary" toggle's `resp.has_extraction` check
  documents) — and regeneration doesn't read `extraction.json` at all; the
  simplify job walks the paper's stored sections directly (see below), so
  there both is a rewrite to look at and a way to regenerate it even when
  `hasExtraction` is false. Gating Regenerate on `hasExtraction` too would
  incorrectly hide the button in exactly that case.

### Component wiring — `components/reader.js`

- **Lazy fetch, cached per open.** `GET /simplified` is fetched at most once
  per reader open: eagerly for PDF-less papers (needed for tab defaulting,
  see above), otherwise lazily on the Simplified tab's first activation
  (`_ensureSimplifiedPane`). The response is cached in module state
  (`_simplifiedData`) and reset on every `_renderContent` / `_close` so one
  paper's cached view can never bleed into the next paper opened in the same
  reader instance.
- **Section links.** A bullet's `sectionId` renders as a link to the Text tab
  labeled with that section's nav label (`"n. Title"`) when the id is still
  present among the *current* reader's sections; otherwise it renders a
  plain, non-clickable `<span>` with the raw id — clicking a link for a
  section that no longer exists would call the nav's `_setActive` with an id
  matching nothing, clearing every active highlight instead of navigating
  anywhere (fixed in 1b121e6). `_normalizeRewriteGroups` is the single place
  the server's `section_id` key is renamed to the client's `sectionId`, so a
  cached rewrite's bullets render through the exact same
  `_renderSimplifiedBullet` path as the auto model's.
- **Empty state.** An un-analyzed paper (`has_extraction: false`) shows
  exactly: *"This paper hasn't been analyzed yet — run analysis from the
  Library to get the simplified view."*
- **Per-open generation guard.** The Simplified tab has three async
  continuations with no natural identity object to check against (unlike the
  PDF tab's `_pdfFrame` reference): the no-PDF prefetch, the lazy `/simplified`
  fetch, and the Simplify-further job poll. All three capture a
  `_readerGeneration` counter (minted once per `_open_()` call) and re-check
  it after every `await` before touching `_simplifiedData`, painting, or
  toasting — so a slow response from a superseded open (closed, or reopened
  onto a different paper, while the request was in flight) can never poison
  the paper that's actually on screen.

### "Simplify further" — one cached LLM call

- **`GET /api/papers/{id}/simplified`** (`lab_api.py`) never makes a network
  call: it loads `extraction.json` (via the existing `store.load_extraction`,
  keyed by the current `extraction_prompt_sha256()` so a stale extraction
  under a changed prompt is treated as absent) and `simplified.json` (via
  `store.load_simplified`), and reports `provider_configured` — key
  *presence* for the resolved pipeline provider, read the same way the
  Settings page's masked-key display does (`get_settings()["keys"]`), never
  by constructing an LLM client — 404 for an unknown paper. Response shape:
  `{extraction, rewrite, has_extraction, provider_configured}`.
- **`POST /api/papers/{id}/simplify`** starts a background job (kind
  `"simplify"`, the same job/poll machinery as every other Lab job — 409 when
  the paper has no stored text at all). The job walks the paper's sections in
  document order, packing text into the prompt up to the same
  `settings["char_budget"]` accessor `qa.answer` uses (`_simplify_char_budget`)
  — it deliberately ignores `k_sections` (that knob scopes *retrieval* to a
  query's top-k sections; a full-paper simplify has no query and wants every
  section, budget permitting) — and calls `_resolve_llm(json_mode=True)`, the
  same provider seam Ask uses, so "Simplify further" always talks to
  whichever provider/model you've configured, never a hardcoded one.
- **Prompt contract** (`_SIMPLIFY_PROMPT`): forbids adding any fact not in the
  supplied paper text, requires plain-English rewording of unavoidable
  jargon, and requires grouping under **exactly** the same four headings as
  the auto model ("What this paper is about" / "Key claims" / "How they did
  it" / "What they found"), omitting a heading only when the paper truly has
  nothing for it. Requested JSON shape:
  `{"groups": [{"title", "bullets": [{"text", "section_id"}]}]}`.
- **Markdown-fence tolerance.** The raw LLM response is passed through
  `extract._strip_code_fences` before `json.loads` (18671bb) — the same
  house convention the extraction pipeline already relies on for providers
  that wrap JSON in ` ```json ` fences despite `json_mode=True`.
- **Cache file contract** — `store.save_simplified` / `load_simplified` write
  and read `papers/<dir>/simplified.json`:
  `{"provider", "model", "created_at" (UTC ISO-8601, "Z" suffix), "groups"}`.
  `load_simplified` returns `None` (never raises) on a missing file, a
  corrupt/non-JSON file, or a JSON value that isn't an object — the reader
  treats a `None` rewrite identically to "no rewrite yet", never as an error.
  **Regenerate overwrites** the same file; a failed regenerate call leaves
  whatever was already cached untouched, since `save_simplified` is only
  reached after the LLM call and `json.loads` both succeed.
- **Isolation.** `simplified.json` is written and read in exactly one place
  each (`lab_api.py`'s two endpoints) plus rendered in `components/reader.js`
  — no other code path (Ask, Draft alignment, citation grounding, graph
  build) reads it. The rewrite is a comprehension aid for a human, not a
  source of truth the pipeline can cite.

### Testing split

Pure logic (`readerSimplifiedHelpers.js`'s grouping/ordering/empty-omission
and the four-way display-state matrix, plus `readerPdfHelpers.js`'s extended
`readerTabs`) is fully covered under `node:test`, no browser or server
involved. The endpoints are covered in `tests/test_lab_api.py` (both-source
GET shape, 404/409, job kind, fence-stripped parsing, cache overwrite,
failure-keeps-cache) and `tests/test_store.py` (round-trip and corrupt-file
handling for `save_simplified`/`load_simplified`). The DOM-dependent parts of
`components/reader.js` (tab painting, the section-link fallback, the
generation-token guard across all three async paths, the button/toggle
wiring) are smoke-tested via string assertions on the built JS in
`tests/test_lab_static.py` rather than a real DOM, the same convention §19's
PDF-tab wiring uses.

## 22. Uncited-paper opportunities + revision notes

Two small, deliberately dependency-free additions surface library papers your
draft *doesn't* cite but whose stored analysis says they'd help a section, and
let you turn any one of those suggestions into a persistent, checklist-style
revision note. Both are **display-only aids**: nothing here feeds back into
Ask, Draft alignment, strength, or citations coverage — they only *read*
those artifacts.

### Opportunities assembly — `research_companion/opportunities.py`

- **`uncited_paper_ids(draft_id) -> set[str]`** — every library `paper_id`,
  minus the draft itself, minus every `matched_paper_id` in
  `citations_coverage.compute_coverage(draft_id)["references"]`. Cited-but-
  unmatched references (no `matched_paper_id`) don't remove anything, so a
  paper only drops out once coverage has actually resolved it against the
  library — the same matching `lab_api.py`'s citation endpoints already
  trust.
- **`build_opportunities(draft_id | None) -> dict`** — `{"draft_id": None,
  "sections": []}` immediately when there's no draft (no store reads at
  all). Otherwise it mirrors `lab_api.get_draft_alignment`'s per-section
  assembly, but restricted to `uncited_paper_ids(draft_id)`: for each uncited
  paper it loads `store.load_alignment(paper_id, draft_paper_id=draft_id)`
  (skipped entirely when `None` — an uncited paper with no stored alignment
  contributes nothing) and, per aligned section, appends a suggestion
  carrying `relation`, `relevance`, `rationale`, `evidence` (verbatim from the
  alignment record — the same evidence blocks the Draft view's alignment
  cards already render) and `strength_band` from `store.load_strength`.
  Every field is copied from what an earlier `align` run already persisted;
  the function makes no LLM call and opens no network connection. Sections
  are keyed by `section_id`; a section with zero uncited-paper suggestions is
  omitted from the output entirely (no empty-array placeholder), and each
  section's `suggestions` list is sorted by `relevance` descending.
- **`GET /api/draft/opportunities`** (`lab_api.py`) resolves the active draft
  via `store.get_draft_paper_id()` and calls `build_opportunities` on a
  worker thread (`asyncio.to_thread`) — the same offloading pattern every
  other read-only Lab endpoint uses to keep the event loop free.
- Tested in `tests/test_opportunities.py`: cited-and-draft exclusion, output
  shape and relevance sort, empty-section omission, and the no-draft shape.
  `tests/test_lab_api.py`'s `/api/draft/opportunities` cases cover the HTTP
  layer on top.

### Notes store — `research_companion/notes_store.py`

A note is a structured, citable snapshot of one opportunity suggestion plus
an optional user comment — not a free-text scratchpad. It's workspace-scoped
(`papergraph_dir()/notes.json`, a flat JSON array), mirroring the
failures-store accessors (`record_failure` / `list_failures` /
`clear_failure`) already in `research_companion/store.py`.

- **Record shape** — `_FIELDS`: `draft_section_id`, `draft_section_title`,
  `paper_id`, `paper_title`, `relation`, `relevance`, `rationale`,
  `evidence_quote`, `evidence_section_id`, `comment`, `kind`,
  `source_excerpt`; plus server-assigned `id` (`uuid.uuid4().hex`),
  `created_at` (UTC ISO-8601, `Z` suffix), and `status` (`"open"` /
  `"done"` / `"dismissed"`, starting `"open"`). *(`kind` and
  `source_excerpt` were added in §23, which generalized the record beyond
  opportunity suggestions — see there for the current contract.)*
- **`save_note(record) -> dict`** dedupes on **(`paper_id`,
  `draft_section_id`)**: if an **open** note already matches, its fields are
  updated in place (so re-saving a refreshed suggestion doesn't pile up
  duplicates) rather than appended — except a blank incoming `comment` never
  blanks an existing one, so a re-save can't silently erase what the user
  typed. `relevance` is coerced through `_as_float` (falls back to `0.0` on
  anything non-numeric/`None`) both on write and again wherever
  `notes_to_markdown` sorts by it, since `relevance` is caller-supplied and
  the API boundary validates only `kind` and overall non-emptiness (see
  §23) — one bad record on disk must never 500 the whole list or export.
- **`update_note(note_id, *, status=None, comment=None)`** patches whichever
  fields are passed and returns `None` for an unknown id.
  **`delete_note(note_id) -> bool`** removes by id.
  **`list_notes() -> list[dict]`** returns `[]` on a missing or unparseable
  file rather than raising.
- **`notes_to_markdown(notes) -> str`** builds the entire "Revision notes"
  document server-side — the single source of truth (see the DRY note
  below). Dismissed notes are dropped first; the rest are grouped by
  `draft_section_title`, groups sorted alphabetically, notes within a group
  sorted by relevance descending; a `done` note renders `- [x]`, everything
  else `- [ ]`, and a non-empty `comment` is appended as `— note: ...`. An
  all-dismissed/empty note list still renders a valid doc (`_No notes yet._`
  under the heading) rather than an empty string.
- **Endpoints** (`lab_api.py`): `GET /api/notes` → `{"notes": [...]}`;
  `POST /api/notes` → `save_note(body)`, 400 only on an invalid `kind` or
  when `comment`/`paper_id`/`source_excerpt`/`evidence_quote` are *all*
  empty (relaxed in §23 — no longer requires `paper_id` +
  `draft_section_id`); `PATCH /api/notes/{note_id}` → 400 on an invalid
  `status` value, 404 unknown id; `DELETE /api/notes/{note_id}` → 404
  unknown id; `GET /api/notes/export` → `{"markdown":
  notes_to_markdown(list_notes(), group_by=...)}`, `group_by` an optional
  `?group_by=section|paper` query param added in §23 (defaults to
  `"section"`). *(§23 has the full rationale for the relaxed POST rule and
  the group_by param — this is the current contract, kept in sync here.)*
  **Route order matters**: `/api/notes/export` is registered *before*
  `/api/notes/{note_id}`, the same fix already applied to
  `/api/papers/find-pdfs` vs. `/api/papers/{paper_id:path}` — otherwise
  FastAPI would match `export` as a `note_id` path param.
- **DRY note vs. the original design sketch**: markdown is built exactly
  once, in Python, and pytest-covered; the client (`views/notes.js`) only
  downloads the string as a `.md` file. There is no parallel
  `notesToMarkdown` in JS — avoid reintroducing one if you're tempted to
  format notes client-side for a new view.
- Tested in `tests/test_notes_store.py` (id/status/timestamp assignment,
  dedupe including the comment-preservation edge case, update/delete,
  markdown grouping/checkbox/omission, relevance coercion surviving a bad
  on-disk record) and `tests/test_lab_api.py` (CRUD + export over HTTP,
  validation errors, the export-route-order regression).

### Frontend — `opportunityHelpers.js`, `views/draft.js`, `views/notes.js`

- **`opportunityHelpers.js`** is pure and DOM-free (`node:test`-covered in
  `tests/js/opportunityHelpers.test.mjs`), exporting two total functions
  (malformed input degrades to an empty/neutral result, never throws):
  `opportunityModel(sections)` normalizes `GET /api/draft/opportunities`'
  `sections` into `{sectionId, sectionTitle, count, suggestions: [{paperId,
  title, relation, relevance, rationale, quote, quoteSectionId,
  strengthBand}]}` (only the *first* evidence quote per suggestion is
  surfaced), and `noteRowModel(note)` maps a stored note record to Notes-view
  display fields (`relevancePct`, `badgeColor`/`badgeIcon` from the same
  relation→color/icon palette `views/draft.js` uses for stance chips).
- **`views/draft.js`** loads opportunities alongside alignment
  (`api.getOpportunities()`) in the same `_render()` pass; a failure here is
  non-fatal and just yields zero opportunity blocks, so it never blocks the
  already-working alignment view. The section list shows a lightweight
  `+n` count badge per section; the full block — rationale, relevance,
  relation badge, an evidence-quote button that dispatches `rc:open-reader`
  on the *uncited* paper at that quote, and a **Save note** button that
  `POST`s `/api/notes` — renders only for the currently-selected section, in
  the detail column, so it can't crowd out the narrow nav rows.
- **`views/notes.js`** (route `#/notes`) lists every note, each row built
  through `noteRowModel`. An editable comment `<textarea>` PATCHes on blur
  (only when changed); Mark done/Dismiss/Reopen call `PATCH {status}`;
  Delete calls `DELETE /api/notes/{id}`; **Export as Markdown** fetches
  `GET /api/notes/export` and downloads the returned string client-side as
  `revision-notes.md` (no client-side formatting — see the DRY note above).
  *(§23 generalized this view into a notebook — group-by Section/Paper,
  kind + status filter chips, New note — see there for the current shape;
  this paragraph describes only the pieces that haven't changed.)*
- Both views' markup and wiring are smoke-tested via string assertions in
  `tests/test_lab_static.py` (the same convention §19/§21 use), alongside the
  node-test coverage of the pure helpers.

## 23. Notes everywhere — generalized record, five entry points, notebook view

§22 shipped notes as one thing: a citable snapshot of an uncited-paper
opportunity suggestion, saveable only from the Draft opportunities block.
This generalizes the same store into a lightweight capture tool usable from
anywhere in the Lab, without weakening anything §22 already relies on — a
legacy on-disk note with no `kind` still reads back as `"opportunity"`, and
every §22 test still passes unmodified. Still **display-only**: nothing a
note captures is ever fed back into Ask, Draft alignment/strength, or
citation coverage.

### Generalized record — `research_companion/notes_store.py`

- **`kind`** — one of `"opportunity"`, `"alignment"`, `"reader"`, `"paper"`,
  `"ask"`, `"freeform"`, added to `_FIELDS` alongside a new
  **`source_excerpt`** (a verbatim snippet the *user* selected or the tool
  already produced — a Reader text selection, an Ask answer — never a new
  claim). Both anchors (`paper_id`, `draft_section_id`) that §22 required are
  now **optional**: an `ask` note may carry a `paper_id` (from its answer's
  top citation) with no section; a `reader`/`paper`/`freeform` note may carry
  either, both, or neither.
- **Backward compatibility** — `list_notes()` backfills any on-disk record
  missing a `kind` key to `"opportunity"` (`n.setdefault("kind",
  "opportunity")`) as it loads, so every note saved before this change reads
  back unchanged. `save_note()` itself defaults a record with no `kind` to
  `"freeform"` (the API layer already normalizes this before calling it —
  see below — so in practice this branch only matters for direct/legacy
  callers of the store function).
- **Dedupe stays narrow** — `save_note()`'s open-note dedupe on (`paper_id`,
  `draft_section_id`) now fires **only when both are truthy** on the
  incoming record. An `ask` note with only a `paper_id`, or a `freeform` note
  with neither anchor, always appends a new note instead of silently
  merging into an unrelated one — merging on a partial key would be wrong
  (e.g. two different `ask` notes about the same paper are two different
  answers, not one suggestion being refreshed).
- Tested in `tests/test_notes_store.py`: `test_kind_and_source_excerpt_persist`,
  `test_legacy_note_without_kind_defaults_to_opportunity`,
  `test_dedupe_only_when_both_anchors_present`,
  `test_markdown_group_by_paper_and_unfiled`.

### Relaxed POST + group-aware export — `lab_api.py`

- **`POST /api/notes`** no longer requires `paper_id` + `draft_section_id`.
  It 400s only on an invalid `kind` (must be one of the six above, defaulted
  to `"freeform"` when absent) or when **all four** of `comment`, `paper_id`,
  `source_excerpt`, `evidence_quote` are empty — i.e. a note must carry
  *something* (a paper reference, a captured excerpt/quote, or the user's
  own comment), but no specific combination is mandatory. This is what makes
  an anchorless `freeform` or `ask` note legal.
- **`GET /api/notes/export`** takes an optional `?group_by=section|paper`
  query param (defaulting to, and falling back on any other value to,
  `"section"`), passed straight through to `notes_to_markdown(notes,
  group_by=...)` — see §22's markdown grouping, now parameterized by
  `group_by="paper"` grouping on `paper_title` instead of
  `draft_section_title` (same `"Unfiled"` fallback key, same
  relevance-descending sort within a group). The markdown is still built
  exactly once, server-side, in Python — the DRY note in §22 still holds,
  there is no client-side `notesToMarkdown`.
- Tested in `tests/test_lab_api.py`: the relaxed-validation cases (comment-only,
  bogus-kind rejection, still-rejects-fully-empty) and
  `?group_by=paper`/`?group_by=bogus` export cases.

### Five entry points — `noteRecord.js` + four call-sites + `views/draft.js`

- **`research_companion/lab/static/js/noteRecord.js`** exports the single
  builder every "Save note" affordance now goes through:
  `buildNoteRecord(kind, data) -> record`. It's pure, DOM-free, and total —
  an unrecognized `kind` degrades to `"freeform"`, every field missing from
  `data` becomes `""` (relevance becomes `""`, not `0`/`NaN`, so an omitted
  relevance stays distinguishable from an explicit `0`). This is the one
  place surface-local field names (`paperId`, `sectionId`, `quote`,
  `sourceExcerpt`, ...) get mapped to the server's `_FIELDS` names — no
  call-site hand-builds a POST body.
- The five ways to reach `POST /api/notes`, all via `buildNoteRecord`:
  1. **Draft cited-alignment cards** (`views/draft.js`) — a **Save note**
     button beside each alignment card's evidence quote →
     `buildNoteRecord('alignment', {...})`.
  2. **Reader header** (`components/reader.js`) — a header **Save note**
     button reads `window.getSelection()` (guarded — it can throw or be
     absent in odd embeds) and posts the selected text as `sourceExcerpt` →
     `buildNoteRecord('reader', {...})`.
  3. **Any paper card** (`components/paperCard.js`) — a **Save note** button
     → `buildNoteRecord('paper', { paperId, paperTitle })`, no section/quote.
  4. **Ask answers** (`views/ask.js`) — a **Save note** button per answer
     posts the answer text (trimmed, capped at `ASK_NOTE_EXCERPT_MAX` chars)
     as `sourceExcerpt`, plus `paperId`/`paperTitle` from the answer's top
     citation if any → `buildNoteRecord('ask', {...})`. Guarded client-side
     against a rapid double-click (`btn.disabled`), since an `ask` note
     often has no `draft_section_id` and so can't rely on the server's
     both-anchors dedupe to absorb a duplicate.
  5. **Free-form** — a tiny inline `+ note` form per section row in the
     Draft view (`views/draft.js`'s `_toggleSectionNoteForm`) →
     `buildNoteRecord('freeform', { sectionId, sectionTitle, comment })`; and
     the **New note** button in the Notes view itself (see below).
  - Plus the pre-existing §22 **uncited-opportunity** Save note, now
    explicitly routed through `buildNoteRecord('opportunity', {...})` rather
    than a hand-built object — omitting this previously let the record
    silently default to `kind:"freeform"` server-side, breaking the Notes
    view's Opportunity filter (see the fix commit's note in `views/draft.js`
    around the alignment-card wiring).
- **`views/draft.js`**'s uncited-opportunities block now renders **expanded
  by default**: `_oppExpandedSections` is seeded with every section that has
  opportunities the first time they load (once per mount, gated so a user's
  own subsequent collapse/expand toggle is never overridden), rather than
  starting collapsed.
- Tested in `tests/js/noteRecord.test.mjs` (the builder, all six kinds,
  totality) and `tests/test_lab_static.py` (each surface's Save note markup
  and wiring present in the served HTML/JS).

### Notebook view — `opportunityHelpers.js` + `views/notes.js`

- **`noteRowModel(note)`** (extended from §22) now also carries `kind` and
  `sourceExcerpt` through to the display model, and tolerates a note with no
  `paper`/`section`/`relation` at all (an `ask` or `freeform` note) — those
  fields simply normalize to `''`/`null` like any other missing field; the
  relation badge falls back to a muted color with no icon.
- **`notesGroupModel(notes, groupBy) -> [{key, label, rows}]`** is the new
  grouping helper `views/notes.js` uses in place of §22's single
  section-only grouping: `groupBy === 'paper'` groups by `paperTitle`
  (`noteRowModel` applied internally), anything else groups by
  `sectionTitle`; either way a blank key falls back to `'Unfiled'`, and the
  `'Unfiled'` group — if present — is always moved to the end regardless of
  when it was first encountered. Total: malformed/empty input returns `[]`
  rather than throwing.
- **`views/notes.js`** (`#/notes`) is now a notebook, not a flat list:
  - **Group by** toggle — Section (default) / Paper — re-runs
    `notesGroupModel` client-side (no refetch).
  - **Kind filter chips** — Alignment / Opportunity / Reader / Ask / Paper /
    Free-form / All — and **status chips** — Open (default) / Done /
    Dismissed / All — both applied in `_filterNotes` *before* grouping, so
    an empty group never renders.
  - **New note** — a header button opens a small inline form (textarea +
    optional draft-section and paper `<select>` pickers, lazy-fetched via
    `api.getDraftAlignment()` and the in-memory paper list, both degrading
    to "no picker" on failure) → `buildNoteRecord('freeform', {...})` →
    `api.saveNote()` → refetch.
  - **Export as Markdown** now calls `api.exportNotes(_groupBy)` →
    `GET /api/notes/export?group_by=<_groupBy>`, so the exported file always
    matches whichever grouping is currently on screen.
  - A note's evidence-quote → open-in-reader button now renders only when
    the note has **both** a `paperId` and a `quote` (an `ask`/`freeform`
    note may carry a quote-less `sourceExcerpt`, or a paper-less quote makes
    no sense to "open in source").
- Tested in `tests/js/opportunityHelpers.test.mjs` (`notesGroupModel`
  grouping/Unfiled-last/totality, `noteRowModel`'s kind/sourceExcerpt
  passthrough) and `tests/test_lab_static.py` (notebook controls present:
  group-by toggle, both chip rows, New note form, kind-aware export call).

## 24. Researches tracking table + sidebar tab descriptions

The Researches screen (`#/researches`) went from a card-per-workspace summary
to a sortable tracking table, backed by an extended, additive
`workspace_stats()`. Every new stat is read from an already-on-disk,
per-workspace artifact — **never** `compute_coverage`, an LLM call, or a
network request — and every read is none-safe: a missing or corrupt file
degrades to `0`/`null`, it never raises and never breaks the list.

### `workspace_stats(ws_id)` — `research_companion/workspaces.py`

All reads go through `_read_json(path)`, which returns `{}` on `OSError` or
`json.JSONDecodeError` — every stat below is derived from that empty-dict
fallback when the file is missing/corrupt, so nothing here can 500 the
Researches list:

| Key | Source | Notes |
|---|---|---|
| `papers` | `papers/<dir>/metadata.json` presence | count of paper dirs with a metadata file |
| `draft_title` | `config.json` → `draft_paper_id` → that paper's `metadata.json` | falls back to the draft id if no title |
| `open_suggestions` | `suggestions/<draft-dir>/suggestions.json` | count of entries with `status == "open"` |
| `last_activity` | `mtime` of `config.json`, `journey.json`, `graph.json`, `lab_events.jsonl` | max of whichever of those exist, ISO/UTC |
| `failed` | `failed.json` | dict keyed by paper/target — `len()` of it |
| `draft_versions` | `journey.json` → `draft_versions` (list) | `len()` of the list |
| `draft_updated` | `journey.json` → `draft_versions[-1].added_at` | timestamp of the most recent version |
| `coverage` | `citations_coverage.json` → `counts` | `{in_library, total}`, or `null` if the cache doesn't exist yet — **cached payload only, never recomputed** for a list |
| `strength` | each paper's `strength.json` → `band` | tally of `{strong, moderate, weak, unscored}`; a paper with no `strength.json` or an unrecognized band counts as `unscored` |

`created_at` is **not** part of `workspace_stats()` — it lives on the
workspace record itself (set once in `create_workspace()`), so the frontend
row model reads it off `ws.created_at`, not `ws.stats`.

Tested in `tests/test_workspaces.py`: `test_workspace_stats_new_metrics` (each
new key populates correctly from its cached file) and
`test_workspace_stats_empty_workspace_is_none_safe` (every key degrades
cleanly with no on-disk artifacts at all).

### Row model + sort — `workspaceHelpers.js`

- **`researchRowModel(ws, activeId)`** flattens a `GET /api/workspaces`
  record + its `stats` into the table's display model. It derives fields the
  raw stats don't carry directly: `analyzed = max(0, papers - failed)`,
  `coveragePct` (rounded `100 * in_library / total`, or `null` when there's
  no cached coverage or `total` is `0`), `coverageLabel` (`"in_library/total"`
  or `"—"`), and `strengthSegments` (an ordered `[{band, count}]` for
  `strong`/`moderate`/`weak` — `unscored` is folded in by the renderer, not
  carried as a segment). Every numeric field defaults through `Number(x) ||
  0`, so a missing/malformed stat never becomes `NaN` or `undefined` on
  screen.
- **`sortResearchRows(rows, col, dir)`** sorts by one of six columns —
  `name`, `papers`, `coverage` (via `coveragePct`), `lastActivity`,
  `created`, `draftUpdated` — via a small accessor table
  (`_SORT_ACCESSORS`). Nulls always sort last regardless of `dir`; ties and
  null-groups keep their original relative order (stable); the input array
  is never mutated. An unrecognized `col` falls back to the `name`
  accessor.
- Tested in `tests/js/workspaceHelpers.test.mjs`: row-model derivation
  (analyzed, coveragePct/Label including the no-coverage and zero-total
  cases, strength segments, `createdAtIso` from `ws.created_at`) and
  `sortResearchRows` (each column, both directions, null-last, stability,
  non-mutation, unknown-column fallback).

### Table view — `views/researches.js`

`#/researches` renders one `<table class="researches-table">`: an inline
create row, then one `<tr>` per active workspace via `_rowHtml`, built from
`researchRowModel` output sorted by `sortResearchRows`. Columns, in order:
**Research** (name, an active-dot, and a draft star when `hasDraft`),
**Papers** (total, with an "N analyzed · N failed" sub-line), **Draft**
(title or `—`, plus a `vN` sub-line from `draftVersions`), **Citations**
(`coverageLabel` plus a fill bar sized to `coveragePct`), **Strength** (a
mini segmented bar over `strengthSegments`, title-attribute tooltip spelling
out the counts), **Open items**, **Draft updated** / **Last activity**
(relative time via `timeAgo`, `—` when absent), **Created** (absolute date),
and **Actions** (Open/Go to Home, rename, archive, delete). Header cells for
the six sortable columns are buttons (`data-sort-col`) that toggle
`_sortCol`/`_sortDir` and re-render; non-sortable columns (`draft`,
`strength`, `openSuggestions`, `actions`) render as plain `<th>`s.

Archived workspaces render in a second, collapsed `<details class="ws-archived">`
section using the same row renderer with `isArchived: true` — no Open button
and no row-click-to-open affordance (an archived workspace 409s on
activate), just Unarchive + Delete. All user/server-supplied text (names,
draft titles) goes through `escapeHtml` before being interpolated into the
row markup. The top-bar workspace switcher (`components/workspaceSwitcher.js`)
is kept as-is for a quick switch without leaving the current screen; its
"All researches…" and "New research" links still route to `#/researches`
and `#/researches?new=1`.

### Sidebar — nav entry + per-tab hover descriptions

`index.html`'s nav rail gained a **Researches** entry (`data-route
="/researches"`, right after Home) using the pre-existing `.nav-btn` markup.
Every nav button also now carries a `data-desc` attribute — a short
plain-language sentence (e.g. Researches: "track all your research projects
at a glance") rendered as a `::before` popover on hover via
`.nav-btn[data-desc]::before` in `lab.css`: left accent stripe, elevated
shadow, wraps to `max-width: 220px`. On the expanded rail the plain
single-line `title` tooltip is already nulled out (labels are visible, so it
would just echo them) — the `data-desc` popover is the only hover affordance
there. Under the pre-existing 640px icon-only collapse, `data-desc::before`
is explicitly nulled back out and the plain `title` tooltip is re-armed
instead, so the collapsed rail's behavior is unchanged by this feature.

## 25. Home dashboard — quick-nav model, empty/populated split, motion layer

The Home view (`#/home`, `views/home.js`) renders one of two layouts from the
same store subscription, chosen by whether a draft is set — no separate
route or component tree, just a branch in `_render()`.

### `homeNavModel(state)` — `homeHelpers.js`

A pure, dependency-light function (no DOM access, `node --test`-able) that
returns a fixed, ordered array of six quick-nav entries:

```js
{ key, label, desc, count, route? , action? }
```

- **Curated tab set, fixed order:** `library`, `graph`, `draft`, `ask`,
  `timeline`, `citations` — every entry every time, regardless of state.
- **`route` XOR `action`, never both:** `library`/`graph`/`draft`/`ask`/
  `timeline` carry a `route` (e.g. `'#/library'`) that the caller turns into
  a hash navigation; `citations` carries `action: 'open-citations'` instead —
  there's no dedicated `#/citations` route, so it reuses the existing
  `rc:toggle-citations` event the citation-coverage panel already listens
  for, rather than inventing a new one.
- **`count`:** only `library` carries a real number — the count of papers
  that are neither the draft nor flagged `is_draft` (mirrors the same
  non-draft-paper count `emptyHeroModel` computes). Every other entry's
  `count` is `null`; the renderer only emits a `home-nav-count` badge when
  `count` is not `null`/`undefined`.
- **`draft` label toggles on state:** `'Draft'` once a draft is set, else
  `'Set a draft'` — the one entry whose *label*, not just its badge, reflects
  state.
- Tested in `tests/js/homehelpers.test.mjs`: entry order/shape, the
  `library` count derivation, and the draft-label toggle.

### Empty/populated split — `views/home.js`

`_render()` reads `draftId` off the store — `const draft = draftId ?
papers.get(draftId) : null;` — and branches on that alone:

- **Populated** (`draftId` is set) — `_heroHtml()` renders the compact draft
  hero (title, version pill, last-activity, a severity donut, open count,
  related-paper count, addressed/total), then the quick-nav row is inserted
  via `_navRowHtml(state)` between the hero and the Next Steps (NBA) strip,
  followed by the top-3 open suggestions and the journey section.
- **Empty** (no `draftId` — regardless of how many non-draft papers are
  already in the library) — `_emptyHeroHtml()` renders the product intro
  instead: the brand line (`emptyHeroModel(state)`'s heading/subline), the
  `★ Add your draft` / `Ingest a folder` CTAs (`#home-hero-draft` /
  `#home-hero-folder`, wired to `_addDraftWithNudge()` and the folder-ingest
  modal), the ①②③④ step strip driven by `onboardingStep()`, the three value
  pillars (`_PILLARS`, a static array — no model needed since the copy
  doesn't depend on state), and — unlike the populated branch — its **own**
  call to `_navRowHtml(state)` embedded directly under the pillars, since
  there's no separate hero/nav-row insertion point in this branch. A
  non-empty library does not switch this branch to the populated hero — the
  only thing that changes is `emptyHeroModel`'s subline text (it swaps from
  the zero-papers copy to *"You've added N papers — add your draft to start
  analyzing them"*); the CTAs, step strip, pillars, and nav-row are
  unaffected by paper count.
- Both branches call the same `_navRowHtml(state)` → `homeNavModel(state)`
  path, so the six quick-nav cards render identically either way; only their
  position in the page (and the surrounding hero) differs. Card clicks are
  wired generically via `[data-nav-route]` / `[data-nav-action]` regardless
  of which branch rendered them.

### Motion layer contract — `lab.css` (`Home motion layer` block)

A CSS-only, additive layer gated entirely on one class:

- **`.home-animate-in`** is added to the `.home-view` wrapper only on the
  *first* `_render()` after `mount()` (a module-level `_animatedIn` flag,
  reset in `mount()`); navigating away and back re-triggers it once. Its
  direct children get a staggered `home-rise` entrance (fade + `translateY`,
  60ms stagger, first five children only via `:nth-child(1..5)`).
- **Sparkline draw-in:** `_journeyHtml()` renders the `<path>` with
  `pathLength="1"` — a normalized path length independent of the actual
  pixel length — so `lab.css` can animate a generic `stroke-dasharray: 1;
  stroke-dashoffset: 1` to `0` (`home-draw`, 0.6s, only under
  `.home-animate-in`) without computing the path's real length in JS.
- **Quick-nav hover-lift:** `.home-nav-card` gets a small `translateY(-2px)`
  + shadow on `:hover`/`:focus-visible`, independent of `.home-animate-in`
  (a permanent affordance, not part of the one-time entrance).
- **`@media (prefers-reduced-motion: reduce)`** forces every animated
  property on `.home-animate-in > *`, `.home-animate-in .home-sparkline
  path`, and `.home-nav-card` back to its resting state — `animation: none`,
  `transition: none`, `opacity: 1`, `transform: none`,
  `stroke-dashoffset: 0` — all `!important`. This is the binding contract:
  **nothing in the Home view depends on the animation actually running to
  be visible or usable** — the reduced-motion path renders the exact same
  final DOM and CSS classes, just with every transition/keyframe short-
  circuited to its end state instantly.

## 26. No-research-selected: nullable active-workspace resolution + `main` normalization

Fresh installs and libraries emptied down to zero workspaces used to be
impossible to express — `active_workspace_id()` always fell back to the
hardcoded `"main"`. It is now honestly nullable end to end: no workspace
selected is a real, representable state, not an implicit default.

### Active-research resolution (nullable) — `store.py`

`active_workspace_id() -> str | None` resolves, in order:

1. `$RESEARCH_COMPANION_WORKSPACE` (slugified) — always wins when set.
2. The registry's `active` field (`workspaces.json`) — may be `null`.
3. `None` — no more implicit `"main"` fallback.

`papergraph_dir() -> Path | None` is `None` whenever the resolver above
returns `None`. Every per-workspace read helper in `store.py` and its
sibling modules (`graph.py`, `journey.py`, `notes_store.py`, `views.py`,
`converse.py`) routes through `workspace_path(*parts)`, which returns
`None` under the same condition — so a read degrades to an empty/`None`
result instead of raising on `None / "x"`.

### The write-guard contract — `require_active_workspace()` in `lab_api.py`

Write-only helpers are not individually guarded; instead every mutating
endpoint (add/upload a paper, ingest, set-draft, notes, views, `/api/ask`,
`/api/converse`, and friends) declares
`dependencies=[Depends(require_active_workspace)]`. That dependency raises
`NoActiveWorkspaceError` when `store.active_workspace_id()` is `None`; a
dedicated `app.exception_handler(NoActiveWorkspaceError)` turns it into a
`409` with the exact body `{"error": "no_active_workspace"}` (not FastAPI's
default `{"detail": ...}` shape). The net effect: **reads degrade to an
empty `200`, writes 409** — nothing 500s just because no research is
active.

### Deleting down to none, and `main`'s normalization

`delete_workspace()` (`workspaces.py`) can now remove the last remaining
workspace, leaving the registry at `{"active": null, "workspaces": []}` —
there is no synthesized fallback. `main` is no longer special: it is an
ordinary registry record like any other, deletable and renamable.

`load_registry()` runs a one-time, idempotent normalization on every load: a
`main` record whose name is still the untouched default `"Main"` is
relabeled to `"My research"` (no directory move — the id and its data stay
put). It is guarded by name-equality, so it is a no-op once the record has
been renamed (by the user or by a previous run) — existing users upgrading
keep their data and their active selection; only the name changes, once.

### Frontend affordance — `workspaceSwitcher.js` + `researchGuard.js`

The topbar switcher (`components/workspaceSwitcher.js`) renders a visible
muted **"Research: none"** in place of a name when `activeId` doesn't
resolve to a workspace, instead of silently picking one. `researchGuard.js`
exports `ensureActiveResearch(action, deps)`: when no research is active it
shows a "Name your research" prompt, validates the name, creates +
activates the new workspace, refreshes the workspaces snapshot, and only
then runs the originally-requested `action` — resolving to `null` (never
throwing) on a cancelled prompt or a failed create/activate. It gates the
first Add draft / Ingest folder / + Add papers action from `home.js` /
`main.js` so a user never hits a write against no active workspace through
the normal UI flow.

## 27. Gap synthesis — themed bullets from verified gaps

`research_companion/gaps.py` already extracts and resolves per-paper
limitation/future-work gaps (`extract_gaps`, `resolve_gaps`,
`gaps_overview()`). The Gaps tab adds one more pure+LLM pass on top,
`synthesize_gaps(overview, *, llm=None)`, that groups near-duplicate
**verified** gaps into cross-corpus themes:

1. `_collect_verified_gaps(overview)` — pure. Flattens `gaps_overview()`'s
   `papers[].gaps[]` to the gaps whose `evidence.verified` is `True`, dropping
   everything else. Each item is `{gap_id, statement, kind, paper_id, title,
   year, status}` (`status` from the gap's `resolution`, default `"open"`).
2. One `GAP_SYNTHESIS_PROMPT` call (`research_companion/prompts.py`) — the
   only LLM call in the pipeline. It receives the verified gaps rendered as
   `[gap_id] (kind, year, status): statement` lines and returns
   `{"themes": [{"title", "bullet", "fws_type", "gap_ids": [...]}]}`. The
   prompt is explicit that every `gap_id` must be copied from the input list —
   grouping only, no invention.
3. `_assemble_themes(cluster_result, index)` — pure. For each raw theme,
   drops any `gap_id` not present in `index` (an LLM-invented id never
   survives into a citation); a theme left with zero valid members is
   dropped entirely. Builds `citations` (deduped by `paper_id`, first
   occurrence wins), `frequency` (# distinct citing papers), `recency` (max
   citation year), a rolled-up `status` (`open` if any member is open, else
   `partial`, else `addressed`), and the dominant `type` (`limitation` vs
   `future_work`, tie-broken toward `limitation`). `theme_id` is
   `"theme_" + sha256("|".join(sorted(gap_ids)))[:12]` — reproducible from
   the final membership alone.
4. `rank_gap_themes(themes)` — pure. Attaches a deterministic `score =
   3.0*frequency + 0.1*(recency-2000) + open_weight` (`open_weight`: 2.0 for
   `open`, 1.0 for `partial`, 0.0 for `addressed`) and stable-sorts
   descending.

`synthesize_gaps` never raises: an overview with no verified gaps returns
`{"themes": [], "generated_from_sha": ...}` **without calling the LLM at
all**; a malformed LLM response or a raised exception during the LLM call
degrades to an empty themes list rather than propagating, so
`POST /api/gaps/refresh` can still finish extraction/resolution and cache
what it has even if the synthesis step has a bad day.

### Caching

Like `gap_resolution.json`, the synthesis is cached store-side —
`gap_synthesis.json`, written by `store.save_gap_synthesis(payload)` /
read by `store.load_gap_synthesis()`. Staleness is the caller's job (mirrors
`gaps_overview()`'s own staleness check against `gap_resolution.json`):
the payload embeds `gap_prompt_sha256`, `resolution_prompt_sha256`,
`papers_sha256` (from `gaps._papers_sha`), and `synthesis_prompt_sha256`
(from the new `prompts.gap_synthesis_prompt_sha256()`); a cache is only
served when all four match the current values.

### Wiring

`POST /api/gaps/refresh` (`lab_api.py`) already ran
`extract_all_gaps` -> `resolve_gaps` -> `gaps_overview()`; it now also runs
`synthesize_gaps(overview, llm=resolved_llm)` (same injectable
`app.state.llm` / `_resolve_llm(json_mode=True)` seam as everything else),
caches the result via `store.save_gap_synthesis`, and publishes
`GapsUpdated(n_gaps, n_open, n_themes)` on the event bus (`n_themes` is
additive, default `0`, so any code still constructing the old two-field
`GapsUpdated` keeps working). `GET /api/gaps` reads the cache back (`themes:
[]` when there is none, or it's stale) and adds it to the existing response
— additive, no schema break.

### Frontend

`research_companion/lab/static/js/gapHelpers.js` is the pure, node-tested
model (`gapThemeRowModel`, `sortGapThemes`, `filterGapThemes` —
`tests/js/gapHelpers.test.mjs`); `views/gaps.js` (route `/gaps`, nav-rail
entry "Gaps") is the thin DOM layer on top, following the same
mount/unmount + `store.subscribe(['gaps'], ...)` re-fetch pattern as
`views/timeline.js` (both react to the `gaps_updated` SSE event via the
same `'gaps'` store topic). The Timeline's diamond overlay is untouched —
the Gaps tab is a complementary, deduped, cross-corpus reading of the same
underlying verified-gap data.

## 28. Brainstorm — `GET /api/discover`, `expand_query`, and the frontend helpers

The Brainstorm tab's discovery surface (2a of the ideation arc) is a
read-only literature search layered on top of the existing `discover.py`
module — no new mutating endpoint, no new dependency.

### `discover.expand_query(title, *, llm=None) -> list[str]`

`research_companion/discover.py`. Turns a rough title/topic into up to 5
search queries via one SHA-cached `DISCOVER_EXPAND_PROMPT` LLM call
(`research_companion/prompts.py`, `format_discover_expand_prompt` /
`discover_expand_prompt_sha256`). The original `title` is always the first
entry in the returned list. `llm` is the same injectable
`callable(prompt: str) -> str` seam used throughout (`_resolve_llm`,
`app.state.llm`). Never raises: `llm=None`, an LLM exception, or
unparsable/malformed JSON all degrade to `[title]`.

### `GET /api/discover`

`research_companion/lab_api.py`, registered inside `create_lab_app` right
after `GET /api/papers`. Query params: `q` (required — empty returns
`{results: [], queries_used: [], expanded}` with no search attempted),
`year_min`, `year_max`, `limit` (default 20, capped at 50), `expand` (0/1).

1. `expand=1` -> `queries = expand_query(q, llm=resolved_llm)` (same
   `app.state.llm` / `_resolve_llm(json_mode=True)` fallback pattern as the
   other LLM-backed endpoints); `expand=0` -> `queries = [q]`.
2. Each query is searched via `discover.search_topic_with_fallback(query,
   limit=..., year_min=..., year_max=...)` inside `asyncio.to_thread` (it's
   a blocking `httpx` call).
3. Results are merged across queries and deduped by identity
   (`connectors.identity.alt_ids`, same precedence as the rest of the
   codebase: DOI > PMID > PMCID > arXiv > title), keeping the
   higher-citation copy of any duplicate (`_dedup_discovered`).
4. Each surviving result is marked `in_library` by re-checking its identity
   against every paper currently in the store (`_library_identity_ids()`).
   This re-check matters even though `search_topic`/`search_topic_openalex`
   already filter out papers you own: `search_topic_with_fallback`'s
   opt-in domain-connector merge is only deduped against the S2/OpenAlex
   batch and against itself, not against the local store, so a
   connector-only hit can still legitimately need `in_library: true`.

**Deliberately NOT behind `require_active_workspace`** — it's a read, and a
brand-new user with no research yet must still be able to search. Dedup
against the library uses `store.list_papers()`, which is `[]` with no
active workspace, so nothing is marked `in_library` in that case (never a
409, never a 500).

**Never 500s.** Any exception raised while expanding or searching is caught
around the whole "resolve queries + search" block and turned into a 200
`{"results": [], "queries_used": [q], "expanded": expand, "error": "<msg>"}`
— exactly the shape the frontend already knows how to render as a retry
banner, not a broken tab.

Add-to-library is unchanged: results carry `add_cmd` and the raw
identifiers `POST /api/papers` already understands, and the existing add
pipeline (job queue, `require_active_workspace`, `ensureActiveResearch` on
the frontend) is reused as-is — no new mutating endpoint.

### Frontend — `discoverHelpers.js` + `views/brainstorm.js`

`research_companion/lab/static/js/discoverHelpers.js` is the pure,
DOM-free, node-tested layer (`tests/js/discoverHelpers.test.mjs`):

- `dedupeDiscoverResults(list)` — a second, defensive dedup pass over the
  raw `results[]` from `GET /api/discover` (same identity + higher-citation
  tie-break logic as the backend, kept independent so the view stays
  correct even against an older server).
- `discoverResultModel(raw, libraryIds)` — maps one raw result to a display
  row: escaped title/author-string/short-abstract, a human `sourceLabel`,
  `citationCount`/`year` normalized to safe defaults, `inLibrary` (ORs the
  server's `in_library` with an optional local `Set` of `"prefix:id"`
  identifiers the view already knows about right after an Add, before the
  next full refetch), and `addTarget` — the bare identifier
  `POST /api/papers`'s `target` expects, using the same pmid > arXiv > DOI
  > S2 > URL precedence as `DiscoveredPaper.add_cmd`.
- `sortDiscoverResults(list, col, dir)` — sorts an array of
  `discoverResultModel` rows by `'citations'` or `'year'`; `'relevance'`
  (or any unknown column) is a no-op copy, because the array's incoming
  order already **is** the relevance order the search API returned.

`views/brainstorm.js` (route `/brainstorm`, registered in `main.js`) is the
thin glue: a topic input + year-range inputs + an AI-expand checkbox + a
Search button call `api.discover({...})`; the raw `results[]` is run
through `dedupeDiscoverResults` -> `discoverResultModel` ->
`sortDiscoverResults` before rendering. Every result row's Add button (and
the header's Add all) calls
`ensureActiveResearch(() => api.addPaper(model.addTarget))` — the same
guard every other add-flow in the Lab uses, so a brand-new user is
prompted to name a research before the first paper lands. Loading / empty
/ error states mirror `views/gaps.js`; an `.error` payload from the server
renders as a retry banner instead of an exception.

## 29. Research Directions — `POST /api/directions`, `directions.py`, and the frontend helpers

The Brainstorm tab's Research Directions section (2b of the ideation arc)
mirrors `gaps.py`'s collect -> one-LLM-call -> assemble -> rank shape, but is
deliberately **synchronous and ephemeral** like `GET /api/discover` (2a) —
NOT a disk-cached background job like Gaps. Directions are a function of a
free-text topic + transient 2a discovery seeds, both of which change every
search, so there is no corpus-SHA disk cache that could stay valid.

### `research_companion/directions.py`

`synthesize_directions(topic, seeds, *, library_papers=(), graph=None, gap_synthesis=None, llm=None) -> dict`
is the orchestrator:

1. **`_collect_grounding`** (pure) builds a stable-keyed index of everything
   the LLM is allowed to cite:
   - **Papers** — the union of `library_papers` (assembled by the endpoint:
     `store.list_papers()` paired with each paper's cached
     `store.load_extraction(...)` for its concept names) and `seeds` (the
     2a `GET /api/discover` results the client already fetched), deduped by
     identity (`connectors.identity.alt_ids`, same DOI>PMID>PMCID>arXiv>title
     precedence as 2a's `_dedup_discovered`). Each survivor gets a stable
     `p:<connectors.identity.canonical_id(...)>` key.
   - **Underexplored concepts** (`_underexplored_concepts`) — concept nodes
     from the knowledge graph (`graph.py`'s `load_graph()`) with the lowest
     `paper_count` (the only existing per-concept frequency signal; no
     centrality/sparse-region computation exists), bottom third, capped at
     15, each a `c:<normalized-name>` key.
   - **Open gaps** — themes from `store.load_gap_synthesis()` with
     `status in ("open", "partial")`, each a `g:<theme_id>` key.
   - When there is no topic text AND this index is empty, `synthesize_directions`
     returns `{"directions": [], "generated_from_sha": ..., "topic": ""}`
     with **no LLM call** — there is truly nothing to ground a suggestion in.
     A topic alone (even with an empty index) still triggers one call.
2. **One SHA-cached LLM call** — `prompts.format_directions_prompt(topic=...,
   grounding_block=...)` -> `llm(prompt)`. `DIRECTIONS_PROMPT` instructs the
   model to over-generate 8-12 directions, cite ONLY the given keys, and
   return strict JSON. `_strip_code_fences` + a tolerant `json.loads`; any
   parse/LLM failure (including `llm=None`) degrades to `[]`, never raises.
3. **`_assemble_directions`** (pure) maps each `grounded_in` key back to its
   real citation and **drops any key not in the index** — the same honesty
   guard as `gaps._assemble_themes` dropping invented `gap_id`s. A direction
   whose citations all drop is kept (not hidden) with `grounding_count: 0`
   so ranking sends it to the bottom. `direction_id = "dir_" +
   sha256(_norm(title))[:12]` (same `_norm` as `gaps._gap_id`).
4. **`rank_directions`** (pure) computes `score = 3.0*grounding_count +
   0.1*(recency-2000) + type_weight` (`open_gap`=2.0,
   `underexplored_concept`=1.5, `cross_pollination`=1.0, others=0.0;
   `recency` = the max cited paper year, 0 if none) and stable-sorts
   descending — ties keep the LLM's original order.

### `POST /api/directions`

`research_companion/lab_api.py`, registered right after `GET /api/discover`.
Body: `{topic, year_min?, year_max?, seeds?}` (`year_min`/`year_max` are
accepted for parity with 2a but not yet used to filter). The handler
resolves the LLM (`app.state.llm or _resolve_llm(json_mode=True)`), builds
`library_papers` from the store, loads the graph and gap synthesis, and
calls `directions.synthesize_directions(...)` inside `asyncio.to_thread`.

**Deliberately NOT behind `require_active_workspace`** — a cold brainstormer
with no research yet can still generate directions from a topic and 2a
seeds alone; `store.list_papers()` degrades to `[]` with no active
workspace, so nothing from the library grounds the result in that case, but
nothing 409s or 500s either.

**Never 500s.** The entire body (LLM resolution, store reads, graph load,
`synthesize_directions`) is wrapped in one `try/except Exception` that
degrades to a 200 `{"directions": [], "topic": topic, "error": "<msg>"}` —
the same shape the frontend already renders as a retry banner.

### Frontend — `directionsHelpers.js` + the Research Directions section

`research_companion/lab/static/js/directionsHelpers.js` is the pure,
DOM-free, node-tested layer (`tests/js/directionsHelpers.test.mjs`):
`directionResultModel(raw)` maps one raw direction to a display row with
pre-escaped `title`/`rationale`/`typeBadge.label`/citation `label`s and raw
`directionId`/citation `paperId`/`themeId`/`name` (the caller escapes these
before writing into a DOM attribute — same contract as
`discoverHelpers.js`); `sortDirections(list, col, dir)` sorts by `'score'`
(default) or `'recency'`, nulls last, stable, unknown column = no-op copy.

`views/brainstorm.js` appends the section below the existing discovery
results: a **Generate directions** button (enabled once there is a typed
topic or at least one 2a search result in view) calls
`api.directions({topic, yearMin, yearMax, seeds: _rawResults})` — reusing
2a's already-fetched `_rawResults` as `seeds`, so the surface never
re-runs a search server-side. Direction cards show the title, rationale,
type badge, citation chips, and a grounding/score indicator. A citation
chip for a paper already in the library dispatches the same
`rc:open-paper` CustomEvent + `#/library` hash navigation `views/gaps.js`
uses for its citation chips; a concept/gap chip, or a paper citation
grounded only in a not-yet-added 2a seed (no `paper_id`, and the pinned
citation shape carries no URL), is informational only. Loading / empty /
error(retry) states mirror the rest of the tab; there is no SSE
subscription — the endpoint is synchronous, exactly like 2a's search.

## 30. Novelty Gate — `POST /api/novelty`, `novelty_check.py`, and the frontend helpers

The Brainstorm tab's per-direction **Check novelty** action (2c of the
ideation arc) is a small, synchronous, ephemeral function — NOT the
`ctx`-shaped `NoveltyAgent`/`PriorArtAgent` pipeline used by the full-paper
review runner (that stays as-is; grep confirms it has zero references in
`lab_api.py`). It reuses `prompts.format_comparison_prompt`
(`COMPARISON_PROMPT`) exactly as-is — no new prompt was added.

### `research_companion/novelty_check.py`

`check_novelty(title, rationale, *, year_min=None, year_max=None, limit=15,
top_n=5, search=None, llm=None) -> dict` is the orchestrator:

1. **`_novelty_query`** (pure) strips the direction's `title` into a search
   query. An empty/whitespace title returns an empty shell
   (`{"verdict": None, ...}`) with **no search and no LLM call** — nothing
   to check.
2. **Real prior-art search** — `(search or
   discover.search_topic_with_fallback)(query, limit=limit, year_min=...,
   year_max=...)`, the same S2→OpenAlex-fallback search 2a/2b use; `search`
   is the injectable seam for tests.
3. **`_rank_prior_works`** (pure) re-ranks the results client-side by token
   overlap (`rank.tokenize`, the same primitive `gaps.resolve_gaps` uses) —
   there is no semantic-similarity primitive in this codebase. Score =
   size of the token-set intersection between the direction text
   (`title + " " + rationale`) and each paper's `title + " " + abstract`;
   stable sort desc (ties keep the search's own citation-sorted order);
   capped at `top_n`.
4. **Zero prior works found** ⇒ returns an honest `verdict="novel"`,
   `confidence=0.3`, `rationale="No prior work found for this direction in
   the searched sources."`, `prior_works=[]`, and **no LLM call** —
   nothing to compare against, so nothing is fabricated.
5. **Otherwise, one LLM call** — `claim = f"{title}. {rationale}".strip()`;
   `prior_art = _prior_block(top_papers)` (a numbered `"[i] {title}
   ({year}) - {abstract[:300]}"` block); `format_comparison_prompt(claim,
   prior_art)` → `llm(prompt)` → `_strip_code_fences` + a tolerant
   `json.loads`, all inside a never-raise `try/except` that reports
   `llm_error` and keeps `verdict=None` on any failure (malformed JSON,
   LLM exception, or `llm=None`).
6. **Normalize** (pure) — verdict coerced to one of the 4 labels
   (`novel`/`incremental`/`overlaps`/`anticipated`) else `"novel"`;
   confidence clamped to `[0.0, 1.0]`; `closest_prior` coerced to a list of
   strings; `prior_works` attached as the curated, real (clickable) subset
   of each `DiscoveredPaper` — `title`/`year`/`url`/`doi`/`arxiv_id`/
   `s2_id`/`pmid`/`citation_count` (not the full `to_dict()`).

Returns `{"verdict", "confidence", "rationale", "closest_prior",
"prior_works", "query", "llm_error"}`. Never raises.

### `POST /api/novelty`

`research_companion/lab_api.py`, registered right after `POST
/api/directions`. Body: `{title, rationale?, year_min?, year_max?}`
(`_NoveltyBody`). The handler resolves the LLM (`app.state.llm or
_resolve_llm(json_mode=True)`) and calls `novelty_check.check_novelty(...)`
inside `asyncio.to_thread`.

**Deliberately NOT behind `require_active_workspace`** — a novelty check
depends only on the title/rationale it's given, not on the store, so a
cold brainstormer with no active workspace can still use it.

**Never 500s.** The entire body (LLM resolution, `check_novelty`) is
wrapped in one `try/except Exception` that degrades to a 200
`{"verdict": None, "prior_works": [], "error": "<msg>"}`. A second layer
re-surfaces `check_novelty`'s own `llm_error` field as the same shape — a
transient search/LLM outage shows a retry banner, never a false verdict.

### Frontend — `noveltyHelpers.js` + the per-card Check novelty action

`research_companion/lab/static/js/noveltyHelpers.js` is the pure,
DOM-free, node-tested layer (`tests/js/noveltyHelpers.test.mjs`):
`noveltyResultModel(raw)` maps one raw `POST /api/novelty` response to a
display row — a verdict→badge map (`novel`→positive, `incremental`/
`overlaps`→caution, `anticipated`→negative, unknown/null→none),
`confidencePct`, pre-escaped `rationale`, a `priorWorks` list (pre-escaped
`label`, raw `url`), and a pre-escaped `error`. Same escaping contract as
`directionsHelpers.js`: pre-escaped fields interpolate directly; raw `url`
is escaped by the caller when written into an attribute.

`views/brainstorm.js` adds a **Check novelty** button inside
`_directionCardHtml`, backed by a module-level `_noveltyByDirectionId` Map
(`directionId -> {loading, error, result}`) so a verdict survives a
subsequent full `_render()` (e.g. after a re-sort or a regenerate). The
click handler (`_checkNovelty`) mirrors `components/citationsPanel.js`'s
per-row pattern: it looks up the direction's raw (unescaped) `title`/
`rationale` from `_rawDirections`, calls `api.checkNovelty(...)`, and
mutates ONLY that card's own `.brainstorm-direction-novelty` panel via
direct DOM assignment — never a full `_render()` mid-flight — so checking
one card's novelty never disturbs another's in-flight check. An error
renders an inline retry button, rebound after each DOM mutation.

## 31. Draft this direction — `POST /api/directions/draft`, `scaffold.py`, and the frontend helpers

The Brainstorm tab's per-direction **Draft this direction** action (2d of
the ideation arc) turns one chosen Research Direction (2b) into a real
draft paper — an ordinary paper pointed at by `config.draft_paper_id`
(there is no distinct Draft object; see `_apply_draft` below). Unlike 2b's
`POST /api/directions` and 2c's `POST /api/novelty`, this endpoint
**MUTATES** (it creates a draft in the active research) so it is
workspace-guarded, and it is **atomic-on-success**: nothing is created
unless the outline LLM call actually succeeds.

### `research_companion/scaffold.py`

Two clearly separated stages, mirroring the design note in the module
docstring:

1. **`generate_outline(direction, *, llm=None) -> dict`** — one call to the
   new `prompts.SCAFFOLD_OUTLINE_PROMPT` (via
   `format_scaffold_outline_prompt`), grounded in the direction's `title`,
   `rationale`, `direction_type`, and a `_grounding_block` of its real
   `citations` (kind `"paper"` only — concepts/gaps aren't papers to name).
   `_strip_code_fences` + a tolerant `json.loads`, all inside a never-raise
   `try/except`. `_normalize_outline_sections` (pure) then caps the result
   at 12 sections, clamps `level` to `{1, 2}`, drops empty titles, and
   promotes a level-2 section with no preceding level-1 to level-1 (the
   same tiling invariant `sections.py` enforces). **A degenerate/empty
   outline — an LLM/parse failure OR a well-formed but empty `sections`
   list — is treated as a failure**: both set `llm_error`, so the caller
   never creates an empty draft. Returns `{"sections": [...],
   "llm_error": str|None}`.
2. **`scaffold_sections_payload(outline, *, title) -> (text, sections_payload)`**
   (pure) — builds the synthetic draft body (a `"# {title}\n\n{description}
   \n\n"` / `"## …"` block per section, concatenated in document order) and
   the tiling `sections.json` (`section_id`s `s1`/`s2`/`s2.1`, a level-2's
   `parent` is the nearest preceding level-1, `char_start`/`char_end` tile
   `text` exactly, `text_sha256` of that same text, `method: "scaffold"`).
   `title` is accepted only for signature symmetry with
   `create_draft_from_direction` (which uses it for the paper's own
   `metadata.title`) — it is NOT written into the body, since every outline
   section already carries its own tailored heading (mirrors
   `directions.py`'s `_collect_grounding`, whose `topic` parameter is
   accepted for the same reason without being grounding content itself).
3. **`create_draft_from_direction(direction, outline, *, store_mod=store) -> str`**
   — MUTATING; call ONLY after `generate_outline` succeeds. Mints a
   **deterministic** `paper_id` — `"scaffold:" +
   sha256(_norm(title) + "|" + _norm(rationale))[:12]` (same
   `rebuttal.verify._norm` + sha256-truncation convention as
   `directions._assemble_directions`'s `direction_id`) — so re-scaffolding
   the SAME direction overwrites the same draft paper instead of piling up
   duplicates. Builds a `store.PaperMetadata(paper_id, title=title,
   authors=[], year=None, abstract=rationale, source_url="",
   added_at=<now>, parse_source="scaffold", full_text_available=True)`,
   `.save()`s it, then `store.save_text` + `store.save_sections` from
   `scaffold_sections_payload`. Does **not** set the draft pointer or
   record a journey version — the endpoint reuses the existing
   `_apply_draft` for that, so the wiring is never duplicated.

### `POST /api/directions/draft`

`research_companion/lab_api.py`, registered right after `POST
/api/novelty`. Body: `{title, rationale?, direction_type?, citations?}`
(`_ScaffoldBody`). **Guarded** —
`dependencies=[Depends(require_active_workspace)]` (409 when no research is
active), unlike `POST /api/directions`/`POST /api/novelty`, because this
endpoint actually creates a draft in that research.

**Atomic-on-success.** The handler resolves the LLM, calls
`scaffold.generate_outline` inside `asyncio.to_thread`, and — if
`outline["llm_error"]` or `outline["sections"]` is empty — returns 200
`{"ok": False, "error": "..."}` **without creating anything**. Only once
the outline succeeds does it call `scaffold.create_draft_from_direction`
(also in `asyncio.to_thread`), capture `replaced = store.get_draft_paper_id()
not in (None, paper_id)` (whether a *different* draft already existed),
and `await _apply_draft(paper_id)` — the same shared mutator `POST
/api/draft` and `POST /api/papers/upload` use, so the draft pointer,
journey draft-version record, background suggestion-matching, and
`DraftVersionAdded` event all fire exactly as they do for any other draft.
Success: `{"ok": True, "paper_id", "draft_paper_id", "section_count",
"replaced_draft"}`.

**Never 500s.** The entire body is wrapped in one `try/except Exception`
that degrades to 200 `{"ok": False, "error": "Draft scaffold failed:
<msg>"}` — an LLM/parse failure never leaves a half-made draft (nothing
runs after the outline check fails) and never surfaces as a raw 500.

### Frontend — `scaffoldHelpers.js` + the guarded per-card Draft this direction action

`research_companion/lab/static/js/scaffoldHelpers.js` is the pure,
DOM-free, node-tested layer (`tests/js/scaffoldHelpers.test.mjs`):
`scaffoldPanelModel(state)` maps a per-card `{loading, error, result}`
state (tracked by `views/brainstorm.js`'s `_scaffoldByDirectionId` Map,
exactly like 2c's `_noveltyByDirectionId`) to one of four display states —
idle (the button), loading, error (pre-escaped `errorMessage` + retry), or
success (a pre-escaped `successMessage` naming the section count and
whether a previous draft was replaced, plus a raw `openDraftRoute`,
`"#/draft"`). Never throws.

`views/brainstorm.js` adds a **Draft this direction** button in
`_directionCardHtml` (a sibling slot to 2c's novelty panel), and a
`_scaffoldDraft(directionId)` handler that — unlike `_checkNovelty`, which
is read-only — **wraps the entire mutation in
`ensureActiveResearch(async () => ...)`**, mirroring `_addOne`/`_addAll`:
a cold brainstormer with no active research is prompted to name one before
anything is created. On success it calls `store.setDraft(paper_id)` (so
the rest of the UI — e.g. the topbar draft indicator — picks up the new
draft immediately), renders an inline "Open draft" link (`href="#/draft"`)
plus a `showToast(..., 'info')`, and mutates ONLY that card's own
`.brainstorm-direction-scaffold` panel — never a full `_render()`
mid-flight, so drafting one direction never disturbs another's in-flight
request. An error renders an inline retry button, rebound after each DOM
mutation, exactly like 2c's novelty panel.

### Seeing the outline + `POST /api/draft/analyze` ("Analyze this draft")

A scaffolded (or any freshly set) draft has **no per-paper alignment** —
alignment is computed at *ingest* time against whatever draft was active
then (`lab/__init__.py` Stage 5), so `GET /api/draft/alignment` returns
`{sections: []}` for it. Two additive pieces close the gap:

- **Outline fallback (frontend).** `research_companion/lab/static/js/draftHelpers.js`
  exposes the pure, node-tested `draftSectionModel(alignmentSections,
  outlineSections)` → `{sections, fromOutline}`: alignment sections when
  present, else the draft's own outline (from `GET /api/sections`, i.e.
  `store.load_sections(draft_id)`) mapped to `{section_id, title, level,
  alignments: []}` with `fromOutline: true`. `views/draft.js` calls it in
  `_render()` whenever alignment is empty, so the Draft view lists the
  outline instead of "No sections found."
- **`POST /api/draft/analyze` (backend).** Guarded
  (`require_active_workspace`), **never 500s**: friendly `200 {"ok": False,
  "error"}` with **no** job when there is no draft, no model, or no analyzed
  papers; otherwise a background job (gaps-refresh pattern:
  `asyncio.create_task`, `app.state.jobs[job_id]`,
  `_announce_start`/`_announce_finish`) that runs `align_papers(draft_id,
  cand_id, llm=…, force=…)` for every non-draft paper with an extraction,
  publishing the existing `AlignmentReady` per paper (so the Draft view
  refreshes with no new plumbing) and *Analyzing N/M* progress. A per-paper
  failure is counted, never aborts the run. `app.state.aligner_override` is
  the test seam; `analyze_draft_running` is a single-flight guard. The
  frontend button (`views/draft.js` toolbar, `api.analyzeDraft()`) derives
  its running state from the shared active-jobs map (kind `analyze`), not a
  local flag, so it auto-resets on `JobFinished`.
- **Scaffold status.** `_build_paper_summary` reports a `parse_source ==
  "scaffold"` draft as `status="done"` (it has text+sections but no
  extraction), so it is not stuck "pending" in the Library.

## 32. Deep-Research Report — `POST /api/report/refresh`, `deep_research.py`, and the frontend helpers

The **Report** tab (slice 2e-1 of the ideation arc) turns a topic into a
structured, cited literature review over the researcher's own library —
"topic in, cited report out." Unlike 2b/2c/2d's synchronous/atomic
endpoints, this is a **background job** (like `POST /api/gaps/refresh`),
because it makes N sequential LLM calls (one per investigation question)
and reports incremental progress along the way.

### Pipeline (`research_companion/deep_research.py`)

1. **`_report_grounding_block(library_papers, graph)`** (pure) — builds
   the LLM grounding block for question generation: one `"- Paper: {title}
   ({year})."` line per real library paper, plus one `"- Underexplored
   concept: {name} (...)."` line per underexplored concept, reusing
   `directions._underexplored_concepts` — the only existing per-concept
   frequency signal. `""` when there's nothing to ground on. Never raises.
2. **`generate_questions(topic, *, library_papers=(), graph=None,
   llm=None, max_questions=6) -> {"questions", "llm_error"}`** — one
   `REPORT_QUESTIONS_PROMPT` call (`prompts.format_report_questions_prompt`)
   turning the topic + grounding block into 4-`max_questions` distinct
   investigation sub-questions. `_normalize_questions` (pure) dedupes
   case-insensitively, drops empty/non-string items, and caps the count.
   An empty topic AND empty grounding short-circuits with no LLM call
   (`{"questions": [], "llm_error": None}` — truly nothing to ground on).
   A degenerate/empty question list (LLM/parse failure, or a well-formed
   but empty list) is treated as a **failure** — both set `llm_error`, so
   the caller never builds an empty report (mirrors
   `scaffold.generate_outline`'s empty-outline rule). Never raises.
3. **`build_report(topic, questions, *, answer_fn, generated_shas) ->
   dict`** (pure orchestration) — for each question, calls the injectable
   `answer_fn(question)` (the caller passes a `qa.answer` closure) and maps
   the result to a report section via `_citation_dict` (duck-typed
   `getattr` reads off the `QAAnswer`/`QASource`-like object, so this
   module never imports `qa.QASource` directly). A question whose
   `answer_fn` raises, or returns `None`, degrades to a section with an
   `"error"` key rather than aborting the rest of the report — **per-question
   failure isolation**, the same guarantee `synthesize_gaps` gives
   per-paper. Returns `{"topic", "sections": [{"question", "answer",
   "citations": [{"paper_id", "paper_title", "section_id", "char_start",
   "char_end", "chunk_index", "score"}, ...], "unverified_quotes",
   "error"?}, ...], "generated_from": generated_shas, "question_count"}`.

Honest by construction: questions are grounded ONLY in the library's own
concepts/papers (the prompt must not invent papers/concepts not
supplied), and every answer + its citations come straight from `qa.answer`
— real, quote-verified library chunks. Nothing is fabricated.

### The job, the store trio, and staleness

`POST /api/report/refresh` (`research_companion/lab_api.py`, guarded —
`dependencies=[Depends(require_active_workspace)]`, body `{topic}` via
`_ReportBody`) enqueues a background task exactly like `POST
/api/gaps/refresh`: it creates a `job_id`, returns 202 `{"job_id"}`
immediately, then runs `generate_questions` -> a loop of `qa.answer` calls
(updating the job's `detail` with `"Answering i/N"` between each one, the
progress `views/report.js` polls for) -> `build_report`, and finally
`store.save_report(...)`.

The persistence trio in `research_companion/store.py` mirrors the
gap-synthesis trio exactly:

- **`report_path() -> Path | None`** — `papergraph_dir()/research_report.json`,
  `None` with no active workspace.
- **`save_report(payload) -> Path | None`** — writes the payload as-is; the
  caller embeds whatever staleness-key SHAs it wants under
  `payload["generated_from"]`.
- **`load_report() -> dict | None`** — `None` if missing, unparseable, not
  a dict, or no active workspace. Staleness is the caller's job.

`GET /api/report` (read-only, never 500s) loads the cached report and
recomputes staleness by comparing `generated_from`'s `papers_sha256`
(`gaps._papers_sha`) and `report_questions_prompt_sha256`
(`prompts.report_questions_prompt_sha256`) against the CURRENT library —
exactly the same cached-themes freshness check `GET /api/gaps` runs.
`topic_sha256` is also recorded under `generated_from` (though not yet
consulted by `GET /api/report`'s `stale` flag) so a future slice can key
staleness on topic changes too. Returns `{"topic", "sections",
"question_count", "stale"}`.

### The event

`ReportUpdated(question_count, topic)` (`research_companion/agents/events.py`)
is published (`report_updated` on the wire) once the background job
finishes; the frontend `reducer.js`'s `report_updated` case maps it to the
`'report'` topic, so any mounted `views/report.js` refetches automatically
— a report generated from another tab/session still shows up here.

### Frontend — `reportHelpers.js` + `views/report.js`

`research_companion/lab/static/js/reportHelpers.js` is the pure, DOM-free,
node-tested layer (`tests/js/reportHelpers.test.mjs`):
`reportSectionModel(rawSection)` maps one raw `GET /api/report`
`sections[]` item to `{question, answer, hasError, errorMessage,
citations: [{label, paperId, sectionId}], unverifiedQuotes}`. `question`,
`answer`, `errorMessage`, each unverified quote, and each citation's
`label` are returned ALREADY escaped (interpolate directly — do not
re-escape); each citation's raw `paperId`/`sectionId` are NOT escaped, so
the view must `escapeHtml` them before writing into a `data-` attribute.
Never throws — every field defaults safely for a partial/malformed
section (a missing `paper_title` becomes `"Untitled"`, a missing
`question` becomes `"Untitled question"`, etc.).

`views/report.js` (`mount`/`unmount`, `store.subscribe(['report'],
refetch)` like `views/gaps.js`) renders a topic input + **Generate
report** button. The mutating `_generate()` call wraps `api.refreshReport`
in `ensureActiveResearch(async () => {...})` — mirroring Brainstorm's
`_scaffoldDraft` — since `POST /api/report/refresh` is guarded. Once the
job starts, `_pollJob` polls `api.getJob(jobId)` on an 800ms interval,
reusing `oaLinkHelpers.pollDecision` (the same job-poll state machine
`views/library.js` uses for find-pdf jobs) to decide `continue` /
`retry-transient` / `give-up` / `stop-404` on each attempt, surfacing the
job's `detail` ("Answering i/N") as live progress text. On completion it
refetches `GET /api/report` and renders each section — question heading,
answer, citation chips (open the cited paper/section in the reader via
the shared `rc:open-paper` CustomEvent, exactly like `views/gaps.js`'s
citation chips), and an unverified-quote caveat — as escaped-HTML DOM
built from the structured JSON, with no markdown library involved.

See `docs/superpowers/specs/2026-08-10-deep-research-report-design.md`
for the full design, including the deferred 2e-2..2e-5 sub-slices
(relevance/support/contradiction scoring, coverage %, an editable research
plan, and export).

## 33. Report Evidence Scoring (RCS) — `POST /api/report/score-evidence`, `rcs.py`, and the frontend badge

The **Report Evidence Scoring** (RCS) system rates each citation in a Report for relevance to its question and stance (supports / contradicts / neutral) toward its answer — an honest, on-demand AI judgment separate from the quote-verified ✓ badge used elsewhere.

### The pipeline (`research_companion/rcs.py`)

The core functions mirror the report-generation architecture:

1. **`_chunk_text(paper_id, char_start, char_end, *, load_text_fn=store.load_text) -> str`** (pure) — retrieves the exact character range from `store.load_text(paper_id)[char_start:char_end]`, using the precise offsets that `build_report`/`qa.answer` already produced. No fresh retrieval, no approximation. Returns `""` if the text cannot be loaded.

2. **`_chunks_block(citations, chunk_texts) -> (block, ref_to_index)`** (pure) — assembles the scorable citations into a numbered LLM-facing block, skipping any citation whose chunk text is empty. Returns a tuple: the formatted `"0. [Paper]: ... {quote excerpt}"` block and a `ref_to_index` dict mapping LLM-facing reference numbers (0, 1, ...) to indices in the original citations list.

3. **`score_section(question, answer, citations, *, load_text_fn=store.load_text, llm=None) -> list[dict|None]`** — orchestrates one section's scoring:
   - Loads chunk text for each citation via `_chunk_text`.
   - Assembles the block via `_chunks_block`, skipping unchunkable citations.
   - Calls `RCS_PROMPT` (from `prompts.format_rcs_prompt`, one call per section, **batched like `gaps.synthesize_gaps`**).
   - Parses the LLM response and maps scores back onto the original citation list via `ref_to_index`.
   - Returns `list[dict|None]` where a scorable citation gets `{"relevance": float 0..1, "stance": "supports"|"contradicts"|"neutral", "rationale": "..."}` and an unchunkable one gets `None`.

4. **`_normalize_scores(scores) -> list[dict|None]`** (pure) — post-processes a scored list:
   - Drops any `ref` key the LLM may have invented (only refs in `ref_to_index` are legal).
   - Clamps `relevance` to [0, 1] and normalizes it to [0%, 100%].
   - Ensures `stance` is one of the three canonical values; invalid stances become `None` (unscorable).
   - Returns the normalized list, with unparseable entries becoming `None`.

5. **`score_report(report, *, load_text_fn=store.load_text, llm=None, progress=None) -> dict`** — the public entry point:
   - Walks each section in the saved report and calls `score_section` on its citations.
   - Attaches the scored results directly onto each citation in place: `citation["rcs"] = {"relevance": ..., "stance": ..., "rationale": ...}`.
   - Stamps the report with `rcs_generated_from: {rcs_prompt_sha256: "..."}` so staleness checks know which version of the prompt generated these scores.
   - Never raises — an LLM failure, a malformed section, or any other error degrades gracefully to unscored citations.
   - Returns the augmented report dict (identical to `load_report`'s shape, with `rcs` fields added to citations).

The `RCS_PROMPT` is defined in `research_companion/prompts.py` alongside `REPORT_QUESTIONS_PROMPT` and other templates; `rcs_prompt_sha256()` returns a stable hash for staleness tracking (Task 1).

### Why a separate opt-in job instead of folding into `POST /api/report/refresh`?

Scoring adds `question_count` extra LLM calls on top of report generation (one per section). This is kept opt-in and separately costed, mirroring the pattern that novelty-check and alignment-scoring use elsewhere in the app — the user decides when to pay the extra cost, not every report generation.

### The honesty contract

- `rcs.score_section` and `rcs.score_report` **never raise** — an LLM failure, parse error, or any other issue degrades to unscored citations (the citation stays in the report, just with no `rcs` badge).
- The `rcs` field is **purely additive** — a report scored by an older client, or never scored at all, still renders correctly; the field is optional and its absence is not an error.
- Chunk text is **always real** — `_chunk_text` loads only from `store.load_text`, never invents or approximates text.
- Invented `ref`s are **always dropped** — `_normalize_scores` never lets an LLM-invented reference onto a citation.
- Scores are **clamped and normalized** — `relevance` is bounded to [0, 1] and displayed as an integer percentage; `stance` is validated against the canonical set.

### The endpoint (`research_companion/lab_api.py`)

`POST /api/report/score-evidence` (`dependencies=[Depends(require_active_workspace)]`) enqueues a background job exactly like `POST /api/report/refresh`:

- Returns 202 `{"job_id"}` immediately.
- Runs `score_report(report, llm=resolved_llm, progress=_progress)` where `_progress` is a callback updating the job's `detail` with `"Scoring evidence j/m"`.
- Publishes `ReportUpdated(question_count=..., topic=...)` on completion, reusing the same event that `POST /api/report/refresh` publishes — the frontend refetches and re-renders automatically.
- Job `kind: "report_rcs"`, with `"failed"`/`"done"` transitions and corresponding `_announce_start`/`_announce_finish` calls.

The guarded-202-job pattern keeps scoring on-demand and crashes are impossible — an LLM error is caught and degraded to unscored citations within `score_report` itself.

### The frontend (`research_companion/lab/static/js/reportHelpers.js`, `views/report.js`, `api.js`, `glossary.js`)

**`reportHelpers.js`** — new pure, node-tested helper:

- **`_rcsModel(rawRcs) -> {relevancePct, stanceSlug, stanceIcon, rationale, tipRelevance, tipStance}`** — maps the `rcs` dict onto display-friendly fields:
  - `relevancePct`: clamped percentage string (e.g., "85%").
  - `stanceSlug`: one of `"supports"`, `"contradicts"`, `"neutral"`.
  - `stanceIcon`: mapped via `format.js`'s `stanceIcon(stanceSlug)` function (reusing the same icons as elsewhere in the app).
  - `rationale`: the model's explanation text (HTML-escaped).
  - `tipRelevance`: literal string `"rcs_relevance"` for glossary lookup.
  - `tipStance`: literal string `"rcs_stance"` for glossary lookup.

**`views/report.js`**:

- **"Score evidence" button** in the report header (only enabled if a report is loaded).
- **Progress display** "Scoring evidence j/m" while the job is running.
- **Badge rendering** — each citation chip gains a new sub-section showing relevancePct and the stance icon (built via `_rcsBadgeHtml`), with the icon's tooltip and rationale visible on hover.
- **Event handling** — on `ReportUpdated`, refetch and re-render, which picks up the new `rcs` fields automatically.

**`api.js`**:

- **`api.scoreEvidence() -> {job_id}`** — `POST /api/report/score-evidence`, wraps the job endpoint.

**`glossary.js`**:

- **`rcs_relevance`**: "The relevance of this citation to the question (an AI judgment of the cited passage, not independently verified)."
- **`rcs_stance`**: "Whether this citation supports, contradicts, or is neutral toward the answer (an AI judgment, not independently verified)."

Both glossary entries emphasize that these are AI judgments, never "verified" in the same sense as the ✓ badge.

### Design reference

See `docs/superpowers/specs/2026-08-10-report-rcs-scoring-design.md` for the full design, the deferred 2e-3..2e-5 sub-slices (coverage %, editable research plan, export), rejected alternatives (folding into refresh, per-chunk calls, reusing `ALIGNMENT_PROMPT` verbatim, badging as "verified"), and the manual test script.

## 34. Report Coverage / Saturation — coverage.py and the always-on refresh fold-in

The **Report Coverage** system computes an auditable, BM25-heuristic coverage metric for each section and the report overall — showing how much of the library material the search judged relevant actually ended up cited in the answer. This is computed for free, LLM-free, and automatically every time a report is generated or regenerated, with no new endpoint or user action required.

### The pipeline (`research_companion/coverage.py`)

The core functions mirror the report-generation architecture:

1. **`_relevant_units(question, units, *, rank_fn, threshold=0.35) -> set[tuple[str, str, int]]`** (pure) — re-ranks a section's question against every unit in the library's retrieval index to find relevant passages:
   - Calls `rank_fn(question, q_tokens, units, *, k=len(units))` — a full re-rank of all available units, not a top-k cutoff (in practice, `rank_fn` is `retrieve.rank_units` from the same module that powers Ask and Brainstorm).
   - Applies the exact same relevance gate `gaps._relevance_score >= threshold` (default `0.35`) that `gaps.py` and `directions.py` use for their own relevance filtering.
   - Returns the set of unit tuples `(paper_id, section_id, chunk_index)` that passed the gate.

2. **`_section_coverage(section, relevant_units) -> dict`** (pure) — computes coverage for a single section:
   - Extracts the distinct cited units from the section's answer citations (each citation records its exact `(paper_id, section_id, chunk_index)`).
   - Intersects the cited units against the relevant units: `cited_set = cited_units & relevant_units`.
   - Computes the percentage: `pct = round(100 * len(cited_set) / len(relevant_units))` if `relevant_units` is non-empty, otherwise an honest `0` — never a fake `100`.
   - Returns `{"pct": int, "cited": len(cited_set), "relevant_available": len(relevant_units)}`.

3. **`score_report(report, *, build_index_fn=None, rank_fn=None, threshold=0.35) -> dict`** — the public entry point:
   - Builds the retrieval unit index once using `build_index_fn(report)` (or the real `qa.build_section_index` if not stubbed).
   - For each section, calls `_relevant_units` to find relevant material and `_section_coverage` to compute coverage.
   - Rolls up per-section coverage into a report-level summary: `{pct, cited, relevant_available, median_pct}` where `median_pct` is the median of all non-zero section percentages (robust to outliers).
   - Stamps the report with `coverage_generated_from: timestamp_or_stable_key` for staleness tracking.
   - **Never raises** — any failure in `build_index_fn`, `rank_fn`, or section processing degrades gracefully to honest zeros (each section gets `{"pct": 0, "cited": 0, "relevant_available": 0}`), never a fabricated number.
   - Returns a new dict with `coverage` and `coverage_generated_from` added (non-mutating; the original report is unchanged).

### Why fold it into `POST /api/report/refresh` instead of a separate opt-in job like RCS?

Coverage costs **zero extra LLM calls** — it's pure retrieval math over data the report already computed (the citations and the section structure). There is no latency cost and no billing reason to gate it behind a click. It is **LLM-free and always-on**: every report automatically includes coverage, computed at the same time as the report itself, adding no perceptible overhead.

This differs from RCS (Report Evidence Scoring), which adds `question_count` extra LLM calls and is kept opt-in and separately costed.

### The honesty contract

- **Relative to the search's own judgment, never the whole library** — the denominator is "passages *our* search ranked relevant," not the size of the entire library (which would yield misleading percentages in the single digits for large libraries).
- **BM25 heuristic label, not ground truth** — a tooltip and caption under the report header explicitly state that coverage reflects the search algorithm's judgment, which is an imperfect proxy.
- **Auditable raw counts always shown** — each bar displays the fraction `cited/relevant_available` (e.g., "3/7") so the raw numbers are transparent.
- **Honest 0-denominator, never fake 100%** — if `relevant_available` is 0 (the search found no relevant material for that question), coverage is `0%` / `0/0`, never hidden or shown as a misleading 100%.
- **Graceful degradation** — any failure (retrieval error, index build failure, etc.) degrades each affected section to honest zeros, never crashes the report job.
- **Purely additive** — the `coverage` field is optional; a report generated without coverage or by an older version still renders correctly, with the field simply absent.

### The endpoint (`research_companion/lab_api.py`)

Coverage is folded directly into the existing `POST /api/report/refresh` job, guarded by try/except:

- After `build_report` generates the answer and citations, `coverage.score_report(report)` is called to compute coverage for each section and the report overall.
- The computed `coverage` and `coverage_generated_from` fields are attached to the report dict before `save_report`.
- If `score_report` raises for any reason, the exception is caught, logged, and the report is saved with honest zero-coverage fields on all sections, never failing the job itself.
- The `GET /api/report` endpoint gains a passthrough for `coverage` and `coverage_generated_from` so the frontend receives them (the existing `sections` passthrough already carries per-section coverage).

### The frontend (`research_companion/lab/static/js/reportHelpers.js`, `views/report.js`, `glossary.js`)

**`reportHelpers.js`** — new pure, node-tested helper:

- **`_coverageModel(rawCoverage) -> {pct, cited, relevantAvailable, tip: 'coverage'}`** — maps the `coverage` dict onto display-friendly fields:
  - `pct`: numeric percentage (0–100).
  - `cited`: count of cited passages.
  - `relevantAvailable`: count of passages the search ranked relevant.
  - `tip: 'coverage'`: literal key for glossary lookup.
  - Returns `null` if `rawCoverage` is null or malformed (safe to consume in views without extra checks).

- **`reportCoverageModel(report) -> {pct, cited, relevantAvailable, medianPct, ...}` or null** — models the report-level coverage summary, gates on truthiness (if coverage was computed), and never throws.

- **`reportSectionModel(section, ...)`** — updated to include section-level coverage via the same `_coverageModel` shape.

**`views/report.js`**:

- **Per-section coverage bar** — each section heading is followed by a small coverage bar and percentage, rendered verbatim using `lab.css`'s existing `.research-cov-bar` and `.research-cov-bar-fill` CSS classes (no new styles, reusing the exact component from the RCS feature).
- **Report-level saturation** — near the report header (after the topic and questions, before the sections), a summary bar shows the overall coverage percentage, median percentage, and raw counts.
- **Gating** — both bars are only shown if `reportCoverage` is truthy (exact same pattern as 2e-2's `hasRcs` gating).
- **Event handling** — on `ReportUpdated`, refetch and re-render, picking up the new `coverage` fields automatically.

**`glossary.js`**:

- **`coverage`**: "How much of the library material our search judged relevant actually made it into the citations (a BM25 heuristic, not ground truth: the denominator is passages *our search* ranked relevant, not your entire library; each bar shows cited/relevant_available). Shows 0/0 and 0% honestly if the search found no relevant material."

The entry emphasizes that coverage is a search-relative signal, never an absolute measure of library completeness.

### Design reference

See `docs/superpowers/specs/2026-08-10-report-coverage-design.md` for the full design, including the deferred 2e-4/2e-5 sub-slices (editable research plan, export), rejected alternatives (whole-library percentage, opt-in endpoint, separate LLM judgment), and the manual test script.

---

## 35. Editable Research Plan — POST /api/report/plan, the extended refresh, and the frontend editor

The **Editable Research Plan** feature adds a synchronous planning checkpoint before the expensive report-answering pass, allowing users to review and edit the model-generated investigation questions in their browser before committing to answers. It splits the previous all-in-one generate-and-answer flow into two optional steps, while keeping the one-shot path completely unchanged.

### The pipeline split (`research_companion/deep_research.py` and `research_companion/lab_api.py`)

Previously, `POST /api/report/refresh`'s background job called `generate_questions` and immediately answered every returned question in the same run, with no checkpoint.

The 2e-4 change is **purely additive** — a plain `refresh({topic})` call (without a `questions` parameter) still generates AND answers in a single job, byte-for-byte identical to 2e-1. The new optional plan step adds an additional endpoint:

1. **`POST /api/report/plan` endpoint** (`_ReportPlanBody{topic: str = ""}`, guarded by `require_active_workspace`):
   - Runs a single `generate_questions` LLM call, just like the original refresh endpoint's first step, but **returns immediately** — it is **synchronous, never a background job**.
   - On success, saves a **fresh plan-only artifact** via `store.save_report({"topic": topic, "plan": {"topic": topic, "questions": [...], "status": "draft"}})`, deliberately omitting `sections` and `generated_from` to fully supersede any old answered report.
   - Publishes the existing `ReportUpdated` event with `question_count=0` (nothing has been answered yet).
   - **Never raises HTTP 500** — any LLM failure, parse failure, or internal exception returns 200 OK with body `{ok: false, error: <message>}` instead of 500, giving the frontend the ability to show a graceful user-facing error and retry.
   - Returns `{ok: true, plan: {topic, questions, status: "draft"}, error: null}` on success.

2. **`POST /api/report/refresh` extended with optional `questions`** (`_ReportBody` gains `questions: list[str] | None = None`):
   - Inside `_run_report`, if `body.questions` is a non-empty list, normalize via `_normalize_plan_questions` and skip the `generate_questions` call entirely, answering exactly those questions directly.
   - If `body.questions` is omitted, `None`, or empty, the function falls through to the exact 2e-1 code path unchanged — one LLM call to generate questions, then answer them all in the same job.
   - The fallback to the original behavior is **proven in the test suite** with an exploding `generate_questions` stub that will raise if invoked, demonstrating that when `body.questions` is a non-empty list, `generate_questions` is never called.
   - After `build_report` completes (and `coverage.score_report` runs, if any), EVERY run — whether one-shot or plan-driven — stamps the report with the exact set of questions that was actually answered: `report["plan"] = {"topic": topic, "questions": normalized_questions, "status": "answered"}`, recording the definitive list that produced this report.

3. **`_normalize_plan_questions(raw_questions: list, *, max_questions: int = 12) -> list[str]`** (pure utility, `research_companion/deep_research.py`):
   - A thin wrapper around the existing `_normalize_questions` function, reused identically by both the new plan endpoint and the extended refresh's `questions`-provided branch.
   - Higher default `max_questions` cap (12 vs. the 6 used by `generate_questions` alone) to allow user-curated lists to reasonably be longer than the model's initial guess.
   - Filters out blanks, non-strings, truncates to `max_questions`, and normalizes whitespace — the exact same sanitization as the one-shot path.

4. **`GET /api/report` additive passthrough**:
   - A top-level `plan` field (the cached `report["plan"]` sub-object if present, else `None`) is added to the endpoint's response at all three of its `return` points (the cache-empty return, the happy-path return, and the exception-fallback return), mirroring how `coverage`/`coverage_generated_from` were added in 2e-3. It is a single top-level field — not nested per-section or inside `coverage`; the frontend reads it as `_report.plan`.
   - Non-breaking: if a report from an older slice is retrieved, `plan` is absent and read as `None` by the frontend.

### The frontend (`research_companion/lab_static/js/`, specifically `views/report.js` and `reportHelpers.js`)

**`reportHelpers.js`**:

- **`reportPlanModel(rawPlan) -> {status, questions}|null`** — a pure helper that transforms the raw plan JSON into the front-end's display model:
  - Validates `rawPlan.status` is one of `"draft"` or `"answered"`.
  - Validates `rawPlan.questions` is an array and filters out non-strings and blanks.
  - Returns `{status, questions: [str, ...]}` on success, or `null` if the input is `null`, undefined, or malformed.
  - Escapes all question strings via `escapeHtml` **only for display-only read contexts** (history/review views); the actual editable state stays raw and lives in the module's `_plan` field.

**`views/report.js`**:

- New module state variables:
  - `_plan`: the current editable plan's questions array, raw (no escaping) since it only ever goes into `<textarea>.value` and textarea never parses HTML.
  - `_planMode`: either `"draft"` (user is editing the plan), `"answered"` (the report was answered), or `null` (no plan yet).
  - `_planGenerating`: `true` while the "Generate plan" request is in flight.
  - `_planError`: any error message from the plan generation or run.

- **`_syncPlanFromReport(report)`** — called on every report fetch/refetch:
  - If `report.plan.status === 'draft'`, automatically opens the plan in edit mode without user action (unfinished plans reopen where you left off).
  - Populates `_plan` with `report.plan.questions`.

- **`_generatePlan()`** — async function:
  - Calls `api.reportPlan({topic: _topic})`.
  - On `{ok: true}`, sets `_plan` and `_planMode = "draft"`, then calls `_render()`.
  - On `{ok: false}`, stores the error message and re-renders to show the user.

- **`_runReport()`** — async function:
  - Calls `api.refreshReport({topic: _topic, questions: _plan})`, exactly the same job submission as always (returns `{job_id}`).
  - Enters the existing `_pollJob` loop unchanged.
  - Sets `_planMode = "answered"` once the report completes.

- **`_editPlan()`** — opens the current report's plan in edit mode:
  - Loads the questions from `_report.plan.questions` into `_plan`.
  - Sets `_planMode = "draft"`.
  - Renders the editable UI.

- The **editable plan UI** (rendered when `_planMode === "draft"`):
  - A list of per-question rows, one per question.
  - Each row has a `<textarea>` (pre-populated with the question text), a **✕** delete button, **▲** and **▼** swap-reorder buttons.
  - Below the list, a **+ Add question** form where users can type a new question and press Enter (or click a button).
  - All edits are **purely client-side array mutations** followed by a local `_render()` — no network call until the user clicks **Run report**.
  - "Generate plan" and "Run report" buttons trigger the network actions (async, with loading states).

- **`api.js` clients**:
  - **`api.reportPlan({topic}) -> {ok, plan?, error?}`** — POST to `/api/report/plan`, returns the plan object (with `questions` and `status`) or an error message.
  - **`api.refreshReport({topic, questions?}) -> {job_id}`** — modified to accept an optional `questions` array and pass it in the POST body to `/api/report/refresh`.

- The original 2e-1 **one-shot "Generate report" button** (`report-generate-btn`, the `_generate`/`_pollJob` flow) is **completely unmodified** — the new plan flow is purely additive UI alongside it, reusing the exact same job-submission and poll machinery for the "Run report" action.

- **Markers and HTML elements**:
  - `report-generate-plan-btn`: triggers "Generate plan".
  - `Generate plan`: button label.
  - `api.reportPlan(`: the plan-generation API call.
  - `report-plan-q`: a question row in the editable list.
  - `data-q-idx`: data attribute on each row to identify which question (for delete/reorder).
  - `report-plan-delete`: delete button within a row.
  - `report-plan-up`, `report-plan-down`: swap-reorder buttons (plain `▲`/`▼`).
  - `report-plan-add-btn`: the "+ Add question" form.
  - `+ Add question`: user-facing text.
  - `report-run-btn`: triggers "Run report".
  - `Run report`: button label.
  - `_syncPlanFromReport`: function that populates the draft mode on report load.
  - `'draft'` and `'answered'`: plan statuses checked in the render logic.
  - `report-edit-plan-btn`: button to open an answered report's plan in edit mode.
  - `Edit plan / re-run`: button label.

### The honesty contract

- **User-edited questions are answered exactly as-is** — the existing `qa.answer` engine is grounded and quote-verified, with no new fabrication surface introduced. User questions are not specially treated or re-drafted by the model; they are answered with the same standards as model-generated ones.
- **Every run stamps the exact question set** — the `plan` sub-object on every report records the exact questions that were actually answered (`status: "answered"`), surviving `coverage.score_report`'s shallow-copy pass-through unchanged.
- **Re-running clears prior RCS scores** — this behavior predates 2e-4 and is not new: when a report is regenerated, all sections are rebuilt from scratch, which erases prior RCS (evidence-scoring) results. The user must re-run "Score evidence" if they want the badges refreshed. This is documented in the USER_MANUAL and accepted as a soft limitation (not re-engineered).
- **One-shot path is byte-for-byte identical to 2e-1** — the plain "Generate report" button invokes the exact same `refresh({topic})` call with no `questions` parameter, hitting the unchanged 2e-1 code path, tested with an exploding stub to prove `generate_questions` is never skipped.
- **No new staleness machinery** — the design explicitly rejected plan-time library staleness and focused on the answering-time retrieval, matching the Ask and Brainstorm features' own staleness model.

## 36. Report Export — report_export.py and GET /api/report/export

Slice 2e-5 adds a **markdown export** of a saved deep-research report — a one-click **Download (.md)** the researcher can save, paste, or share, carrying the exact same honesty caveats the live Report view shows.

### The pipeline (`research_companion/report_export.py`)

- `report_to_markdown(report: dict) -> str` is a **pure, never-raising** serializer, mirroring `notes_store.notes_to_markdown`'s list-of-lines → `"\n".join` shape — isinstance-guarded on every nested field, so a malformed/partial/`None` report degrades to a best-effort (or empty) string rather than raising.
- Builds, in order: `# {topic}` (fallback `# Deep-Research Report`); an overall `> **Coverage:** ...` line when `report["coverage"]` is a dict; per section a `## {question}` heading, the answer, a `**Citations**` bullet list (`paper_title` + a `section_id`/char-range locator, plus an inline `_[relevance NN%, stance]_` badge-as-text when `citation["rcs"]` is present — the same two fields, `relevance*100` + `stance`, `views/report.js`'s badge renders), a per-section coverage line, an "Unverified quote(s) (not found verbatim in your library): …" callout, and an error line; a footer with the RCS caveat (only if any citation anywhere carries `rcs`), the coverage caveat (only if report-level `coverage` is present), and a generic "AI judgments … are heuristics, not ground truth" line.
- `report_export.py` has **no import from `research_companion`** — it is entirely self-contained, taking only a plain dict and returning a plain string, exactly like `notes_store.notes_to_markdown`.

### Why markdown-only, not HTML

`report.py`'s `render_report_html` is hard-wired to the paper-*review*-lane shape (`{paper_id, title, lanes}`) with ~16 lane renderers — none match the deep-research `{topic, sections}` shape, so it isn't reusable. A self-contained-HTML renderer for the deep-research shape was considered and rejected as a whole new component for marginal benefit over a `.md` file; markdown is deferred-friendly and covers the "save/share" need.

### The endpoint (`research_companion/lab_api.py`)

- `GET /api/report/export` mirrors `GET /api/notes/export`: **unguarded** (no `require_active_workspace` — read-only), loads the report via `store.load_report()`, and returns `{"markdown": report_export.report_to_markdown(report) if isinstance(report, dict) else ""}`. The whole handler body is wrapped in `try/except Exception` → `{"markdown": ""}`, so it **never 500s** — no saved report, no active workspace, or even a hypothetical serializer failure all degrade to empty markdown, never an error response.
- Registered immediately after `GET /api/report` (before `POST /api/report/plan`) — there is no `/api/report/{id}` path-capture route to collide with.
- Purely additive: no change to `GET /api/report`'s own return shape, `deep_research.build_report`, or any 2e-1..2e-4 behavior.

### The frontend (`research_companion/lab/static/js/api.js`, `views/report.js`)

- `api.exportReport()` — a one-line `GET /api/report/export` wrapper, identical in shape to `api.exportNotes`.
- `views/report.js` adds a **Download (.md)** button to the existing `report-controls` row, disabled until `hasReport` (the same boolean the Score-evidence button already gates on). Its click handler calls `api.exportReport()` then a duplicated `_downloadMarkdown` helper — `Blob([markdown], {type:'text/markdown'})` → `URL.createObjectURL` → a synthetic `<a download="research-report.md">` click → `URL.revokeObjectURL`. This is the exact same pattern `views/notes.js` already uses for its own Export button; there is no shared download-helper module, so it is duplicated locally rather than introducing one for a single extra caller.
- **Static filename, no `Date.now()`** — `Date.now()`/`new Date()` is unavailable in some execution contexts; the Notes precedent already sidesteps this with a static name, so Report export follows suit (`research-report.md`).
- **No XSS**: the markdown is downloaded as a file via a Blob, never interpolated into `innerHTML` or otherwise inserted into the DOM.

### The honesty contract

- The export **fabricates nothing** — `report_to_markdown` only reproduces fields already present in the saved report (topic, questions, answers, citations, rcs, coverage, unverified quotes, errors).
- RCS badges are written as plain text explicitly labeled a judgment (`_[relevance NN%, stance]_`), and the footer states outright that relevance/stance are AI judgments, not independently verified — reusing the same caveat wording `views/report.js`'s `hasRcs` caption already shows the live UI.
- Coverage is captioned as a BM25 heuristic relative to the search's own relevance set, not ground truth — reusing the same wording `views/report.js`'s coverage caption shows.
- Per-section unverified-quote callouts are carried over verbatim, so a downloaded/shared file never reads as more "verified" than the app itself.

### Design reference

See `docs/superpowers/specs/2026-08-10-report-export-design.md`.
