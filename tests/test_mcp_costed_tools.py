"""Costed MCP tools: gates, refusals, error dicts (fully offline)."""
import json

from research_companion import mcp_tools, store


def _keyed(monkeypatch):
    monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def _settings(monkeypatch, cap=1.0):
    from research_companion.settings import DEFAULTS
    s = dict(DEFAULTS)
    s["mcp_cost_cap_usd"] = cap
    monkeypatch.setattr("research_companion.settings.get_settings", lambda: s)


_seed_counter = [0]


def _seed_paper_with_text(monkeypatch):
    _seed_counter[0] += 1
    pid = f"local:costed{_seed_counter[0]}"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "Attention is a mechanism that lets a model weigh "
                         "different parts of the input when producing output. "
                         "The transformer relies entirely on self-attention.")
    return pid


def test_ask_library_happy_path(monkeypatch):
    _keyed(monkeypatch)
    _settings(monkeypatch)
    _seed_paper_with_text(monkeypatch)  # mirror test_mcp_tools' store seeding style
    out = mcp_tools.ask_library(question="what is attention?",
                                llm=lambda p: "Attention is weighting [1].")
    assert "error" not in out
    assert out["answer"].startswith("Attention")
    assert isinstance(out["sources"], list)
    assert out["estimated_cost_usd"] > 0


def test_ask_library_over_cap_refuses_without_calling_llm(monkeypatch):
    _keyed(monkeypatch)
    _settings(monkeypatch, cap=0.0)   # everything is over a $0 cap
    calls = []
    out = mcp_tools.ask_library(question="q", llm=lambda p: calls.append(p) or "x")
    assert "error" in out and "cap" in out["error"]
    assert out["cap_usd"] == 0.0 and out["estimated_cost_usd"] > 0
    assert calls == []                # zero spend: llm never invoked


def test_ask_library_llm_failure_returns_error_dict(monkeypatch):
    _keyed(monkeypatch)
    _settings(monkeypatch)
    _seed_paper_with_text(monkeypatch)

    def _boom(p):
        raise RuntimeError("no api key")
    # Question shares vocabulary with the seeded text so BM25 actually
    # retrieves a unit and the llm callable gets invoked (a single-token
    # query like "q" tokenizes to [] and short-circuits before the LLM call).
    out = mcp_tools.ask_library(question="what is attention", llm=_boom)
    assert "error" in out             # never raises to the client


def test_ask_library_cited_sources_are_json_safe(monkeypatch):
    # Regression: ask_library's "cited" list must be JSON-serializable dicts,
    # not raw QASource dataclass instances. Use the REAL [S#] citation format
    # that qa.parse_citations matches so the cited path actually fires.
    _keyed(monkeypatch)
    _settings(monkeypatch)
    _seed_paper_with_text(monkeypatch)
    out = mcp_tools.ask_library(question="what is attention",
                                llm=lambda p: "Attention weights tokens [S1].")
    assert "error" not in out
    assert out["cited"], "cited must be non-empty to prove the citation path fired"
    json.dumps(out)  # must not raise


def test_review_draft_unknown_paper(monkeypatch):
    _keyed(monkeypatch)
    _settings(monkeypatch)
    out = mcp_tools.review_draft(paper_id="local:nope")
    assert "error" in out and "local:nope" in out["error"]


def test_review_draft_fast_estimates_zero_and_runs(monkeypatch):
    _keyed(monkeypatch)
    _settings(monkeypatch, cap=0.0)   # even a $0 cap admits a fast (LLM-free) review
    pid = _seed_paper_with_text(monkeypatch)
    monkeypatch.setattr("research_companion.review_runner.run_review",
                        lambda p, **kw: {"paper_id": p, "lanes": {"citation": {"ok": True}}})
    out = mcp_tools.review_draft(paper_id=pid, fast=True)
    assert out["paper_id"] == pid
    assert out["estimated_cost_usd"] == 0.0


def test_review_draft_full_over_cap_refuses(monkeypatch):
    _keyed(monkeypatch)
    _settings(monkeypatch, cap=0.0)
    pid = _seed_paper_with_text(monkeypatch)
    called = []
    monkeypatch.setattr("research_companion.review_runner.run_review",
                        lambda p, **kw: called.append(p) or {})
    out = mcp_tools.review_draft(paper_id=pid, fast=False)
    assert "error" in out and out["cap_usd"] == 0.0
    assert called == []               # runner never invoked over cap


def test_review_draft_runner_failure_returns_error_dict(monkeypatch):
    _keyed(monkeypatch)
    _settings(monkeypatch, cap=50.0)
    pid = _seed_paper_with_text(monkeypatch)

    def _boom(p, **kw):
        raise RuntimeError("pipeline exploded")
    monkeypatch.setattr("research_companion.review_runner.run_review", _boom)
    out = mcp_tools.review_draft(paper_id=pid, fast=False)
    assert "error" in out


def test_review_draft_corrupt_metadata_returns_error_dict(monkeypatch):
    # Regression: PaperMetadata.load()/load_text() sat outside the try/except
    # (only run_review was wrapped), so a corrupted metadata.json would
    # propagate and violate "never raises to the caller".
    _keyed(monkeypatch)
    _settings(monkeypatch)

    def _boom(paper_id):
        raise RuntimeError("corrupt")
    monkeypatch.setattr("research_companion.store.PaperMetadata.load", _boom)
    out = mcp_tools.review_draft(paper_id="x")
    assert "error" in out


# ---------------------------------------------------------------------------
# Self-hosted providers: a local model is $0; an unknown price is NOT $0.
# ---------------------------------------------------------------------------


def _self_hosted(monkeypatch, provider):
    monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", provider)
    monkeypatch.setenv("RESEARCH_COMPANION_MODEL", "local-model")
    monkeypatch.setenv("RESEARCH_COMPANION_BASE_URL", "http://localhost:8000/v1")


def test_ask_library_local_ollama_is_free_and_passes_a_zero_cap(monkeypatch):
    _self_hosted(monkeypatch, "ollama")
    _settings(monkeypatch, cap=0.0)
    _seed_paper_with_text(monkeypatch)
    out = mcp_tools.ask_library(question="what is attention",
                                llm=lambda p: "Attention weights tokens [S1].")
    assert "error" not in out
    assert out["estimated_cost_usd"] == 0.0


def test_ask_library_unknown_price_refuses_instead_of_passing_as_zero(monkeypatch):
    _self_hosted(monkeypatch, "openai_compatible")
    _settings(monkeypatch, cap=100.0)   # even the largest cap cannot check an unknown price
    calls = []
    out = mcp_tools.ask_library(question="q", llm=lambda p: calls.append(p) or "x")
    assert "price not known" in out["error"]
    assert out["estimated_cost_usd"] is None and out["cap_usd"] == 100.0
    assert calls == []


def test_review_draft_unknown_price_refuses_full_but_allows_fast(monkeypatch):
    _self_hosted(monkeypatch, "openai_compatible")
    _settings(monkeypatch, cap=100.0)
    pid = _seed_paper_with_text(monkeypatch)
    called = []
    monkeypatch.setattr("research_companion.review_runner.run_review",
                        lambda p, **kw: called.append(p) or {"paper_id": p})
    out = mcp_tools.review_draft(paper_id=pid, fast=False)
    assert "price not known" in out["error"] and called == []
    # The fast review makes no model call, so its cost is known: $0.
    out = mcp_tools.review_draft(paper_id=pid, fast=True)
    assert out["estimated_cost_usd"] == 0.0 and called == [pid]
