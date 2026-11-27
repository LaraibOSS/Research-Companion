"""A tool advertised as a lookup must not write.

There is one coverage file per workspace, belonging to the current draft. The
MCP citation_coverage tool computed coverage for whichever paper it was asked
about and saved it there, replacing the draft's stored coverage.
"""
from __future__ import annotations

from research_companion import store

_BIB = """Intro text.

References

[1] A. Vaswani, N. Shazeer, N. Parmar. Attention is all you need. NeurIPS, 2017.
[2] J. Devlin, M. Chang, K. Lee. BERT: Pre-training of deep bidirectional transformers. NAACL, 2019.
[3] K. He, X. Zhang, S. Ren, J. Sun. Deep residual learning for image recognition. CVPR, 2016.
"""


def _paper(pid: str, text: str):
    store.PaperMetadata(paper_id=pid, title=pid, authors=[]).save()
    store.save_text(pid, text)


def test_mcp_citation_coverage_does_not_replace_the_drafts_stored_coverage(isolated_papergraph_dir):
    from research_companion import citations_coverage as cc
    from research_companion import mcp_tools

    _paper("local:draft", _BIB)
    _paper("local:other", _BIB.replace("Attention is all you need", "Some other title entirely"))

    saved = cc.compute_coverage("local:draft")
    saved["resolved_at"] = "2026-01-01T00:00:00Z"
    cc.save_coverage(saved)
    before = cc.coverage_path().read_text(encoding="utf-8")

    res = mcp_tools.citation_coverage(paper_id="local:other")

    assert res["paper_id"] == "local:other" and res["counts"]["total"] == 3
    assert cc.coverage_path().read_text(encoding="utf-8") == before
    assert cc.load_coverage()["draft_paper_id"] == "local:draft"
