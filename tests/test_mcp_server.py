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
