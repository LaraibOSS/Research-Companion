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
  `evidence_quote`, `evidence_section_id`, `comment`; plus server-assigned
  `id` (`uuid.uuid4().hex`), `created_at` (UTC ISO-8601, `Z` suffix), and
  `status` (`"open"` / `"done"` / `"dismissed"`, starting `"open"`).
- **`save_note(record) -> dict`** dedupes on **(`paper_id`,
  `draft_section_id`)**: if an **open** note already matches, its fields are
  updated in place (so re-saving a refreshed suggestion doesn't pile up
  duplicates) rather than appended — except a blank incoming `comment` never
  blanks an existing one, so a re-save can't silently erase what the user
  typed. `relevance` is coerced through `_as_float` (falls back to `0.0` on
  anything non-numeric/`None`) both on write and again wherever
  `notes_to_markdown` sorts by it, since `relevance` is caller-supplied and
  only `paper_id`/`draft_section_id` are validated at the API boundary — one
  bad record on disk must never 500 the whole list or export.
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
  `POST /api/notes` → 400 unless both `paper_id` and `draft_section_id` are
  present, otherwise `save_note(body)`; `PATCH /api/notes/{note_id}` → 400 on
  an invalid `status` value, 404 unknown id; `DELETE /api/notes/{note_id}` →
  404 unknown id; `GET /api/notes/export` → `{"markdown": notes_to_markdown(list_notes())}`.
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
- **`views/notes.js`** (route `#/notes`) lists every note grouped by
  `draft_section_title`, each row built through `noteRowModel`. An editable
  comment `<textarea>` PATCHes on blur (only when changed); Mark
  done/Dismiss/Reopen call `PATCH {status}`; Delete calls
  `DELETE /api/notes/{id}`; **Export as Markdown** fetches
  `GET /api/notes/export` and downloads the returned string client-side as
  `revision-notes.md` (no client-side formatting — see the DRY note above).
- Both views' markup and wiring are smoke-tested via string assertions in
  `tests/test_lab_static.py` (the same convention §19/§21 use), alongside the
  node-test coverage of the pure helpers.
