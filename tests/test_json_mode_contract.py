"""OpenAI's JSON-object response format has a hard precondition.

`response_format={"type": "json_object"}` is rejected with HTTP 400 unless the
messages contain the word "json". A prose prompt routed through JSON mode
therefore does not merely produce odd output — it fails the entire request.

That shipped: the Report resolved ONE json-mode model and used it for both
question generation (JSON, correct) and answering (prose, broken), so every
report answer died with:

    'messages' must contain the word 'json' ... to use 'response_format'
"""
from __future__ import annotations

import research_companion.prompts as P
from research_companion.extract import _openai_request_kwargs

#: Prompts that intentionally produce PROSE. They must never be sent in JSON
#: mode. Listed explicitly so adding a prose prompt is a deliberate act.
PROSE_PROMPTS = {
    "QA_PROMPT",
    "CHAT_SYSTEM_PROMPT",
    "CHAT_USER_PROMPT",
    "COMPARE_PROMPT",
}


def _prompt_names() -> list[str]:
    return [n for n in dir(P) if n.endswith("_PROMPT") and isinstance(getattr(P, n), str)]


def test_every_json_contract_prompt_contains_the_word_json():
    """Any prompt that is not explicitly prose is used under json_mode, so it
    must satisfy OpenAI's precondition."""
    offenders = [
        name for name in _prompt_names()
        if name not in PROSE_PROMPTS and "json" not in getattr(P, name).lower()
    ]
    assert not offenders, (
        f"these prompts are used in JSON mode but never say 'json', so OpenAI "
        f"rejects the request with HTTP 400: {offenders}"
    )


def test_prose_prompts_are_still_prose():
    """If one of these grows a JSON contract it should leave the prose list —
    otherwise the guard below silently stops protecting it."""
    for name in PROSE_PROMPTS:
        assert hasattr(P, name), f"{name} no longer exists; update PROSE_PROMPTS"
        assert "json" not in getattr(P, name).lower(), (
            f"{name} now mentions json — either it became a JSON prompt (remove "
            "it from PROSE_PROMPTS) or the wording needs care"
        )


def test_json_mode_is_dropped_when_the_prompt_cannot_satisfy_the_api():
    """The safety net: a prose prompt in JSON mode degrades to a working prose
    call instead of a 400 that kills the whole request."""
    prose = _openai_request_kwargs(model="m", max_output_tokens=10,
                                   json_mode=True, prompt=P.QA_PROMPT)
    assert "response_format" not in prose

    contract = _openai_request_kwargs(model="m", max_output_tokens=10,
                                      json_mode=True, prompt=P.EXTRACTION_PROMPT)
    assert contract["response_format"] == {"type": "json_object"}


def test_guard_preserves_behaviour_for_callers_that_pass_no_prompt():
    kwargs = _openai_request_kwargs(model="m", max_output_tokens=10, json_mode=True)
    assert kwargs["response_format"] == {"type": "json_object"}
    off = _openai_request_kwargs(model="m", max_output_tokens=10, json_mode=False)
    assert "response_format" not in off


def test_report_answering_uses_a_prose_model_not_a_json_one():
    """The actual regression: the report's answer path must resolve json_mode
    False, separately from its question-generation path."""
    import pathlib

    src = pathlib.Path("research_companion/lab_api.py").read_text(encoding="utf-8")
    assert "answer_llm = app.state.llm" in src
    assert "_resolve_llm(json_mode=False)" in src
    assert "qa_answer_fn(q, llm=answer_llm" in src
