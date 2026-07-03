"""Command-line interface for papergraph.

Subcommands:
    add <url-or-pdf> ... [-f FILE] [--title T] [--authors A,B,C] [--year Y]
    build [--provider anthropic|openai] [--model M] [--force]
    cost-estimate [--provider anthropic|openai] [--model M]
    view [--no-open]
    chat [<question>] [--provider P] [--model M] [--depth N]
    search <query> [--kind K] [--limit N] [--json]
    list
    remove <paper-id>
    stats
    export [--format {markdown,csv,json,obsidian}] [--output DIR]
    discover <topic> [--limit N] [--year-min Y] [--year-max Y] [--add] [--json]
    discover --expand [--limit N] [--min-citations N] [--add] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from papergraph import __version__


def _cmd_add(args: argparse.Namespace) -> int:
    from papergraph.fetch import FetchError, add_paper

    # --- collect targets from positional args + --from-file -----------------
    targets: list[str] = list(args.target) if args.target else []

    if args.from_file:
        fpath = Path(args.from_file)
        if not fpath.is_file():
            print(f"papergraph: file not found: {fpath}", file=sys.stderr)
            return 1
        for raw in fpath.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()   # strip inline comments
            if line:
                targets.append(line)

    if not targets:
        print("papergraph: nothing to add. Provide targets or use --from-file.",
              file=sys.stderr)
        return 1

    # --- metadata flags only make sense for a single local PDF --------------
    authors = [a.strip() for a in args.authors.split(",")] if args.authors else None
    has_local_meta = args.title or authors or args.year
    if has_local_meta and len(targets) > 1:
        print("papergraph: warning: --title/--authors/--year ignored when "
              "adding multiple targets", file=sys.stderr)
        has_local_meta = False
        authors = None

    # --- loop through targets -----------------------------------------------
    title = args.title if has_local_meta else None
    year = args.year if has_local_meta else None
    meta_authors = authors if has_local_meta else None

    failed = 0
    for target in targets:
        try:
            if has_local_meta:
                try:
                    meta = add_paper(target, title=title, authors=meta_authors, year=year)
                except TypeError:
                    # add_paper rejects local-PDF kwargs for arXiv inputs.
                    meta = add_paper(target)
            else:
                meta = add_paper(target)
        except FetchError as e:
            print(f"papergraph: failed to add {target}: {e}", file=sys.stderr)
            failed += 1
            continue
        print(f"+ {meta.paper_id}  {meta.title}")
        if meta.authors:
            print(f"  {', '.join(meta.authors[:3])}"
                  f"{'...' if len(meta.authors) > 3 else ''}, {meta.year or '?'}")

    if failed:
        print(f"\npapergraph: {failed}/{len(targets)} paper(s) failed.", file=sys.stderr)
    return 0 if not failed else 1


# ---------------------------------------------------------------------------
# Pricing (USD per 1M tokens, as of 2025)
# ---------------------------------------------------------------------------

_PRICING: dict[str, dict[str, tuple[float, float]]] = {
    # provider -> model-prefix -> (input_per_1M, output_per_1M)
    "anthropic": {"default": (3.00, 15.00)},
    "openai":    {"default": (2.50, 10.00)},
}

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-7",
    "openai":    "gpt-4o-2024-11-20",
}

# Approximate output tokens per extraction (response is ~500-1000 tokens).
_EST_OUTPUT_TOKENS_PER_PAPER = 800


def _lookup_pricing(provider: str) -> tuple[float, float]:
    """Return (input_cost_per_1M, output_cost_per_1M) for *provider*."""
    bucket = _PRICING.get(provider, _PRICING["anthropic"])
    return bucket["default"]


def _estimate_cost(
    total_input_tokens: int, total_output_tokens: int, provider: str,
) -> float:
    """Return estimated cost in USD."""
    in_rate, out_rate = _lookup_pricing(provider)
    return (total_input_tokens / 1_000_000) * in_rate + (total_output_tokens / 1_000_000) * out_rate


def _cmd_cost_estimate(args: argparse.Namespace) -> int:
    from papergraph.extract import MAX_PAPER_CHARS
    from papergraph.prompts import extraction_prompt_sha256
    from papergraph.store import list_papers, load_extraction, load_text, pdf_path

    papers = list_papers()
    if not papers:
        print("papergraph: no papers in store. Add some first: papergraph add <url-or-pdf>",
              file=sys.stderr)
        return 1

    provider = args.provider
    model = args.model or _DEFAULT_MODELS.get(provider, _DEFAULT_MODELS["anthropic"])
    prompt_sha = extraction_prompt_sha256()

    cached_n = 0
    need_extraction: list = []
    est_input_tokens = 0

    for meta in papers:
        cached = load_extraction(meta.paper_id, prompt_sha=prompt_sha)
        if cached is not None:
            cached_n += 1
            continue
        # Not cached -- estimate token count from paper text (or PDF size).
        text = load_text(meta.paper_id)
        if text is not None:
            char_count = min(len(text), MAX_PAPER_CHARS)
        else:
            pdf = pdf_path(meta.paper_id)
            if pdf is not None:
                # Rough heuristic: PDF bytes -> chars is ~0.5x for text-heavy PDFs.
                char_count = min(int(pdf.stat().st_size * 0.5), MAX_PAPER_CHARS)
            else:
                char_count = MAX_PAPER_CHARS  # worst-case fallback
        est_input_tokens += int(char_count / 4)
        need_extraction.append(meta)

    need_n = len(need_extraction)
    est_output_tokens = need_n * _EST_OUTPUT_TOKENS_PER_PAPER
    est_cost = _estimate_cost(est_input_tokens, est_output_tokens, provider)

    print(f"\npapergraph cost-estimate (provider: {provider}, model: {model})\n")
    print(f"  Papers in store:        {len(papers):>5}")
    print(f"  Already cached:         {cached_n:>5}")
    print(f"  Needing extraction:     {need_n:>5}")
    print()
    print(f"  Estimated input tokens:   ~{est_input_tokens:>,}")
    print(f"  Estimated output tokens:  ~{est_output_tokens:>,}")
    print(f"  Estimated cost:           ~${est_cost:,.2f}")
    print()
    print("Run `papergraph build` to proceed. Cached papers are free.")
    print()
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from papergraph.extract import ExtractionError, extract_paper
    from papergraph.graph import build_graph, graph_stats, save_graph
    from papergraph.store import list_papers

    papers = list_papers()
    if not papers:
        print("papergraph: no papers in store. Add some first: papergraph add <url-or-pdf>",
              file=sys.stderr)
        return 1

    print(f"papergraph: extracting from {len(papers)} paper(s) using {args.provider}...")
    total_in = total_out = 0
    cached_n = 0
    failed: list[str] = []
    t0 = time.perf_counter()

    for i, meta in enumerate(papers, 1):
        prefix = f"  [{i}/{len(papers)}]"
        try:
            _, usage = extract_paper(meta, provider=args.provider, model=args.model, force=args.force)
        except ExtractionError as e:
            print(f"{prefix} FAILED  {meta.title[:60]}: {e}", file=sys.stderr)
            failed.append(meta.paper_id)
            continue
        if usage.get("cached"):
            cached_n += 1
            print(f"{prefix} cached  {meta.title[:60]}")
        else:
            total_in += usage.get("input_tokens", 0)
            total_out += usage.get("output_tokens", 0)
            print(f"{prefix} {usage.get('input_tokens', 0)}+{usage.get('output_tokens', 0)} tok  "
                  f"{meta.title[:60]}")

    print(f"\npapergraph: extraction done in {time.perf_counter()-t0:.1f}s. "
          f"{cached_n} cached, {len(failed)} failed, {total_in}+{total_out} tokens used.")
    if total_in + total_out > 0:
        model_label = args.model or _DEFAULT_MODELS.get(args.provider, args.provider)
        est = _estimate_cost(total_in, total_out, args.provider)
        print(f"papergraph: estimated cost: ~${est:,.2f} "
              f"(based on {args.provider} {model_label} pricing)")

    print("papergraph: building cross-paper graph...")
    G = build_graph(papers)
    save_graph(G)
    stats = graph_stats(G)
    print(f"papergraph: graph saved with {stats['nodes_total']} nodes "
          f"({stats.get('node_paper', 0)} papers, "
          f"{stats.get('node_concept', 0)} concepts, "
          f"{stats.get('node_method', 0)} methods, "
          f"{stats.get('node_dataset', 0)} datasets) "
          f"and {stats['edges_total']} edges.")
    return 0 if not failed else 2


def _cmd_view(args: argparse.Namespace) -> int:
    from papergraph.viz import view

    p = view(open_browser=not args.no_open)
    print(f"papergraph: rendered {p}")
    if args.no_open:
        print(f"papergraph: open in browser:  file://{p.resolve().as_posix()}")
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    from papergraph.chat import chat
    from papergraph.graph import load_graph

    G = load_graph()
    if G.number_of_nodes() == 0:
        print("papergraph: graph is empty. Run `papergraph add <url>` then `papergraph build` first.",
              file=sys.stderr)
        return 1

    if args.question:
        ans = chat(args.question, G=G, provider=args.provider, model=args.model, depth=args.depth)
        _print_answer(ans)
        return 0

    # Interactive REPL.
    print(f"papergraph chat — {G.number_of_nodes()} nodes, {G.number_of_edges()} edges. "
          f"Ctrl-D / Ctrl-C to exit.")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q:
            continue
        if q in ("exit", "quit", ":q"):
            return 0
        ans = chat(q, G=G, provider=args.provider, model=args.model, depth=args.depth)
        _print_answer(ans)


def _print_answer(ans) -> None:
    print()
    print(ans.answer)
    print()
    print(f"--- {ans.n_subgraph_nodes} nodes, {ans.n_subgraph_edges} edges retrieved · "
          f"{ans.input_tokens}+{ans.output_tokens} tokens ---")


def _cmd_list(args: argparse.Namespace) -> int:
    from papergraph.store import list_papers

    papers = list_papers()
    if not papers:
        print("papergraph: no papers in store.")
        return 0
    if args.json:
        out = [{"paper_id": p.paper_id, "title": p.title, "authors": p.authors,
                "year": p.year, "added_at": p.added_at} for p in papers]
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(f"papergraph: {len(papers)} paper(s)")
    for p in papers:
        first = p.authors[0] if p.authors else "?"
        cite = f"{first} et al." if len(p.authors) > 1 else first
        print(f"  {p.paper_id}  ({cite}, {p.year or '?'})  {p.title[:60]}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    from papergraph.store import remove_paper

    ok = remove_paper(args.paper_id)
    if ok:
        print(f"papergraph: removed {args.paper_id}")
        print("papergraph: run `papergraph build` to rebuild the graph without it.")
        return 0
    print(f"papergraph: no such paper: {args.paper_id}", file=sys.stderr)
    return 1


def _cmd_stats(args: argparse.Namespace) -> int:
    from papergraph.graph import graph_stats, load_graph

    G = load_graph()
    if G.number_of_nodes() == 0:
        print("papergraph: graph is empty.")
        return 0
    stats = graph_stats(G)
    print(json.dumps(stats, indent=2))
    return 0


_SEARCH_KINDS = ("paper", "concept", "method", "dataset", "claim", "result")


def _score_node(query: str, label: str, description: str) -> int:
    """Score a node against a search query (case-insensitive).

    Scoring:
        +3  full query is a substring of label
        +2  full query is a substring of description
        +1  per individual query word found in label or description
    """
    q = query.lower()
    lbl = label.lower()
    desc = description.lower()
    score = 0
    if q in lbl:
        score += 3
    if q in desc:
        score += 2
    for word in q.split():
        if word in lbl or word in desc:
            score += 1
    return score


def _containing_papers(G, node_id: str) -> list[str]:
    """Return titles of paper nodes linked to *node_id* via a ``contains`` edge."""
    titles: list[str] = []
    for neighbor in G.neighbors(node_id):
        nd = G.nodes[neighbor]
        if nd.get("kind") != "paper":
            continue
        edge_data = G.edges[neighbor, node_id]
        if edge_data.get("relation") == "contains":
            titles.append(nd.get("label", neighbor))
    return titles


def _cmd_search(args: argparse.Namespace) -> int:
    from papergraph.graph import load_graph

    G = load_graph()
    if G.number_of_nodes() == 0:
        print("papergraph: graph is empty. Run `papergraph add <url>` then `papergraph build` first.",
              file=sys.stderr)
        return 1

    query: str = args.query
    kind_filter: list[str] | None = args.kind or None
    limit: int = args.limit

    # Score every node.
    hits: list[tuple[int, str, dict]] = []
    for nid, data in G.nodes(data=True):
        kind = data.get("kind", "")
        if kind_filter and kind not in kind_filter:
            continue
        label = data.get("label", "")
        description = data.get("definition") or data.get("description") or data.get("full_text") or ""
        score = _score_node(query, label, description)
        if score > 0:
            hits.append((score, nid, data))

    hits.sort(key=lambda t: t[0], reverse=True)
    hits = hits[:limit]

    if not hits:
        print(f'papergraph: no matches for "{query}"')
        return 0

    # --json mode
    if args.json:
        out = []
        for score, nid, data in hits:
            entry = {"id": nid, "kind": data.get("kind", ""), "label": data.get("label", ""),
                     "score": score}
            desc = data.get("definition") or data.get("description") or data.get("full_text") or ""
            if desc:
                entry["description"] = desc
            if data.get("kind") != "paper":
                papers = _containing_papers(G, nid)
                if papers:
                    entry["appears_in"] = papers
            out.append(entry)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    # Pretty-print mode
    print(f'\npapergraph: {len(hits)} match{"es" if len(hits) != 1 else ""} for "{query}"\n')

    for _score, nid, data in hits:
        kind = data.get("kind", "?")
        label = data.get("label", nid)

        if kind == "paper":
            # Paper node: show authors + year inline.
            authors = data.get("authors") or []
            year = data.get("year")
            if authors:
                first = authors[0]
                cite = f"{first} et al." if len(authors) > 1 else first
                cite_str = f" ({cite}, {year or '?'})"
            elif year:
                cite_str = f" ({year})"
            else:
                cite_str = ""
            print(f"  [{kind}]  {label}{cite_str}")
        else:
            desc = data.get("definition") or data.get("description") or data.get("full_text") or ""
            suffix = f" -- {desc[:80]}" if desc else ""
            print(f"  [{kind}]  {label}{suffix}")
            papers = _containing_papers(G, nid)
            if papers:
                paper_list = ", ".join(papers[:5])
                more = f", ... +{len(papers)-5}" if len(papers) > 5 else ""
                if kind == "result":
                    print(f"             -> from: {paper_list}{more}")
                else:
                    print(f"             -> appears in: {paper_list}{more}")

    print()
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from papergraph.export import export_graph

    output_dir = Path(args.output)
    fmt = args.format
    try:
        result = export_graph(output_dir, fmt=fmt)
    except Exception as e:
        print(f"papergraph: export failed: {e}", file=sys.stderr)
        return 1
    print(f"papergraph: exported ({fmt}) to {result.resolve()}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    from papergraph.discover import expand_from_existing, search_topic
    from papergraph.fetch import FetchError, add_paper

    # --- choose mode: topic search vs expand --------------------------------
    if args.expand:
        from papergraph.store import list_papers as _lp
        papers = _lp()
        if not papers:
            print("papergraph: no papers in store. Add some first, then use --expand.",
                  file=sys.stderr)
            return 1
        print(f"papergraph: scanning citations and references of {len(papers)} paper(s)...",
              file=sys.stderr)
        results = expand_from_existing(
            limit=args.limit,
            min_citations=args.min_citations,
        )
        mode_label = "citation expansion"
    else:
        if not args.topic:
            print("papergraph: provide a topic to search, or use --expand to scan "
                  "citations of existing papers.", file=sys.stderr)
            return 1
        topic = " ".join(args.topic)
        print(f'papergraph: searching Semantic Scholar for "{topic}"...',
              file=sys.stderr)
        results = search_topic(
            topic,
            limit=args.limit,
            year_min=args.year_min,
            year_max=args.year_max,
        )
        mode_label = "topic search"

    if not results:
        print(f"papergraph: no new papers found via {mode_label}.")
        return 0

    # --- JSON output --------------------------------------------------------
    if args.json:
        print(json.dumps([p.to_dict() for p in results], indent=2, ensure_ascii=False))
        if args.add:
            # Still add even in JSON mode.
            _auto_add_discovered(results, add_paper, FetchError)
        return 0

    # --- pretty print -------------------------------------------------------
    print(f"\npapergraph: {len(results)} paper(s) discovered via {mode_label}\n")
    for i, p in enumerate(results, 1):
        first = p.authors[0] if p.authors else "?"
        cite = f"{first} et al." if len(p.authors) > 1 else first
        year_str = str(p.year) if p.year else "?"
        cites = f"{p.citation_count:,} citations" if p.citation_count else "0 citations"

        # Source badge.
        if p.arxiv_id:
            src = f"arXiv:{p.arxiv_id}"
        elif p.doi:
            src = f"DOI:{p.doi}"
        else:
            src = "S2"

        print(f"  {i:>2}. {p.title}")
        print(f"      {cite}, {year_str} · {cites} · {src}")
        if p.source == "reference":
            print("      [referenced by your papers]")
        elif p.source == "citation":
            print("      [cites your papers]")

    # --- auto-add if --add flag set -----------------------------------------
    if args.add:
        print()
        added, failed = _auto_add_discovered(results, add_paper, FetchError)
        print(f"\npapergraph: added {added}/{len(results)}, "
              f"{failed} failed. Run `papergraph build` to extract.")
    else:
        print(f"\nTo add all: papergraph discover {'--expand' if args.expand else chr(34) + ' '.join(args.topic) + chr(34)} --add")
        print("Or add individually:")
        for p in results[:5]:
            print(f"  {p.add_cmd}")
        if len(results) > 5:
            print(f"  ... ({len(results) - 5} more)")

    print()
    return 0


def _auto_add_discovered(results, add_paper_fn, fetch_error_cls) -> tuple[int, int]:
    """Add all discovered papers to the local store. Returns (added, failed)."""
    added = failed = 0
    for p in results:
        target = p.arxiv_id or p.doi or (p.s2_id if p.s2_id else None)
        if target is None:
            continue
        try:
            meta = add_paper_fn(target)
            print(f"  + {meta.paper_id}  {meta.title[:60]}")
            added += 1
        except fetch_error_cls as e:
            print(f"  x failed: {p.title[:50]}: {e}", file=sys.stderr)
            failed += 1
    return added, failed


# Test seam: tests monkeypatch this to inject offline lookup/search callables.
REVIEW_CONTEXT_OVERRIDES: dict = {}


def _cmd_review(args: argparse.Namespace) -> int:
    import asyncio

    from papergraph.agents.base import AgentContext
    from papergraph.agents.benchmark import BenchmarkAgent
    from papergraph.agents.bus import Bus
    from papergraph.agents.citation import CitationAgent
    from papergraph.agents.confidence import ConfidenceAgent
    from papergraph.agents.ingest import IngestAgent
    from papergraph.agents.novelty import NoveltyAgent
    from papergraph.agents.orchestrator import run_agents
    from papergraph.agents.priorart import PriorArtAgent

    agents = [IngestAgent(), CitationAgent(), PriorArtAgent()]
    if not args.fast:
        agents += [NoveltyAgent(), ConfidenceAgent(), BenchmarkAgent()]
    ctx = AgentContext(paper_id=args.paper_id, bus=Bus(),
                       data=dict(REVIEW_CONTEXT_OVERRIDES))
    results = asyncio.run(run_agents(agents, ctx))

    if args.json:
        payload = {
            "paper_id": args.paper_id,
            "agents": {name: {"ok": r.ok, "data": r.data, "error": r.error}
                       for name, r in results.items()},
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if all(r.ok for r in results.values()) else 1

    summaries = {
        "ingest": lambda d: f"graph: {d['graph_nodes']} nodes / {d['graph_edges']} edges",
        "citation": lambda d: (f"{d['counts']['verified']} verified · "
                               f"{d['counts']['suspect']} suspect · "
                               f"{d['counts']['unverified']} unverified"),
        "priorart": lambda d: f"{d['count']} related papers",
        "novelty": lambda d: ", ".join(f"{v}: {n}" for v, n in sorted(d["counts"].items()))
                             or "no claims",
        "confidence": lambda d: f"{len(d['claims'])} claim(s) scored",
        "benchmark": lambda d: f"{len(d['suggestions'])} benchmark(s) suggested",
    }
    for agent in agents:
        r = results[agent.name]
        if r.ok:
            print(f"  {agent.name:<10} done    {summaries.get(agent.name, lambda d: str(d)[:80])(r.data)}")
        else:
            print(f"  {agent.name:<10} FAILED  {r.error}")
    ok = all(r.ok for r in results.values())
    print(f"\n{'All agents completed.' if ok else 'Some agents failed.'}")
    return 0 if ok else 1


REBUTTAL_CONTEXT_OVERRIDES: dict = {}


def _cmd_rebuttal(args: argparse.Namespace) -> int:
    import asyncio

    from papergraph.agents.base import AgentContext
    from papergraph.agents.bus import Bus
    from papergraph.agents.ingest import IngestAgent
    from papergraph.agents.orchestrator import run_agents
    from papergraph.agents.rebuttal import RebuttalAgent
    from papergraph.rebuttal.models import concerns_from_json, concerns_to_json
    from papergraph.rebuttal.segment import segment_reviews

    if not args.reviews and not args.segments:
        print("papergraph: provide --reviews FILE or --segments FILE.", file=sys.stderr)
        return 1

    reviews_text = ""
    if args.reviews:
        rpath = Path(args.reviews)
        if not rpath.is_file():
            print(f"papergraph: reviews file not found: {rpath}", file=sys.stderr)
            return 1
        reviews_text = rpath.read_text(encoding="utf-8")

    if args.emit_segments:
        concerns = segment_reviews(reviews_text)
        Path(args.emit_segments).write_text(concerns_to_json(concerns), encoding="utf-8")
        print(f"papergraph: wrote {len(concerns)} segment(s) to {args.emit_segments}. "
              "Edit, then rerun with --segments.")
        return 0

    ctx_data = dict(REBUTTAL_CONTEXT_OVERRIDES)
    ctx_data["_reviews_text"] = reviews_text
    ctx_data["_tone"] = args.tone
    if args.segments:
        ctx_data["_concerns"] = concerns_from_json(
            Path(args.segments).read_text(encoding="utf-8"))

    ctx = AgentContext(paper_id=args.paper_id, bus=Bus(), data=ctx_data)
    results = asyncio.run(run_agents([IngestAgent(), RebuttalAgent()], ctx))
    reb = results["rebuttal"]
    if not reb.ok:
        print(f"papergraph: rebuttal failed: {reb.error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(reb.data, indent=2, ensure_ascii=False))
        return 0

    kinds = {c["concern_id"]: c["kind"] for c in reb.data["concerns"]}
    for d in reb.data["drafts"]:
        status = ("[OK all quotes verified]" if d["verified"]
                  else f"[CHECK {len(d['unverified_spans'])} unverified span(s)]")
        print(f"\n{d['concern_id']} ({kinds.get(d['concern_id'], '?')})  {status}")
        print(f"  {d['reply']}")
        if d["planned_revision"]:
            print(f"  Revision: {d['planned_revision']}")
    if reb.data["changelog"]:
        print("\nPlanned revisions:")
        for item in reb.data["changelog"]:
            print(f"  - {item}")
    return 0


def _cmd_refcheck(args: argparse.Namespace) -> int:
    from papergraph.prompts import extraction_prompt_sha256
    from papergraph.refcheck.parse import references_from_extraction
    from papergraph.refcheck.retrieval import default_lookup
    from papergraph.refcheck.validate import validate_bibliography
    from papergraph.store import load_extraction

    ext = load_extraction(args.paper_id, prompt_sha=extraction_prompt_sha256())
    if ext is None:
        print(
            f"papergraph: no extraction for {args.paper_id}. Run `papergraph build` first.",
            file=sys.stderr,
        )
        return 1

    refs = references_from_extraction(ext)
    report = validate_bibliography(refs, default_lookup())
    counts = report.counts()

    if args.json:
        payload = {
            "paper_id": args.paper_id,
            "counts": counts,
            "references": [
                {
                    "title": ref.title,
                    "status": verdict.status,
                    "reasons": verdict.reasons,
                    "doi": ref.doi,
                    "arxiv_id": ref.arxiv_id,
                }
                for ref, verdict in report.entries
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if not report.entries:
        print("papergraph: no references found in this paper's extraction.")
        return 0

    symbol = {"verified": "OK ", "suspect": "?? ", "unverified": "XX "}
    for ref, verdict in report.entries:
        print(f"{symbol[verdict.status]} [{verdict.status}] {ref.title}")
        for reason in verdict.reasons:
            print(f"        - {reason}")
    print(
        f"\nSummary: {counts['verified']} verified, "
        f"{counts['suspect']} suspect, {counts['unverified']} unverified "
        f"({len(report.entries)} references)"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="papergraph",
        description="Knowledge graph + chat over a corpus of research papers.",
    )
    p.add_argument("--version", action="version", version=f"papergraph {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="Add arXiv URL(s)/ID(s) or local PDF(s)")
    pa.add_argument("target", nargs="*", help="arXiv URL/ID (e.g. 2410.05779) or path to PDF")
    pa.add_argument("-f", "--from-file", metavar="FILE",
                    help="Read targets from FILE (one per line; # comments)")
    pa.add_argument("--title", help="Title (single local PDF only)")
    pa.add_argument("--authors", help="Comma-separated authors (single local PDF only)")
    pa.add_argument("--year", type=int, help="Year (single local PDF only)")
    pa.set_defaults(func=_cmd_add)

    pb = sub.add_parser("build", help="Run extraction on all papers and build the graph")
    pb.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    pb.add_argument("--model", default=None, help="Model override (defaults to provider's recommended)")
    pb.add_argument("--force", action="store_true", help="Re-extract even if cached")
    pb.set_defaults(func=_cmd_build)

    pce = sub.add_parser("cost-estimate", help="Estimate API cost for the next build")
    pce.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    pce.add_argument("--model", default=None, help="Model override (defaults to provider's recommended)")
    pce.set_defaults(func=_cmd_cost_estimate)

    pv = sub.add_parser("view", help="Render and open the interactive HTML graph")
    pv.add_argument("--no-open", action="store_true", help="Don't auto-open the browser")
    pv.set_defaults(func=_cmd_view)

    pc = sub.add_parser("chat", help="Ask a question (one-shot if argument given, else REPL)")
    pc.add_argument("question", nargs="?", help="Question (omit for interactive REPL)")
    pc.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    pc.add_argument("--model", default=None)
    pc.add_argument("--depth", type=int, default=2, help="BFS hop depth (default 2)")
    pc.set_defaults(func=_cmd_chat)

    pq = sub.add_parser("search", help="Search the knowledge graph by keyword")
    pq.add_argument("query", help="Search term")
    pq.add_argument("-k", "--kind", action="append", choices=_SEARCH_KINDS,
                    help="Filter by node kind (repeatable)")
    pq.add_argument("-n", "--limit", type=int, default=20, help="Max results (default 20)")
    pq.add_argument("--json", action="store_true", help="JSON output")
    pq.set_defaults(func=_cmd_search)

    pl = sub.add_parser("list", help="List papers in the local store")
    pl.add_argument("--json", action="store_true", help="JSON output")
    pl.set_defaults(func=_cmd_list)

    pr = sub.add_parser("remove", help="Remove a paper from the store")
    pr.add_argument("paper_id", help="Paper ID, e.g. arxiv:2410.05779 or local:abc123")
    pr.set_defaults(func=_cmd_remove)

    ps = sub.add_parser("stats", help="Print graph statistics as JSON")
    ps.set_defaults(func=_cmd_stats)

    pe = sub.add_parser("export", help="Export the knowledge graph to a portable format")
    pe.add_argument("--format", choices=["markdown", "csv", "json", "obsidian"],
                    default="markdown", help="Export format (default: markdown)")
    pe.add_argument("--output", default="./papergraph-export/",
                    help="Output directory (default: ./papergraph-export/)")
    pe.set_defaults(func=_cmd_export)

    pd = sub.add_parser("discover",
                        help="Discover related papers via Semantic Scholar (topic search or citation expansion)")
    pd.add_argument("topic", nargs="*",
                    help="Topic to search for (e.g. 'graph-based RAG')")
    pd.add_argument("--expand", action="store_true",
                    help="Discover papers by following citations/references of existing papers")
    pd.add_argument("-n", "--limit", type=int, default=20,
                    help="Max papers to return (default 20)")
    pd.add_argument("--year-min", type=int, default=None,
                    help="Minimum publication year (topic search only)")
    pd.add_argument("--year-max", type=int, default=None,
                    help="Maximum publication year (topic search only)")
    pd.add_argument("--min-citations", type=int, default=5,
                    help="Minimum citation count for --expand mode (default 5)")
    pd.add_argument("--add", action="store_true",
                    help="Automatically add all discovered papers to the store")
    pd.add_argument("--json", action="store_true", help="JSON output")
    pd.set_defaults(func=_cmd_discover)

    prc = sub.add_parser("refcheck",
                         help="Validate a paper's references against CrossRef/OpenAlex")
    prc.add_argument("paper_id", help="ID of a paper already built (see `papergraph list`)")
    prc.add_argument("--json", action="store_true", help="JSON output")
    prc.set_defaults(func=_cmd_refcheck)

    prv = sub.add_parser("review",
                         help="Run the agent team over a paper (ingest, citations, prior art)")
    prv.add_argument("paper_id", help="ID of a paper already built (see `papergraph list`)")
    prv.add_argument("--json", action="store_true", help="JSON output")
    prv.add_argument("--fast", action="store_true",
                     help="Skip LLM lanes (novelty, confidence, benchmark)")
    prv.set_defaults(func=_cmd_review)

    prb = sub.add_parser("rebuttal", help="Draft grounded replies to reviewer comments")
    prb.add_argument("paper_id", help="ID of a paper already built")
    prb.add_argument("--reviews", help="Path to a text file with the reviewer comments")
    prb.add_argument("--emit-segments", help="Segment reviews, write JSON here, and stop")
    prb.add_argument("--segments", help="Resume from an edited segments JSON file")
    prb.add_argument("--tone", choices=["deferential", "balanced", "firm"], default="balanced")
    prb.add_argument("--json", action="store_true", help="JSON output")
    prb.set_defaults(func=_cmd_rebuttal)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
