"""Extraction of NHST reports and GRIM means across reporting styles."""
from research_companion.statcheck.extract import extract_means, extract_stat_tests


def test_extract_t_test_with_provenance():
    text = "The effect was significant, t(48) = 2.10, p = .04, indicating support."
    got = extract_stat_tests(text)
    assert len(got) == 1
    f = got[0]
    assert f["test_type"] == "t"
    assert f["df"] == 48.0
    assert f["statistic"] == 2.10
    assert f["p_operator"] == "="
    assert f["p_reported"] == 0.04
    # provenance: offsets slice back to the raw report
    assert text[f["char_start"]:f["char_end"]] == f["raw"]
    assert f["raw"].startswith("t(48)")


def test_extract_f_test():
    got = extract_stat_tests("A one-way ANOVA, F(2, 60) = 3.50, p < .05.")
    assert len(got) == 1
    f = got[0]
    assert f["test_type"] == "F"
    assert f["df1"] == 2.0 and f["df2"] == 60.0
    assert f["statistic"] == 3.50
    assert f["p_operator"] == "<"
    assert f["p_reported"] == 0.05


def test_extract_chi2_variants():
    for src in ["χ²(1, N = 90) = 4.20, p = .04",
                "chi2(1) = 4.20, p = .04",
                "X2(1) = 4.20, p = .04"]:
        got = extract_stat_tests(src)
        assert len(got) == 1, src
        assert got[0]["test_type"] == "chi2"
        assert got[0]["df"] == 1.0
        assert got[0]["statistic"] == 4.20


def test_extract_r_and_z():
    got = extract_stat_tests("A correlation r(28) = 0.55, p = .002 and z = 1.98, p = .048.")
    types = {g["test_type"] for g in got}
    assert "r" in types and "z" in types


def test_extract_multiple_and_sorted():
    text = "First t(10) = 2.23, p = .05. Then F(1, 20) = 4.35, p = .05."
    got = extract_stat_tests(text)
    assert [g["test_type"] for g in got] == ["t", "F"]
    assert got[0]["char_start"] < got[1]["char_start"]


def test_no_false_matches_on_prose():
    assert extract_stat_tests("We tested the hypothesis and found support.") == []
    assert extract_stat_tests("") == []


def test_extract_means_ties_to_n():
    got = extract_means("The group scored M = 3.45 (SD = 0.8, N = 20) overall.")
    assert len(got) == 1
    assert got[0]["mean"] == 3.45
    assert got[0]["n"] == 20


def test_extract_means_requires_nearby_n():
    # No N within the window -> not paired (conservative).
    assert extract_means("The mean was M = 3.45. Much later, N = 20 papers.") == []
