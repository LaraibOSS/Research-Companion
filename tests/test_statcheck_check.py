"""End-to-end classification: consistent / inconsistent / decision-flip / GRIM."""
from research_companion.statcheck import check_stats
from research_companion.statcheck.check import _classify


def _one(text):
    findings = check_stats(text)["findings"]
    assert len(findings) == 1, findings
    return findings[0]


def test_consistent_two_tailed():
    f = _one("t(48) = 2.10, p = .04")
    assert f["status"] == "consistent"
    assert f["severity"] == "info"
    assert "assumed two-tailed" in f["assumptions"]
    # provenance preserved
    assert f["char_start"] >= 0 and f["raw"].startswith("t(48)")


def test_consistent_one_tailed_assumption():
    # Two-tailed p ~ .041; one-tailed ~ .020 -> reported .02 is consistent one-tailed.
    f = _one("t(48) = 2.10, p = .02")
    assert f["status"] == "consistent"
    assert "assumed one-tailed" in f["assumptions"]


def test_inconsistent_without_decision_flip():
    # Recomputed ~ .04 (significant); reported .001 also significant -> plain inconsistent.
    f = _one("t(48) = 2.10, p = .001")
    assert f["status"] == "inconsistent"
    assert f["severity"] == "medium"


def test_decision_inconsistent_flips_significance():
    # Recomputed ~ .04 (significant); reported .20 (not significant) -> decision flip.
    f = _one("t(48) = 2.10, p = .20")
    assert f["status"] == "decision_inconsistent"
    assert f["severity"] == "high"


def test_decision_inconsistent_with_inequality():
    # F recomputes to ~ .22 (not significant) but the paper claims p < .05.
    f = _one("F(1, 100) = 1.50, p < .05")
    assert f["status"] == "decision_inconsistent"


def test_f_and_chi2_consistent():
    # F(2,60)=3.15 -> p ~ .05 ; chi2(1)=3.84 -> p ~ .05
    assert _one("F(2, 60) = 3.15, p = .05")["status"] == "consistent"
    assert _one("chi2(1) = 3.84, p = .05")["status"] == "consistent"


def test_grim_impossible_mean_flagged():
    f = _one("Group mean M = 3.43 (SD = 0.8, N = 20).")
    assert f["test_type"] == "mean"
    assert f["status"] == "impossible_mean"
    assert f["severity"] == "high"


def test_summary_counts_and_text():
    text = ("t(48) = 2.10, p = .04. Also t(30) = 2.05, p = .20. "
            "And M = 3.43 (N = 20).")
    rep = check_stats(text)
    s = rep["summary"]
    assert s["n_tests"] == 2
    assert s["n_decision_inconsistent"] == 1
    assert s["n_impossible_means"] == 1
    assert "flip" in s["text"]


def test_empty_and_stat_free_are_non_alarming():
    rep = check_stats("This paper presents a qualitative study with no statistics.")
    assert rep["findings"] == []
    assert rep["summary"]["text"] == "no parseable statistics found"
    assert check_stats("")["summary"]["n_tests"] == 0


def test_classify_is_pure_dict():
    # sanity: _classify returns JSON-safe primitives
    f = _classify({"test_type": "t", "statistic": 2.10, "statistic_str": "2.10",
                   "p_operator": "=", "p_reported": 0.04, "p_reported_str": ".04",
                   "raw": "t(48) = 2.10, p = .04", "char_start": 0, "char_end": 21,
                   "df": 48.0})
    assert isinstance(f["recomputed_p"], float)
    assert f["df"] == 48.0
