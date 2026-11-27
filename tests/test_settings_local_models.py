"""Settings for the self-hosted model providers (openai_compatible, ollama)."""
from __future__ import annotations

import os

import pytest

from research_companion import llm, settings

_ENV_VARS = ("RESEARCH_COMPANION_PROVIDER", "RESEARCH_COMPANION_MODEL",
             "RESEARCH_COMPANION_BASE_URL", "RESEARCH_COMPANION_API_KEY",
             "RESEARCH_COMPANION_OLLAMA_URL", "RESEARCH_COMPANION_OLLAMA_NUM_CTX",
             "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


@pytest.fixture
def clean_env(monkeypatch, isolated_papergraph_dir):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_new_providers_accepted(clean_env):
    for provider in ("ollama", "openai_compatible"):
        s = settings.update_settings({"provider": provider})
        assert s["provider"] == provider
        assert os.environ["RESEARCH_COMPANION_PROVIDER"] == provider


def test_settings_providers_are_the_layers_providers():
    assert set(llm.PROVIDERS) == settings._VALID_PROVIDERS


def test_unknown_provider_still_rejected(clean_env):
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"provider": "llamafile"})


def test_defaults(clean_env):
    s = settings.get_settings()
    assert s["base_url"] == ""
    assert s["ollama_url"] == ""
    assert s["ollama_num_ctx"] == 16384


def test_urls_mirrored_to_env_and_cleared(clean_env):
    settings.update_settings({"base_url": "http://localhost:8000/v1",
                              "ollama_url": " https://gpu-box:11434 "})
    assert os.environ["RESEARCH_COMPANION_BASE_URL"] == "http://localhost:8000/v1"
    # Stored and mirrored without the stray whitespace.
    assert os.environ["RESEARCH_COMPANION_OLLAMA_URL"] == "https://gpu-box:11434"
    assert settings.get_settings()["ollama_url"] == "https://gpu-box:11434"

    settings.update_settings({"base_url": ""})
    assert "RESEARCH_COMPANION_BASE_URL" not in os.environ


@pytest.mark.parametrize("bad", ["localhost:11434", "ftp://x", "file:///etc", "http://", 42])
def test_url_validation(clean_env, bad):
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"ollama_url": bad})
    with pytest.raises(settings.SettingsError):
        settings.update_settings({"base_url": bad})


def test_num_ctx_mirrored_and_validated(clean_env):
    settings.update_settings({"ollama_num_ctx": 32768})
    assert os.environ["RESEARCH_COMPANION_OLLAMA_NUM_CTX"] == "32768"
    assert llm.ollama_num_ctx() == 32768
    for bad in (1024, 2_000_000, "16384", 16384.0, True):
        with pytest.raises(settings.SettingsError):
            settings.update_settings({"ollama_num_ctx": bad})


def test_env_values_shown_when_not_saved(clean_env):
    clean_env.setenv("RESEARCH_COMPANION_OLLAMA_URL", "http://env-host:11434")
    clean_env.setenv("RESEARCH_COMPANION_OLLAMA_NUM_CTX", "8192")
    s = settings.get_settings()
    assert s["ollama_url"] == "http://env-host:11434"
    assert s["ollama_num_ctx"] == 8192


def test_openai_compatible_key_is_a_masked_secret(clean_env):
    s = settings.update_settings({"keys": {"openai_compatible_api_key": "sk-local-123456"}})
    assert os.environ["RESEARCH_COMPANION_API_KEY"] == "sk-local-123456"
    info = s["keys"]["openai_compatible_api_key"]
    assert info["set"] is True and "sk-local" not in info["masked"]


# ---------------------------------------------------------------------------
# "Is a model configured" -- not the same as "is a key present"
# ---------------------------------------------------------------------------


def test_ollama_needs_no_key_only_a_model(clean_env):
    settings.update_settings({"provider": "ollama"})
    assert settings.get_settings()["provider_ready"] is False  # no model yet
    settings.update_settings({"model": "llama3.1:8b"})
    assert settings.get_settings()["provider_ready"] is True


def test_openai_compatible_key_optional_but_url_and_model_required(clean_env):
    settings.update_settings({"provider": "openai_compatible", "model": "qwen2.5"})
    assert settings.get_settings()["provider_ready"] is False  # no server URL
    settings.update_settings({"base_url": "http://localhost:8000/v1"})
    assert settings.get_settings()["provider_ready"] is True  # no key needed


def test_hosted_providers_still_need_their_key(clean_env):
    settings.update_settings({"provider": "anthropic"})
    assert settings.get_settings()["provider_ready"] is False
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-xxxxxxxx")
    assert settings.get_settings()["provider_ready"] is True


def test_lab_provider_configured_follows_provider_ready(clean_env):
    from research_companion.lab_api import _llm_provider_configured
    settings.update_settings({"provider": "ollama", "model": "llama3.1:8b"})
    assert _llm_provider_configured() is True
    settings.update_settings({"provider": "openai"})
    assert _llm_provider_configured() is False
