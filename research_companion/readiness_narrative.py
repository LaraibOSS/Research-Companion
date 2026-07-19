"""Optional LLM narrative over the deterministic submission-readiness verdict.

Consumes ONLY the readiness dict (never the paper or lane internals), so the
model can rephrase and prioritize the existing punch-list but cannot invent
findings. Display-only; any failure degrades to None (no narrative), the
same shape as compare._generate_summary. readiness.py itself stays pure.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable

_TAKE_MAX_CHARS = 800
_PLAN_MAX_ITEMS = 6
_PLAN_ITEM_MAX_CHARS = 300
_MAX_OUTPUT_TOKENS = 1024


def _default_llm(prompt: str) -> str:
    from research_companion.extract import _call_anthropic, _call_openai, resolve_model

    provider = os.environ.get("RESEARCH_COMPANION_PROVIDER", "anthropic")
    model = resolve_model(provider, os.environ.get("RESEARCH_COMPANION_MODEL"))
    if provider == "openai":
        text, _usage = _call_openai(prompt, model=model,
                                    max_output_tokens=_MAX_OUTPUT_TOKENS, json_mode=True)
    else:
        text, _usage = _call_anthropic(prompt, model=model,
                                       max_output_tokens=_MAX_OUTPUT_TOKENS)
    return text


def _parse(raw: str) -> dict:
    from research_companion.extract import _strip_code_fences

    parsed = json.loads(_strip_code_fences(raw))
    if not isinstance(parsed, dict):
        raise ValueError("narrative: LLM returned non-object JSON")
    return parsed


def _validate(parsed: dict) -> dict | None:
    take = parsed.get("take")
    plan = parsed.get("plan")
    if not isinstance(take, str) or not take.strip():
        return None
    if not isinstance(plan, list) or not all(isinstance(s, str) for s in plan):
        return None
    return {
        "take": take.strip()[:_TAKE_MAX_CHARS],
        "plan": [s.strip()[:_PLAN_ITEM_MAX_CHARS]
                 for s in plan if s.strip()][:_PLAN_MAX_ITEMS],
    }


def generate_readiness_narrative(readiness: dict | None, *,
                                 llm: Callable[[str], str] | None = None) -> dict | None:
    """Reviewer's take + prioritized fix plan, or None.

    None when there is nothing to narrate (falsy readiness, or no blockers and
    no warnings — a clean "ready" needs no essay) and on ANY failure: missing
    key, network error, invalid JSON, wrong shape. The llm is never invoked on
    the skip paths.
    """
    if not readiness:
        return None
    if not (readiness.get("blockers") or readiness.get("warnings")):
        return None
    try:
        from research_companion.prompts import format_readiness_narrative_prompt

        prompt = format_readiness_narrative_prompt(readiness)
        raw = (llm or _default_llm)(prompt)
        return _validate(_parse(raw))
    except Exception:
        return None
