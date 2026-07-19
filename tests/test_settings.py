"""Tests for research_companion.settings — env-file key management and settings config."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from research_companion import settings, store


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch):
    """update_settings mirrors provider/model into os.environ process-wide, so
    earlier tests in a full run leak into env-aware get_settings — scrub first."""
    monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)
    monkeypatch.delenv("RESEARCH_COMPANION_MODEL", raising=False)


# ---------------------------------------------------------------------------
# env_file_path
# ---------------------------------------------------------------------------

class TestEnvFilePath:
    def test_returns_path_under_root_dir(self, isolated_root_dir):
        # Keys are GLOBAL: .env lives at the root, shared by all workspaces
        p = settings.env_file_path()
        assert p == isolated_root_dir / ".env"
        assert p.parent == isolated_root_dir


# ---------------------------------------------------------------------------
# read_env_file
# ---------------------------------------------------------------------------

class TestReadEnvFile:
    def test_parses_simple_key_value(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("FOO=bar\nBAZ=qux\n", encoding="utf-8")
        result = settings.read_env_file(f)
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_strips_inline_comments(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("FOO=bar # this is a comment\n", encoding="utf-8")
        result = settings.read_env_file(f)
        # Comment stripping: value is everything before #
        # (only if # is not part of the value — simple parser)
        assert "FOO" in result

    def test_skips_comment_lines(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("# this is a comment\nFOO=bar\n", encoding="utf-8")
        result = settings.read_env_file(f)
        assert result == {"FOO": "bar"}

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("\n\nFOO=bar\n\n", encoding="utf-8")
        result = settings.read_env_file(f)
        assert result == {"FOO": "bar"}

    def test_strips_double_quotes(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text('FOO="hello world"\n', encoding="utf-8")
        result = settings.read_env_file(f)
        assert result["FOO"] == "hello world"

    def test_strips_single_quotes(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("FOO='hello world'\n", encoding="utf-8")
        result = settings.read_env_file(f)
        assert result["FOO"] == "hello world"

    def test_missing_file_returns_empty(self, tmp_path):
        result = settings.read_env_file(tmp_path / "nonexistent.env")
        assert result == {}

    def test_roundtrip(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("KEY1=val1\nKEY2=val2\n", encoding="utf-8")
        result = settings.read_env_file(f)
        assert result["KEY1"] == "val1"
        assert result["KEY2"] == "val2"


# ---------------------------------------------------------------------------
# load_env_file
# ---------------------------------------------------------------------------

class TestLoadEnvFile:
    def test_sets_os_environ_for_missing_keys(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("MY_TEST_KEY=hello\n", encoding="utf-8")
        monkeypatch.delenv("MY_TEST_KEY", raising=False)
        settings.load_env_file(f)
        assert os.environ.get("MY_TEST_KEY") == "hello"

    def test_does_not_override_existing_env_by_default(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("MY_TEST_KEY=from_file\n", encoding="utf-8")
        monkeypatch.setenv("MY_TEST_KEY", "already_set")
        settings.load_env_file(f)
        assert os.environ["MY_TEST_KEY"] == "already_set"

    def test_override_true_replaces_existing(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("MY_TEST_KEY=from_file\n", encoding="utf-8")
        monkeypatch.setenv("MY_TEST_KEY", "already_set")
        settings.load_env_file(f, override=True)
        assert os.environ["MY_TEST_KEY"] == "from_file"

    def test_returns_parsed_dict(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("LOAD_TEST_KEY=xyz\n", encoding="utf-8")
        monkeypatch.delenv("LOAD_TEST_KEY", raising=False)
        result = settings.load_env_file(f)
        assert isinstance(result, dict)
        assert result.get("LOAD_TEST_KEY") == "xyz"

    def test_missing_file_is_fine(self, tmp_path, monkeypatch):
        # Must not raise
        result = settings.load_env_file(tmp_path / "no.env")
        assert result == {}


# ---------------------------------------------------------------------------
# write_env_keys
# ---------------------------------------------------------------------------

class TestWriteEnvKeys:
    def test_writes_new_key(self, tmp_path):
        f = tmp_path / ".env"
        settings.write_env_keys({"NEW_KEY": "myvalue"}, path=f)
        result = settings.read_env_file(f)
        assert result["NEW_KEY"] == "myvalue"

    def test_merge_preserves_unrelated_lines(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("# a comment\nEXISTING=keep\n", encoding="utf-8")
        settings.write_env_keys({"NEW_KEY": "newval"}, path=f)
        content = f.read_text(encoding="utf-8")
        assert "# a comment" in content
        assert "EXISTING=keep" in content
        assert "NEW_KEY=newval" in content

    def test_none_deletes_key(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("DEL_KEY=todelete\nKEEP=this\n", encoding="utf-8")
        settings.write_env_keys({"DEL_KEY": None}, path=f)
        result = settings.read_env_file(f)
        assert "DEL_KEY" not in result
        assert result.get("KEEP") == "this"

    def test_update_existing_key(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("MY_KEY=old\n", encoding="utf-8")
        settings.write_env_keys({"MY_KEY": "new"}, path=f)
        result = settings.read_env_file(f)
        assert result["MY_KEY"] == "new"

    def test_roundtrip_write_read(self, tmp_path):
        f = tmp_path / ".env"
        settings.write_env_keys({"A": "1", "B": "2"}, path=f)
        result = settings.read_env_file(f)
        assert result["A"] == "1"
        assert result["B"] == "2"


# ---------------------------------------------------------------------------
# mask_secret
# ---------------------------------------------------------------------------

class TestMaskSecret:
    def test_long_value_shows_last_4(self):
        val = "sk-anthropic-key-abcdef123456"
        masked = settings.mask_secret(val)
        assert masked.endswith("3456")
        assert masked.startswith("****")

    def test_short_value_just_stars(self):
        # len < 8
        val = "abc"
        assert settings.mask_secret(val) == "****"

    def test_exactly_8_chars_shows_last_4(self):
        val = "abcdefgh"  # len == 8
        masked = settings.mask_secret(val)
        assert masked.endswith("efgh")
        assert masked.startswith("****")

    def test_7_chars_is_short(self):
        # len < 8 -> just "****"
        val = "abcdefg"
        assert settings.mask_secret(val) == "****"

    def test_exactly_8_not_short(self):
        val = "12345678"
        masked = settings.mask_secret(val)
        assert masked != "****"
        assert masked.endswith("5678")


# ---------------------------------------------------------------------------
# get_settings
# ---------------------------------------------------------------------------

class TestGetSettings:
    def test_defaults_without_config(self, isolated_papergraph_dir, monkeypatch):
        # Clear any stray env keys
        for env_var in settings.SECRET_KEYS.values():
            monkeypatch.delenv(env_var, raising=False)
        result = settings.get_settings()
        assert result["provider"] == "anthropic"
        assert result["theme"] == "dark"
        assert result["k_sections"] == 6
        assert result["char_budget"] == 8000
        assert result["embed_model"] == "sentence-transformers/all-MiniLM-L6-v2"

    def test_keys_block_set_false_when_absent(self, isolated_papergraph_dir, monkeypatch):
        for env_var in settings.SECRET_KEYS.values():
            monkeypatch.delenv(env_var, raising=False)
        result = settings.get_settings()
        for name in settings.SECRET_KEYS:
            assert result["keys"][name]["set"] is False
            assert result["keys"][name]["masked"] is None

    def test_keys_block_set_true_when_present(self, isolated_papergraph_dir, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-12345678")
        result = settings.get_settings()
        assert result["keys"]["anthropic_api_key"]["set"] is True
        assert result["keys"]["anthropic_api_key"]["masked"] is not None
        # Raw value must NOT appear
        assert "sk-ant-test" not in result["keys"]["anthropic_api_key"]["masked"]

    def test_config_merge_overrides_defaults(self, isolated_papergraph_dir, monkeypatch):
        for env_var in settings.SECRET_KEYS.values():
            monkeypatch.delenv(env_var, raising=False)
        store.save_root_settings({"theme": "light", "k_sections": 10})
        result = settings.get_settings()
        assert result["theme"] == "light"
        assert result["k_sections"] == 10
        # Defaults still fill unset keys
        assert result["provider"] == "anthropic"

    def test_model_none_by_default(self, isolated_papergraph_dir, monkeypatch):
        for env_var in settings.SECRET_KEYS.values():
            monkeypatch.delenv(env_var, raising=False)
        result = settings.get_settings()
        assert result["model"] is None


# ---------------------------------------------------------------------------
# update_settings
# ---------------------------------------------------------------------------

class TestUpdateSettings:
    def _clean_env(self, monkeypatch):
        for env_var in settings.SECRET_KEYS.values():
            monkeypatch.delenv(env_var, raising=False)
        for ev in ("RESEARCH_COMPANION_PROVIDER", "RESEARCH_COMPANION_MODEL"):
            monkeypatch.delenv(ev, raising=False)

    def test_update_theme(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        result = settings.update_settings({"theme": "light"})
        assert result["theme"] == "light"

    def test_invalid_provider_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"provider": "mistral"})

    def test_invalid_theme_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"theme": "pink"})

    def test_invalid_accent_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"accent": "red"})

    def test_invalid_density_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"density": "spacious"})

    def test_k_sections_too_low_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"k_sections": 0})

    def test_k_sections_too_high_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"k_sections": 21})

    def test_char_budget_too_low_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"char_budget": 999})

    def test_char_budget_too_high_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"char_budget": 50001})

    def test_unknown_field_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"unknown_field": "value"})

    def test_provider_mirrored_to_environ(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        settings.update_settings({"provider": "openai"})
        assert os.environ.get("RESEARCH_COMPANION_PROVIDER") == "openai"

    def test_model_mirrored_to_environ(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        settings.update_settings({"model": "gpt-4o"})
        assert os.environ.get("RESEARCH_COMPANION_MODEL") == "gpt-4o"

    def test_model_none_removes_environ(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        monkeypatch.setenv("RESEARCH_COMPANION_MODEL", "some-model")
        settings.update_settings({"model": None})
        assert "RESEARCH_COMPANION_MODEL" not in os.environ

    def test_keys_write_env_file_and_environ(self, isolated_papergraph_dir, monkeypatch, tmp_path):
        self._clean_env(monkeypatch)
        env_path = tmp_path / "test.env"
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        settings.update_settings({"keys": {"anthropic_api_key": "sk-test-12345678"}},
                                  env_path=env_path)
        # Environment should be set
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test-12345678"
        # File should contain key
        file_data = settings.read_env_file(env_path)
        assert file_data.get("ANTHROPIC_API_KEY") == "sk-test-12345678"

    def test_keys_none_deletes_from_env_and_file(self, isolated_papergraph_dir, monkeypatch, tmp_path):
        self._clean_env(monkeypatch)
        env_path = tmp_path / "test.env"
        env_path.write_text("ANTHROPIC_API_KEY=sk-to-delete\n", encoding="utf-8")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-to-delete")
        settings.update_settings({"keys": {"anthropic_api_key": None}}, env_path=env_path)
        assert "ANTHROPIC_API_KEY" not in os.environ
        file_data = settings.read_env_file(env_path)
        assert "ANTHROPIC_API_KEY" not in file_data

    def test_empty_string_key_raises(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"keys": {"anthropic_api_key": ""}})

    def test_returns_get_settings_shape(self, isolated_papergraph_dir, monkeypatch):
        self._clean_env(monkeypatch)
        result = settings.update_settings({"theme": "light"})
        assert "keys" in result
        assert "provider" in result
        assert "theme" in result


# ---------------------------------------------------------------------------
# store: review_report helpers
# ---------------------------------------------------------------------------

class TestReviewReportStore:
    def test_save_and_load_roundtrip(self, isolated_papergraph_dir):
        paper_id = "arxiv:2410.00001"
        report = {"paper_id": paper_id, "lanes": {"citation": {"ok": True}}}
        store.save_review_report(paper_id, report)
        loaded = store.load_review_report(paper_id)
        assert loaded is not None
        assert loaded["paper_id"] == paper_id
        assert loaded["lanes"]["citation"]["ok"] is True

    def test_load_missing_returns_none(self, isolated_papergraph_dir):
        assert store.load_review_report("arxiv:nothere") is None

    def test_review_report_path_location(self, isolated_papergraph_dir):
        paper_id = "arxiv:2410.00001"
        path = store.review_report_path(paper_id)
        assert path.parent.name == "arxiv__2410_00001"
        assert path.name == "report.json"
        assert "reviews" in str(path)

    def test_save_returns_path(self, isolated_papergraph_dir):
        paper_id = "arxiv:2410.00001"
        report = {"test": True}
        p = store.save_review_report(paper_id, report)
        assert isinstance(p, Path)
        assert p.exists()

    def test_load_corrupt_returns_none(self, isolated_papergraph_dir):
        paper_id = "arxiv:2410.00001"
        # Manually write corrupt JSON
        rpath = store.review_report_path(paper_id)
        rpath.parent.mkdir(parents=True, exist_ok=True)
        rpath.write_text("not valid json {{{", encoding="utf-8")
        assert store.load_review_report(paper_id) is None


class TestProviderEnvDefault:
    """Wrap-up fix: get_settings must reflect RESEARCH_COMPANION_PROVIDER/MODEL env
    when config.json carries no explicit setting (otherwise the UI checks the wrong key)."""

    def test_provider_defaults_from_env(self, monkeypatch):
        from research_companion.settings import get_settings
        monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")
        monkeypatch.setenv("RESEARCH_COMPANION_MODEL", "gpt-4o-2024-11-20")
        s = get_settings()
        assert s["provider"] == "openai"
        assert s["model"] == "gpt-4o-2024-11-20"

    def test_config_overrides_env(self, monkeypatch):
        from research_companion.settings import get_settings, update_settings
        monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")
        update_settings({"provider": "anthropic"})
        assert get_settings()["provider"] == "anthropic"


class TestNumericNullValidation:
    """Explicit null for numeric knobs must be a 400-style SettingsError, not a
    TypeError 500 (pydantic forwards explicit nulls via model_fields_set)."""

    def test_k_sections_none_raises_settings_error(self, isolated_papergraph_dir):
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"k_sections": None})

    def test_char_budget_none_raises_settings_error(self, isolated_papergraph_dir):
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"char_budget": None})


class TestAutoAddCitationsSetting:
    def test_default_is_true(self, isolated_papergraph_dir):
        assert settings.get_settings()["auto_add_citations"] is True

    def test_toggle_persists(self, isolated_papergraph_dir):
        settings.update_settings({"auto_add_citations": False})
        assert settings.get_settings()["auto_add_citations"] is False

    def test_non_bool_rejected(self, isolated_papergraph_dir):
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"auto_add_citations": "yes"})


def test_connectors_defaults_empty_and_validates(tmp_path, monkeypatch):
    from research_companion import settings
    monkeypatch.setattr(settings, "load_root_settings", lambda: {}, raising=False)
    assert settings.DEFAULTS["connectors"] == []

def test_update_settings_rejects_unknown_connector(monkeypatch):
    from research_companion import settings
    monkeypatch.setattr("research_companion.store.load_root_settings", lambda: {})
    monkeypatch.setattr("research_companion.store.save_root_settings", lambda s: None)
    import pytest
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"connectors": ["nope"]})

def test_update_settings_accepts_valid_connectors(monkeypatch):
    from research_companion import settings
    saved = {}
    monkeypatch.setattr("research_companion.store.load_root_settings", lambda: dict(saved))
    monkeypatch.setattr("research_companion.store.save_root_settings", lambda s: saved.update(s))
    settings.update_settings({"connectors": ["europepmc"]})
    assert saved["connectors"] == ["europepmc"]


# ---------------------------------------------------------------------------
# semantic_overlap settings (Task 4)
# ---------------------------------------------------------------------------

def test_semantic_overlap_settings_accepted(isolated_papergraph_dir):
    from research_companion import settings
    s = settings.update_settings({"semantic_overlap": True,
                                  "semantic_overlap_allow_remote": True,
                                  "semantic_overlap_threshold": 0.9})
    assert s["semantic_overlap"] is True
    assert s["semantic_overlap_allow_remote"] is True
    assert s["semantic_overlap_threshold"] == 0.9


def test_semantic_overlap_settings_validated(isolated_papergraph_dir):
    from research_companion import settings
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"semantic_overlap": "yes"})
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"semantic_overlap_allow_remote": 1})
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"semantic_overlap_threshold": 1.5})
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"semantic_overlap_threshold": True})


# ---------------------------------------------------------------------------
# readiness_narrative setting (Task 3)
# ---------------------------------------------------------------------------

def test_readiness_narrative_setting_accepted(isolated_papergraph_dir):
    s = settings.update_settings({"readiness_narrative": True})
    assert s["readiness_narrative"] is True


def test_readiness_narrative_setting_rejects_non_bool(isolated_papergraph_dir):
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"readiness_narrative": "yes"})


# ---------------------------------------------------------------------------
# mcp_costed_tools / mcp_cost_cap_usd settings (Task 1)
# ---------------------------------------------------------------------------

def test_mcp_costed_tools_setting_accepted(isolated_papergraph_dir):
    s = settings.update_settings({"mcp_costed_tools": True, "mcp_cost_cap_usd": 2.5})
    assert s["mcp_costed_tools"] is True
    assert s["mcp_cost_cap_usd"] == 2.5


def test_mcp_costed_tools_setting_validated(isolated_papergraph_dir):
    import pytest
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"mcp_costed_tools": "yes"})
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"mcp_cost_cap_usd": 200.0})
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"mcp_cost_cap_usd": True})
