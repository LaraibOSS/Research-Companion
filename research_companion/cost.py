"""Shared LLM pricing/cost estimation + the key gate for cost-incurring features.

Extracted from cli.py so the MCP layer can estimate a call's cost without
importing the CLI. Pricing is a coarse per-provider guardrail, not an invoice.
"""
from __future__ import annotations

import os

# provider -> model-prefix -> (input_per_1M, output_per_1M) USD
PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {"default": (3.00, 15.00)},
    "openai":    {"default": (2.50, 10.00)},
}

_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def lookup_pricing(provider: str) -> tuple[float, float]:
    """Return (input_cost_per_1M, output_cost_per_1M) for *provider*."""
    bucket = PRICING.get(provider, PRICING["anthropic"])
    return bucket["default"]


def estimate_cost(input_tokens: int, output_tokens: int, provider: str) -> float:
    """Estimated USD cost for a call of this size."""
    in_rate, out_rate = lookup_pricing(provider)
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


def chars_to_tokens(chars: int) -> int:
    """The repo's standing ~4-chars-per-token heuristic."""
    return max(0, chars) // 4


def configured_provider() -> tuple[str, str | None] | None:
    """(provider, model) when an LLM key exists for the RESOLVED provider, else None.

    Resolves the provider from RESEARCH_COMPANION_PROVIDER (default "anthropic")
    and requires the MATCHING key env var. A key for the wrong provider does not
    count — it would only produce a crash at call time.
    """
    provider = os.environ.get("RESEARCH_COMPANION_PROVIDER", "anthropic")
    key_env = _KEY_ENV.get(provider)
    if not key_env or not os.environ.get(key_env):
        return None
    return provider, os.environ.get("RESEARCH_COMPANION_MODEL")
