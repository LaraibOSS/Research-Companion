"""Shared LLM pricing/cost estimation + the key gate for cost-incurring features.

Extracted from cli.py so the MCP layer can estimate a call's cost without
importing the CLI. Pricing is a coarse per-provider guardrail, not an invoice.

Three kinds of answer:

- a hosted provider has a price;
- ``ollama`` runs on the user's own machine and costs $0;
- ``openai_compatible`` can be anything from a laptop to a paid gateway, so
  its price is NOT KNOWN. ``lookup_pricing`` returns None and
  ``estimate_cost`` returns None for it (unless the call has no tokens at
  all). Callers must show "price not known", never a dollar figure -- and a
  cost cap must not treat an unknown price as $0 (see mcp_tools).
"""
from __future__ import annotations

import os

# provider -> model-prefix -> (input_per_1M, output_per_1M) USD
PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {"default": (3.00, 15.00)},
    "openai":    {"default": (2.50, 10.00)},
    # Local: the user's own hardware. No per-token charge.
    "ollama":    {"default": (0.00, 0.00)},
}

# Providers whose price cannot be known from here.
UNPRICED_PROVIDERS = frozenset({"openai_compatible"})


def lookup_pricing(provider: str) -> tuple[float, float] | None:
    """(input_cost_per_1M, output_cost_per_1M) for *provider*, or None when
    the price is not known (an OpenAI-compatible server). An unrecognised
    provider name falls back to Anthropic rates, as it always has."""
    if provider in UNPRICED_PROVIDERS:
        return None
    bucket = PRICING.get(provider, PRICING["anthropic"])
    return bucket["default"]


def price_known(provider: str) -> bool:
    return lookup_pricing(provider) is not None


def estimate_cost(input_tokens: int, output_tokens: int, provider: str) -> float | None:
    """Estimated USD cost for a call of this size, or None when the price is
    not known. A call with no tokens costs $0 whatever the provider."""
    rates = lookup_pricing(provider)
    if rates is None:
        return 0.0 if input_tokens <= 0 and output_tokens <= 0 else None
    in_rate, out_rate = rates
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


def format_cost(cost: float | None, provider: str) -> str:
    """Human-readable estimate: '~$1.23', or a plain 'price not known' sentence."""
    if cost is None:
        return f"price not known for provider {provider!r}"
    return f"~${cost:,.2f}"


def chars_to_tokens(chars: int) -> int:
    """The repo's standing ~4-chars-per-token heuristic."""
    return max(0, chars) // 4


def configured_provider() -> tuple[str, str | None] | None:
    """(provider, model) when the RESOLVED provider can make a call, else None.

    Resolves the provider from RESEARCH_COMPANION_PROVIDER (default "anthropic").
    A hosted provider requires its MATCHING key env var -- a key for the wrong
    provider does not count, it would only produce a crash at call time. A
    self-hosted provider needs no key but does need a model name (and an
    OpenAI-compatible server a URL); llm.provider_ready is the one rule.
    """
    from research_companion.llm import provider_ready

    provider = (os.environ.get("RESEARCH_COMPANION_PROVIDER", "anthropic").strip().lower()
                or "anthropic")
    model = os.environ.get("RESEARCH_COMPANION_MODEL")
    if not provider_ready(provider, model):
        return None
    return provider, model
