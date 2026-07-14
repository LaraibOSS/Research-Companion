# Release notes — 0.7

Research Companion 0.7 turns the tool inside-out: for two years it has *verified
its own answers*; now it exposes that verification to **other** agents. The
strategic bet (see `docs/superpowers/specs/2026-07-07-openscience-analysis-and-adoption-design.md`)
is that as autonomous research agents proliferate, the scarce, defensible role is
the **trust layer** — they generate, Research Companion checks.

---

## 0.7.1 — Near-duplicate / overlap detection

Completes the roadmap's integrity track (the remaining half of #13). A new
deterministic, **local-first** check flags passages in a paper that near-duplicate
another paper **in your own library** — self-plagiarism, duplicated passages, or a
draft too close to something already ingested.

- **Local by default, private, key-free:** k-word shingling over the existing
  tokenizer + containment scoring (`research_companion/overlap.py`); reuses the
  chunking char-offset provenance so each flagged passage is highlightable in the
  reader. Compares only against your local library — nothing leaves the machine.
- **Honest labeling:** findings are a *near-duplicate / textual overlap with library
  paper X (NN%)*, never "plagiarism" or "misconduct." Complements the existing
  *exact*-duplicate detector (`citations_coverage.find_library_duplicate`).
- **Surfaces:** an always-on `OverlapAgent` in `review`, a "Near-duplicate passages"
  report section, and `research-companion check-overlap <paper-id> [--json]`.
- **Opt-in external seam (consent-gated):** `check-overlap --external` can call a
  registered `ExternalOverlapProvider` (e.g. a web-corpus plagiarism API) for true
  cross-internet checking. **No provider ships by default**, and text is sent
  **only** when a provider is registered *and* consent is given — a guarantee
  covered by a test asserting the provider is never called otherwise. True
  web-corpus plagiarism is therefore available but never on by default.
- Modules: `research_companion/overlap.py`, `research_companion/agents/overlap.py`.
  Tests: `tests/test_overlap.py`, `tests/test_agents_overlap.py`.

**Upgrade notes:** none — additive; no new dependencies, no store/settings migration.

---

## 0.7.0 — MCP trust-layer server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes Research Companion's deterministic verification to any MCP-capable agent
(Claude Desktop, IDE agents, orchestration frameworks).

- **Start it:** `research-companion mcp serve` (stdio transport). Requires the
  optional dependency — `pip install 'research-companion[mcp]'`.
- **Four tools, all deterministic, key-free, and zero-LLM-cost** — safe to expose
  by default because they touch only the local store (plus, for citation checks,
  read-only scholarly-metadata lookups) and never spend API money:
  - **`verify_citation`** — validate a citation against CrossRef/OpenAlex/arXiv →
    verified / suspect / unverified with reasons.
  - **`ground_claim`** — check a quote appears verbatim in a stored paper and
    return its exact character span (literal, never semantic).
  - **`citation_coverage`** — how much of a draft's bibliography is in the library.
  - **`search_library`** — BM25 keyword search over the library with grounded
    snippets and char-offset provenance (no embeddings, so no key).
- **Design for testability & safety:** the tool *logic* lives in
  `research_companion/mcp_tools.py` — free of any MCP-SDK import, so it is fully
  unit-tested without the SDK or a live server. `research_companion/mcp_server.py`
  is a thin wrapper that lazily imports the SDK and registers the tools, so the
  base install and the rest of the CLI never depend on `mcp`.
- **Versioned contract:** `docs/mcp-schemas/tools.v1.json` documents the stable
  input/output schema external agents can rely on.
- **The cost-and-keys boundary is deliberate:** the tools that spend LLM money or
  need a key (`ask_library`, `review_draft`) are **held for 0.7.1** behind an
  explicit budget gate, so nothing exposed in 0.7.0 can run up a bill.

Modules: `research_companion/mcp_tools.py`, `research_companion/mcp_server.py`.
Tests: `tests/test_mcp_tools.py`, `tests/test_mcp_server.py`.

**Upgrade notes:** none — additive. The `mcp` dependency is optional; without it
everything except `mcp serve` works unchanged, and `mcp serve` prints a clear
install hint.
