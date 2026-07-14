"""Deterministic ethics / integrity-declaration detector (Phase 3 #13).

Rounds out the desk-rejection taxonomy by checking whether a paper includes the
integrity declarations reviewers and venues increasingly require: funding,
conflict-of-interest, ethics/IRB approval, informed consent, and author
contributions. LLM-free and pure.

Scope note: true plagiarism detection needs an external similarity corpus/service
and is deliberately out of scope here; this module covers the declaration side of
#13. See docs/ROADMAP.md.
"""
from __future__ import annotations

import re

# name -> (pattern, expected_by_default)
# expected_by_default marks declarations most venues expect from any submission;
# consent/ethics-approval are only expected for human/animal-subjects work, so
# they are reported but never listed as "missing".
_DECLARATIONS: dict[str, tuple[re.Pattern[str], bool]] = {
    "funding": (
        re.compile(r"(funding|financial support|supported (?:in part )?by|"
                   r"grant (?:no|number|#)|acknowledge(?:s|ment)?s? .*(?:support|fund))",
                   re.IGNORECASE),
        True,
    ),
    "conflict_of_interest": (
        re.compile(r"(conflict(?:s)? of interest|competing interest|"
                   r"no (?:competing|conflicting) interest|declare no)",
                   re.IGNORECASE),
        True,
    ),
    "author_contributions": (
        re.compile(r"(author contributions|CRediT|contributed equally|"
                   r"equal contribution)", re.IGNORECASE),
        True,
    ),
    "ethics_approval": (
        re.compile(r"(ethics (?:approval|committee|board|statement)|"
                   r"institutional review board|\bIRB\b|approved by the .*(?:committee|board))",
                   re.IGNORECASE),
        False,
    ),
    "informed_consent": (
        re.compile(r"(informed consent|consent (?:to participate|was obtained)|"
                   r"participant consent)", re.IGNORECASE),
        False,
    ),
}


def detect_declarations(fulltext: str) -> dict:
    """Detect integrity declarations in *fulltext*.

    Returns a JSON-safe dict:
      {declarations: {name: bool}, present: [names], absent: [names],
       missing_expected: [names]}  where missing_expected is the subset of
       absent declarations that most venues expect from any submission.
    """
    text = fulltext or ""
    declarations = {name: bool(rx.search(text)) for name, (rx, _) in _DECLARATIONS.items()}
    present = [n for n, found in declarations.items() if found]
    absent = [n for n, found in declarations.items() if not found]
    missing_expected = [
        n for n in absent if _DECLARATIONS[n][1]
    ]
    return {
        "declarations": declarations,
        "present": present,
        "absent": absent,
        "missing_expected": missing_expected,
    }
