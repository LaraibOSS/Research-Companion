"""Tests for the legacy-store → workspaces/ migration in store.py.

The user's real pre-0.4 store (papers/, graph.json, config.json at the root)
must migrate atomically into workspaces/main/ on first resolution, be
idempotent on re-runs, and self-heal from a half-completed migration.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_companion import store


@pytest.fixture()
def fresh_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A root dir NOT yet touched by any store call (bypasses the autouse fixture's
    pre-created workspace by pointing at a sibling directory)."""
    root = tmp_path / "legacy-root"
    root.mkdir()
    monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
    monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
    store._reset_workspace_caches()
    return root


def _build_legacy_store(root: Path) -> None:
    """A miniature pre-0.4 store: 2 papers, graph, config with draft+settings,
    journey, suggestions, and a .env that must never move."""
    papers = root / "papers"
    for name in ("arxiv__1", "arxiv__2"):
        d = papers / name
        d.mkdir(parents=True)
        (d / "metadata.json").write_text(json.dumps({
            "paper_id": name.replace("__", ":"),
            "title": f"Paper {name}",
            "authors": ["A"],
        }), encoding="utf-8")
    (root / "graph.json").write_text('{"nodes": [], "links": []}', encoding="utf-8")
    (root / "config.json").write_text(json.dumps({
        "draft_paper_id": "arxiv:1",
        "settings": {"theme": "light", "provider": "openai"},
    }), encoding="utf-8")
    (root / "journey.json").write_text('{"version": 1}', encoding="utf-8")
    sug = root / "suggestions" / "arxiv__1"
    sug.mkdir(parents=True)
    (sug / "suggestions.json").write_text('{"suggestions": []}', encoding="utf-8")
    (root / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")


class TestFreshStore:
    def test_fresh_root_resolution_writes_nothing(self, fresh_root):
        assert store.papergraph_dir() is None
        # No eager registry, no workspace dir creation for a fresh store
        assert not (fresh_root / "workspaces.json").exists()

    def test_active_defaults_to_none(self, fresh_root):
        assert store.active_workspace_id() is None


class TestLegacyMigration:
    def test_full_migration_layout(self, fresh_root):
        _build_legacy_store(fresh_root)
        ws = store.papergraph_dir()

        assert ws == fresh_root / "workspaces" / "main"
        # Everything per-workspace moved
        assert (ws / "papers" / "arxiv__1" / "metadata.json").exists()
        assert (ws / "papers" / "arxiv__2").exists()
        assert (ws / "graph.json").exists()
        assert (ws / "journey.json").exists()
        assert (ws / "suggestions" / "arxiv__1" / "suggestions.json").exists()
        # config.json split: draft stays per-workspace, settings go global
        ws_cfg = json.loads((ws / "config.json").read_text(encoding="utf-8"))
        assert ws_cfg == {"draft_paper_id": "arxiv:1"}
        root_settings = json.loads(
            (fresh_root / "settings.json").read_text(encoding="utf-8"))
        assert root_settings == {"theme": "light", "provider": "openai"}
        # Legacy artifacts gone from root
        assert not (fresh_root / "papers").exists()
        assert not (fresh_root / "graph.json").exists()
        assert not (fresh_root / "config.json").exists()
        # .env NEVER moves
        assert (fresh_root / ".env").read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-test\n"
        # Registry written as completion marker
        reg = json.loads((fresh_root / "workspaces.json").read_text(encoding="utf-8"))
        assert reg["active"] == "main"
        assert any(w["id"] == "main" for w in reg["workspaces"])

    def test_migration_is_idempotent(self, fresh_root):
        _build_legacy_store(fresh_root)
        store.papergraph_dir()
        before = (fresh_root / "workspaces.json").read_bytes()
        store._reset_workspace_caches()
        store.papergraph_dir()
        assert (fresh_root / "workspaces.json").read_bytes() == before
        assert (fresh_root / "workspaces" / "main" / "papers" / "arxiv__1").exists()

    def test_half_migrated_store_completes(self, fresh_root):
        _build_legacy_store(fresh_root)
        # Simulate a crash: graph.json already moved, papers still at root, no registry
        ws = fresh_root / "workspaces" / "main"
        ws.mkdir(parents=True)
        (fresh_root / "graph.json").rename(ws / "graph.json")

        resolved = store.papergraph_dir()
        assert resolved == ws
        assert (ws / "papers" / "arxiv__1").exists()
        assert (ws / "graph.json").exists()
        assert not (fresh_root / "papers").exists()
        assert (fresh_root / "workspaces.json").exists()

    def test_draft_pointer_survives_migration(self, fresh_root):
        _build_legacy_store(fresh_root)
        store.papergraph_dir()
        assert store.get_draft_paper_id() == "arxiv:1"


class TestActiveWorkspaceResolution:
    def test_env_var_overrides_registry(self, fresh_root, monkeypatch):
        store.save_registry({
            "version": 1, "active": "main",
            "workspaces": [
                {"id": "main", "name": "Main", "created_at": "2026-01-01T00:00:00Z", "archived": False},
                {"id": "other", "name": "Other", "created_at": "2026-01-01T00:00:00Z", "archived": False},
            ],
        })
        monkeypatch.setenv("RESEARCH_COMPANION_WORKSPACE", "other")
        store._reset_workspace_caches()
        assert store.active_workspace_id() == "other"
        assert store.papergraph_dir().name == "other"

    def test_registry_active_used_when_no_env(self, fresh_root):
        store.save_registry({
            "version": 1, "active": "proj-b",
            "workspaces": [
                {"id": "main", "name": "Main", "created_at": "2026-01-01T00:00:00Z", "archived": False},
                {"id": "proj-b", "name": "Proj B", "created_at": "2026-01-01T00:00:00Z", "archived": False},
            ],
        })
        store._reset_workspace_caches()
        assert store.active_workspace_id() == "proj-b"

    def test_registry_change_on_disk_is_picked_up(self, fresh_root):
        # External `workspace use` writes the registry; a long-lived process
        # must notice (mtime-keyed cache).
        reg = store.load_registry()
        assert store.active_workspace_id() is None
        reg["workspaces"].append(
            {"id": "w2", "name": "W2", "created_at": "2026-01-01T00:00:00Z", "archived": False})
        reg["active"] = "w2"
        store.save_registry(reg)
        assert store.active_workspace_id() == "w2"


class TestRegistryPrimitives:
    def test_load_registry_synthesizes_default(self, fresh_root):
        reg = store.load_registry()
        assert reg["active"] is None
        assert reg["workspaces"] == []
        # Synthesized, not written
        assert not (fresh_root / "workspaces.json").exists()

    def test_load_registry_tolerates_corrupt_file(self, fresh_root):
        (fresh_root / "workspaces.json").write_text("{not json", encoding="utf-8")
        reg = store.load_registry()
        assert reg["active"] is None
        assert reg["workspaces"] == []

    def test_save_registry_roundtrip(self, fresh_root):
        reg = {
            "version": 1, "active": "main",
            "workspaces": [{"id": "main", "name": "Main",
                            "created_at": "2026-01-01T00:00:00Z", "archived": False}],
        }
        store.save_registry(reg)
        loaded = store.load_registry()
        loaded["workspaces"][0]["name"] = "Renamed"
        store.save_registry(loaded)
        assert store.load_registry()["workspaces"][0]["name"] == "Renamed"


class TestRootSettings:
    def test_root_settings_roundtrip(self, fresh_root):
        assert store.load_root_settings() == {}
        store.save_root_settings({"theme": "light"})
        assert store.load_root_settings() == {"theme": "light"}
        assert (fresh_root / "settings.json").exists()

    def test_corrupt_root_settings_returns_empty(self, fresh_root):
        (fresh_root / "settings.json").write_text("nope", encoding="utf-8")
        assert store.load_root_settings() == {}


class TestMigrationTriggersBeforeRegistryOps:
    """CRITICAL (final review): if the FIRST 0.4 command on a legacy store is a
    workspace operation, the registry write must not precede migration — that
    would make _needs_migration() False forever and orphan the library."""

    def test_workspace_create_first_migrates_legacy_store(self, fresh_root):
        from research_companion import workspaces
        _build_legacy_store(fresh_root)
        workspaces.create_workspace("Brand New")
        # Legacy artifacts must have been migrated, not orphaned
        assert (fresh_root / "workspaces" / "main" / "papers" / "arxiv__1").exists()
        assert not (fresh_root / "papers").exists()
        ids = [w["id"] for w in store.load_registry()["workspaces"]]
        assert "main" in ids and "brand-new" in ids

    def test_workspace_list_first_migrates_and_counts(self, fresh_root):
        from research_companion import workspaces
        _build_legacy_store(fresh_root)
        listing = workspaces.list_workspaces()
        main = next(w for w in listing["workspaces"] if w["id"] == "main")
        assert main["stats"]["papers"] == 2

    def test_direct_save_registry_first_migrates(self, fresh_root):
        _build_legacy_store(fresh_root)
        reg = store.load_registry()
        store.save_registry(reg)
        assert (fresh_root / "workspaces" / "main" / "papers" / "arxiv__1").exists()
        assert not (fresh_root / "papers").exists()

    def test_corrupt_config_preserved_as_bak(self, fresh_root):
        (fresh_root / "papers").mkdir()
        (fresh_root / "config.json").write_text("{not valid json", encoding="utf-8")
        store.papergraph_dir()
        # Original bytes preserved for hand recovery
        bak = fresh_root / "workspaces" / "main" / "config.json.bak"
        assert bak.exists()
        assert bak.read_text(encoding="utf-8") == "{not valid json"
