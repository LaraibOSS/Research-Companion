"""Shared fixtures: isolated RESEARCH_COMPANION_DIR per test, sample fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _restore_os_environ():
    """Snapshot and restore os.environ around every test.

    monkeypatch only undoes env vars it set itself; it cannot undo *direct*
    os.environ writes made by product code (e.g. settings.load_env_file loading
    the project .env in serve_lab, or update_settings mirroring keys/provider).
    Those leak process-globally and change later tests' behavior (a leaked
    HF_TOKEN flips qa.answer onto the hybrid retrieval path, breaking the
    zero-score / empty-question short-circuit). Restoring the full environ here
    makes env isolation hold for the whole suite regardless of who mutates it.
    """
    snapshot = dict(os.environ)
    # Pin the parser to pypdfium for the whole suite: docling is auto-selected
    # by get_parser() whenever the docling package happens to be importable, and
    # routing real-PDF parsing through it costs 40+ seconds per call (plus model
    # downloads on a clean machine). Tests that specifically exercise docling
    # selection override this explicitly (see tests/test_parsers_docling.py).
    os.environ["RESEARCH_COMPANION_PARSER"] = "pypdfium"
    # Pin the provider to anthropic for the whole suite: cli.main() unconditionally
    # loads Path.cwd()/".env" at startup, and the maintainer's real local .env sets
    # RESEARCH_COMPANION_PROVIDER=openai for their own dev workflow. load_env_file
    # only fills keys that are NOT already in os.environ, so pre-setting it here
    # keeps that developer-specific value from leaking into any test that invokes
    # cli.main() without an explicit --provider flag. This was inert before
    # RESEARCH_COMPANION_PROVIDER was honored as an env fallback (args.provider
    # always won); now that it's honored, an unset var here would silently flip
    # provider-default tests to openai. Tests exercising a specific provider/env
    # combination still override this locally via monkeypatch.setenv/delenv.
    os.environ["RESEARCH_COMPANION_PROVIDER"] = "anthropic"
    yield
    for key in list(os.environ):
        if key not in snapshot:
            del os.environ[key]
    for key, value in snapshot.items():
        if os.environ.get(key) != value:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def _reset_graph_lock():
    """Give every test a fresh ``research_companion.lab._GRAPH_LOCK``.

    The pipeline serializes graph read/write with a *module-global*
    ``asyncio.Lock`` (``lab._GRAPH_LOCK``). An asyncio.Lock binds to the event
    loop that first *waits* on it and carries its ``_locked``/``_waiters`` state
    process-globally. That is invisible in production (serve_lab runs one loop
    for the whole process) but leaks across tests: each TestClient spins up its
    own short-lived event loop, and if one test's loop is torn down while a task
    is contending the lock (the bpo-42130 cancellation-race shape the lifespan
    teardown already guards against), the lock is left locked and bound to a now
    dead loop. The next test that contends it — e.g. the retry job racing the
    startup weak-metadata backfill on the same paper — then raises
    ``RuntimeError: ... is bound to a different event loop`` inside the stage-4
    graph section, so ``ingest_one`` bails before the strength stage and
    ``test_retry_pipeline_stages_run_on_success`` sees strengther never called.
    Rebinding a pristine Lock per test keeps that isolation from leaking.
    """
    import asyncio

    from research_companion import lab

    lab._GRAPH_LOCK = asyncio.Lock()
    yield
    lab._GRAPH_LOCK = asyncio.Lock()


@pytest.fixture(autouse=True)
def isolated_papergraph_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force every test to use a fresh research-companion dir under tmp_path.

    Autouse so no test can accidentally write to the user's real
    ~/.research-companion/. Returns the ACTIVE WORKSPACE directory
    (root/workspaces/main) — the place papers/, graph.json, config.json etc.
    live — so the ~400 existing usages keep working unchanged after the
    0.4 workspaces feature.

    A fresh root now starts with NO active workspace (active: null,
    workspaces: []) — see store._default_registry(). The ~400 existing
    tests assume an active "main" research, so this fixture seeds and
    activates one explicitly instead of relying on the removed implicit
    default. Tests that specifically exercise the none/fresh-install state
    use the `no_active_workspace` fixture (tests/test_none_active_workspace.py)
    or `store.save_registry({...active: None...})` directly.
    """
    from research_companion import store, workspaces

    root = tmp_path / "research-companion"
    root.mkdir()
    monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
    monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
    store._reset_workspace_caches()
    reg = store.load_registry()
    if not any(w.get("id") == "main" for w in reg["workspaces"]):
        workspaces.create_workspace("Main")
    workspaces.activate_workspace("main")
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
