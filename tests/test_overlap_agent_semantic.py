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
    calls = []

    def _spy(**kw):
        calls.append(kw)
        return None

    monkeypatch.setattr("research_companion.embed.resolve_embedder", _spy)
    out = OverlapAgent._maybe_semantic("p", ["q"], LEXICAL)
    assert out is LEXICAL
    assert calls == []  # resolve_embedder truly never invoked


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


def test_explicit_zero_threshold_not_replaced_by_default(monkeypatch):
    """Explicit 0.0 threshold must not be silently converted to default."""
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: _settings(semantic_overlap=True,
                                          semantic_overlap_threshold=0.0))
    monkeypatch.setattr("research_companion.embed.resolve_embedder",
                        lambda **kw: (lambda texts: [], "local"))

    recorded_threshold = []

    def _spy_collect(*a, **kw):
        recorded_threshold.append(kw.get("threshold"))
        return {"findings": [], "summary": {"n_passages": 0, "papers": [],
                                           "max_score": 0.0, "text": "none"}}

    monkeypatch.setattr("research_companion.semoverlap.collect_semantic_findings",
                        _spy_collect)
    OverlapAgent._maybe_semantic("p", ["q"], LEXICAL)
    assert recorded_threshold == [0.0]  # Must be 0.0, not the default 0.83
