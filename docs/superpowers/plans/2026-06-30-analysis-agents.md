# Analysis Agents Implementation Plan (Plan 2 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** NoveltyAgent (contribution extraction → prior-art comparison → evidence verification), ConfidenceAgent (deterministic score+band per claim), BenchmarkAgent (graph-mined benchmark suggestions), wired into `papergraph review` as three new lanes.

**Architecture:** Same thin-agent pattern as Plan 1. LLM access goes through an injectable seam `ctx.data["_llm"]` (callable `prompt: str -> str`); the default resolves to the existing `extract._call_anthropic/_call_openai`. Sync work inside `async run()` is wrapped in `asyncio.to_thread` (final-review pattern). Confidence and Benchmark are fully deterministic — no LLM.

**Tech Stack:** Python 3.10, asyncio, existing `prompts.py` SHA pattern, existing `extract.py` LLM clients, networkx graph already on the blackboard.

## Global Constraints

- Python ≥ 3.10, line length 110, ruff `E,F,I,B,UP,SIM` (E501 ignored).
- TDD: failing test first, watch fail, minimal code, watch pass, commit. RED/GREEN evidence in report.
- Zero network/LLM in tests: inject `_llm`, `_search`, `_lookup` via `ctx.data`.
- `AgentResult.data` JSON-serializable; non-JSON objects only under `_`-prefixed ctx keys.
- Sync-library calls inside `async run()` must use `await asyncio.to_thread(...)`.
- Commit ONLY the files each task names. NEVER `git add -A`, `git add .`, `git commit -a`.
- Suite green after every task. Baseline at plan start: **138 passed** (post final-review fixes).
- Confidence formula (spec §4, fixed): signal weights — verified evidence span 1.0, novelty comparison 0.8, citation health 0.6. score = weighted mean of signal values. band half-width = `0.5/sqrt(n) + 0.5*stdev(values)` clamped to [0.05, 0.5] (population stdev; 0.0 when n==1).

---

### Task 1: Novelty prompts (SHA-cached)

**Files:**
- Modify: `papergraph/prompts.py` (append at end, before any `__main__` guard if present)
- Test: `tests/test_novelty_prompts.py`

**Interfaces:**
- Produces: `CONTRIBUTION_PROMPT` (placeholders `{title}`, `{paper_text}`), `COMPARISON_PROMPT` (placeholders `{claim}`, `{prior_art}`), `format_contribution_prompt(title, paper_text) -> str`, `format_comparison_prompt(claim, prior_art) -> str`, `novelty_prompt_sha256() -> str` (sha over both prompts concatenated).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_novelty_prompts.py
"""Tests for the novelty-assessment prompts."""
from __future__ import annotations

from papergraph import prompts


def test_format_contribution_prompt_substitutes():
    p = prompts.format_contribution_prompt("My Title", "BODY TEXT")
    assert "My Title" in p and "BODY TEXT" in p
    assert "{title}" not in p and "{paper_text}" not in p


def test_format_comparison_prompt_substitutes():
    p = prompts.format_comparison_prompt("claim text", "1. Prior A\n2. Prior B")
    assert "claim text" in p and "Prior A" in p
    assert "{claim}" not in p and "{prior_art}" not in p


def test_contribution_prompt_demands_json_schema():
    assert '"claims"' in prompts.CONTRIBUTION_PROMPT
    assert "evidence_quote" in prompts.CONTRIBUTION_PROMPT


def test_novelty_prompt_sha_is_stable_hex():
    sha = prompts.novelty_prompt_sha256()
    assert sha == prompts.novelty_prompt_sha256()
    assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_novelty_prompts.py -q`
Expected: FAIL — `AttributeError: module 'papergraph.prompts' has no attribute 'format_contribution_prompt'`

- [ ] **Step 3: Write minimal implementation**

Append to `papergraph/prompts.py`:

```python
# ---------------------------------------------------------------------------
# Novelty assessment prompts (agents/novelty.py). SHA-cached like extraction.
# ---------------------------------------------------------------------------

CONTRIBUTION_PROMPT = """You are extracting the claimed contributions of a research paper.

Paper title: {title}

Paper text:
{paper_text}

Return ONLY valid JSON, no markdown fences, matching exactly:
{{
  "claims": [
    {{
      "text": "one-sentence statement of the claimed contribution",
      "kind": "method|dataset|finding|theory|application|resource",
      "evidence_quote": "short verbatim span from the paper supporting this claim"
    }}
  ]
}}

Rules:
- 2 to 6 claims. Only contributions the AUTHORS claim as new.
- evidence_quote must be copied verbatim from the paper text above.
"""


COMPARISON_PROMPT = """You are assessing the novelty of one claimed contribution against prior work.

Claimed contribution:
{claim}

Prior work (title, year - abstract):
{prior_art}

Return ONLY valid JSON, no markdown fences, matching exactly:
{{
  "verdict": "novel|incremental|overlaps|anticipated",
  "confidence": 0.0,
  "closest_prior": ["title of the most similar prior work, if any"],
  "rationale": "one or two sentences grounded in the prior work above"
}}

Rules:
- Base the verdict ONLY on the prior work listed above. If none is similar, verdict is "novel".
- confidence is your certainty in the verdict, 0.0-1.0.
"""


def format_contribution_prompt(title: str, paper_text: str) -> str:
    return CONTRIBUTION_PROMPT.format(title=title, paper_text=paper_text)


def format_comparison_prompt(claim: str, prior_art: str) -> str:
    return COMPARISON_PROMPT.format(claim=claim, prior_art=prior_art)


def novelty_prompt_sha256() -> str:
    both = CONTRIBUTION_PROMPT + COMPARISON_PROMPT
    return hashlib.sha256(both.encode("utf-8")).hexdigest()
```

(`hashlib` is already imported at the top of prompts.py — verify; if not, add `import hashlib`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_novelty_prompts.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/prompts.py tests/test_novelty_prompts.py
git commit -m "feat(prompts): SHA-cached contribution and comparison prompts for novelty"
```

---

### Task 2: PriorArtAgent stashes full papers on the blackboard

**Files:**
- Modify: `papergraph/agents/priorart.py`
- Test: `tests/test_agents_priorart.py` (extend)

**Interfaces:**
- Produces: after a successful run, `ctx.data["_priorart_papers"]` holds the raw `list[DiscoveredPaper]` (with abstracts) for NoveltyAgent. JSON result data unchanged.

- [ ] **Step 1: Write the failing test** — append to `tests/test_agents_priorart.py`:

```python
@pytest.mark.asyncio
async def test_priorart_stashes_full_papers_for_downstream():
    store.PaperMetadata(paper_id="local:pa3", title="T", authors=[]).save()
    ctx = AgentContext(paper_id="local:pa3", bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": []}
    papers = [_paper("GraphRAG")]
    ctx.data["_search"] = lambda q: papers
    await PriorArtAgent().run(ctx)
    assert ctx.data["_priorart_papers"] is papers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_priorart.py -q`
Expected: 1 FAIL (`KeyError: '_priorart_papers'`), others pass.

- [ ] **Step 3: Write minimal implementation** — in `priorart.py`, right after `found = await asyncio.to_thread(search, query)` add:

```python
        ctx.data["_priorart_papers"] = found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_priorart.py -q` — Expected: all pass (3).

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/priorart.py tests/test_agents_priorart.py
git commit -m "feat(agents): PriorArtAgent stashes full papers for novelty comparison"
```

---

### Task 3: NoveltyAgent

**Files:**
- Create: `papergraph/agents/novelty.py`
- Test: `tests/test_agents_novelty.py`

**Interfaces:**
- Consumes: `ctx.data["_extraction"]`, `ctx.data["_priorart_papers"]` (may be absent → treat as []), `ctx.data["_llm"]` (callable `str -> str`; default `_default_llm` uses `extract._call_anthropic` unless env `PAPERGRAPH_PROVIDER=openai`), `store.PaperMetadata.load` + `store.load_text` for title/fulltext.
- Produces: `NoveltyAgent` — `name="novelty"`, `depends_on=("priorart",)`. Result data:
  `{"claims": [{"text","kind","verdict","confidence","closest_prior","rationale","evidence_verified"}], "counts": {verdict: n}}`. Publishes one `Finding(kind="novelty_verdict")` per claim and one `Finding(kind="novelty_report")` at the end. Helper `_verify_quote(quote, fulltext) -> bool` (exact, then whitespace/case-normalized containment) — pure, exported for reuse.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_novelty.py
"""Tests for NoveltyAgent — LLM injected, no network."""
from __future__ import annotations

import json

import pytest

from papergraph import store
from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.novelty import NoveltyAgent, _verify_quote
from papergraph.discover import DiscoveredPaper


def test_verify_quote_exact_and_normalized():
    text = "We propose GraphNov, a  graph-based novelty checker."
    assert _verify_quote("We propose GraphNov", text)
    assert _verify_quote("we PROPOSE graphnov,   a graph-based", text)
    assert not _verify_quote("completely absent claim", text)


def _fake_llm_factory():
    calls = []

    def _llm(prompt: str) -> str:
        calls.append(prompt)
        if '"claims"' in prompt:  # contribution extraction call
            return json.dumps({"claims": [
                {"text": "We propose GraphNov.", "kind": "method",
                 "evidence_quote": "We propose GraphNov"},
            ]})
        return json.dumps({"verdict": "overlaps", "confidence": 0.8,
                           "closest_prior": ["GraphRAG"], "rationale": "similar"})

    return _llm, calls


@pytest.mark.asyncio
async def test_novelty_extracts_compares_and_verifies():
    pid = "local:nov1"
    store.PaperMetadata(paper_id=pid, title="GraphNov Paper", authors=[]).save()
    store.save_text(pid, "In this paper We propose GraphNov, a graph novelty checker.")
    llm, calls = _fake_llm_factory()

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": []}
    ctx.data["_priorart_papers"] = [DiscoveredPaper(
        title="GraphRAG", authors=[], year=2024, citation_count=1,
        arxiv_id=None, doi=None, s2_id=None, url="", abstract="graph rag abstract")]
    ctx.data["_llm"] = llm

    result = await NoveltyAgent().run(ctx)

    assert result.ok
    claim = result.data["claims"][0]
    assert claim["verdict"] == "overlaps"
    assert claim["closest_prior"] == ["GraphRAG"]
    assert claim["evidence_verified"] is True
    assert result.data["counts"] == {"overlaps": 1}
    assert len(calls) == 2  # one extraction + one comparison
    kinds = [e.kind for e in ctx.bus.history if isinstance(e, events.Finding)]
    assert kinds.count("novelty_verdict") == 1 and kinds.count("novelty_report") == 1


@pytest.mark.asyncio
async def test_novelty_unverified_quote_flagged():
    pid = "local:nov2"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "totally different body text")
    llm, _ = _fake_llm_factory()
    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    ctx.data.update({"_extraction": {}, "_priorart_papers": [], "_llm": llm})
    result = await NoveltyAgent().run(ctx)
    assert result.ok
    assert result.data["claims"][0]["evidence_verified"] is False


@pytest.mark.asyncio
async def test_novelty_bad_llm_json_fails_cleanly():
    pid = "local:nov3"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "body")
    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    ctx.data.update({"_extraction": {}, "_priorart_papers": [],
                     "_llm": lambda p: "NOT JSON AT ALL"})
    result = await NoveltyAgent().run(ctx)
    assert not result.ok
    assert "novelty" in result.error.lower() or "json" in result.error.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_novelty.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.novelty'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/novelty.py
"""NoveltyAgent: extract claimed contributions, compare against prior art,
and verify every evidence quote against the paper's own fulltext.

The LLM is reached only through ctx.data["_llm"] (callable prompt -> raw text);
tests inject it, production falls back to the extract.py clients.
"""
from __future__ import annotations

import asyncio
import json
import os
import re

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _verify_quote(quote: str, fulltext: str) -> bool:
    """True iff the quote appears in the fulltext (exact or normalized)."""
    if not quote or not fulltext:
        return False
    return quote in fulltext or _normalize(quote) in _normalize(fulltext)


def _default_llm(prompt: str) -> str:
    from papergraph.extract import _call_anthropic, _call_openai

    provider = os.environ.get("PAPERGRAPH_PROVIDER", "anthropic")
    call = _call_openai if provider == "openai" else _call_anthropic
    text, _usage = call(prompt, model=os.environ.get("PAPERGRAPH_MODEL") or None)
    return text


def _parse_json(raw: str, what: str) -> dict:
    from papergraph.extract import _strip_code_fences

    try:
        return json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"novelty: LLM returned invalid JSON for {what}: {exc}") from exc


class NoveltyAgent(Agent):
    name = "novelty"
    role = "Assesses each claimed contribution against prior art, with verified evidence."
    depends_on = ("priorart",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.prompts import format_comparison_prompt, format_contribution_prompt
        from papergraph.store import PaperMetadata, load_text

        llm = ctx.data.get("_llm") or _default_llm
        meta = PaperMetadata.load(ctx.paper_id)
        title = meta.title if meta else ""
        fulltext = load_text(ctx.paper_id) or ""

        raw = await asyncio.to_thread(llm, format_contribution_prompt(title, fulltext[:20000]))
        claims = _parse_json(raw, "contribution extraction").get("claims", [])

        prior = ctx.data.get("_priorart_papers") or []
        prior_block = "\n".join(
            f"{i}. {p.title} ({p.year}) - {p.abstract[:300]}" for i, p in enumerate(prior, 1)
        ) or "(no prior work found)"

        out_claims = []
        counts: dict[str, int] = {}
        for c in claims:
            raw_cmp = await asyncio.to_thread(
                llm, format_comparison_prompt(c.get("text", ""), prior_block)
            )
            cmp = _parse_json(raw_cmp, "comparison")
            verdict = cmp.get("verdict", "novel")
            entry = {
                "text": c.get("text", ""),
                "kind": c.get("kind", ""),
                "verdict": verdict,
                "confidence": float(cmp.get("confidence", 0.0)),
                "closest_prior": cmp.get("closest_prior", []),
                "rationale": cmp.get("rationale", ""),
                "evidence_verified": _verify_quote(c.get("evidence_quote", ""), fulltext),
            }
            out_claims.append(entry)
            counts[verdict] = counts.get(verdict, 0) + 1
            await ctx.bus.publish(events.Finding(
                agent=self.name, kind="novelty_verdict",
                summary=f"[{verdict}] {entry['text'][:80]}",
                data=entry,
            ))

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="novelty_report",
            summary=", ".join(f"{v}: {n}" for v, n in sorted(counts.items())) or "no claims",
            data={"counts": counts},
        ))
        return AgentResult(agent=self.name, ok=True,
                           data={"claims": out_claims, "counts": counts})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_novelty.py -q`
Expected: `4 passed`

- [ ] **Step 5: Run full suite, then commit**

Run: `python -m pytest -q` — all green.

```bash
git add papergraph/agents/novelty.py tests/test_agents_novelty.py
git commit -m "feat(agents): NoveltyAgent - claims, prior-art comparison, evidence verification"
```

---

### Task 4: ConfidenceAgent (deterministic)

**Files:**
- Create: `papergraph/agents/confidence.py`
- Test: `tests/test_agents_confidence.py`

**Interfaces:**
- Consumes: `ctx.data["novelty"]` (NoveltyAgent result data) and `ctx.data["citation"]` (CitationAgent result data) — both plain dicts placed by the orchestrator.
- Produces: `ConfidenceAgent` — `name="confidence"`, `depends_on=("citation", "novelty")`. Pure function `score_claim(evidence_verified: bool, novelty_confidence: float, citation_health: float) -> tuple[float, float]` returning (score, band). Result data `{"claims": [{"text","score","band","signals"}]}`. One `Finding(kind="confidence_card")` per claim.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_confidence.py
"""Tests for ConfidenceAgent — fully deterministic, no LLM."""
from __future__ import annotations

import math

import pytest

from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.confidence import ConfidenceAgent, score_claim


def test_score_claim_formula_exact():
    # signals: evidence 1.0 (weight 1.0), novelty 0.8 (weight 0.8), citation 0.5 (weight 0.6)
    score, band = score_claim(True, 0.8, 0.5)
    vals = [1.0, 0.8, 0.5]
    weights = [1.0, 0.8, 0.6]
    expected = sum(v * w for v, w in zip(vals, weights)) / sum(weights)
    assert math.isclose(score, expected)
    mean = sum(vals) / 3
    stdev = math.sqrt(sum((v - mean) ** 2 for v in vals) / 3)
    expected_band = min(0.5, max(0.05, 0.5 / math.sqrt(3) + 0.5 * stdev))
    assert math.isclose(band, expected_band)


def test_score_claim_unverified_evidence_scores_lower():
    hi, _ = score_claim(True, 0.9, 1.0)
    lo, _ = score_claim(False, 0.9, 1.0)
    assert lo < hi


def test_band_bounds():
    _, band = score_claim(True, 1.0, 1.0)
    assert 0.05 <= band <= 0.5


@pytest.mark.asyncio
async def test_confidence_agent_emits_card_per_claim():
    ctx = AgentContext(paper_id="local:x", bus=Bus(), data={})
    ctx.data["novelty"] = {"claims": [
        {"text": "claim A", "confidence": 0.8, "evidence_verified": True},
        {"text": "claim B", "confidence": 0.4, "evidence_verified": False},
    ]}
    ctx.data["citation"] = {"counts": {"verified": 3, "suspect": 1, "unverified": 0}}
    result = await ConfidenceAgent().run(ctx)
    assert result.ok
    assert len(result.data["claims"]) == 2
    a, b = result.data["claims"]
    assert a["score"] > b["score"]
    assert all(0.0 <= c["score"] <= 1.0 and 0.05 <= c["band"] <= 0.5
               for c in result.data["claims"])
    cards = [e for e in ctx.bus.history
             if isinstance(e, events.Finding) and e.kind == "confidence_card"]
    assert len(cards) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_confidence.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.confidence'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/confidence.py
"""ConfidenceAgent: deterministic per-claim confidence score with uncertainty band.

Formula (design spec section 4): weighted mean of three signals -
verified evidence span (weight 1.0), novelty-comparison confidence (0.8),
citation health = verified/total references (0.6). Band half-width is
0.5/sqrt(n) + 0.5*stdev(values), clamped to [0.05, 0.5].
"""
from __future__ import annotations

import math

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult

_WEIGHTS = (1.0, 0.8, 0.6)


def score_claim(
    evidence_verified: bool, novelty_confidence: float, citation_health: float,
) -> tuple[float, float]:
    values = (1.0 if evidence_verified else 0.3, novelty_confidence, citation_health)
    score = sum(v * w for v, w in zip(values, _WEIGHTS)) / sum(_WEIGHTS)
    mean = sum(values) / len(values)
    stdev = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    band = min(0.5, max(0.05, 0.5 / math.sqrt(len(values)) + 0.5 * stdev))
    return score, band


class ConfidenceAgent(Agent):
    name = "confidence"
    role = "Scores every claim with a confidence value and uncertainty band."
    depends_on = ("citation", "novelty")

    async def run(self, ctx: AgentContext) -> AgentResult:
        counts = ctx.data["citation"]["counts"]
        total = sum(counts.values()) or 1
        citation_health = counts.get("verified", 0) / total

        out = []
        for claim in ctx.data["novelty"]["claims"]:
            score, band = score_claim(
                bool(claim.get("evidence_verified")),
                float(claim.get("confidence", 0.0)),
                citation_health,
            )
            card = {
                "text": claim.get("text", ""),
                "score": round(score, 3),
                "band": round(band, 3),
                "signals": {
                    "evidence_verified": bool(claim.get("evidence_verified")),
                    "novelty_confidence": float(claim.get("confidence", 0.0)),
                    "citation_health": round(citation_health, 3),
                },
            }
            out.append(card)
            await ctx.bus.publish(events.Finding(
                agent=self.name, kind="confidence_card",
                summary=f"{card['score']:.2f} +/- {card['band']:.2f}  {card['text'][:70]}",
                data=card,
            ))
        return AgentResult(agent=self.name, ok=True, data={"claims": out})
```

**Test-fixture note (score ordering):** claim A (verified, 0.8) vs claim B (unverified, 0.4): values A = (1.0, 0.8, 0.75), B = (0.3, 0.4, 0.75) → A's weighted mean strictly greater. Ordering assertion holds.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_confidence.py -q` — Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/confidence.py tests/test_agents_confidence.py
git commit -m "feat(agents): ConfidenceAgent - deterministic per-claim score with band"
```

---

### Task 5: BenchmarkAgent (graph-mined, deterministic)

**Files:**
- Create: `papergraph/agents/benchmark.py`
- Test: `tests/test_agents_benchmark.py`

**Interfaces:**
- Consumes: `ctx.data["_graph"]` (networkx Graph; dataset nodes have attr `kind == "dataset"`, human name in attr `label`), `ctx.data["_priorart_papers"]` (list with `.abstract`/`.title`).
- Produces: `BenchmarkAgent` — `name="benchmark"`, `depends_on=("ingest", "priorart")`. Result data `{"suggestions": [{"name", "graph_degree", "prior_art_mentions"}]}` ranked by (prior_art_mentions, graph_degree) descending. One `Finding(kind="benchmarks")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_benchmark.py
"""Tests for BenchmarkAgent — deterministic graph mining, no LLM/network."""
from __future__ import annotations

import networkx as nx
import pytest

from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.benchmark import BenchmarkAgent
from papergraph.discover import DiscoveredPaper


def _paper(title, abstract):
    return DiscoveredPaper(title=title, authors=[], year=2024, citation_count=1,
                           arxiv_id=None, doi=None, s2_id=None, url="", abstract=abstract)


@pytest.mark.asyncio
async def test_benchmark_ranks_datasets_by_prior_art_mentions_then_degree():
    G = nx.Graph()
    G.add_node("d1", kind="dataset", label="HotpotQA")
    G.add_node("d2", kind="dataset", label="MuSiQue")
    G.add_node("p1", kind="paper", label="P1")
    G.add_edge("p1", "d1")
    G.add_edge("p1", "d2")
    G.add_node("c1", kind="concept", label="RAG")
    G.add_edge("c1", "d1")  # d1 degree 2, d2 degree 1

    ctx = AgentContext(paper_id="local:b1", bus=Bus(), data={})
    ctx.data["_graph"] = G
    ctx.data["_priorart_papers"] = [
        _paper("A", "evaluated on MuSiQue and MuSiQue again"),
        _paper("B", "we test on MuSiQue"),
        _paper("C", "uses HotpotQA"),
    ]
    result = await BenchmarkAgent().run(ctx)
    assert result.ok
    names = [s["name"] for s in result.data["suggestions"]]
    # MuSiQue mentioned in 2 prior papers > HotpotQA in 1 (degree breaks ties only)
    assert names[0] == "MuSiQue" and names[1] == "HotpotQA"
    assert result.data["suggestions"][0]["prior_art_mentions"] == 2
    assert any(isinstance(e, events.Finding) and e.kind == "benchmarks"
               for e in ctx.bus.history)


@pytest.mark.asyncio
async def test_benchmark_no_datasets_is_ok_and_empty():
    ctx = AgentContext(paper_id="local:b2", bus=Bus(), data={})
    ctx.data["_graph"] = nx.Graph()
    ctx.data["_priorart_papers"] = []
    result = await BenchmarkAgent().run(ctx)
    assert result.ok and result.data["suggestions"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_benchmark.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.benchmark'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/benchmark.py
"""BenchmarkAgent: suggest evaluation benchmarks by mining the knowledge graph
for dataset nodes and counting how many related (prior-art) papers mention each.
Fully deterministic - no LLM.
"""
from __future__ import annotations

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class BenchmarkAgent(Agent):
    name = "benchmark"
    role = "Suggests evaluation benchmarks used by related work, mined from the graph."
    depends_on = ("ingest", "priorart")

    async def run(self, ctx: AgentContext) -> AgentResult:
        graph = ctx.data["_graph"]
        prior = ctx.data.get("_priorart_papers") or []
        prior_texts = [f"{p.title} {p.abstract}".lower() for p in prior]

        suggestions = []
        for node, attrs in graph.nodes(data=True):
            if attrs.get("kind") != "dataset":
                continue
            label = attrs.get("label", node)
            mentions = sum(1 for t in prior_texts if label.lower() in t)
            suggestions.append({
                "name": label,
                "graph_degree": graph.degree(node),
                "prior_art_mentions": mentions,
            })
        suggestions.sort(key=lambda s: (-s["prior_art_mentions"], -s["graph_degree"], s["name"]))

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="benchmarks",
            summary=f"{len(suggestions)} benchmark(s) suggested",
            data={"count": len(suggestions)},
        ))
        return AgentResult(agent=self.name, ok=True, data={"suggestions": suggestions})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_benchmark.py -q` — Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/benchmark.py tests/test_agents_benchmark.py
git commit -m "feat(agents): BenchmarkAgent mines graph + prior art for benchmark suggestions"
```

---

### Task 6: Wire the three lanes into `papergraph review`

**Files:**
- Modify: `papergraph/cli.py` (`_cmd_review` only)
- Test: `tests/test_cli_review.py` (extend)

**Interfaces:**
- Produces: `review` now runs six agents: Ingest, Citation, PriorArt, Novelty, Confidence, Benchmark (lane order = this list order). New summaries entries. `--fast` flag skips novelty+confidence+benchmark (runs the original three) for LLM-free usage. JSON payload unchanged in shape (more agents keys).

- [ ] **Step 1: Write the failing test** — append to `tests/test_cli_review.py`:

```python
def _full_overrides():
    ov = _overrides()

    def llm(prompt):
        if '"claims"' in prompt:
            return json.dumps({"claims": [{"text": "We propose X.", "kind": "method",
                                           "evidence_quote": "We propose X"}]})
        return json.dumps({"verdict": "novel", "confidence": 0.9,
                           "closest_prior": [], "rationale": "r"})

    ov["_llm"] = llm
    return ov


def test_review_cli_full_pipeline_six_lanes(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    store.save_text(paper_id, "Body. We propose X here.")
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _full_overrides())
    rc = cli.main(["review", paper_id])
    out = capsys.readouterr().out
    assert rc == 0
    for lane in ("ingest", "citation", "priorart", "novelty", "confidence", "benchmark"):
        assert lane in out


def test_review_cli_fast_skips_llm_lanes(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--fast"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "novelty" not in out and "confidence" not in out
```

Also add `from papergraph import store` to the test file imports if missing.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_review.py -q`
Expected: new tests FAIL (novelty lane missing / unknown `--fast` flag → SystemExit 2); original 3 pass.

- [ ] **Step 3: Write minimal implementation** — in `_cmd_review`:

Replace the agents list construction with:

```python
    from papergraph.agents.benchmark import BenchmarkAgent
    from papergraph.agents.confidence import ConfidenceAgent
    from papergraph.agents.novelty import NoveltyAgent

    agents = [IngestAgent(), CitationAgent(), PriorArtAgent()]
    if not args.fast:
        agents += [NoveltyAgent(), ConfidenceAgent(), BenchmarkAgent()]
```

Extend the `summaries` dict:

```python
        "novelty": lambda d: ", ".join(f"{v}: {n}" for v, n in sorted(d["counts"].items()))
                             or "no claims",
        "confidence": lambda d: f"{len(d['claims'])} claim(s) scored",
        "benchmark": lambda d: f"{len(d['suggestions'])} benchmark(s) suggested",
```

Register the flag on the `review` subparser:

```python
    prv.add_argument("--fast", action="store_true",
                     help="Skip LLM lanes (novelty, confidence, benchmark)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_review.py -q` — Expected: `5 passed`

- [ ] **Step 5: Full suite + ruff, then commit**

Run: `python -m pytest -q` (all green) and
`python -m ruff check papergraph/agents papergraph/cli.py papergraph/prompts.py tests/test_agents_novelty.py tests/test_agents_confidence.py tests/test_agents_benchmark.py tests/test_novelty_prompts.py tests/test_cli_review.py`
(clean; auto-fix I001 import sorting if flagged, re-run tests).

```bash
git add papergraph/cli.py tests/test_cli_review.py
git commit -m "feat(cli): review runs novelty/confidence/benchmark lanes (--fast to skip)"
```

---

## Verification (whole plan)

1. `python -m pytest -q` — green, no regressions (baseline 138 + ~16 new).
2. Ruff clean on all files this plan touched.
3. Offline smoke: seed paper + text, run `review` with `_llm`/`_lookup`/`_search` injected via `REVIEW_CONTEXT_OVERRIDES` → six lanes, exit 0; `--fast` → three lanes.

## What later plans consume

- Plan 3 (Rebuttal): `_verify_quote` (novelty.py) as the verification primitive to generalize.
- Plan 4 (Dashboard/Report): `novelty_verdict`/`confidence_card`/`benchmarks` Finding kinds; result-data shapes above.
