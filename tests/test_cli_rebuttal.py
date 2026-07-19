"""End-to-end tests for `research-companion rebuttal` — LLM injected, no network."""
from __future__ import annotations

import json

import pytest

from research_companion import cli, store
from research_companion.prompts import extraction_prompt_sha256

REVIEWS = """Reviewer 1

1. Missing baseline comparison against BaselineX in the evaluation.
"""


def _seed():
    pid = "local:rebut0000001"
    store.PaperMetadata(paper_id=pid, title="P", authors=[]).save()
    store.save_extraction(pid, {"related_work": []}, prompt_sha=extraction_prompt_sha256())
    store.save_text(pid, "Intro.\n\nIn Section 4.2 we compare against BaselineX on three datasets.\n")
    return pid


def _llm(prompt):
    if '"kind"' in prompt:
        return json.dumps({"kind": "misunderstanding"})
    return json.dumps({"reply": 'See "we compare against BaselineX on three datasets".',
                       "planned_revision": "Highlight baseline comparison."})


def test_rebuttal_cli_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    pid = _seed()
    reviews = tmp_path / "reviews.txt"
    reviews.write_text(REVIEWS, encoding="utf-8")
    monkeypatch.setattr(cli, "REBUTTAL_CONTEXT_OVERRIDES", {"_llm": _llm})
    rc = cli.main(["rebuttal", pid, "--reviews", str(reviews)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "R1.1" in out and "misunderstanding" in out
    assert "verified" in out.lower()
    assert "Highlight baseline comparison." in out


def test_rebuttal_cli_emit_and_resume_segments(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    pid = _seed()
    reviews = tmp_path / "reviews.txt"
    reviews.write_text(REVIEWS, encoding="utf-8")
    seg = tmp_path / "segments.json"
    rc = cli.main(["rebuttal", pid, "--reviews", str(reviews), "--emit-segments", str(seg)])
    assert rc == 0 and seg.exists()
    assert json.loads(seg.read_text(encoding="utf-8"))[0]["concern_id"] == "R1.1"
    capsys.readouterr()
    monkeypatch.setattr(cli, "REBUTTAL_CONTEXT_OVERRIDES", {"_llm": _llm})
    rc2 = cli.main(["rebuttal", pid, "--segments", str(seg), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc2 == 0
    assert payload["drafts"][0]["concern_id"] == "R1.1"


def test_rebuttal_cli_missing_reviews_errors(capsys):
    pid = _seed()
    rc = cli.main(["rebuttal", pid])
    assert rc == 1
    assert "reviews" in capsys.readouterr().err.lower()


def test_rebuttal_cli_rejects_malformed_segments(tmp_path, capsys):
    pid = _seed()
    bad = tmp_path / "bad.json"
    bad.write_text('[{"wrong_key": 1}]', encoding="utf-8")
    rc = cli.main(["rebuttal", pid, "--segments", str(bad)])
    assert rc == 1
    assert "invalid segments" in capsys.readouterr().err.lower()


def test_rebuttal_cli_missing_segments_file(capsys):
    pid = _seed()
    rc = cli.main(["rebuttal", pid, "--segments", "nope.json"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# --provider / --model flags (parity with build/align/compare/lab ingest)
# ---------------------------------------------------------------------------

def test_rebuttal_parser_accepts_provider_and_model():
    parser = cli._build_parser()
    args = parser.parse_args(["rebuttal", "some-id", "--provider", "openai", "--model", "gpt-x"])
    assert args.provider == "openai"
    assert args.model == "gpt-x"


def test_resolve_llm_for_rebuttal_explicit_provider_overrides_env(monkeypatch):
    """_resolve_llm_for_rebuttal must honor an explicit --provider over the
    env var, resolving openai even when RESEARCH_COMPANION_PROVIDER is
    unset/anthropic."""
    from research_companion import extract as extract_mod

    calls = []
    monkeypatch.setattr(
        extract_mod, "_call_openai",
        lambda prompt, model=None, **kw: (calls.append(("openai", model)) or ("ok", {})))
    monkeypatch.setattr(
        extract_mod, "_call_anthropic",
        lambda prompt, model=None: (calls.append(("anthropic", model)) or ("ok", {})))
    monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)

    parser = cli._build_parser()
    args = parser.parse_args(["rebuttal", "some-id", "--provider", "openai"])
    llm = cli._resolve_llm_for_rebuttal(args, {})
    assert llm is not None
    assert llm("hi") == "ok"
    assert calls and calls[0][0] == "openai"


def test_resolve_llm_for_rebuttal_returns_none_without_flags():
    parser = cli._build_parser()
    args = parser.parse_args(["rebuttal", "some-id"])
    assert cli._resolve_llm_for_rebuttal(args, {}) is None


def test_resolve_llm_for_rebuttal_does_not_override_context_seam():
    """If REBUTTAL_CONTEXT_OVERRIDES already injected an `_llm` (the existing
    test seam), the explicit-flag path must never clobber it."""
    parser = cli._build_parser()
    args = parser.parse_args(["rebuttal", "some-id", "--provider", "openai"])
    sentinel = object()
    assert cli._resolve_llm_for_rebuttal(args, {"_llm": sentinel}) is None


def test_rebuttal_cli_end_to_end_honors_explicit_provider(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    """End-to-end: passing --provider openai to `rebuttal` must actually
    route the RebuttalAgent's LLM calls through the openai client, even
    though RESEARCH_COMPANION_PROVIDER is unset (defaults to anthropic)."""
    from research_companion import extract as extract_mod

    pid = _seed()
    reviews = tmp_path / "reviews.txt"
    reviews.write_text(REVIEWS, encoding="utf-8")
    monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)

    calls = []

    def fake_openai(prompt, *, model=None, **kw):
        calls.append(("openai", model))
        if '"kind"' in prompt:
            return json.dumps({"kind": "misunderstanding"}), {}
        return json.dumps({
            "reply": 'See "we compare against BaselineX on three datasets".',
            "planned_revision": "Highlight baseline comparison.",
        }), {}

    def fake_anthropic(prompt, *, model=None):
        calls.append(("anthropic", model))
        return "unexpected", {}

    monkeypatch.setattr(extract_mod, "_call_openai", fake_openai)
    monkeypatch.setattr(extract_mod, "_call_anthropic", fake_anthropic)

    rc = cli.main(["rebuttal", pid, "--reviews", str(reviews), "--provider", "openai"])
    assert rc == 0
    assert calls, "expected the rebuttal agent to invoke an LLM"
    assert all(c[0] == "openai" for c in calls)
