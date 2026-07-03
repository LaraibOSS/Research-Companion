# Tier-1 Spec — Novelty Engine + Reference Validator

> Concrete, build-ready spec for the first vertical slice, grounded in papergraph's existing modules and the architectures of OpenNovelty / RefChecker / GraphMind (see `COMPETITOR_ARCHITECTURES.md`). Design rules from the research (`RESEARCH_EVALUATOR_PLAN.md`): **everything citation-grounded; verify before asserting; deterministic checks backstop the LLM.**

## What exists today (reuse, don't rebuild)

| Module | Gives us |
|---|---|
| `store.py` | `PaperMetadata` (paper_id, title, authors, year, abstract, source_url, arxiv_categories), per-paper dirs, `make_{arxiv,doi,s2,local}_id`, extraction cache keyed by prompt SHA |
| `fetch.py` | `add_arxiv / add_doi / add_s2 / add_local_pdf` + metadata fetchers |
| `discover.py` | Semantic Scholar search + citation/reference expansion |
| `extract.py` | `extract_paper` (LLM, Anthropic/OpenAI), `pdf_to_text`, `_validate_extraction`, code-fence stripping |
| `prompts.py` | `EXTRACTION_PROMPT` → `concepts / methods / datasets / related_work`; prompt SHA caching |
| `graph.py` | `build_graph`, `_norm`, `_node_id`, `_resolve_citation`, `co_mentioned`/`contains`/`cites` edges |
| `chat.py` | `_bfs`, `_score_nodes`, `_render_subgraph` — graph→context for the LLM |

**The gap:** papergraph extracts *what a paper is about*, never *what it claims as new*, and never compares those claims against prior art. Tier-1 adds exactly that.

---

## Component 1 — Contribution extraction (`novelty/contributions.py`)

Extend the extraction layer to pull **contribution claims**, not just concepts.

```python
@dataclass
class ContributionClaim:
    claim_id: str            # f"{paper_id}__c{n}"
    paper_id: str
    text: str                # the claimed contribution, verbatim-ish
    kind: Literal["method", "dataset", "finding", "theory", "application", "resource"]
    evidence_quote: str      # exact span from the paper supporting the claim
    evidence_location: str   # section/page anchor for verification
    prior_work_query: str    # LLM-generated query to find competing work
```

- New prompt in `prompts.py` (`CONTRIBUTION_PROMPT`, SHA-cached like the existing one) following OpenNovelty's Phase-1 split: extract claims → generate one `prior_work_query` per claim (prefix-normalized, e.g. *"Find papers about …"*).
- Reuse `extract.py`'s `_call_anthropic/_call_openai`, `_strip_code_fences`, `_validate_extraction`, and the prompt-SHA cache. **No new LLM plumbing.**
- Default model: latest Claude (the repo already supports Anthropic). Keep the OpenAI path.

## Component 2 — Multi-source prior-art retrieval (`novelty/retrieval.py`)

papergraph has S2 only (`discover.py`). Add a thin connector layer with a uniform return type, so novelty isn't blind to non-S2 venues.

```python
class PriorArtRetriever(Protocol):
    def search(self, query: str, *, limit: int, year_max: int | None) -> list[PaperMetadata]: ...

# implementations: SemanticScholarRetriever (wrap existing), OpenAlexRetriever,
# ArxivRetriever, CrossRefRetriever, DBLPRetriever
```

- **Canonical dedup across sources** — adopt OpenNovelty's pattern: `canonical_id = md5(normalize_title(title))`. papergraph's `_norm()` already normalizes; extend it into `make_canonical_id()` in `store.py` and dedup the merged candidate pool before comparison.
- `year_max` filter (don't compare against papers published *after* the target — a correctness bug OpenNovelty handles via `_filter_temporal`).
- Cache raw responses per query (mirror the extraction cache) so re-runs are free.

## Component 3 — Contribution-level novelty comparison (`novelty/compare.py`)

For each `ContributionClaim`, compare against (a) retrieved prior art and (b) the **papergraph neighborhood** of the paper's concepts — this is the differentiator GraphMind/OpenNovelty get only via flat retrieval.

```python
@dataclass
class NoveltyVerdict:
    claim_id: str
    verdict: Literal["novel", "incremental", "overlaps", "anticipated"]
    confidence: float                  # 0–1
    closest_prior: list[ClaimMatch]    # papers + the overlapping span, ranked
    rationale: str
    graph_context: list[str]           # papergraph nodes/communities that bridge claim↔prior
```

- Two-stage like the *Idea Novelty Checker* the research surfaced: cheap embedding/retrieval shortlist → LLM facet comparison on the top-K.
- Feed graph context via `chat.py`'s existing `_render_subgraph` / `_bfs` — linearize the claim's concept neighborhood (GraphMind's "fluent linearization") into the comparison prompt.
- Borrow GraphMind's **citation-context polarity** typing for matches: `extends / supports / contrasts / refutes / mentions`.

## Component 4 — Evidence verification (`novelty/verify.py`) — NON-NEGOTIABLE

The anti-hallucination layer. Every quote the LLM attributes to a paper is checked back against that paper's fulltext before it reaches the report. Directly ported from OpenNovelty's `EvidenceVerifier`.

```python
def verify_quote(quote: str, fulltext: str) -> VerifyResult:
    # exact match → normalized match → anchor/fuzzy match (split into anchors,
    # match each in fulltext); return matched|unverified + location
```

- Any claim whose evidence is `unverified` is **demoted, not shown as fact** (research: LLM reviewers are systematically too lenient).
- Reuse `get_paper_text()` for fulltext.

## Component 5 — Deterministic reference validator (`refcheck/validate.py`)

Independent of the LLM — pure win, ship first. RefChecker pattern, but for the paper's *own* bibliography.

- Parse references (from extraction `related_work` + bib if available).
- Validate each against **CrossRef / OpenAlex / S2 / arXiv / DBLP**: exists? title/author match? (flag <60% author overlap), DOI/arXiv-id conflicts, broken URLs, retraction flags.
- Deterministic pre-filters first; only escalate ambiguous ones to an LLM/web lookup (RefChecker's cost-control hybrid).
- Output: per-reference status (`verified / suspect / unverified`) + reason.

## Component 6 — Report + graph view (`novelty/report.py`)

- Aggregate verdicts → an overall novelty assessment with a **per-claim breakdown**, every assertion carrying its cited prior-art + verified evidence span.
- Reuse `viz.py` for an interactive graph: target paper's claims as nodes, edges to overlapping prior art colored by polarity. (OpenNovelty renders Mermaid; papergraph already has a richer HTML graph — lead with it.)
- CLI: `papergraph novelty <paper_id> --venue <slug>` wired through `cli.py`.

---

## Data flow

```
add paper (fetch.py) ─► extract concepts (extract.py) + contributions (Component 1)
                                    │
                    per claim: prior_work_query
                                    ▼
            multi-source retrieval (Component 2) ─► canonical dedup, temporal filter
                                    ▼
       compare claim × {prior art, papergraph neighborhood}  (Component 3)
                                    ▼
            verify every evidence quote vs fulltext  (Component 4)   ◄── gate
                                    ▼
        novelty report + graph view (Component 6)   ║   reference validator (Component 5, parallel, LLM-free)
```

## Build order (TDD — test first, each independently shippable)

1. **Component 5 (reference validator)** — zero LLM risk, immediate user value, easy golden tests against known-good/bad bibliographies.
2. **Component 1 (contribution extraction)** — golden-file tests on a handful of papers already in the repo's `examples/`.
3. **Component 2 (retrieval)** — mock each API (the repo's tests already mock S2/HTTP — extend that pattern); test dedup + temporal filter deterministically.
4. **Component 4 (verify)** — pure function, exhaustively unit-testable (exact/normalized/fuzzy/unverified cases).
5. **Component 3 (compare)** — mock the LLM; assert verdict structure, polarity typing, graph-context wiring.
6. **Component 6 (report + viz + CLI)** — integration test end-to-end on one example paper.

## Explicit non-goals for Tier-1
- No reviewer-style critique engine (Tier 2 — AgentReview pattern).
- No venue/format compliance linting beyond reference checks (Tier 1–3).
- No non-CS venue knowledge base (the hardest gap — needs its own design pass; see open questions in the research report).

## Risks / open questions carried from research
- **Novelty-assessor accuracy is unmeasured** — build a small human-labeled validation set early; report confidence honestly, never a bare "novel/not-novel" verdict.
- **Coverage gaps for non-English / non-indexed venues** — retrieval is only as good as the APIs; surface "low prior-art coverage" warnings rather than implying exhaustiveness.
- **Pricing/positioning** still unresearched (see report's open questions) — doesn't block building, does block launch.
