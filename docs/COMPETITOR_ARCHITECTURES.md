# Competitor Architecture Teardown (from graphified source)

Three open-source competitors were cloned and graphified (AST-structural graphs: god nodes + community detection). This is what their *actual code* reveals — not their marketing — and what Research Companion should borrow or beat.

> **Status (2026):** the borrow/beat decisions below are delivered — see `docs/ROADMAP.md` for what shipped. Kept for the competitive rationale behind each design choice.

| Repo | Graph size | What it actually is |
|---|---|---|
| **GraphMind** | 6,020 nodes · 13,018 edges · 295 communities | Research-grade novelty-assessment *web app* + a sprawling experiment harness (baselines, tournaments, training data gen) |
| **OpenNovelty** | 1,127 nodes · 2,511 edges · 59 communities | Clean, production-shaped **4-phase novelty pipeline** — the best architectural blueprint of the three |
| **RefChecker** | 323 nodes · 536 edges · 19 communities | Focused **claim-extraction → retrieve → entailment-check** citation/hallucination verifier |

---

## 1. OpenNovelty — the blueprint to copy

Its community structure maps 1:1 onto a phase pipeline (god nodes in **bold**):

- **Phase 1 — Extract** (`Phase1Orchestrator`, `ContributionsExtractor`, `CoreTaskExtractor`, `QueryVariantsGenerator`, `PriorWorkQueryGenerator`, `MetadataEnricher`, `PdfTextLoader`): load PDF/URL → extract **`ContributionClaim`**s → generate prior-work search queries per claim → enrich metadata.
- **Phase 2 — Search** (`Phase2Processor`, `searching.py`, `WispaperClient` (OAuth), `postprocess`): multi-source academic search → **citation_index** with global dedup, canonical IDs, roles & aliases.
- **Phase 3 — Compare & Verify** (`ComparisonWorkflow`, **`LLMAnalyzer`**, **`EvidenceVerifier`**, `textual_similarity_detector`, `CitationManager`, `Phase3Survey`, `taxonomy builder`): build a **taxonomy tree** of prior art → contribution-level comparison (`compare_contributions`, `compare_core_task`, `_compare_siblings`) → **verify every evidence quote against fulltext** (`verify_quote_in_fulltext`, `match_anchor_in_fulltext`) → plagiarism/similarity segments.
- **Phase 4 — Report** (`LightweightReportGenerator`, `report_rendering`): markdown → PDF, **Mermaid flowcharts/mindmaps** of the taxonomy.

**Three patterns worth stealing outright:**
1. **Canonical paper IDs = MD5 hash of normalized title** (`make_canonical_id`, `_normalize_title_for_hash`) — the dedup backbone across arXiv/DOI/S2/OpenReview. *papergraph already has `_norm()`/`_node_id()` doing title normalization — this is a direct extension.*
2. **Evidence verification layer** (`EvidenceVerifier`): every claim the LLM makes is checked back against the source fulltext via anchor matching. This is the concrete anti-hallucination mechanism the research said is mandatory.
3. **Taxonomy tree of prior art** built via LLM then structurally validated (`_validate_taxonomy`: coverage + uniqueness + structural constraints). *papergraph's community detection is the graph-native equivalent — a differentiator.*

## 2. RefChecker — the deterministic validator to embed

Pipeline: **`LLMExtractor`** (extract KG **claim triplets** / subsentence claims) → **`GoogleRetriever`** (LLM-generated queries → web search → split docs) → **checker** (`AlignScoreChecker` / `LLMChecker` / NLI via `BERTAlignModel`) → **`NaiveEmbedLocalizer`** (locate supporting evidence by cosine distance). Core abstractions: `CheckerBase`, `ExtractorBase`, `RCClaim`, `RCText`.

**Steal:** the **triplet extraction → entailment-check** loop is exactly how to validate that a paper's *cited* claims are actually supported. Note it leans on a trained NLI model (AlignScore/Electra) for cheap deterministic checking before invoking an LLM — the hybrid cost-control pattern.

## 3. GraphMind — the analog to beat (and what's overbuilt)

The closest competitor to a papergraph-powered tool. Useful pieces:
- **Graph extraction + novelty eval** (`extract_graph_from_paper`, `evaluate_paper_graph_novelty`, `EvidenceItem` w/ `S2Reference`) — builds a contribution graph then scores novelty against it. **This is our exact thesis, already shipped.**
- **ACU (Atomic Content Units) extraction** + **NovaSCORE** novelty method — decompose a paper into atomic claims, score each against retrieved prior art.
- **Citation-context polarity** (`Based-on/Extension`, `Support`, `Contrast`, `Question/Refutation`, `Mention`) — typed edges richer than papergraph's current `cites`/`co_mentioned`. **Adopt this typing.**
- **Fluent graph linearization** (graph → natural-language text for the LLM) — how they feed a KG into an LLM prompt. Directly relevant to papergraph's `query`.
- **IMRaD section classification** — structural parse for venue/framing checks.

**What's overbuilt (don't copy):** Bradley-Terry model tournaments, SFT training-data generation, dozens of baseline harnesses (`minimal.py`, `sc4anm.py`, PETER threshold experiments). That's research-paper scaffolding, not product. ~60% of GraphMind's 295 communities are experiment/eval code — a lean product is far smaller.

---

## Net: where papergraph already wins, and the gaps to close

| Capability | papergraph today | Best competitor | Action |
|---|---|---|---|
| Cross-paper KG with community detection | ✅ have it | GraphMind (heavier) | **Lead with this** |
| Title normalization / canonical IDs | ✅ `_norm`/`_node_id` | OpenNovelty MD5 | Extend to multi-source canonical IDs |
| Typed citation edges | partial (`cites`, `co_mentioned`) | GraphMind polarity types | Adopt polarity typing |
| Contribution-claim extraction | ❌ | OpenNovelty Phase 1 | **Build (Tier 1)** |
| Multi-source prior-art retrieval | partial (S2 discover) | OpenNovelty Phase 2 | Add OpenAlex/arXiv/CrossRef/DBLP |
| Contribution-level novelty comparison | ❌ | OpenNovelty Phase 3 / NovaSCORE | **Build (Tier 1)** |
| Evidence verification (anti-hallucination) | ❌ | OpenNovelty `EvidenceVerifier` / RefChecker | **Build (Tier 1) — non-negotiable** |
| Deterministic reference validation | ❌ | RefChecker | **Build (Tier 1)** |
| Reviewer-style critique | ❌ (chat only) | AgentReview / OpenJudge | Tier 2 |
| Venue/format compliance linting | ❌ | ACL-pubcheck / Penelope | Tier 1–3 |
