"""Tests for research_companion.workspaces — CRUD, slugify, stats."""
from __future__ import annotations

import pytest

from research_companion import store, workspaces


class TestSlugify:
    @pytest.mark.parametrize("name,expected", [
        ("LLM Safety", "llm-safety"),
        ("  My   Research!!  ", "my-research"),
        ("Déjà__vu 2.0", "d-j-vu-2-0"),
        ("UPPER", "upper"),
        ("a" * 100, "a" * 64),
    ])
    def test_slugify(self, name, expected):
        assert workspaces.slugify(name) == expected

    def test_empty_name_raises_422(self):
        with pytest.raises(workspaces.WorkspaceError) as e:
            workspaces.slugify("!!!")
        assert e.value.status == 422


class TestCreate:
    def test_create_appends_and_mkdirs(self, isolated_root_dir):
        rec = workspaces.create_workspace("LLM Safety")
        assert rec["id"] == "llm-safety"
        assert rec["name"] == "LLM Safety"
        assert rec["archived"] is False
        assert (isolated_root_dir / "workspaces" / "llm-safety").is_dir()
        reg = store.load_registry()
        assert any(w["id"] == "llm-safety" for w in reg["workspaces"])
        # main is still active
        assert reg["active"] == "main"

    def test_duplicate_slug_409(self, isolated_root_dir):
        workspaces.create_workspace("LLM Safety")
        with pytest.raises(workspaces.WorkspaceError) as e:
            workspaces.create_workspace("llm safety")
        assert e.value.status == 409

    def test_create_persists_main_in_registry(self, isolated_root_dir):
        # Creating the first extra workspace must not lose the implicit main
        workspaces.create_workspace("Other")
        ids = [w["id"] for w in store.load_registry()["workspaces"]]
        assert "main" in ids and "other" in ids


class TestUpdate:
    def test_rename(self, isolated_root_dir):
        workspaces.create_workspace("Other")
        rec = workspaces.update_workspace("other", name="Renamed")
        assert rec["name"] == "Renamed"
        assert rec["id"] == "other"  # id is stable across rename

    def test_archive_non_active(self, isolated_root_dir):
        workspaces.create_workspace("Other")
        rec = workspaces.update_workspace("other", archived=True)
        assert rec["archived"] is True

    def test_archive_active_409(self, isolated_root_dir):
        with pytest.raises(workspaces.WorkspaceError) as e:
            workspaces.update_workspace("main", archived=True)
        assert e.value.status == 409

    def test_unknown_404(self, isolated_root_dir):
        with pytest.raises(workspaces.WorkspaceError) as e:
            workspaces.update_workspace("nope", name="x")
        assert e.value.status == 404


class TestActivate:
    def test_activate_switches_resolution(self, isolated_root_dir):
        workspaces.create_workspace("Other")
        old_ws = store.papergraph_dir()
        result = workspaces.activate_workspace("other")
        assert result["active"] == "other"
        assert store.papergraph_dir() != old_ws
        assert store.papergraph_dir().name == "other"

    def test_activate_unknown_404(self, isolated_root_dir):
        with pytest.raises(workspaces.WorkspaceError) as e:
            workspaces.activate_workspace("nope")
        assert e.value.status == 404

    def test_activate_archived_409(self, isolated_root_dir):
        workspaces.create_workspace("Other")
        workspaces.update_workspace("other", archived=True)
        with pytest.raises(workspaces.WorkspaceError) as e:
            workspaces.activate_workspace("other")
        assert e.value.status == 409


class TestDelete:
    def test_delete_non_active(self, isolated_root_dir):
        workspaces.create_workspace("Other")
        result = workspaces.delete_workspace("other")
        assert result == {"removed": True, "active": "main", "switched": False}
        assert not (isolated_root_dir / "workspaces" / "other").exists()
        reg = store.load_registry()
        assert all(w["id"] != "other" for w in reg["workspaces"])
        assert reg["active"] == "main"

    def test_delete_active_prefers_main(self, isolated_root_dir):
        workspaces.create_workspace("Other")
        workspaces.activate_workspace("other")
        result = workspaces.delete_workspace("other")
        assert result == {"removed": True, "active": "main", "switched": True}
        assert store.load_registry()["active"] == "main"
        assert not (isolated_root_dir / "workspaces" / "other").exists()

    def test_delete_active_main_falls_back_to_first_open(self, isolated_root_dir):
        workspaces.create_workspace("Arch")
        workspaces.create_workspace("Open One")
        workspaces.update_workspace("arch", archived=True)
        result = workspaces.delete_workspace("main")
        assert result == {"removed": True, "active": "open-one", "switched": True}
        assert store.load_registry()["active"] == "open-one"

    def test_delete_active_all_others_archived_picks_first(self, isolated_root_dir):
        workspaces.create_workspace("Arch")
        workspaces.update_workspace("arch", archived=True)
        result = workspaces.delete_workspace("main")
        assert result == {"removed": True, "active": "arch", "switched": True}

    def test_delete_only_workspace_resynthesizes_main(self, isolated_root_dir):
        result = workspaces.delete_workspace("main")
        assert result == {"removed": True, "active": "main", "switched": True}
        reg = store.load_registry()
        assert reg["active"] == "main"
        assert [w["id"] for w in reg["workspaces"]] == ["main"]
        assert reg["workspaces"][0]["archived"] is False

    def test_delete_main_when_not_active(self, isolated_root_dir):
        workspaces.create_workspace("Other")
        workspaces.activate_workspace("other")
        result = workspaces.delete_workspace("main")
        assert result == {"removed": True, "active": "other", "switched": False}
        assert [w["id"] for w in store.load_registry()["workspaces"]] == ["other"]

    def test_delete_unknown_404(self, isolated_root_dir):
        with pytest.raises(workspaces.WorkspaceError) as e:
            workspaces.delete_workspace("nope")
        assert e.value.status == 404


class TestListAndStats:
    def test_list_includes_stats(self, isolated_papergraph_dir, isolated_root_dir):
        # Seed the active (main) workspace with a paper + draft + suggestions
        meta = store.PaperMetadata(
            paper_id="arxiv:ws1", title="Stats Paper", authors=["A"],
            added_at="2026-01-01T00:00:00Z")
        meta.save()
        store.set_draft_paper_id("arxiv:ws1")
        from research_companion.suggestions import save_suggestions
        save_suggestions("arxiv:ws1", {"suggestions": [
            {"id": "s1", "status": "open"},
            {"id": "s2", "status": "dismissed"},
            {"id": "s3", "status": "open"},
        ]})

        listing = workspaces.list_workspaces()
        assert listing["active"] == "main"
        main = next(w for w in listing["workspaces"] if w["id"] == "main")
        assert main["stats"]["papers"] == 1
        assert main["stats"]["draft_title"] == "Stats Paper"
        assert main["stats"]["open_suggestions"] == 2
        assert main["stats"]["last_activity"]  # some ISO string / not None

    def test_stats_on_empty_workspace(self, isolated_root_dir):
        workspaces.create_workspace("Empty One")
        listing = workspaces.list_workspaces()
        empty = next(w for w in listing["workspaces"] if w["id"] == "empty-one")
        assert empty["stats"]["papers"] == 0
        assert empty["stats"]["draft_title"] is None
        assert empty["stats"]["open_suggestions"] == 0

    def test_stats_never_raise_on_corrupt_workspace(self, isolated_root_dir):
        workspaces.create_workspace("Corrupt")
        ws = isolated_root_dir / "workspaces" / "corrupt"
        (ws / "config.json").write_text("{broken", encoding="utf-8")
        listing = workspaces.list_workspaces()  # must not raise
        rec = next(w for w in listing["workspaces"] if w["id"] == "corrupt")
        assert rec["stats"]["papers"] == 0


class TestListActiveHonorsEnvOverride:
    def test_env_override_reflected_in_listing(self, isolated_root_dir, monkeypatch):
        workspaces.create_workspace("Other")
        monkeypatch.setenv("RESEARCH_COMPANION_WORKSPACE", "other")
        store._reset_workspace_caches()
        assert workspaces.list_workspaces(with_stats=False)["active"] == "other"
