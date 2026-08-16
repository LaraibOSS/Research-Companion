"""Tests for the MCP server wiring — no live server, SDK-optional."""
import argparse
import importlib
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


# ---------------------------------------------------------------------------
# SDK version compatibility
#
# mcp 2.0 removed `mcp.server.fastmcp` and renamed FastMCP to MCPServer. The
# surface we use is unchanged, so both are supported. A dependency bump that
# widened the bound to <3 failed CI on exactly this, which is what these pin.
# ---------------------------------------------------------------------------

def test_both_known_sdk_layouts_are_tried_newest_first():
    paths = dict(mcp_server._SERVER_CLASS_PATHS)
    assert paths["mcp.server.mcpserver"] == "MCPServer"   # mcp >= 2.0
    assert paths["mcp.server.fastmcp"] == "FastMCP"       # mcp 1.x
    # newest first, so a dual-provider SDK resolves to the supported class
    assert mcp_server._SERVER_CLASS_PATHS[0][0] == "mcp.server.mcpserver"


def test_resolve_falls_through_to_the_older_layout(monkeypatch):
    """With only the 1.x layout importable, resolution must still succeed."""
    real = importlib.import_module

    def only_1x(name, *a, **kw):
        if name == "mcp.server.mcpserver":
            raise ImportError("no such module")
        return real(name, *a, **kw)

    monkeypatch.setattr(importlib, "import_module", only_1x)
    if _HAS_MCP:
        assert mcp_server._resolve_server_class() is not None


def test_an_unrecognised_sdk_is_not_reported_as_a_missing_one(monkeypatch):
    """The install hint would send the user to install what they already have.

    "pip install research-companion[mcp]" is the wrong instruction when the SDK
    is present but too new — the fix is a version bound, and the message has to
    say so or the user loops on a command that changes nothing.
    """
    monkeypatch.setattr(importlib, "import_module",
                        lambda name, *a, **kw: (_ for _ in ()).throw(ImportError(name)))
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    with pytest.raises(ImportError) as ei:
        mcp_server._resolve_server_class()
    msg = str(ei.value)
    assert "research-companion[mcp]" not in msg
    assert "mcp.server.mcpserver" in msg and "mcp.server.fastmcp" in msg


def test_a_genuinely_missing_sdk_still_gets_the_install_hint(monkeypatch):
    monkeypatch.setattr(importlib, "import_module",
                        lambda name, *a, **kw: (_ for _ in ()).throw(ImportError(name)))
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    with pytest.raises(ImportError) as ei:
        mcp_server._resolve_server_class()
    assert "research-companion[mcp]" in str(ei.value)


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
