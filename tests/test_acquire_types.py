"""The acquisition outcome model.

Every download failure used to collapse to None, so 404, 403, timeout, an
HTML body and the size cap were indistinguishable. That is why a paywalled
ACM article and an unreachable host produced the same sentence.
"""
from __future__ import annotations

import pytest

from research_companion.acquire import AcquireReason, Acquisition, Attempt, HostClass


def _attempt(status=403, host_class=HostClass.PUBLISHER):
    return Attempt(url="https://dl.acm.org/doi/pdf/10.1145/3732941",
                   host_class=host_class, status=status, outcome="403")


def test_an_obtained_acquisition_carries_no_reason():
    a = Acquisition(obtained=True, reason=None, attempts=(), source=None)
    assert a.obtained is True
    assert a.reason is None


def test_an_obtained_acquisition_may_not_carry_a_reason():
    """The invariant that keeps 'we got it, but here is why we didn't' out."""
    with pytest.raises(ValueError):
        Acquisition(obtained=True, reason=AcquireReason.PAYWALLED,
                    attempts=(), source=None)


def test_a_failed_acquisition_must_carry_a_reason():
    with pytest.raises(ValueError):
        Acquisition(obtained=False, reason=None, attempts=(), source=None)


@pytest.mark.parametrize("reason", [
    AcquireReason.BLOCKED_BY_HOST,
    AcquireReason.PAYWALLED,
    AcquireReason.NO_LOCATION_FOUND,
    AcquireReason.NOT_A_PDF,
    AcquireReason.NOT_ATTEMPTED,
])
def test_a_person_can_help_with_everything_except_a_transient_failure(reason):
    a = Acquisition(obtained=False, reason=reason, attempts=(), source=None)
    assert a.human_can_help is True


def test_the_machine_owns_transient_failures():
    """SOURCE_UNAVAILABLE is the one reason that does NOT go to the queue:
    retrying is the machine's job, and asking a person to fix a timeout is
    noise."""
    a = Acquisition(obtained=False, reason=AcquireReason.SOURCE_UNAVAILABLE,
                    attempts=(), source=None)
    assert a.human_can_help is False


def test_paywalled_still_reaches_the_person():
    """We cannot know whether this user has institutional access. Offering the
    action and letting them find out beats deciding they cannot."""
    a = Acquisition(obtained=False, reason=AcquireReason.PAYWALLED,
                    attempts=(), source=None)
    assert a.human_can_help is True


def test_an_obtained_acquisition_needs_nobody():
    a = Acquisition(obtained=True, reason=None, attempts=(), source=None)
    assert a.human_can_help is False


def test_attempts_are_ordered_and_immutable():
    a = Acquisition(obtained=False, reason=AcquireReason.BLOCKED_BY_HOST,
                    attempts=(_attempt(), _attempt(status=404)), source=None)
    assert [x.status for x in a.attempts] == [403, 404]
    with pytest.raises((AttributeError, TypeError)):
        a.attempts[0].status = 200


def test_to_dict_round_trips_for_persistence():
    a = Acquisition(obtained=False, reason=AcquireReason.BLOCKED_BY_HOST,
                    attempts=(_attempt(),), source=None)
    d = a.to_dict()
    assert d["reason"] == "blocked_by_host"
    assert d["human_can_help"] is True
    assert d["attempts"][0]["host_class"] == "publisher"
    assert Acquisition.from_dict(d) == a
