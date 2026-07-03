# Tier-2 Agents + Evaluation + Packaging (Plan 5 of 5 — final)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps.

**Goal:** Complete the spec's roster (ProblemStatementAgent, TrackerAgent), build and RUN the offline citation-P/R evaluation (the demo paper's headline table), ship the novelty-vs-OpenReview harness (ready-to-run; honest about needing keys), sweep the accumulated deferrals, and finish packaging (offline demo script + README polish).

**Tech Stack:** everything already in the repo; no new dependencies.

## Global Constraints
- Python ≥ 3.10, ruff clean repo-wide (it currently is — keep it that way), `zip(strict=)`, line 110.
- TDD per task; no network/LLM in tests (seams as established). Suite baseline: **196 passed** (+ any Plan-4 fix deltas — use observed count).
- Commit ONLY named files. NEVER `git add -A`/`.`/`-a`.
- Eval outputs are artifacts: write to `eval/results/` and COMMIT them (they go in the paper); the eval run itself must be deterministic (seeded RNG).

---

### Task 1: ProblemStatementAgent + prompt

**Files:** Modify `papergraph/prompts.py` (append `PROBLEM_PROMPT` with placeholders `{statement}`, `{graph_context}`; `format_problem_prompt(statement, graph_context)`; `problem_prompt_sha256()`) · Create `papergraph/agents/problem.py` · Tests `tests/test_agents_problem.py` (+1 prompt test in `tests/test_novelty_prompts.py` style — put it in the new test file)

**Contract:** `ProblemStatementAgent` — `name="problem"`, `depends_on=("ingest", "priorart")`. Consumes `ctx.data["_problem_statement"]` (str; if empty/missing → ok=False, error mentions `--problem`). Graph context = top-10 concept labels by degree from `ctx.data["_graph"]` + titles of `_priorart_papers` (first 10) formatted as a bullet list. One LLM call (seam `_llm`, default `novelty._default_llm`, `asyncio.to_thread`) with `format_problem_prompt` → JSON `{"refined_statement": str, "gaps": [str], "next_steps": [str]}` (parse via a local `_parse_json` with the dict guard, RuntimeError mentions "problem"). Result data = that dict; one `Finding(kind="problem_refined")` with the refined statement as summary. PROBLEM_PROMPT rules: ground gaps ONLY in the provided graph context; return ONLY valid JSON (doubled braces in example).

**Tests (4):** prompt formats + placeholders gone; agent happy path (fake llm returns valid JSON; assert result fields + Finding); missing statement → ok=False; bad JSON → ok=False with "problem" in error. Expected count: baseline+4.

**Commit:** `git add papergraph/prompts.py papergraph/agents/problem.py tests/test_agents_problem.py` · `feat(agents): ProblemStatementAgent refines research problems against the graph`

---

### Task 2: TrackerAgent

**Files:** Create `papergraph/agents/tracker.py` · Test `tests/test_agents_tracker.py`

**Contract:** `TrackerAgent` — `name="tracker"`, `depends_on=("ingest",)`. Consumes `ctx.data["_extraction"]` concepts + paper title (store.PaperMetadata.load), builds the same query shape as PriorArtAgent; search seam `ctx.data["_search_recent"]` default `lambda q: search_topic(q, limit=10, year_min=<current year - 1>)` (compute year via `datetime.now().year` at call time — runtime only, tests inject); wraps in `asyncio.to_thread`. Result data `{"count": n, "new_papers": [{"title","year","id"}]}`; one `Finding(kind="new_related_work")`. Scheduled/watch mode is explicitly future work (docstring note).

**Tests (2):** injected search returns 2 papers → count/new_papers/Finding correct; empty results ok. Expected: +2.

**Commit:** `git add papergraph/agents/tracker.py tests/test_agents_tracker.py` · `feat(agents): TrackerAgent one-shot new-related-work sweep`

---

### Task 3: Citation P/R evaluation harness — BUILD AND RUN

**Files:** Create `papergraph/eval/__init__.py`, `papergraph/eval/citation_pr.py` · Test `tests/test_eval_citation_pr.py` · Artifacts (committed): `eval/results/citation_pr.json`, `eval/results/citation_pr.md`

**Contract:** `papergraph/eval/citation_pr.py`:
- `GOLD: list[dict]` — 40 real-looking reference records (title/authors/year/doi/arxiv_id) defined inline (mix of ML-paper-style titles; deterministic).
- `corrupt(records, rng) -> list[tuple[Reference, str]]`: from GOLD build a labeled set — per record emit the clean ref (`label="clean"`) plus, for a seeded random 50%, one corrupted variant drawn round-robin from: `fabricated` (title replaced by rng-generated nonsense words), `wrong_doi` (doi digits shuffled), `author_swap` (authors replaced by other record's authors).
- `run_eval(seed=42) -> dict`: lookup = in-memory best-title-match over GOLD (reuse `refcheck.matching.title_similarity`, floor 0.7 — mirrors `test_refcheck_integration._db_lookup`); predict: `verified`→clean, anything else→flagged; compute precision/recall/F1 of flagging corrupted refs overall AND per corruption type; return dict with counts.
- `main()` writes both artifact files (md = a small table) and prints the table; `python -m papergraph.eval.citation_pr` runs it.

**Tests (3):** corrupt() is deterministic for a fixed seed and labels correctly; run_eval returns precision/recall in [0,1] and >0.9 recall for `fabricated` (fabricated titles can't match the DB — sanity anchor); artifact writer creates both files in a tmp dir (path injectable via arg `out_dir`). Expected: +3.

**Step (controller or implementer): RUN IT** — `python -m papergraph.eval.citation_pr` → commit the two artifacts with the code.

**Commit:** `git add papergraph/eval/__init__.py papergraph/eval/citation_pr.py tests/test_eval_citation_pr.py eval/results/citation_pr.json eval/results/citation_pr.md` · `feat(eval): citation P/R corruption benchmark + results`

---

### Task 4: Novelty-vs-OpenReview harness (ready-to-run)

**Files:** Create `papergraph/eval/novelty_openreview.py` · Test `tests/test_eval_novelty_openreview.py` · Create `eval/README.md`

**Contract:** `load_cases(path) -> list[dict]` (JSONL: `{"paper_id","human_novelty": 1-5}` — papers must already be in the store with text); `run_cases(cases, llm=None, search=None) -> dict` — for each case runs NoveltyAgent via the orchestrator with injected seams when given (tests) or real defaults (production); maps our verdicts to a 1-5 scale (`novel`=5, `incremental`=3.5, `overlaps`=2, `anticipated`=1; paper score = mean over claims weighted by claim confidence); returns Spearman-style rank agreement computed WITHOUT scipy (simple rank correlation implemented inline) + per-paper table. `main()` CLI: `python -m papergraph.eval.novelty_openreview cases.jsonl [--out DIR]`; prints an honest banner when run without API keys explaining what will fail. `eval/README.md`: how to assemble ~25 ICLR cases from OpenReview (manual steps), how to run both evals, and the honest note that novelty-vs-OpenReview requires network + LLM keys and was NOT executed in this environment.

**Tests (2, all seams injected):** two fake cases with a fake llm → returns per-paper scores + a rank-agreement float in [-1,1]; verdict→score mapping exact. Expected: +2.

**Commit:** `git add papergraph/eval/novelty_openreview.py tests/test_eval_novelty_openreview.py eval/README.md` · `feat(eval): novelty-vs-OpenReview harness (requires keys to run live)`

---

### Task 5: Deferral sweep

**Files:** Modify `papergraph/rebuttal/segment.py`, `papergraph/rebuttal/draft.py`, `papergraph/agents/novelty.py`, `papergraph/cli.py` · Tests: extend `tests/test_rebuttal_segment.py`, `tests/test_rebuttal_draft.py` (novelty covered by existing suite)

**Changes (each with a test where behavior changes):**
1. segment.py: extend `_REVIEWER_RE` to `r"^\s*(?:[#=\s]*)reviewer\s*#?\s*(\w+)"` AND accept `^R(\d+)[:.]\s` lines; use the captured label when it is digits (`R{label}`), else keep encounter order. Tests: "Reviewer #2" and "R3:" headers produce R2/R3 ids; "Reviewer comments" heading no longer switches reviewer when followed by no digit? (keep simple: if captured label is not digits and not a single word like "One/Two", still switch but keep encounter numbering — assert existing tests unchanged).
2. draft.py: skip the classify LLM call when `concern.kind` already non-empty (test: pre-classified concern → fake llm sees only ONE call).
3. novelty.py: replace `_verify_quote`/`_normalize` with `from papergraph.rebuttal.verify import verify_quote` adapter (`evidence_verified = verify_quote(q, fulltext)[0]`); keep `_verify_quote` as a thin alias for backwards test-compat OR update the novelty tests' import — update the test import (cleaner).
4. cli.py `main()`: at entry, best-effort console hardening —
   `with contextlib.suppress(Exception): sys.stdout.reconfigure(errors="replace"); sys.stderr.reconfigure(errors="replace")`.

**Tests:** +3 (reviewer-label ids, R-prefix header, skip-classify single-call). Expected: baseline grows by 3.

**Commit:** `git add papergraph/rebuttal/segment.py papergraph/rebuttal/draft.py papergraph/agents/novelty.py papergraph/cli.py tests/test_rebuttal_segment.py tests/test_rebuttal_draft.py tests/test_agents_novelty.py` · `refactor: deferral sweep - segmentation labels, classify skip, shared verify, console hardening`

---

### Task 6: Offline demo script + README/packaging polish + FINAL GATES

**Files:** Create `examples/demo_offline.py` · Modify `README.md` (install section: `[demo]` extra; a "Reproduce the demo" block; tier-2 lanes note) · No other code.

**demo_offline.py:** self-contained script (run `python examples/demo_offline.py`) that: creates a temp PAPERGRAPH_DIR, seeds the demo paper + extraction + text (the Plan-4 smoke fixture), injects offline `_lookup/_search/_llm` seams via `cli.REVIEW_CONTEXT_OVERRIDES`, runs `review --report demo-out/`, runs `rebuttal` on a bundled 3-concern review text via `REBUTTAL_CONTEXT_OVERRIDES`, prints where report.html landed. Zero network, zero keys — the reviewer-facing "try it in 30 seconds" path.

**FINAL GATES (controller):** full suite green; repo-wide ruff clean; `python examples/demo_offline.py` exit 0 + report.html exists; `python -m papergraph.eval.citation_pr` deterministic re-run matches committed artifacts.

**Commit:** `git add examples/demo_offline.py README.md` · `feat(examples): zero-key offline demo script + docs polish`

## After this plan
Final cross-plan review (fable, whole range ef763d8..HEAD) → one fixer → consolidated report + push notification. Paper/video authoring offered separately.
