"""OverlapAgent semantic hook (settings-gated; all seams monkeypatched)."""
from research_companion.agents.overlap import OverlapAgent

LEXICAL = {"findings": [], "summary": {"n_passages": 0, "papers": [],
                                       "max_score": 0.0, "text": "none"}}


def _settings(**over):
    base = {"semantic_overlap": False, "semantic_overlap_allow_remote": False,
            "semantic_overlap_threshold": 0.83, "embed_model": "m"}
    base.update(over)
    return base


def test_off_returns_lexical_unchanged_and_never_resolves(monkeypatch):
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _settings())

    def _boom(**kw):
        raise AssertionError("resolve_embedder must not be called when off")
    monkeypatch.setattr("research_companion.embed.resolve_embedder", _boom)
    out = OverlapAgent._maybe_semantic("p", ["q"], LEXICAL)
    assert out is LEXICAL  # the very same object — byte-identical path


def test_no_backend_silently_skips(monkeypatch):
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _settings(semantic_overlap=True))
    monkeypatch.setattr("research_companion.embed.resolve_embedder",
                        lambda **kw: None)
    assert OverlapAgent._maybe_semantic("p", ["q"], LEXICAL) is LEXICAL


def test_on_merges_semantic_findings(monkeypatch):
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _settings(semantic_overlap=True))
    monkeypatch.setattr("research_companion.embed.resolve_embedder",
                        lambda **kw: (lambda texts: [], "local"))
    semantic = {"findings": [
        {"matched_paper_id": "q", "score": 0.9, "char_start": 0,
         "char_end": 100, "snippet": "s", "method": "semantic",
         "matched_section_id": "c1"}],
        "summary": {"n_passages": 1, "papers": ["q"], "max_score": 0.9,
                    "text": "1 ..."}}
    monkeypatch.setattr("research_companion.semoverlap.collect_semantic_findings",
                        lambda *a, **kw: semantic)
    out = OverlapAgent._maybe_semantic("p", ["q"], LEXICAL)
    assert out["summary"]["n_semantic"] == 1
    assert out["findings"][0]["method"] == "semantic"


def test_any_failure_falls_back_to_lexical(monkeypatch):
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _settings(semantic_overlap=True))
    monkeypatch.setattr("research_companion.embed.resolve_embedder",
                        lambda **kw: (lambda texts: [], "local"))

    def _boom(*a, **kw):
        raise RuntimeError("model exploded")
    monkeypatch.setattr("research_companion.semoverlap.collect_semantic_findings",
                        _boom)
    assert OverlapAgent._maybe_semantic("p", ["q"], LEXICAL) is LEXICAL
