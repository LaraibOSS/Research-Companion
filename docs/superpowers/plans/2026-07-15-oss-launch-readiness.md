# OSS Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Laraib-Hasan-Future/Research-Companion` a safely contributable public repo: community files, hardened CI, platform guardrails, and a security + correctness audit with fixes. This is a **contributor-readiness** launch, not a user-release: publishing stays held and PyPI remains at 0.5.14 while source is 0.7.1 — disclosed in the docs.

**Architecture:** All file changes land on `feat/oss-launch` and merge via one PR that must itself pass the new gating checks (`ci-ok` + `codeql-ok`). GitHub *settings* (branch protection, scanning, default token scope) are applied via `gh api` after the workflows exist on the PR. Meta-tests pin every guardrail so regressions fail CI.

**Tech Stack:** GitHub Actions (matrix, aggregate gates), CodeQL, pip-audit, dependency-review-action, PyPI Trusted Publishing (OIDC, build-once/publish-exact), pytest meta-tests + security regression tests.

## Global Constraints

- Branch `feat/oss-launch`. Commits `git -c user.name="Laraib Hasan" -c user.email="Lxh417bham@gmail.com" commit …`, **no AI trailer**, explicit `git add <paths>`.
- Full gate after every task: `python -m pytest -q` (baseline 1866 pass / 3 skip) · `node --test tests/js/*.test.mjs` (638 pass) · `ruff check research_companion tests examples`.
- **Publish stays HELD** — never push a `v*` tag.
- **NEVER touch `Laraib-Hasan-OSS/Research-Companion`** (frozen EMNLP-reviewer artifact).
- Nothing the EMNLP paper claims may break: `examples/demo_offline.py`, `eval/` harnesses, the Lab.
- No `CITATION.cff` / paper mention (deferred until the review decision).
- `docs/Medical/` stays untracked/untouched. Repo URL everywhere: `https://github.com/Laraib-Hasan-Future/Research-Companion`.
- **Required-check contexts (final):** `ci-ok`, `codeql-ok`. Branch protection uses `enforce_admins: true`, `strict: true`, `required_approving_review_count: 0`. **Never verify protection with a real push to `main`.**

---

### Task 1: .gitignore hardening + meta-test

**Files:** Modify `.gitignore`; Test `tests/test_packaging.py` (append).

- [ ] **Step 1: Failing test** — append to `tests/test_packaging.py`:

```python
def test_gitignore_covers_private_local_content():
    """docs/Medical and all .env variants (except .env.example) must be ignored."""
    gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in ("docs/Medical/", ".env.*", "!.env.example"):
        assert pattern in gi, f".gitignore missing {pattern!r}"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_packaging.py::test_gitignore_covers_private_local_content -q` → FAIL.
- [ ] **Step 3: Implement** — in `.gitignore` replace `.env` / `.env.local` with:

```
.env
.env.*
!.env.example
```

and add `docs/Medical/` under the `# Local user state` block.

- [ ] **Step 4:** Re-run test → PASS; `git status --short` no longer shows `docs/Medical/`.
- [ ] **Step 5: Full gate; commit** `.gitignore tests/test_packaging.py` · `chore(gitignore): ignore docs/Medical and all .env variants`.

### Task 2: Community & governance files + meta-test

**Files:** Create `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/{bug_report.yml,feature_request.yml,config.yml}`, `.github/dependabot.yml`; Test `tests/test_community_files.py` (new).

- [ ] **Step 1: Failing test** — create `tests/test_community_files.py`:

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
    assert "@Hasan-Laraib" in (REPO_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")

def test_security_md_points_to_private_reporting():
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    assert "security advisories" in text or "report a vulnerability" in text

def test_security_md_discloses_version_skew():
    """SECURITY.md must use an explicit version table (source 0.7.1 vs PyPI 0.5.14)."""
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "| Version" in text or "|Version" in text, "SECURITY.md needs a supported-version table"
    assert "main" in text and "PyPI" in text

def test_dependabot_covers_pip_and_actions():
    text = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "pip" in text and "github-actions" in text
```

- [ ] **Step 2: Run** `python -m pytest tests/test_community_files.py -q` → FAIL.
- [ ] **Step 3: Create the files** (real prose, no stubs):
  - `CONTRIBUTING.md`: setup (`git clone https://github.com/Laraib-Hasan-Future/Research-Companion.git`, `cd Research-Companion`, `pip install -e ".[dev]"`); the three gates verbatim; TDD expected; design principles (deterministic-first, char-span provenance, "never claim more than computed", local-first — no new services/DBs); run the Lab (`pip install -e ".[server]"` + `research-companion lab serve`); PR checklist (tests added, gates green, docs updated, no secrets); CI runs Python 3.10–3.13 on Ubuntu + Windows.
  - `SECURITY.md`: **explicit supported-version table** (rows: `main` → "Security fixes accepted"; "Latest PyPI release (0.5.14)" → "Yes"; "Older PyPI releases" → "No") plus a note that the source tree is 0.7.1 (unreleased; publishing held). Report privately via GitHub Security Advisories ("Report a vulnerability" on the Security tab) — **no public issues for vulns**; ack target 7 days; scope notes (local-first; Lab binds 127.0.0.1 and must not be exposed; keys only in local `.env`).
  - `CODE_OF_CONDUCT.md`: full **Contributor Covenant v2.1**; enforcement contact `@Hasan-Laraib` via GitHub.
  - `.github/CODEOWNERS`: `* @Hasan-Laraib`.
  - `.github/PULL_REQUEST_TEMPLATE.md`: Summary; Motivation; Test evidence (three gate commands + results); Checklist (tests added; three gates green; docs updated if user-facing; no secrets/private data).
  - `.github/ISSUE_TEMPLATE/bug_report.yml`: fields — what happened, repro steps, expected, version (`research-companion --version`), OS/Python, logs.
  - `.github/ISSUE_TEMPLATE/feature_request.yml`: problem, proposed solution, alternatives.
  - `.github/ISSUE_TEMPLATE/config.yml`: `blank_issues_enabled: true`; contact link to the repo Security-Advisories page for vulnerabilities.
  - `.github/dependabot.yml`: v2; `pip` (dir `/`, weekly) + `github-actions` (dir `/`, weekly).
- [ ] **Step 4:** `python -m pytest tests/test_community_files.py -q` → PASS (6 tests).
- [ ] **Step 5: Full gate; commit** the files + test · `docs(community): contributing, security policy, code of conduct, templates, dependabot`.

### Task 3: ci.yml overhaul — matrix, lint-once, pip-audit, package, dependency-review, ci-ok

**Files:** Modify `.github/workflows/ci.yml` (full rewrite), `tests/test_packaging.py` (replace `test_ci_workflow_has_node_test_command`; add assertions).

**Interfaces:** Produces jobs `test`, `lint`, `audit`, `package`, `dependency-review`, `ci-ok`. Task 9 requires status context **`ci-ok`**.

- [ ] **Step 1: Update meta-tests.** In `tests/test_packaging.py`, REPLACE `test_ci_workflow_has_node_test_command` with:

```python
def test_ci_workflow_runs_all_js_tests_via_glob():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "node --test tests/js/*.test.mjs" in content
    assert "reducer.test.mjs" not in content, "ci.yml must not hardcode JS filenames"

def test_ci_workflow_scopes_permissions():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "permissions:" in content and "contents: read" in content

def test_ci_workflow_has_python_matrix_and_windows():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in ("'3.10'", "'3.11'", "'3.12'", "'3.13'", "windows-latest"):
        assert needle in content, f"ci.yml matrix missing {needle}"

def test_ci_workflow_audits_and_packages_and_gates():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip-audit --strict ." in content, "ci.yml must audit the project with --strict"
    assert "python -m build" in content and "twine check" in content, "ci.yml must build+check the wheel"
    assert "dependency-review-action" in content, "ci.yml must run dependency review on PRs"
    assert "ci-ok" in content, "ci.yml must expose the ci-ok gate (required check)"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_packaging.py -q -k ci_workflow` → new tests FAIL.
- [ ] **Step 3: Rewrite `.github/workflows/ci.yml`** exactly:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

defaults:
  run:
    shell: bash

jobs:
  test:
    name: test (${{ matrix.os }}, ${{ matrix.python }})
    runs-on: ${{ matrix.os }}
    timeout-minutes: 20
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
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Install
        run: python -m pip install -e ".[dev]"
      - name: pytest
        run: python -m pytest -q

  lint:
    name: lint
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install -e ".[dev]"
      - name: ruff
        run: ruff check research_companion tests examples
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: JS tests
        run: node --test tests/js/*.test.mjs

  audit:
    name: audit
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install pip-audit
      - name: pip-audit (project)
        run: pip-audit --strict .

  package:
    name: package
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install build twine
      - name: Build distributions
        run: python -m build
      - name: twine check
        run: python -m twine check dist/*
      - name: Install wheel + smoke test
        run: |
          python -m venv wheel-test
          wheel-test/bin/python -m pip install dist/*.whl
          wheel-test/bin/research-companion --version
          wheel-test/bin/research-companion --help >/dev/null
          wheel-test/bin/python -c "from research_companion import add_paper, build_graph, chat, view"

  dependency-review:
    name: dependency-review
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/dependency-review-action@v4
        with:
          fail-on-severity: high

  ci-ok:
    name: ci-ok
    if: always()
    needs: [test, lint, audit, package, dependency-review]
    runs-on: ubuntu-latest
    steps:
      - name: Required jobs green (dependency-review may be skipped on push)
        run: |
          set -euo pipefail
          for r in "${{ needs.test.result }}" "${{ needs.lint.result }}" \
                   "${{ needs.audit.result }}" "${{ needs.package.result }}"; do
            [ "$r" = "success" ] || { echo "required job failed: $r"; exit 1; }
          done
          dr="${{ needs.dependency-review.result }}"
          [ "$dr" = "success" ] || [ "$dr" = "skipped" ] || { echo "dependency-review failed"; exit 1; }
```

Note: `wheel-test/bin/...` is Linux (the package job runs on ubuntu) — correct here.

- [ ] **Step 4: Run** `python -m pytest tests/test_packaging.py -q` → all pass.
- [ ] **Step 5: Full gate; commit** `.github/workflows/ci.yml tests/test_packaging.py` · `ci: matrix, lint-once, pip-audit --strict, wheel package job, dependency-review, ci-ok gate`.

### Task 4: CodeQL workflow with codeql-ok gate

**Files:** Create `.github/workflows/codeql.yml`; Test `tests/test_packaging.py` (append).

- [ ] **Step 1: Failing test:**

```python
def test_codeql_workflow_exists_and_gates():
    codeql = REPO_ROOT / ".github" / "workflows" / "codeql.yml"
    assert codeql.exists(), "Missing .github/workflows/codeql.yml"
    content = codeql.read_text(encoding="utf-8")
    assert "security-events: write" in content
    assert "python" in content and "javascript" in content
    assert "codeql-ok" in content, "codeql.yml must expose a stable codeql-ok gate"
```

- [ ] **Step 2: Run** → FAIL.
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

concurrency:
  group: codeql-${{ github.ref }}
  cancel-in-progress: true

jobs:
  analyze:
    name: Analyze (${{ matrix.language }})
    runs-on: ubuntu-latest
    timeout-minutes: 30
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

  codeql-ok:
    name: codeql-ok
    if: always()
    needs: [analyze]
    runs-on: ubuntu-latest
    steps:
      - name: CodeQL passed?
        run: |
          set -euo pipefail
          [ "${{ needs.analyze.result }}" = "success" ] || { echo "CodeQL failed"; exit 1; }
```

- [ ] **Step 4:** test passes; full gate.
- [ ] **Step 5: Commit** · `ci(security): CodeQL for python + javascript behind a codeql-ok gate`.

### Task 5: publish.yml → Trusted Publishing, build-once/publish-exact

**Files:** Modify `.github/workflows/publish.yml`; `tests/test_packaging.py` (replace `test_publish_workflow_has_secret_reference`).

- [ ] **Step 1: Replace meta-test:**

```python
def test_publish_workflow_uses_trusted_publishing_build_once():
    content = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "id-token: write" in content, "publish must request OIDC id-token"
    assert "pypa/gh-action-pypi-publish" in content
    assert "environment:" in content and "pypi" in content
    assert "PYPI_API_TOKEN" not in content, "long-lived token must be gone"
    assert "upload-artifact" in content and "download-artifact" in content, \
        "publish must build once and publish the exact tested artifact"
```

- [ ] **Step 2: Run** `-k publish` → new test FAILS.
- [ ] **Step 3: Rewrite `.github/workflows/publish.yml`:** trigger `push` tags `v*`; top-level `permissions: contents: read`. Two jobs:
  - `build` (ubuntu): checkout; verify the tag matches `pyproject` version AND the tagged commit is reachable from `main` (`git merge-base --is-ancestor <sha> origin/main`); `pip install -e ".[dev]" build twine`; `pytest -q`; `node --test tests/js/*.test.mjs`; `python -m build`; `twine check dist/*`; install the built wheel in a fresh venv and smoke-test `research-companion --version`; `actions/upload-artifact` the `dist/`.
  - `publish` (needs: build; `if: github.repository == 'Laraib-Hasan-Future/Research-Companion'`; `environment: pypi`; `permissions: id-token: write, contents: read`): `download-artifact` → `dist/`; `uses: pypa/gh-action-pypi-publish@release/v1` (no rebuild, no repo code execution, no token env).
- [ ] **Step 4: Run** `python -m pytest tests/test_packaging.py -q` → all pass (tag-trigger, pytest, build, twine-check, upload-guard assertions still satisfied).
- [ ] **Step 5: Full gate; commit** · `ci(publish): Trusted Publishing, build-once/publish-exact via pypi environment`.

### Task 6: SSRF/traversal hardening + regression tests

**Files:** Create `research_companion/net.py`; Modify `research_companion/fetch.py`; Test `tests/test_security_regressions.py` (new).

**Interfaces:** Produces `research_companion.net.validate_public_url(url: str) -> None` (raises `research_companion.fetch.FetchError` — actually raise a local `UrlSecurityError(ValueError)` and let fetch map it; see below). To avoid a fetch→net import cycle, `net.py` defines its own `UrlNotAllowed(Exception)`; `_download_pdf` catches it and re-raises `FetchError`, so the existing `_try_download_pdf` handler still swallows it.

- [ ] **Step 1: Write regression tests** — `tests/test_security_regressions.py`:

```python
"""Security regressions: URL SSRF/scheme, path traversal, loopback binding."""
import inspect  # noqa: F401  (kept only if a fallback source check is needed)

import pytest

from research_companion import net, store


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd", "ftp://example.com/x.pdf", "gopher://x/1",
    "http://user:pass@example.com/x.pdf",          # embedded creds
    "http://127.0.0.1/x.pdf", "http://localhost/x.pdf", "http://[::1]/x.pdf",
    "http://169.254.169.254/latest/meta-data",      # cloud metadata
    "http://10.0.0.5/x.pdf", "http://192.168.1.1/x.pdf", "http://172.16.0.2/x.pdf",
    "http://0.0.0.0/x.pdf",
])
def test_validate_public_url_rejects_dangerous(bad):
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url(bad)


@pytest.mark.parametrize("ok", [
    "https://arxiv.org/pdf/2410.05779", "http://export.arxiv.org/pdf/1234.5678",
])
def test_validate_public_url_allows_public(ok):
    net.validate_public_url(ok)  # must not raise


def test_download_pdf_maps_blocked_url_to_fetcherror():
    """A blocked URL must surface as FetchError so _try_download_pdf handles it."""
    from research_companion.fetch import FetchError, _download_pdf
    with pytest.raises(FetchError):
        _download_pdf("http://127.0.0.1/x.pdf")


def test_paper_id_cannot_traverse_paths():
    """A hostile paper_id must never escape the (test-isolated) papers dir."""
    root = store.papers_dir().resolve()          # conftest autouse-isolates this to tmp
    for hostile in ("../../evil", "..\\..\\evil", "a/../../b", "x:..%2F..%2Fy"):
        resolved = store.paper_dir(hostile).resolve()
        assert root == resolved.parent, f"{hostile!r} escaped: {resolved}"
        assert ".." not in resolved.name


def test_lab_server_binds_loopback_only(monkeypatch):
    """serve_lab must invoke uvicorn.run with host=127.0.0.1 (behavioral, not source scan)."""
    import uvicorn
    from research_companion import lab_api
    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: captured.update(k))
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: None)
    lab_api.serve_lab(open_browser=False)
    assert captured.get("host") == "127.0.0.1"
    assert captured.get("host") != "0.0.0.0"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_security_regressions.py -q`. Expected: traversal PASSES; `net`/download/bind tests FAIL (module + host-arg not present yet). If the loopback test errors because `serve_lab` does more than call `uvicorn.run`, also monkeypatch `research_companion.store` env as needed — but the `.env` load is exception-safe, so patching `uvicorn.run` + `webbrowser.open` should suffice.
- [ ] **Step 3a: Create `research_companion/net.py`:**

```python
"""URL egress guardrails for user-supplied download URLs (SSRF hardening)."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB cap for a single PDF
MAX_REDIRECTS = 5


class UrlNotAllowed(Exception):
    """Raised when a URL is disallowed by the egress policy."""


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved or addr.is_unspecified)


def validate_public_url(url: str) -> None:
    """Raise UrlNotAllowed unless *url* is a public http(s) URL with no creds and
    a hostname that resolves ONLY to public IP addresses."""
    parts = urlparse(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise UrlNotAllowed(f"scheme not allowed: {url!r}")
    if parts.username or parts.password:
        raise UrlNotAllowed("embedded credentials are not allowed")
    host = parts.hostname
    if not host:
        raise UrlNotAllowed(f"missing host: {url!r}")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlNotAllowed(f"cannot resolve host {host!r}: {exc}") from exc
    resolved = {info[4][0] for info in infos}
    if not resolved:
        raise UrlNotAllowed(f"host {host!r} resolved to no addresses")
    for ip in resolved:
        if not _ip_is_public(ip):
            raise UrlNotAllowed(f"host {host!r} resolves to non-public address {ip}")
```

- [ ] **Step 3b: Harden `research_companion/fetch.py::_download_pdf`** — validate up front, disable auto-redirects, follow manually with per-hop revalidation + cap, stream with a size cap, map `UrlNotAllowed` → `FetchError`:

```python
def _download_pdf(url: str, *, timeout: float = 60.0) -> bytes:
    from research_companion.net import MAX_DOWNLOAD_BYTES, MAX_REDIRECTS, UrlNotAllowed, validate_public_url
    try:
        current = url
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT},
                          follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                validate_public_url(current)          # re-validate EVERY hop
                resp = client.get(current)
                if resp.is_redirect:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise FetchError(f"redirect without Location from {current}")
                    current = str(resp.url.join(loc))
                    continue
                resp.raise_for_status()
                body = resp.content
                if len(body) > MAX_DOWNLOAD_BYTES:
                    raise FetchError(f"PDF exceeds size cap ({MAX_DOWNLOAD_BYTES} bytes): {url}")
                if not body:
                    raise FetchError(f"empty PDF from {url}")
                if not body.startswith(b"%PDF-"):
                    raise FetchError(f"response from {url} does not look like a PDF")
                return body
            raise FetchError(f"too many redirects for {url}")
    except UrlNotAllowed as exc:
        raise FetchError(str(exc)) from exc
```

- [ ] **Step 4: Run** `python -m pytest tests/test_security_regressions.py -q` → all PASS. **Full gate** — confirm no existing `fetch`/`discover` test relied on redirect auto-following to a private host or a non-PDF body (they use real arxiv/crossref, all public + PDF).
- [ ] **Step 5: Commit** `research_companion/net.py research_companion/fetch.py tests/test_security_regressions.py` · `fix(security): SSRF egress guard (scheme/creds/private-IP/redirect/size) + traversal & loopback regressions`.

### Task 7: Adversarial security + correctness review (subagent passes)

**Files:** findings-driven; fixes land where they belong, each with a regression test.

- [ ] **Step 1:** Dispatch a **security review** subagent over `research_companion/lab_api.py` (upload filename handling, `/pdf` + `/text` serving via `paper_id`→dirname, `/api/ingest` `paths` validation, workspace/view names → paths, **Host/Origin/CORS/CSRF posture and DNS-rebinding resistance for a loopback web server**, stored/reflected XSS from filenames + paper metadata + extracted text rendered in the Lab), `research_companion/mcp_server.py` + `mcp_tools.py` (input validation, `paper_id` path escape), and `parsers/_docling_worker.py` (subprocess args passed as a list, no shell). Bar: concrete exploitable findings only, with repro + severity + exact fix site.
- [ ] **Step 2:** Dispatch a **correctness review** subagent over `research_companion/statcheck/`, `interop/`, `overlap.py`, `mcp_tools.py`, `report.py` wiring — same confirmed-findings-only bar.
- [ ] **Step 3:** Per CONFIRMED finding: failing regression test → minimal fix → targeted test → full gate; one commit each. If a fix would change behavior the EMNLP paper describes, STOP and consult the user.
- [ ] **Step 4:** If a review returns zero confirmed findings, record that in the PR body — invent no work.

### Task 8: Content scrub + README polish + pyproject URLs

**Files:** Modify `docs/superpowers/plans/2026-06-29-agent-runtime-core.md`, `docs/superpowers/specs/2026-07-11-port-v0517-improvements-design.md`, `README.md`, `pyproject.toml`; Test `tests/test_packaging.py` (append).

- [ ] **Step 1: Failing meta-tests:**

```python
def test_no_windows_dev_paths_in_tracked_docs():
    import subprocess
    out = subprocess.run(["git", "grep", "-lI", "-e", r"C:\\Users\\LARAIB",
                          "-e", "C:/Users/LARAIB", "--", "*.md"],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.stdout.strip() == "", f"dev paths leaked in: {out.stdout}"

def test_pyproject_has_homepage_and_changelog_urls():
    urls = _load_pyproject()["project"]["urls"]
    for key in ("Homepage", "Documentation", "Changelog"):
        assert key in urls, f"[project.urls] missing {key}"

def test_readme_clone_cd_and_import_are_valid():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "cd research-companion" not in text, "cd must match cloned dir Research-Companion"
    assert "import research-companion" not in text, "hyphenated import is invalid Python"
    assert "research-companion." not in text, "no hyphenated module attribute access in examples"
```

- [ ] **Step 2: Run** `-k "dev_paths or homepage or clone_cd"` → 3 FAIL.
- [ ] **Step 3: Implement:**
  - Both `docs/superpowers/` files: replace `C:\Users\LARAIB\...` / `C:/Users/LARAIB/...` with generic references (`the repo root`, `a parallel local clone`).
  - `README.md`: both `cd research-companion` → `cd Research-Companion`; fix the programmatic-API example — replace `import research-companion` / `research-companion.add_paper(...)` etc. with `from research_companion import add_paper, build_graph, chat, view` and use the bare function names; add badges under the title (CI, `License: MIT`, `python 3.10–3.13`); replace the Contributing body with a pointer to `CONTRIBUTING.md` + the three gates (JS via glob); add "This repository is the canonical home of Research Companion."; add a one-line note that the PyPI release (0.5.14) trails the source tree (0.7.1) while publishing is held.
  - `pyproject.toml` `[project.urls]`: add `Homepage`, `Documentation` (→ `blob/main/docs/DOCUMENTATION.md`), `Changelog` (→ `blob/main/docs/RELEASE_0.7.md`).
- [ ] **Step 4:** 3 tests pass; full gate.
- [ ] **Step 5: Commit** · `docs: scrub dev paths, fix README import/cd + badges/contributing, pyproject URLs`.

### Task 9: Launch PR + platform guardrails (NO push to main)

**Files:** none (git/GitHub operations only). **`gh` must have admin on the repo; if not, stop after Step 2 and hand the maintainer the Step-4 commands.**

- [ ] **Step 0 (pre-launch gate — maintainer must confirm before Step 2):**

```
[ ] New OpenAI credential generated; OLD one revoked at platform
[ ] New Hugging Face credential generated; OLD one revoked at platform
[ ] Any credential ever pasted into chat revoked
[ ] Local .env updated with the new values
[ ] `git log --all -- .env` still empty (never committed) — re-confirmed
```

- [ ] **Step 1: Full gate one final time** (expect ≥1885 py pass — baseline 1866 + new meta/security tests — 638 js, ruff clean).
- [ ] **Step 2: Push + PR:** `git push -u origin feat/oss-launch`; `gh pr create --base main --title "OSS launch readiness: guardrails, CI hardening, security audit" --body <summary of phases, audit outcomes, and holds (publish held; PyPI 0.5.14 vs source 0.7.1; mirror untouched)>`.
- [ ] **Step 3: Wait for the PR checks** — `test` matrix, `lint`, `audit`, `package`, `dependency-review`, `ci-ok`, and `codeql-ok` must all pass on the PR (fix forward if not). Confirm no CI job requires secrets (only `publish.yml` does) so fork PRs will run cleanly.
- [ ] **Step 4: Apply platform settings** (repo `Laraib-Hasan-Future/Research-Companion` ONLY; each `gh api` wrapped so a failure aborts and is inspected):

```bash
set -euo pipefail

# default workflow token → read-only repo-wide
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/actions/permissions/workflow \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false

# secret scanning + push protection
gh api -X PATCH repos/Laraib-Hasan-Future/Research-Companion \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'

# dependabot alerts + automated security fixes + private vuln reporting
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/vulnerability-alerts
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/automated-security-fixes
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/private-vulnerability-reporting

# branch protection: PR required, ci-ok + codeql-ok required & up-to-date,
# admins enforced, 0 approvals (solo), no force-push/deletion
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/branches/main/protection --input - <<'JSON'
{"required_status_checks":{"strict":true,"contexts":["ci-ok","codeql-ok"]},
 "enforce_admins":true,
 "required_pull_request_reviews":{"required_approving_review_count":0},
 "restrictions":null,
 "allow_force_pushes":false,
 "allow_deletions":false}
JSON
```

- [ ] **Step 5: Verify — WITHOUT pushing to main.** Read the config back and assert intent; do NOT run `git push … HEAD:main`:

```bash
gh api repos/Laraib-Hasan-Future/Research-Companion/branches/main/protection \
  --jq '{admins:.enforce_admins.enabled, strict:.required_status_checks.strict,
         contexts:.required_status_checks.contexts, force:.allow_force_pushes.enabled,
         del:.allow_deletions.enabled, approvals:.required_pull_request_reviews.required_approving_review_count}'
# Expect: admins=true, strict=true, contexts=[ci-ok,codeql-ok], force=false, del=false, approvals=0
```

Also confirm on the open PR that GitHub requests review from `@Hasan-Laraib` (CODEOWNERS wired) and that merge is blocked until `ci-ok`+`codeql-ok` are green.

- [ ] **Step 6: Merge the PR through the guardrails** (`gh pr merge --merge --delete-branch`), confirm `main` green.

**USER ACTIONS (flagged, not executable by the plan):**
- The Step-0 credential rotation (above).
- Before ever publishing: configure the PyPI trusted publisher (owner `Laraib-Hasan-Future`, repo `Research-Companion`, workflow `publish.yml`, environment `pypi`) and create the `pypi` environment (with protection) in repo settings.
- After the first successful Trusted-Publishing release: **delete the `PYPI_API_TOKEN` GitHub secret and revoke the token on PyPI**; confirm no workflow still references it.

## Notes on review items intentionally scoped down
- **Traversal test isolation:** `tests/conftest.py` has an autouse `isolated_papergraph_dir` fixture, so `store.papers_dir()` is already a per-test tmp dir — the test is safe without threading `tmp_path` (it now asserts via `paper_dir()` under that isolated root).
- **Full-SHA action pinning / YAML-parsing meta-tests:** declined. SHA-pinning is high maintenance for a solo maintainer and Dependabot's `github-actions` updates cover action CVEs; `@vN` tags are the pragmatic norm. Substring meta-tests stay dep-free (no PyYAML dev-dep).
- **SSRF depth:** the egress guard blocks scheme/creds/private-IPs/redirects/size — proportionate to a local single-user CLI; a full DNS-rebinding/egress-firewall model is out of scope.
