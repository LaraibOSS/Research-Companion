"""Zero-key offline demo for papergraph.

Reviewer-facing 30-second tryout: seeds a synthetic paper, runs the full
review pipeline (all 6 agent lanes), then drafts a rebuttal -- all offline,
no API keys, no network.

Usage:
    python examples/demo_offline.py

Output: demo-out/report.html (relative to the current working directory).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    # --- 1. Point PAPERGRAPH_DIR at a fresh temp dir BEFORE importing store ---
    tmp = tempfile.mkdtemp(prefix="papergraph-demo-")
    os.environ["PAPERGRAPH_DIR"] = tmp

    # Now safe to import papergraph modules (store reads env at call time).
    from papergraph import cli, store
    from papergraph.discover import DiscoveredPaper
    from papergraph.prompts import extraction_prompt_sha256

    # --- 2. Seed the demo paper -------------------------------------------------
    paper_id = "local:demo"
    store.PaperMetadata(paper_id=paper_id, title="Graph RAG Survey", authors=[]).save()
    store.save_extraction(
        paper_id,
        {
            "concepts": [{"name": "RAG", "definition": "Retrieval-Augmented Generation"}],
            "methods": [],
            "datasets": [{"name": "HotpotQA", "description": "multi-hop QA benchmark"}],
            "claims": [],
            "results": [],
            "related_work": [
                "Attention Is All You Need",
                "A Fabricated Paper Title",
            ],
        },
        prompt_sha=extraction_prompt_sha256(),
    )
    store.save_text(paper_id, "We propose X. Experiments on HotpotQA confirm gains.")

    # --- 3. Build offline seams (mirrors tests/test_cli_review.py::_full_overrides) ---
    def _lookup(ref):
        if "attention" in ref.title.lower():
            return {
                "title": ref.title,
                "authors": [],
                "year": 2017,
                "doi": None,
                "arxiv_id": None,
            }
        return None

    def _search(query):  # noqa: ARG001
        return [
            DiscoveredPaper(
                title="GraphRAG",
                authors=[],
                year=2024,
                citation_count=5,
                arxiv_id="2404.00001",
                doi=None,
                s2_id=None,
                url="",
                abstract="Multi-hop QA on HotpotQA with GraphRAG.",
            )
        ]

    def _llm_review(prompt):
        if '"evidence_quote"' in prompt:
            return json.dumps(
                {
                    "claims": [
                        {
                            "text": "We propose X.",
                            "kind": "method",
                            "evidence_quote": "We propose X",
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "verdict": "novel",
                "confidence": 0.9,
                "closest_prior": [],
                "rationale": "No exact prior covers this combination.",
            }
        )

    cli.REVIEW_CONTEXT_OVERRIDES = {
        "_lookup": _lookup,
        "_search": _search,
        "_llm": _llm_review,
    }

    # --- 4. Run the review pipeline ---------------------------------------------
    report_dir = "demo-out"
    print("papergraph demo: running review pipeline (6 agent lanes, offline)...")
    rc_review = cli.main(["review", paper_id, "--report", report_dir])
    if rc_review != 0:
        print(f"papergraph demo: review FAILED (exit {rc_review})", file=sys.stderr)
        return 1

    # --- 5. Build offline rebuttal seam ----------------------------------------
    def _llm_rebuttal(prompt):
        if '"kind"' in prompt:
            return json.dumps({"kind": "clarity"})
        return json.dumps(
            {
                "reply": 'We agree; see "We propose X" in Section 1.',
                "planned_revision": "Expand methodology section.",
            }
        )

    cli.REBUTTAL_CONTEXT_OVERRIDES = {"_llm": _llm_rebuttal}

    # --- 6. Write a small 3-concern reviews file and run rebuttal ---------------
    reviews_path = Path(tmp) / "reviews.txt"
    reviews_path.write_text(
        "Reviewer 1\n\n"
        "1. The methodology is unclear.\n"
        "2. Missing comparison with baseline X.\n\n"
        "Reviewer 2\n\n"
        "1. The methodology is unclear.\n",
        encoding="utf-8",
    )

    print("papergraph demo: running rebuttal pipeline (offline)...")
    rc_rebuttal = cli.main(["rebuttal", paper_id, "--reviews", str(reviews_path)])
    if rc_rebuttal != 0:
        print(f"papergraph demo: rebuttal FAILED (exit {rc_rebuttal})", file=sys.stderr)
        return 1

    # --- 7. Final summary -------------------------------------------------------
    report_html = Path(report_dir) / "report.html"
    print()
    print("Demo complete.")
    print(f"  Report HTML : {report_html.resolve()}")
    print(f"  Temp store  : {tmp}")
    print("  Zero API keys used / zero network calls made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
