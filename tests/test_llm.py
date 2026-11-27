"""The one model layer (research_companion/llm.py).

No network and no real model: the SDK clients and httpx are replaced with
fakes that record what would have been sent.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from research_companion import extract, llm

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeAnthropic:
    calls: list[dict] = []
    stop_reason = "end_turn"

    def __init__(self, api_key=None):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        _FakeAnthropic.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hello")],
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
            stop_reason=_FakeAnthropic.stop_reason,
        )


class _FakeOpenAI:
    calls: list[dict] = []
    inits: list[dict] = []
    finish_reason = "stop"
    raise_on_create: Exception | None = None

    def __init__(self, **kwargs):
        _FakeOpenAI.inits.append(kwargs)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        if _FakeOpenAI.raise_on_create is not None:
            raise _FakeOpenAI.raise_on_create
        _FakeOpenAI.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=" hi "),
                                     finish_reason=_FakeOpenAI.finish_reason)],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
        )


@pytest.fixture
def fake_anthropic(monkeypatch):
    import anthropic
    _FakeAnthropic.calls = []
    _FakeAnthropic.stop_reason = "end_turn"
    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    return _FakeAnthropic


@pytest.fixture
def fake_openai(monkeypatch):
    import openai
    _FakeOpenAI.calls = []
    _FakeOpenAI.inits = []
    _FakeOpenAI.finish_reason = "stop"
    _FakeOpenAI.raise_on_create = None
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    return _FakeOpenAI


@pytest.fixture
def clean_llm_env(monkeypatch):
    for var in (llm.PROVIDER_ENV_VAR, llm.MODEL_ENV_VAR, llm.BASE_URL_ENV_VAR, llm.API_KEY_ENV_VAR,
                llm.OLLAMA_URL_ENV_VAR, llm.OLLAMA_NUM_CTX_ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


class _FakeHttpxResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.fixture
def fake_ollama(monkeypatch):
    sent: list[dict] = []
    state = {"payload": {
        "message": {"role": "assistant", "content": '{"ok": true}'},
        "prompt_eval_count": 120, "eval_count": 30, "done_reason": "stop",
    }, "status": 200, "raise": None}

    def _post(url, json=None, timeout=None):
        if state["raise"] is not None:
            raise state["raise"]
        sent.append({"url": url, "json": json})
        return _FakeHttpxResponse(state["payload"], state["status"])

    monkeypatch.setattr(httpx, "post", _post)
    return SimpleNamespace(sent=sent, state=state)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_resolution_explicit_beats_env_beats_default(clean_llm_env):
    assert llm.resolve_provider_and_model() == ("anthropic", llm.DEFAULT_MODELS["anthropic"])

    clean_llm_env.setenv(llm.PROVIDER_ENV_VAR, "openai")
    clean_llm_env.setenv(llm.MODEL_ENV_VAR, "gpt-env")
    assert llm.resolve_provider_and_model() == ("openai", "gpt-env")

    assert llm.resolve_provider_and_model("anthropic", "claude-x") == ("anthropic", "claude-x")


def test_resolution_env_model_only_and_default_model_flag(clean_llm_env):
    clean_llm_env.setenv(llm.PROVIDER_ENV_VAR, "openai")
    assert llm.resolve_provider_and_model() == ("openai", llm.DEFAULT_MODELS["openai"])
    assert llm.resolve_provider_and_model(default_model=False) == ("openai", None)


def test_resolution_normalises_env_provider(clean_llm_env):
    clean_llm_env.setenv(llm.PROVIDER_ENV_VAR, "  Ollama ")
    assert llm.resolve_provider_and_model()[0] == "ollama"


def test_local_providers_have_no_default_model(clean_llm_env):
    assert llm.resolve_provider_and_model("ollama") == ("ollama", None)
    assert llm.resolve_provider_and_model("openai_compatible") == ("openai_compatible", None)
    with pytest.raises(llm.LLMConfigError, match=llm.MODEL_ENV_VAR):
        llm.resolve_model("ollama")


def test_extract_resolve_model_is_the_same_function():
    assert extract.resolve_model is llm.resolve_model
    assert extract._DEFAULT_MODELS_BY_PROVIDER is llm.DEFAULT_MODELS


def test_text_callable_never_fails_at_build_time(clean_llm_env):
    fn = llm.text_callable("ollama")  # no model: must not raise yet
    with pytest.raises(llm.LLMConfigError):
        fn("prompt")


# ---------------------------------------------------------------------------
# LLMResult
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason,truncated", [
    ("max_tokens", True), ("length", True), ("end_turn", False), ("stop", False), (None, False),
])
def test_truncated_property(reason, truncated):
    r = llm.LLMResult(text="", input_tokens=0, output_tokens=0, stop_reason=reason,
                      provider="x", model="y")
    assert r.truncated is truncated
    assert r.usage()["truncated"] is truncated


# ---------------------------------------------------------------------------
# Hosted providers
# ---------------------------------------------------------------------------


def test_anthropic_request_and_result(fake_anthropic, clean_llm_env):
    r = llm.complete("p", provider="anthropic", model="m", max_output_tokens=99)
    assert fake_anthropic.calls == [{
        "model": "m", "max_tokens": 99, "messages": [{"role": "user", "content": "p"}]}]
    assert (r.text, r.input_tokens, r.output_tokens) == ("hello", 11, 7)
    assert r.provider == "anthropic" and not r.truncated


def test_anthropic_truncation_detected(fake_anthropic, clean_llm_env):
    fake_anthropic.stop_reason = "max_tokens"
    assert llm.complete("p", provider="anthropic", model="m").truncated


def test_anthropic_system_prompt_passed(fake_anthropic, clean_llm_env):
    llm.complete("u", provider="anthropic", model="m", system="sys")
    assert fake_anthropic.calls[0]["system"] == "sys"


def test_openai_request_and_result(fake_openai, clean_llm_env):
    r = llm.complete("give json", provider="openai", model="g", json_mode=True)
    call = fake_openai.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["temperature"] == 0.0 and call["max_tokens"] == 2048
    assert r.text == "hi" and (r.input_tokens, r.output_tokens) == (5, 3)


def test_openai_truncation_detected(fake_openai, clean_llm_env):
    fake_openai.finish_reason = "length"
    assert llm.complete("p", provider="openai", model="g").truncated


def test_unknown_provider_rejected_by_complete(clean_llm_env):
    with pytest.raises(ValueError, match="unknown provider"):
        llm.complete("p", provider="nope", model="m")


# ---------------------------------------------------------------------------
# Legacy seams still work, and still intercept
# ---------------------------------------------------------------------------


def test_extract_call_anthropic_keeps_its_shape(fake_anthropic, clean_llm_env):
    text, usage = extract._call_anthropic("p", model="m")
    assert text == "hello"
    assert usage["input_tokens"] == 11 and usage["output_tokens"] == 7
    assert usage["truncated"] is False


def test_extract_call_openai_keeps_its_shape(fake_openai, clean_llm_env):
    text, usage = extract._call_openai("p", model="g", json_mode=False)
    assert text == "hi" and usage["input_tokens"] == 5
    assert "response_format" not in fake_openai.calls[0]


def test_call_text_routes_hosted_providers_through_extract_seams(monkeypatch, clean_llm_env):
    calls = []
    monkeypatch.setattr(extract, "_call_anthropic",
                        lambda prompt, model: (calls.append(("anthropic", model)) or ("a", {})))
    monkeypatch.setattr(extract, "_call_openai",
                        lambda prompt, model, **kw: (calls.append(("openai", model, kw)) or ("o", {})))
    assert llm.call_text("p")[0] == "a"
    assert llm.call_text("p", provider="openai", json_mode=False)[0] == "o"
    # An unrecognised provider keeps the long-standing fallback to Anthropic.
    assert llm.call_text("p", provider="mystery")[0] == "a"
    assert calls == [
        ("anthropic", llm.DEFAULT_MODELS["anthropic"]),
        ("openai", llm.DEFAULT_MODELS["openai"], {"json_mode": False}),
        ("anthropic", llm.DEFAULT_MODELS["anthropic"]),
    ]


def test_chat_seams_delegate_to_layer(fake_anthropic, fake_openai, clean_llm_env):
    from research_companion import chat
    text, usage = chat._call_anthropic("sys", "user", model="m")
    assert text == "hello" and usage == {"input_tokens": 11, "output_tokens": 7}
    assert fake_anthropic.calls[0]["system"] == "sys"
    assert fake_anthropic.calls[0]["max_tokens"] == 1024
    text, _ = chat._call_openai("sys", "user", model="g")
    assert text == "hi"
    msgs = fake_openai.calls[0]["messages"]
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert "response_format" not in fake_openai.calls[0]


# ---------------------------------------------------------------------------
# openai_compatible
# ---------------------------------------------------------------------------


def test_openai_compatible_uses_base_url_and_placeholder_key(fake_openai, clean_llm_env):
    clean_llm_env.setenv(llm.BASE_URL_ENV_VAR, "http://localhost:8000/v1")
    r = llm.complete("give json", provider="openai_compatible", model="qwen", json_mode=True)
    init = fake_openai.inits[-1]
    assert init["base_url"] == "http://localhost:8000/v1"
    assert init["api_key"]  # SDK requires a value even when the server needs none
    assert fake_openai.calls[0]["response_format"] == {"type": "json_object"}
    assert fake_openai.calls[0]["model"] == "qwen"
    assert r.provider == "openai_compatible" and r.text == "hi"


def test_openai_compatible_sends_configured_key(fake_openai, clean_llm_env):
    clean_llm_env.setenv(llm.BASE_URL_ENV_VAR, "http://h/v1")
    clean_llm_env.setenv(llm.API_KEY_ENV_VAR, "sk-local")
    llm.complete("p", provider="openai_compatible", model="m")
    assert fake_openai.inits[-1]["api_key"] == "sk-local"


def test_openai_compatible_truncation(fake_openai, clean_llm_env):
    clean_llm_env.setenv(llm.BASE_URL_ENV_VAR, "http://h/v1")
    fake_openai.finish_reason = "length"
    assert llm.complete("p", provider="openai_compatible", model="m").truncated


def test_openai_compatible_requires_model_and_url(fake_openai, clean_llm_env):
    with pytest.raises(llm.LLMConfigError, match="model"):
        llm.complete("p", provider="openai_compatible")
    with pytest.raises(llm.LLMConfigError, match=llm.BASE_URL_ENV_VAR):
        llm.complete("p", provider="openai_compatible", model="m")


def test_openai_compatible_connection_failure_is_plain(fake_openai, clean_llm_env):
    import openai
    clean_llm_env.setenv(llm.BASE_URL_ENV_VAR, "http://localhost:9/v1")
    fake_openai.raise_on_create = openai.APIConnectionError(
        request=httpx.Request("POST", "http://localhost:9/v1/chat/completions"))
    with pytest.raises(llm.LLMConnectionError) as ei:
        llm.complete("p", provider="openai_compatible", model="m")
    assert str(ei.value) == ("Could not reach the OpenAI-compatible server at "
                             "http://localhost:9/v1. Is it running?")


# ---------------------------------------------------------------------------
# ollama
# ---------------------------------------------------------------------------


def test_ollama_request_shape(fake_ollama, clean_llm_env):
    r = llm.complete("Return JSON please", provider="ollama", model="llama3.1:8b",
                     max_output_tokens=512, json_mode=True)
    assert len(fake_ollama.sent) == 1
    sent = fake_ollama.sent[0]
    assert sent["url"] == "http://localhost:11434/api/chat"
    assert sent["json"] == {
        "model": "llama3.1:8b",
        "messages": [{"role": "user", "content": "Return JSON please"}],
        "stream": False,
        "options": {"num_ctx": 16384, "temperature": 0, "num_predict": 512},
        "format": "json",
    }
    assert (r.text, r.input_tokens, r.output_tokens) == ('{"ok": true}', 120, 30)
    assert r.provider == "ollama" and not r.truncated


def test_ollama_prose_call_has_no_format(fake_ollama, clean_llm_env):
    llm.complete("write prose", provider="ollama", model="m", json_mode=False)
    assert "format" not in fake_ollama.sent[0]["json"]


def test_ollama_uses_configured_url_and_num_ctx(fake_ollama, clean_llm_env):
    clean_llm_env.setenv(llm.OLLAMA_URL_ENV_VAR, "http://gpu-box:11434/")
    clean_llm_env.setenv(llm.OLLAMA_NUM_CTX_ENV_VAR, "32768")
    llm.complete("p", provider="ollama", model="m")
    assert fake_ollama.sent[0]["url"] == "http://gpu-box:11434/api/chat"
    assert fake_ollama.sent[0]["json"]["options"]["num_ctx"] == 32768


def test_ollama_reads_saved_settings_when_env_absent(fake_ollama, clean_llm_env):
    from research_companion.store import load_root_settings, save_root_settings
    s = load_root_settings()
    s.update({"ollama_url": "http://saved:1234", "ollama_num_ctx": 8192})
    save_root_settings(s)
    llm.complete("p", provider="ollama", model="m")
    assert fake_ollama.sent[0]["url"] == "http://saved:1234/api/chat"
    assert fake_ollama.sent[0]["json"]["options"]["num_ctx"] == 8192


def test_ollama_truncation(fake_ollama, clean_llm_env):
    fake_ollama.state["payload"]["done_reason"] = "length"
    assert llm.complete("p", provider="ollama", model="m").truncated


def test_ollama_refuses_prompt_that_does_not_fit(fake_ollama, clean_llm_env):
    clean_llm_env.setenv(llm.OLLAMA_NUM_CTX_ENV_VAR, "4096")
    prompt = "x" * (4 * 3000)  # ~3000 tokens + 2048 output > 4096
    with pytest.raises(llm.LLMContextError) as ei:
        llm.complete(prompt, provider="ollama", model="m")
    msg = str(ei.value)
    assert "4,096" in msg and llm.OLLAMA_NUM_CTX_ENV_VAR in msg
    assert fake_ollama.sent == []  # never sent and hoped


def test_ollama_connection_failure_is_plain(fake_ollama, clean_llm_env):
    fake_ollama.state["raise"] = httpx.ConnectError("refused")
    with pytest.raises(llm.LLMConnectionError) as ei:
        llm.complete("p", provider="ollama", model="m")
    assert str(ei.value) == "Could not reach Ollama at http://localhost:11434. Is it running?"


def test_ollama_server_error_is_reported(fake_ollama, clean_llm_env):
    fake_ollama.state["payload"] = {"error": "model 'm' not found"}
    fake_ollama.state["status"] = 404
    with pytest.raises(llm.LLMError, match="model 'm' not found"):
        llm.complete("p", provider="ollama", model="m")


def test_ollama_requires_model(fake_ollama, clean_llm_env):
    with pytest.raises(llm.LLMConfigError, match=llm.MODEL_ENV_VAR):
        llm.complete("p", provider="ollama")
    assert fake_ollama.sent == []


def test_call_text_routes_local_providers_through_complete(fake_ollama, clean_llm_env):
    clean_llm_env.setenv(llm.PROVIDER_ENV_VAR, "ollama")
    clean_llm_env.setenv(llm.MODEL_ENV_VAR, "m")
    text, usage = llm.call_text("say json")
    assert text == '{"ok": true}'
    assert usage == {"input_tokens": 120, "output_tokens": 30, "truncated": False}
    # json_mode defaulted on, as the hosted seams do.
    assert fake_ollama.sent[0]["json"]["format"] == "json"


def test_existing_call_site_works_with_ollama(fake_ollama, clean_llm_env):
    """A real call site (the novelty agent's default llm) reaches Ollama."""
    from research_companion.agents.novelty import _default_llm
    clean_llm_env.setenv(llm.PROVIDER_ENV_VAR, "ollama")
    clean_llm_env.setenv(llm.MODEL_ENV_VAR, "m")
    assert json.loads(_default_llm("answer in json")) == {"ok": True}
