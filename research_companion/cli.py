"""Command-line interface for research_companion.

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
    set-draft <paper_id> [--clear] [--show]
    align <paper_id> [--against <paper_id>] [--force] [--json]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

from research_companion import __version__


def _parse_connectors_arg(value):
    """Parse --connectors 'europepmc,pubmed,dblp' -> ['europepmc','pubmed','dblp'];
    None if the flag was omitted (so settings are used). Exits on an unknown name."""
    if not value:
        return None
    from research_companion.connectors import VALID_CONNECTORS
    names = [v.strip() for v in value.split(",") if v.strip()]
    bad = [n for n in names if n not in VALID_CONNECTORS]
    if bad:
        print(f"research-companion: unknown connector(s): {', '.join(bad)}. "
              f"Valid: {', '.join(sorted(VALID_CONNECTORS))}", file=sys.stderr)
        raise SystemExit(2)
    return names or None


def _cmd_add(args: argparse.Namespace) -> int:
    from research_companion.fetch import FetchError, add_paper

    # --- collect targets from positional args + --from-file -----------------
    targets: list[str] = list(args.target) if args.target else []

    if args.from_file:
        fpath = Path(args.from_file)
        if not fpath.is_file():
            print(f"research-companion: file not found: {fpath}", file=sys.stderr)
            return 1
        for raw in fpath.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()   # strip inline comments
            if line:
                targets.append(line)

    if not targets:
        print("research-companion: nothing to add. Provide targets or use --from-file.",
              file=sys.stderr)
        return 1

    # --- metadata flags only make sense for a single local PDF --------------
    authors = [a.strip() for a in args.authors.split(",")] if args.authors else None
    has_local_meta = args.title or authors or args.year
    if has_local_meta and len(targets) > 1:
        print("research-companion: warning: --title/--authors/--year ignored when "
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
            print(f"research-companion: failed to add {target}: {e}", file=sys.stderr)
            failed += 1
            continue
        print(f"+ {meta.paper_id}  {meta.title}")
        if meta.authors:
            print(f"  {', '.join(meta.authors[:3])}"
                  f"{'...' if len(meta.authors) > 3 else ''}, {meta.year or '?'}")

    if failed:
        print(f"\nresearch-companion: {failed}/{len(targets)} paper(s) failed.", file=sys.stderr)
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
    from research_companion.extract import MAX_PAPER_CHARS
    from research_companion.prompts import extraction_prompt_sha256
    from research_companion.store import list_papers, load_extraction, load_text, pdf_path

    papers = list_papers()
    if not papers:
        print("research-companion: no papers in store. Add some first: research-companion add <url-or-pdf>",
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

    print(f"\nresearch-companion cost-estimate (provider: {provider}, model: {model})\n")
    print(f"  Papers in store:        {len(papers):>5}")
    print(f"  Already cached:         {cached_n:>5}")
    print(f"  Needing extraction:     {need_n:>5}")
    print()
    print(f"  Estimated input tokens:   ~{est_input_tokens:>,}")
    print(f"  Estimated output tokens:  ~{est_output_tokens:>,}")
    print(f"  Estimated cost:           ~${est_cost:,.2f}")
    print()
    print("Run `research-companion build` to proceed. Cached papers are free.")
    print()
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from research_companion.extract import ExtractionError, extract_paper
    from research_companion.graph import build_graph, graph_stats, save_graph
    from research_companion.store import list_papers

    papers = list_papers()
    if not papers:
        print("research-companion: no papers in store. Add some first: research-companion add <url-or-pdf>",
              file=sys.stderr)
        return 1

    print(f"research-companion: extracting from {len(papers)} paper(s) using {args.provider}...")
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

    print(f"\nresearch-companion: extraction done in {time.perf_counter()-t0:.1f}s. "
          f"{cached_n} cached, {len(failed)} failed, {total_in}+{total_out} tokens used.")
    if total_in + total_out > 0:
        model_label = args.model or _DEFAULT_MODELS.get(args.provider, args.provider)
        est = _estimate_cost(total_in, total_out, args.provider)
        print(f"research-companion: estimated cost: ~${est:,.2f} "
              f"(based on {args.provider} {model_label} pricing)")

    print("research-companion: building cross-paper graph...")
    G = build_graph(papers)
    save_graph(G)
    stats = graph_stats(G)
    print(f"research-companion: graph saved with {stats['nodes_total']} nodes "
          f"({stats.get('node_paper', 0)} papers, "
          f"{stats.get('node_concept', 0)} concepts, "
          f"{stats.get('node_method', 0)} methods, "
          f"{stats.get('node_dataset', 0)} datasets) "
          f"and {stats['edges_total']} edges.")
    return 0 if not failed else 2


def _cmd_view(args: argparse.Namespace) -> int:
    from research_companion.viz import view

    p = view(open_browser=not args.no_open)
    print(f"research-companion: rendered {p}")
    if args.no_open:
        print(f"research-companion: open in browser:  file://{p.resolve().as_posix()}")
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    from research_companion.chat import chat
    from research_companion.graph import load_graph

    G = load_graph()
    if G.number_of_nodes() == 0:
        print("research-companion: graph is empty. Run `research-companion add <url>` then `research-companion build` first.",
              file=sys.stderr)
        return 1

    if args.question:
        ans = chat(args.question, G=G, provider=args.provider, model=args.model, depth=args.depth)
        _print_answer(ans)
        return 0

    # Interactive REPL.
    print(f"research-companion chat — {G.number_of_nodes()} nodes, {G.number_of_edges()} edges. "
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
    from research_companion.store import list_papers

    papers = list_papers()
    if not papers:
        print("research-companion: no papers in store.")
        return 0
    if args.json:
        out = [{"paper_id": p.paper_id, "title": p.title, "authors": p.authors,
                "year": p.year, "added_at": p.added_at} for p in papers]
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(f"research-companion: {len(papers)} paper(s)")
    for p in papers:
        first = p.authors[0] if p.authors else "?"
        cite = f"{first} et al." if len(p.authors) > 1 else first
        print(f"  {p.paper_id}  ({cite}, {p.year or '?'})  {p.title[:60]}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    from research_companion.store import remove_paper

    ok = remove_paper(args.paper_id)
    if ok:
        print(f"research-companion: removed {args.paper_id}")
        print("research-companion: run `research-companion build` to rebuild the graph without it.")
        return 0
    print(f"research-companion: no such paper: {args.paper_id}", file=sys.stderr)
    return 1


def _cmd_stats(args: argparse.Namespace) -> int:
    from research_companion.graph import graph_stats, load_graph

    G = load_graph()
    if G.number_of_nodes() == 0:
        print("research-companion: graph is empty.")
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
    from research_companion.graph import load_graph

    G = load_graph()
    if G.number_of_nodes() == 0:
        print("research-companion: graph is empty. Run `research-companion add <url>` then `research-companion build` first.",
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
        print(f'research-companion: no matches for "{query}"')
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
    print(f'\nresearch-companion: {len(hits)} match{"es" if len(hits) != 1 else ""} for "{query}"\n')

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
    from research_companion.export import export_graph

    output_dir = Path(args.output)
    fmt = args.format
    try:
        result = export_graph(output_dir, fmt=fmt)
    except Exception as e:
        print(f"research-companion: export failed: {e}", file=sys.stderr)
        return 1
    print(f"research-companion: exported ({fmt}) to {result.resolve()}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    from research_companion.discover import expand_from_existing, search_topic
    from research_companion.fetch import FetchError, add_paper

    # --- choose mode: topic search vs expand --------------------------------
    if args.expand:
        from research_companion.store import list_papers as _lp
        papers = _lp()
        if not papers:
            print("research-companion: no papers in store. Add some first, then use --expand.",
                  file=sys.stderr)
            return 1
        print(f"research-companion: scanning citations and references of {len(papers)} paper(s)...",
              file=sys.stderr)
        results = expand_from_existing(
            limit=args.limit,
            min_citations=args.min_citations,
        )
        mode_label = "citation expansion"
    else:
        if not args.topic:
            print("research-companion: provide a topic to search, or use --expand to scan "
                  "citations of existing papers.", file=sys.stderr)
            return 1
        topic = " ".join(args.topic)
        print(f'research-companion: searching Semantic Scholar for "{topic}"...',
              file=sys.stderr)
        results = search_topic(
            topic,
            limit=args.limit,
            year_min=args.year_min,
            year_max=args.year_max,
        )
        mode_label = "topic search"

    if not results:
        print(f"research-companion: no new papers found via {mode_label}.")
        return 0

    # --- JSON output --------------------------------------------------------
    if args.json:
        print(json.dumps([p.to_dict() for p in results], indent=2, ensure_ascii=False))
        if args.add:
            # Still add even in JSON mode.
            _auto_add_discovered(results, add_paper, FetchError)
        return 0

    # --- pretty print -------------------------------------------------------
    print(f"\nresearch-companion: {len(results)} paper(s) discovered via {mode_label}\n")
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
        print(f"\nresearch-companion: added {added}/{len(results)}, "
              f"{failed} failed. Run `research-companion build` to extract.")
    else:
        print(f"\nTo add all: research-companion discover {'--expand' if args.expand else chr(34) + ' '.join(args.topic) + chr(34)} --add")
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


def _run_uvicorn_in_thread(app, port: int) -> None:
    """Start uvicorn in a daemon background thread."""
    from research_companion.dashboard.server import _run_uvicorn_in_thread as _real
    _real(app, port)


async def _run_with_state(agents, ctx, state: dict) -> dict:
    """Run agents while tracking their status in *state* via bus events."""
    import asyncio
    import contextlib

    from research_companion.agents.events import AgentDone, AgentError, AgentStarted
    from research_companion.agents.orchestrator import run_agents

    q = ctx.bus.subscribe()

    async def _tracker():
        while True:
            event = await q.get()
            if isinstance(event, AgentStarted):
                state["lanes"][event.agent] = "running"
            elif isinstance(event, AgentDone):
                state["lanes"][event.agent] = "done"
            elif isinstance(event, AgentError):
                state["lanes"][event.agent] = "FAILED"

    tracker = asyncio.create_task(_tracker())
    try:
        results = await run_agents(agents, ctx)
    finally:
        tracker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tracker
        ctx.bus.unsubscribe(q)
        state["done"] = True

    return results


def _readiness_line(readiness: dict | None) -> str:
    """Format the submission-readiness verdict + top items for readable review output."""
    if not readiness:
        return ""
    label = {"not_ready": "NOT READY", "revise": "REVISE", "ready": "READY"}.get(
        readiness.get("verdict", "revise"), "REVISE")
    lines = [f"\nSubmission readiness: {label} — {readiness.get('summary', '')}"]
    for b in (readiness.get("blockers") or [])[:3]:
        lines.append(f"  ! [{b.get('lane', '')}] {b.get('title', '')}")
    shown = max(0, 3 - len(readiness.get("blockers") or []))
    for w in (readiness.get("warnings") or [])[:shown]:
        lines.append(f"  - [{w.get('lane', '')}] {w.get('title', '')}")
    return "\n".join(lines)


def _cmd_review(args: argparse.Namespace) -> int:
    import asyncio
    import contextlib
    import threading

    from research_companion.agents.base import AgentContext
    from research_companion.agents.benchmark import BenchmarkAgent
    from research_companion.agents.bus import Bus
    from research_companion.agents.citation import CitationAgent
    from research_companion.agents.citation_polarity import CitationPolarityAgent
    from research_companion.agents.compliance import ComplianceAgent
    from research_companion.agents.confidence import ConfidenceAgent
    from research_companion.agents.ethics import EthicsAgent
    from research_companion.agents.events import EventLog
    from research_companion.agents.ingest import IngestAgent
    from research_companion.agents.novelty import NoveltyAgent
    from research_companion.agents.orchestrator import run_agents
    from research_companion.agents.overlap import OverlapAgent
    from research_companion.agents.priorart import PriorArtAgent
    from research_companion.agents.reproducibility import ReproducibilityAgent
    from research_companion.agents.severity import SeverityAgent
    from research_companion.agents.statsoundness import StatSoundnessAgent
    from research_companion.agents.taxonomy import TaxonomyAgent
    from research_companion.agents.venuefit import VenueFitAgent
    from research_companion.store import _id_to_dirname, papergraph_dir

    runs_dir = papergraph_dir() / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    # Critical 1: use _id_to_dirname to handle DOI ids that contain '/' chars,
    # and time_ns() to avoid same-second collisions.
    log_path = runs_dir / f"{_id_to_dirname(args.paper_id)}-{time.time_ns()}.jsonl"

    agents = [IngestAgent(), CitationAgent(), PriorArtAgent(),
              StatSoundnessAgent(), ReproducibilityAgent(), EthicsAgent(), OverlapAgent()]
    if not args.fast:
        agents += [NoveltyAgent(), CitationPolarityAgent(), ConfidenceAgent(), BenchmarkAgent(),
                   SeverityAgent(), TaxonomyAgent()]
    if getattr(args, "venue", None):
        agents.append(VenueFitAgent())
        agents.append(ComplianceAgent())
    ctx = AgentContext(paper_id=args.paper_id, bus=Bus(log=EventLog(log_path)),
                       data=dict(REVIEW_CONTEXT_OVERRIDES))
    if getattr(args, "venue", None):
        ctx.data["_venue"] = args.venue

    conns = _parse_connectors_arg(getattr(args, "connectors", None))
    if conns is not None:
        from research_companion.discover import search_topic_with_fallback
        from research_companion.refcheck.retrieval import default_lookup as _default_lookup

        ctx.data["_lookup"] = _default_lookup(connectors=conns)
        ctx.data["_search"] = lambda q: search_topic_with_fallback(q, limit=15, connectors=conns)

    if getattr(args, "serve", False):
        try:
            from research_companion.dashboard.server import create_app
        except ImportError:
            print(
                "research-companion: dashboard requires fastapi and uvicorn. "
                "Install with: pip install fastapi uvicorn",
                file=sys.stderr,
            )
            return 1

        port = getattr(args, "port", 8501)
        state: dict = {"lanes": {}, "done": False}
        app = create_app(ctx.bus, state)

        injected_runner = ctx.data.get("_server_runner")
        runner = injected_runner or _run_uvicorn_in_thread
        runner(app, port)

        print(f"Dashboard: http://127.0.0.1:{port}")
        results = asyncio.run(_run_with_state(agents, ctx, state))

        # Critical 2: when using the real uvicorn server (not an injected test
        # runner), block so the dashboard remains accessible after agents finish.
        if injected_runner is None:
            print("Dashboard still running - press Ctrl+C to stop.")
            with contextlib.suppress(KeyboardInterrupt):
                threading.Event().wait()
    else:
        results = asyncio.run(run_agents(agents, ctx))

    # Rebuild and save the graph so the lab reflects any new citation-polarity
    # (or other) enrichment produced by this review run. Best-effort: never
    # fail the review over a graph-refresh error. Skipped in --fast mode:
    # the polarity agent (and other enrichment agents) don't run there, so
    # there's nothing new for a rebuild to materialize.
    if not args.fast:
        try:
            from research_companion.graph import build_graph, save_graph
            save_graph(build_graph())
        except Exception:
            pass

    # Always persist the review report to the store (regardless of --report flag)
    # so the suggestions engine can read it deterministically.
    _rep = None
    try:
        from research_companion.report import build_report_json
        from research_companion.store import PaperMetadata, save_review_report

        _meta = PaperMetadata.load(args.paper_id)
        _rep = build_report_json(args.paper_id, _meta.title if _meta else "", results)
        save_review_report(args.paper_id, _rep)
    except Exception:  # noqa: BLE001
        pass  # Non-fatal: don't break review output if persistence fails

    # Journey: log review_run event
    try:
        from research_companion.journey import log_event
        lanes_ok = {name: r.ok for name, r in results.items()}
        log_event("review_run", {"paper_id": args.paper_id, "lanes_ok": lanes_ok})
    except Exception:  # noqa: BLE001
        pass

    if args.report:
        from research_companion.report import build_report_json, render_report_html
        from research_companion.store import PaperMetadata

        meta = PaperMetadata.load(args.paper_id)
        rep = build_report_json(args.paper_id, meta.title if meta else "", results)
        out_dir = Path(args.report)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / "report.html").write_text(render_report_html(rep), encoding="utf-8")
        if not args.json:
            print(f"\nReport: {out_dir / 'report.html'}")
            print(f"        {out_dir / 'report.json'}")

    if args.json:
        payload = {
            "paper_id": args.paper_id,
            "agents": {name: {"ok": r.ok, "data": r.data, "error": r.error}
                       for name, r in results.items()},
        }
        readiness = (_rep or {}).get("readiness")
        if readiness:
            payload["readiness"] = readiness
        if args.report:
            payload["report_dir"] = str(out_dir)
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
    line = _readiness_line((_rep or {}).get("readiness"))
    if line:
        print(line)
    return 0 if ok else 1


REBUTTAL_CONTEXT_OVERRIDES: dict = {}


# Test seam for the align command: tests monkeypatch this to inject a fake LLM.
ALIGN_CONTEXT_OVERRIDES: dict = {}


# Test seam for the ask command: tests monkeypatch this to inject a fake LLM.
# Key "llm": callable(prompt: str) -> str
QA_CONTEXT_OVERRIDES: dict = {}


# Test seam for the compare command: tests monkeypatch this to inject a fake LLM.
# Key "llm": callable(prompt: str) -> str
COMPARE_CONTEXT_OVERRIDES: dict = {}


def _resolve_llm_for_align(args: argparse.Namespace) -> object:
    """Return an LLM callable for the align command.

    In tests, ALIGN_CONTEXT_OVERRIDES["_llm"] is injected.
    In production, wires the real provider (same pattern as novelty/rebuttal agents).
    """
    injected = ALIGN_CONTEXT_OVERRIDES.get("_llm")
    if injected is not None:
        return injected

    # Real provider wiring (lazy import, mirrors agents/novelty.py::_default_llm)
    import os

    from research_companion.extract import _call_anthropic, _call_openai, resolve_model

    provider = getattr(args, "provider", None) or os.environ.get(
        "RESEARCH_COMPANION_PROVIDER", "anthropic"
    )
    model = getattr(args, "model", None) or os.environ.get("RESEARCH_COMPANION_MODEL")
    resolved_model = resolve_model(provider, model)
    call = _call_openai if provider == "openai" else _call_anthropic

    def _real_llm(prompt: str) -> str:
        text, _usage = call(prompt, model=resolved_model)
        return text

    return _real_llm


def _cmd_compare(args: argparse.Namespace) -> int:
    """Compare two papers: entity overlap and optional narrative."""
    from research_companion.compare import compare_papers

    paper_a = args.paper_a
    paper_b = args.paper_b

    # Resolve LLM: use injected callable from COMPARE_CONTEXT_OVERRIDES if present
    llm = None
    if not getattr(args, "no_summary", False):
        llm = COMPARE_CONTEXT_OVERRIDES.get("llm")
        if llm is None:
            # Wire real provider (mirrors _resolve_llm_for_align pattern)
            import os

            from research_companion.extract import _call_anthropic, _call_openai, resolve_model

            provider = getattr(args, "provider", None) or os.environ.get(
                "RESEARCH_COMPANION_PROVIDER", "anthropic"
            )
            model = getattr(args, "model", None) or os.environ.get("RESEARCH_COMPANION_MODEL")
            resolved_model = resolve_model(provider, model)

            def _real_llm(prompt: str) -> str:
                if provider == "openai":
                    # Narrative summary is prose: JSON mode would mangle it.
                    text, _usage = _call_openai(prompt, model=resolved_model, json_mode=False)
                else:
                    text, _usage = _call_anthropic(prompt, model=resolved_model)
                return text

            llm = _real_llm

    try:
        result = compare_papers(paper_a, paper_b, llm=llm)
    except ValueError as e:
        print(f"research-companion: compare failed: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # Human-readable output: titles, three columns, results table, summary
    print()
    print(f"Paper A: {result['paper_a']['title']}")
    print(f"Paper B: {result['paper_b']['title']}")
    print()

    # Three-column summary
    def _count_section(entities: dict) -> int:
        return len(entities.get("concepts", [])) + len(entities.get("methods", [])) + len(entities.get("datasets", []))

    shared_count = _count_section(result["shared"])
    only_a_count = _count_section(result["only_a"])
    only_b_count = _count_section(result["only_b"])

    print(f"Shared ({shared_count}):")
    for ent in result["shared"]["concepts"]:
        print(f"  • {ent} (concept)")
    for ent in result["shared"]["methods"]:
        print(f"  • {ent} (method)")
    for ent in result["shared"]["datasets"]:
        print(f"  • {ent} (dataset)")
    if shared_count == 0:
        print("  (none)")

    print()
    print(f"Only in Paper A ({only_a_count}):")
    for ent in result["only_a"]["concepts"]:
        print(f"  • {ent} (concept)")
    for ent in result["only_a"]["methods"]:
        print(f"  • {ent} (method)")
    for ent in result["only_a"]["datasets"]:
        print(f"  • {ent} (dataset)")
    if only_a_count == 0:
        print("  (none)")

    print()
    print(f"Only in Paper B ({only_b_count}):")
    for ent in result["only_b"]["concepts"]:
        print(f"  • {ent} (concept)")
    for ent in result["only_b"]["methods"]:
        print(f"  • {ent} (method)")
    for ent in result["only_b"]["datasets"]:
        print(f"  • {ent} (dataset)")
    if only_b_count == 0:
        print("  (none)")

    # Results table
    if result["results"]:
        print()
        print("Results:")
        print(f"  {'Metric':<15} {'Dataset':<20} {'Value A':<15} {'Value B':<15}")
        print(f"  {'-'*15} {'-'*20} {'-'*15} {'-'*15}")
        for row in result["results"]:
            val_a = row["value_a"] if row["value_a"] is not None else "-"
            val_b = row["value_b"] if row["value_b"] is not None else "-"
            print(f"  {row['metric']:<15} {row['dataset']:<20} {val_a:<15} {val_b:<15}")

    # Summary
    if result["summary"]:
        print()
        print("Summary:")
        print(f"  {result['summary']}")

    print()
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    """Answer a research question using BM25-retrieved paper sections."""
    import dataclasses

    from research_companion.qa import QAAnswer, answer

    question = args.question
    if not question:
        print("research-companion: no question given. Usage: research-companion ask '<question>'",
              file=sys.stderr)
        return 1

    # Resolve LLM: use injected callable from QA_CONTEXT_OVERRIDES if present
    llm = QA_CONTEXT_OVERRIDES.get("llm")

    try:
        result: QAAnswer = answer(
            question,
            llm=llm,
            k_sections=args.k,
            section_id=getattr(args, "section", None),
        )
    except Exception as e:
        print(f"research-companion: ask failed: {e}", file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "answer": result.answer,
            "sources": [dataclasses.asdict(s) for s in result.sources],
            "cited": [dataclasses.asdict(s) for s in result.cited],
            "unverified_quotes": result.unverified_quotes,
            "input_chars": result.input_chars,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    # Human output
    print()
    print(result.answer)
    print()
    if result.sources:
        print("Sources:")
        cited_ids = {(s.paper_id, s.section_id) for s in result.cited}
        for i, src in enumerate(result.sources, 1):
            mark = " *" if (src.paper_id, src.section_id) in cited_ids else ""
            print(f"  [S{i}]{mark} {src.paper_title} §{src.section_title}")
    if result.unverified_quotes:
        print(f"\nWARNING: {len(result.unverified_quotes)} quote(s) could not be verified "
              "against source text.")
    print()
    return 0


def _cmd_set_draft(args: argparse.Namespace) -> int:
    from research_companion.store import (
        PaperMetadata,
        get_draft_paper_id,
        set_draft_paper_id,
    )

    # --show: print current draft (or message if none)
    if getattr(args, "show", False):
        current = get_draft_paper_id()
        if current:
            print(f"research-companion: draft paper: {current}")
        else:
            print("research-companion: no draft set")
        return 0

    # --clear: remove configured draft
    if getattr(args, "clear", False):
        set_draft_paper_id(None)
        print("research-companion: draft cleared")
        return 0

    # Positional paper_id required
    paper_id = getattr(args, "paper_id", None)
    if not paper_id:
        print("research-companion: paper_id required (or use --clear / --show)", file=sys.stderr)
        return 1

    meta = PaperMetadata.load(paper_id)
    if meta is None:
        print(f"research-companion: no such paper: {paper_id}", file=sys.stderr)
        return 1

    set_draft_paper_id(paper_id)
    print(f"research-companion: draft set to {paper_id}  \"{meta.title}\"")

    # Journey: record new draft version and run deterministic suggestion matching
    try:
        import contextlib

        from research_companion.journey import match_open_suggestions, record_draft_version
        ver = record_draft_version(paper_id)
        if ver is not None:
            with contextlib.suppress(Exception):
                match_open_suggestions(paper_id, llm=None)
    except Exception:  # noqa: BLE001
        pass

    return 0


def _cmd_align(args: argparse.Namespace) -> int:
    from research_companion.alignment import AlignmentError, align_papers
    from research_companion.store import get_draft_paper_id

    candidate_id: str = args.paper_id
    draft_id: str | None = getattr(args, "against", None) or get_draft_paper_id()

    if not draft_id:
        print(
            "research-companion: no draft configured. Use --against <paper_id> or "
            "run `research-companion set-draft <paper_id>` first.",
            file=sys.stderr,
        )
        return 1

    llm = _resolve_llm_for_align(args)
    force = getattr(args, "force", False)
    # When using --against (not the configured draft), persist=None triggers
    # the "different draft" branch (no write) unless it happens to match.
    persist = None

    try:
        payload = align_papers(
            draft_id,
            candidate_id,
            llm=llm,
            force=force,
            persist=persist,
        )
    except (ValueError, AlignmentError) as exc:
        print(f"research-companion: align failed: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    # Human-readable output
    verdict = payload["verdict"]
    score = payload["score"]
    band = payload["band"]
    print(f"\nAlignment: {candidate_id}")
    print(f"  vs draft: {draft_id}")
    print(f"  verdict:  {verdict.upper()}  score={score:.3f} ±{band:.3f}")
    print()
    for sec in payload["sections"]:
        n_ev = len(sec["evidence"])
        n_verified = sum(1 for e in sec["evidence"] if e.get("verified"))
        ev_str = f"  [{n_verified}/{n_ev} quotes verified]" if n_ev else ""
        print(f"  {sec['section_id']}  [{sec['relation']}]  {sec['section_title']}{ev_str}")
    print()
    return 0


def _cmd_rebuttal(args: argparse.Namespace) -> int:
    import asyncio

    from research_companion.agents.base import AgentContext
    from research_companion.agents.bus import Bus
    from research_companion.agents.ingest import IngestAgent
    from research_companion.agents.orchestrator import run_agents
    from research_companion.agents.rebuttal import RebuttalAgent
    from research_companion.rebuttal.models import concerns_from_json, concerns_to_json
    from research_companion.rebuttal.segment import segment_reviews

    if not args.reviews and not args.segments:
        print("research-companion: provide --reviews FILE or --segments FILE.", file=sys.stderr)
        return 1

    reviews_text = ""
    if args.reviews:
        rpath = Path(args.reviews)
        if not rpath.is_file():
            print(f"research-companion: reviews file not found: {rpath}", file=sys.stderr)
            return 1
        reviews_text = rpath.read_text(encoding="utf-8")

    if args.emit_segments:
        concerns = segment_reviews(reviews_text)
        Path(args.emit_segments).write_text(concerns_to_json(concerns), encoding="utf-8")
        print(f"research-companion: wrote {len(concerns)} segment(s) to {args.emit_segments}. "
              "Edit, then rerun with --segments.")
        return 0

    ctx_data = dict(REBUTTAL_CONTEXT_OVERRIDES)
    ctx_data["_reviews_text"] = reviews_text
    ctx_data["_tone"] = args.tone
    if args.segments:
        seg_path = Path(args.segments)
        if not seg_path.is_file():
            print(f"research-companion: segments file not found: {seg_path}", file=sys.stderr)
            return 1
        try:
            ctx_data["_concerns"] = concerns_from_json(seg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError) as exc:
            print(f"research-companion: invalid segments file: {exc}", file=sys.stderr)
            return 1

    ctx = AgentContext(paper_id=args.paper_id, bus=Bus(), data=ctx_data)
    results = asyncio.run(run_agents([IngestAgent(), RebuttalAgent()], ctx))
    reb = results["rebuttal"]
    if not reb.ok:
        print(f"research-companion: rebuttal failed: {reb.error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(reb.data, indent=2, ensure_ascii=False))
        return 0

    kinds = {c["concern_id"]: c["kind"] for c in reb.data["concerns"]}
    for d in reb.data["drafts"]:
        if d.get("evidence_status") == "no_quotes":
            status = "[NOTE reply cites no paper quotes]"
        elif d["verified"]:
            status = "[OK all quotes verified]"
        else:
            status = f"[CHECK {len(d['unverified_spans'])} unverified span(s)]"
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
    from research_companion.prompts import extraction_prompt_sha256
    from research_companion.refcheck.parse import references_from_extraction
    from research_companion.refcheck.retrieval import default_lookup
    from research_companion.refcheck.validate import validate_bibliography
    from research_companion.store import load_extraction

    ext = load_extraction(args.paper_id, prompt_sha=extraction_prompt_sha256())
    if ext is None:
        print(
            f"research-companion: no extraction for {args.paper_id}. Run `research-companion build` first.",
            file=sys.stderr,
        )
        return 1

    refs = references_from_extraction(ext)
    conns = _parse_connectors_arg(getattr(args, "connectors", None))
    lookup = default_lookup(connectors=conns) if conns is not None else default_lookup()
    report = validate_bibliography(refs, lookup)
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
        print("research-companion: no references found in this paper's extraction.")
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


def _cmd_check_stats(args: argparse.Namespace) -> int:
    from research_companion.statcheck import check_stats
    from research_companion.store import load_text

    text = load_text(args.paper_id)
    if text is None:
        print(
            f"research-companion: no text for {args.paper_id}. Add or ingest the paper first.",
            file=sys.stderr,
        )
        return 1

    report = check_stats(text)
    if args.json:
        report["paper_id"] = args.paper_id
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    findings = report["findings"]
    if not findings:
        print("research-companion: no parseable statistics found (nothing to check).")
        return 0

    symbol = {"consistent": "OK ", "inconsistent": "?? ",
              "decision_inconsistent": "XX ", "impossible_mean": "XX "}
    for f in findings:
        sym = symbol.get(f["status"], "?? ")
        if f.get("test_type") == "mean":
            print(f"{sym}[{f['status']}] mean={f['mean']} N={f['n']}")
        else:
            print(f"{sym}[{f['status']}] {f['raw']}  (recomputed p~{f['recomputed_p']})")
    print(f"\nSummary: {report['summary']['text']}")
    return 0


def _cmd_export_bib(args: argparse.Namespace) -> int:
    from research_companion.interop import papers_to_bibtex, papers_to_ris
    from research_companion.store import list_papers

    papers = list_papers()
    if not papers:
        print("research-companion: library is empty; nothing to export.")
        return 0
    content = papers_to_ris(papers) if args.format == "ris" else papers_to_bibtex(papers)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(content, encoding="utf-8")
        print(f"Wrote {len(papers)} entries to {args.output} ({args.format}).")
    else:
        print(content, end="")
    return 0


def _cmd_import_bib(args: argparse.Namespace) -> int:
    from pathlib import Path

    from research_companion.interop import parse_bibtex
    from research_companion.store import PaperMetadata, paper_dir

    path = Path(args.file)
    if not path.exists():
        print(f"research-companion: no such file: {args.file}", file=sys.stderr)
        return 1
    entries = parse_bibtex(path.read_text(encoding="utf-8", errors="ignore"))
    if not entries:
        print("research-companion: no BibTeX entries found in that file.")
        return 0

    added, skipped = 0, 0
    for e in entries:
        pid = f"bibtex:{e['key']}"
        if (paper_dir(pid) / "metadata.json").exists():
            skipped += 1
            continue
        source = e.get("url") or (f"https://doi.org/{e['doi']}" if e.get("doi") else "")
        PaperMetadata(
            paper_id=pid,
            title=e.get("title", "") or e["key"],
            authors=e.get("authors", []) or [],
            year=e.get("year"),
            source_url=source,
            parse_source="bibtex",
        ).save()
        added += 1
    print(f"Imported {added} entries ({skipped} already present) as metadata-only "
          f"library papers.")
    return 0


def _cmd_check_overlap(args: argparse.Namespace) -> int:
    from research_companion.overlap import (
        check_external,
        get_external_provider,
        near_duplicate_passages,
    )
    from research_companion.store import list_papers, load_text

    target = load_text(args.paper_id)
    if target is None:
        print(
            f"research-companion: no text for {args.paper_id}. Add or ingest the paper first.",
            file=sys.stderr,
        )
        return 1

    corpus = [
        (p.paper_id, load_text(p.paper_id) or "")
        for p in list_papers()
        if p.paper_id != args.paper_id
    ]
    result = near_duplicate_passages(target, corpus)

    from research_companion import embed, semoverlap, settings

    s = settings.get_settings()
    want_semantic = args.semantic or bool(s.get("semantic_overlap"))
    if want_semantic:
        model = s.get("embed_model") or embed.DEFAULT_EMBED_MODEL
        allow_remote = args.allow_remote or bool(
            s.get("semantic_overlap_allow_remote"))
        resolved = embed.resolve_embedder(model=model, allow_remote=allow_remote)
        if resolved is None:
            if args.semantic:  # explicit request -> say why it was skipped
                print("research-companion: semantic overlap skipped — no embedding "
                      "backend. Install the local extra (pip install "
                      "'research-companion[semantic]') or pass --allow-remote with "
                      "HF_TOKEN set.", file=sys.stderr)
        else:
            embed_fn, _label = resolved
            raw_threshold = s.get("semantic_overlap_threshold")
            threshold = float(raw_threshold if raw_threshold is not None
                              else semoverlap.DEFAULT_SEMANTIC_THRESHOLD)
            try:
                semantic = semoverlap.collect_semantic_findings(
                    args.paper_id,
                    [pid for pid, _ in corpus],
                    embed_fn=embed_fn, embed_model=model,
                    threshold=threshold)
                result = semoverlap.merge_overlap_results(result, semantic)
            except Exception as exc:
                print(f"research-companion: semantic overlap failed ({exc}); "
                      "showing lexical results only.", file=sys.stderr)

    external = None
    if args.external:
        # Passing --external is the explicit consent to send text to the provider.
        external = check_external(target, provider=get_external_provider(), consent=True)

    if args.json:
        payload = {"paper_id": args.paper_id, **result}
        if external is not None:
            payload["external"] = external
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    for f in result["findings"]:
        pct = round(float(f["score"]) * 100)
        label = "paraphrase" if f.get("method") == "semantic" else "overlap"
        print(f"XX [{pct}% {label}] with {f['matched_paper_id']}: "
              f"\"{f['snippet'][:120]}...\"")
    print(f"\nSummary: {result['summary']['text']}")

    if args.external:
        if external and external.get("enabled"):
            print(f"\nExternal ({external['provider']}): {len(external['matches'])} match(es).")
            for m in external["matches"]:
                print(f"  - {m}")
        else:
            reason = external.get("reason", "disabled") if external else "disabled"
            print(f"\nExternal check not run: {reason}. Register a provider with "
                  "research_companion.overlap.register_external_provider(...).")
    return 0


def _cmd_check_compliance(args: argparse.Namespace) -> int:
    from research_companion.compliance import check_compliance
    from research_companion.prompts import extraction_prompt_sha256
    from research_companion.refcheck.parse import references_from_extraction
    from research_companion.sections import Section, build_section_tree
    from research_companion.store import (
        PaperMetadata,
        load_extraction,
        load_sections,
        load_text,
        pdf_page_count,
    )
    from research_companion.venues import get_venue

    venue = get_venue(args.venue)
    if venue is None:
        print(f"research-companion: unknown venue {args.venue!r}. "
              "See `research-companion` venue list for valid slugs.", file=sys.stderr)
        return 1

    fulltext = load_text(args.paper_id) or ""

    # store.load_sections() returns a persisted payload dict
    # ({"sections": [...plain dicts...], ...}) or None (missing/stale cache)
    # — never a bare list of Section objects. check_compliance needs real
    # Section objects (it reads `.title`), so convert the payload's plain
    # dicts into Section instances; when there's no cached payload at all,
    # build fresh from the fulltext instead.
    raw = load_sections(args.paper_id)
    sections: list[Section] | None = None
    if isinstance(raw, dict):
        try:
            sections = [Section(**s) for s in raw.get("sections", [])]
        except TypeError:
            sections = None
    if not sections and fulltext:
        try:
            sections = build_section_tree(fulltext)
        except Exception:
            sections = None

    meta = PaperMetadata.load(args.paper_id)
    abstract = meta.abstract if meta else ""
    ext = load_extraction(args.paper_id, prompt_sha=extraction_prompt_sha256())
    references = references_from_extraction(ext) if ext else None
    page_count = pdf_page_count(args.paper_id)

    result = check_compliance(
        venue, fulltext=fulltext, sections=sections, abstract=abstract,
        references=references, page_count=page_count)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    checks = result["checks"]
    desk_rejects = [c for c in checks if c["status"] == "finding" and c["severity"] == "desk_reject"]
    warnings = [c for c in checks if c["status"] == "finding" and c["severity"] == "warning"]
    skipped = [c for c in checks if c["status"] == "skipped"]

    if desk_rejects:
        print("Desk-reject risks:")
        for c in desk_rejects:
            print(f"  XX [{c['check']}] {c['message']}")
            if c.get("detail"):
                print(f"     {c['detail']}")
    if warnings:
        print("Warnings:")
        for c in warnings:
            print(f"  ?? [{c['check']}] {c['message']}")
            if c.get("detail"):
                print(f"     {c['detail']}")
    if skipped:
        print("Skipped:")
        for c in skipped:
            print(f"  -- [{c['check']}] {c['message']}")
    if not desk_rejects and not warnings:
        print("research-companion: no compliance issues found.")

    print(f"\n{result['disclaimer']}")
    return 0


def _cmd_mcp_serve(args: argparse.Namespace) -> int:
    from research_companion.mcp_server import serve

    try:
        serve(transport=args.transport)
    except ImportError as exc:
        print(f"research-companion: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 0
    return 0


def _cmd_cite_tex(args: argparse.Namespace) -> int:
    from pathlib import Path

    from research_companion.interop import extract_cite_keys, resolve_tex_citations

    tex_path = Path(args.tex_file)
    if not tex_path.exists():
        print(f"research-companion: no such file: {args.tex_file}", file=sys.stderr)
        return 1
    tex = tex_path.read_text(encoding="utf-8", errors="ignore")

    if not args.bib:
        keys = extract_cite_keys(tex)
        if args.json:
            print(json.dumps({"cited_keys": keys}, indent=2))
        else:
            print(f"{len(keys)} distinct cite keys:")
            for k in keys:
                print(f"  {k}")
        return 0

    bib_path = Path(args.bib)
    if not bib_path.exists():
        print(f"research-companion: no such file: {args.bib}", file=sys.stderr)
        return 1
    res = resolve_tex_citations(tex, bib_path.read_text(encoding="utf-8", errors="ignore"))
    if args.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"Coverage: {res['coverage']}")
    if res["missing"]:
        print("\nCited but missing from the .bib:")
        for k in res["missing"]:
            print(f"  {k}")
    if res["unused"]:
        print(f"\n{len(res['unused'])} bib entries are never cited.")
    return 0


# Test seam for gaps command: tests monkeypatch this to inject LLM.
# Key "llm": callable(prompt: str) -> str
GAPS_CONTEXT_OVERRIDES: dict = {}


def _cmd_gaps(args: argparse.Namespace) -> int:
    """Show research gaps extracted from corpus papers."""
    from research_companion.gaps import extract_all_gaps, gaps_overview, resolve_gaps

    do_refresh = getattr(args, "refresh", False)

    if do_refresh:
        # Resolve LLM
        llm = GAPS_CONTEXT_OVERRIDES.get("llm")
        if llm is None:
            import os

            from research_companion.extract import _call_anthropic, _call_openai, resolve_model

            provider = os.environ.get("RESEARCH_COMPANION_PROVIDER", "anthropic")
            model = os.environ.get("RESEARCH_COMPANION_MODEL")
            resolved_model = resolve_model(provider, model)

            def _real_llm(prompt: str) -> str:
                if provider == "openai":
                    text, _usage = _call_openai(prompt, model=resolved_model, json_mode=True)
                else:
                    text, _usage = _call_anthropic(prompt, model=resolved_model)
                return text

            llm = _real_llm

        print("research-companion: extracting gaps...")
        extract_all_gaps(llm=llm)
        print("research-companion: resolving gaps...")
        resolve_gaps(llm=llm)

    overview = gaps_overview()

    if getattr(args, "json", False):
        print(json.dumps(overview, indent=2, ensure_ascii=False))
        return 0

    papers = overview.get("papers", [])
    draft_addresses = set(overview.get("draft_addresses", []))
    stale = overview.get("stale", True)

    if stale:
        print("research-companion: gaps data is stale. Run `research-companion gaps --refresh` to update.")

    if not papers:
        print("research-companion: no gaps found. Run `research-companion gaps --refresh` to extract.")
        return 0

    total_gaps = sum(len(p.get("gaps", [])) for p in papers)
    print(f"\nresearch-companion: {total_gaps} gap(s) across {len(papers)} paper(s)\n")

    _STATUS_GLYPH = {
        "addressed": "[+]",
        "partially": "[~]",
        "open": "[ ]",
    }

    for paper in papers:
        title = paper.get("title", paper.get("paper_id", "?"))
        year = paper.get("year") or "?"
        print(f"  {title} ({year})")
        for gap in paper.get("gaps", []):
            gid = gap["gap_id"]
            stmt = gap.get("statement", "")[:80]
            kind = gap.get("kind", "?")
            res = gap.get("resolution", {})
            status = res.get("status", "open")
            glyph = _STATUS_GLYPH.get(status, "[ ]")
            draft_mark = " [DRAFT]" if gid in draft_addresses else ""
            print(f"    {glyph} [{kind}] {stmt}{draft_mark}")
        print()

    return 0


def _cmd_timeline(args: argparse.Namespace) -> int:
    """Print the research timeline (temporal overview)."""
    from research_companion.temporal import build_timeline

    timeline = build_timeline()

    if getattr(args, "json", False):
        print(json.dumps(timeline, indent=2, ensure_ascii=False))
        return 0

    years = timeline.get("years", [])
    papers_per_year = timeline.get("papers_per_year", [])
    tracks = timeline.get("tracks", [])

    if not years:
        print("research-companion: no temporal data. Add papers with years first.")
        return 0

    print(f"\nresearch-companion: timeline  {min(years)}-{max(years)}\n")
    print(f"  {'Year':<6} {'Papers':>6}")
    print(f"  {'-'*6} {'-'*6}")
    ppy_map = {p["year"]: p["count"] for p in papers_per_year}
    for yr in years:
        print(f"  {yr:<6} {ppy_map.get(yr, 0):>6}")

    if tracks:
        print(f"\n  {len(tracks)} track(s):")
        for t in tracks[:20]:
            apps = len(t.get("appearances", []))
            print(f"    [{t['kind']}] {t['label']}  first:{t['first_seen']}  appearances:{apps}")
        if len(tracks) > 20:
            print(f"    ... ({len(tracks) - 20} more)")

    truncated = timeline.get("truncated_tracks", 0)
    if truncated:
        print(f"\n  (truncated {truncated} additional track(s))")
    print()
    return 0


# Test seam: tests monkeypatch this to inject ingest_folder for CLI tests.
LAB_INGEST_OVERRIDES: dict = {}


def _cmd_lab_ingest(args: argparse.Namespace) -> int:
    import asyncio as _asyncio

    from research_companion.agents.bus import Bus
    from research_companion.agents.events import EventLog
    from research_companion.store import papergraph_dir

    folder = Path(args.folder)
    log_path = papergraph_dir() / "lab_events.jsonl"
    bus = Bus(log=EventLog(log_path))

    # Allow tests to inject ingest_folder via LAB_INGEST_OVERRIDES
    ingest_fn = LAB_INGEST_OVERRIDES.get("ingest_folder")
    if ingest_fn is None:
        from research_companion.lab import ingest_folder as _real_ingest
        ingest_fn = _real_ingest

    try:
        result = _asyncio.run(
            ingest_fn(
                folder,
                bus=bus,
                provider=getattr(args, "provider", "anthropic"),
                model=getattr(args, "model", None),
                align=not getattr(args, "no_align", False),
            )
        )
    except ValueError as e:
        print(f"research-companion lab ingest: {e}", file=sys.stderr)
        return 1

    # Summary table
    print(f"\nresearch-companion lab ingest: {folder}")
    print(f"  added:   {len(result.added)}")
    print(f"  skipped: {len(result.skipped)}")
    print(f"  failed:  {len(result.failed)}")
    if result.failed:
        print("\nFailures:")
        for f_entry in result.failed:
            stage = f_entry.get("stage", "?")
            error = f_entry.get("error", "?")
            path_ = f_entry.get("path", "?")
            print(f"  [{stage}]  {path_}  -- {error}")
        return 2
    return 0


def _cmd_lab_serve(args: argparse.Namespace) -> int:
    """Start the Research Companion web server (REST + SSE)."""
    try:
        from research_companion.lab_api import serve_lab
    except ImportError:
        print(
            "research-companion: lab server requires fastapi and uvicorn. "
            "Install with: pip install 'research-companion[server]'",
            file=sys.stderr,
        )
        return 1

    port = getattr(args, "port", 8765)
    open_browser = not getattr(args, "no_open", False)

    try:
        serve_lab(port=port, open_browser=open_browser)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


def _cmd_lab_failures(args: argparse.Namespace) -> int:
    from research_companion.store import list_failures

    failures = list_failures()
    if not failures:
        print("research-companion lab failures: none")
        return 0

    print(f"research-companion lab failures: {len(failures)} recorded")
    for key, info in failures.items():
        stage = info.get("stage", "?")
        error = info.get("error", "?")
        at = info.get("at", "?")
        print(f"  [{stage}]  {key}  ({at})")
        print(f"           {error}")
    return 0


def _cmd_workspace(args: argparse.Namespace) -> int:
    from research_companion import workspaces

    if args.ws_cmd == "list":
        listing = workspaces.list_workspaces()
        active = listing["active"]
        print("research-companion workspaces:")
        for w in listing["workspaces"]:
            marker = "*" if w["id"] == active else " "
            arch = "  [archived]" if w.get("archived") else ""
            papers = w.get("stats", {}).get("papers", 0)
            print(f"  {marker} {w['id']:<24} {w['name']:<32} {papers} papers{arch}")
        return 0

    if args.ws_cmd == "create":
        try:
            rec = workspaces.create_workspace(args.name)
        except workspaces.WorkspaceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"created workspace: {rec['id']}  ({rec['name']})")
        return 0

    if args.ws_cmd == "use":
        target = args.workspace
        listing = workspaces.list_workspaces(with_stats=False)
        known = {w["id"] for w in listing["workspaces"]}
        ws_id = target if target in known else None
        if ws_id is None:
            try:
                candidate = workspaces.slugify(target)
            except workspaces.WorkspaceError:
                candidate = None
            if candidate in known:
                ws_id = candidate
        if ws_id is None:
            print(f"error: unknown workspace: {target!r}", file=sys.stderr)
            return 1
        try:
            workspaces.activate_workspace(ws_id)
        except workspaces.WorkspaceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"active workspace: {ws_id}")
        return 0

    return 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="research-companion",
        description="Knowledge graph + chat over a corpus of research papers.",
    )
    p.add_argument("--version", action="version", version=f"research-companion {__version__}")
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
    pe.add_argument("--output", default="./research-companion-export/",
                    help="Output directory (default: ./research-companion-export/)")
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
    prc.add_argument("paper_id", help="ID of a paper already built (see `research-companion list`)")
    prc.add_argument("--json", action="store_true", help="JSON output")
    prc.add_argument("--connectors", help="Comma-separated domain connectors: europepmc,pubmed,dblp")
    prc.set_defaults(func=_cmd_refcheck)

    pcs = sub.add_parser("check-stats",
                         help="Recompute reported p-values and check means (Statcheck + GRIM)")
    pcs.add_argument("paper_id", help="ID of a paper already added/ingested")
    pcs.add_argument("--json", action="store_true", help="JSON output")
    pcs.set_defaults(func=_cmd_check_stats)

    pco = sub.add_parser("check-overlap",
                         help="Flag passages that near-duplicate another paper in your library")
    pco.add_argument("paper_id", help="ID of a paper already added/ingested")
    pco.add_argument("--external", action="store_true",
                     help="Also run a registered external similarity provider (consent implied; "
                          "sends text off-machine — none is configured by default)")
    pco.add_argument("--json", action="store_true", help="JSON output")
    pco.add_argument("--semantic", action="store_true",
                     help="Also run the opt-in paraphrase (embedding) overlap pass "
                          "(or enable the semantic_overlap setting)")
    pco.add_argument("--allow-remote", action="store_true",
                     help="Consent to embed via the Hugging Face API when no local "
                          "backend is installed — sends draft AND library text "
                          "off-machine (requires HF_TOKEN)")
    pco.set_defaults(func=_cmd_check_overlap)

    pcc = sub.add_parser("check-compliance",
                         help="Check a paper against a venue's submission rules (desk-reject linter)")
    pcc.add_argument("paper_id", help="ID of a paper already added/ingested")
    pcc.add_argument("--venue", required=True, help="Target venue slug/name")
    pcc.add_argument("--json", action="store_true", help="JSON output")
    pcc.set_defaults(func=_cmd_check_compliance)

    peb = sub.add_parser("export-bib",
                         help="Export the library to BibTeX or RIS")
    peb.add_argument("--format", choices=["bibtex", "ris"], default="bibtex",
                     help="Bibliography format (default: bibtex)")
    peb.add_argument("-o", "--output", help="Write to this file (default: stdout)")
    peb.set_defaults(func=_cmd_export_bib)

    pib = sub.add_parser("import-bib",
                         help="Import a .bib file (e.g. a Zotero/Mendeley export) into the library")
    pib.add_argument("file", help="Path to a .bib file")
    pib.set_defaults(func=_cmd_import_bib)

    pct = sub.add_parser("cite-tex",
                         help="Read \\cite keys from a .tex draft; resolve them against a .bib")
    pct.add_argument("tex_file", help="Path to a .tex file")
    pct.add_argument("--bib", help="Path to a .bib file to resolve the cited keys against")
    pct.add_argument("--json", action="store_true", help="JSON output")
    pct.set_defaults(func=_cmd_cite_tex)

    pmcp = sub.add_parser("mcp",
                          help="MCP trust-layer server (expose verification tools to agents)")
    mcp_sub = pmcp.add_subparsers(dest="mcp_cmd", required=True)
    pmcp_serve = mcp_sub.add_parser("serve",
                                    help="Start the MCP server (deterministic, key-free tools)")
    pmcp_serve.add_argument("--transport", default="stdio", choices=["stdio", "sse"],
                            help="MCP transport (default: stdio)")
    pmcp_serve.set_defaults(func=_cmd_mcp_serve)

    prv = sub.add_parser("review",
                         help="Run the agent team over a paper (ingest, citations, prior art)")
    prv.add_argument("paper_id", help="ID of a paper already built (see `research-companion list`)")
    prv.add_argument("--json", action="store_true", help="JSON output")
    prv.add_argument("--fast", action="store_true",
                     help="Skip LLM lanes (novelty, confidence, benchmark)")
    prv.add_argument("--report", help="Write report.html + report.json to this directory")
    prv.add_argument("--venue",
                     help="Target venue slug/name for a scope/venue-fit check "
                          "(e.g. neurips, icml, acl). See docs for supported venues.")
    prv.add_argument("--serve", action="store_true",
                     help="Start a live dashboard while agents run")
    prv.add_argument("--port", type=int, default=8501,
                     help="Port for the dashboard (default: 8501)")
    prv.add_argument("--connectors", help="Comma-separated domain connectors: europepmc,pubmed,dblp")
    prv.set_defaults(func=_cmd_review)

    prb = sub.add_parser("rebuttal", help="Draft grounded replies to reviewer comments")
    prb.add_argument("paper_id", help="ID of a paper already built")
    prb.add_argument("--reviews", help="Path to a text file with the reviewer comments")
    prb.add_argument("--emit-segments", help="Segment reviews, write JSON here, and stop")
    prb.add_argument("--segments", help="Resume from an edited segments JSON file")
    prb.add_argument("--tone", choices=["deferential", "balanced", "firm"], default="balanced")
    prb.add_argument("--json", action="store_true", help="JSON output")
    prb.set_defaults(func=_cmd_rebuttal)

    psd = sub.add_parser("set-draft",
                         help="Designate a paper as the draft (the reference for alignment)")
    psd.add_argument("paper_id", nargs="?", help="Paper ID to set as draft")
    psd.add_argument("--clear", action="store_true", help="Clear the configured draft")
    psd.add_argument("--show", action="store_true", help="Print the currently configured draft")
    psd.set_defaults(func=_cmd_set_draft)

    pal = sub.add_parser("align",
                         help="Assess how a candidate paper relates to the draft paper")
    pal.add_argument("paper_id", help="Candidate paper ID to align against the draft")
    pal.add_argument("--against", metavar="PAPER_ID",
                     help="Draft paper ID (overrides configured draft)")
    pal.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    pal.add_argument("--model", default=None, help="Model override")
    pal.add_argument("--force", action="store_true", help="Re-run even if cached")
    pal.add_argument("--json", action="store_true", help="JSON output")
    pal.set_defaults(func=_cmd_align)

    pask = sub.add_parser("ask",
                          help="Answer a research question using BM25-retrieved paper sections")
    pask.add_argument("question", nargs="?", default="",
                      help="Question to answer (required)")
    pask.add_argument("-k", type=int, default=6,
                      help="Number of top sections to retrieve (default 6)")
    pask.add_argument("--section", default=None,
                      help="Section ID to scope query context (uses configured draft)")
    pask.add_argument("--json", action="store_true", help="JSON output")
    pask.set_defaults(func=_cmd_ask)

    pcmp = sub.add_parser("compare", help="Compare two papers: entity overlap and metrics")
    pcmp.add_argument("paper_a", help="First paper ID")
    pcmp.add_argument("paper_b", help="Second paper ID")
    pcmp.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    pcmp.add_argument("--model", default=None, help="Model override (for summary LLM)")
    pcmp.add_argument("--no-summary", action="store_true", help="Skip LLM summary generation")
    pcmp.add_argument("--json", action="store_true", help="JSON output")
    pcmp.set_defaults(func=_cmd_compare)

    # Lab subcommand group (serve added by Task 9)
    pgaps = sub.add_parser("gaps", help="Show research gaps from corpus papers vs your draft")
    pgaps.add_argument("--refresh", action="store_true",
                       help="Re-extract and re-resolve gaps before displaying")
    pgaps.add_argument("--json", action="store_true", help="JSON output")
    pgaps.set_defaults(func=_cmd_gaps)

    ptl = sub.add_parser("timeline", help="Show the research timeline (temporal overview)")
    ptl.add_argument("--json", action="store_true", help="JSON output")
    ptl.set_defaults(func=_cmd_timeline)

    plab = sub.add_parser("lab", help="Research Companion commands (folder ingestion, failures)")
    lab_sub = plab.add_subparsers(dest="lab_cmd", required=True)

    plab_ingest = lab_sub.add_parser("ingest", help="Ingest a folder of PDFs into the knowledge graph")
    plab_ingest.add_argument("folder", help="Path to folder containing PDF files")
    plab_ingest.add_argument("--no-align", action="store_true", help="Skip alignment stage")
    plab_ingest.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    plab_ingest.add_argument("--model", default=None, help="Model override")
    plab_ingest.set_defaults(func=_cmd_lab_ingest)

    plab_failures = lab_sub.add_parser("failures", help="List persisted ingest failures")
    plab_failures.set_defaults(func=_cmd_lab_failures)

    plab_serve = lab_sub.add_parser(
        "serve", help="Start the Research Companion web server (REST + SSE)"
    )
    plab_serve.add_argument(
        "--port", type=int, default=8765, help="Port to listen on (default: 8765)"
    )
    plab_serve.add_argument(
        "--no-open", action="store_true", help="Don't auto-open the browser"
    )
    plab_serve.set_defaults(func=_cmd_lab_serve)

    plab.set_defaults(func=lambda args: plab.print_help() or 0)

    pws = sub.add_parser(
        "workspace",
        help="Manage research workspaces (isolated stores per research)",
        epilog="The active workspace can also be overridden per-invocation "
               "with the RESEARCH_COMPANION_WORKSPACE environment variable.",
    )
    ws_sub = pws.add_subparsers(dest="ws_cmd", required=True)
    ws_sub.add_parser("list", help="List workspaces (* marks the active one)")
    pws_create = ws_sub.add_parser("create", help="Create a new workspace")
    pws_create.add_argument("name", help="Display name (id is a slug of it)")
    pws_use = ws_sub.add_parser("use", help="Switch the active workspace")
    pws_use.add_argument("workspace", help="Workspace id or name")
    pws.set_defaults(func=_cmd_workspace)

    return p


def main(argv: list[str] | None = None) -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(errors="replace")  # type: ignore[attr-defined]

    # Load .env files at startup: cwd convention + store .env.
    # Both are exception-safe (missing files fine, errors silently ignored).
    try:
        from research_companion import settings as _settings
        _settings.load_env_file(Path.cwd() / ".env")
        _settings.load_env_file()
    except Exception:  # noqa: BLE001
        pass

    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
