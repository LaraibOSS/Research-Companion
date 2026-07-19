"""Tests for `research-companion workspace list|create|use` (W4-B5)."""
from __future__ import annotations

from research_companion import cli, store


class TestWorkspaceCli:
    def test_list_shows_active_main(self, isolated_root_dir, capsys):
        rc = cli.main(["workspace", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "* main" in out

    def test_create_then_list(self, isolated_root_dir, capsys):
        assert cli.main(["workspace", "create", "LLM Safety"]) == 0
        out = capsys.readouterr().out
        assert "llm-safety" in out
        cli.main(["workspace", "list"])
        out = capsys.readouterr().out
        assert "llm-safety" in out and "LLM Safety" in out

    def test_create_duplicate_errors(self, isolated_root_dir, capsys):
        cli.main(["workspace", "create", "Twice"])
        rc = cli.main(["workspace", "create", "twice"])
        assert rc == 1
        err = capsys.readouterr().err
        # Every user-facing stderr error is prefixed "research-companion:",
        # not the old bare "error:".
        assert err.strip().startswith("research-companion:")
        assert not err.strip().startswith("error:")

    def test_use_by_id_and_by_name(self, isolated_root_dir, capsys):
        cli.main(["workspace", "create", "Proj X"])
        assert cli.main(["workspace", "use", "proj-x"]) == 0
        assert store.active_workspace_id() == "proj-x"
        assert cli.main(["workspace", "use", "Proj X"]) == 0  # by display name
        assert cli.main(["workspace", "use", "main"]) == 0
        assert store.active_workspace_id() == "main"

    def test_use_unknown_errors(self, isolated_root_dir, capsys):
        rc = cli.main(["workspace", "use", "nope"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "unknown workspace" in err
        assert err.strip().startswith("research-companion:")

    def test_round_trip_isolation(self, isolated_root_dir, capsys):
        # Paper saved in main is invisible from a fresh workspace and back
        store.PaperMetadata(
            paper_id="arxiv:cliws", title="Main Paper", authors=["A"],
            added_at="2026-01-01T00:00:00Z").save()
        assert len(store.list_papers()) == 1
        cli.main(["workspace", "create", "Fresh"])
        cli.main(["workspace", "use", "fresh"])
        assert store.list_papers() == []
        cli.main(["workspace", "use", "main"])
        assert len(store.list_papers()) == 1
