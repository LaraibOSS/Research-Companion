# Contributing to Research Companion

Thanks for your interest in improving Research Companion! Anyone is welcome to
open an issue or a pull request. This guide covers how to set up, the checks your
change must pass, and the principles that keep the project coherent.

## Development setup

```bash
git clone https://github.com/LaraibOSS/Research-Companion.git
cd Research-Companion
pip install -e ".[dev]"
```

To work on the browser **Research Lab**:

```bash
pip install -e ".[server]"
research-companion lab serve      # opens http://127.0.0.1:8765
```

## The three gates (run before every PR)

Your change must pass all three locally, and CI enforces them on every PR:

```bash
python -m pytest -q
node --test tests/js/*.test.mjs
ruff check research_companion tests examples
```

CI runs the Python suite on **Python 3.10–3.13** across **Ubuntu and Windows**,
so please keep code portable (no OS-specific assumptions, use `pathlib`).

## Test-driven development

We practice TDD: write a failing test first, then the minimal code to make it
pass. Deterministic modules (extraction, statistics, overlap, interop, retrieval
fallback) must have fully reproducible tests with no network. If your change adds
behavior, it needs a test; if it fixes a bug, add the regression test that fails
before your fix.

## Design principles

Research Companion's identity is **verifiability**. Please keep changes aligned:

- **Deterministic-first.** Prefer pure, testable computation over LLM calls.
  Anything using an LLM must degrade gracefully when no key is configured.
- **Never claim more than you compute.** A finding states exactly what was
  checked (e.g. a citation is "unverified", never "fabricated"; a statistic is a
  "reporting inconsistency", never "misconduct"). Skip ambiguous cases rather
  than guess.
- **Char-span provenance.** Keep absolute character offsets flowing from
  chunking → Q&A → reader so evidence is verifiable in the source.
- **Local-first.** No new servers or databases; persist as per-paper JSON under
  `~/.research-companion/`. Keep heavy/optional imports lazy.
- **Fail honestly.** Surface real reasons; never a silent empty success.

## Pull request checklist

- [ ] Tests added or updated (TDD).
- [ ] All three gates pass locally.
- [ ] Docs updated if the change is user-facing.
- [ ] No secrets, credentials, or private data in the diff.

## Reporting security issues

Please do **not** open a public issue for a vulnerability — see
[SECURITY.md](SECURITY.md) for private disclosure via GitHub Security Advisories.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
