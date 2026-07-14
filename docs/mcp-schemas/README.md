# MCP tool schemas

Versioned JSON schemas for the tools exposed by the Research Companion MCP
trust-layer server (`research-companion mcp serve`). These document the stable
contract external agents can rely on; the schema `version` is bumped when a
tool's input/output shape changes.

- **`tools.v1.json`** — v0.7.0 tool surface: the four **deterministic, key-free,
  zero-LLM-cost** tools (`verify_citation`, `ground_claim`, `citation_coverage`,
  `search_library`). Safe to expose by default: they touch only the local store
  (plus, for `verify_citation`, read-only scholarly-metadata lookups) and never
  spend API money or require a key.

The costed, key-requiring tools (`ask_library`, `review_draft`) are deferred to
v0.7.1 behind an explicit budget gate — the "cost-and-keys boundary" — and will
ship as `tools.v2.json`.

The server lives in `research_companion/mcp_server.py`; the tool logic (usable and
testable without the MCP SDK) is in `research_companion/mcp_tools.py`. Install the
optional dependency with `pip install 'research-companion[mcp]'`.
