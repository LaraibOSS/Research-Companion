# OSS mirror — divergence from this (PyPI) repo

**Purpose.** Research Companion lives in two GitHub repos. This file records
exactly how the public demo **mirror** differs from this **canonical** repo, so
that when we work here (or sync between them) we know what is intentionally
different and must NOT be clobbered.

| | Repo | Role |
|---|---|---|
| **Canonical (this repo)** | `Laraib-Hasan-Future/Research-Companion` | Published to **PyPI**; keeps the publish + CI workflows and PyPI-style install docs. This is the source of truth. |
| **Demo mirror** | `Laraib-Hasan-OSS/Research-Companion` | Private, **source-install only** artifact for the EMNLP System Demo paper. No PyPI, no CI. **Fresh single-commit history** (HEAD `6576cd3`, v0.5.16). |

The mirror was produced by exporting this repo's tracked tree at `a26ea28`
(v0.5.16), then applying the de-PyPI transforms below. It is a one-way,
regenerable snapshot — not a fork with shared history.

---

## What the OSS mirror removes / changes vs this repo

**Workflows & their tests**
1. Removed `.github/workflows/publish.yml` (the PyPI publisher) **and** the 7
   `test_publish_workflow_*` tests in `tests/test_packaging.py`.
2. Removed `.github/workflows/ci.yml` **and** the 5 `test_ci_workflow_*` tests.
   (No CI: the push token lacked GitHub's `workflow` scope, and we opted for a
   no-CI mirror rather than re-authing.)

**Docs & metadata (de-PyPI + re-point URLs to `Laraib-Hasan-OSS`)**
3. `README.md`: install-from-source (`git clone … && pip install -e ".[server]"`)
   instead of `pip install research-companion`; repo URLs → OSS; dropped the
   "PyPI packaging" changelog phrase; fixed the Programmatic-API snippet
   (`import research_companion`, not the invalid hyphenated form); corrected
   stale test counts + replaced the hard-coded node command with
   `node --test tests/js/*.test.mjs`; removed the `RESEARCH_COMPANION_GUIDE.pdf`
   link.
4. `pyproject.toml` `[project.urls]` (Repository/Issues) → OSS.
5. `docs/USER_MANUAL.md`: §2 install → source clone + `pip install -e ".[server]"`;
   OCR extras → `pip install -e ".[docling]"`; header URL → OSS.
   `docs/USER_MANUAL.pdf` regenerated to match.
6. `research_companion/lab/static/js/components/helpPanel.js` `GITHUB_URL` → OSS;
   `research_companion/refcheck/retrieval.py` `USER_AGENT` URL → OSS.

**Code (the one runtime string that hard-coded a PyPI install)**
7. `research_companion/lab/__init__.py` `EMPTY_TEXT_ERROR`: the scanned-PDF
   OCR-failure message hint changed from
   `pip install research-companion[docling]` → `pip install -e ".[docling]"`.
   (Tests assert against the imported constant, not a literal, so no test edit
   was needed.)

**Dangling references to the omitted files, cleaned up in the mirror**
7b. Because the docs below (§8) were removed, their in-repo references were also
   scrubbed in the mirror: the in-app Help panel's `DOCS_PATH`
   (`research_companion/lab/static/js/components/helpPanel.js`) → `docs/USER_MANUAL.pdf`
   (was `docs/RESEARCH_COMPANION_GUIDE.pdf`); `docs/USER_MANUAL.md` dropped its
   `docs/superpowers/specs/` pointer and the `RESEARCH_COMPANION_GUIDE.pdf`
   companion-doc line; `docs/DEVELOPER_GUIDE.md` dropped its
   `docs/superpowers/specs/…` decision-report pointer; and a
   `refcheck/validate.py` comment dropped its `NOVELTY_ENGINE_SPEC` reference.

**Files/folders omitted from the mirror entirely**
8. `paper/` (LaTeX + figures + video script + user-study protocol),
   `docs/superpowers/` (internal SDD plans/specs),
   `docs/COMPETITOR_ARCHITECTURES.md`, `docs/NOVELTY_ENGINE_SPEC.md`,
   `docs/RESEARCH_EVALUATOR_PLAN.md`, `docs/RESEARCH_TOOL_ANALYSIS.md` + `.pdf`,
   `docs/ROADMAP.md`, `docs/RESEARCH_COMPANION_GUIDE.pdf`.
   Kept in the mirror: `research_companion/`, `tests/`, `eval/`, `examples/`,
   `docs/USER_MANUAL.*`, `docs/DEVELOPER_GUIDE.md`, `docs/RELEASE_0.*.md`,
   `LICENSE`, `pyproject.toml`, `README.md`, `.gitignore`, `.gitattributes`.
   **Exception:** the demo-video script from `paper/VIDEO_SCRIPT.md` WAS ported
   into the mirror as `docs/DEMO_VIDEO_SCRIPT.md` — adapted for OSS (source
   install shot instead of `pip install research-companion`, closing frame shows
   the OSS repo URL not the PyPI line, refreshed test count, `paper/main.tex`
   reference dropped), and linked from the README's Documentation list. The
   canonical PyPI version stays at `paper/VIDEO_SCRIPT.md` here.
9. Fresh single-commit history (no commit history carried from this repo).

---

## Guidance when working in THIS (PyPI) repo

- **Keep** `publish.yml`, `ci.yml`, the PyPI-style install docs, the
  `pip install research-companion[docling]` runtime message, the
  `Laraib-Hasan-Future` URLs, and all `docs/` + `paper/` content. These are
  correct here and are exactly what the mirror strips.
- **Porting a feature Future → OSS:** re-run the export and re-apply the
  transforms in the list above (they're all mechanical).
- **Porting a change OSS → Future:** take the code/feature, but do **not** bring
  back any of the de-PyPI edits (URLs, source-install docs, removed workflows,
  the `-e ".[docling]"` message) — they would break PyPI packaging here.

_Mirror HEAD at last sync: `Laraib-Hasan-OSS/Research-Companion` @ `6576cd3`
(2026-07-10)._
