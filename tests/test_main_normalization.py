"""Tests for the version-gated, TRUE one-time migration inside
load_registry(): a still-default-named "main" (name == "Main") in a
version < 2 registry is EMPTY -> REMOVED (no active research), or
non-empty -> RELABELED to "My research" (no data loss). Once a registry is
version 2, the migration never runs again — a user who later creates and
names a brand-new workspace "Main" is never touched."""
from __future__ import annotations

from research_companion import store, workspaces


def _seed_legacy_registry(root, *, active="main", name="Main", version=1):
    """Write a v1-shaped (or version-less) registry directly to disk, as a
    genuinely old pre-migration store would have — bypasses save_registry's
    caller-side version stamping so the loaded file really predates v2."""
    import json as _json
    reg = {"active": active, "workspaces": [{
        "id": "main", "name": name,
        "created_at": "2026-01-01T00:00:00Z", "archived": False,
    }]}
    if version is not None:
        reg["version"] = version
    (root / "workspaces.json").write_text(_json.dumps(reg), encoding="utf-8")


class TestMainNormalization:
    def test_empty_legacy_main_is_removed(self, tmp_path, monkeypatch):
        # A still-default-named "main" (name == "Main") with no papers and no
        # draft, in a version-1 (legacy) registry — the shape a pre-0.4
        # upgrader with an untouched, empty default lands in.
        root = tmp_path / "empty-main-root"
        root.mkdir()
        monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
        monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
        store._reset_workspace_caches()
        (root / "workspaces" / "main").mkdir(parents=True)
        _seed_legacy_registry(root, version=1)

        reg = store.load_registry()
        assert not any(w["id"] == "main" for w in reg["workspaces"])
        assert reg["active"] is None
        assert reg["version"] == 2

    def test_nonempty_legacy_main_is_relabeled(self, tmp_path, monkeypatch):
        # Same still-default-named "main" in a v1 registry, but WITH a paper
        # on disk — must be relabeled and kept, never removed (no data loss).
        root = tmp_path / "nonempty-main-root"
        root.mkdir()
        monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
        monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
        store._reset_workspace_caches()
        paper_dir = root / "workspaces" / "main" / "papers" / "arxiv__1"
        paper_dir.mkdir(parents=True)
        (paper_dir / "metadata.json").write_text(
            '{"paper_id": "arxiv:1", "title": "T", "authors": []}', encoding="utf-8")
        _seed_legacy_registry(root, version=1)

        reg = store.load_registry()
        main = next(w for w in reg["workspaces"] if w["id"] == "main")
        assert main["name"] == "My research"
        assert reg["active"] == "main"  # still active — no data/selection lost
        assert reg["version"] == 2

    def test_user_renamed_main_in_legacy_registry_is_left_alone(self, tmp_path, monkeypatch):
        # name != "Main" -> not touched by the migration content-wise, but the
        # registry is still stamped version 2 (the migration always runs its
        # one-time pass over a version < 2 registry, even when every record
        # is a no-op for it).
        root = tmp_path / "renamed-main-root"
        root.mkdir()
        monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
        monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
        store._reset_workspace_caches()
        _seed_legacy_registry(root, name="Protein Folding", version=1)

        reg = store.load_registry()
        main = next(w for w in reg["workspaces"] if w["id"] == "main")
        assert main["name"] == "Protein Folding"
        assert reg["active"] == "main"
        assert reg["version"] == 2

    def test_normalization_is_idempotent(self, tmp_path, monkeypatch):
        # Empty legacy main: removed once (version bumped to 2), then a
        # true no-op on the 2nd call (version already 2 — the migration
        # block does not even run) — the file must not be rewritten again.
        root = tmp_path / "idempotent-empty-root"
        root.mkdir()
        monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
        monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
        store._reset_workspace_caches()
        (root / "workspaces" / "main").mkdir(parents=True)
        _seed_legacy_registry(root, version=1)

        reg = store.load_registry()
        assert not any(w["id"] == "main" for w in reg["workspaces"])
        assert reg["active"] is None
        assert reg["version"] == 2
        before = store.registry_path().read_bytes()
        store.load_registry()  # second call must not rewrite the file again
        assert store.registry_path().read_bytes() == before

        # Non-empty legacy main: relabeled once (version bumped to 2), then
        # a no-op on the 2nd call.
        root2 = tmp_path / "idempotent-nonempty-root"
        root2.mkdir()
        monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root2))
        store._reset_workspace_caches()
        paper_dir = root2 / "workspaces" / "main" / "papers" / "arxiv__1"
        paper_dir.mkdir(parents=True)
        (paper_dir / "metadata.json").write_text(
            '{"paper_id": "arxiv:1", "title": "T", "authors": []}', encoding="utf-8")
        _seed_legacy_registry(root2, version=1)

        store.load_registry()
        before2 = store.registry_path().read_bytes()
        store.load_registry()  # second call must not rewrite the file again
        assert store.registry_path().read_bytes() == before2

    def test_fresh_install_has_no_main_to_normalize(self, tmp_path, monkeypatch):
        root = tmp_path / "brand-new"
        root.mkdir()
        monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
        monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
        store._reset_workspace_caches()
        reg = store.load_registry()
        assert reg == {"version": 2, "active": None, "workspaces": []}
        assert not (root / "workspaces.json").exists()

    def test_user_created_empty_main_survives_post_upgrade(self, tmp_path, monkeypatch):
        """The real safety-fix scenario: on a fresh (post-upgrade, version-2)
        root with no workspaces yet, a user creates a brand-new EMPTY
        workspace and names it "Main". Because the registry is already
        version 2, load_registry() must NOT remove it — a user-created
        "Main" is not a legacy leftover."""
        root = tmp_path / "post-upgrade-root"
        root.mkdir()
        monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(root))
        monkeypatch.delenv("RESEARCH_COMPANION_WORKSPACE", raising=False)
        store._reset_workspace_caches()

        # A fresh root's registry is already version 2 (see _default_registry).
        assert store.load_registry()["version"] == 2

        workspaces.create_workspace("Main")  # empty; id "main", name "Main"
        workspaces.activate_workspace("main")
        store._reset_workspace_caches()

        reg = store.load_registry()
        main = next(w for w in reg["workspaces"] if w["id"] == "main")
        assert main["name"] == "Main"  # NOT removed, NOT relabeled
        assert reg["active"] == "main"
        assert reg["version"] == 2
