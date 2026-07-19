"""Export the research-companion knowledge graph to portable formats.

Supported formats:
    markdown  — directory of per-paper .md files + _index.md
    csv       — nodes.csv + edges.csv
    json      — graph.json + papers.json
    obsidian  — markdown with [[wikilinks]]; each concept/method/dataset gets its own note
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any


def export_graph(output_dir: Path, *, fmt: str = "markdown") -> Path:
    """Export the knowledge graph to *output_dir* in the requested format.

    Returns the output directory path (created/overwritten).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "markdown":
        return _export_markdown(output_dir)
    elif fmt == "csv":
        return _export_csv(output_dir)
    elif fmt == "json":
        return _export_json(output_dir)
    elif fmt == "obsidian":
        return _export_obsidian(output_dir)
    else:
        raise ValueError(f"unknown export format {fmt!r} (expected markdown, csv, json, or obsidian)")


# ---------------------------------------------------------------------------
# Helpers — load graph + paper data
# ---------------------------------------------------------------------------

def _load_data() -> tuple[Any, list[Any], dict[str, dict]]:
    """Return (graph, papers, extractions_by_paper_id).

    Lazy-imports graph/store modules so CLI startup stays fast.
    """
    from research_companion.graph import load_graph
    from research_companion.prompts import extraction_prompt_sha256
    from research_companion.store import list_papers, load_extraction

    G = load_graph()
    papers = list_papers()
    prompt_sha = extraction_prompt_sha256()
    extractions: dict[str, dict] = {}
    for meta in papers:
        ext = load_extraction(meta.paper_id, prompt_sha=prompt_sha)
        if ext is not None:
            extractions[meta.paper_id] = ext
    return G, papers, extractions


def _sanitize_filename(name: str) -> str:
    """Turn a paper title into a filesystem-safe filename (no extension)."""
    import re
    s = re.sub(r"[^\w\s-]", "", name)
    s = re.sub(r"[\s]+", "_", s.strip())
    return s[:120] or "untitled"


def _dedupe_filename(base: str, used: dict[str, int]) -> str:
    """Return a filename unique within *used*, appending -2, -3, ... on collision.

    Mirrors the house pattern in ``interop/bibtex.py``'s ``_alpha_suffix``
    (used there to disambiguate colliding cite keys): track how many times a
    base name has been seen and append a short, deterministic disambiguator
    on repeats, so two different papers/entities whose sanitized names
    collide never silently overwrite each other on disk.

    Mutates *used* to record the new count for *base*.
    """
    if base not in used:
        used[base] = 1
        return base
    used[base] += 1
    return f"{base}-{used[base]}"


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

def _export_markdown(output_dir: Path) -> Path:
    _, papers, extractions = _load_data()

    index_lines: list[str] = ["# research-companion — Paper Index\n"]
    file_map: dict[str, str] = {}  # paper_id -> filename (without .md)
    used_names: dict[str, int] = {}

    for meta in papers:
        fname = _dedupe_filename(_sanitize_filename(meta.title), used_names)
        file_map[meta.paper_id] = fname
        ext = extractions.get(meta.paper_id, {})

        lines: list[str] = []
        lines.append(f"# {meta.title}\n")

        if meta.authors:
            lines.append(f"**Authors:** {', '.join(meta.authors)}")
        if meta.year:
            lines.append(f"**Year:** {meta.year}")
        if meta.source_url:
            lines.append(f"**Source:** {meta.source_url}")
        lines.append("")

        # Concepts.
        concepts = ext.get("concepts", [])
        if concepts:
            lines.append("## Concepts")
            for c in concepts:
                name = c.get("name", "")
                defn = c.get("definition", "")
                lines.append(f"- **{name}**: {defn}" if defn else f"- **{name}**")
            lines.append("")

        # Methods.
        methods = ext.get("methods", [])
        if methods:
            lines.append("## Methods")
            for m in methods:
                name = m.get("name", "")
                desc = m.get("description", "")
                lines.append(f"- **{name}**: {desc}" if desc else f"- **{name}**")
            lines.append("")

        # Datasets.
        datasets = ext.get("datasets", [])
        if datasets:
            lines.append("## Datasets")
            for d in datasets:
                name = d.get("name", "")
                desc = d.get("description", "")
                lines.append(f"- **{name}**: {desc}" if desc else f"- **{name}**")
            lines.append("")

        # Claims.
        claims = ext.get("claims", [])
        if claims:
            lines.append("## Key Claims")
            for cl in claims:
                text = cl.get("text", "")
                if text:
                    lines.append(f"- {text}")
            lines.append("")

        # Results.
        results = ext.get("results", [])
        if results:
            lines.append("## Results")
            lines.append("| Metric | Value | Dataset |")
            lines.append("|--------|-------|---------|")
            for r in results:
                metric = r.get("metric", "")
                value = r.get("value", "")
                dataset = r.get("dataset", "")
                lines.append(f"| {metric} | {value} | {dataset} |")
            lines.append("")

        # Related work.
        related = ext.get("related_work", [])
        if related:
            lines.append("## Related Work")
            for ref in related:
                if ref:
                    lines.append(f"- {ref}")
            lines.append("")

        md_path = output_dir / f"{fname}.md"
        md_path.write_text("\n".join(lines), encoding="utf-8")

        # Index entry.
        first = meta.authors[0] if meta.authors else "?"
        cite = f"{first} et al." if len(meta.authors) > 1 else first
        index_lines.append(f"- [{meta.title}]({fname}.md) ({cite}, {meta.year or '?'})")

    index_path = output_dir / "_index.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return output_dir


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def _export_csv(output_dir: Path) -> Path:
    G, papers, _ = _load_data()

    # nodes.csv
    nodes_path = output_dir / "nodes.csv"
    with nodes_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "kind", "label", "definition_or_description",
                         "authors", "year", "source_url"])
        for nid, data in G.nodes(data=True):
            kind = data.get("kind", "")
            label = data.get("label", "")
            defn = data.get("definition", "") or data.get("description", "") or data.get("full_text", "")
            authors = "; ".join(data.get("authors", [])) if isinstance(data.get("authors"), list) else ""
            year = str(data.get("year", "")) if data.get("year") else ""
            source_url = data.get("source_url", "")
            writer.writerow([nid, kind, label, defn, authors, year, source_url])

    # edges.csv
    edges_path = output_dir / "edges.csv"
    with edges_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target", "relation", "weight"])
        for u, v, data in G.edges(data=True):
            relation = data.get("relation", "")
            weight = str(data.get("weight", "")) if data.get("weight") else ""
            writer.writerow([u, v, relation, weight])

    return output_dir


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def _export_json(output_dir: Path) -> Path:
    from research_companion.store import graph_json_path

    G, papers, extractions = _load_data()

    # Copy the raw graph.json.
    src = graph_json_path()
    if src.exists():
        shutil.copy2(src, output_dir / "graph.json")
    else:
        # Fall back: serialise from the in-memory graph.
        from networkx.readwrite import json_graph
        try:
            data = json_graph.node_link_data(G, edges="links")
        except TypeError:
            # Older networkx (<3.4) doesn't support the `edges` kwarg.
            data = json_graph.node_link_data(G)
        (output_dir / "graph.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # papers.json — paper metadata + their extractions.
    papers_out: list[dict[str, Any]] = []
    for meta in papers:
        entry: dict[str, Any] = {
            "paper_id": meta.paper_id,
            "title": meta.title,
            "authors": meta.authors,
            "year": meta.year,
            "abstract": meta.abstract,
            "source_url": meta.source_url,
            "added_at": meta.added_at,
        }
        ext = extractions.get(meta.paper_id)
        if ext is not None:
            entry["extraction"] = ext
        papers_out.append(entry)
    (output_dir / "papers.json").write_text(
        json.dumps(papers_out, indent=2, ensure_ascii=False), encoding="utf-8")

    return output_dir


# ---------------------------------------------------------------------------
# Obsidian export  (markdown + [[wikilinks]], one note per entity)
# ---------------------------------------------------------------------------

def _export_obsidian(output_dir: Path) -> Path:
    _, papers, extractions = _load_data()

    # Collect every entity across all papers so each gets its own note.
    # entity_key -> {"kind": ..., "name": ..., "detail": ..., "papers": [paper_id, ...]}
    entities: dict[str, dict[str, Any]] = {}

    for meta in papers:
        ext = extractions.get(meta.paper_id, {})
        for c in ext.get("concepts", []):
            name = c.get("name", "")
            if not name:
                continue
            key = name.lower()
            if key not in entities:
                entities[key] = {"kind": "concept", "name": name,
                                 "detail": c.get("definition", ""), "papers": []}
            entities[key]["papers"].append(meta.paper_id)

        for m in ext.get("methods", []):
            name = m.get("name", "")
            if not name:
                continue
            key = name.lower()
            if key not in entities:
                entities[key] = {"kind": "method", "name": name,
                                 "detail": m.get("description", ""), "papers": []}
            entities[key]["papers"].append(meta.paper_id)

        for d in ext.get("datasets", []):
            name = d.get("name", "")
            if not name:
                continue
            key = name.lower()
            if key not in entities:
                entities[key] = {"kind": "dataset", "name": name,
                                 "detail": d.get("description", ""), "papers": []}
            entities[key]["papers"].append(meta.paper_id)

    # Build a paper_id -> title map for back-links.
    paper_title: dict[str, str] = {m.paper_id: m.title for m in papers}

    # paper_id -> actual filename written (without .md), populated below as
    # paper notes are written. Entity "Mentioned in" back-links look this up
    # by paper_id instead of re-sanitizing the title, so a back-link always
    # resolves to the real (possibly disambiguated) file — see the entity
    # notes loop further down.
    paper_fname: dict[str, str] = {}
    # Shared across BOTH paper and entity notes below — they are written to the
    # same output_dir, so a paper title and an entity name that sanitize to the
    # same base filename must be deduped against ONE namespace. Two separate
    # dicts (one per category) would let a paper note and an entity note both
    # claim the same on-disk filename and silently overwrite each other.
    used_names: dict[str, int] = {}

    # --- Paper notes (one per paper) ---
    for meta in papers:
        ext = extractions.get(meta.paper_id, {})
        lines: list[str] = []
        lines.append(f"# {meta.title}\n")

        if meta.authors:
            lines.append(f"**Authors:** {', '.join(meta.authors)}")
        if meta.year:
            lines.append(f"**Year:** {meta.year}")
        if meta.source_url:
            lines.append(f"**Source:** {meta.source_url}")
        lines.append("")

        # Concepts with wikilinks.
        concepts = ext.get("concepts", [])
        if concepts:
            lines.append("## Concepts")
            for c in concepts:
                name = c.get("name", "")
                defn = c.get("definition", "")
                link = f"[[{name}]]"
                lines.append(f"- {link}: {defn}" if defn else f"- {link}")
            lines.append("")

        # Methods with wikilinks.
        methods = ext.get("methods", [])
        if methods:
            lines.append("## Methods")
            for m in methods:
                name = m.get("name", "")
                desc = m.get("description", "")
                link = f"[[{name}]]"
                lines.append(f"- {link}: {desc}" if desc else f"- {link}")
            lines.append("")

        # Datasets with wikilinks.
        datasets = ext.get("datasets", [])
        if datasets:
            lines.append("## Datasets")
            for d in datasets:
                name = d.get("name", "")
                desc = d.get("description", "")
                link = f"[[{name}]]"
                lines.append(f"- {link}: {desc}" if desc else f"- {link}")
            lines.append("")

        # Claims (no links needed).
        claims = ext.get("claims", [])
        if claims:
            lines.append("## Key Claims")
            for cl in claims:
                text = cl.get("text", "")
                if text:
                    lines.append(f"- {text}")
            lines.append("")

        # Results.
        results = ext.get("results", [])
        if results:
            lines.append("## Results")
            lines.append("| Metric | Value | Dataset |")
            lines.append("|--------|-------|---------|")
            for r in results:
                metric = r.get("metric", "")
                value = r.get("value", "")
                dataset = r.get("dataset", "")
                ds_link = f"[[{dataset}]]" if dataset else ""
                lines.append(f"| {metric} | {value} | {ds_link} |")
            lines.append("")

        # Related work.
        related = ext.get("related_work", [])
        if related:
            lines.append("## Related Work")
            for ref in related:
                if ref:
                    lines.append(f"- {ref}")
            lines.append("")

        fname = _dedupe_filename(_sanitize_filename(meta.title), used_names)
        paper_fname[meta.paper_id] = fname
        (output_dir / f"{fname}.md").write_text("\n".join(lines), encoding="utf-8")

    # --- Entity notes (one per concept/method/dataset) ---
    for info in entities.values():
        name = info["name"]
        kind = info["kind"]
        detail = info["detail"]
        paper_ids = info["papers"]

        lines = []
        lines.append(f"# {name}\n")
        lines.append(f"**Type:** {kind}")
        if detail:
            lines.append(f"\n{detail}")
        lines.append("")

        lines.append("## Mentioned in")
        for pid in paper_ids:
            # Look up the actual filename written for this paper (not a fresh
            # re-sanitization of its title) so this link resolves correctly
            # even when the paper's sanitized name collided with another's
            # and got disambiguated above.
            fname = paper_fname.get(pid) or _sanitize_filename(paper_title.get(pid, pid))
            lines.append(f"- [[{fname}]]")
        lines.append("")

        entity_fname = _dedupe_filename(_sanitize_filename(name), used_names)
        (output_dir / f"{entity_fname}.md").write_text("\n".join(lines), encoding="utf-8")

    return output_dir
