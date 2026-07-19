"""Readiness narrative — pure generation over an injected fake LLM (offline)."""
import json

from research_companion.readiness_narrative import generate_readiness_narrative

READINESS = {
    "verdict": "revise",
    "blockers": [{"lane": "compliance", "severity": "blocker",
                  "title": "no limitations section detected",
                  "action": "add a Limitations section"}],
    "warnings": [{"lane": "citation", "severity": "warning",
                  "title": "3 unverified references",
                  "action": "verify or replace 3 references"}],
    "coverage": {"ran": ["citation", "compliance"], "not_run": [], "failed": []},
    "summary": "revise before submitting — 1 desk-reject risk, 1 warning",
}

GOOD = json.dumps({"take": "Solid draft, but fix the desk-reject risk first.",
                   "plan": ["Add a Limitations section",
                            "Verify or replace the 3 unverified references"]})


def test_valid_json_yields_take_and_plan():
    out = generate_readiness_narrative(READINESS, llm=lambda p: GOOD)
    assert out == {"take": "Solid draft, but fix the desk-reject risk first.",
                   "plan": ["Add a Limitations section",
                            "Verify or replace the 3 unverified references"]}


def test_code_fenced_json_is_parsed():
    out = generate_readiness_narrative(READINESS, llm=lambda p: f"```json\n{GOOD}\n```")
    assert out is not None and out["plan"]


def test_bad_json_and_raising_llm_yield_none():
    assert generate_readiness_narrative(READINESS, llm=lambda p: "not json") is None

    def _boom(p):
        raise RuntimeError("no api key")
    assert generate_readiness_narrative(READINESS, llm=_boom) is None


def test_missing_or_wrong_shape_yields_none():
    assert generate_readiness_narrative(
        READINESS, llm=lambda p: json.dumps({"plan": ["x"]})) is None       # no take
    assert generate_readiness_narrative(
        READINESS, llm=lambda p: json.dumps({"take": "", "plan": []})) is None   # empty take
    assert generate_readiness_narrative(
        READINESS, llm=lambda p: json.dumps({"take": "t", "plan": "not-a-list"})) is None
    assert generate_readiness_narrative(
        READINESS, llm=lambda p: json.dumps(["not", "a", "dict"])) is None


def test_caps_enforced():
    huge = json.dumps({"take": "x" * 5000,
                       "plan": [f"step {i} " + "y" * 1000 for i in range(20)]})
    out = generate_readiness_narrative(READINESS, llm=lambda p: huge)
    assert len(out["take"]) == 800
    assert len(out["plan"]) == 6
    assert all(len(s) <= 300 for s in out["plan"])


def test_empty_plan_is_allowed():
    out = generate_readiness_narrative(
        READINESS, llm=lambda p: json.dumps({"take": "Fine overall.", "plan": []}))
    assert out == {"take": "Fine overall.", "plan": []}


def test_skips_without_calling_llm_when_nothing_to_narrate():
    calls = []

    def _spy(p):
        calls.append(p)
        return GOOD

    assert generate_readiness_narrative({}, llm=_spy) is None
    assert generate_readiness_narrative(None, llm=_spy) is None
    ready = dict(READINESS, verdict="ready", blockers=[], warnings=[])
    assert generate_readiness_narrative(ready, llm=_spy) is None
    assert calls == []  # the llm was never invoked on any skip path


def test_prompt_contains_verdict_and_items():
    prompts_seen = []

    def _capture(p):
        prompts_seen.append(p)
        return GOOD

    generate_readiness_narrative(READINESS, llm=_capture)
    p = prompts_seen[0]
    assert "revise" in p
    assert "no limitations section detected" in p
    assert "verify or replace 3 references" in p
    assert "1 desk-reject risk" in p            # the summary/caveat line
    assert "do not invent" in p.lower()          # the grounding instruction
