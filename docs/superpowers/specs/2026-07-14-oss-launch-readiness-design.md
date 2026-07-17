# OSS launch readiness — guardrails, security, and community infrastructure

## Context

Research Companion (v0.7.1, MIT) is **already public** at
`Laraib-Hasan-Future/Research-Companion` — but as a solo-pushed repo with no
contributor guardrails: no branch protection, no community files, CI that runs
only a stale subset of the JS tests on one Python version, a long-lived PyPI
token in the publish workflow, and no automated security scanning. The goal is a
repo where **anyone can raise a PR safely**: contributions are gated by required
CI, security issues have a private disclosure path, automation catches secrets
and vulnerable dependencies, and the code itself has passed a security and
correctness audit.

Decisions made with the maintainer:
- **Governance: solo maintainer** (`Hasan-Laraib`). Branch protection requires
  PR + green CI but **no required approvals** (a solo maintainer must be able to
  merge their own PRs); force-pushes and branch deletion on `main` blocked.
- **Old demo mirror** (`Laraib-Hasan-OSS/Research-Companion`): left as-is.
- **Audit depth: full** — security audit + correctness review + fixes, not just
  scanners.
- **Publish stays HELD.** Workflow changes below alter *how* publishing would
  happen (Trusted Publishing), not *whether* (still only on an explicitly pushed
  `v*` tag, which we are not pushing).
- `paper/`, `docs/superpowers/`, `docs/OSS_MIRROR_NOTES.md` **stay tracked**:
  they are already in public git history, so removing them from the tip
  un-publishes nothing. Personal absolute paths inside them are scrubbed.

Audit facts this design is grounded on (verified 2026-07-14):
- Local `.env` holds **live OpenAI + HF keys** — untracked, gitignored, never in
  history (verified with `git log --all -- .env` + pattern scans; all history
  hits are placeholders/test fixtures). Keys must be **rotated by the user**.
- CI runs a hardcoded list of 18 of 29 `tests/js/*.test.mjs` files; Python 3.11 /
  ubuntu only; no `permissions:` blocks; `setup-python@v4`.
- No branch protection; secret scanning / Dependabot / CodeQL not configured.
- No CONTRIBUTING / SECURITY / CODE_OF_CONDUCT / CODEOWNERS / templates.
- Tracked-tree secrets scan: clean. `docs/Medical/` untracked but NOT gitignored.
- Windows dev paths leak in `docs/superpowers/plans/2026-06-29-agent-runtime-core.md`
  and `docs/superpowers/specs/2026-07-11-port-v0517-improvements-design.md`.
- README: no badges, no screenshots, `cd research-companion` casing bug (the
  clone dir is `Research-Companion`), minimal contributing guidance.
- pyproject: no `Homepage`/`Documentation`/`Changelog` URLs.

## Architecture of the change

Everything lands as **one branch (`feat/oss-launch`) → one PR into `main`**,
which must itself pass the new required checks (dogfooding the guardrails).
GitHub *settings* (branch protection, scanning toggles) are applied via
`gh api` after the workflows merge, since required-check names must exist first.

### Phase 0 — Immediate security hygiene
- **USER ACTION (cannot be done by tooling): rotate the OpenAI key and HF token
  currently in `.env`**; also rotate the OpenAI key pasted into chat earlier if
  different. Update `.env` locally with the new values.
- Add `docs/Medical/` and broader `.env.*` patterns (keep `!.env.example`) to
  `.gitignore`.

### Phase 1 — Community & governance files (new files)
- `CONTRIBUTING.md` — dev setup (`pip install -e ".[dev]"`), the three gates
  (`python -m pytest -q`, `node --test tests/js/*.test.mjs`,
  `ruff check research_companion tests examples`), TDD expectation, honesty-
  boundary principles (deterministic-first, never claim more than computed),
  how to run the Lab, PR checklist, and "tests must pass CI on 3.10–3.13".
- `SECURITY.md` — supported versions, private disclosure via GitHub Security
  Advisories ("Report a vulnerability" button), response expectation, scope
  notes (local-first tool; Lab server binds 127.0.0.1; keys live in local `.env`).
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1, contact = GitHub profile
  of the maintainer.
- `.github/CODEOWNERS` — `* @Hasan-Laraib`.
- `.github/PULL_REQUEST_TEMPLATE.md` — summary/motivation, test evidence
  (all three gates), checklist (tests added, docs updated, no secrets).
- `.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, `config.yml`
  (blank issues on; security link to the advisories page).
- `.github/dependabot.yml` — weekly `pip` + `github-actions` update PRs.

### Phase 2 — CI hardening (edit `.github/workflows/`)
- `ci.yml`:
  - top-level `permissions: contents: read`;
  - replace the 18-file JS list with `node --test tests/js/*.test.mjs`;
  - matrix: python `[3.10, 3.11, 3.12, 3.13]` on `ubuntu-latest`, plus one
    `windows-latest` + 3.12 job (the dev platform); `fail-fast: false`;
  - bump `actions/setup-python` to v5 / `actions/checkout` stays v4;
  - keep job name stable (`test`) so required-check config is predictable.
- New `codeql.yml` — CodeQL for `python` and `javascript`, on push/PR to main +
  weekly schedule; `permissions: security-events: write, contents: read`.
- New `audit` job inside `ci.yml` — runs `pip-audit` against the installed
  package; fails the build on known vulnerabilities (no `continue-on-error`).
- `publish.yml`:
  - top-level `permissions: contents: read`; upload job gets
    `id-token: write` and `environment: pypi`;
  - replace `TWINE_USERNAME/PASSWORD` with **PyPI Trusted Publishing**
    (`pypa/gh-action-pypi-publish@release/v1`); keep the repository guard and
    tag/version match check; fix the same JS-list drift.
  - **USER ACTION:** configure the trusted publisher on pypi.org
    (project `research-companion` → publishing → add GitHub publisher:
    owner `Laraib-Hasan-Future`, repo `Research-Companion`,
    workflow `publish.yml`, environment `pypi`) and create the `pypi`
    environment in repo settings. Until then the workflow simply cannot
    publish — consistent with publish-held.

### Phase 3 — GitHub platform guardrails (`gh api`, after merge)
- Branch protection on `main`: require PR before merge (0 approvals), required
  status checks = the CI matrix jobs + CodeQL, strict up-to-date not required,
  block force pushes + deletions, enforce_admins **off** (solo-maintainer
  escape hatch).
- Enable: secret scanning, secret-scanning push protection, Dependabot alerts,
  Dependabot security updates, private vulnerability reporting
  (`gh api -X PATCH repos/... security_and_analysis`, `-X PUT .../vulnerability-alerts`, etc.).

### Phase 4 — Security audit + fixes (TDD)
Adversarial review of the attack surfaces, fixing confirmed findings:
- `research_companion/lab_api.py` (~50 endpoints): upload handling (filename/
  path traversal), `/api/papers/{id}/pdf` + `/text` file serving (id → dirname
  traversal), `/api/ingest` + `/ingest/scan` `paths` validation (already
  validated within scanned folder — verify), workspace ids, saved-view names →
  filesystem paths. Confirm the server binds `127.0.0.1` only and document
  that it must not be exposed; check CORS posture.
- SSRF surface: `fetch.py` / `discover.py` / coverage "Add all" download URLs —
  scheme/host validation on user-supplied URLs.
- `research_companion/mcp_server.py` + `mcp_tools.py`: input validation,
  no path escape via `paper_id` (`_id_to_dirname` sanitization — verify).
- Zip/PDF handling: `parsers/` subprocess isolation already contains crashes;
  verify no shell-injection in the docling worker invocation.
- `pip-audit` run; upgrade any vulnerable pins.
- Each confirmed finding: failing test → fix → gate.

### Phase 5 — Correctness review + fixes
- Code-review pass (correctness lens) over the newest surfaces (`statcheck/`,
  `interop/`, `overlap.py`, `mcp_tools.py`, report wiring) + high-traffic core
  (`store.py`, `lab/__init__.py` ingest stages). Fix confirmed bugs TDD; the
  1866/638 gate must stay green.

### Phase 6 — Content scrub + polish
- Replace `C:\Users\LARAIB\...` absolute paths in the two tracked
  `docs/superpowers/` files with generic relative references.
- `README.md`: CI + license + Python-versions badges; fix both
  `cd research-companion` → `cd Research-Companion`; Contributing section →
  point at `CONTRIBUTING.md` + correct JS glob; embed 1–2 screenshots
  (reuse `paper/figures/`); one line clarifying this repo is the canonical home.
- `pyproject.toml`: add `Homepage`, `Documentation` (docs/DOCUMENTATION.md),
  `Changelog` (docs/RELEASE_0.7.md) URLs. Author email unchanged (maintainer's
  published identity, their call).

### Phase 7 — Verification + launch PR
- Full gate locally (expect ≥1866 py / 638 js / ruff clean + new tests).
- Push `feat/oss-launch`, open the PR, confirm the new CI matrix + CodeQL run
  and pass on it; apply Phase-3 settings; verify branch protection blocks a
  direct push; merge via the PR itself.

## Out of scope
- Pushing the `v0.7.1` tag / publishing to PyPI (held).
- Archiving/altering the old mirror repo (user chose leave-as-is).
- History rewriting (nothing sensitive is in history; rewriting a public repo
  would break clones for no gain).
- Docs site, Discord/discussions setup, FUNDING.yml (add later if wanted).

## Verification (end-to-end)
1. `python -m pytest -q` + `node --test tests/js/*.test.mjs` +
   `ruff check research_companion tests examples` — green, no regressions.
2. PR to `main` shows required checks (all matrix jobs + CodeQL) and cannot be
   merged red; direct push to `main` is rejected by protection.
3. `gh api repos/.../branches/main/protection` shows the intended config;
   secret scanning/Dependabot/private-vuln-reporting show enabled.
4. A dummy fork-style PR (or the launch PR itself) demonstrates: templates
   render, CI runs without secrets, CODEOWNERS requests review from maintainer.
5. `pip-audit` clean (or documented accepted risks).
6. Security-audit findings each have a regression test.
