"""Command-line interface for papergraph.

Subcommands:
    add <url-or-pdf> [--title T] [--authors A,B,C] [--year Y]
    build [--provider anthropic|openai] [--model M] [--force]
    view [--no-open]
    chat [<question>] [--provider P] [--model M] [--depth N]
    list
    remove <paper-id>
    stats
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

    authors = [a.strip() for a in args.authors.split(",")] if args.authors else None
    try:
        meta = add_paper(args.target, title=args.title, authors=authors, year=args.year)
    except FetchError as e:
        print(f"papergraph: failed to add: {e}", file=sys.stderr)
        return 1
    except TypeError:
        # add_paper rejects local-PDF kwargs for arXiv inputs by passing **local_kwargs.
        # If the user supplied --title for an arXiv URL, we just ignore it.
        meta = add_paper(args.target)
    print(f"+ {meta.paper_id}  {meta.title}")
    if meta.authors:
        print(f"  {', '.join(meta.authors[:3])}{'...' if len(meta.authors) > 3 else ''}, {meta.year or '?'}")
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="papergraph",
        description="Knowledge graph + chat over a corpus of research papers.",
    )
    p.add_argument("--version", action="version", version=f"papergraph {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="Add an arXiv URL/ID or local PDF")
    pa.add_argument("target", help="arXiv URL/ID (e.g. 2410.05779) or path to PDF")
    pa.add_argument("--title", help="Title (local PDFs only)")
    pa.add_argument("--authors", help="Comma-separated authors (local PDFs only)")
    pa.add_argument("--year", type=int, help="Year (local PDFs only)")
    pa.set_defaults(func=_cmd_add)

    pb = sub.add_parser("build", help="Run extraction on all papers and build the graph")
    pb.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    pb.add_argument("--model", default=None, help="Model override (defaults to provider's recommended)")
    pb.add_argument("--force", action="store_true", help="Re-extract even if cached")
    pb.set_defaults(func=_cmd_build)

    pv = sub.add_parser("view", help="Render and open the interactive HTML graph")
    pv.add_argument("--no-open", action="store_true", help="Don't auto-open the browser")
    pv.set_defaults(func=_cmd_view)

    pc = sub.add_parser("chat", help="Ask a question (one-shot if argument given, else REPL)")
    pc.add_argument("question", nargs="?", help="Question (omit for interactive REPL)")
    pc.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    pc.add_argument("--model", default=None)
    pc.add_argument("--depth", type=int, default=2, help="BFS hop depth (default 2)")
    pc.set_defaults(func=_cmd_chat)

    pl = sub.add_parser("list", help="List papers in the local store")
    pl.add_argument("--json", action="store_true", help="JSON output")
    pl.set_defaults(func=_cmd_list)

    pr = sub.add_parser("remove", help="Remove a paper from the store")
    pr.add_argument("paper_id", help="Paper ID, e.g. arxiv:2410.05779 or local:abc123")
    pr.set_defaults(func=_cmd_remove)

    ps = sub.add_parser("stats", help="Print graph statistics as JSON")
    ps.set_defaults(func=_cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
