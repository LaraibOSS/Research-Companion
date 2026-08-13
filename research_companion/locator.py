"""Citation locators — a resolvable pointer to *where* a claim came from.

A citation that names a paper says "this idea is in there somewhere". That is
not enough to check anything: to ask whether a source actually supports a
claim, you first have to be able to fetch the passage the claim was drawn
from. Without a locator, "unverified" and "unverifiable" are the same word.

A locator is that pointer — paper, section, character range, and the quote
itself where one exists. Two things follow:

* Verifying a quote becomes a **mechanical** offset/substring check rather
  than a judgement call.
* **Anchorless** becomes a detectable state. A citation with no locator is not
  "fine", it is *uncheckable*, and the difference is reportable.

The kinds are ordered by how much they let you check:

    QUOTE   -> exact character range; the strongest anchor
    SECTION -> a section of the paper; narrows to a passage
    PAPER   -> the document only; you can fetch it, not a passage
    NONE    -> nothing to resolve; the citation cannot be audited

Prior art: the typed citation anchors in ARS (`academic-research-skills`,
CC BY-NC 4.0). Independent implementation; no ARS code or text is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class LocatorKind(str, Enum):
    QUOTE = "quote"
    SECTION = "section"
    PAPER = "paper"
    NONE = "none"


#: How much of the source a kind lets you actually retrieve, strongest first.
#: Used to compare anchors, and to decide whether an audit is even possible.
_STRENGTH = {
    LocatorKind.QUOTE: 3,
    LocatorKind.SECTION: 2,
    LocatorKind.PAPER: 1,
    LocatorKind.NONE: 0,
}


@dataclass(frozen=True)
class Locator:
    """Where a cited claim can be found. ``paper_id`` is the only hard
    requirement; everything else narrows the target."""

    paper_id: str
    kind: LocatorKind = LocatorKind.NONE
    section_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str = ""

    @property
    def is_anchored(self) -> bool:
        """True when this points at a passage, not merely at a document.

        ``PAPER`` is deliberately excluded: naming a document is not an anchor,
        it is the citation itself.
        """
        return _STRENGTH[self.kind] >= _STRENGTH[LocatorKind.SECTION]

    @property
    def strength(self) -> int:
        return _STRENGTH[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "kind": self.kind.value,
            "section_id": self.section_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "quote": self.quote,
            "is_anchored": self.is_anchored,
        }


def anchorless(paper_id: str) -> Locator:
    """A citation naming a paper we cannot resolve a passage in."""
    return Locator(paper_id=paper_id, kind=LocatorKind.PAPER if paper_id else LocatorKind.NONE)


def _norm(text: str) -> str:
    """Whitespace/case-insensitive form, matching how quotes are verified
    elsewhere so an anchor agrees with the verification badge."""
    return " ".join(text.split()).lower()


def anchor_quote(paper_id: str, quote: str, fulltext: str) -> Locator:
    """Locate *quote* inside *fulltext* and return the strongest anchor found.

    Tries an exact match first, then a whitespace/case-insensitive one (the
    same two tiers quote verification uses, so a quote that verifies is a quote
    that anchors). Falls back to a paper-level locator when the quote cannot be
    placed — never a QUOTE anchor with invented offsets.
    """
    if not paper_id or not quote or not fulltext:
        return anchorless(paper_id)

    idx = fulltext.find(quote)
    if idx != -1:
        return Locator(paper_id=paper_id, kind=LocatorKind.QUOTE,
                       char_start=idx, char_end=idx + len(quote), quote=quote)

    # Normalized fallback: locate in the normalized text, then map back by
    # walking the original and comparing normalized prefixes. Cheap enough for
    # the passage sizes involved, and avoids reporting offsets we cannot trust.
    nq, nf = _norm(quote), _norm(fulltext)
    if nq and nq in nf:
        approx = _map_normalized_span(fulltext, quote)
        if approx is not None:
            start, end = approx
            return Locator(paper_id=paper_id, kind=LocatorKind.QUOTE,
                           char_start=start, char_end=end, quote=quote)
        # Found it, but could not place it precisely — say section-less rather
        # than fabricate a range.
        return Locator(paper_id=paper_id, kind=LocatorKind.PAPER, quote=quote)

    return anchorless(paper_id)


def _map_normalized_span(fulltext: str, quote: str) -> tuple[int, int] | None:
    """Best-effort character span in *fulltext* for a normalized match."""
    target = _norm(quote)
    if not target:
        return None
    # Walk candidate start positions at word boundaries only — a quote never
    # starts mid-token, and this keeps the scan linear in practice.
    starts = [0] + [i + 1 for i, ch in enumerate(fulltext) if ch.isspace()]
    for start in starts:
        window = fulltext[start:start + len(quote) * 3 + 32]
        if _norm(window).startswith(target):
            # Take the SHORTEST span whose normalized form EQUALS the target.
            # `startswith` would happily run past the end of the quote and
            # return a range containing words the author never quoted.
            limit = min(len(fulltext), start + len(window))
            for end in range(start + 1, limit + 1):
                if _norm(fulltext[start:end]) == target:
                    return start, end
            return None
    return None


def anchor_section(paper_id: str, section_id: str,
                   sections_payload: dict | None) -> Locator:
    """Anchor to a section, carrying its character range when the tiling has one."""
    if not paper_id or not section_id:
        return anchorless(paper_id)
    for sec in (sections_payload or {}).get("sections", []):
        if sec.get("section_id") == section_id:
            return Locator(
                paper_id=paper_id, kind=LocatorKind.SECTION, section_id=section_id,
                char_start=sec.get("char_start"), char_end=sec.get("char_end"),
            )
    # Named a section the tiling does not contain: do not pretend to have it.
    return anchorless(paper_id)


def resolve(loc: Locator, fulltext: str) -> str:
    """Return the anchored passage from *fulltext*.

    "" when the locator does not point at a passage — the caller must treat
    that as *uncheckable*, never as an empty-but-fine result.
    """
    if not loc.is_anchored or not fulltext:
        return ""
    start, end = loc.char_start, loc.char_end
    if start is None or end is None:
        return ""
    start = max(0, min(start, len(fulltext)))
    end = max(start, min(end, len(fulltext)))
    return fulltext[start:end]
