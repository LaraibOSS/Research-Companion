"""End-to-end tests for `papergraph rebuttal` — LLM injected, no network."""
from __future__ import annotations

import json

import pytest

from papergraph import cli, store
from papergraph.prompts import extraction_prompt_sha256

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
