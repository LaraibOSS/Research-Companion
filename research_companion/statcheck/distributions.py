"""Self-contained tail probabilities for the NHST distributions (t, F, chi2, z).

No SciPy / NumPy dependency: everything is built from the standard library
``math`` module via the regularized incomplete beta and gamma functions
(Numerical-Recipes style), so the statistical-soundness checker is always
available and its results are fully reproducible. Accuracy is validated against
known critical values in ``tests/test_statcheck_distributions.py``.

All functions return an upper-tail / two-tailed **p-value** in ``[0, 1]``.
"""
from __future__ import annotations

import math

_EPS = 3.0e-12
_FPMIN = 1.0e-300


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b) in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _gser(a: float, x: float) -> float:
    """Lower regularized incomplete gamma P(a, x) via series expansion."""
    if x <= 0.0:
        return 0.0
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(1000):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a: float, x: float) -> float:
    """Upper regularized incomplete gamma Q(a, x) via continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = b + an / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gammq(a: float, x: float) -> float:
    """Upper-tail regularized incomplete gamma Q(a, x) = 1 - P(a, x)."""
    if x <= 0.0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gser(a, x)
    return _gcf(a, x)


# --- Public tail probabilities ---------------------------------------------

def normal_two_tailed(z: float) -> float:
    """Two-tailed p-value for a standard-normal z statistic."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def t_two_tailed(t: float, df: float) -> float:
    """Two-tailed p-value P(|T| >= |t|) for Student's t with df degrees."""
    if df <= 0:
        raise ValueError("t distribution requires df > 0")
    x = df / (df + t * t)
    return betai(df / 2.0, 0.5, x)


def f_pvalue(f: float, df1: float, df2: float) -> float:
    """Upper-tail p-value P(F >= f) for an F statistic with (df1, df2)."""
    if f < 0:
        return 1.0
    if df1 <= 0 or df2 <= 0:
        raise ValueError("F distribution requires df1 > 0 and df2 > 0")
    x = df2 / (df2 + df1 * f)
    return betai(df2 / 2.0, df1 / 2.0, x)


def chi2_pvalue(x2: float, df: float) -> float:
    """Upper-tail p-value P(chi2 >= x2) for a chi-square statistic with df."""
    if x2 < 0:
        return 1.0
    if df <= 0:
        raise ValueError("chi2 distribution requires df > 0")
    return gammq(df / 2.0, x2 / 2.0)


def r_two_tailed(r: float, df: float) -> float:
    """Two-tailed p-value for a Pearson correlation r with df = N - 2."""
    if df <= 0:
        raise ValueError("correlation test requires df > 0")
    if abs(r) >= 1.0:
        return 0.0
    t = r * math.sqrt(df / (1.0 - r * r))
    return t_two_tailed(t, df)
