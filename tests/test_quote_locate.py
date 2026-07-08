"""Tests for locating a quote's character offsets within source text."""
from __future__ import annotations

from research_companion.rebuttal.verify import locate_quote, verify_quote

TEXT = "In Section 4.2 we compare against BaselineX on three datasets."


def test_locate_quote_exact():
    quote = "we compare against BaselineX"
    span = locate_quote(quote, TEXT)
    assert span is not None
    start, end = span
    assert TEXT[start:end] == quote


def test_locate_quote_whitespace_case_insensitive():
    text = "Recent work on large   language\nmodels has shown promise."
    quote = "Large Language Models"
    span = locate_quote(quote, text)
    assert span is not None
    start, end = span

    def norm(s: str) -> str:
        return " ".join(s.lower().split())

    assert norm(text[start:end]) == norm(quote)


def test_locate_quote_absent():
    assert locate_quote("we outperform everything on every benchmark", TEXT) is None


def test_locate_quote_empty_quote():
    assert locate_quote("", TEXT) is None


def test_locate_quote_empty_text():
    assert locate_quote("we compare against BaselineX", "") is None


def test_locate_quote_too_short():
    # "on three" is well under the 15-char floor, even though it's present.
    assert locate_quote("on three", TEXT) is None


def test_locate_quote_returns_first_occurrence():
    text = "repeat this exact phrase here. later, repeat this exact phrase here again."
    quote = "repeat this exact phrase here"
    span = locate_quote(quote, text)
    assert span is not None
    start, end = span
    assert (start, end) == (0, len(quote))
    assert text[start:end] == quote


def test_verify_quote_still_exact():
    assert verify_quote("we compare against BaselineX", TEXT) == (True, "exact")


def test_verify_quote_still_normalized():
    ok, how = verify_quote("WE   compare against baselinex", TEXT)
    assert ok and how == "normalized"


def test_verify_quote_still_miss():
    assert verify_quote("we outperform everything", TEXT) == (False, "")
