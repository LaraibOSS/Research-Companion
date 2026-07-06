"""Shared fixtures: isolated RESEARCH_COMPANION_DIR per test, sample fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_papergraph_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force every test to use a fresh research-companion dir under tmp_path.

    Autouse so no test can accidentally write to the user's real
    ~/.research-companion/. Returns the ACTIVE WORKSPACE directory
    (root/workspaces/main) — the place papers/, graph.json, config.json etc.
    live — so the ~400 existing usages keep working unchanged after the
    0.4 workspaces feature.
    """
    from research_companion import store

    root = tmp_path / "research-companion"
    root.mkdir()
    monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
    monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
    store._reset_workspace_caches()
    ws = store.papergraph_dir()
    ws.mkdir(parents=True, exist_ok=True)
    yield ws
    store._reset_workspace_caches()


@pytest.fixture
def isolated_root_dir(isolated_papergraph_dir: Path) -> Path:
    """The GLOBAL root (holds .env, settings.json, workspaces.json)."""
    from research_companion import store
    return store.root_dir()


@pytest.fixture
def fake_pdf_bytes() -> bytes:
    """Smallest valid PDF — pypdf can parse it."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj\n"
        b"4 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 50 750 Td (Hello papergraph) Tj ET\n"
        b"endstream endobj\n"
        b"xref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n"
        b"0000000109 00000 n\n0000000189 00000 n\n"
        b"trailer<</Size 5/Root 1 0 R>>\n"
        b"startxref\n279\n%%EOF\n"
    )


@pytest.fixture
def sample_extraction() -> dict:
    """A reasonable extraction object matching the prompt schema."""
    return {
        "concepts": [
            {"name": "Knowledge graph", "definition": "A graph of entities and their relationships."},
            {"name": "RAG", "definition": "Retrieval-augmented generation."},
        ],
        "methods": [
            {"name": "GraphRAG", "description": "Hierarchical graph + community summaries for RAG."},
            {"name": "BM25", "description": "Sparse keyword retrieval."},
        ],
        "datasets": [
            {"name": "HotpotQA", "description": "Multi-hop QA over Wikipedia."},
        ],
        "claims": [
            {"text": "Graph-based RAG outperforms vector RAG on multi-hop questions."},
        ],
        "results": [
            {"metric": "F1", "value": "78.9", "dataset": "HotpotQA"},
        ],
        "related_work": ["Lewis et al. 2020"],
    }
