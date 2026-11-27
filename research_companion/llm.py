"""The one model layer.

Every model call in the package goes through here: one provider/model
resolution order, one default-model table, one place that knows how each
provider is spoken to, and one result shape that says whether the answer was
cut off by the output limit.

Resolution order (``resolve_provider_and_model``): an explicit argument wins,
then the environment (``RESEARCH_COMPANION_PROVIDER`` /
``RESEARCH_COMPANION_MODEL``, which the Settings page mirrors into
``os.environ``), then the default. Provider-specific server settings (base
URL, Ollama URL and context length) are read from the environment first and
then from the saved settings file, because a server restarted after the user
saved them has the file but not the environment.

Providers:

- ``anthropic`` / ``openai``: the hosted APIs through their SDKs.
- ``openai_compatible``: any server speaking the OpenAI chat API (vLLM,
  LM Studio, llama.cpp server, ...), through the ``openai`` SDK with a
  ``base_url``. The API key is optional.
- ``ollama``: Ollama's NATIVE ``/api/chat``, over httpx. Not its
  OpenAI-compatible endpoint: that endpoint cannot set the context length, and
  Ollama's default context is far smaller than this app's ~12k-token
  extraction prompt -- the prompt would be silently cut from the front.

The two local/self-hosted providers have no default model: guessing a model
name the user's server does not have only moves the failure somewhere less
clear. A missing model raises ``LLMConfigError`` naming the setting.

Legacy seam: many tests monkeypatch ``extract._call_anthropic`` /
``extract._call_openai``. ``call_text`` therefore routes the two hosted
providers through those module attributes (which themselves delegate to
``complete``), so a monkeypatch there still intercepts every call site.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

PROVIDER_ENV = "RESEARCH_COMPANION_PROVIDER"
MODEL_ENV = "RESEARCH_COMPANION_MODEL"
BASE_URL_ENV = "RESEARCH_COMPANION_BASE_URL"
API_KEY_ENV = "RESEARCH_COMPANION_API_KEY"
OLLAMA_URL_ENV = "RESEARCH_COMPANION_OLLAMA_URL"
OLLAMA_NUM_CTX_ENV = "RESEARCH_COMPANION_OLLAMA_NUM_CTX"

DEFAULT_PROVIDER = "anthropic"
PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "openai_compatible", "ollama")

# The ONE default-model table. Providers absent from it have no default: the
# user must name the model their own server runs.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-7",
    "openai": "gpt-4o-2024-11-20",
}
_NO_DEFAULT_MODEL = frozenset({"openai_compatible", "ollama"})

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_NUM_CTX = 16384
MIN_OLLAMA_NUM_CTX = 2048
MAX_OLLAMA_NUM_CTX = 1_048_576

# Placeholder sent when an OpenAI-compatible server needs no key: the SDK
# refuses to construct a client without one.
_NO_KEY_PLACEHOLDER = "not-needed"

# Hosted providers whose API key env var must be set before a call can work.
KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai_compatible": API_KEY_ENV,
}
KEY_REQUIRED = frozenset({"anthropic", "openai"})

_OLLAMA_TIMEOUT_S = 600.0


class LLMError(RuntimeError):
    """A model call could not be made or completed, with a plain-language reason."""


class LLMConfigError(LLMError):
    """The provider is not configured well enough to make a call."""


class LLMConnectionError(LLMError):
    """A local or self-hosted server could not be reached."""


class LLMContextError(LLMError):
    """The request would not fit in the configured context length."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    provider: str
    model: str

    @property
    def truncated(self) -> bool:
        """True when the provider reports the answer was cut at the output limit."""
        return self.stop_reason in ("max_tokens", "length")

    def usage(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def default_model(provider: str) -> str | None:
    return DEFAULT_MODELS.get(provider)


def resolve_provider_and_model(provider: str | None = None, model: str | None = None,
                               *, default_model: bool = True) -> tuple[str, str | None]:
    """(provider, model): explicit argument, then environment, then default.

    The model is None only for a provider with no default model (or when
    ``default_model=False`` and none was given) -- the caller decides whether
    that is an error, so building a callable never fails before it is used.
    """
    p = (provider or os.environ.get(PROVIDER_ENV, "") or "").strip().lower() or DEFAULT_PROVIDER
    m = (model or os.environ.get(MODEL_ENV, "") or "").strip() or None
    if m is None and default_model:
        m = DEFAULT_MODELS.get(p)
    return p, m


def resolve_model(provider: str, model: str | None = None) -> str:
    """The model to use for *provider*, falling back to its default.

    An unrecognised provider falls back to the Anthropic default (the
    long-standing behaviour). A provider with no default and no model raises
    ``LLMConfigError`` naming the setting.
    """
    if model:
        return model
    if provider in _NO_DEFAULT_MODEL:
        raise LLMConfigError(
            f"No model name is set for provider {provider!r}. Set the model in "
            f"Settings (Model) or with {MODEL_ENV}."
        )
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS[DEFAULT_PROVIDER])


def _saved_setting(key: str):
    try:
        from research_companion.store import load_root_settings
        return load_root_settings().get(key)
    except Exception:  # noqa: BLE001 — settings trouble must not break a call
        return None


def _config_str(env_var: str, settings_key: str, default: str) -> str:
    val = (os.environ.get(env_var) or "").strip()
    if val:
        return val
    saved = _saved_setting(settings_key)
    if isinstance(saved, str) and saved.strip():
        return saved.strip()
    return default


def base_url() -> str:
    """The OpenAI-compatible server's base URL, or "" when not set."""
    return _config_str(BASE_URL_ENV, "base_url", "")


def ollama_url() -> str:
    return _config_str(OLLAMA_URL_ENV, "ollama_url", DEFAULT_OLLAMA_URL).rstrip("/")


def ollama_num_ctx() -> int:
    raw = (os.environ.get(OLLAMA_NUM_CTX_ENV) or "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError as e:
            raise LLMConfigError(
                f"{OLLAMA_NUM_CTX_ENV} must be a whole number of tokens, got {raw!r}."
            ) from e
    saved = _saved_setting("ollama_num_ctx")
    if isinstance(saved, int) and not isinstance(saved, bool):
        return saved
    return DEFAULT_OLLAMA_NUM_CTX


def provider_ready(provider: str, model: str | None = None) -> bool:
    """True when *provider* has what it needs to attempt a call.

    Hosted providers need their API key. The self-hosted ones need no key
    (optional for openai_compatible) but have no default model, so they need a
    model name -- and openai_compatible needs a base URL. Pure presence checks:
    no network.
    """
    if provider in KEY_REQUIRED:
        return bool(os.environ.get(KEY_ENV[provider]))
    if provider == "ollama":
        return bool(model)
    if provider == "openai_compatible":
        return bool(model) and bool(base_url())
    return False


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _anthropic(prompt: str, *, system: str | None, model: str,
               max_output_tokens: int) -> LLMResult:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    kwargs: dict = {
        "model": model,
        "max_tokens": max_output_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system is not None:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return LLMResult(
        text=text,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        stop_reason=getattr(resp, "stop_reason", None),
        provider="anthropic",
        model=model,
    )


def openai_request_kwargs(*, model: str, max_output_tokens: int, json_mode: bool,
                          prompt: str = "") -> dict:
    """Request kwargs for an OpenAI-API chat call. json_mode forces a JSON
    object response (extraction/novelty/alignment need it); prose callers
    (qa, compare narrative) must pass json_mode=False or the model mangles
    free text.

    Safety net: OpenAI REJECTS ``response_format=json_object`` outright (HTTP
    400) unless the messages contain the word "json". A prose prompt routed
    here in JSON mode is a wiring mistake, and forcing the format would fail
    the whole request; dropping it degrades to a working prose call instead.
    ``prompt=""`` (callers that do not pass it) keeps the previous behavior.
    """
    kwargs = {
        "model": model,
        "max_tokens": max_output_tokens,
        "temperature": 0.0,
    }
    if json_mode and (not prompt or "json" in prompt.lower()):
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def _openai_messages(prompt: str, system: str | None) -> list[dict]:
    msgs: list[dict] = []
    if system is not None:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return msgs


def _openai_result(resp, *, provider: str, model: str) -> LLMResult:
    choice = resp.choices[0]
    return LLMResult(
        text=(choice.message.content or "").strip(),
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        stop_reason=getattr(choice, "finish_reason", None),
        provider=provider,
        model=model,
    )


def _openai(prompt: str, *, system: str | None, model: str, max_output_tokens: int,
            json_mode: bool) -> LLMResult:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        messages=_openai_messages(prompt, system),
        **openai_request_kwargs(model=model, max_output_tokens=max_output_tokens,
                                json_mode=json_mode, prompt=prompt),
    )
    return _openai_result(resp, provider="openai", model=model)


def _openai_compatible(prompt: str, *, system: str | None, model: str,
                       max_output_tokens: int, json_mode: bool) -> LLMResult:
    import openai
    url = base_url()
    if not url:
        raise LLMConfigError(
            "No server address is set for the OpenAI-compatible provider. Set "
            f"Settings > Server URL or {BASE_URL_ENV} (for example "
            "http://localhost:8000/v1)."
        )
    key = (os.environ.get(API_KEY_ENV) or "").strip() or _NO_KEY_PLACEHOLDER
    client = openai.OpenAI(base_url=url, api_key=key)
    try:
        resp = client.chat.completions.create(
            messages=_openai_messages(prompt, system),
            **openai_request_kwargs(model=model, max_output_tokens=max_output_tokens,
                                    json_mode=json_mode, prompt=prompt),
        )
    except openai.APIConnectionError as e:
        raise LLMConnectionError(
            f"Could not reach the OpenAI-compatible server at {url}. Is it running?"
        ) from e
    return _openai_result(resp, provider="openai_compatible", model=model)


def _ollama(prompt: str, *, system: str | None, model: str, max_output_tokens: int,
            json_mode: bool) -> LLMResult:
    import httpx

    from research_companion.cost import chars_to_tokens

    url = ollama_url()
    num_ctx = ollama_num_ctx()

    # Refuse rather than send and hope: Ollama silently drops the start of a
    # prompt that exceeds num_ctx, which for extraction is the paper itself.
    est_prompt = chars_to_tokens(len(prompt) + len(system or ""))
    needed = est_prompt + max_output_tokens
    if needed > num_ctx:
        raise LLMContextError(
            f"This request needs about {needed:,} tokens (prompt ~{est_prompt:,} + up to "
            f"{max_output_tokens:,} for the answer), but the Ollama context length is "
            f"{num_ctx:,}. Raise it in Settings (Context length) or with "
            f"{OLLAMA_NUM_CTX_ENV}, within what the model supports."
        )

    body: dict = {
        "model": model,
        "messages": _openai_messages(prompt, system),
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0, "num_predict": max_output_tokens},
    }
    # Same safety net as the OpenAI path: JSON is forced only when the prompt
    # actually asks for JSON, so a prose prompt is never coerced into an object.
    if json_mode and "json" in prompt.lower():
        body["format"] = "json"

    try:
        resp = httpx.post(f"{url}/api/chat", json=body,
                          timeout=httpx.Timeout(_OLLAMA_TIMEOUT_S, connect=10.0))
    except httpx.ConnectError as e:
        raise LLMConnectionError(f"Could not reach Ollama at {url}. Is it running?") from e
    except httpx.TimeoutException as e:
        raise LLMConnectionError(
            f"Ollama at {url} did not answer within {int(_OLLAMA_TIMEOUT_S)} seconds."
        ) from e
    except httpx.HTTPError as e:
        raise LLMConnectionError(f"Could not reach Ollama at {url}: {e}") from e

    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or not isinstance(data, dict) or data.get("error"):
        detail = data.get("error") if isinstance(data, dict) else None
        raise LLMError(
            f"Ollama at {url} refused the request (HTTP {resp.status_code}): "
            f"{detail or 'no detail given'}"
        )
    message = data.get("message") or {}
    return LLMResult(
        text=(message.get("content") or "").strip(),
        input_tokens=int(data.get("prompt_eval_count") or 0),
        output_tokens=int(data.get("eval_count") or 0),
        stop_reason=data.get("done_reason"),
        provider="ollama",
        model=model,
    )


def complete(prompt: str, *, provider: str | None = None, model: str | None = None,
             max_output_tokens: int = 2048, json_mode: bool = False,
             system: str | None = None) -> LLMResult:
    """Make one model call and return its text, usage and stop reason.

    Raises ``LLMConfigError`` when the provider lacks a required setting,
    ``LLMConnectionError`` when a self-hosted server cannot be reached,
    ``LLMContextError`` when the request would not fit Ollama's context, and
    ``ValueError`` for an unknown provider. Hosted-SDK errors propagate as-is.
    """
    p, m = resolve_provider_and_model(provider, model)
    if p not in PROVIDERS:
        raise ValueError(f"unknown provider {p!r} (expected one of {', '.join(PROVIDERS)})")
    m = resolve_model(p, m)
    if p == "anthropic":
        return _anthropic(prompt, system=system, model=m, max_output_tokens=max_output_tokens)
    if p == "openai":
        return _openai(prompt, system=system, model=m, max_output_tokens=max_output_tokens,
                       json_mode=json_mode)
    if p == "openai_compatible":
        return _openai_compatible(prompt, system=system, model=m,
                                  max_output_tokens=max_output_tokens, json_mode=json_mode)
    return _ollama(prompt, system=system, model=m, max_output_tokens=max_output_tokens,
                   json_mode=json_mode)


# ---------------------------------------------------------------------------
# Call-site helpers
# ---------------------------------------------------------------------------

def call_text(prompt: str, *, provider: str | None = None, model: str | None = None,
              json_mode: bool | None = None,
              max_output_tokens: int | None = None) -> tuple[str, dict]:
    """(text, usage) for one call -- the shape every call site already used.

    ``json_mode``/``max_output_tokens`` left as None mean "the callee's
    default" (JSON mode on, 2048 tokens), and are then not passed to the
    legacy ``extract._call_*`` seams, so a test fake with a narrow signature
    keeps working. An unrecognised provider name routes to Anthropic, as every
    call site did before this layer existed.
    """
    p, m = resolve_provider_and_model(provider, model)
    if p in _NO_DEFAULT_MODEL:
        r = complete(prompt, provider=p, model=m,
                     max_output_tokens=max_output_tokens or 2048,
                     json_mode=True if json_mode is None else json_mode)
        return r.text, r.usage()

    from research_companion import extract  # the monkeypatchable seams

    kw: dict = {}
    if max_output_tokens is not None:
        kw["max_output_tokens"] = max_output_tokens
    if p == "openai":
        if json_mode is not None:
            kw["json_mode"] = json_mode
        return extract._call_openai(prompt, model=resolve_model(p, m), **kw)
    return extract._call_anthropic(prompt, model=resolve_model(p, m), **kw)


def text_callable(provider: str | None = None, model: str | None = None, *,
                  json_mode: bool | None = None,
                  max_output_tokens: int | None = None) -> Callable[[str], str]:
    """A ``prompt -> text`` callable with provider/model resolved NOW.

    Building it never fails: a missing model for a provider without a default
    is reported when the callable is invoked, not when it is constructed.
    """
    p, m = resolve_provider_and_model(provider, model)

    def _llm(prompt: str) -> str:
        text, _usage = call_text(prompt, provider=p, model=m, json_mode=json_mode,
                                 max_output_tokens=max_output_tokens)
        return text

    return _llm
