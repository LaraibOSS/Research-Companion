"""Tests for the venue KB, lookup, overlap prefilter, and discipline model."""
from __future__ import annotations

from research_companion.venues import (
    VENUES,
    Venue,
    get_venue,
    infer_discipline,
    list_disciplines,
    list_venues,
    suggest_alternatives,
    topic_overlap,
    venues_for_discipline,
)


class TestRegistry:
    def test_all_venues_have_required_fields(self):
        for v in VENUES.values():
            assert v.slug and v.name and v.scope
            assert v.kind in {"conference", "journal"}
            assert isinstance(v.topics, tuple)
            assert isinstance(v.checklists, tuple)
            assert isinstance(v.desk_reject_rules, tuple)
            assert v.discipline

    def test_kb_is_cross_discipline(self):
        disciplines = set(list_disciplines())
        # CS/ML plus at least biomedical, physics, and a general/multidisciplinary tier.
        assert {"machine_learning", "biomedical", "physics"} <= disciplines
        assert len(disciplines) >= 6

    def test_get_venue_by_slug(self):
        assert get_venue("neurips") is VENUES["neurips"]

    def test_get_venue_by_name_case_insensitive(self):
        assert get_venue("NeurIPS") is VENUES["neurips"]
        assert get_venue("  icml ") is VENUES["icml"]

    def test_get_venue_by_alias(self):
        assert get_venue("nips") is VENUES["neurips"]
        assert get_venue("lancet") is VENUES["the-lancet"]

    def test_get_venue_unknown_is_none(self):
        assert get_venue("does-not-exist") is None
        assert get_venue("") is None

    def test_list_venues_sorted(self):
        slugs = [v.slug for v in list_venues()]
        assert slugs == sorted(slugs)
        assert "neurips" in slugs


class TestDisciplineModel:
    def test_venues_for_discipline(self):
        ml = {v.slug for v in venues_for_discipline("machine_learning")}
        assert {"neurips", "icml", "iclr"} <= ml
        assert "the-lancet" not in ml

    def test_infer_discipline_biomed(self):
        terms = ["A randomized clinical trial in patients with disease"]
        disc, score = infer_discipline(terms)
        assert disc == "biomedical"
        assert score > 0.0

    def test_infer_discipline_ml(self):
        disc, _ = infer_discipline(["deep learning neural network optimization"])
        assert disc == "machine_learning"

    def test_infer_discipline_no_overlap(self):
        disc, score = infer_discipline(["zzzz qqqq"])
        assert disc is None and score == 0.0

    def test_suggest_alternatives_in_discipline(self):
        alts = suggest_alternatives(
            VENUES["neurips"], ["deep learning representation optimization"], limit=2)
        assert len(alts) <= 2
        assert "NeurIPS" not in alts  # excludes the venue itself
        # alternatives are drawn from the same (ML) discipline
        ml_names = {v.name for v in venues_for_discipline("machine_learning")}
        assert all(a in ml_names for a in alts)


class TestTopicOverlap:
    def _v(self):
        return Venue("t", "T", "conference", "scope",
                     ("machine learning", "optimization", "graph"))

    def test_full_overlap(self):
        terms = ["A machine learning method for optimization on a graph"]
        assert topic_overlap(terms, self._v()) == 1.0

    def test_no_overlap(self):
        terms = ["A study of marine biology in coral reefs"]
        assert topic_overlap(terms, self._v()) == 0.0

    def test_partial_overlap(self):
        terms = ["graph algorithms"]
        # only "graph" of the 3 topics -> 1/3
        assert abs(topic_overlap(terms, self._v()) - (1 / 3)) < 1e-9

    def test_multiword_phrase_must_match_as_phrase(self):
        v = Venue("t", "T", "conference", "s", ("machine learning",))
        assert topic_overlap(["machine learning rocks"], v) == 1.0
        # tokens present but not as the phrase
        assert topic_overlap(["a learning machine"], v) == 0.0

    def test_no_topics_is_zero(self):
        v = Venue("t", "T", "conference", "s", ())
        assert topic_overlap(["anything"], v) == 0.0
