"""Tests for the idempotent 'main' -> 'My research' normalization inside
load_registry() (Task 1's implementation, exercised here end-to-end)."""
from __future__ import annotations

from research_companion import store, workspaces


class TestMainNormalization:
    def test_default_named_main_is_relabeled_once(self, isolated_root_dir):
        # The autouse fixture already created+activated "main" with name "Main"
        # (workspaces.create_workspace("Main")); the very next load_registry()
        # call (already triggered internally) should have relabeled it.
        reg = store.load_registry()
        main = next(w for w in reg["workspaces"] if w["id"] == "main")
        assert main["name"] == "My research"
        assert reg["active"] == "main"  # still active — no data/selection lost

    def test_user_renamed_main_is_left_alone(self, isolated_root_dir):
        workspaces.update_workspace("main", name="Protein Folding")
        reg = store.load_registry()
        main = next(w for w in reg["workspaces"] if w["id"] == "main")
        assert main["name"] == "Protein Folding"

    def test_normalization_is_idempotent(self, isolated_root_dir):
        store.load_registry()
        before = store.registry_path().read_bytes()
        store.load_registry()  # second call must not rewrite the file again
        assert store.registry_path().read_bytes() == before

    def test_fresh_install_has_no_main_to_normalize(self, tmp_path, monkeypatch):
        root = tmp_path / "brand-new"
        root.mkdir()
        monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
        monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
        store._reset_workspace_caches()
        reg = store.load_registry()
        assert reg == {"version": 1, "active": None, "workspaces": []}
        assert not (root / "workspaces.json").exists()
