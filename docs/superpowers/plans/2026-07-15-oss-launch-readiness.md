# OSS Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Laraib-Hasan-Future/Research-Companion` a safely contributable public repo: community files, hardened CI, platform guardrails, and a security + correctness audit with fixes.

**Architecture:** All file changes land on the `feat/oss-launch` branch and merge via one PR that must pass the new CI itself. GitHub *settings* (branch protection, scanning) are applied via `gh api` after the workflows exist on the PR. Meta-tests in `tests/test_packaging.py` / new `tests/test_community_files.py` pin every guardrail so regressions fail CI.

**Tech Stack:** GitHub Actions, CodeQL, pip-audit, PyPI Trusted Publishing (OIDC), pytest meta-tests.

## Global Constraints

- Branch: `feat/oss-launch`. Commits: `git -c user.name="Laraib Hasan" -c user.email="Lxh417bham@gmail.com" commit …`, **no AI trailer**, explicit `git add <paths>`.
- Full gate after every task: `python -m pytest -q` (baseline 1866 pass / 3 skip) · `node --test tests/js/*.test.mjs` (638 pass) · `ruff check research_companion tests examples`.
- **Publish stays HELD** — never push a `v*` tag; workflow changes alter only *how* publishing would work.
- **NEVER touch `Laraib-Hasan-OSS/Research-Companion`** (frozen EMNLP-reviewer artifact).
- Nothing the EMNLP paper claims may break: `examples/demo_offline.py`, `eval/` harnesses, the Lab.
- No `CITATION.cff` / paper mention anywhere (deferred until the review decision).
- `docs/Medical/` stays untracked and untouched.
- Repo URL in docs/badges: `https://github.com/Laraib-Hasan-Future/Research-Companion`.

---

### Task 1: .gitignore hardening + meta-test

**Files:**
- Modify: `.gitignore`
- Test: `tests/test_packaging.py` (append)

**Interfaces:** Produces: `.gitignore` entries `docs/Medical/`, `.env.*`, `!.env.example`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_packaging.py`:

```python
def test_gitignore_covers_private_local_content():
    """docs/Medical and all .env variants (except .env.example) must be ignored."""
    gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in ("docs/Medical/", ".env.*", "!.env.example"):
        assert pattern in gi, f".gitignore missing {pattern!r}"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_packaging.py::test_gitignore_covers_private_local_content -q` → FAIL (missing patterns).
- [ ] **Step 3: Implement** — in `.gitignore`, replace the two lines `.env` / `.env.local` with:

```
.env
.env.*
!.env.example
```

and under the `# Local user state — never commit` block add `docs/Medical/`.

- [ ] **Step 4: Run the test again** → PASS. Run `git status --short` → `docs/Medical/` no longer listed as untracked.
- [ ] **Step 5: Full gate, then commit** `git add .gitignore tests/test_packaging.py` · `chore(gitignore): ignore docs/Medical and all .env variants`.

### Task 2: Community & governance files + meta-test

**Files:**
- Create: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `.github/ISSUE_TEMPLATE/config.yml`, `.github/dependabot.yml`
- Test: `tests/test_community_files.py` (new)

**Interfaces:** Produces the files above; Task 3's PR relies on templates existing.

- [ ] **Step 1: Write the failing test** — create `tests/test_community_files.py`:

```python
"""Community/governance files required for a contributable public repo."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

def test_community_files_exist():
    for rel in ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
                ".github/CODEOWNERS", ".github/PULL_REQUEST_TEMPLATE.md",
                ".github/ISSUE_TEMPLATE/bug_report.yml",
                ".github/ISSUE_TEMPLATE/feature_request.yml",
                ".github/ISSUE_TEMPLATE/config.yml",
                ".github/dependabot.yml"):
        assert (REPO_ROOT / rel).exists(), f"missing {rel}"

def test_contributing_documents_the_three_gates():
    text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for cmd in ("python -m pytest -q", "node --test tests/js/*.test.mjs",
                "ruff check research_companion tests examples"):
        assert cmd in text, f"CONTRIBUTING.md missing gate: {cmd}"

def test_codeowners_assigns_maintainer():
    text = (REPO_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    assert "@Hasan-Laraib" in text

def test_security_md_points_to_private_reporting():
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    assert "security advisories" in text or "report a vulnerability" in text

def test_dependabot_covers_pip_and_actions():
    text = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "pip" in text and "github-actions" in text
```

- [ ] **Step 2: Run** `python -m pytest tests/test_community_files.py -q` → FAIL (files missing).
- [ ] **Step 3: Create the files.** Content requirements (write real prose, no stubs):
  - `CONTRIBUTING.md`: dev setup (`git clone https://github.com/Laraib-Hasan-Future/Research-Companion.git`, `cd Research-Companion`, `pip install -e ".[dev]"`); the three gates verbatim (as asserted above); TDD expected for new code; design principles (deterministic-first, char-span provenance, "never claim more than computed", local-first — no new services/DBs); how to run the Lab (`pip install -e ".[server]"` + `research-companion lab serve`); PR checklist (tests added, all gates green, docs updated, no secrets); note that CI runs Python 3.10–3.13 on Ubuntu + Windows.
  - `SECURITY.md`: supported version = latest release; report privately via GitHub Security Advisories ("Report a vulnerability" on the Security tab) — **do not open public issues for vulnerabilities**; acknowledgment target within 7 days; scope notes (local-first app; Lab server binds 127.0.0.1 and must not be exposed publicly; API keys live only in the local `.env`).
  - `CODE_OF_CONDUCT.md`: full standard **Contributor Covenant v2.1** text, enforcement contact = the maintainer via GitHub (`@Hasan-Laraib`).
  - `.github/CODEOWNERS`: single line `* @Hasan-Laraib`.
  - `.github/PULL_REQUEST_TEMPLATE.md`: sections — Summary; Motivation; Test evidence (the three gate commands with results); Checklist (`- [ ] Tests added/updated`, `- [ ] All three gates green locally`, `- [ ] Docs updated if user-facing`, `- [ ] No secrets or private data in the diff`).
  - `.github/ISSUE_TEMPLATE/bug_report.yml`: form with fields — what happened, steps to reproduce, expected behavior, version (`research-companion --version`), OS/Python, logs.
  - `.github/ISSUE_TEMPLATE/feature_request.yml`: problem, proposed solution, alternatives.
  - `.github/ISSUE_TEMPLATE/config.yml`: `blank_issues_enabled: true` and a contact link to the repo Security-Advisories page for vulnerabilities.
  - `.github/dependabot.yml`: version 2; two update entries — `package-ecosystem: pip`, directory `/`, weekly; `package-ecosystem: github-actions`, directory `/`, weekly.
- [ ] **Step 4: Run** `python -m pytest tests/test_community_files.py -q` → PASS (5 tests).
- [ ] **Step 5: Full gate, then commit** all nine files + the test · `docs(community): contributing, security policy, code of conduct, templates, dependabot`.

### Task 3: ci.yml overhaul (permissions, JS glob, matrix, pip-audit, ci-ok)

**Files:**
- Modify: `.github/workflows/ci.yml` (full rewrite), `tests/test_packaging.py:257-264` (`test_ci_workflow_has_node_test_command`)
- Test: `tests/test_packaging.py` (modified + new assertions)

**Interfaces:** Produces job names `test`, `audit`, `ci-ok` — Task 7 (branch protection) requires status check context **`ci-ok`**.

- [ ] **Step 1: Update/extend the meta-tests first.** In `tests/test_packaging.py`, REPLACE `test_ci_workflow_has_node_test_command` with:

```python
def test_ci_workflow_runs_all_js_tests_via_glob():
    """ci.yml must glob ALL JS tests, not a hardcoded file list (which drifts)."""
    ci_yml = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    content = ci_yml.read_text(encoding="utf-8")
    assert "node --test tests/js/*.test.mjs" in content, \
        "ci.yml must run node --test with the tests/js/*.test.mjs glob"
    assert "reducer.test.mjs" not in content, \
        "ci.yml must not hardcode individual JS test filenames"

def test_ci_workflow_scopes_permissions():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "permissions:" in content and "contents: read" in content

def test_ci_workflow_has_python_matrix_and_windows():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in ("'3.10'", "'3.11'", "'3.12'", "'3.13'", "windows-latest"):
        assert needle in content, f"ci.yml matrix missing {needle}"

def test_ci_workflow_has_pip_audit_and_summary_job():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip-audit" in content, "ci.yml must run pip-audit"
    assert "ci-ok" in content, "ci.yml must expose the ci-ok summary job (required check)"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_packaging.py -q -k ci_workflow` → the 4 new/changed tests FAIL, existing ones pass.
- [ ] **Step 3: Rewrite `.github/workflows/ci.yml`** with exactly:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

defaults:
  run:
    shell: bash

jobs:
  test:
    name: test (${{ matrix.os }}, ${{ matrix.python }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest]
        python: ['3.10', '3.11', '3.12', '3.13']
        include:
          - os: windows-latest
            python: '3.12'
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}

      - name: Install dependencies
        run: python -m pip install -e ".[dev]" build twine

      - name: Run pytest
        run: python -m pytest -q

      - name: Run ruff check
        run: ruff check research_companion tests examples

      - name: Set up Node.js 20
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Run Node.js tests
        run: node --test tests/js/*.test.mjs

  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install package + pip-audit
        run: python -m pip install -e . pip-audit
      - name: Audit dependencies for known vulnerabilities
        run: pip-audit --skip-editable

  ci-ok:
    if: always()
    needs: [test, audit]
    runs-on: ubuntu-latest
    steps:
      - name: All required jobs green?
        run: |
          [ "${{ needs.test.result }}" = "success" ] && [ "${{ needs.audit.result }}" = "success" ]
```

- [ ] **Step 4: Run** `python -m pytest tests/test_packaging.py -q` → ALL pass (old + new).
- [ ] **Step 5: Full gate, then commit** `.github/workflows/ci.yml tests/test_packaging.py` · `ci: permissions scoping, full JS glob, 3.10-3.13 + Windows matrix, pip-audit, ci-ok gate`.

### Task 4: CodeQL workflow

**Files:**
- Create: `.github/workflows/codeql.yml`
- Test: `tests/test_packaging.py` (append)

- [ ] **Step 1: Failing test** — append:

```python
def test_codeql_workflow_exists_and_scopes_permissions():
    codeql = REPO_ROOT / ".github" / "workflows" / "codeql.yml"
    assert codeql.exists(), "Missing .github/workflows/codeql.yml"
    content = codeql.read_text(encoding="utf-8")
    assert "security-events: write" in content
    assert "python" in content and "javascript" in content
```

- [ ] **Step 2: Run it** → FAIL (file missing).
- [ ] **Step 3: Create `.github/workflows/codeql.yml`:**

```yaml
name: CodeQL

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '30 5 * * 1'

permissions:
  contents: read

jobs:
  analyze:
    name: Analyze (${{ matrix.language }})
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    strategy:
      fail-fast: false
      matrix:
        language: [python, javascript-typescript]
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/analyze@v3
        with:
          category: "/language:${{ matrix.language }}"
```

- [ ] **Step 4: Test passes; full gate.**
- [ ] **Step 5: Commit** · `ci(security): CodeQL analysis for python and javascript`.

### Task 5: publish.yml → PyPI Trusted Publishing

**Files:**
- Modify: `.github/workflows/publish.yml`, `tests/test_packaging.py:211-216` (`test_publish_workflow_has_secret_reference`)

**Interfaces:** Consumes nothing; publishing still requires the user to configure the trusted publisher on pypi.org + create the `pypi` environment (publish HELD regardless).

- [ ] **Step 1: Replace the meta-test.** REPLACE `test_publish_workflow_has_secret_reference` with:

```python
def test_publish_workflow_uses_trusted_publishing():
    """publish.yml must use PyPI Trusted Publishing (OIDC), not a long-lived token."""
    content = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "id-token: write" in content, "publish.yml must request OIDC id-token"
    assert "pypa/gh-action-pypi-publish" in content
    assert "environment: pypi" in content or "environment:\n      name: pypi" in content
    assert "PYPI_API_TOKEN" not in content, "long-lived token must be gone"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_packaging.py -q -k publish` → new test FAILS, others pass.
- [ ] **Step 3: Rewrite `.github/workflows/publish.yml`:** keep name/trigger (`push` tags `v*`), keep tag-vs-pyproject version check, pytest, `node --test tests/js/*.test.mjs`, `python -m build`, `twine check dist/*`; add top-level `permissions: contents: read`; the publish job gets `environment: pypi`, `permissions: id-token: write, contents: read`, keeps the step-level guard `if: github.repository == 'Laraib-Hasan-Future/Research-Companion'`, and uploads via `uses: pypa/gh-action-pypi-publish@release/v1` (no env vars, no twine upload).
- [ ] **Step 4: Run** `python -m pytest tests/test_packaging.py -q` → all pass (`test_publish_workflow_has_upload_guard` still satisfied by the `if:` guard; `twine check` assertion still satisfied).
- [ ] **Step 5: Full gate; commit** · `ci(publish): migrate to PyPI Trusted Publishing behind the pypi environment`.

### Task 6: Security regression tests + targeted fixes

**Files:**
- Test: `tests/test_security_regressions.py` (new)
- Modify (only if a test fails): `research_companion/fetch.py`, `research_companion/lab_api.py`

- [ ] **Step 1: Write the regression tests** (lock in the safe behaviors a public repo depends on):

```python
"""Security regression tests: traversal, SSRF scheme, loopback binding."""
import inspect
from pathlib import Path

from research_companion import store


def test_paper_id_cannot_traverse_paths(tmp_path):
    """A hostile paper_id must never escape the papers dir."""
    for hostile in ("../../evil", "..\\..\\evil", "a/../../b", "x:..%2F..%2Fy"):
        dirname = store._id_to_dirname(hostile)
        assert "/" not in dirname and "\\" not in dirname and ".." not in dirname
        resolved = (store.papers_dir() / dirname).resolve()
        assert store.papers_dir().resolve() in resolved.parents


def test_download_pdf_rejects_non_http_schemes():
    """_download_pdf must refuse file:// and other non-http(s) URLs (SSRF/LFI)."""
    import pytest
    from research_companion.fetch import _download_pdf
    for bad in ("file:///etc/passwd", "ftp://example.com/x.pdf", "gopher://x/1"):
        with pytest.raises(ValueError):
            _download_pdf(bad)


def test_lab_server_binds_loopback_only():
    """serve_lab must bind 127.0.0.1, never 0.0.0.0."""
    from research_companion import lab_api
    src = inspect.getsource(lab_api.serve_lab)
    assert "127.0.0.1" in src
    assert "0.0.0.0" not in src
```

- [ ] **Step 2: Run** `python -m pytest tests/test_security_regressions.py -q`. Expected: traversal + loopback PASS (current code is safe); the scheme test likely FAILS (no validation today).
- [ ] **Step 3: Fix what fails.** In `research_companion/fetch.py::_download_pdf`, add at the top:

```python
    from urllib.parse import urlparse
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"refusing to download non-http(s) URL: {url!r}")
```

- [ ] **Step 4: Re-run the file → all PASS. Full gate** (confirm no existing fetch test used a non-http scheme).
- [ ] **Step 5: Commit** · `fix(security): scheme validation on PDF downloads + traversal/loopback regression tests`.

### Task 7: Adversarial security + correctness review (subagent passes)

**Files:** findings-driven; fixes land in the modules they touch, each with a regression test.

- [ ] **Step 1:** Dispatch a **security review** subagent over `research_companion/lab_api.py` (uploads, file serving, `/api/ingest` paths validation, workspace/view names → filesystem), `research_companion/mcp_server.py` + `mcp_tools.py`, and `parsers/_docling_worker.py` (no shell-injection; args passed as list). Instruction: report concrete exploitable findings with reproduction, severity, and the exact fix location — no theoretical/nitpick findings.
- [ ] **Step 2:** Dispatch a **correctness review** subagent over `research_companion/statcheck/`, `interop/`, `overlap.py`, `mcp_tools.py`, and `report.py` wiring with the same confirmed-findings-only bar.
- [ ] **Step 3:** For each CONFIRMED finding: failing regression test → minimal fix → targeted test → full gate. One commit per finding (`fix(security): …` / `fix: …`). If a finding is disputed or would change behavior the EMNLP paper describes, STOP and consult the user instead of forcing it.
- [ ] **Step 4:** If both reviews return zero confirmed findings, record that in the PR description and move on — do not invent work.

### Task 8: Content scrub + README polish + pyproject URLs

**Files:**
- Modify: `docs/superpowers/plans/2026-06-29-agent-runtime-core.md:19`, `docs/superpowers/specs/2026-07-11-port-v0517-improvements-design.md` (lines 4, 57), `README.md`, `pyproject.toml`
- Test: `tests/test_packaging.py` (append)

- [ ] **Step 1: Failing meta-tests** — append:

```python
def test_no_windows_dev_paths_in_tracked_docs():
    """Absolute dev-box paths must not appear in tracked markdown."""
    import subprocess
    out = subprocess.run(["git", "grep", "-l", "C:\\\\Users\\\\LARAIB", "--", "*.md"],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.stdout.strip() == "", f"dev paths leaked in: {out.stdout}"

def test_pyproject_has_homepage_and_changelog_urls():
    data = _load_pyproject()
    urls = data["project"]["urls"]
    for key in ("Homepage", "Documentation", "Changelog"):
        assert key in urls, f"[project.urls] missing {key}"

def test_readme_clone_cd_matches_repo_dirname():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "cd research-companion" not in text, "cd must match the cloned dir Research-Companion"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_packaging.py -q -k "dev_paths or homepage or clone_cd"` → 3 FAIL. (Also check `git grep -n "C:/Users/LARAIB"` forward-slash variants and fix those lines too.)
- [ ] **Step 3: Implement:**
  - Both `docs/superpowers/` files: replace absolute paths with generic references (`the repo root`, `a parallel local clone`).
  - `README.md`: both occurrences `cd research-companion` → `cd Research-Companion`; add badges under the title: `[![CI](https://github.com/Laraib-Hasan-Future/Research-Companion/actions/workflows/ci.yml/badge.svg)](…/actions/workflows/ci.yml)`, `[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)`, `[![Python 3.10–3.13](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)](pyproject.toml)`; replace the Contributing section body with a pointer to `CONTRIBUTING.md` + the three gates (JS via the glob); add one line: "This repository is the canonical home of Research Companion."
  - `pyproject.toml` `[project.urls]`: add `Homepage = "https://github.com/Laraib-Hasan-Future/Research-Companion"`, `Documentation = "https://github.com/Laraib-Hasan-Future/Research-Companion/blob/main/docs/DOCUMENTATION.md"`, `Changelog = "https://github.com/Laraib-Hasan-Future/Research-Companion/blob/main/docs/RELEASE_0.7.md"`.
- [ ] **Step 4: All 3 tests pass; full gate.**
- [ ] **Step 5: Commit** · `docs: scrub dev paths, README badges/casing/contributing, pyproject URLs`.

### Task 9: Launch PR + platform guardrails

**Files:** none (git/GitHub operations only).

- [ ] **Step 1: Full gate one final time** (expect ≥1880 py pass — baseline 1866 + new meta/security tests — 638 js, ruff clean).
- [ ] **Step 2: Push + PR:** `git push -u origin feat/oss-launch`; `gh pr create --base main --title "OSS launch readiness: guardrails, CI hardening, security audit" --body` summarizing phases + audit outcomes + the standing holds (publish held; mirror untouched).
- [ ] **Step 3: Wait for the PR's checks** — the new matrix, audit, ci-ok, and CodeQL must all pass on the PR (fix forward if not).
- [ ] **Step 4: Apply platform settings** (repo `Laraib-Hasan-Future/Research-Companion` ONLY):

```bash
# secret scanning + push protection + dependabot
gh api -X PATCH repos/Laraib-Hasan-Future/Research-Companion \
  -f security_and_analysis[secret_scanning][status]=enabled \
  -f security_and_analysis[secret_scanning_push_protection][status]=enabled
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/vulnerability-alerts
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/automated-security-fixes
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/private-vulnerability-reporting
# branch protection: PR required, ci-ok required, no force-push/deletion, 0 approvals (solo)
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/branches/main/protection \
  --input - <<'JSON'
{"required_status_checks":{"strict":false,"contexts":["ci-ok"]},
 "enforce_admins":false,
 "required_pull_request_reviews":{"required_approving_review_count":0},
 "restrictions":null,
 "allow_force_pushes":false,
 "allow_deletions":false}
JSON
```

- [ ] **Step 5: Verify protection works:** `git push origin HEAD:main` from a scratch commit must be REJECTED; `gh api repos/…/branches/main/protection` shows the config.
- [ ] **Step 6: Merge the PR through the guardrails** (`gh pr merge --merge`), confirm `main` green, delete `feat/oss-launch`.

**USER ACTIONS (flagged, not executable by the plan):** rotate the two local `.env` keys; when ready to ever publish: configure the PyPI trusted publisher (owner `Laraib-Hasan-Future`, repo `Research-Companion`, workflow `publish.yml`, environment `pypi`) and create the `pypi` environment in repo settings.
