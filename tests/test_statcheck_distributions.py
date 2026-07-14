"""Validate the self-contained NHST distributions against known values.

Critical values are the standard alpha=.05 two-tailed / upper-tail points from
statistical tables; recomputing their p-value must return ~.05.
"""
import pytest

from research_companion.statcheck import distributions as d


def test_normal_two_tailed_known_values():
    assert d.normal_two_tailed(1.959964) == pytest.approx(0.05, abs=1e-4)
    assert d.normal_two_tailed(1.0) == pytest.approx(0.317310, abs=1e-5)
    assert d.normal_two_tailed(2.575829) == pytest.approx(0.01, abs=1e-4)
    assert d.normal_two_tailed(0.0) == pytest.approx(1.0, abs=1e-9)


def test_t_two_tailed_critical_values():
    # df -> two-tailed .05 critical t value
    for df, tcrit in [(10, 2.228139), (20, 2.085963), (30, 2.042272), (60, 2.000298)]:
        assert d.t_two_tailed(tcrit, df) == pytest.approx(0.05, abs=1e-4)
    # Large df approaches the normal.
    assert d.t_two_tailed(1.959964, 1_000_000) == pytest.approx(0.05, abs=1e-3)


def test_chi2_upper_tail_critical_values():
    # df -> upper-tail .05 critical chi2 value
    for df, xcrit in [(1, 3.841459), (2, 5.991465), (3, 7.814728), (10, 18.307038)]:
        assert d.chi2_pvalue(xcrit, df) == pytest.approx(0.05, abs=1e-4)
    # chi2 with df=1 is z^2: P(chi2_1 > 1) == P(|Z| > 1).
    assert d.chi2_pvalue(1.0, 1) == pytest.approx(0.317310, abs=1e-5)


def test_f_upper_tail_critical_values():
    # (df1, df2) -> upper-tail .05 critical F value
    for df1, df2, fcrit in [(1, 10, 4.964603), (3, 12, 3.490295), (2, 60, 3.150411)]:
        assert d.f_pvalue(fcrit, df1, df2) == pytest.approx(0.05, abs=1e-4)


def test_r_two_tailed_critical_value():
    # N=20 -> df=18; two-tailed .05 critical r is 0.4438.
    assert d.r_two_tailed(0.4438, 18) == pytest.approx(0.05, abs=1e-3)


def test_p_values_are_bounded_and_monotone():
    assert 0.0 <= d.t_two_tailed(0.5, 12) <= 1.0
    # Larger statistic -> smaller p (more significant).
    assert d.t_two_tailed(3.0, 12) < d.t_two_tailed(1.0, 12)
    assert d.f_pvalue(10.0, 2, 20) < d.f_pvalue(1.0, 2, 20)
    assert d.chi2_pvalue(20.0, 3) < d.chi2_pvalue(2.0, 3)


def test_invalid_df_raises():
    with pytest.raises(ValueError):
        d.t_two_tailed(2.0, 0)
    with pytest.raises(ValueError):
        d.chi2_pvalue(3.0, 0)
    with pytest.raises(ValueError):
        d.f_pvalue(3.0, 0, 10)
