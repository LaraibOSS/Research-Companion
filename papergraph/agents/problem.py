"""ProblemStatementAgent: refine a research problem statement against the graph
and prior-art context.

The LLM is reached only through ctx.data["_llm"] (callable prompt -> raw text);
tests inject it, production falls back to novelty._default_llm.
"""
from __future__ import annotations

import asyncio
import json

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


def _parse_json(raw: str, what: str) -> dict:
    from papergraph.extract import _strip_code_fences

    try:
        parsed = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"problem: LLM returned invalid JSON for {what}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"problem: LLM returned non-object JSON for {what}")
    return parsed


class ProblemStatementAgent(Agent):
    name = "problem"
    role = "Refines the researcher's problem statement against the knowledge graph."
    depends_on = ("ingest", "priorart")

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.agents.novelty import _default_llm
        from papergraph.prompts import format_problem_prompt

        try:
            statement: str = ctx.data.get("_problem_statement") or ""
            if not statement.strip():
                return AgentResult(
                    agent=self.name,
                    ok=False,
                    error=(
                        "problem: no problem statement provided — "
                        "supply one with --problem"
                    ),
                )

            # Build graph context: top-10 concept labels by degree
            graph = ctx.data.get("_graph")
            concept_labels: list[str] = []
            if graph is not None:
                concept_nodes = [
                    n for n, attrs in graph.nodes(data=True)
                    if attrs.get("kind") == "concept"
                ]
                concept_nodes.sort(key=lambda n: graph.degree(n), reverse=True)
                concept_labels = [
                    graph.nodes[n].get("label", str(n))
                    for n in concept_nodes[:10]
                ]

            # Build prior-art context: first 10 titles
            prior = ctx.data.get("_priorart_papers") or []
            prior_titles = [p.title for p in prior[:10]]

            lines: list[str] = []
            if concept_labels:
                lines.append("Concepts:")
                lines.extend(f"  - {label}" for label in concept_labels)
            if prior_titles:
                lines.append("Prior-art papers:")
                lines.extend(f"  - {title}" for title in prior_titles)
            graph_context = "\n".join(lines) if lines else "(no graph context available)"

            llm = ctx.data.get("_llm") or _default_llm
            raw = await asyncio.to_thread(
                llm, format_problem_prompt(statement, graph_context)
            )
            result_data = _parse_json(raw, "problem refinement")

            await ctx.bus.publish(events.Finding(
                agent=self.name,
                kind="problem_refined",
                summary=result_data.get("refined_statement", "")[:120],
                data=result_data,
            ))

            return AgentResult(agent=self.name, ok=True, data=result_data)

        except Exception as exc:
            return AgentResult(agent=self.name, ok=False, error=str(exc))
