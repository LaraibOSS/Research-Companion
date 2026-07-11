# Port v0.5.17 reliability/UX improvements into the canonical tool

## Context
A parallel dev clone (`C:\Users\LARAIB\Projects\Research-Companion`, remote
`Laraib-Hasan-OSS`, local `v0.5.17`) advanced our exact `v0.5.16` base with 10
TDD'd commits — ingestion/citation reliability fixes, several UI/UX fixes, and an
onboarding bundle. Those improvements were never pushed to a shared remote; they
live only in that clone (plus its `pre-cleanup-backup` tag). This spec brings the
**code** improvements into `papergraph` (our canonical / PyPI repo, currently
`v0.5.16` with pristine v0.5.16 code) **without degrading or breaking anything**.

The governing constraint: **only enhance.** Every ported change must land green
(its own tests + the full gate) before the next, and anything that can't be
integrated cleanly is paused for a decision rather than forced.

## Scope
Port all 10 improvement commits (chronological, oldest→newest):

| Commit | Area | Change |
|---|---|---|
| `7204e83` | UX bundle | Guarded Main-ingest + first-launch key prompt + Settings close + new-research nudge — **split into 4 increments** |
| `2fdfb85` | Ingest | Recover from Docling parse failure/truncation; honest related-work fallback label |
| `0393e50` | Citations | Line-numbered author-year bibliography parser (gated splitter) |
| `d4d00a2` | Bug | Ask-tab 500 fix — resolve LLM from Settings when `app.state.llm` is None |
| `09a5113` | Citations | Author-year citation-placement |
| `2d4afe5` | UI | Citation-Placement panel wrap + Timeline alignment |
| `007f862` | Library | Cross-source de-duplication (content hash / arXiv-id·DOI in filename / byte-identical PDF) |
| `ec555a6` | UI | Timeline "N papers" / "Papers / year" label |
| `4c24585` | Ingest | Docling isolated in a subprocess (native crash/timeout can't kill the server; falls back to pypdfium) |
| `94bac59` | UX | Duplicate-upload feedback, honest count labels, Converse-panel z-index |

**Excluded:** `95001f6` (local `Audio RAG/` gitignore), the paper-draft /
recording-script / README-0.5.17 commits, and any `README.md` hunk *inside* the
ported commits (our README + docs are maintained separately in this repo).

### `7204e83` split (4 feature-scoped increments)
The commit's new files split cleanly; shared files (`main.js`, `lab.css`,
`store.py`, `router.js`, `index.html`, `lab_api.py`) are allocated by feature.
1. **Main-ingest guard** — `graph.py`, `lab/__init__.py`, the guard-related
   `store.py` hunks; `tests/test_graph.py`, `tests/test_store*.py`.
2. **First-launch key-prompt dialog** — `welcomeDialog.js`, `keyPromptHelpers.js`
   (+ `tests/js/keyPromptHelpers.test.mjs`), and their `main.js` / `router.js` /
   `index.html` / `lab.css` / `lab_api.py` hunks; `tests/test_lab_static.py`
   updated for the new served JS files.
3. **Settings close (× / Esc)** — `views/settings.js` + its `lab.css` /
   `index.html` / `main.js` hunks.
4. **New-research nudge** — `confirmDialog.js`, `researchNudgeHelpers.js`
   (+ `tests/js/researchNudgeHelpers.test.mjs`), and their `main.js` / `home.js` /
   `store.py` hunks; `tests/test_lab_static.py` for the new served JS.

If any sub-feature's hunks cannot be cleanly separated from another's, port those
two together as one increment rather than risk a broken intermediate state.

## Approach (the "don't break" mechanism)
1. **Backup:** `git tag pre-port-backup` on `papergraph` HEAD before starting.
2. **Source:** add the clone as a **read-only** local remote
   (`git remote add ported "C:/Users/LARAIB/Projects/Research-Companion"`,
   `git fetch ported`). Never push to it.
3. **Per increment (one commit / one sub-feature at a time, in the order above):**
   - `git cherry-pick -x <sha>` (or apply the feature's hunks for a split).
     The two v0.5.16 bases differ slightly, so expect occasional 3-way conflicts —
     resolve conservatively, preferring the ported change's intent while keeping
     our code's surrounding context.
   - Run the change's own tests, then the **full gate**: `python -m pytest -q`,
     `node --test tests/js/*.test.mjs`, `ruff check research_companion tests examples`.
   - Only commit + proceed when all green. If a change can't be made green without
     altering behavior, **stop and consult** — do not force it.
   - Commit as `Laraib Hasan <Lxh417bham@gmail.com>`, no AI trailer; keep the
     original subject (append `(ported from <sha>)`).
4. **Reviewer pass** (optional but recommended for the medium/large ports —
   `09a5113`, `007f862`, `2fdfb85`, `4c24585`, and the split): a fresh review of
   the applied diff vs. our code for spec-compliance and regressions.

## Verification
- After **every** increment: full gate green (no new failures vs. the pre-port
  baseline count).
- **Final full run:** `pytest -q` + `node --test tests/js/*.test.mjs` + `ruff`
  all green; record the new test count (baseline v0.5.16 was 1,668 passed).
- **Live smoke** (lab server) of each touched flow: folder ingest (+ a
  corrupt/scanned PDF → clean fallback, server stays up), Ask tab under an
  OpenAI-only config, citation coverage "N of M cited references", author-year
  placement, Timeline alignment + labels, Citation-Placement panel wrap, Settings
  ×/Esc, first-launch key prompt, new-research nudge, duplicate-upload message,
  cross-source de-dup (add same paper via arXiv + local PDF → one row).

## Release
Bump to **0.5.17** (4 spots: `pyproject.toml`, `__init__` fallback,
`tests/test_packaging.py`, `helpPanel.js`), refresh the editable install, add a
`0.5.17` What's-new line + `docs/RELEASE_0.5.md` section + any `USER_MANUAL`
updates for the new user-facing bits (key prompt, Settings close, dedup message),
regenerate `USER_MANUAL.pdf`. **Publish (tag → PyPI) stays HELD** pending explicit
go-ahead, consistent with v0.5.15/0.5.16.

## Out of scope (separate follow-ups)
- Re-deriving the OSS demo mirror to include these improvements (per the
  transforms in `docs/OSS_MIRROR_NOTES.md`).
- Reconciling the `Research-Companion` clone's divergence from its
  `Laraib-Hasan-OSS` origin.
- Porting the paper drafts / recording script / any doc-only commits.

## Rollback
Any increment that regresses and can't be fixed forward: `git reset --hard` to the
prior increment (or `pre-port-backup` to abandon the whole port). Because each
increment is a separate green commit, a bad one is isolated and cheap to drop.
