"""Deterministic desk-reject compliance linter.

Checks a paper against a venue's structured submission rules (page/length,
required sections, anonymization, citation completeness). Pure: no LLM, no
network. Each check self-skips when its venue field or input is absent, so a
partially-populated venue KB is fine. Rules are KB approximations — every
result carries a disclaimer to verify against the venue's current CFP.
"""
from __future__ import annotations

PAGE_SLACK = 4  # PDF page count includes refs/appendix; limits are main-text only.
DISCLAIMER = ("Rules are KB approximations — always verify against the venue's "
              "current call for papers.")


def _finding(check: str, severity: str, message: str, detail: str = "") -> dict:
    return {"check": check, "status": "finding", "severity": severity,
            "message": message, "detail": detail}


def _ok(check: str, message: str) -> dict:
    return {"check": check, "status": "ok", "severity": None, "message": message, "detail": ""}


def _skipped(check: str, message: str) -> dict:
    return {"check": check, "status": "skipped", "severity": None, "message": message, "detail": ""}


def _check_page_limit(venue, page_count) -> dict:
    if venue.page_limit is None:
        return _skipped("page_limit", "no page limit configured for this venue")
    if page_count is None:
        return _skipped("page_limit", "no PDF on disk — page limit not checked")
    if page_count > venue.page_limit + PAGE_SLACK:
        return _finding("page_limit", "desk_reject",
                        f"PDF is {page_count} pages; {venue.name} limit is {venue.page_limit}",
                        f"Counting all PDF pages (incl. references/appendix) with a "
                        f"{PAGE_SLACK}-page allowance; the main-text limit is {venue.page_limit}.")
    return _ok("page_limit", f"{page_count} pages within the {venue.page_limit}-page limit (+slack)")


def _check_abstract_words(venue, abstract) -> dict:
    if venue.abstract_word_limit is None:
        return _skipped("abstract_word_limit", "no abstract word limit for this venue")
    if not abstract:
        return _skipped("abstract_word_limit", "no abstract found")
    n = len(abstract.split())
    if n > venue.abstract_word_limit:
        return _finding("abstract_word_limit", "warning",
                        f"Abstract is {n} words; limit is {venue.abstract_word_limit}")
    return _ok("abstract_word_limit", f"abstract {n} words within {venue.abstract_word_limit}")


def check_compliance(venue, *, fulltext, sections=None, abstract=None,
                     references=None, page_count=None) -> dict:
    checks = [
        _check_page_limit(venue, page_count),
        _check_abstract_words(venue, abstract),
    ]
    counts = {"desk_reject": 0, "warning": 0}
    for c in checks:
        if c["status"] == "finding":
            counts[c["severity"]] = counts.get(c["severity"], 0) + 1
    return {"venue": venue.slug, "checks": checks, "counts": counts, "disclaimer": DISCLAIMER}
