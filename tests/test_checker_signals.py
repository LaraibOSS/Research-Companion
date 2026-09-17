"""Every deterministic checker, expressed in one vocabulary.

Each checker grew its own result shape, so "we could not check this" is spelled
differently in each — and any consumer that forgets one of the spellings renders
it as a pass. These adapters translate; they do not replace.

The property under test throughout: **a check that did not establish something
never reads as clean, and a check that could not apply never reads as an
outstanding task.**
"""
from __future__ import annotations

from types import SimpleNamespace

from research_companion import checker_signals as cs
from research_companion.refcheck.validate import Reference, RefVerdict
from research_companion.signals import CheckStatus, Finding, Reason


def _verdicts(*pairs):
    return SimpleNamespace(entries=[(Reference(title=t), v) for t, v in pairs])


# ---------------------------------------------------------------------------
# refcheck — one status hiding two questions
# ---------------------------------------------------------------------------

def test_a_suspect_reference_exists_but_its_details_do_not_match():
    """The decomposition the native `suspect` status flattens.

    Reporting only existence hides a real finding; reporting only the mismatch
    implies the reference is fabricated. Both are wrong, so emit both.
    """
    sigs = cs.refcheck_signals(_verdicts(
        ("Sloppy Cite", RefVerdict(status="suspect", reasons=["Title does not match"])),
    ))
    by_name = {s.name: s for s in sigs}
    assert by_name["reference_exists"].finding is Finding.SUPPORTED
    assert by_name["reference_details_match"].finding is Finding.CONTRADICTED
    assert by_name["reference_details_match"].needs_attention is True


def test_a_verified_reference_is_clean_on_both_counts():
    sigs = cs.refcheck_signals(_verdicts(("Good", RefVerdict(status="verified", reasons=[]))))
    assert all(s.is_clean for s in sigs)
    assert not any(s.needs_attention for s in sigs)


def test_a_missing_reference_is_contradicted_not_degraded():
    sigs = cs.refcheck_signals(_verdicts(
        ("Nonexistent", RefVerdict(status="unverified",
                                   reasons=["No matching record found in authoritative sources"])),
    ))
    assert sigs[0].check_status is CheckStatus.CHECKED
    assert sigs[0].finding is Finding.CONTRADICTED


def test_an_outage_is_degraded_and_never_contradicted():
    """The distinction the whole model exists for: silence is not an answer.

    Reporting an unreachable catalogue as CONTRADICTED would accuse a real
    reference of not existing because the network was down.
    """
    sigs = cs.refcheck_signals(_verdicts(
        ("During outage", RefVerdict(
            status="unverified",
            reasons=["Could not verify — no bibliographic source could be reached."])),
    ))
    assert len(sigs) == 1
    assert sigs[0].check_status is CheckStatus.DEGRADED
    assert sigs[0].finding is Finding.UNRESOLVED
    assert sigs[0].reason is Reason.SOURCE_UNAVAILABLE
    assert sigs[0].is_clean is False and sigs[0].is_adverse is False


# ---------------------------------------------------------------------------
# statcheck — nothing found is the interesting case
# ---------------------------------------------------------------------------

def test_no_parseable_statistics_is_not_applicable_not_clean():
    sigs = cs.statcheck_signals({"findings": [], "summary": {"n_tests": 0}})
    assert len(sigs) == 1
    s = sigs[0]
    assert s.check_status is CheckStatus.NOT_APPLICABLE
    assert s.is_clean is False, "must never read as a pass"
    assert s.needs_attention is False, "and must not invent a task either"
    assert "not a clean bill of health" in s.detail


def test_an_inconsistent_test_is_adverse():
    sigs = cs.statcheck_signals({
        "findings": [{"status": "inconsistent", "message": "t(28)=2.20 implies p=.036"}],
        "summary": {"n_tests": 1},
    })
    assert sigs[0].is_adverse is True
    assert sigs[0].name == "statistics_internally_consistent"


def test_grim_gets_its_own_proposition():
    """GRIM tests whether a mean is possible, not whether a p-value matches."""
    sigs = cs.statcheck_signals({
        "findings": [{"status": "impossible_mean", "message": "mean impossible for n=7"}],
        "summary": {"n_means": 1, "n_tests": 1},
    })
    assert sigs[0].name == "reported_means_are_possible"
    assert sigs[0].is_adverse is True


# ---------------------------------------------------------------------------
# compliance — one "skipped" covering two different facts
# ---------------------------------------------------------------------------

def _compliance(*checks):
    return cs.compliance_signals({"checks": list(checks)}, venue_slug="neurips")


def test_a_rule_the_venue_does_not_have_is_not_applicable():
    sigs = _compliance({"check": "abstract_word_limit", "status": "skipped",
                        "message": "no abstract word limit for this venue"})
    assert sigs[0].check_status is CheckStatus.NOT_APPLICABLE
    assert sigs[0].reason is Reason.NO_SUCH_REQUIREMENT
    assert sigs[0].needs_attention is False


def test_a_rule_we_could_not_evaluate_still_demands_attention():
    """Same native status, opposite meaning: this one is an outstanding task."""
    sigs = _compliance({"check": "citation_completeness", "status": "skipped",
                        "message": "no extraction — run build first"})
    assert sigs[0].check_status is CheckStatus.NOT_CHECKED
    assert sigs[0].needs_attention is True


def test_an_unrecognised_skip_reason_errs_toward_needing_attention():
    """Assuming a check was irrelevant is the more dangerous mistake."""
    sigs = _compliance({"check": "mystery", "status": "skipped", "message": "something odd"})
    assert sigs[0].needs_attention is True


def test_a_desk_reject_finding_is_adverse():
    sigs = _compliance({"check": "limitations", "status": "finding",
                        "severity": "desk_reject", "message": "no limitations section"})
    assert sigs[0].is_adverse is True
    assert sigs[0].evidence["severity"] == "desk_reject"


# ---------------------------------------------------------------------------
# overlap — an empty library is not a clean bill
# ---------------------------------------------------------------------------

def test_nothing_to_compare_against_is_not_applicable():
    sigs = cs.overlap_signals(
        {"findings": [],
         "summary": {"papers": [], "text": "no other library papers to compare against"}},
        paper_id="p1")
    assert sigs[0].check_status is CheckStatus.NOT_APPLICABLE
    assert sigs[0].is_clean is False, "nothing was established"
    assert sigs[0].needs_attention is False


def test_a_real_comparison_with_no_hits_is_clean():
    sigs = cs.overlap_signals(
        {"findings": [], "summary": {"papers": ["p2", "p3"]}}, paper_id="p1")
    assert sigs[0].is_clean is True


def test_an_overlapping_passage_cites_both_documents():
    sigs = cs.overlap_signals(
        {"findings": [{"paper_id": "p2", "score": 0.94, "message": "near-duplicate"}],
         "summary": {"papers": ["p2"]}}, paper_id="p1")
    s = sigs[0]
    assert s.is_adverse is True
    assert s.subject.paper_id == "p1"
    assert s.evidence_refs[0].paper_id == "p2"


# ---------------------------------------------------------------------------
# The shared contract
# ---------------------------------------------------------------------------

def test_every_proposition_reads_so_that_supported_means_no_problem():
    """Otherwise CONTRADICTED means good in one checker and bad in another, and
    no shared renderer can colour anything."""
    names = set()
    names |= {s.name for s in cs.refcheck_signals(
        _verdicts(("x", RefVerdict(status="verified", reasons=[]))))}
    names |= {s.name for s in cs.statcheck_signals(
        {"findings": [{"status": "consistent", "message": "ok"}], "summary": {"n_tests": 1}})}
    names |= {s.name for s in cs.overlap_signals(
        {"findings": [], "summary": {"papers": ["p2"]}}, paper_id="p1")}
    for n in names:
        assert not any(bad in n for bad in ("_detected", "_failed", "_violation")), n


def test_malformed_input_never_raises():
    for empty in ({}, {"findings": None}, {"checks": None}):
        cs.statcheck_signals(empty)
        cs.compliance_signals(empty)
        cs.overlap_signals(empty)
    cs.refcheck_signals(SimpleNamespace(entries=[]))
