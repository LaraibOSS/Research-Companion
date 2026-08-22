"""The epistemic signal carrier and its one load-bearing invariant.

The rule under test: a check that did not complete is never rendered as clean.
"""
from __future__ import annotations

import pytest

from research_companion import signals as S

# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", sorted(S.INCOMPLETE_STATUSES, key=lambda s: s.value))
@pytest.mark.parametrize("finding", [S.Finding.SUPPORTED, S.Finding.CONTRADICTED])
def test_incomplete_check_cannot_carry_a_conclusion(status, finding):
    """An outage establishes nothing — neither existence nor fabrication."""
    with pytest.raises(S.SignalError, match="did not complete"):
        S.Signal(
            name="citation_exists",
            epistemic_class=S.EpistemicClass.DETERMINISTIC_FACT,
            check_status=status,
            finding=finding,
            detail="x",
        )


def test_unresolved_must_explain_itself():
    """'We don't know' is only useful if the user learns why."""
    with pytest.raises(S.SignalError, match="must say why"):
        S.Signal(
            name="citation_exists",
            epistemic_class=S.EpistemicClass.PROCESS_ATTESTATION,
            check_status=S.CheckStatus.DEGRADED,
            finding=S.Finding.UNRESOLVED,
        )


def test_signal_requires_a_name():
    with pytest.raises(S.SignalError):
        S.Signal(
            name="",
            epistemic_class=S.EpistemicClass.DETERMINISTIC_FACT,
            check_status=S.CheckStatus.CHECKED,
            finding=S.Finding.SUPPORTED,
        )


# ---------------------------------------------------------------------------
# is_clean — the single gate every green tick must go through
# ---------------------------------------------------------------------------

def test_only_a_completed_positive_check_is_clean():
    assert S.resolved("c", source="crossref").is_clean is True
    assert S.not_found("c", source="crossref").is_clean is False
    assert S.could_not_check("c", detail="crossref 429").is_clean is False
    assert S.not_checked("c", detail="connectors off").is_clean is False


def test_an_empty_signal_list_is_not_clean():
    """Nothing checked means nothing established — never a pass."""
    assert S.all_clean([]) is False
    assert S.all_clean([S.resolved("a"), S.resolved("b")]) is True
    assert S.all_clean([S.resolved("a"), S.could_not_check("b", detail="down")]) is False


# ---------------------------------------------------------------------------
# Labels — what the user actually reads
# ---------------------------------------------------------------------------

def test_unresolved_never_reads_as_clean():
    for sig in (S.could_not_check("c", detail="down"),
                S.not_checked("c", detail="off")):
        label = sig.label()
        assert "UNRESOLVED" in label
        assert "VERIFIED" not in label


def test_outage_and_never_ran_are_distinguishable():
    """Retryable vs. switched-off need different user actions."""
    assert S.could_not_check("c", detail="down").label() == "COULD NOT VERIFY — UNRESOLVED"
    assert S.not_checked("c", detail="off").label() == "NOT CHECKED — UNRESOLVED"


def test_a_matched_heuristic_is_never_labelled_a_definitive_problem():
    matched = S.heuristic("tortured_phrase", matched=True, detail="2 patterns")
    assert "ADVISORY" in matched.label()
    assert matched.label() != "PROBLEM FOUND"
    # and a heuristic that did not match is still only advisory
    assert "ADVISORY" in S.heuristic("t", matched=False, detail="none").label()


def test_to_dict_exposes_is_clean_and_label_for_ui_consumers():
    d = S.could_not_check("citation_exists", detail="crossref unreachable",
                          source="crossref").to_dict()
    assert d["is_clean"] is False
    assert d["finding"] == "unresolved"
    assert d["check_status"] == "degraded"
    assert d["epistemic_class"] == "process_attestation"
    assert "UNRESOLVED" in d["label"]


# ---------------------------------------------------------------------------
# The pilot: refcheck must stop reporting an outage as "no record found"
# ---------------------------------------------------------------------------

def _ref():
    from research_companion.refcheck.validate import Reference
    return Reference(title="Some Paper", authors=["A. Author"], year=2024,
                     doi=None, arxiv_id=None, url=None, raw="Some Paper (2024)")


def test_lookup_outcome_separates_answered_from_unreachable():
    import httpx

    from research_companion.refcheck.retrieval import lookup_with_outcome

    answered = lookup_with_outcome(_ref(), lookup=lambda r: None)
    assert answered.any_reachable is True    # a resolver said "no record"
    assert answered.record is None

    def unreachable(_ref_):
        raise httpx.ConnectError("network down")

    out = lookup_with_outcome(_ref(), lookup=unreachable)
    assert out.any_reachable is False        # nothing answered
    assert out.errors and "ConnectError" in out.errors[0]


def test_validate_does_not_claim_no_record_found_during_an_outage():
    """The bug this fixes: an unreachable resolver used to surface as
    'No matching record found in authoritative sources' — asserting as fact
    something the tool could not check."""
    import httpx

    from research_companion.refcheck.validate import validate_reference

    def unreachable(_ref_):
        raise httpx.ConnectError("network down")

    verdict = validate_reference(_ref(), unreachable)
    assert verdict.status == "unverified"
    joined = " ".join(verdict.reasons)
    assert "could not verify" in joined.lower()
    assert "could be reached" in joined.lower()
    assert "no matching record found" not in joined.lower()
    assert "not evidence" in joined.lower()   # states what it does NOT prove


def test_validate_still_reports_a_genuine_miss_as_not_found():
    from research_companion.refcheck.validate import validate_reference

    verdict = validate_reference(_ref(), lambda r: None)
    assert verdict.status == "unverified"
    assert "No matching record found" in " ".join(verdict.reasons)


# ---------------------------------------------------------------------------
# NOT_APPLICABLE — the third way a check can fail to conclude
#
# "we did not run it", "we ran it and it failed", and "running it would be
# meaningless" are three different facts. Collapsing the third into either of
# the others either invents an outstanding task or hides one.
# ---------------------------------------------------------------------------

def test_not_applicable_is_not_an_outstanding_task():
    """GRIM on an ML result: nothing is wrong and nothing needs reviewing."""
    sig = S.not_applicable(
        "statistics_internally_consistent",
        reason=S.Reason.STATISTIC_TYPE_UNSUPPORTED,
        detail="GRIM applies to means of bounded integer items.",
        source="statcheck",
    )
    assert sig.check_status is S.CheckStatus.NOT_APPLICABLE
    assert sig.needs_attention is False, "not-applicable must not demand action"
    assert sig.is_clean is False, "and must not read as a pass either"
    assert sig.is_adverse is False
    assert sig.label() == "NOT APPLICABLE"


def test_a_degraded_check_does_demand_attention():
    sig = S.could_not_check("claim_supported", detail="no anchor",
                                  reason=S.Reason.NO_ANCHOR)
    assert sig.check_status is S.CheckStatus.DEGRADED
    assert sig.needs_attention is True


def test_not_applicable_must_say_why():
    """Without a reason the status is unreadable — why does it not apply?"""
    with pytest.raises(S.SignalError, match="Reason"):
        S.Signal(
            name="x", epistemic_class=S.EpistemicClass.PROCESS_ATTESTATION,
            check_status=S.CheckStatus.NOT_APPLICABLE,
            finding=S.Finding.UNRESOLVED, detail="d",
        )


def test_not_applicable_cannot_carry_a_conclusion():
    with pytest.raises(S.SignalError):
        S.Signal(
            name="x", epistemic_class=S.EpistemicClass.PROCESS_ATTESTATION,
            check_status=S.CheckStatus.NOT_APPLICABLE,
            finding=S.Finding.SUPPORTED,
            reason=S.Reason.NOT_RELEVANT, detail="d",
        )


def test_a_completed_check_has_no_failure_reason():
    """"CHECKED + PARSE_FAILED" is two states at once."""
    with pytest.raises(S.SignalError, match="did not fail"):
        S.Signal(
            name="x", epistemic_class=S.EpistemicClass.DETERMINISTIC_FACT,
            check_status=S.CheckStatus.CHECKED,
            finding=S.Finding.SUPPORTED,
            reason=S.Reason.PARSE_FAILED,
        )


def test_reason_is_structured_so_failures_can_be_counted():
    """Free text cannot be grouped; this is why `reason` is not `detail`."""
    sigs = [
        S.could_not_check("a", detail="x", reason=S.Reason.SOURCE_UNAVAILABLE),
        S.could_not_check("b", detail="x", reason=S.Reason.SOURCE_UNAVAILABLE),
        S.could_not_check("c", detail="x", reason=S.Reason.PARSE_FAILED),
    ]
    from collections import Counter
    counts = Counter(s.reason for s in sigs)
    assert counts[S.Reason.SOURCE_UNAVAILABLE] == 2


# ---------------------------------------------------------------------------
# Provenance — what was checked, and what it was checked against
# ---------------------------------------------------------------------------

def test_evidence_is_not_limited_to_documents():
    """refcheck cites a catalogue record, novelty a query, compliance a rule.
    A single `locator` field could not carry any of those."""
    refs = [
        S.DocumentRef(paper_id="p1", section_id="s2", char_start=10, char_end=40),
        S.CatalogueRef(catalogue="crossref", identifier="10.1234/x"),
        S.VenueRuleRef(venue_slug="neurips", rule_id="page_limit",
                             rules_version="2026-08-01"),
        S.QueryRef(query="adaptive recurrent depth", sources=("openalex",)),
    ]
    kinds = {r.to_dict()["kind"] for r in refs}
    assert kinds == {"document", "catalogue", "venue_rule", "query"}


def test_subject_and_evidence_are_separate():
    """"bibliography entry 17" and "CrossRef 10.x" are different facts."""
    sig = S.resolved(
        "reference_exists", source="crossref", detail="matched",
    )
    sig = S.Signal(
        name=sig.name, epistemic_class=sig.epistemic_class,
        check_status=sig.check_status, finding=sig.finding, detail=sig.detail,
        source=sig.source,
        subject=S.DocumentRef(paper_id="draft", section_id="refs"),
        evidence_refs=(S.CatalogueRef(catalogue="crossref", identifier="10.1234/x"),),
    )
    d = sig.to_dict()
    assert d["subject"]["kind"] == "document"
    assert d["evidence_refs"][0]["kind"] == "catalogue"


def test_overlap_can_cite_two_locations():
    sig = S.heuristic(
        "passage_is_original", matched=True, detail="near-duplicate",
    )
    sig = S.Signal(
        name=sig.name, epistemic_class=sig.epistemic_class,
        check_status=sig.check_status, finding=sig.finding, detail=sig.detail,
        evidence_refs=(S.DocumentRef(paper_id="a", char_start=0, char_end=50),
                       S.DocumentRef(paper_id="b", char_start=90, char_end=140)),
    )
    assert len(sig.to_dict()["evidence_refs"]) == 2


def test_heuristic_signals_can_record_what_produced_them():
    """A model judgement is only re-checkable if you know the model and prompt."""
    sig = S.Signal(
        name="claim_supported",
        epistemic_class=S.EpistemicClass.HEURISTIC_ADVISORY,
        check_status=S.CheckStatus.CHECKED, finding=S.Finding.SUPPORTED,
        detail="states it directly", source="claim_audit",
        checker_version="1.4.2", prompt_sha="abc123", checked_at="2026-08-22T10:00:00Z",
    )
    d = sig.to_dict()
    assert d["prompt_sha"] == "abc123" and d["checked_at"].startswith("2026")


def test_timestamps_are_never_auto_filled():
    """An implicit now() makes signals non-comparable and tests flaky."""
    assert S.resolved("x", detail="d").checked_at == ""


def test_to_dict_keeps_the_existing_keys():
    """claim_audit and the API already serialise these; adding fields must not
    remove any."""
    d = S.resolved("x", source="s", detail="d").to_dict()
    for key in ("name", "epistemic_class", "check_status", "finding", "detail",
                "source", "evidence", "is_clean", "label"):
        assert key in d
