"""Tests for the citation P/R evaluation harness.

Three tests:
1. corrupt() is deterministic for a fixed seed and labels correctly.
2. run_eval() returns precision/recall in [0,1] with >0.9 recall for fabricated.
3. main() / artifact writer creates both files in a tmp dir.
"""
from __future__ import annotations

import json


def test_corrupt_is_deterministic_and_labeled():
    """corrupt() with a fixed seed must return the same output every time,
    and every (ref, label) pair must have label in {"clean", "fabricated",
    "wrong_doi", "author_swap"}.
    """
    import random

    from papergraph.eval.citation_pr import GOLD, corrupt

    rng_a = random.Random(42)
    rng_b = random.Random(42)

    result_a = corrupt(GOLD, rng_a)
    result_b = corrupt(GOLD, rng_b)

    # Same seed → identical output
    assert len(result_a) == len(result_b)
    for (ref_a, lbl_a), (ref_b, lbl_b) in zip(result_a, result_b, strict=True):
        assert lbl_a == lbl_b
        assert ref_a.title == ref_b.title

    # Every label is valid
    valid_labels = {"clean", "fabricated", "wrong_doi", "author_swap"}
    for _ref, label in result_a:
        assert label in valid_labels, f"Unexpected label: {label!r}"

    # GOLD has 40 records → at least 40 entries (clean copies) + corrupted variants
    assert len(result_a) >= 40

    # Both clean and at least one corrupted variant must appear
    labels = [lbl for _, lbl in result_a]
    assert "clean" in labels
    assert any(lbl != "clean" for lbl in labels)


def test_run_eval_metrics_in_range_and_fabricated_recall_high():
    """run_eval() must return a dict with overall precision/recall/F1 in [0,1],
    and recall for the 'fabricated' corruption type must exceed 0.9.
    """
    from papergraph.eval.citation_pr import run_eval

    result = run_eval(seed=42)

    # Required top-level keys
    assert "overall" in result
    assert "per_type" in result

    overall = result["overall"]
    for key in ("precision", "recall", "f1"):
        assert key in overall, f"Missing overall[{key!r}]"
        val = overall[key]
        assert 0.0 <= val <= 1.0, f"overall[{key!r}] = {val} out of [0,1]"

    # fabricated recall > 0.9 (fabricated titles can't match the DB)
    per_type = result["per_type"]
    assert "fabricated" in per_type, "Expected 'fabricated' key in per_type"
    fab_recall = per_type["fabricated"]["recall"]
    assert fab_recall > 0.9, f"Fabricated recall {fab_recall:.3f} <= 0.9"


def test_main_writes_both_artifact_files(tmp_path):
    """main(out_dir=...) must create citation_pr.json and citation_pr.md
    in the given directory, and the JSON must be a non-empty dict.
    """
    from papergraph.eval.citation_pr import main

    main(out_dir=str(tmp_path))

    json_file = tmp_path / "citation_pr.json"
    md_file = tmp_path / "citation_pr.md"

    assert json_file.exists(), "citation_pr.json was not created"
    assert md_file.exists(), "citation_pr.md was not created"

    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, "citation_pr.json must be a non-empty dict"

    md_content = md_file.read_text(encoding="utf-8")
    assert "|" in md_content, "citation_pr.md should contain a markdown table"
