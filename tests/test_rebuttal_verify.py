"""Tests for rebuttal quote verification against paper fulltext."""
from __future__ import annotations

from research_companion.rebuttal.verify import verify_quote, verify_reply_quotes

TEXT = "In Section 4.2 we compare against BaselineX on three datasets."


def test_verify_quote_exact():
    assert verify_quote("we compare against BaselineX", TEXT) == (True, "exact")


def test_verify_quote_normalized():
    ok, how = verify_quote("WE   compare against baselinex", TEXT)
    assert ok and how == "normalized"


def test_verify_quote_miss():
    assert verify_quote("we outperform everything", TEXT) == (False, "")


def test_verify_reply_quotes_flags_only_unverified_long_spans():
    reply = ('As stated, "we compare against BaselineX on three datasets" already; '
             'we never claim "a fabricated span that is definitely not present" and '
             'short "ok" spans are ignored.')
    bad = verify_reply_quotes(reply, TEXT)
    assert bad == ["a fabricated span that is definitely not present"]
