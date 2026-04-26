"""KG-aware chat over the papergraph.

Pipeline per question:
    question -> seed nodes (lexical match on labels) -> BFS subgraph (depth N, budget B)
             -> render subgraph as text + paper list -> LLM with chat prompts -> answer

Every answer cites paper titles in square brackets so users can verify.
"""
from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass
from typing import Any

import networkx as nx

from papergraph.graph import load_graph
from papergraph.prompts import CHAT_SYSTEM_PROMPT, render_chat_user_prompt


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

_STOP = {
    "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "is", "are",
    "what", "which", "how", "why", "do", "does", "did", "this", "that", "these",
    "those", "with", "from", "by", "as", "be", "been", "being", "was", "were",
    "it", "its", "they", "them", "their", "there", "here", "we", "you",
}


def _question_terms(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]+", question.lower())
    return [w for w in words if w not in _STOP and len(w) >= 3]


def _score_nodes(G: nx.Graph, terms: list[str]) -> list[tuple[float, str]]:
    """Score every node by how many query terms appear in its label/definition."""
    scored: list[tuple[float, str]] = []
    for nid, data in G.nodes(data=True):
        haystack = " ".join(str(data.get(k, "")).lower()
                             for k in ("label", "definition", "description")).strip()
        if not haystack:
            continue
        score = sum(1.0 for t in terms if t in haystack)
        # Slight preference for concept/method/dataset over paper/claim — these are
        # what users usually ask about.
        kind = data.get("kind", "")
        if kind in ("concept", "method", "dataset"):
            score *= 1.2
        if score > 0:
            scored.append((score, nid))
    scored.sort(reverse=True)
    return scored


def _bfs(G: nx.Graph, seeds: list[str], depth: int) -> tuple[set[str], list[tuple]]:
    """Breadth-first traversal capped at `depth` hops from any seed."""
    visited: set[str] = set(seeds)
    edges: list[tuple] = []
    frontier = deque((s, 0) for s in seeds)
    while frontier:
        node, d = frontier.popleft()
        if d >= depth:
            continue
        for neighbour in G.neighbors(node):
            if neighbour not in visited:
                visited.add(neighbour)
                frontier.append((neighbour, d + 1))
            if (node, neighbour) not in edges and (neighbour, node) not in edges:
                edges.append((node, neighbour))
    return visited, edges


def _render_subgraph(G: nx.Graph, nodes: set[str], edges: list[tuple],
                      *, char_budget: int = 6000) -> tuple[str, list[dict[str, Any]]]:
    """Render subgraph as text + extract the involved papers.

    Returns (context_text, papers_list). Papers list is dicts of
    {title, authors, year, source_url} for citation in the answer.
    """
    lines: list[str] = []
    paper_ids: set[str] = set()

    # Group nodes by kind for legibility.
    for kind in ("paper", "concept", "method", "dataset", "claim", "result"):
        chunk: list[str] = []
        for nid in nodes:
            d = G.nodes[nid]
            if d.get("kind") != kind:
                continue
            label = d.get("label", nid)
            extra = ""
            if kind == "paper":
                authors = d.get("authors") or []
                first = authors[0] if authors else "?"
                year = d.get("year") or "?"
                extra = f" ({first} et al., {year})" if len(authors) > 1 else f" ({first}, {year})"
                paper_ids.add(nid)
            elif kind in ("concept", "method", "dataset"):
                blurb = d.get("definition") or d.get("description") or ""
                if blurb:
                    extra = f" — {blurb[:160]}"
            elif kind == "result":
                metric = d.get("metric")
                value = d.get("value")
                ds = d.get("dataset")
                extra = f" — {metric}={value}" + (f" on {ds}" if ds else "")
            elif kind == "claim":
                extra = ""  # label already contains the text
            chunk.append(f"  - [{kind}] {label}{extra}")
        if chunk:
            lines.append(f"{kind.upper()}S:")
            lines.extend(chunk)

    # Edges (most informative ones first).
    if edges:
        lines.append("RELATIONSHIPS:")
        for u, v in edges[:80]:  # cap edge listing
            d = G.edges[u, v]
            ul = G.nodes[u].get("label", u)
            vl = G.nodes[v].get("label", v)
            lines.append(f"  {ul} --[{d.get('relation', 'related_to')}]--> {vl}")

    text = "\n".join(lines)
    if len(text) > char_budget:
        text = text[:char_budget] + "\n[... context truncated ...]"

    # Paper list for citation.
    papers: list[dict[str, Any]] = []
    for pid in paper_ids:
        d = G.nodes[pid]
        papers.append({
            "title": d.get("label", pid),
            "authors": d.get("authors") or [],
            "year": d.get("year"),
            "source_url": d.get("source_url", ""),
        })
    papers.sort(key=lambda p: (p.get("year") or 0, p.get("title", "")))
    return text, papers


def _format_paper_list(papers: list[dict[str, Any]]) -> str:
    if not papers:
        return "(no papers in retrieved subgraph)"
    out: list[str] = []
    for p in papers:
        authors = p.get("authors") or []
        first = authors[0] if authors else "?"
        year = p.get("year") or "?"
        cite = f"{first} et al., {year}" if len(authors) > 1 else f"{first}, {year}"
        out.append(f"  - {p['title']} [{cite}]")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_anthropic(system: str, user: str, *, model: str) -> tuple[str, dict]:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return text.strip(), {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }


def _call_openai(system: str, user: str, *, model: str) -> tuple[str, dict]:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        max_tokens=1024,
    )
    text = (resp.choices[0].message.content or "").strip()
    return text, {
        "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
        "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChatAnswer:
    answer: str
    context: str
    papers: list[dict[str, Any]]
    n_seed_nodes: int
    n_subgraph_nodes: int
    n_subgraph_edges: int
    input_tokens: int
    output_tokens: int


def chat(
    question: str,
    *,
    G: nx.Graph | None = None,
    provider: str = "anthropic",
    model: str | None = None,
    depth: int = 2,
    n_seeds: int = 5,
) -> ChatAnswer:
    """Answer a question using the cross-paper graph.

    Args:
        question: The natural-language question.
        G: Pre-loaded graph; defaults to loading from disk.
        provider: "anthropic" or "openai".
        model: Model override. Defaults: anthropic=claude-sonnet-4-7, openai=gpt-4o-2024-11-20.
        depth: BFS hop count from seed nodes. 2 is usually enough; 3 gets noisy.
        n_seeds: How many top-scoring nodes to seed BFS from.
    """
    G = G if G is not None else load_graph()
    if G.number_of_nodes() == 0:
        return ChatAnswer(
            answer="The knowledge graph is empty. Run `papergraph add <url>` then `papergraph build` first.",
            context="", papers=[], n_seed_nodes=0, n_subgraph_nodes=0, n_subgraph_edges=0,
            input_tokens=0, output_tokens=0,
        )

    terms = _question_terms(question)
    scored = _score_nodes(G, terms)
    seeds = [nid for _, nid in scored[:n_seeds]]
    if not seeds:
        # Fall back: include all paper nodes as seeds if no lexical match.
        seeds = [nid for nid, d in G.nodes(data=True) if d.get("kind") == "paper"][:n_seeds]

    nodes, edges = _bfs(G, seeds, depth)
    context, papers = _render_subgraph(G, nodes, edges)
    paper_list = _format_paper_list(papers)

    user_prompt = render_chat_user_prompt(
        context=context,
        paper_list=paper_list,
        question=question,
    )

    if provider == "anthropic":
        model = model or "claude-sonnet-4-7"
        answer, usage = _call_anthropic(CHAT_SYSTEM_PROMPT, user_prompt, model=model)
    elif provider == "openai":
        model = model or "gpt-4o-2024-11-20"
        answer, usage = _call_openai(CHAT_SYSTEM_PROMPT, user_prompt, model=model)
    else:
        raise ValueError(f"unknown provider {provider!r}")

    return ChatAnswer(
        answer=answer,
        context=context,
        papers=papers,
        n_seed_nodes=len(seeds),
        n_subgraph_nodes=len(nodes),
        n_subgraph_edges=len(edges),
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
    )
