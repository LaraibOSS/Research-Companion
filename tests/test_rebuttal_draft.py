"""Tests for the rebuttal drafting pipeline (LLM injected)."""
from __future__ import annotations

import json

import pytest

from papergraph.rebuttal.draft import draft_rebuttal
from papergraph.rebuttal.models import Concern

FULLTEXT = "Intro.\n\nIn Section 4.2 we compare against BaselineX on three datasets.\n"


def _llm(prompt: str) -> str:
    if '"kind"' in prompt:
        return json.dumps({"kind": "misunderstanding"})
    return json.dumps({
        "reply": 'We respectfully note "we compare against BaselineX on three datasets" in §4.2.',
        "planned_revision": "Make the baseline comparison more prominent.",
    })


def _bad_reply_llm(prompt: str) -> str:
    if '"kind"' in prompt:
        return json.dumps({"kind": "factual_error"})
    return json.dumps({"reply": 'The paper says "a totally fabricated sentence not in the paper".',
                       "planned_revision": ""})


def test_draft_grounds_verifies_and_builds_changelog():
    concerns = [Concern(concern_id="R1.1", reviewer="R1",
                        text="Missing baseline comparison against BaselineX")]
    report = draft_rebuttal(concerns, FULLTEXT, _llm)
    d = report.drafts[0]
    assert d.concern_id == "R1.1" and d.verified and d.unverified_spans == []
    assert d.cited_passages and d.cited_passages[0].location == "para 2"
    assert report.changelog == ["Make the baseline comparison more prominent."]
    assert report.groups == [["R1.1"]]
    assert concerns[0].kind == "misunderstanding"


def test_draft_flags_unverified_spans():
    concerns = [Concern(concern_id="R1.1", reviewer="R1", text="Some concern text here")]
    report = draft_rebuttal(concerns, FULLTEXT, _bad_reply_llm)
    d = report.drafts[0]
    assert not d.verified
    assert d.unverified_spans == ["a totally fabricated sentence not in the paper"]


def test_draft_bad_json_raises_runtimeerror():
    concerns = [Concern(concern_id="R1.1", reviewer="R1", text="Some concern text here")]
    with pytest.raises(RuntimeError, match="rebuttal"):
        draft_rebuttal(concerns, FULLTEXT, lambda p: "NOT JSON")
