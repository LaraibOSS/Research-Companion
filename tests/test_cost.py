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


def test_local_ollama_costs_nothing():
    assert lookup_pricing("ollama") == (0.0, 0.0)
    assert estimate_cost(1_000_000, 1_000_000, "ollama") == 0.0


def test_unpriced_provider_is_unknown_not_zero():
    from research_companion.cost import format_cost, price_known
    assert lookup_pricing("openai_compatible") is None
    assert price_known("openai_compatible") is False
    assert estimate_cost(1000, 1000, "openai_compatible") is None
    # ...but a call with no tokens costs nothing whatever the price.
    assert estimate_cost(0, 0, "openai_compatible") == 0.0
    assert format_cost(None, "openai_compatible") == \
        "price not known for provider 'openai_compatible'"
    assert format_cost(1.234, "anthropic") == "~$1.23"


def test_configured_provider_self_hosted(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "RESEARCH_COMPANION_API_KEY",
                "RESEARCH_COMPANION_BASE_URL", "RESEARCH_COMPANION_MODEL"):
        monkeypatch.delenv(var, raising=False)
    # Ollama: no key needed, but a model is.
    monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "ollama")
    assert configured_provider() is None
    monkeypatch.setenv("RESEARCH_COMPANION_MODEL", "llama3.1:8b")
    assert configured_provider() == ("ollama", "llama3.1:8b")
    # OpenAI-compatible: key optional, server URL required.
    monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai_compatible")
    assert configured_provider() is None
    monkeypatch.setenv("RESEARCH_COMPANION_BASE_URL", "http://localhost:8000/v1")
    assert configured_provider() == ("openai_compatible", "llama3.1:8b")
