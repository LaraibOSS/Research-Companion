"""Claim-audit benchmark harness, with a fake model.

Cases go through the real ``audit_claim``, so the fake model sees the real
prompt and the harness sees the real fail-closed outcomes. What is pinned is
the scoring: an inconclusive audit is neither a detection nor a pass.
"""
from __future__ import annotations

import json

import pytest

from research_companion.eval import claim_audit_bench as cb
from research_companion.eval._common import BenchFormatError

PASSAGE = ("We evaluate on three multi-hop datasets and observe that graph retrieval "
           "reduces answer error by 12 points relative to dense retrieval.")


def fake_model(prompt: str) -> str:
    """Judge by markers in the claim, which the real prompt carries."""
    if "MODEL-BREAKS" in prompt:
        raise RuntimeError("provider error")
    if "UNCLEAR" in prompt:
        return json.dumps({"verdict": "unclear", "reason": "cannot tell"})
    if "40%" in prompt:
        return json.dumps({"verdict": "not_supported", "reason": "passage says 12 points"})
    return json.dumps({"verdict": "supported", "reason": "stated"})


def _write(tmp_path, rows):
    p = tmp_path / "claims.jsonl"
    p.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n",
                 encoding="utf-8")
    return p


CASES = [
    {"claim": "Graph retrieval reduces error by 12 points.", "passage": PASSAGE,
     "label": "supported"},
    {"claim": "Graph retrieval reduces error by 40%.", "passage": PASSAGE,
     "label": "supported", "type": "paraphrase"},          # the fake wrongly accuses
    {"claim": "Graph retrieval cuts hallucination by 40%.", "passage": PASSAGE,
     "label": "not_supported", "type": "contradict"},
    {"claim": "Graph retrieval is faster.", "passage": PASSAGE,
     "label": "not_supported", "type": "noinfo"},           # the fake misses
    {"claim": "UNCLEAR claim.", "passage": PASSAGE, "label": "not_supported",
     "type": "noinfo"},
    {"claim": "MODEL-BREAKS here.", "passage": PASSAGE, "label": "supported"},
    {"claim": "Too short a source.", "passage": "short passage", "label": "supported"},
    "{bad json",
    {"claim": "x", "passage": PASSAGE, "label": "true"},
]


def test_scoring_excludes_inconclusive_audits(tmp_path):
    result = cb.evaluate(_write(tmp_path, CASES), fake_model)
    m = result["metrics"]
    assert [r["outcome"] for r in result["rows"]] == [
        "accepted", "falsely_accused", "detected", "missed",
        "inconclusive", "inconclusive", "inconclusive"]
    assert m["supported"] == {"total": 4, "conclusive": 2, "inconclusive": 2,
                              "judged_not_supported": 1, "false_accusation_rate": 0.5}
    assert m["not_supported"] == {"total": 3, "conclusive": 2, "inconclusive": 1,
                                  "judged_not_supported": 1, "detection_rate": 0.5}
    assert m["inconclusive"] == {"total": 3, "supported": 2, "not_supported": 1}
    assert m["confusion_matrix"]["supported"]["unverifiable"] == 2
    per = {(g["type"], g["label"]): g for g in m["per_type"]}
    assert per[("noinfo", "not_supported")]["inconclusive"] == 1
    assert per[("noinfo", "not_supported")]["rate"] == 0.0
    assert per[("contradict", "not_supported")]["rate"] == 1.0


def test_malformed_rows_are_reported(tmp_path):
    result = cb.evaluate(_write(tmp_path, CASES), fake_model)
    errors = {s["line"]: s["error"] for s in result["skipped"]}
    assert set(errors) == {8, 9}
    assert "not valid JSON" in errors[8]
    assert '"label"' in errors[9]


def test_no_model_means_nothing_was_checked(tmp_path):
    result = cb.evaluate(_write(tmp_path, CASES[:3]), None)
    assert all(r["verdict"] == "not_checked" for r in result["rows"])
    assert result["metrics"]["supported"]["false_accusation_rate"] is None
    assert result["metrics"]["not_supported"]["detection_rate"] is None


def test_a_file_with_no_usable_row_names_the_fields(tmp_path):
    with pytest.raises(BenchFormatError) as exc:
        cb.load_cases(_write(tmp_path, [{"entry": "x", "label": "real"}]))
    assert '"claim"' in str(exc.value) and '"passage"' in str(exc.value)


def test_cli_human_and_json(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cb, "_resolve_llm", lambda provider, model: fake_model)
    path = _write(tmp_path, CASES)

    assert cb.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "Detection rate:        50.0% (1 of 2 checked)" in out
    assert "False-accusation rate: 50.0% (1 of 2 checked)" in out
    assert "Inconclusive (audit could not conclude): 3" in out
    assert "Rows skipped as malformed: 2" in out

    assert cb.main([str(path), "--json", "--limit", "2"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["metrics"]["cases_run"] == 2 and data["usable_rows"] == 7


def test_cli_rejects_a_mismatched_file(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cb, "_resolve_llm", lambda provider, model: fake_model)
    assert cb.main([str(_write(tmp_path, [{"nope": 1}]))]) == 2
    assert '"claim"' in capsys.readouterr().err
