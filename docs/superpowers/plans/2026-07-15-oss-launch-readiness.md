# OSS Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This plan is the single authoritative source.** The design doc
> `docs/superpowers/specs/2026-07-14-oss-launch-readiness-design.md` is marked
> Superseded; where they differ, THIS plan wins. Do not execute both as
> independent instructions.

**Goal:** Make `Laraib-Hasan-Future/Research-Companion` a safely contributable public repo: community files, hardened CI, platform guardrails, and a security + correctness audit with fixes. This is a **contributor-readiness** launch, not a user-release: publishing stays held and PyPI remains at 0.5.14 while source is 0.7.1 — disclosed in the docs.

**Architecture:** All file changes land on `feat/oss-launch` and merge via one PR that must itself pass the gating checks (`ci-ok` + `codeql-ok`). GitHub *settings* (branch protection, scanning, default token scope) are applied via `gh api` after the workflows exist on the PR. Meta-tests pin every guardrail so regressions fail CI.

**Tech Stack:** GitHub Actions (matrix, aggregate gates), CodeQL, pip-audit, dependency-review-action, PyPI Trusted Publishing (OIDC, build-once/publish-exact), pytest meta-tests + security regression tests.

## Global Constraints

- Branch `feat/oss-launch`. Commits `git -c user.name="Laraib Hasan" -c user.email="Lxh417bham@gmail.com" commit …`, **no AI trailer**, explicit `git add <paths>`.
- Full gate after every task: `python -m pytest -q` · `node --test tests/js/*.test.mjs` · `ruff check research_companion tests examples`. **All discovered tests must pass with no regressions** vs. the branch baseline (currently ~1868 py / 3 skip, 638 js); the PR records baseline→final counts and no previously-tracked test file may disappear. Do not hard-code an exact expected count (parametrization/consolidation shifts it legitimately).
- **Publish stays HELD** — never push a `v*` tag.
- **NEVER touch `Laraib-Hasan-OSS/Research-Companion`** (frozen EMNLP-reviewer artifact).
- Nothing the EMNLP paper claims may break: `examples/demo_offline.py`, `eval/` harnesses, the Lab.
- No `CITATION.cff` / paper mention (deferred until the review decision).
- `docs/Medical/` stays untracked/untouched. Repo URL everywhere: `https://github.com/Laraib-Hasan-Future/Research-Companion`.
- **Pinned GitHub Action majors (verified current 2026-07-17):** `actions/checkout@v7`, `actions/setup-python@v6`, `actions/setup-node@v7`, `actions/upload-artifact@v7`, `actions/download-artifact@v8`, `actions/dependency-review-action@v5`, `github/codeql-action/*@v4`, `pypa/gh-action-pypi-publish@release/v1`.
- **Required-check contexts (final):** `ci-ok`, `codeql-ok`, via the `checks` array. Branch protection uses `enforce_admins: true`, `strict: true`, `required_approving_review_count: 0`. **Never verify protection with a real push to `main`.**

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

def test_security_md_states_precise_version_status():
    """No blanket 'supported' promise for PyPI 0.5.14; must disclose the source/PyPI skew."""
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "| Version" in text or "|Version" in text, "SECURITY.md needs a version-status table"
    assert "0.5.14" in text and "0.7.1" in text, "must disclose PyPI 0.5.14 vs source 0.7.1"
    assert "legacy" in text.lower() or "not equivalent" in text.lower()

def test_dependabot_covers_pip_and_actions():
    text = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "pip" in text and "github-actions" in text
```

- [ ] **Step 2: Run** `python -m pytest tests/test_community_files.py -q` → FAIL.
- [ ] **Step 3: Create the files** (real prose, no stubs):
  - `CONTRIBUTING.md`: setup (`git clone https://github.com/Laraib-Hasan-Future/Research-Companion.git`, `cd Research-Companion`, `pip install -e ".[dev]"`); the three gates verbatim; TDD expected; design principles (deterministic-first, char-span provenance, "never claim more than computed", local-first — no new services/DBs); run the Lab (`pip install -e ".[server]"` + `research-companion lab serve`); PR checklist (tests added, gates green, docs updated, no secrets); CI runs Python 3.10–3.13 on Ubuntu + Windows.
  - `SECURITY.md`: **precise version-status table** — rows: `main` / source 0.7.1 → "Actively maintained; security reports accepted"; `PyPI 0.5.14` → "Legacy installable release; **not equivalent** to current source"; "Releases older than 0.5.14" → "Unsupported". Followed by: *"Until publishing resumes, security fixes are applied to `main`. Users of the legacy PyPI release may need to install the corrected source version, as a patched PyPI distribution is not currently guaranteed."* Then private reporting via GitHub Security Advisories ("Report a vulnerability" on the Security tab) — **no public issues for vulns**; ack target 7 days; scope notes (local-first; Lab binds 127.0.0.1 and must not be exposed; keys only in local `.env`).
  - `CODE_OF_CONDUCT.md`: full **Contributor Covenant v2.1**; enforcement contact `@Hasan-Laraib` via GitHub.
  - `.github/CODEOWNERS`: `* @Hasan-Laraib`.
  - `.github/PULL_REQUEST_TEMPLATE.md`: Summary; Motivation; Test evidence (three gate commands + results); Checklist (tests added; three gates green; docs updated if user-facing; no secrets/private data).
  - `.github/ISSUE_TEMPLATE/bug_report.yml`: fields — what happened, repro steps, expected, version (`research-companion --version`), OS/Python, logs.
  - `.github/ISSUE_TEMPLATE/feature_request.yml`: problem, proposed solution, alternatives.
  - `.github/ISSUE_TEMPLATE/config.yml`: `blank_issues_enabled: true`; contact link to the repo Security-Advisories page for vulnerabilities.
  - `.github/dependabot.yml`: v2; `pip` (dir `/`, weekly) + `github-actions` (dir `/`, weekly).
- [ ] **Step 4:** `python -m pytest tests/test_community_files.py -q` → PASS (6 tests).
- [ ] **Step 5: Full gate; commit** the files + test · `docs(community): contributing, security policy, code of conduct, templates, dependabot`.

### Task 3: ci.yml overhaul — matrix, lint-once, pip-audit, package (wheel+sdist+assets+extras), dependency-review, ci-ok

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

def test_ci_workflow_audits_packages_and_gates():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip-audit --strict ." in content, "ci.yml must audit the project with --strict"
    assert "python -m build" in content and "twine check" in content, "ci.yml must build+check dists"
    assert "dist/*.whl" in content and "dist/*.tar.gz" in content, "package job must install BOTH wheel and sdist"
    assert "lab/static/index.html" in content, "package job must assert packaged static assets"
    assert "dependency-review-action@v5" in content, "ci.yml must run dependency review (v5) on PRs"
    assert "ci-ok" in content, "ci.yml must expose the ci-ok gate (required check)"

def test_ci_workflow_uses_current_action_majors():
    content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for good in ("actions/checkout@v7", "actions/setup-python@v6", "actions/setup-node@v7"):
        assert good in content, f"ci.yml must use {good}"
    for stale in ("actions/checkout@v4", "actions/setup-python@v5", "actions/setup-node@v4"):
        assert stale not in content, f"ci.yml still pins stale {stale}"
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
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python }}
      - run: python -m pip install -e ".[dev]"
      - run: python -m pytest -q

  lint:
    name: lint
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: python -m pip install -e ".[dev]"
      - run: ruff check research_companion tests examples
      - uses: actions/setup-node@v7
        with:
          node-version: '20'
      - run: node --test tests/js/*.test.mjs

  audit:
    name: audit
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: python -m pip install pip-audit
      - run: pip-audit --strict .

  package:
    name: package
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: python -m pip install build twine
      - name: Build distributions
        run: python -m build
      - name: twine check
        run: python -m twine check dist/*
      - name: Install WHEEL + smoke test (base, server, mcp extras)
        run: |
          python -m venv wheel-test
          wheel-test/bin/python -m pip install "$(echo dist/*.whl)[server,mcp]"
          wheel-test/bin/research-companion --version
          wheel-test/bin/research-companion --help >/dev/null
          wheel-test/bin/python -c "from research_companion import add_paper, build_graph, chat, view"
          wheel-test/bin/python -c "from importlib.resources import files; \
            assert files('research_companion').joinpath('lab/static/index.html').is_file(), \
            'packaged Lab static assets missing from wheel'"
          wheel-test/bin/python -c "from research_companion.mcp_server import create_server; create_server()"
      - name: Install SDIST + smoke test
        run: |
          python -m venv sdist-test
          sdist-test/bin/python -m pip install dist/*.tar.gz
          sdist-test/bin/research-companion --version
          sdist-test/bin/python -c "from research_companion import add_paper, build_graph, chat, view"
          sdist-test/bin/python -c "from importlib.resources import files; \
            assert files('research_companion').joinpath('lab/static/index.html').is_file(), \
            'packaged Lab static assets missing from sdist'"

  dependency-review:
    name: dependency-review
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: actions/dependency-review-action@v5
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

Note: the `package` job runs on Ubuntu so `wheel-test/bin/...` is correct. `create_server()` succeeds only with the `mcp` extra installed (it is), exercising the optional-dep path.

- [ ] **Step 4: Run** `python -m pytest tests/test_packaging.py -q` → all pass.
- [ ] **Step 5: Full gate; commit** `.github/workflows/ci.yml tests/test_packaging.py` · `ci: matrix, lint-once, pip-audit --strict, wheel+sdist+assets+extras package job, dependency-review, ci-ok gate; bump action majors`.

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
    assert "codeql-action/init@v4" in content and "codeql-action/analyze@v4" in content
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
      - uses: actions/checkout@v7
      - uses: github/codeql-action/init@v4
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/analyze@v4
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
- [ ] **Step 5: Commit** · `ci(security): CodeQL (v4) for python + javascript behind a codeql-ok gate`.

### Task 5: publish.yml → Trusted Publishing, build-once/publish-exact, full-history reachability

**Files:** Modify `.github/workflows/publish.yml`; `tests/test_packaging.py` (replace `test_publish_workflow_has_secret_reference`).

- [ ] **Step 1: Replace meta-test:**

```python
def test_publish_workflow_uses_trusted_publishing_build_once():
    content = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "id-token: write" in content, "publish must request OIDC id-token"
    assert "pypa/gh-action-pypi-publish@release/v1" in content
    assert "environment:" in content and "pypi" in content
    assert "PYPI_API_TOKEN" not in content, "long-lived token must be gone"
    assert "upload-artifact@v7" in content and "download-artifact@v8" in content, \
        "publish must build once and publish the exact tested artifact"
    assert "fetch-depth: 0" in content, "reachability check needs full git history"
    assert "git rev-list -n 1" in content, "resolve annotated tags to a commit before ancestry check"
```

- [ ] **Step 2: Run** `-k publish` → new test FAILS.
- [ ] **Step 3: Rewrite `.github/workflows/publish.yml`:** trigger `push` tags `v*`; top-level `permissions: contents: read`. Two jobs:
  - `build` (ubuntu): `actions/checkout@v7` **with `fetch-depth: 0`**; `actions/setup-python@v6`; verify tag↔version and reachability from `origin/main`:

```yaml
      - name: Verify tag matches version and is on main
        run: |
          set -euo pipefail
          TAG_VERSION="${GITHUB_REF_NAME#v}"
          PROJECT_VERSION="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
          [ "$TAG_VERSION" = "$PROJECT_VERSION" ] || { echo "tag $TAG_VERSION != project $PROJECT_VERSION"; exit 1; }
          git fetch origin main --quiet
          TAG_COMMIT="$(git rev-list -n 1 "$GITHUB_REF_NAME")"
          git merge-base --is-ancestor "$TAG_COMMIT" origin/main || { echo "tagged commit not on main"; exit 1; }
```

    then `pip install -e ".[dev]" build twine`; `python -m pytest -q`; `actions/setup-node@v7` + `node --test tests/js/*.test.mjs`; `python -m build`; `python -m twine check dist/*`; install the built wheel in a fresh venv and smoke `research-companion --version`; `actions/upload-artifact@v7` the `dist/`.
  - `publish` (needs: build; `if: github.repository == 'Laraib-Hasan-Future/Research-Companion'`; `environment: pypi`; `permissions: id-token: write, contents: read`): `actions/download-artifact@v8` → `dist/`; `uses: pypa/gh-action-pypi-publish@release/v1` (no rebuild, no repo code execution, no token env).
- [ ] **Step 4: Run** `python -m pytest tests/test_packaging.py -q` → all pass (tag-trigger, pytest, build, twine-check, upload-guard assertions still satisfied).
- [ ] **Step 5: Full gate; commit** · `ci(publish): Trusted Publishing, build-once/publish-exact, full-history reachability check`.

### Task 6: SSRF/traversal hardening + regression tests

**Files:** Create `research_companion/net.py`; Modify `research_companion/fetch.py`; Test `tests/test_security_regressions.py` (new).

**Interfaces (single, consistent exception model):**
- `research_companion.net.validate_public_url(url: str) -> None` raises **`net.UrlNotAllowed`** (an `Exception` subclass) on any disallowed URL. `net` imports nothing from `fetch` (no cycle).
- `fetch._download_pdf()` catches `UrlNotAllowed` **and** `httpx.HTTPError` and re-raises **`fetch.FetchError`**, preserving the established caller contract (`_try_download_pdf` already swallows `FetchError`).
- Policy is **globally-reachable only** via `ipaddress.ip_address(...).is_global` (correctly excludes CGNAT `100.64/10`, TEST-NET, `192.0.2/24`, `198.18/15`, `2001:db8::/32`, etc.), not a hand-rolled flag list.
- **Honesty caveat (documented in the module + SECURITY.md):** this is a *best-effort application-level egress guard*. Because `validate_public_url` resolves the host and httpx resolves again at connect time, it does not fully prevent DNS-rebinding/TOCTOU; connection-IP pinning and network egress controls are out of scope for a local single-user CLI.

- [ ] **Step 1: Write regression tests** — `tests/test_security_regressions.py`:

```python
"""Security regressions: URL egress guard (deterministic DNS), traversal, loopback bind."""
import socket

import httpx
import pytest

from research_companion import net, store


def _resolves_to(*ips):
    """Return a fake getaddrinfo that resolves any host to the given IPs."""
    def fake(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET,
                 socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))
                for ip in ips]
    return fake


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x.pdf", "gopher://x/1",
    "http://user:pass@example.com/x.pdf",           # embedded creds
    "https://example.org:notaport/x.pdf",           # invalid port
    "https:///nohost",                              # missing host
])
def test_reject_by_static_policy(url):
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url(url)


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "::1", "169.254.169.254", "10.0.0.5", "192.168.1.1",
    "172.16.0.2", "0.0.0.0", "100.64.0.1", "198.18.0.1",
    "192.0.2.1", "198.51.100.1", "203.0.113.1", "2001:db8::1",
])
def test_reject_non_global_resolved_ip(ip, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolves_to(ip))
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url("https://papers.example.org/p.pdf")


@pytest.mark.parametrize("ip", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_allow_global_resolved_ip(ip, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolves_to(ip))
    net.validate_public_url("https://papers.example.org/p.pdf")  # must not raise


def test_reject_mixed_public_and_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolves_to("93.184.216.34", "127.0.0.1"))
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url("https://papers.example.org/p.pdf")


def test_reject_zero_addresses_and_gaierror(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url("https://none.example.org/p.pdf")
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url("https://bad.example.org/p.pdf")


def test_download_pdf_maps_blocked_url_to_fetcherror():
    """A blocked URL (literal loopback, no DNS) surfaces as FetchError."""
    from research_companion.fetch import FetchError, _download_pdf
    with pytest.raises(FetchError):
        _download_pdf("http://127.0.0.1/x.pdf")


# --- streaming size cap + redirects, deterministic via httpx.MockTransport ----

def _download_with(monkeypatch, handler):
    """Force fetch's internal httpx.Client to use a MockTransport, and allow any host."""
    monkeypatch.setattr(net, "validate_public_url", lambda url: None)
    import research_companion.fetch as fetch_mod
    real_client = httpx.Client
    def fake_client(*a, **k):
        k.pop("follow_redirects", None)
        return real_client(*a, transport=httpx.MockTransport(handler),
                           follow_redirects=False, **k)
    monkeypatch.setattr(fetch_mod.httpx, "Client", fake_client)
    from research_companion.fetch import _download_pdf
    return _download_pdf


def test_stream_rejects_oversized_content_length(monkeypatch):
    from research_companion.net import MAX_DOWNLOAD_BYTES
    from research_companion.fetch import FetchError
    def handler(req):
        return httpx.Response(200, headers={"content-length": str(MAX_DOWNLOAD_BYTES + 1)},
                              content=b"%PDF-xx")
    dl = _download_with(monkeypatch, handler)
    with pytest.raises(FetchError):
        dl("https://ok.example.org/p.pdf")


def test_stream_rejects_oversized_body_without_content_length(monkeypatch):
    from research_companion.net import MAX_DOWNLOAD_BYTES
    from research_companion.fetch import FetchError
    big = b"%PDF-" + b"a" * (MAX_DOWNLOAD_BYTES + 10)
    def handler(req):
        return httpx.Response(200, content=big)   # httpx sets content-length; drop it
    def handler_nolen(req):
        r = httpx.Response(200, content=big)
        r.headers.pop("content-length", None)
        return r
    dl = _download_with(monkeypatch, handler_nolen)
    with pytest.raises(FetchError):
        dl("https://ok.example.org/p.pdf")


def test_stream_rejects_non_pdf_and_empty(monkeypatch):
    from research_companion.fetch import FetchError
    for content in (b"", b"<html>not a pdf</html>"):
        dl = _download_with(monkeypatch, lambda req, c=content: httpx.Response(200, content=c))
        with pytest.raises(FetchError):
            dl("https://ok.example.org/p.pdf")


def test_stream_follows_bounded_redirects_then_downloads(monkeypatch):
    hops = {"n": 0}
    def handler(req):
        if hops["n"] < 2:
            hops["n"] += 1
            return httpx.Response(302, headers={"location": "https://ok.example.org/next"})
        return httpx.Response(200, content=b"%PDF-1.7 minimal")
    dl = _download_with(monkeypatch, handler)
    assert dl("https://ok.example.org/start").startswith(b"%PDF-")


def test_stream_rejects_too_many_redirects(monkeypatch):
    from research_companion.fetch import FetchError
    def handler(req):
        return httpx.Response(302, headers={"location": "https://ok.example.org/loop"})
    dl = _download_with(monkeypatch, handler)
    with pytest.raises(FetchError):
        dl("https://ok.example.org/start")


def test_paper_id_cannot_traverse_paths():
    """A hostile paper_id must never escape the (conftest-isolated) papers dir."""
    root = store.papers_dir().resolve()
    for hostile in ("../../evil", "..\\..\\evil", "a/../../b", "x:..%2F..%2Fy"):
        resolved = store.paper_dir(hostile).resolve()
        assert root == resolved.parent, f"{hostile!r} escaped to {resolved}"
        assert ".." not in resolved.name


def test_lab_server_binds_loopback_only(monkeypatch):
    """serve_lab must call uvicorn.run(host='127.0.0.1') — behavioral, not source scan."""
    import uvicorn
    from research_companion import lab_api
    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: captured.update(k))
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: None)
    lab_api.serve_lab(open_browser=False)
    assert captured.get("host") == "127.0.0.1"
    assert captured.get("host") != "0.0.0.0"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_security_regressions.py -q`. Expected: traversal PASSES; `net`/download/streaming/bind tests FAIL (module + streaming not present). If `serve_lab` reads `.env` etc., note it is exception-safe, so patching `uvicorn.run` + `webbrowser.open` suffices.
- [ ] **Step 3a: Create `research_companion/net.py`:**

```python
"""URL egress guardrails for user-supplied download URLs (best-effort SSRF hardening).

NOT a complete SSRF defense: the host is resolved here and again by the HTTP client
at connect time (a TOCTOU/DNS-rebinding window). Connection-IP pinning and network
egress controls are out of scope for this local single-user tool.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB cap for a single PDF
MAX_REDIRECTS = 5


class UrlNotAllowed(Exception):
    """Raised when a URL is disallowed by the egress policy."""


def validate_public_url(url: str) -> None:
    """Raise UrlNotAllowed unless *url* is an http(s) URL, credential-free, whose
    host resolves ONLY to globally-reachable IP addresses."""
    try:
        parts = urlparse(url)
    except ValueError as exc:
        raise UrlNotAllowed(f"unparseable URL: {url!r}") from exc
    if parts.scheme.lower() not in ("http", "https"):
        raise UrlNotAllowed(f"scheme not allowed: {url!r}")
    if parts.username or parts.password:
        raise UrlNotAllowed("embedded credentials are not allowed")
    try:
        port = parts.port  # raises ValueError on a non-numeric port
    except ValueError as exc:
        raise UrlNotAllowed(f"invalid port in {url!r}") from exc
    host = parts.hostname
    if not host:
        raise UrlNotAllowed(f"missing host: {url!r}")
    try:
        infos = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlNotAllowed(f"cannot resolve host {host!r}: {exc}") from exc
    resolved = {info[4][0] for info in infos}
    if not resolved:
        raise UrlNotAllowed(f"host {host!r} resolved to no addresses")
    for ip in resolved:
        # strip IPv6 scope id if present (e.g. 'fe80::1%eth0')
        clean = ip.split("%", 1)[0]
        if not ipaddress.ip_address(clean).is_global:
            raise UrlNotAllowed(f"host {host!r} resolves to non-global address {ip}")
```

- [ ] **Step 3b: Rewrite `research_companion/fetch.py::_download_pdf`** — validate + stream with a running size cap + manual bounded redirects, mapping both `UrlNotAllowed` and `httpx.HTTPError` to `FetchError`:

```python
def _download_pdf(url: str, *, timeout: float = 60.0) -> bytes:
    from research_companion.net import (MAX_DOWNLOAD_BYTES, MAX_REDIRECTS,
                                        UrlNotAllowed, validate_public_url)
    current = url
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT},
                          follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                validate_public_url(current)          # re-validate EVERY hop
                with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        loc = resp.headers.get("location")
                        if not loc:
                            raise FetchError(f"redirect without Location from {current}")
                        current = str(resp.url.join(loc))
                        continue
                    resp.raise_for_status()
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                        raise FetchError(f"PDF exceeds size cap ({MAX_DOWNLOAD_BYTES} bytes): {url}")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            raise FetchError(f"PDF exceeds size cap ({MAX_DOWNLOAD_BYTES} bytes): {url}")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    if not body:
                        raise FetchError(f"empty PDF from {url}")
                    if not body.startswith(b"%PDF-"):
                        raise FetchError(f"response from {url} does not look like a PDF")
                    return body
            raise FetchError(f"too many redirects for {url}")
    except UrlNotAllowed as exc:
        raise FetchError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"download failed for {url}: {exc}") from exc
```

Before editing, confirm `_download_pdf`'s only caller is `_try_download_pdf` (grep) so wrapping `httpx.HTTPError` into `FetchError` does not change a direct caller's expectations; if another caller catches raw httpx errors, wrap there instead.

- [ ] **Step 4: Run** `python -m pytest tests/test_security_regressions.py -q` → all PASS. **Full gate** — confirm no existing `fetch`/`discover` test relied on redirect auto-following to a private host or a non-PDF body (they use real public arxiv/crossref).
- [ ] **Step 5: Commit** `research_companion/net.py research_companion/fetch.py tests/test_security_regressions.py` · `fix(security): global-only URL egress guard + real streaming size cap + traversal/loopback regressions`.

### Task 7: Adversarial security + correctness review (subagent passes)

**Files:** findings-driven; fixes land where they belong, each with a regression test.

- [ ] **Step 1:** Dispatch a **security review** subagent over `research_companion/lab_api.py` (upload filename handling, `/pdf` + `/text` serving via `paper_id`→dirname, `/api/ingest` `paths` validation, workspace/view names → paths, **Host/Origin/CORS/CSRF posture and DNS-rebinding resistance for a loopback web server**, stored/reflected XSS from filenames + paper metadata + extracted text rendered in the Lab), `research_companion/mcp_server.py` + `mcp_tools.py` (input validation, `paper_id` path escape), and `parsers/_docling_worker.py` (subprocess args passed as a list, no shell). Bar: concrete exploitable findings only, with repro + severity + exact fix site.
- [ ] **Step 2:** Dispatch a **correctness review** subagent over `research_companion/statcheck/`, `interop/`, `overlap.py`, `mcp_tools.py`, `report.py` wiring — same confirmed-findings-only bar.
- [ ] **Step 2b:** Dispatch an **agent-runtime review** subagent over the CURRENT `research_companion/agents/` (`orchestrator.py`, `bus.py`, `events.py`, and the concrete agents). These concerns were raised against the historical agent-runtime plan — **verify each against the current code and fix only if real** (do not assume; the runtime has evolved far past that plan):
  - **Blocking sync in async lanes:** agents call sync `validate_bibliography`/`search`/`build_graph` inside `asyncio.gather`; if they do blocking I/O they serialize the "concurrent" lanes. If confirmed, wrap with `asyncio.to_thread(...)` and add a test that two injected blocking callables overlap (not `asyncio.sleep` theatre).
  - **Duplicate agent names / empty names** silently collapsing in the orchestrator's name→agent dict → raise `ValueError` on duplicate/empty; test both.
  - **Untrusted `result.agent`:** orchestrator keys results by the returned `result.agent`; a mismatched value can `KeyError`/mis-own results. Reject or key by the scheduled agent's name; test a lying agent.
  - **`AgentResult.data` JSON-serializability** is documented but unenforced → validate (`json.dumps`) before accepting a success, demote to error otherwise; test graph/set/callable/instance.
  - **Event contract:** `Bus` claims "any object publishable" but `EventLog.event_to_dict` assumes the known dataclasses → type the union / reject unknowns with `TypeError`.
  - **Audit-log CLI wiring:** `_cmd_review` builds `Bus()` with no `EventLog`, so there is no persistent audit trail from the CLI. Either add `--event-log PATH` (mkdir parents; note logs may hold paper metadata) or drop any "audit trail" claim from the docs.
  - **Bus retention** (unbounded `history`/queues) and **per-agent timeout/cancellation** (a stuck lookup hangs the whole review; use `asyncio.wait_for`, let `CancelledError` propagate) — assess; fix if they affect the shipped CLI, otherwise note as future.
  - **Mutable module-global `REVIEW_CONTEXT_OVERRIDES`** test seam → prefer an injected parameter if it risks cross-test leakage.
  (The two honesty overclaims from that review — CitationAgent "fabricated" and PriorArtAgent "maps onto the graph" — were already verified real and fixed in commit `a562dc9`.)
- [ ] **Step 3:** Per CONFIRMED finding: failing regression test → minimal fix → targeted test → full gate; one commit each. If a fix would change behavior the EMNLP paper describes, STOP and consult the user.
- [ ] **Step 4:** If a review returns zero confirmed findings, record that in the PR body — invent no work.

### Task 8: Content scrub + README polish + pyproject URLs

**Files:** Modify `docs/superpowers/plans/2026-06-29-agent-runtime-core.md`, `docs/superpowers/specs/2026-07-11-port-v0517-improvements-design.md`, `README.md`, `pyproject.toml`; Test `tests/test_packaging.py` (append).

- [ ] **Step 1: Add three meta-tests** to `tests/test_packaging.py` (implemented there — this Markdown plan deliberately does not embed the literal path patterns, so the scan doesn't flag its own plan):
  - `test_no_personal_dev_paths_in_tracked_docs` — a **fixed-string** (`git grep -F`) scan of tracked `*.md`/`*.txt`/`*.rst`/`*.cff` for personal user-directory path prefixes (a Windows user dir with either slash, plus POSIX `/home/<user>` and `/Users/<user>`); asserts none remain.
  - `test_pyproject_has_homepage_and_changelog_urls` — asserts `[project.urls]` has `Homepage`, `Documentation`, `Changelog`.
  - `test_readme_clone_cd_and_import_are_valid` — asserts no `cd research-companion` casing bug and no invalid hyphenated `import research-companion` example.
- [ ] **Step 2: Run** the three tests → they FAIL initially.
- [ ] **Step 3: Implement:**
  - Both `docs/superpowers/` files: replace the personal absolute dev-box paths with generic references (`the repo root`, `a parallel local clone`).
  - `README.md`: both `cd research-companion` → `cd Research-Companion`; fix the programmatic-API example — replace `import research-companion` / `research-companion.add_paper(...)` with `from research_companion import add_paper, build_graph, chat, view` and bare function names; add badges (CI, `License: MIT`, `python 3.10–3.13`); replace the Contributing body with a pointer to `CONTRIBUTING.md` + the three gates (JS via glob); add "This repository is the canonical home of Research Companion."; add a note that the PyPI release (0.5.14) trails the source tree (0.7.1) while publishing is held.
  - `pyproject.toml` `[project.urls]`: add `Homepage`, `Documentation` (→ `blob/main/docs/DOCUMENTATION.md`), `Changelog` (→ `blob/main/docs/RELEASE_0.7.md`).
- [ ] **Step 4:** 3 tests pass; full gate.
- [ ] **Step 5: Commit** · `docs: scrub dev paths, fix README import/cd + badges/contributing, pyproject URLs`.

### Task 9: Launch PR + platform guardrails (NO push to main)

**Files:** none (git/GitHub operations only). **`gh` must have admin on the repo; if not, stop after Step 2 and hand the maintainer the Step-4 commands.**

- [ ] **Step 0 (pre-launch gate — maintainer confirms before Step 2):**

```
[ ] New OpenAI credential generated; OLD one revoked at platform
[ ] New Hugging Face credential generated; OLD one revoked at platform
[ ] Any credential ever pasted into chat revoked
[ ] Local .env updated with the new values
[ ] `git log --all -- .env` still empty (never committed) — re-confirmed
```

- [ ] **Step 1: Full gate one final time** — all discovered py + js tests pass, ruff clean, no previously-tracked test file removed; record baseline→final counts in the PR (do not assert an exact number).
- [ ] **Step 2: Push + PR:** `git push -u origin feat/oss-launch`; `gh pr create --base main --title "OSS launch readiness: guardrails, CI hardening, security audit" --body <summary of phases, audit outcomes, holds (publish held; PyPI 0.5.14 vs source 0.7.1; mirror untouched)>`.
- [ ] **Step 3: Wait for the PR checks** — `test` matrix, `lint`, `audit`, `package`, `dependency-review`, `ci-ok`, `codeql-ok` must all pass (fix forward if not). Confirm no CI job needs secrets (only `publish.yml` does) so fork PRs run cleanly.
- [ ] **Step 4: Apply platform settings** (repo `Laraib-Hasan-Future/Research-Companion` ONLY; abort-on-error, verify each response):

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

# branch protection: PR required, ci-ok + codeql-ok required (checks array) & up-to-date,
# admins enforced, 0 approvals (solo), no force-push/deletion
gh api -X PUT repos/Laraib-Hasan-Future/Research-Companion/branches/main/protection --input - <<'JSON'
{"required_status_checks":{"strict":true,"checks":[{"context":"ci-ok"},{"context":"codeql-ok"}]},
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
         checks:.required_status_checks.checks, force:.allow_force_pushes.enabled,
         del:.allow_deletions.enabled, approvals:.required_pull_request_reviews.required_approving_review_count}'
# Expect: admins=true, strict=true, checks=[ci-ok,codeql-ok], force=false, del=false, approvals=0
```

- [ ] **Step 6: Merge the PR through the guardrails** (`gh pr merge --merge --delete-branch`), confirm `main` green.
- [ ] **Step 7: CODEOWNERS verification (POST-MERGE only — GitHub reads CODEOWNERS from the base branch, so it cannot be exercised by the launch PR that introduces it):**
  1. Confirm `@Hasan-Laraib` has write access (`gh api repos/…/collaborators/Hasan-Laraib/permission`).
  2. Create a throwaway branch off `main`, change a harmless file, open a PR to `main`.
  3. Confirm GitHub auto-requests review from `@Hasan-Laraib` and that merge is blocked until `ci-ok`+`codeql-ok` are green.
  4. Close the test PR, delete the branch.

**USER ACTIONS (flagged, not executable by the plan):**
- The Step-0 credential rotation.
- **Retire the existing long-lived PyPI token now (it exists in repo secrets, created 2026-07-06).** As soon as the Trusted-Publishing `publish.yml` is merged to `main` (Task 5): confirm no workflow references `PYPI_API_TOKEN`, then **delete the GitHub secret and revoke the token on PyPI** — do not wait for a future release, since publishing is held and the credential otherwise sits unused.
- Before the next real release: configure the PyPI trusted publisher (owner `Laraib-Hasan-Future`, repo `Research-Companion`, workflow `publish.yml`, environment `pypi`), create the protected `pypi` environment, **rehearse on TestPyPI**, then do the production release only after the rehearsal succeeds.

## Notes on review items intentionally scoped down
- **Traversal test isolation:** `tests/conftest.py` has an autouse `isolated_papergraph_dir` fixture, so `store.papers_dir()` is already a per-test tmp dir — the test asserts via `paper_dir()` under that isolated root.
- **Full-SHA action pinning / YAML-parsing meta-tests:** declined. SHA-pinning is high maintenance for a solo maintainer; Dependabot's `github-actions` updates cover action CVEs and will bump these `@vN` majors (updating the pinned-major meta-tests in the same PR). Substring meta-tests stay dep-free (no PyYAML dev-dep).
- **SSRF depth:** the guard blocks scheme/creds/non-global-IPs/redirects/size and is documented as best-effort (residual DNS-rebinding TOCTOU acknowledged); a full egress-firewall/connection-pinning model is out of scope for a local single-user CLI. The optional "scholarly-host allowlist" is not adopted (would change legitimate add-paper behavior).
