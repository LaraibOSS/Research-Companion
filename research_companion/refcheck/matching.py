"""Pure, network-free matching helpers for reference validation.

These are the deterministic pre-filters: cheap string comparisons that decide
whether a bibliography entry plausibly matches an authoritative record before
any expensive lookup or LLM call.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for comparison only."""
    title = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    return re.sub(r"\s+", " ", title).strip()


def title_similarity(a: str, b: str) -> float:
    """Similarity ratio in [0, 1] between two titles, ignoring case/punctuation."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na and not nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def title_is_cited(cited: str, authoritative: str) -> bool:
    """Does *cited* refer to the *authoritative* title?

    ``title_similarity`` compares two titles. A bibliography line parsed from a
    paper's own text is not a title -- it carries the authors, venue and pages
    around one, which drags the ratio well below the threshold. "Vaswani et al.
    Attention is all you need. NeurIPS" scores 0.69 against "Attention Is All
    You Need" and would be reported as a title mismatch: a false accusation
    against a perfectly correct citation.

    So: a match is either a high similarity ratio, OR the authoritative title
    appearing whole inside the cited string. Containment is real evidence the
    right work was cited, not a relaxation of the check -- a genuinely wrong
    title still fails both tests.
    """
    na, nb = normalize_title(cited), normalize_title(authoritative)
    if not nb:
        return False
    if title_similarity(cited, authoritative) >= 0.9:
        return True

    # Otherwise measure the longest CONTIGUOUS run the two share. This is the
    # only test that survives both ways a real bibliography deviates from the
    # authoritative record:
    #   extra text  - "Vaswani et al. <title>. NeurIPS 2017"
    #   truncation  - "BERT: pre-training of deep bidirectional transformers"
    #                 for a record ending "...for Language Understanding"
    # A different paper shares no long run, so this does not weaken the check.
    # The floor is on the SHARED RUN, not the title: it stops a short generic
    # phrase ("deep learning", 13 chars) matching a longer record that merely
    # starts with it. It must stay below a real short title though -- "Layer
    # Normalization" normalises to 19 chars and was a 100% match rejected by a
    # 20-char floor.
    match = SequenceMatcher(None, na, nb).find_longest_match(0, len(na), 0, len(nb))
    return match.size >= 15 and (match.size / len(nb)) >= 0.4


def _fold(text: str) -> str:
    """Strip accents so "Müller" and "Muller" compare equal."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def title_matched_by_containment(cited: str, authoritative: str,
                                 cited_title: str | None = None) -> bool:
    """True when ``title_is_cited`` passes only through its shared-run rule.

    ``cited_title`` is the caller's best guess at the title inside the cited
    line (``parse.probable_title``). When that guess itself matches the record
    the match is a whole-title one after all -- the line merely carried an
    identifier or a venue beside it -- and no second opinion is needed.

    That rule measures the shared run against the RECORD's title alone, which
    it has to: the cited line carries authors and venue, so its own length
    says nothing. The consequence is that a short record title sitting inside
    a longer cited title passes at 100% -- "Deep Reinforcement Learning" is
    wholly contained in a line citing "Deep reinforcement learning for protein
    folding dynamics in zero gravity". The title alone cannot tell those
    apart, so a containment match needs a second, independent agreement
    before it is believed (see ``authors_corroborate``).
    """
    if not title_is_cited(cited, authoritative):
        return False
    if cited_title and title_similarity(cited_title, authoritative) >= 0.9:
        return False
    return title_similarity(cited, authoritative) < 0.9


def authors_corroborate(cited: str, record_authors: list[str]) -> bool | None:
    """Does the cited line name any author of the matched record?

    A bibliography line carries its authors, so when a record was matched on
    title containment alone, finding one of the record's surnames in the line
    is cheap independent evidence it is the same work -- and finding none is
    evidence it is not. Returns None when the record lists no usable authors:
    there is nothing to compare, which is not the same as a disagreement.

    One surname is enough. Lines routinely give only a first author and
    "et al.", and catalogues disagree on author order and completeness.
    """
    keys = {_last_name(_fold(a)) for a in record_authors or []}
    keys.discard("")
    if not keys:
        return None
    folded = _fold(cited).lower()
    words = set(re.sub(r"[^a-z0-9\s]", " ", folded).split())
    squashed = re.sub(r"[^a-z0-9]", "", folded)
    for key in keys:
        if key in words:
            return True
        # Hyphenated or spaced surnames ("Chang-Wei", "van der Maaten") do not
        # survive as one word. Only long keys may match as a substring: a
        # two-letter surname would otherwise be found inside any sentence.
        if len(key) >= 5 and key in squashed:
            return True
    return False


def short_title_matches_exactly(cited: str, authoritative: str, cited_title: str | None,
                                record_authors: list[str]) -> bool:
    """A short real title, cited whole, by one of its own authors.

    ``title_is_cited`` refuses shared runs under 15 characters so that a
    generic phrase ("Deep learning") cannot verify any longer record that
    begins with it. That floor also rejected the real paper titled exactly
    "Deep learning" (LeCun, Bengio, Hinton, Nature 2015): a false accusation.

    Accept a short title only when the title extracted from the line equals
    the record's title AND the line names one of the record's authors. The
    generic-phrase case still fails: a different record has different authors.
    """
    if not cited_title or not authoritative:
        return False
    if title_similarity(cited_title, authoritative) < 0.9:
        return False
    return authors_corroborate(cited, record_authors) is True


def names_people(cited: str, cited_title: str | None) -> bool:
    """Does the cited line carry an author segment before its title?

    Lines extracted by a model are often the title alone ("Attention Is All
    You Need. arXiv:1706.03762"). Asking such a line for an author in common
    would accuse every one of them, so the author check below applies only
    when the line actually names someone ahead of the title.
    """
    if not cited_title:
        return False
    head = _fold(cited).lower().split(_fold(cited_title).lower().strip(), 1)[0]
    words = [w for w in re.split(r"[^a-z]+", head) if len(w) >= 2 and w not in ("et", "al", "and")]
    return len(words) >= 1


def _last_name(author: str) -> str:
    """Best-effort surname extraction, normalized to lowercase alphanumerics.

    Handles "John Smith" -> "smith" and "Smith, John" -> "smith".
    """
    author = author.strip()
    if "," in author:
        surname = author.split(",", 1)[0]
    else:
        parts = author.split()
        surname = parts[-1] if parts else ""
    return re.sub(r"[^a-z0-9]", "", surname.lower())


def author_overlap(claimed: list[str], authoritative: list[str]) -> float:
    """Fraction of `claimed` authors whose surname appears in `authoritative`.

    Matching is on normalized surname, so "J. Smith" matches "John Smith".
    Returns 0.0 when `claimed` is empty (nothing to confirm).
    """
    if not claimed:
        return 0.0
    auth_surnames = {_last_name(a) for a in authoritative}
    auth_surnames.discard("")
    matched = sum(1 for c in claimed if _last_name(c) in auth_surnames)
    return matched / len(claimed)
