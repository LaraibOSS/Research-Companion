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
