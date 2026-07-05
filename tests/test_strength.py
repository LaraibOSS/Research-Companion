"""Tests for research_companion.strength — paper strength scoring."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from research_companion import store
from research_companion.strength import compute_strength, strength_for_paper


# Test data: extraction completeness
@pytest.mark.parametrize(
    "extraction,expected_value,expected_available",
    [
        # Full extraction (all 6 keys present and non-empty)
        (
            {
                "concepts": [{"name": "test"}],
                "methods": [{"name": "test"}],
                "datasets": [{"name": "test"}],
                "claims": [{"text": "test"}],
                "results": [{"metric": "test"}],
                "related_work": ["ref"],
            },
            1.0,
            True,
        ),
        # Half empty (3 of 6 keys have content)
        (
            {
                "concepts": [{"name": "test"}],
                "methods": [{"name": "test"}],
                "datasets": [{"name": "test"}],
                "claims": [],
                "results": [],
                "related_work": [],
            },
            0.5,
            True,
        ),
        # No extraction
        (None, None, False),
        # Empty extraction dict — available (extraction is not None), value 0.0
        ({}, 0.0, True),
        # Extraction with only empty lists
        (
            {
                "concepts": [],
                "methods": [],
                "datasets": [],
                "claims": [],
                "results": [],
                "related_work": [],
            },
            0.0,
            True,
        ),
    ],
)
def test_compute_strength_extraction_completeness(
    extraction, expected_value, expected_available
):
    """Test extraction_completeness signal availability and value."""
    result = compute_strength(
        extraction=extraction, refcheck=None, alignment=None, year=None, now_year=2024
    )
    sig = result["signals"]["extraction_completeness"]
    assert sig["available"] == expected_available
    if expected_available:
        assert sig["value"] == expected_value
    else:
        assert sig["value"] is None


@pytest.mark.parametrize(
    "refcheck,expected_value,expected_available",
    [
        # Valid refcheck: 8 verified out of 10 total -> 0.8
        ({"verified": 8, "total": 10}, 0.8, True),
        # All verified
        ({"verified": 10, "total": 10}, 1.0, True),
        # None verified
        ({"verified": 0, "total": 10}, 0.0, True),
        # Total is 0 -> unavailable
        ({"verified": 5, "total": 0}, None, False),
        # No refcheck
        (None, None, False),
        # Missing keys
        ({}, None, False),
    ],
)
def test_compute_strength_citation_health(refcheck, expected_value, expected_available):
    """Test citation_health signal availability and value."""
    result = compute_strength(
        extraction=None, refcheck=refcheck, alignment=None, year=None, now_year=2024
    )
    sig = result["signals"]["citation_health"]
    assert sig["available"] == expected_available
    if expected_available:
        assert sig["value"] == expected_value
    else:
        assert sig["value"] is None


@pytest.mark.parametrize(
    "alignment,expected_value,expected_available",
    [
        # Valid alignment with score
        ({"score": 0.75}, 0.75, True),
        # Score of 0
        ({"score": 0.0}, 0.0, True),
        # Score of 1
        ({"score": 1.0}, 1.0, True),
        # Missing score key
        ({}, None, False),
        # No alignment
        (None, None, False),
    ],
)
def test_compute_strength_alignment(alignment, expected_value, expected_available):
    """Test alignment signal availability and value."""
    result = compute_strength(
        extraction=None, refcheck=None, alignment=alignment, year=None, now_year=2024
    )
    sig = result["signals"]["alignment"]
    assert sig["available"] == expected_available
    if expected_available:
        assert sig["value"] == expected_value
    else:
        assert sig["value"] is None


@pytest.mark.parametrize(
    "year,now_year,expected_value",
    [
        # Within 2 years -> 1.0
        (2024, 2024, 1.0),
        (2023, 2024, 1.0),
        (2022, 2024, 1.0),  # Exactly at now_year - 2
        # Linear interpolation from 1.0 at (now-2) to 0.2 at (now-10)
        # (now - 2 - year) = diff; value = max(0.2, min(1.0, 1.0 - 0.8 * (diff / 8)))
        (2021, 2024, 0.9),  # diff=1: 1.0 - 0.8 * (1/8) = 0.9
        (2020, 2024, 0.8),  # diff=2: 1.0 - 0.8 * (2/8) = 0.8
        (2018, 2024, 0.6),  # diff=4: 1.0 - 0.8 * (4/8) = 0.6
        (2016, 2024, 0.4),  # diff=6: 1.0 - 0.8 * (6/8) = 0.4
        (2014, 2024, 0.2),  # diff=8: 1.0 - 0.8 * (8/8) = 0.2
        # Below now-10 -> clamped to 0.2
        (2013, 2024, 0.2),  # diff=9: unclamped would be 0.1
        (2000, 2024, 0.2),  # far in past
        # No year -> unavailable
        (None, 2024, None),
    ],
)
def test_compute_strength_recency(year, now_year, expected_value):
    """Test recency signal boundaries and linear interpolation."""
    result = compute_strength(
        extraction=None, refcheck=None, alignment=None, year=year, now_year=now_year
    )
    sig = result["signals"]["recency"]
    if expected_value is None:
        assert not sig["available"]
        assert sig["value"] is None
    else:
        assert sig["available"]
        assert abs(sig["value"] - expected_value) < 1e-6


def test_compute_strength_renormalization():
    """Test weight renormalization when only some signals available.

    Only extraction (weight 0.30) and recency (weight 0.20) available.
    extraction=1.0, recency=0.5
    Score = (0.30*1.0 + 0.20*0.5) / (0.30+0.20) = 0.7 / 0.50 = 0.8
    """
    # For recency=0.5: 1.0 - 0.8 * (diff/8) = 0.5 => diff = 5
    # now_year - 2 - year = 5 => year = now_year - 7
    result = compute_strength(
        extraction={
            "concepts": [{"name": "test"}],
            "methods": [{"name": "test"}],
            "datasets": [{"name": "test"}],
            "claims": [{"name": "test"}],
            "results": [{"name": "test"}],
            "related_work": ["test"],
        },
        refcheck=None,
        alignment=None,
        year=2017,  # 2024 - 7 = 2017, now_year - 2 - year = 2024 - 2 - 2017 = 5
        now_year=2024,
    )
    # extraction=1.0 (w=0.30), recency=0.5 (w=0.20)
    sig_ext = result["signals"]["extraction_completeness"]
    sig_rec = result["signals"]["recency"]
    assert sig_ext["available"]
    assert sig_ext["value"] == 1.0
    assert sig_rec["available"]
    assert abs(sig_rec["value"] - 0.5) < 1e-6

    # Check renormalization: score = (0.30 * 1.0 + 0.20 * 0.5) / 0.50 = 0.8
    assert abs(result["score"] - 0.8) < 1e-6


def test_compute_strength_fewer_than_2_signals():
    """Test unscored when < 2 signals available."""
    # Only extraction available
    result = compute_strength(
        extraction={
            "concepts": [{"name": "test"}],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        },
        refcheck=None,
        alignment=None,
        year=None,
        now_year=2024,
    )
    assert result["score"] is None
    assert result["band"] == "unscored"
    assert result["color"] == "#8b949e"

    # No signals available
    result = compute_strength(
        extraction=None,
        refcheck=None,
        alignment=None,
        year=None,
        now_year=2024,
    )
    assert result["score"] is None
    assert result["band"] == "unscored"
    assert result["color"] == "#8b949e"


@pytest.mark.parametrize(
    "score_target,expected_band,expected_color",
    [
        (0.65, "strong", "#3fb950"),
        (0.6499, "moderate", "#d29922"),
        (0.40, "moderate", "#d29922"),
        (0.399, "weak", "#f0883e"),
    ],
)
def test_compute_strength_band_boundaries(score_target, expected_band, expected_color):
    """Test band/color assignment at exact boundary values.

    Use only alignment (weight 0.25) + citation_health (weight 0.25) with equal
    values both set to score_target.  Renorm = (0.25*t + 0.25*t) / (0.25+0.25) = t
    exactly, so the renormalized score equals score_target with no rounding error.
    Exactly 2 signals are available so the result is never unscored.
    """
    # verified = int(score_target * 10000), total = 10000 keeps the ratio exact.
    verified = int(score_target * 10000)
    result = compute_strength(
        extraction=None,
        refcheck={"verified": verified, "total": 10000},
        alignment={"score": score_target},
        year=None,
        now_year=2024,
    )
    assert result["band"] == expected_band, (
        f"score_target={score_target}: expected band={expected_band!r}, "
        f"got band={result['band']!r} (score={result['score']})"
    )
    assert result["color"] == expected_color


def test_compute_strength_return_shape():
    """Test exact return shape with all four signals present."""
    result = compute_strength(
        extraction={
            "concepts": [{"name": "test"}],
            "methods": [{"name": "test"}],
            "datasets": [{"name": "test"}],
            "claims": [{"name": "test"}],
            "results": [{"name": "test"}],
            "related_work": ["test"],
        },
        refcheck={"verified": 8, "total": 10},
        alignment={"score": 0.75},
        year=2020,
        now_year=2024,
    )

    # Check top-level keys
    assert "version" in result
    assert result["version"] == 1
    assert "score" in result
    assert "band" in result
    assert "color" in result
    assert "signals" in result
    assert "computed_at" in result

    # score should be a float rounded to 4 dp or None
    assert isinstance(result["score"], (float, type(None)))
    if result["score"] is not None:
        # Check it's rounded to 4 dp: convert to string and check
        score_str = f"{result['score']:.4f}"
        assert len(score_str.split(".")[1]) <= 4

    # band and color are strings
    assert isinstance(result["band"], str)
    assert isinstance(result["color"], str)

    # signals dict has exactly 4 keys
    assert len(result["signals"]) == 4
    assert set(result["signals"].keys()) == {
        "extraction_completeness",
        "citation_health",
        "alignment",
        "recency",
    }

    # Each signal has value, weight, available
    for _name, sig in result["signals"].items():
        assert "value" in sig
        assert "weight" in sig
        assert "available" in sig
        assert isinstance(sig["weight"], (int, float))
        assert isinstance(sig["available"], bool)
        assert isinstance(sig["value"], (float, type(None)))

    # computed_at is ISO datetime string
    assert isinstance(result["computed_at"], str)
    # Try to parse it
    datetime.fromisoformat(result["computed_at"].replace("Z", "+00:00"))


def test_compute_strength_score_rounding():
    """Test that score is rounded to exactly 4 decimal places.

    extraction = 1/6 ≈ 0.16666..., refcheck = 7/10 = 0.7
    renorm: (0.30 * 1/6 + 0.25 * 0.7) / (0.30 + 0.25)
          = (0.05 + 0.175) / 0.55
          = 0.225 / 0.55
          = 0.40909090...
    Rounded to 4 dp: 0.4091
    """
    result = compute_strength(
        extraction={
            "concepts": [{"name": "a"}],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        },  # 1/6 ≈ 0.16666...
        refcheck={"verified": 7, "total": 10},  # 0.7
        alignment=None,
        year=None,
        now_year=2024,
    )
    assert result["score"] == 0.4091


def test_strength_for_paper_unknown_paper(tmp_path):
    """Test strength_for_paper raises ValueError for unknown paper."""
    with patch.dict("os.environ", {"RESEARCH_COMPANION_DIR": str(tmp_path)}), pytest.raises(ValueError, match="Unknown paper_id"):
        strength_for_paper("arxiv:9999.99999")


def test_strength_for_paper_persists(tmp_path):
    """Test strength_for_paper persists result via store.save_strength."""
    with patch.dict("os.environ", {"RESEARCH_COMPANION_DIR": str(tmp_path)}):
        paper_id = "arxiv:2410.05779"
        meta = store.PaperMetadata(
            paper_id=paper_id,
            title="Test Paper",
            authors=["Author"],
            year=2023,
        )
        meta.save()

        extraction = {
            "concepts": [{"name": "test"}],
            "methods": [{"name": "test"}],
            "datasets": [{"name": "test"}],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        store.save_extraction(paper_id, extraction, prompt_sha="test_sha")

        with patch(
            "research_companion.strength.load_extraction_for_paper"
        ) as mock_load_ext:
            mock_load_ext.return_value = extraction
            with patch(
                "research_companion.strength.store.get_draft_paper_id",
                return_value=None,
            ):
                result = strength_for_paper(paper_id, refcheck=None, now_year=2024)

        # Verify it was persisted
        loaded = store.load_strength(paper_id)
        assert loaded is not None
        assert loaded["score"] == result["score"]
        assert loaded["band"] == result["band"]


def test_compute_strength_all_signals_unavailable():
    """Test when all 4 signals are unavailable."""
    result = compute_strength(
        extraction=None,
        refcheck=None,
        alignment=None,
        year=None,
        now_year=2024,
    )
    assert result["score"] is None
    assert result["band"] == "unscored"
    assert result["color"] == "#8b949e"
    # Verify all signals show as unavailable
    for sig in result["signals"].values():
        assert not sig["available"]


def test_compute_strength_exactly_2_signals():
    """Test with exactly 2 signals available (minimum for scoring)."""
    result = compute_strength(
        extraction={
            "concepts": [{"name": "test"}],
            "methods": [{"name": "test"}],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        },  # 2/6 = 0.333...
        refcheck={"verified": 5, "total": 10},  # 0.5
        alignment=None,
        year=None,
        now_year=2024,
    )
    assert result["score"] is not None
    assert result["band"] != "unscored"
    # Check: (0.30 * 1/3 + 0.25 * 0.5) / 0.55 = (0.1 + 0.125) / 0.55 ≈ 0.409
    expected_score = (0.30 * (2 / 6) + 0.25 * 0.5) / 0.55
    assert abs(result["score"] - expected_score) < 1e-3


def test_compute_strength_exactly_1_signal_unavailable():
    """Test with 3 signals available (just above minimum)."""
    result = compute_strength(
        extraction={
            "concepts": [{"name": "test"}],
            "methods": [{"name": "test"}],
            "datasets": [{"name": "test"}],
            "claims": [{"name": "test"}],
            "results": [{"name": "test"}],
            "related_work": ["test"],
        },  # 6/6 = 1.0
        refcheck={"verified": 8, "total": 10},  # 0.8
        alignment={"score": 0.9},
        year=None,  # recency unavailable
        now_year=2024,
    )
    assert result["score"] is not None
    assert result["band"] == "strong"  # High score expected


def test_compute_strength_extreme_recency():
    """Test recency at extreme boundaries."""
    # Year far in future (beyond now_year)
    result = compute_strength(
        extraction={
            "concepts": [{"name": "test"}],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        },
        refcheck=None,
        alignment=None,
        year=2050,
        now_year=2024,
    )
    # Should still return 1.0 for future year
    assert result["signals"]["recency"]["value"] == 1.0


def test_compute_strength_negative_year():
    """Test with negative year (very old paper)."""
    result = compute_strength(
        extraction={
            "concepts": [{"name": "test"}],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        },
        refcheck=None,
        alignment=None,
        year=-500,
        now_year=2024,
    )
    # Should clamp to 0.2
    assert result["signals"]["recency"]["value"] == 0.2


def test_strength_for_paper_with_draft_self(isolated_papergraph_dir):
    """Test that draft paper does not consume its own alignment.

    Uses isolated_papergraph_dir to prevent writes to the real ~/.research-companion.
    store.save_strength is also mocked so the test is fully unit-isolated.
    """
    with patch("research_companion.strength.PaperMetadata.load") as mock_load_meta:
        mock_meta = MagicMock()
        mock_meta.year = 2020
        mock_load_meta.return_value = mock_meta

        with patch(
            "research_companion.strength.load_extraction_for_paper"
        ) as mock_load_ext:
            mock_load_ext.return_value = {
                "concepts": [{"name": "test"}],
                "methods": [],
                "datasets": [],
                "claims": [],
                "results": [],
                "related_work": [],
            }

            with patch(
                "research_companion.strength.store.get_draft_paper_id"
            ) as mock_get_draft:
                mock_get_draft.return_value = "arxiv:2410.05779"

                with patch(
                    "research_companion.strength.store.load_alignment"
                ) as mock_load_align, patch(
                    "research_companion.strength.store.save_strength"
                ) as mock_save:
                    # This should NOT be called since paper_id == draft_paper_id
                    strength_for_paper("arxiv:2410.05779")

                    mock_load_align.assert_not_called()
                    mock_save.assert_called_once()


def test_compute_strength_refcheck_with_missing_verified():
    """Test refcheck dict that has total but missing verified key."""
    result = compute_strength(
        extraction=None,
        refcheck={"total": 10},  # Missing "verified"
        alignment=None,
        year=None,
        now_year=2024,
    )
    sig = result["signals"]["citation_health"]
    assert sig["available"]
    assert sig["value"] == 0.0  # Missing verified treated as 0


def test_compute_strength_all_four_signals_perfect():
    """Test all four signals with perfect values."""
    result = compute_strength(
        extraction={
            "concepts": [{"name": "test"}],
            "methods": [{"name": "test"}],
            "datasets": [{"name": "test"}],
            "claims": [{"name": "test"}],
            "results": [{"name": "test"}],
            "related_work": ["test"],
        },  # 1.0
        refcheck={"verified": 100, "total": 100},  # 1.0
        alignment={"score": 1.0},
        year=2024,  # 1.0
        now_year=2024,
    )
    # All signals = 1.0, so score should be 1.0
    assert result["score"] == 1.0
    assert result["band"] == "strong"
    assert result["color"] == "#3fb950"


def test_compute_strength_all_four_signals_zero():
    """Test all four signals with zero values but available."""
    result = compute_strength(
        extraction={
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        },  # 0.0
        refcheck={"verified": 0, "total": 10},  # 0.0
        alignment={"score": 0.0},
        year=2000,  # 0.2
        now_year=2024,
    )
    # Score should be weighted average of 0.0, 0.0, 0.0, 0.2
    expected = (0.30 * 0.0 + 0.25 * 0.0 + 0.25 * 0.0 + 0.20 * 0.2) / 1.0
    assert abs(result["score"] - expected) < 1e-6
    assert result["band"] == "weak"
    assert result["color"] == "#f0883e"
