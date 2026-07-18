"""Degradation: with semantic_overlap off (default), the overlap lane's output
is byte-identical to the lexical-only result."""
import asyncio
import json

from research_companion.overlap import near_duplicate_passages


def test_agent_output_identical_to_lexical_when_off(monkeypatch):
    # Follow the stub-ctx pattern from the existing overlap agent tests.
    from research_companion.agents.overlap import OverlapAgent
    from research_companion.settings import DEFAULTS

    # Hermetic: pin settings to the shipped defaults (semantic_overlap False),
    # not whatever settings.json the developer's machine happens to have.
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: dict(DEFAULTS))

    target = "the quick brown fox jumps over the lazy dog " * 30
    corpus = [("lib:1", "a completely different document body " * 30)]

    monkeypatch.setattr("research_companion.store.load_text",
                        lambda pid: target if pid == "draft" else corpus[0][1])

    class _P:
        paper_id = "lib:1"
    monkeypatch.setattr("research_companion.store.list_papers", lambda: [_P()])

    class _Bus:
        async def publish(self, e):
            pass

    class _Ctx:
        paper_id = "draft"
        bus = _Bus()
        data = {}

    result = asyncio.run(OverlapAgent().run(_Ctx()))
    expected = near_duplicate_passages(target, corpus)
    assert json.dumps(result.data, sort_keys=True) == \
        json.dumps(expected, sort_keys=True)
