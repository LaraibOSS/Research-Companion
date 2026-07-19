"""Shared cost/pricing helpers + the costed-feature key gate (all offline)."""
from research_companion.cost import (
    chars_to_tokens,
    configured_provider,
    estimate_cost,
    lookup_pricing,
)


def test_estimate_cost_matches_pricing_table():
    # anthropic: (3.00 in, 15.00 out) per 1M
    assert estimate_cost(1_000_000, 0, "anthropic") == 3.00
    assert estimate_cost(0, 1_000_000, "anthropic") == 15.00
    # openai: (2.50, 10.00)
    assert estimate_cost(1_000_000, 1_000_000, "openai") == 12.50
    # unknown provider falls back to anthropic rates
    assert estimate_cost(1_000_000, 0, "nonsense") == 3.00


def test_lookup_pricing_shapes():
    assert lookup_pricing("anthropic") == (3.00, 15.00)
    assert lookup_pricing("openai") == (2.50, 10.00)


def test_chars_to_tokens_heuristic():
    assert chars_to_tokens(4000) == 1000
    assert chars_to_tokens(0) == 0
    assert chars_to_tokens(-5) == 0


def test_configured_provider_matrix(monkeypatch):
    # anthropic (default) + its key -> tuple
    monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)
    monkeypatch.delenv("RESEARCH_COMPANION_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert configured_provider() == ("anthropic", None)

    # anthropic without its key -> None
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert configured_provider() is None

    # provider=openai but only an anthropic key -> None (wrong-provider key doesn't count)
    monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert configured_provider() is None

    # openai + its key + model override -> tuple with model
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oa")
    monkeypatch.setenv("RESEARCH_COMPANION_MODEL", "gpt-x")
    assert configured_provider() == ("openai", "gpt-x")
