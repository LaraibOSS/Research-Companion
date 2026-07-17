# OSS launch readiness — guardrails, security, and community infrastructure

> **⚠️ Status: SUPERSEDED — architectural analysis only.**
> The authoritative, executable source is the implementation plan
> `docs/superpowers/plans/2026-07-15-oss-launch-readiness.md`. Where the two
> differ, **the plan wins**. This design records the original reasoning; several
> decisions below were tightened during review and are corrected inline with
> **[UPDATED]** notes. Do not execute this document as instructions.
>
> Key corrections the plan carries (all reflected below):
> branch protection uses `enforce_admins: true` + `strict: true` +
> `checks:[ci-ok,codeql-ok]` (no direct-push test); CI adds a `package`
> (wheel+sdist+assets+extras) job and PR `dependency-review`, with `ci-ok` +
> `codeql-ok` aggregate gates and current action majors (checkout@v7 etc.);
> the URL egress guard uses `ipaddress.is_global` + real streaming size cap and
> is documented as best-effort (residual DNS-rebinding TOCTOU); publishing uses
> build-once/publish-exact Trusted Publishing; and the existing long-lived PyPI
> token is revoked immediately after the workflow migration.

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
- **Demo mirror** (`Laraib-Hasan-OSS/Research-Companion`): **frozen and
  off-limits — never modified by this program or any future work.** It is the
  artifact referenced by the maintainer's EMNLP 2026 System Demonstrations
  submission (single-blind track) and stays exactly as submitted. This program
  applies only to the canonical repo.
- **No paper citation in this repo yet** (no CITATION.cff / README paper
  section) — deferred until the review decision.
- **Audit depth: full** — security audit + correctness review + fixes, not just
  scanners.
- **Publish stays HELD.** Workflow changes below alter *how* publishing would
  happen (Trusted Publishing), not *whether* (still only on an explicitly pushed
  `v*` tag, which we are not pushing).
- `paper/`, `docs/superpowers/`, `docs/OSS_MIRROR_NOTES.md` **stay tracked**:
  they are already in public git history, so removing them from the tip
  un-publishes nothing. Personal absolute paths inside them **will be scrubbed and
  verified by a meta-test before the launch PR merges** (see plan Task 8) — not yet
  done at the time of this design.

Audit facts this design is grounded on (verified 2026-07-14):
- Secrets audit: `.env` is untracked, gitignored, and **never appeared in git
  history** (verified with `git log --all -- .env` + pattern scans; all history
  hits are placeholders/test fixtures). **Credential rotation is a mandatory
  pre-launch gate, not routine hygiene** (see Phase 0).
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
GitHub *settings* (branch protection, scanning toggles) are applied via `gh api`
**after `ci-ok` and `codeql-ok` have run successfully on the launch PR, but before
that PR is merged** — the PR run establishes the required-check contexts, and
applying protection pre-merge means the launch PR itself must pass through it.

### Phase 0 — Mandatory credential revocation (launch gate)
Launch work must not proceed to the PR stage until: the old OpenAI credential is
revoked; the old Hugging Face credential is revoked; any credential ever pasted
into chat is revoked; new least-privilege credentials are generated; the local
`.env` is updated; and (after Task 5 merges the token-free publish workflow) the
existing `PYPI_API_TOKEN` secret is deleted and revoked. "Updated locally" is not
sufficient while an old credential remains valid.
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
  - **[UPDATED]** use the current action majors from the implementation plan
    (`checkout@v7`, `setup-python@v6`, `setup-node@v7`); the old
    "setup-python@v5 / checkout stays v4" note is superseded;
  - **[UPDATED]** matrix jobs get descriptive names, but branch protection depends
    only on the stable **`ci-ok`** aggregate context (not the individual `test`
    job), so the required-check config is stable regardless of the matrix.
- New `codeql.yml` — CodeQL (**`@v4`**) for `python` and `javascript`, on push/PR
  to main + weekly; `permissions: security-events: write, contents: read`; behind
  a stable **`codeql-ok`** aggregate gate.
- **[UPDATED]** `audit` job — `pip-audit --strict .` (audits the *project*, fails
  on collection errors), not the editable-install skip.
- **[UPDATED]** New `package` job — `python -m build` + `twine check`, then install
  **both the wheel (with `[server,mcp]` extras) and the sdist** in clean venvs,
  smoke `research-companion --version`/imports, and assert packaged Lab static
  assets via `importlib.resources`. Wired into `ci-ok`.
- **[UPDATED]** New PR-only `dependency-review` job (`dependency-review-action@v5`,
  `fail-on-severity: high`), wired into `ci-ok` (skip-tolerant on push).
- **[UPDATED]** All action majors bumped to current (verified): `checkout@v7`,
  `setup-python@v6`, `setup-node@v7`, `upload-artifact@v7`, `download-artifact@v8`.
- `publish.yml` **[UPDATED]** — build-once/publish-exact:
  - a `build` job (`checkout@v7` **`fetch-depth: 0`**) verifies tag↔version AND
    that the tagged commit (`git rev-list -n 1`) is reachable from `origin/main`,
    runs tests, builds, `twine check`s, wheel-smokes, and uploads `dist/` as an
    artifact;
  - a `publish` job (`environment: pypi`, `id-token: write`, repo guard) downloads
    that exact artifact and publishes via `pypa/gh-action-pypi-publish@release/v1`
    — no rebuild, no repo-code execution, **no `PYPI_API_TOKEN`**;
  - the existing long-lived `PYPI_API_TOKEN` secret is **deleted + revoked
    immediately after this workflow merges** (it exists now, created 2026-07-06).
  - **USER ACTION:** configure the trusted publisher on pypi.org
    (project `research-companion` → publishing → add GitHub publisher:
    owner `Laraib-Hasan-Future`, repo `Research-Companion`,
    workflow `publish.yml`, environment `pypi`) and create the `pypi`
    environment in repo settings. Until then the workflow simply cannot
    publish — consistent with publish-held.

### Phase 3 — GitHub platform guardrails (`gh api`, after merge)
- **[UPDATED]** Branch protection on `main`: require PR before merge
  (**0 approvals** — solo self-merge), required status checks via the `checks`
  array = **`ci-ok` + `codeql-ok`** (stable aggregate gates, not the individual
  matrix/CodeQL jobs), **`strict: true`** (branch must be current), block force
  pushes + deletions, **`enforce_admins: true`**. (The earlier
  `enforce_admins: off` + "escape hatch" idea was dropped: with 0 required
  approvals the solo maintainer can already self-merge, and admin-enforcement
  removes the direct-push footgun; temporarily toggle protection via the API only
  if a genuine hotfix is ever blocked.)
- Set the repo-wide default `GITHUB_TOKEN` permission to **read-only**.
- Enable: secret scanning, secret-scanning push protection, Dependabot alerts,
  Dependabot security updates, private vulnerability reporting.

### Phase 4 — Security audit + fixes (TDD)
Adversarial review of the attack surfaces, fixing confirmed findings:
- `research_companion/lab_api.py` (~50 endpoints): upload handling (filename/
  path traversal), `/api/papers/{id}/pdf` + `/text` file serving (id → dirname
  traversal), `/api/ingest` + `/ingest/scan` `paths` validation (already
  validated within scanned folder — verify), workspace ids, saved-view names →
  filesystem paths. Confirm the server binds `127.0.0.1` only and document
  that it must not be exposed; check CORS posture.
- **[UPDATED]** SSRF surface: `fetch.py` / `discover.py` / coverage "Add all"
  download URLs — a new `research_companion/net.py` egress guard
  (`validate_public_url`) rejecting non-http(s) schemes, embedded credentials,
  and any host resolving to a **non-`is_global`** IP (correctly catches CGNAT/
  TEST-NET/`2001:db8::`), plus **real streaming** downloads with a running size
  cap and manually-bounded, per-hop-revalidated redirects. Documented as
  **best-effort** (residual DNS-rebinding TOCTOU; connection-IP pinning out of
  scope for a local single-user CLI). `net.UrlNotAllowed` → `fetch.FetchError`.
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
- Full gate locally (expect ≥1895 py / 638 js / ruff clean + new tests).
- Push `feat/oss-launch`, open the PR, confirm `ci-ok` + `codeql-ok` (and the
  jobs behind them) pass on it; apply Phase-3 settings.
- **[UPDATED] Verify branch protection by reading the API config back — NOT by
  pushing to `main`** (a real direct-push test is unsafe and is removed).
- Merge via the PR itself. **CODEOWNERS auto-request is verified POST-merge**
  with a throwaway test PR (GitHub reads CODEOWNERS from the base branch, so the
  launch PR that introduces it cannot exercise it).

## Out of scope
- Pushing the `v0.7.1` tag / publishing to PyPI (held).
- Archiving/altering the old mirror repo (user chose leave-as-is).
- History rewriting (nothing sensitive is in history; rewriting a public repo
  would break clones for no gain).
- Docs site, Discord/discussions setup, FUNDING.yml (add later if wanted).

## Verification (end-to-end)
1. `python -m pytest -q` + `node --test tests/js/*.test.mjs` +
   `ruff check research_companion tests examples` — green, no regressions.
2. PR to `main` shows required checks `ci-ok` + `codeql-ok` and cannot be merged
   red. **Protection is verified by reading the API config back, never by a real
   push to `main`.**
3. `gh api repos/.../branches/main/protection` shows the intended config
   (`enforce_admins: true`, `strict: true`, `checks: [ci-ok, codeql-ok]`, no
   force-push/deletion, 0 approvals); secret scanning / Dependabot /
   private-vuln-reporting enabled; default workflow token read-only.
4. CI runs without secrets (only `publish.yml` uses OIDC), so fork PRs run
   cleanly; templates render. **CODEOWNERS auto-request confirmed post-merge via
   a throwaway PR** (base-branch rule).
5. `pip-audit --strict .` clean (or documented accepted risks); PR
   `dependency-review` blocks high-severity new deps.
6. Security-audit findings each have a regression test.
7. Built **wheel and sdist** install in clean venvs and expose the CLI + packaged
   Lab static assets (the `package` job).
