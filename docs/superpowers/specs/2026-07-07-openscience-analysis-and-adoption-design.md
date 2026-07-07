# OpenScience: Critical Analysis & Adoption Design (v0.6 "Trust Layer")

**Status:** Analysis + design revised after critical review (2026-07-07);
plan for post-EMNLP execution (nothing here touches the July 10 submission).
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
1. **I did not find an explicit verification layer in the reviewed
   architecture.** Nothing in the documented design verifies citations,
   grounds claims against sources, or evaluates agent outputs — the failure
   mode our EMNLP paper documents (lenient LLM reviewers, hallucinated
   citations).
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

**The strategic insight instead:** many autonomous-science workflows still
lack a dedicated, inspectable trust layer for citation verification, claim
grounding, and source coverage. Rather than putting an agent inside
Research Companion, expose Research Companion **to** agents — position it
as **the trust layer for literature-backed claims, citations, and
source-grounded research writing in agentic workflows**. They generate; we
verify what we can verify — and state plainly what we cannot (see §5a).

## 3a. Legal & attribution precautions

- **No source copying.** All adoption is independent Python
  reimplementation of publicly documented ideas and public API surfaces;
  no OpenScience code is vendored or translated.
- **No implied endorsement or affiliation.** Docs say "compatible with
  MCP-capable research agents, including tools such as OpenScience where
  supported" — never "OpenScience integration."
- **No third-party branding in product positioning**; their project is
  citable as an example in docs/blogs only.
- **Comparative claims are phrased as observations of the reviewed
  architecture** ("I did not find…"), not absolutes about their codebase.

## 4. Adoption tracks (all RC-native re-implementations; no vendored TS)

### Track C — MCP Trust-Layer Server (flagship, do first)

**Goal:** any MCP-capable client (Claude Desktop, agent frameworks, other
research tools) can call Research Companion's verification machinery
against a local workspace.

**v0.6.0 tool surface — deterministic, zero-cost, key-free ONLY:**
| MCP tool | Wraps (existing code) | Verdicts |
|---|---|---|
| `verify_citation(raw_ref)` | refcheck parse + default_lookup + validate_reference | verified / suspect / unverified |
| `ground_claim(quote, paper_id?)` | qa's verbatim quote-verification over library texts | found / not_found (+ span) |
| `citation_coverage()` | citations_coverage payload (already stable JSON) | per-ref in_library / available / unchecked / unresolved |
| `search_library(query, k?)` | retrieve.rank_units (BM25; hybrid when token present) | ranked sections |

**v0.6.1 adds the LLM-spending tools** behind explicit cost warnings and
per-session call budgets: `ask_library(question)` (grounded QA; needs
provider key, costs per call) and `review_draft(paper_id?)` (lane reports;
long-running job semantics). Rationale: the v0.6.0/0.6.1 boundary is the
**cost-and-keys boundary** — an agent loop can never spend the user's
money or require configuration against v0.6.0 tools.

**Verdict semantics (per tool — citation-verified ≠ claim-supported):**
- `verify_citation`: *verified* = authoritative record matches (title
  similarity ≥ 0.9, author overlap ≥ 0.6, no identifier conflict — the
  existing refcheck thresholds, documented in the response); *suspect* =
  partial match (title matches but authors/year/identifier conflict);
  *unverified* = no plausible record found.
- `ground_claim`: **verbatim-presence check only** — *found* (with source
  span) / *not_found*. It does NOT assess whether a source semantically
  supports a claim; **semantic entailment is explicitly out of scope** and
  the tool description says so. A real paper can be cited for a false
  claim; this tool cannot detect that, and must not imply it can.
- `citation_coverage`: the existing four statuses, unchanged.

**Response schemas:** every tool returns versioned, strictly data-shaped
JSON — `{"schema_version": 1, ...}` — with shapes derived from existing
artifacts (RefVerdict, the coverage payload, rank_units results). JSON
Schema files ship in-repo (`docs/mcp-schemas/`). Evolution policy:
additive-only within a schema major. Schemas are also a **security
control**: results are data, never instruction-shaped prose (see below).

**Security model (expanded after review):**
- **Store-only principle:** tools may return only store-derived artifacts —
  ingested papers, the draft, computed verdicts. Never filesystem paths,
  environment variables, or any content outside `papergraph_dir()`. All
  access goes through existing store loaders keyed by paper ids, so there
  is no path/traversal surface by construction.
- **Workspace pinned at startup** (`--workspace` / env var via the existing
  resolution); no client-controlled workspace switching. A consent banner
  at server start names the workspace being served to MCP clients.
- **Read-only by default.** The optional write path (adding papers) is
  gated by `--allow-write` and reuses the existing job machinery — no
  parallel write path. Lab server + MCP server concurrent READ access to
  the same workspace is safe (documented); writes remain single-path.
- **Audit log:** every MCP call (tool, arguments hash, result size,
  duration) is appended via the existing EventLog machinery.
- **Abuse/loop protection:** per-session rate limits on network-touching
  tools; `verify_citation` results cached keyed on the raw reference
  string (reusing the coverage-cache pattern) so an agent retry loop
  cannot hammer CrossRef/OpenAlex.
- **Output limits:** hard cap on characters per result; long texts are
  span-referenced, not dumped.
- **Prompt-injection posture:** paper text is untrusted input that flows
  into the calling agent's context through our results; strict schemas +
  span references (instead of large verbatim text blocks) minimize the
  injection surface.

**Implementation shape:** new module `research_companion/mcp_server.py`
using the official `mcp` Python SDK as an optional extra
(`pip install research-companion[mcp]`); lazy/guarded import like fastapi;
entry point `research-companion mcp serve` (stdio transport first — what
Claude Desktop consumes). Tests: direct tool-function unit tests, a
tools-listing smoke test, schema-validation tests, store-only/limit tests.

### Track A — Domain database connectors

**Goal:** citation verification, coverage auto-download, and the library
work for biology/chemistry/medicine drafts, not just CS/ML.

- New package `research_companion/connectors/` with a small protocol:
  `resolve(ref: Reference) -> record|None` and
  `fetch(identifier) -> PaperMetadata` (mirrors refcheck.retrieval +
  fetch.add_* patterns; pure-HTTP against public APIs, seam-injectable, no
  new deps beyond httpx).
- Priority: **PubMed/PMC** (E-utilities; `pmid:` id namespace), **Europe
  PMC** (free full text where available), **DBLP** (CS venue metadata).
  UniProt/PDB/ChEMBL-class *entity* databases stay deferred — they are not
  paper sources; they fit a future entity-enrichment feature.
- **Identity model (the hard part, made explicit):** canonical-id
  precedence DOI > PMID/PMCID > arXiv > DBLP key; `alt_ids` aliasing field
  on PaperMetadata so one paper found via several sources stays one paper;
  preprint↔published pairs surfaced as a warning on the paper card, never
  auto-merged; Unicode/whitespace normalization via the existing
  normalize_title; venue-name variants handled in matching, not identity.
  Rate limits and API failures degrade gracefully (existing failures
  machinery); connectors change nothing for CS/ML users unless enabled
  (Settings toggle per connector, off ⇒ byte-identical behavior).

### Track B — Skills & plugins

**Goal:** the extensibility the v0.3 brainstorm promised, in RC's idiom —
zero-runtime instruction packs first, code plugins second.

- **Review-skill packs (phase 1):** a skill = one markdown file with YAML
  front-matter (`name`, `version`, `description`, `applies_to:
  converse|suggestions|review`) in `<root>/skills/` (global) or
  `<workspace>/skills/`. Loaded packs inject venue/domain checklists into
  CONVERSE_PROMPT context and a deterministic suggestions rule. Ship 2
  built-ins: `emnlp-reviewer.md`, `clinical-reporting.md`.
- **Reproducibility guarantees (added after review):** deterministic load
  order (built-ins first, then path-sorted); every affected output/report
  carries a provenance line ("skills active: emnlp-reviewer@1, …"); a safe
  mode runs built-ins only; malformed front-matter fails safe (skill
  skipped with a visible warning, never a crash); skill `version` required.
- **Code plugins (phase 2, deferred until a real plugin author exists):**
  Python entry-point group `research_companion.plugins` registering
  connectors (Track A protocol) and review lanes.

## 5. Enhancement over and above (the differentiator)

After Track C ships: a docs page + example showing an agent (e.g. Claude
Desktop, or any MCP-capable research tool) drafting a related-work section,
then calling `verify_citation` + `ground_claim` on its own output through
Research Companion — catching a fabricated reference live against our
existing corruption benchmark. A follow-up paper/blog seed.

## 5a. What we can and cannot verify (public honesty line)

Can: bibliographic existence and identity of citations; verbatim presence
of quoted text in sources; reference-list coverage of a draft; grounded
answers over the local library with flagged unverifiable quotes; the
deterministic review-lane checks. Cannot: whether an experiment was run
correctly, whether code is scientifically valid, whether a result is true,
or whether a cited (real) source semantically supports the claim it is
attached to. Public positioning must never blur this line.

## 6. Release acceptance criteria

**Track C (v0.6.0)** releases only when: `research-companion mcp serve`
starts with the core install unchanged; `[mcp]` extra installs the SDK;
the server exposes exactly the four documented tools; all outputs validate
against the shipped schemas; tests cover direct tool calls, tool listing,
schema validation, store-only containment, output limits, and rate-limit
behavior; no-write mode is default; the full existing suite passes without
the extra installed; docs include a Claude Desktop config and the
agent-verification demo; every MCP call lands in the audit log.

**Track A** releases only when: DOI/PMID/PMCID/arXiv/DBLP identity
collisions are fixture-tested; network failure degrades gracefully; all
connector tests run offline via seams; disabled connectors leave existing
behavior byte-identical.

**Track B** releases only when: load order is deterministic and tested;
active skills appear as provenance in outputs; invalid skill files fail
safe with a warning; both built-ins have tests.

## 7. Estimates & sequencing

Release-quality estimates (tests, docs, packaging, security hardening, live
E2E, tagged release — distinguished from prototype time, which is roughly a
third of these): **Track C core 2–3 days; Track A 2–3 days; Track B 1.5–2
days.** These sit below generic-project corrections because this repo's
optional-extra guards, CLI wiring, drift-guard patterns, and release
automation already exist and are exercised weekly (measured wave velocity:
v0.4.0 and v0.5.0 each shipped in a day at release quality).

Order: **v0.6.0** MCP core (4 deterministic tools) → **v0.6.1** ask_library
+ review_draft (cost-gated) → **v0.6.x** connectors (PubMed, Europe PMC,
DBLP) → **v0.7.0** skill packs. Every wave keeps the degradation contract
(feature off / no key / no network ⇒ existing behavior unchanged) and this
repo's identity/commit rules.

## 8. Explicitly rejected (and why)

- Embedding OpenScience's agent/executor — thesis dilution, dual runtime,
  unsandboxed execution risk (Section 3).
- Vendoring their TS connectors — reimplementing thin HTTP clients in
  Python is cheaper than bridging runtimes (and see §3a).
- An `unsupported-claim` verdict — requires semantic entailment we do not
  perform; claiming it would overstate the tool (§5a).
- Experiment execution / code-running lanes in RC — out of scope for a
  verification tool; revisit only with sandboxing as a hard requirement.
- Inline molecule/genome rendering — serves their domains, not draft review.
