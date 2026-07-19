"""MCP trust-layer server (v0.7.0) — expose verification tools to external agents.

Research Companion's strategic role is the *verifiable* layer other agents call:
they generate, it checks. This module registers the four deterministic, key-free,
zero-LLM-cost tools with an MCP server over stdio. The costed, key-requiring tools
(``ask_library`` / ``review_draft``) are also available, but only behind an
explicit opt-in (the ``mcp_costed_tools`` setting) AND a configured LLM key; each
call is further capped by the ``mcp_cost_cap_usd`` setting. This keeps the
default-on boundary safe to expose while letting users who want the LLM tools
turn them on deliberately.

The ``mcp`` SDK is an **optional dependency** (``pip install
'research-companion[mcp]'``): it is imported lazily inside :func:`create_server`
so importing this module — and running the rest of the CLI — never requires it.
The tool logic lives in :mod:`research_companion.mcp_tools` and is fully testable
without the SDK; the wrappers below only give the MCP interface clean,
schema-inferable signatures (no injectable ``lookup``, plain string args).
"""
from __future__ import annotations

from research_companion import mcp_tools

_MISSING_SDK_MSG = (
    "The MCP server needs the optional 'mcp' dependency. "
    "Install it with: pip install 'research-companion[mcp]'"
)


# --- MCP-facing tool wrappers (clean signatures for schema inference) -------

def verify_citation(title: str = "", doi: str = "", arxiv_id: str = "", raw: str = "") -> dict:
    """Validate a citation against authoritative records (CrossRef/OpenAlex/arXiv).

    Provide a title (and optionally authors via `raw`), a DOI, an arXiv id, or a
    raw reference string. Returns verified / suspect / unverified with reasons.
    """
    return mcp_tools.verify_citation(
        title=title or None, doi=doi or None, arxiv_id=arxiv_id or None, raw=raw or None)


def ground_claim(quote: str, paper_id: str) -> dict:
    """Check whether a quote appears verbatim in a stored paper's text.

    Returns whether it is grounded plus the exact character span. This is a
    literal (exact/whitespace-normalized) check, never a semantic judgement.
    """
    return mcp_tools.ground_claim(quote=quote, paper_id=paper_id)


def citation_coverage(paper_id: str) -> dict:
    """Report how much of a draft paper's bibliography is present in the library."""
    return mcp_tools.citation_coverage(paper_id=paper_id)


def search_library(query: str, k: int = 6) -> dict:
    """Keyword-search the local library; return grounded snippets with provenance."""
    return mcp_tools.search_library(query=query, k=k)


# name -> (handler, one-line description) registry — testable without the SDK.
TOOL_HANDLERS: dict[str, object] = {
    "verify_citation": verify_citation,
    "ground_claim": ground_claim,
    "citation_coverage": citation_coverage,
    "search_library": search_library,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "verify_citation": "Validate a citation against CrossRef/OpenAlex/arXiv.",
    "ground_claim": "Check a quote is verbatim-present in a paper; return its char span.",
    "citation_coverage": "How much of a draft's bibliography is in the local library.",
    "search_library": "BM25 keyword search over the library with grounded snippets.",
}


def ask_library(question: str, k: int = 6) -> dict:
    """Answer a question from the local library with cited sources (LLM; costed).

    Available only when the user enabled mcp_costed_tools AND an LLM key is
    configured; each call is refused if its estimated cost exceeds the
    mcp_cost_cap_usd setting.
    """
    return mcp_tools.ask_library(question=question, k=k)


def review_draft(paper_id: str, venue: str = "", fast: bool = False) -> dict:
    """Run the reviewer-style analysis on a stored paper (LLM lanes; costed, read-only)."""
    return mcp_tools.review_draft(paper_id=paper_id, venue=venue or None, fast=fast)


COSTED_TOOL_HANDLERS: dict[str, object] = {
    "ask_library": ask_library,
    "review_draft": review_draft,
}

COSTED_TOOL_DESCRIPTIONS: dict[str, str] = {
    "ask_library": "LLM Q&A over the local library with cited sources (costed; capped).",
    "review_draft": "Run the reviewer-style review of a stored paper (costed; capped; read-only).",
}


def costed_tools_active() -> bool:
    """True when the user opted in (mcp_costed_tools) AND a key matches the provider."""
    try:
        from research_companion.cost import configured_provider
        from research_companion.settings import get_settings
        return bool(get_settings().get("mcp_costed_tools")) and configured_provider() is not None
    except Exception:
        return False


def active_tool_names() -> list[str]:
    """The tool set create_server() would register right now (testable without the SDK)."""
    names = list(TOOL_HANDLERS)
    if costed_tools_active():
        names += list(COSTED_TOOL_HANDLERS)
    return names


def create_server(name: str = "research-companion"):
    """Build a FastMCP server with the base tools, plus costed tools when gated on.

    Raises ImportError (with an install hint) if the optional ``mcp`` SDK is absent.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised without the SDK installed
        raise ImportError(_MISSING_SDK_MSG) from exc

    server = FastMCP(name)
    for tool_name, handler in TOOL_HANDLERS.items():
        server.add_tool(handler, name=tool_name, description=TOOL_DESCRIPTIONS[tool_name])

    if costed_tools_active():
        for tool_name, handler in COSTED_TOOL_HANDLERS.items():
            server.add_tool(handler, name=tool_name,
                            description=COSTED_TOOL_DESCRIPTIONS[tool_name])
    return server


def serve(transport: str = "stdio") -> None:
    """Start the MCP server. Blocks until the client disconnects."""
    create_server().run(transport=transport)
