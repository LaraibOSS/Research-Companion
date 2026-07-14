"""Cross-discipline venue knowledge base for the venue-fit checker.

Venue data lives in ``research_companion/data/venues.json`` (Phase 3 #11) and is
loaded into the ``VENUES`` registry at import time — adding or editing a venue
needs no code change. Each venue carries a scope blurb, topic keywords (for the
deterministic overlap prefilter), a discipline, reporting checklists, and common
desk-reject rules.

Everything here is deterministic and LLM-free; the fuzzy judgement lives in the
agent's LLM step (agents/venuefit.py), grounded by topic_overlap() and, for
cross-discipline routing, infer_discipline().
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib.resources import files


@dataclass(frozen=True)
class Venue:
    slug: str
    name: str
    kind: str  # "conference" | "journal"
    scope: str
    topics: tuple[str, ...] = field(default_factory=tuple)
    discipline: str = "general"
    checklists: tuple[str, ...] = field(default_factory=tuple)
    desk_reject_rules: tuple[str, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)


def _load_venues() -> dict[str, Venue]:
    """Load the venue KB from packaged JSON into a slug -> Venue registry."""
    raw = json.loads(
        (files("research_companion") / "data" / "venues.json").read_text("utf-8"))
    registry: dict[str, Venue] = {}
    for v in raw.get("venues", []):
        venue = Venue(
            slug=v["slug"],
            name=v["name"],
            kind=v.get("kind", "conference"),
            scope=v.get("scope", ""),
            topics=tuple(v.get("topics", ())),
            discipline=v.get("discipline", "general"),
            checklists=tuple(v.get("checklists", ())),
            desk_reject_rules=tuple(v.get("desk_reject_rules", ())),
            aliases=tuple(v.get("aliases", ())),
        )
        registry[venue.slug] = venue
    return registry


VENUES: dict[str, Venue] = _load_venues()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def get_venue(slug_or_name: str) -> Venue | None:
    """Resolve a venue by slug, alias, or (case/space-insensitive) name."""
    if not slug_or_name:
        return None
    key = slug_or_name.strip().lower()
    if key in VENUES:
        return VENUES[key]
    norm = _slug(slug_or_name)
    for v in VENUES.values():
        if _slug(v.slug) == norm or _slug(v.name) == norm:
            return v
        if any(_slug(a) == norm for a in v.aliases):
            return v
    return None


def list_venues() -> list[Venue]:
    """All registered venues, sorted by slug."""
    return [VENUES[k] for k in sorted(VENUES)]


def list_disciplines() -> list[str]:
    """All distinct disciplines represented in the registry, sorted."""
    return sorted({v.discipline for v in VENUES.values()})


def venues_for_discipline(discipline: str) -> list[Venue]:
    """Venues in *discipline*, sorted by slug."""
    return [v for v in list_venues() if v.discipline == discipline]


_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def topic_overlap(paper_terms: list[str], venue: Venue) -> float:
    """Deterministic scope-overlap prefilter in [0, 1].

    Fraction of the venue's topics that appear (as whole multi-word phrases or
    shared tokens) in the paper's terms — title, abstract, concept names, etc.
    """
    if not venue.topics:
        return 0.0
    haystack = " ".join(paper_terms).lower()
    hay_tokens = _norm_tokens(haystack)
    hits = 0
    for topic in venue.topics:
        if " " in topic:
            if topic in haystack:
                hits += 1
        elif topic in hay_tokens:
            hits += 1
    return hits / len(venue.topics)


def infer_discipline(paper_terms: list[str]) -> tuple[str | None, float]:
    """Infer the paper's most likely discipline from topic overlap.

    Scores each discipline by the best topic_overlap across its venues and
    returns (discipline, score). Returns (None, 0.0) when nothing overlaps.
    """
    best_disc: str | None = None
    best_score = 0.0
    for discipline in list_disciplines():
        score = max((topic_overlap(paper_terms, v)
                     for v in venues_for_discipline(discipline)), default=0.0)
        if score > best_score:
            best_score, best_disc = score, discipline
    return best_disc, best_score


def suggest_alternatives(venue: Venue, paper_terms: list[str], *, limit: int = 3) -> list[str]:
    """Suggest in-discipline alternative venues ranked by topic overlap.

    Used when a paper is a weak/out-of-scope fit for *venue*: recommends other
    venues in the same discipline that overlap the paper better.
    """
    peers = [v for v in venues_for_discipline(venue.discipline) if v.slug != venue.slug]
    scored = sorted(peers, key=lambda v: (-topic_overlap(paper_terms, v), v.slug))
    return [v.name for v in scored[:limit]]
