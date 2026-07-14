"""Tests for the venue registry + deterministic overlap prefilter."""
from __future__ import annotations

from research_companion.venues import (
    VENUES,
    Venue,
    get_venue,
    list_venues,
    topic_overlap,
)


class TestRegistry:
    def test_all_venues_have_required_fields(self):
        for v in VENUES.values():
            assert v.slug and v.name and v.scope
            assert v.kind in {"conference", "journal"}
            assert isinstance(v.topics, tuple)

    def test_get_venue_by_slug(self):
        assert get_venue("neurips") is VENUES["neurips"]

    def test_get_venue_by_name_case_insensitive(self):
        assert get_venue("NeurIPS") is VENUES["neurips"]
        assert get_venue("  icml ") is VENUES["icml"]

    def test_get_venue_unknown_is_none(self):
        assert get_venue("does-not-exist") is None
        assert get_venue("") is None

    def test_list_venues_sorted(self):
        slugs = [v.slug for v in list_venues()]
        assert slugs == sorted(slugs)
        assert "neurips" in slugs


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
