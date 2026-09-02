"""An acquisition failure must name its own cause.

Every one of the 17 real failures read 'no PDF on disk for doi:...'. That is
the symptom, observed three steps downstream: the OA locator had already found
the correct open-access URL and ACM had answered 403. The message sent the user
to look for a missing file, and made a web crawler look necessary.

Third instance of the pattern in section 8 of the decision record. This module
exists so there is not a fourth.
"""
from __future__ import annotations

import re

import pytest

from research_companion.acquire import AcquireReason, Acquisition, Attempt, HostClass
from research_companion.acquire.copy import publisher_name, reason_detail, reason_headline

ALL_REASONS = list(AcquireReason)

# Words that assert absence. None of them may describe a refusal.
# Broadened to catch future rephrasings: unable to, couldn't/could not with
# action verbs, no copy, nothing found. Each alternation is specific to avoid
# false positives like "The PDF download was never attempted" (NOT_ATTEMPTED's
# headline) matching "nothing found".
_ABSENCE = re.compile(
    r"no pdf|not found|missing|does not exist|couldn't (?:find|locate|retrieve|obtain|get)|"
    r"could not (?:find|locate|retrieve|obtain|get)|unavailable file|"
    r"unable to (?:obtain|retrieve|locate|find|get)|no copy|nothing found",
    re.I
)


def _acq(reason, attempts=()):
    return Acquisition(obtained=False, reason=reason, attempts=tuple(attempts))


def _attempt(url="https://dl.acm.org/doi/pdf/1", status=403, outcome="403"):
    return Attempt(url=url, host_class=HostClass.PUBLISHER, status=status,
                   outcome=outcome)


@pytest.mark.parametrize("reason", ALL_REASONS)
def test_every_reason_has_a_headline_and_a_detail(reason):
    a = _acq(reason)
    assert reason_headline(a).strip()
    assert reason_detail(a).strip()


def test_a_blocked_host_is_never_described_as_a_missing_file():
    """The regression that motivated all of this."""
    a = _acq(AcquireReason.BLOCKED_BY_HOST, [_attempt()])
    text = reason_headline(a) + " " + reason_detail(a)
    assert not _ABSENCE.search(text), f"reports absence for a refusal: {text!r}"


def test_a_blocked_host_says_the_paper_is_free_and_the_browser_can_get_it():
    a = _acq(AcquireReason.BLOCKED_BY_HOST, [_attempt()])
    text = (reason_headline(a) + " " + reason_detail(a)).lower()
    assert "open access" in text
    assert "browser" in text


def test_a_blocked_host_names_the_host_that_refused():
    a = _acq(AcquireReason.BLOCKED_BY_HOST, [_attempt()])
    assert "ACM" in reason_headline(a) + reason_detail(a)


def test_paywalled_is_never_described_as_a_missing_file_either():
    a = _acq(AcquireReason.PAYWALLED, [_attempt(status=404, outcome="404")])
    text = reason_headline(a) + " " + reason_detail(a)
    assert not _ABSENCE.search(text)


def test_only_no_location_found_may_say_nothing_was_found():
    """The one reason that IS an absence. Everything else must not borrow its
    words."""
    a = _acq(AcquireReason.NO_LOCATION_FOUND)
    assert _ABSENCE.search(reason_headline(a) + " " + reason_detail(a))


@pytest.mark.parametrize("reason", ALL_REASONS)
def test_the_internal_symptom_string_never_reaches_a_user(reason):
    text = reason_headline(_acq(reason)) + " " + reason_detail(_acq(reason))
    assert "no PDF on disk" not in text
    assert "on disk" not in text


def test_the_detail_reports_how_many_sources_were_tried():
    a = _acq(AcquireReason.PAYWALLED,
             [_attempt(), _attempt(url="https://zenodo.org/a.pdf")])
    assert "2 source" in reason_detail(a)


def test_a_transient_failure_does_not_promise_a_retry_nobody_performs():
    """SOURCE_UNAVAILABLE is the one reason human_can_help is False for, so
    it is excluded from the Needs-you queue, the find-pdf sweep and
    `acquire --list/--all`, Find PDF is hidden for it, and no background job
    schedules a retry. The copy therefore must not say one is coming; it
    names the action a person can actually take instead."""
    a = _acq(AcquireReason.SOURCE_UNAVAILABLE, [_attempt(status=None, outcome="timeout")])
    text = (reason_headline(a) + " " + reason_detail(a)).lower()
    assert "we'll try again" not in text
    assert "will try again" not in text
    assert "acquire" in text, "must name the surface that DOES re-run it"


@pytest.mark.parametrize("url,expected", [
    ("https://dl.acm.org/doi/pdf/1", "ACM"),
    ("https://ieeexplore.ieee.org/stamp/1", "IEEE"),
    ("https://link.springer.com/x.pdf", "Springer"),
    ("https://www.sciencedirect.com/x.pdf", "Elsevier"),
    ("https://onlinelibrary.wiley.com/x.pdf", "Wiley"),
])
def test_known_publishers_are_named(url, expected):
    assert publisher_name(url) == expected


def test_an_unknown_publisher_falls_back_to_its_hostname():
    assert publisher_name("https://journal.example.org/x.pdf") == "journal.example.org"


@pytest.mark.parametrize("bad", ["", None, "not a url"])
def test_naming_never_raises(bad):
    assert publisher_name(bad) is None


def test_copy_never_raises_on_an_obtained_acquisition():
    a = Acquisition(obtained=True, reason=None)
    assert reason_headline(a) == ""
    assert reason_detail(a) == ""


def test_not_attempted_does_not_claim_the_paper_lacks_an_identifier():
    """NOT_ATTEMPTED covers two situations: a paper with genuinely no
    identifier, and a metadata lookup (e.g. a DOI Crossref has no entry for)
    that failed before acquisition ever began -- an identifier WAS supplied
    and used in the second case. The message must state only the shared
    fact (the download was never attempted), never assert a reason it
    cannot know."""
    a = _acq(AcquireReason.NOT_ATTEMPTED)
    text = (reason_headline(a) + " " + reason_detail(a)).lower()
    assert "no identifier" not in text
    assert "identifier" not in text


def test_the_absence_guard_catches_rephrasings():
    """Prove the guard would catch future violations — e.g. if someone rewrote
    BLOCKED_BY_HOST as 'unable to obtain' or 'couldn't locate' — that would be
    exactly the bug this module prevents."""
    bad_messages = [
        "we couldn't locate a PDF for this paper",
        "unable to obtain a copy",
        "no copy available",
        "couldn't retrieve the file",
        "nothing found for this identifier",
    ]
    for bad_msg in bad_messages:
        assert _ABSENCE.search(bad_msg), f"guard should catch: {bad_msg!r}"
