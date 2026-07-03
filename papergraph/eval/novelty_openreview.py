"""Novelty-vs-OpenReview evaluation harness.

Runs the NoveltyAgent pipeline over a set of cases (papers already in the
store with a ``human_novelty`` score from OpenReview reviewers), computes a
per-paper model score, and reports Spearman-style rank correlation.

Usage
-----
    python -m papergraph.eval.novelty_openreview cases.jsonl [--out DIR]

Each line of ``cases.jsonl`` must be a JSON object::

    {"paper_id": "arxiv:2401.00001", "human_novelty": 4}

The paper must already be in the store with its text saved (``papergraph add``
+ ``papergraph build`` + text ingested).  ``human_novelty`` is a 1-5 score
(average of OpenReview reviewer novelty/contribution ratings).

Verdict → score map
-------------------
    novel        → 5.0
    incremental  → 3.5
    overlaps     → 2.0
    anticipated  → 1.0

Paper score = confidence-weighted mean over claims.
If total confidence is 0 (all claims have confidence 0), use a plain mean.
If there are no claims, the score is 3.0 (neutral).

Rank correlation
----------------
Spearman rank correlation implemented inline (no scipy):
  rank both lists with average-rank for ties, then Pearson on the ranks.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

VERDICT_SCORES: dict[str, float] = {
    "novel": 5.0,
    "incremental": 3.5,
    "overlaps": 2.0,
    "anticipated": 1.0,
}

_NEUTRAL_SCORE = 3.0


# ---------------------------------------------------------------------------
# rank_correlation: pure Spearman (no scipy)
# ---------------------------------------------------------------------------

def rank_correlation(a: list[float], b: list[float]) -> float:
    """Spearman rank correlation between *a* and *b*.

    Ties receive average ranks.  Returns Pearson correlation on the resulting
    rank lists.  Returns 0.0 for lists shorter than 2.

    Parameters
    ----------
    a, b:
        Sequences of the same length.

    Returns
    -------
    float in [-1.0, 1.0].
    """
    n = len(a)
    if n != len(b):
        raise ValueError("rank_correlation: lists must have equal length")
    if n < 2:
        return 0.0

    def _ranks(xs: list[float]) -> list[float]:
        # Build sorted index list; ties get the average of their positions.
        indexed = sorted(enumerate(xs), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg_rank = (i + j) / 2 + 1  # 1-based average rank
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    ra = _ranks(a)
    rb = _ranks(b)

    mean_a = sum(ra) / n
    mean_b = sum(rb) / n
    num = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(n))
    denom_a = sum((ra[i] - mean_a) ** 2 for i in range(n)) ** 0.5
    denom_b = sum((rb[i] - mean_b) ** 2 for i in range(n)) ** 0.5
    if denom_a == 0 or denom_b == 0:
        return 0.0
    return num / (denom_a * denom_b)


# ---------------------------------------------------------------------------
# load_cases
# ---------------------------------------------------------------------------

def load_cases(path: str) -> list[dict]:
    """Load evaluation cases from a JSONL file.

    Each line must contain at least ``paper_id`` (str) and
    ``human_novelty`` (float 1-5).  Papers must already be in the store.
    """
    cases: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"cases.jsonl line {lineno}: invalid JSON — {exc}") from exc
            if "paper_id" not in obj or "human_novelty" not in obj:
                raise ValueError(
                    f"cases.jsonl line {lineno}: missing 'paper_id' or 'human_novelty'"
                )
            cases.append(obj)
    return cases


# ---------------------------------------------------------------------------
# _score_paper: map claim list to a 1-5 float
# ---------------------------------------------------------------------------

def _score_paper(claims: list[dict]) -> float:
    """Map a list of novelty claims to a 1-5 score.

    Score = confidence-weighted mean of per-claim scores.
    Falls back to plain mean if total confidence == 0.
    Returns _NEUTRAL_SCORE (3.0) if there are no claims.
    """
    if not claims:
        return _NEUTRAL_SCORE

    total_confidence = sum(float(c.get("confidence", 0.0)) for c in claims)
    claim_scores = [VERDICT_SCORES.get(c.get("verdict", "novel"), _NEUTRAL_SCORE) for c in claims]

    if total_confidence == 0.0:
        return sum(claim_scores) / len(claim_scores)

    weighted = sum(
        claim_scores[i] * float(claims[i].get("confidence", 0.0))
        for i in range(len(claims))
    )
    return weighted / total_confidence


# ---------------------------------------------------------------------------
# run_cases
# ---------------------------------------------------------------------------

def run_cases(
    cases: list[dict],
    *,
    llm: Callable[[str], str] | None = None,
    search: Callable[[str], list] | None = None,
) -> dict:
    """Run the NoveltyAgent pipeline over *cases* and return evaluation results.

    Parameters
    ----------
    cases:
        List of dicts with ``paper_id`` and ``human_novelty``.
    llm:
        Optional LLM callable seam (prompt -> raw text).  When *None*, the
        real default LLM is used (requires an API key + network).
    search:
        Optional search callable seam (query -> list[DiscoveredPaper]).
        When *None*, the real ``search_topic`` is used.

    Returns
    -------
    dict with keys:
        ``papers``: list of per-paper dicts (paper_id, human_novelty, model_score).
        ``rank_agreement``: Spearman rank correlation float in [-1, 1].
    """
    from papergraph.agents.base import AgentContext
    from papergraph.agents.bus import Bus
    from papergraph.agents.ingest import IngestAgent
    from papergraph.agents.novelty import NoveltyAgent
    from papergraph.agents.orchestrator import run_agents
    from papergraph.agents.priorart import PriorArtAgent

    overrides: dict = {}
    if llm is not None:
        overrides["_llm"] = llm
    if search is not None:
        overrides["_search"] = search

    paper_rows: list[dict] = []

    for case in cases:
        paper_id = case["paper_id"]
        human_novelty = float(case["human_novelty"])

        ctx = AgentContext(
            paper_id=paper_id,
            bus=Bus(),
            data=dict(overrides),
        )
        agents = [IngestAgent(), PriorArtAgent(), NoveltyAgent()]
        results = asyncio.run(run_agents(agents, ctx))

        novelty_result = results.get("novelty")
        if novelty_result and novelty_result.ok:
            claims = novelty_result.data.get("claims", [])
            model_score = _score_paper(claims)
        else:
            # Agent failed — use neutral score so we still include the row
            model_score = _NEUTRAL_SCORE

        paper_rows.append({
            "paper_id": paper_id,
            "human_novelty": human_novelty,
            "model_score": model_score,
        })

    human_scores = [r["human_novelty"] for r in paper_rows]
    model_scores = [r["model_score"] for r in paper_rows]
    ra = rank_correlation(human_scores, model_scores)

    return {
        "papers": paper_rows,
        "rank_agreement": ra,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m papergraph.eval.novelty_openreview",
        description="Novelty-vs-OpenReview evaluation harness.",
    )
    parser.add_argument(
        "cases",
        help="Path to a JSONL file with evaluation cases "
             '(each line: {"paper_id": "...", "human_novelty": 1-5})',
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help="Optional directory to write novelty_openreview.json",
    )
    args = parser.parse_args(argv)

    # Honest banner when no API keys are set
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    if not has_anthropic and not has_openai:
        print(
            "\n"
            "NOTE: Neither ANTHROPIC_API_KEY nor OPENAI_API_KEY is set.\n"
            "Live runs require a valid API key and network access.\n"
            "See eval/README.md for instructions on assembling cases and\n"
            "setting up credentials before running this harness.\n",
            file=sys.stderr,
        )

    cases = load_cases(args.cases)
    result = run_cases(cases)

    print(f"rank_agreement (Spearman): {result['rank_agreement']:.4f}")
    print(f"papers evaluated: {len(result['papers'])}")
    for row in result["papers"]:
        print(
            f"  {row['paper_id']}"
            f"  human={row['human_novelty']:.1f}"
            f"  model={row['model_score']:.2f}"
        )

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "novelty_openreview.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nResults written to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
