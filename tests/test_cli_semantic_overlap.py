"""check-overlap --semantic CLI path (seams monkeypatched; offline)."""
import argparse

from research_companion.cli import _cmd_check_overlap

TARGET = "the quick brown fox jumps over the lazy dog " * 30


def _args(**over):
    base = dict(paper_id="draft", external=False, json=False,
                semantic=False, allow_remote=False)
    base.update(over)
    return argparse.Namespace(**base)


def _wire(monkeypatch):
    monkeypatch.setattr("research_companion.store.load_text",
                        lambda pid: TARGET)

    class _P:
        paper_id = "lib:1"
    monkeypatch.setattr("research_companion.store.list_papers", lambda: [_P()])


def test_semantic_flag_merges_findings(monkeypatch, capsys):
    _wire(monkeypatch)
    monkeypatch.setattr("research_companion.embed.resolve_embedder",
                        lambda **kw: (lambda texts: [], "local"))
    semantic = {"findings": [
        {"matched_paper_id": "lib:1", "score": 0.9, "char_start": 0,
         "char_end": 100, "snippet": "para", "method": "semantic",
         "matched_section_id": "c1"}],
        "summary": {"n_passages": 1, "papers": ["lib:1"], "max_score": 0.9,
                    "text": "1 ..."}}
    monkeypatch.setattr(
        "research_companion.semoverlap.collect_semantic_findings",
        lambda *a, **kw: semantic)
    rc = _cmd_check_overlap(_args(semantic=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "paraphrased" in out  # merged summary text


def test_semantic_flag_without_backend_prints_remedy(monkeypatch, capsys):
    _wire(monkeypatch)
    monkeypatch.setattr("research_companion.embed.resolve_embedder",
                        lambda **kw: None)
    rc = _cmd_check_overlap(_args(semantic=True))
    err = capsys.readouterr().err
    assert rc == 0  # lexical result still reported
    assert "semantic" in err and "research-companion[semantic]" in err


def test_no_semantic_flag_no_semantic_call(monkeypatch, capsys):
    _wire(monkeypatch)

    def _boom(**kw):
        raise AssertionError("must not resolve when --semantic absent and setting off")
    monkeypatch.setattr("research_companion.embed.resolve_embedder", _boom)
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: {"semantic_overlap": False})
    assert _cmd_check_overlap(_args()) == 0


def test_setting_only_without_backend_skips_silently(monkeypatch, capsys):
    _wire(monkeypatch)
    monkeypatch.setattr("research_companion.settings.get_settings",
                        lambda: {"semantic_overlap": True,
                                 "semantic_overlap_allow_remote": False,
                                 "semantic_overlap_threshold": 0.83,
                                 "embed_model": "m"})
    monkeypatch.setattr("research_companion.embed.resolve_embedder",
                        lambda **kw: None)
    rc = _cmd_check_overlap(_args())  # no --semantic flag
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""          # silent — no remedy note
    assert "Summary:" in captured.out  # lexical output still printed


def test_json_output_includes_merged_semantic_findings(monkeypatch, capsys):
    import json as jsonlib
    _wire(monkeypatch)
    monkeypatch.setattr("research_companion.embed.resolve_embedder",
                        lambda **kw: (lambda texts: [], "local"))
    semantic = {"findings": [
        {"matched_paper_id": "lib:1", "score": 0.9, "char_start": 0,
         "char_end": 100, "snippet": "para", "method": "semantic",
         "matched_section_id": "c1"}],
        "summary": {"n_passages": 1, "papers": ["lib:1"], "max_score": 0.9,
                    "text": "1 ..."}}
    monkeypatch.setattr(
        "research_companion.semoverlap.collect_semantic_findings",
        lambda *a, **kw: semantic)
    rc = _cmd_check_overlap(_args(semantic=True, json=True))
    payload = jsonlib.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["summary"]["n_semantic"] == 1
    assert any(f.get("method") == "semantic" for f in payload["findings"])
