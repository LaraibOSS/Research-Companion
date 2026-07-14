"""Deterministic statistical-soundness checking (Statcheck + GRIM).

Recomputes reported null-hypothesis-test p-values from the test statistic and
degrees of freedom, and checks reported means for arithmetic plausibility (GRIM).
Entirely LLM-free and network-free; the only output is a *reporting
inconsistency* — never a claim of error or misconduct.
"""
from research_companion.statcheck.check import check_stats

__all__ = ["check_stats"]
