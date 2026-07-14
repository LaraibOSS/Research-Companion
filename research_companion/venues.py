"""Venue registry: scope profiles for common CS/ML venues.

Used by the venue-fit checker (agents/venuefit.py) to decide whether a paper's
contributions match a target venue's scope — the #1-2 desk-rejection cause. This
is the CS/ML MVP; a data-driven cross-discipline knowledge base is Phase 3 #11.

Everything here is deterministic and LLM-free; the fuzzy judgement lives in the
agent's LLM step, grounded by the topic_overlap() prefilter below.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Venue:
    slug: str
    name: str
    kind: str  # "conference" | "journal"
    scope: str
    topics: tuple[str, ...] = field(default_factory=tuple)


# Curated CS/ML venues. Topics are lowercase keywords used for the deterministic
# overlap prefilter; scope is the human-readable blurb handed to the LLM.
VENUES: dict[str, Venue] = {
    v.slug: v for v in [
        Venue(
            "neurips", "NeurIPS", "conference",
            "Neural information processing systems: machine learning theory and "
            "practice, deep learning, optimization, probabilistic methods, "
            "reinforcement learning, and neuroscience-inspired computation.",
            ("machine learning", "deep learning", "neural network", "optimization",
             "reinforcement learning", "probabilistic", "representation learning",
             "generative model", "theory"),
        ),
        Venue(
            "icml", "ICML", "conference",
            "International Conference on Machine Learning: novel machine-learning "
            "algorithms, theory, and their application across domains.",
            ("machine learning", "deep learning", "optimization", "theory",
             "reinforcement learning", "kernel", "bayesian", "generalization"),
        ),
        Venue(
            "iclr", "ICLR", "conference",
            "International Conference on Learning Representations: representation "
            "learning and deep learning, including architectures, training methods, "
            "and empirical analysis.",
            ("representation learning", "deep learning", "neural network",
             "self-supervised", "transformer", "embedding", "generative model"),
        ),
        Venue(
            "acl", "ACL", "conference",
            "Association for Computational Linguistics: natural language processing, "
            "computational linguistics, and language technologies.",
            ("nlp", "natural language processing", "language model", "parsing",
             "machine translation", "semantics", "text", "linguistics", "dialogue"),
        ),
        Venue(
            "emnlp", "EMNLP", "conference",
            "Empirical Methods in Natural Language Processing: empirical and "
            "data-driven approaches to NLP problems.",
            ("nlp", "natural language processing", "language model", "text",
             "information extraction", "question answering", "summarization"),
        ),
        Venue(
            "cvpr", "CVPR", "conference",
            "Computer Vision and Pattern Recognition: image and video understanding, "
            "recognition, 3D vision, and visual learning.",
            ("computer vision", "image", "video", "detection", "segmentation",
             "recognition", "3d", "visual", "scene understanding"),
        ),
        Venue(
            "kdd", "KDD", "conference",
            "Knowledge Discovery and Data Mining: data mining, applied machine "
            "learning at scale, and knowledge discovery from large datasets.",
            ("data mining", "knowledge discovery", "recommendation", "graph mining",
             "scalable", "clustering", "anomaly detection", "time series"),
        ),
        Venue(
            "sigir", "SIGIR", "conference",
            "Information Retrieval: search, ranking, recommendation, and evaluation "
            "of information access systems.",
            ("information retrieval", "search", "ranking", "recommendation",
             "relevance", "query", "evaluation"),
        ),
        Venue(
            "aaai", "AAAI", "conference",
            "Association for the Advancement of Artificial Intelligence: broad "
            "artificial intelligence including learning, reasoning, planning, "
            "knowledge representation, and multi-agent systems.",
            ("artificial intelligence", "machine learning", "reasoning", "planning",
             "knowledge representation", "search", "multi-agent", "constraint"),
        ),
    ]
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def get_venue(slug_or_name: str) -> Venue | None:
    """Resolve a venue by slug or (case/space-insensitive) name; None if unknown."""
    if not slug_or_name:
        return None
    key = slug_or_name.strip().lower()
    if key in VENUES:
        return VENUES[key]
    norm = _slug(slug_or_name)
    for v in VENUES.values():
        if _slug(v.slug) == norm or _slug(v.name) == norm:
            return v
    return None


def list_venues() -> list[Venue]:
    """All registered venues, sorted by slug."""
    return [VENUES[k] for k in sorted(VENUES)]


_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def topic_overlap(paper_terms: list[str], venue: Venue) -> float:
    """Deterministic scope-overlap prefilter in [0, 1].

    Fraction of the venue's topics that appear (as whole multi-word phrases or
    shared tokens) in the paper's terms — title, abstract, concept names, etc.
    Grounds the LLM verdict and lets callers skip an obviously out-of-scope match.
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
