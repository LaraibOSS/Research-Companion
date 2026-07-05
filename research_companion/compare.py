"""Pairwise paper comparison module.

Compares two papers by analyzing their normalized entities (concepts, methods, datasets)
and optional results (metrics + datasets).

Returns a structured dict with:
  - shared/only_a/only_b entity sets (matched via _norm normalization)
  - results table (union of metric/dataset pairs)
  - optional LLM-generated summary
"""
from __future__ import annotations

import re
from typing import Callable

from research_companion.graph import _norm
from research_companion.store import PaperMetadata, load_extraction
from research_companion.prompts import extraction_prompt_sha256, format_compare_prompt


def compare_papers(paper_a: str, paper_b: str, *, llm: Callable[[str], str] | None = None) -> dict:
    """Compare two papers, returning entity overlap and results table.

    Args:
        paper_a: paper ID of the first paper
        paper_b: paper ID of the second paper
        llm: optional callable(prompt) -> str for generating summary. If None, summary is null.

    Returns:
        dict with keys:
            version (int)
            paper_a (dict: paper_id, title)
            paper_b (dict: paper_id, title)
            shared (dict: concepts, methods, datasets)
            only_a (dict: concepts, methods, datasets)
            only_b (dict: concepts, methods, datasets)
            results (list of dicts: metric, dataset, value_a, value_b)
            summary (str | null)

    Raises:
        ValueError: if paper not found, or paper_a == paper_b
    """
    # Validate inputs
    if paper_a == paper_b:
        raise ValueError("Cannot compare a paper to itself")

    meta_a = PaperMetadata.load(paper_a)
    if meta_a is None:
        raise ValueError(f"Paper not found: {paper_a}")

    meta_b = PaperMetadata.load(paper_b)
    if meta_b is None:
        raise ValueError(f"Paper not found: {paper_b}")

    # Load extractions (may be None)
    prompt_sha = extraction_prompt_sha256()
    ext_a = load_extraction(paper_a, prompt_sha=prompt_sha) or {}
    ext_b = load_extraction(paper_b, prompt_sha=prompt_sha) or {}

    # Extract and normalize entity sets
    concepts_a = _extract_and_normalize(ext_a.get("concepts", []), "concepts")
    concepts_b = _extract_and_normalize(ext_b.get("concepts", []), "concepts")

    methods_a = _extract_and_normalize(ext_a.get("methods", []), "methods")
    methods_b = _extract_and_normalize(ext_b.get("methods", []), "methods")

    datasets_a = _extract_and_normalize(ext_a.get("datasets", []), "datasets")
    datasets_b = _extract_and_normalize(ext_b.get("datasets", []), "datasets")

    # Compute shared and unique
    shared_concepts, only_a_concepts, only_b_concepts = _split_entities(
        concepts_a, concepts_b
    )
    shared_methods, only_a_methods, only_b_methods = _split_entities(
        methods_a, methods_b
    )
    shared_datasets, only_a_datasets, only_b_datasets = _split_entities(
        datasets_a, datasets_b
    )

    # Build results table
    results = _build_results_table(ext_a.get("results", []), ext_b.get("results", []))

    # Generate summary if llm provided
    summary = None
    if llm is not None:
        summary = _generate_summary(
            llm, meta_a, meta_b,
            concepts_a, concepts_b,
            shared_concepts, shared_methods, shared_datasets,
            ext_a.get("claims", []), ext_b.get("claims", [])
        )

    return {
        "version": 1,
        "paper_a": {"paper_id": paper_a, "title": meta_a.title},
        "paper_b": {"paper_id": paper_b, "title": meta_b.title},
        "shared": {
            "concepts": shared_concepts,
            "methods": shared_methods,
            "datasets": shared_datasets,
        },
        "only_a": {
            "concepts": only_a_concepts,
            "methods": only_a_methods,
            "datasets": only_a_datasets,
        },
        "only_b": {
            "concepts": only_b_concepts,
            "methods": only_b_methods,
            "datasets": only_b_datasets,
        },
        "results": results,
        "summary": summary,
    }


def _extract_and_normalize(
    items: list[dict],
    entity_kind: str,
) -> dict[str, str]:
    """Extract entities and build norm_key -> display_name mapping.

    Args:
        items: list of entity dicts from extraction (each has "name" field)
        entity_kind: "concepts", "methods", or "datasets" (unused here, for clarity)

    Returns:
        dict mapping normalized key to first-seen display name
    """
    result: dict[str, str] = {}
    for item in items:
        name = item.get("name", "").strip()
        if not name:
            continue
        norm_key = _norm(name)
        # First-seen convention: only add if not already present
        if norm_key not in result:
            result[norm_key] = name
    return result


def _split_entities(
    entities_a: dict[str, str],
    entities_b: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """Split entities into shared, only_a, only_b.

    Args:
        entities_a: norm_key -> display_name from paper A
        entities_b: norm_key -> display_name from paper B

    Returns:
        (shared, only_a, only_b) — each a sorted list of display names
    """
    keys_a = set(entities_a.keys())
    keys_b = set(entities_b.keys())

    shared_keys = keys_a & keys_b
    only_a_keys = keys_a - keys_b
    only_b_keys = keys_b - keys_a

    # Use display names from A for shared (first-seen convention)
    shared = sorted([entities_a[k] for k in shared_keys], key=str.lower)
    only_a = sorted([entities_a[k] for k in only_a_keys], key=str.lower)
    only_b = sorted([entities_b[k] for k in only_b_keys], key=str.lower)

    return shared, only_a, only_b


def _build_results_table(
    results_a: list[dict],
    results_b: list[dict],
) -> list[dict]:
    """Build results union table (metric, dataset) pairs.

    Args:
        results_a: list of result dicts from paper A
        results_b: list of result dicts from paper B

    Returns:
        sorted list of dicts: metric, dataset, value_a, value_b
    """
    # Collect all (metric, dataset) pairs from both papers
    pairs: dict[tuple[str, str], dict] = {}

    # Process paper A results
    for result in results_a:
        metric = result.get("metric", "").strip()
        if not metric:
            # Skip malformed entries
            continue
        dataset = result.get("dataset", "").strip()
        value = result.get("value", "").strip()

        norm_metric = _norm(metric)
        norm_dataset = _norm(dataset)
        key = (norm_metric, norm_dataset)

        if key not in pairs:
            pairs[key] = {
                "metric": metric,
                "dataset": dataset,
                "value_a": value,
                "value_b": None,
            }
        else:
            # Override value_a (shouldn't happen, but be consistent)
            pairs[key]["value_a"] = value

    # Process paper B results
    for result in results_b:
        metric = result.get("metric", "").strip()
        if not metric:
            continue
        dataset = result.get("dataset", "").strip()
        value = result.get("value", "").strip()

        norm_metric = _norm(metric)
        norm_dataset = _norm(dataset)
        key = (norm_metric, norm_dataset)

        if key not in pairs:
            pairs[key] = {
                "metric": metric,
                "dataset": dataset,
                "value_a": None,
                "value_b": value,
            }
        else:
            # Update value_b
            pairs[key]["value_b"] = value

    # Sort by (metric, dataset) tuple
    sorted_pairs = sorted(
        pairs.items(),
        key=lambda item: (item[0][0], item[0][1])  # Sort by (norm_metric, norm_dataset)
    )

    return [data for _, data in sorted_pairs]


def _generate_summary(
    llm: Callable[[str], str],
    meta_a,
    meta_b,
    concepts_a: dict[str, str],
    concepts_b: dict[str, str],
    shared_concepts: list[str],
    shared_methods: list[str],
    shared_datasets: list[str],
    claims_a: list[dict],
    claims_b: list[dict],
) -> str | None:
    """Generate LLM summary using blocks of paper info.

    Args:
        llm: callable that takes prompt and returns string
        meta_a, meta_b: PaperMetadata objects
        concepts_a, concepts_b: entity dicts
        shared_concepts, shared_methods, shared_datasets: shared entity lists
        claims_a, claims_b: list of claim dicts

    Returns:
        summary string, or None if llm raises
    """
    try:
        # Build paper A block: title + top entities + top claims
        paper_a_lines = [
            f"Title: {meta_a.title}",
        ]
        if concepts_a:
            paper_a_lines.append(f"Concepts: {', '.join(sorted(concepts_a.values(), key=str.lower)[:5])}")
        if claims_a:
            top_claim = claims_a[0].get("text", "")
            if top_claim:
                paper_a_lines.append(f"Claim: {top_claim}")
        paper_a_block = "\n".join(paper_a_lines)

        # Build paper B block
        paper_b_lines = [
            f"Title: {meta_b.title}",
        ]
        if concepts_b:
            paper_b_lines.append(f"Concepts: {', '.join(sorted(concepts_b.values(), key=str.lower)[:5])}")
        if claims_b:
            top_claim = claims_b[0].get("text", "")
            if top_claim:
                paper_b_lines.append(f"Claim: {top_claim}")
        paper_b_block = "\n".join(paper_b_lines)

        # Build shared block
        shared_items = []
        if shared_concepts:
            shared_items.append(f"Concepts: {', '.join(shared_concepts[:3])}")
        if shared_methods:
            shared_items.append(f"Methods: {', '.join(shared_methods[:3])}")
        if shared_datasets:
            shared_items.append(f"Datasets: {', '.join(shared_datasets[:3])}")
        shared_block = "\n".join(shared_items) if shared_items else "No shared entities."

        # Format and call LLM
        prompt = format_compare_prompt(
            paper_a_block=paper_a_block,
            paper_b_block=paper_b_block,
            shared_block=shared_block,
        )

        summary = llm(prompt).strip()
        return summary

    except Exception:
        # LLM failed; return None
        return None
