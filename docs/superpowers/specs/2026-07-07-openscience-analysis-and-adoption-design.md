# OpenScience: Critical Analysis & Adoption Design (v0.6 "Trust Layer")

**Status:** Approved analysis; plan for post-EMNLP execution (nothing here
touches the July 10 submission).
**Subject repo:** https://github.com/synthetic-sciences/openscience
(Apache-2.0, TypeScript/Bun + React, ~1.1k stars, v1.2.10)

---

## 1. What OpenScience is

An autonomous research workbench: the user gives it a goal; an agent reads
literature, forms a hypothesis, writes and runs real code on real compute,
queries scientific databases, and writes up the result. Architecture (from
their ARCHITECTURE.md and README):

- Local-only CLI server (Bun) + React browser workspace; HTTP + SSE.
- Agent runtime with message loop, tool dispatch, compaction, provenance;
  agent registry (research / biology / physics / ml + read-only plan mode).
- **Skills** = instruction bundles loaded on demand from a hosted "Atlas"
  index (290+: ML training, evaluation, molecular biology, cheminformatics,
  papers/LaTeX/figures, cloud compute).
- **Science connectors** organized by domain (chemistry, genomics,
  literature, omics, pathways, proteins) covering UniProt, PDB, Ensembl,
  ChEMBL, PubChem, arXiv, OpenAlex, Semantic Scholar, "and around 30 more".
- TypeScript SDK generated from the server's OpenAPI contract; plugins can
  add tools, providers, and hooks.
- Explicitly **not sandboxed**: "the permission system keeps you aware of
  what the agent is doing; it is not an isolation boundary."

## 2. Critical analysis

**Strengths (real, worth respecting):** breadth of database connectors;
clean extension surface (skills / plugins / SDK-from-OpenAPI); local-first
posture; polished workspace UI with inline scientific rendering; a large
community validating demand for agentic research tooling.

**Weaknesses (from our vantage point):**
1. **No verification layer anywhere.** Nothing in the architecture verifies
   citations, grounds claims against sources, or evaluates agent outputs.
   The writeups are unverified LLM text — precisely the failure mode our
   EMNLP paper documents (lenient LLM reviewers, hallucinated citations).
2. **Unsandboxed autonomous code execution** — a different risk class from
   our read-and-analyze design.
3. **Stack**: Bun/Node + React build pipeline; embedding it would end our
   "one pip install, offline tests, no build step" reproducibility story.

## 3. Verdict: do NOT integrate the platform

Research Companion optimizes for **verifiability** ("a research assistant
you can verify"); OpenScience optimizes for **autonomy** ("it does the
science for you"). Embedding an unsandboxed autonomous executor would
dilute the exact claim our submission stakes out (C2: verifiability by
construction), double our runtime surface, and inherit an execution risk we
don't need — a draft review tool never needs to run experiments. License is
NOT the blocker (Apache-2.0 is MIT-compatible with attribution); thesis and
architecture are.

**The strategic insight instead:** the autonomous-science space has no
trust component. Rather than putting an agent inside Research Companion,
expose Research Companion **to** agents — become the verification layer
that stacks like OpenScience lack. They generate; we verify. That is
complementary positioning, not competition.

## 4. Adoption tracks (all RC-native re-implementations; no vendored TS)

### Track C — MCP Verification Server (flagship, do first)

**Goal:** any MCP-capable client (Claude Desktop, agent frameworks,
OpenScience via its MCP support) can call Research Companion's verification
machinery against a local workspace.

**Tool surface (initial 6):**
| MCP tool | Wraps (existing code) | Returns |
|---|---|---|
| `verify_citation(raw_ref)` | refcheck parse + default_lookup + validate_reference | verdict verified/suspect/unverified + matched record + reasons |
| `ground_claim(quote, paper_id?)` | qa's verbatim quote-verification helpers over library texts | found/not-found + source span location |
| `citation_coverage()` | citations_coverage.compute/load | counts + per-ref statuses |
| `search_library(query, k?)` | retrieve.rank_units (hybrid/BM25) | top sections w/ paper ids |
| `ask_library(question)` | qa.answer | grounded answer + citations + unverified-quote flags |
| `review_draft(paper_id?)` | review lanes (offline-safe subset by default) | lane reports incl. citation verdicts |

**Design decisions:**
- New module `research_companion/mcp_server.py` using the official `mcp`
  Python SDK as an **optional extra** (`pip install research-companion[mcp]`)
  — core install stays dependency-lean; module import is lazy/guarded like
  fastapi.
- Entry point: `research-companion mcp serve` (stdio transport first —
  what Claude Desktop consumes; SSE transport later if needed).
- Workspace-aware: `--workspace` flag / RESEARCH_COMPANION_WORKSPACE honored
  via the existing store resolution (no new code).
- Read-only by default; a `--allow-write` flag gates anything that mutates
  the store (adding papers) — verification tools never write.
- Tests: unit tests calling the tool functions directly (the SDK server is
  a thin registration layer); one smoke test that the server lists its
  tools; docs page with a Claude Desktop config snippet.
- Est: ~1.5 days incl. docs. Ships as v0.6.0's headline.

### Track A — Domain database connectors

**Goal:** citation verification, coverage auto-download, and the library
work for biology/chemistry/medicine drafts, not just CS/ML.

- New package `research_companion/connectors/` with a small protocol:
  `resolve(ref: Reference) -> record|None` and
  `fetch(identifier) -> PaperMetadata` (mirrors refcheck.retrieval +
  fetch.add_* patterns; connectors are pure-HTTP against public APIs, seam-
  injectable for tests, no new deps beyond httpx already present).
- Priority order by citation-graph value for paper-writing users:
  1. **PubMed/PMC** (E-utilities; DOI/PMID resolution + abstract fetch) —
     unlocks all of biomedicine; PMIDs become a paper-id namespace
     `pmid:...` following the existing `_id_to_dirname` conventions.
  2. **Europe PMC** (free full-text where available — feeds get_paper_text).
  3. **DBLP** (CS venue metadata — improves resolution precision for our
     current audience).
  4. Defer UniProt/PDB/ChEMBL-class *entity* databases: they are not paper
     sources; they fit a future "entity enrichment" feature (link extracted
     datasets/proteins to canonical records), tracked but not planned here.
- Wire-in points: refcheck `default_lookup` chain (resolution),
  `fetch.add_paper` routing (new id shapes), citations_coverage
  `resolve_reference` (searches), Settings toggle per connector.
- Est: ~1 day for PubMed+EuropePMC+DBLP with tests (fixture-based, seams).

### Track B — Skills & plugins

**Goal:** the extensibility the v0.3 brainstorm promised, in RC's idiom —
zero-runtime instruction packs first, code plugins second.

- **Review-skill packs (phase 1):** a skill = one markdown file with YAML
  front-matter (`name`, `description`, `applies_to: converse|suggestions|
  review`) in `<root>/skills/` (global) or `<workspace>/skills/`. Loaded
  packs inject venue/domain checklists into CONVERSE_PROMPT context and a
  deterministic suggestions rule ("checklist item X unaddressed in draft").
  Ship 2 built-ins as examples: `emnlp-reviewer.md` (structure/limitations/
  reproducibility checklist) and `clinical-reporting.md` (CONSORT-style).
  UI: Settings lists discovered skills with on/off toggles.
- **Code plugins (phase 2, later):** Python entry-point group
  `research_companion.plugins` allowing third parties to register
  connectors (Track A protocol) and review lanes. Explicitly deferred until
  a plugin author exists — YAGNI guard.
- Est: phase 1 ~1 day.

## 5. Enhancement over and above (the differentiator)

Combine C+A into a public positioning: **"the verification layer for
agentic science."** Concretely, after C ships: a docs page + example
showing an autonomous agent (Claude Desktop or OpenScience) drafting a
related-work section, then calling `verify_citation` + `ground_claim` on
its own output through RC — catching a fabricated reference live. That demo
writes itself against our existing corruption benchmark and is a follow-up
paper/blog seed no one else in that ecosystem can claim today.

## 6. Sequencing & verification

Order: **C → A → B** (strategic value, then audience, then extensibility),
each as its own wave with the established discipline (TDD, full gates,
live E2E, tag + PyPI). Target versions v0.6.0 (C), v0.6.x (A), v0.7.0 (B).
Verification per track is stated inline above; every track keeps the
degradation contract (no key / no network ⇒ existing behavior unchanged)
and the identity/commit rules of this repo.

## 7. Explicitly rejected (and why)

- Embedding OpenScience's agent/executor — thesis dilution, dual runtime,
  unsandboxed execution risk (Section 3).
- Vendoring their TS connectors — reimplementing thin HTTP clients in
  Python is cheaper than bridging runtimes.
- Experiment execution / code-running lanes in RC — out of scope for a
  verification tool; revisit only with sandboxing as a hard requirement.
- Inline molecule/genome rendering — serves their domains, not draft review.
