"""Claim-level citation audit.

The property that matters most: **the tool must not accuse a correct citation.**
Every path that fails to establish something resolves to an inconclusive
outcome, never to "not supported". A noisy auditor is worse than none, because
users learn to ignore all of its warnings.
"""
from __future__ import annotations

import json

import pytest

from research_companion.claim_audit import (
    INCONCLUSIVE,
    AuditOutcome,
    audit_claim,
    summarize,
)
from research_companion.locator import anchor_quote, anchorless

TEXT = (
    "Background section text. "
    "Graph retrieval reduces error on multi-hop questions across three datasets. "
    "Further discussion follows in the next section."
)
QUOTE = "Graph retrieval reduces error on multi-hop questions"
CLAIM = "Graph retrieval reduces hallucination by 40%."


def _loc():
    return anchor_quote("p1", QUOTE, TEXT)


def _load(_paper_id):
    return TEXT


def _llm(verdict, reason="because"):
    def fn(_prompt):
        return json.dumps({"verdict": verdict, "reason": reason})
    return fn


# ---------------------------------------------------------------------------
# The two conclusive outcomes
# ---------------------------------------------------------------------------

def test_supported_when_the_passage_states_the_claim():
    r = audit_claim(CLAIM, _loc(), load_text=_load, llm=_llm("supported"))
    assert r.outcome is AuditOutcome.SUPPORTED
    assert r.is_adverse is False
    assert r.signal.is_clean is True


def test_not_supported_is_the_only_adverse_outcome():
    r = audit_claim(CLAIM, _loc(), load_text=_load, llm=_llm("not_supported"))
    assert r.outcome is AuditOutcome.NOT_SUPPORTED
    assert r.is_adverse is True
    # even an adverse verdict is a model judgement, never a deterministic fact
    assert "ADVISORY" in r.signal.label()
    assert r.signal.is_clean is False


# ---------------------------------------------------------------------------
# Everything that could go wrong must NOT become an accusation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("llm,label", [
    (_llm("unclear"), "model said unclear"),
    (_llm(""), "empty verdict"),
    (_llm("nonsense_verdict"), "unrecognised verdict"),
    (lambda p: "not json at all", "unparseable output"),
    (lambda p: (_ for _ in ()).throw(RuntimeError("model down")), "model error"),
])
def test_uncertainty_never_becomes_an_accusation(llm, label):
    r = audit_claim(CLAIM, _loc(), load_text=_load, llm=llm)
    assert r.outcome is AuditOutcome.UNVERIFIABLE, label
    assert r.is_adverse is False, label
    assert r.is_inconclusive is True, label


def test_a_citation_with_no_anchor_is_uncheckable_not_wrong():
    r = audit_claim(CLAIM, anchorless("p1"), load_text=_load, llm=_llm("supported"))
    assert r.outcome is AuditOutcome.ANCHORLESS
    assert r.is_adverse is False
    assert "not a finding about the citation" in r.reason.lower()


def test_missing_locator_is_handled():
    r = audit_claim(CLAIM, None, load_text=_load, llm=_llm("supported"))
    assert r.outcome is AuditOutcome.ANCHORLESS


def test_a_source_that_cannot_be_loaded_is_unverifiable():
    def boom(_paper_id):
        raise OSError("disk gone")

    r = audit_claim(CLAIM, _loc(), load_text=boom, llm=_llm("supported"))
    assert r.outcome is AuditOutcome.UNVERIFIABLE
    assert r.is_adverse is False


def test_a_passage_too_short_to_settle_anything_is_declined():
    r = audit_claim(CLAIM, _loc(), load_text=lambda p: "tiny", llm=_llm("not_supported"))
    assert r.outcome is AuditOutcome.UNVERIFIABLE
    assert r.is_adverse is False


def test_audit_switched_off_reports_not_checked_not_clean():
    r = audit_claim(CLAIM, _loc(), load_text=_load, llm=None)
    assert r.outcome is AuditOutcome.NOT_CHECKED
    assert r.signal.is_clean is False
    assert r.is_adverse is False


def test_empty_claim_is_not_checked():
    r = audit_claim("   ", _loc(), load_text=_load, llm=_llm("supported"))
    assert r.outcome is AuditOutcome.NOT_CHECKED


def test_every_inconclusive_outcome_is_marked_inconclusive():
    for outcome in INCONCLUSIVE:
        assert outcome is not AuditOutcome.SUPPORTED
        assert outcome is not AuditOutcome.NOT_SUPPORTED


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def test_summary_does_not_inflate_how_much_was_actually_checked():
    results = [
        audit_claim(CLAIM, _loc(), load_text=_load, llm=_llm("supported")),
        audit_claim(CLAIM, _loc(), load_text=_load, llm=_llm("not_supported")),
        audit_claim(CLAIM, _loc(), load_text=_load, llm=_llm("unclear")),
        audit_claim(CLAIM, anchorless("p1"), load_text=_load, llm=_llm("supported")),
    ]
    s = summarize(results)
    assert s["total"] == 4
    assert s["checked"] == 2          # only the conclusive ones count
    assert s["inconclusive"] == 2
    assert s["adverse"] == 1


def test_result_dict_exposes_the_distinction_the_ui_needs():
    d = audit_claim(CLAIM, _loc(), load_text=_load, llm=_llm("unclear")).to_dict()
    assert d["outcome"] == "unverifiable"
    assert d["is_adverse"] is False
    assert d["is_inconclusive"] is True
    assert d["signal"]["is_clean"] is False


def test_the_prompt_tells_the_model_to_prefer_unclear():
    """The false-positive guarantee is only as good as the instruction."""
    from research_companion.prompts import CLAIM_AUDIT_PROMPT

    assert "unclear" in CLAIM_AUDIT_PROMPT
    assert "not confident" in CLAIM_AUDIT_PROMPT
    assert "accuses the author" in CLAIM_AUDIT_PROMPT
    # it must forbid using outside knowledge, or it is not auditing the passage
    assert "ONLY the passage" in CLAIM_AUDIT_PROMPT


def test_claim_audit_is_opt_in():
    from research_companion.settings import DEFAULTS

    assert DEFAULTS["claim_audit"] is False


# ---------------------------------------------------------------------------
# Runners over whole artifacts
# ---------------------------------------------------------------------------

def test_audit_report_annotates_each_citation_without_mutating_the_source():
    from research_companion.claim_audit import audit_report

    report = {"sections": [{
        "question": "Does graph retrieval help?",
        "answer": "Graph retrieval reduces error by 40%.",
        "citations": [
            {"paper_id": "p1", "section_id": "s1", "char_start": 0, "char_end": len(TEXT)},
            {"paper_id": "p2"},   # no offsets -> anchorless, not an accusation
        ],
    }]}
    original = json.loads(json.dumps(report))

    out = audit_report(report, load_text=_load, llm=_llm("not_supported", "no 40% figure"))
    cits = out["sections"][0]["citations"]
    assert cits[0]["audit"]["outcome"] == "not_supported"
    assert cits[1]["audit"]["outcome"] == "anchorless"
    assert cits[1]["audit"]["is_adverse"] is False
    # summary counts only the conclusive one
    assert out["summary"]["checked"] == 1
    assert out["summary"]["adverse"] == 1
    # the input artifact is untouched
    assert report == original


def test_audit_alignment_uses_the_stored_locator():
    from research_companion.claim_audit import audit_alignment
    from research_companion.locator import anchor_quote

    loc = anchor_quote("p1", QUOTE, TEXT)
    alignment = {"sections": [{
        "section_id": "s1",
        "rationale": "This paper supports the retrieval claim.",
        "evidence": [{"quote": QUOTE, "verified": True, "locator": loc.to_dict()}],
    }]}

    out = audit_alignment(alignment, load_text=_load, llm=_llm("supported"))
    ev = out["sections"][0]["evidence"][0]
    assert ev["audit"]["outcome"] == "supported"
    assert ev["verified"] is True          # existing fields preserved
    assert out["summary"]["checked"] == 1


def test_one_broken_source_does_not_abort_the_batch():
    from research_companion.claim_audit import audit_report

    calls = {"n": 0}

    def flaky_load(paper_id):
        calls["n"] += 1
        if paper_id == "bad":
            raise OSError("unreadable")
        return TEXT

    report = {"sections": [{
        "answer": "A claim.",
        "citations": [
            {"paper_id": "bad", "char_start": 0, "char_end": len(TEXT)},
            {"paper_id": "p1", "char_start": 0, "char_end": len(TEXT)},
        ],
    }]}
    out = audit_report(report, load_text=flaky_load, llm=_llm("supported"))
    outcomes = [c["audit"]["outcome"] for c in out["sections"][0]["citations"]]
    assert outcomes == ["unverifiable", "supported"]
    assert out["summary"]["total"] == 2
