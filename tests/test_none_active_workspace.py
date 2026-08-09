"""Tests for the nullable active-workspace resolver and read-degradation
(no active workspace -> reads return empty/None, never raise)."""
from __future__ import annotations

import pytest

from research_companion import store


@pytest.fixture
def no_active_workspace(isolated_papergraph_dir):
    """Flip the autouse-seeded 'main' workspace's registry to active: None,
    keeping the workspace record itself (and its data) on disk untouched."""
    reg = store.load_registry()
    reg["active"] = None
    store.save_registry(reg)
    store._reset_workspace_caches()
    return reg


class TestResolverIsNullable:
    def test_active_workspace_id_none_when_registry_active_is_null(self, no_active_workspace):
        assert store.active_workspace_id() is None

    def test_papergraph_dir_none_when_none_active(self, no_active_workspace):
        assert store.papergraph_dir() is None

    def test_env_override_still_wins_over_null_active(self, no_active_workspace, monkeypatch):
        monkeypatch.setenv("RESEARCH_COMPANION_WORKSPACE", "main")
        store._reset_workspace_caches()
        assert store.active_workspace_id() == "main"
        assert store.papergraph_dir() is not None


class TestDefaultRegistryIsEmpty:
    def test_default_registry_shape(self):
        # version 2: a brand-new registry has never had a legacy "main" to
        # migrate, so it is synthesized already past the one-time
        # main-normalization gate in store.load_registry() (see there).
        assert store._default_registry() == {
            "version": 2, "active": None, "workspaces": [],
        }


class TestReadHelpersDegradeToEmpty:
    def test_list_papers_empty_when_none_active(self, no_active_workspace):
        assert store.list_papers() == []

    def test_papers_dir_none_and_does_not_mkdir(self, no_active_workspace, isolated_root_dir):
        assert store.papers_dir() is None
        # No stray "papers" dir created relative to cwd or anywhere else.
        assert not (isolated_root_dir / "papers").exists()

    def test_paper_dir_none(self, no_active_workspace):
        assert store.paper_dir("arxiv:none-active") is None

    def test_papermetadata_load_none(self, no_active_workspace):
        assert store.PaperMetadata.load("arxiv:none-active") is None

    def test_pdf_path_none(self, no_active_workspace):
        assert store.pdf_path("arxiv:none-active") is None

    def test_load_text_none(self, no_active_workspace):
        assert store.load_text("arxiv:none-active") is None

    def test_load_extraction_none(self, no_active_workspace):
        assert store.load_extraction("arxiv:none-active", prompt_sha="x") is None

    def test_load_simplified_none(self, no_active_workspace):
        assert store.load_simplified("arxiv:none-active") is None

    def test_load_citation_polarity_empty(self, no_active_workspace):
        assert store.load_citation_polarity("arxiv:none-active") == {}

    def test_load_sections_none(self, no_active_workspace):
        assert store.load_sections("arxiv:none-active") is None

    def test_load_structure_none(self, no_active_workspace):
        assert store.load_structure("arxiv:none-active") is None

    def test_load_alignment_none(self, no_active_workspace):
        assert store.load_alignment("arxiv:none-active") is None

    def test_load_strength_none(self, no_active_workspace):
        assert store.load_strength("arxiv:none-active") is None

    def test_load_embeddings_none(self, no_active_workspace):
        assert store.load_embeddings("arxiv:none-active") is None

    def test_load_gaps_none(self, no_active_workspace):
        assert store.load_gaps("arxiv:none-active") is None

    def test_load_config_empty(self, no_active_workspace):
        assert store.load_config() == {}

    def test_get_draft_paper_id_none(self, no_active_workspace):
        assert store.get_draft_paper_id() is None

    def test_list_failures_empty(self, no_active_workspace):
        assert store.list_failures() == {}

    def test_load_review_report_none(self, no_active_workspace):
        assert store.load_review_report("arxiv:none-active") is None

    def test_load_gap_resolution_none(self, no_active_workspace):
        assert store.load_gap_resolution() is None

    def test_workspace_path_none(self, no_active_workspace):
        assert store.workspace_path("anything.json") is None


class TestSiblingModulesDegrade:
    def test_load_graph_empty(self, no_active_workspace):
        from research_companion.graph import load_graph
        g = load_graph()
        assert g.number_of_nodes() == 0

    def test_load_journey_default(self, no_active_workspace):
        from research_companion.journey import load_journey
        assert load_journey() == {"version": 1, "draft_versions": [], "events": []}

    def test_journey_summary_never_raises(self, no_active_workspace):
        from research_companion.journey import journey_summary
        summary = journey_summary()
        assert summary["versions"] == []
        assert summary["events"] == []

    def test_list_notes_empty(self, no_active_workspace):
        from research_companion.notes_store import list_notes
        assert list_notes() == []

    def test_list_views_empty(self, no_active_workspace):
        from research_companion.views import list_views
        assert list_views() == []

    def test_load_conversation_none(self, no_active_workspace):
        from research_companion.converse import load_conversation
        assert load_conversation("conv_doesnotexist") is None

    def test_delete_conversation_false(self, no_active_workspace):
        from research_companion.converse import delete_conversation
        assert delete_conversation("conv_doesnotexist") is False

    def test_load_placement_none(self, no_active_workspace):
        from research_companion.citation_placement import load_placement
        assert load_placement() is None

    def test_load_coverage_none(self, no_active_workspace):
        from research_companion.citations_coverage import load_coverage
        assert load_coverage() is None

    def test_load_suggestions_none(self, no_active_workspace):
        from research_companion.suggestions import load_suggestions
        assert load_suggestions("arxiv:none-active") is None
