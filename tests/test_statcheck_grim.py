"""GRIM arithmetic-plausibility checks."""
from research_companion.statcheck.grim import count_decimals, grim_possible


def test_count_decimals():
    assert count_decimals("3.45") == 2
    assert count_decimals("3.4") == 1
    assert count_decimals("3") == 0
    assert count_decimals("3.400") == 3


def test_grim_possible_true():
    # 69/20 = 3.45 exactly -> possible.
    assert grim_possible("3.45", 20) is True
    # 3.40 = 68/20 -> possible.
    assert grim_possible("3.40", 20) is True


def test_grim_impossible():
    # With N=20 the granularity is 0.05; 3.43 is not within half a rounding unit
    # of any k/20, so it is arithmetically impossible.
    assert grim_possible("3.43", 20) is False
    # N=7 -> granularity ~0.1428; 2.20 is not reachable to 2 decimals.
    assert grim_possible("2.20", 7) is False


def test_grim_large_n_always_possible():
    # When 1/N is finer than the rounding unit, any value is reachable.
    assert grim_possible("3.43", 1000) is True


def test_grim_guards_bad_n():
    assert grim_possible("3.45", 0) is True
