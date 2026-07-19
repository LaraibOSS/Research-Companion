"""Tests for the MCP server wiring — no live server, SDK-optional."""
import argparse
import importlib.util
import io
import json
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from research_companion import mcp_server, store
from research_companion.cli import _cmd_mcp_serve

_HAS_MCP = importlib.util.find_spec("mcp") is not None
_SCHEMA = Path(__file__).resolve().parents[1] / "docs" / "mcp-schemas" / "tools.v1.json"

EXPECTED_TOOLS = {"verify_citation", "ground_claim", "citation_coverage", "search_library"}


def test_module_imports_without_sdk():
    # Importing the server module must never require the optional mcp SDK.
    assert set(mcp_server.TOOL_HANDLERS) == EXPECTED_TOOLS
    assert set(mcp_server.TOOL_DESCRIPTIONS) == EXPECTED_TOOLS


def test_wrappers_delegate_to_tool_logic():
    store.PaperMetadata(paper_id="local:m1", title="T", authors=[]).save()
    store.save_text("local:m1", "The model uses contrastive learning objectives.")
    res = mcp_server.search_library(query="contrastive learning", k=3)
    assert res["results"] and res["results"][0]["paper_id"] == "local:m1"


def test_ground_claim_wrapper():
    store.PaperMetadata(paper_id="local:m2", title="T", authors=[]).save()
    store.save_text("local:m2", "We introduce a novel benchmark for evaluation.")
    res = mcp_server.ground_claim(quote="a novel benchmark for evaluation", paper_id="local:m2")
    assert res["grounded"] is True


def test_schema_matches_registered_tools():
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["tools"]) == EXPECTED_TOOLS
    assert schema["version"] == 1


@pytest.mark.skipif(_HAS_MCP, reason="mcp SDK is installed; friendly-error path not exercised")
def test_create_server_without_sdk_raises_hint():
    with pytest.raises(ImportError) as ei:
        mcp_server.create_server()
    assert "research-companion[mcp]" in str(ei.value)


@pytest.mark.skipif(_HAS_MCP, reason="mcp SDK is installed; would start a real server")
def test_cli_mcp_serve_reports_missing_sdk():
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = _cmd_mcp_serve(argparse.Namespace(transport="stdio"))
    assert rc == 1
    assert "mcp" in buf.getvalue().lower()


@pytest.mark.skipif(not _HAS_MCP, reason="mcp SDK not installed")
def test_create_server_builds_when_sdk_present():
    server = mcp_server.create_server()
    assert server is not None


COSTED_TOOLS = {"ask_library", "review_draft"}


def _gate_on(monkeypatch):
    from research_companion.settings import DEFAULTS
    s = dict(DEFAULTS)
    s["mcp_costed_tools"] = True
    monkeypatch.setattr("research_companion.settings.get_settings", lambda: s)
    monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_default_active_tools_is_v1_set(monkeypatch):
    from research_companion.settings import DEFAULTS
    monkeypatch.setattr("research_companion.settings.get_settings", lambda: dict(DEFAULTS))
    assert set(mcp_server.active_tool_names()) == set(EXPECTED_TOOLS)


def test_gate_on_with_key_adds_costed_tools(monkeypatch):
    _gate_on(monkeypatch)
    assert set(mcp_server.active_tool_names()) == set(EXPECTED_TOOLS) | COSTED_TOOLS


def test_gate_on_without_key_hides_costed_tools(monkeypatch):
    from research_companion.settings import DEFAULTS
    s = dict(DEFAULTS)
    s["mcp_costed_tools"] = True
    monkeypatch.setattr("research_companion.settings.get_settings", lambda: s)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)
    assert set(mcp_server.active_tool_names()) == set(EXPECTED_TOOLS)


def test_v2_schema_matches_costed_registry():
    import json
    from pathlib import Path
    schema = json.loads(Path("docs/mcp-schemas/tools.v2.json").read_text(encoding="utf-8"))
    assert set(schema["tools"]) == set(EXPECTED_TOOLS) | COSTED_TOOLS
    assert schema["version"] == 2


def test_costed_wrappers_delegate(monkeypatch):
    called = {}
    monkeypatch.setattr("research_companion.mcp_tools.ask_library",
                        lambda **kw: called.setdefault("ask", kw) or {"answer": "x"})
    monkeypatch.setattr("research_companion.mcp_tools.review_draft",
                        lambda **kw: called.setdefault("rev", kw) or {"lanes": {}})
    mcp_server.ask_library("q", k=3)
    mcp_server.review_draft("p1", venue="", fast=True)
    assert called["ask"]["question"] == "q" and called["ask"]["k"] == 3
    assert called["rev"]["paper_id"] == "p1" and called["rev"]["venue"] is None
