"""BenchmarkAgent: suggest evaluation benchmarks by mining the knowledge graph
for dataset nodes and counting how many related (prior-art) papers mention each.
Fully deterministic - no LLM.
"""
from __future__ import annotations

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class BenchmarkAgent(Agent):
    name = "benchmark"
    role = "Suggests evaluation benchmarks used by related work, mined from the graph."
    depends_on = ("ingest", "priorart")

    async def run(self, ctx: AgentContext) -> AgentResult:
        graph = ctx.data["_graph"]
        prior = ctx.data.get("_priorart_papers") or []
        prior_texts = [f"{p.title} {p.abstract}".lower() for p in prior]

        suggestions = []
        for node, attrs in graph.nodes(data=True):
            if attrs.get("kind") != "dataset":
                continue
            label = str(attrs.get("label") or node)
            mentions = sum(1 for t in prior_texts if label.lower() in t)
            suggestions.append({
                "name": label,
                "graph_degree": graph.degree(node),
                "prior_art_mentions": mentions,
            })
        suggestions.sort(key=lambda s: (-s["prior_art_mentions"], -s["graph_degree"], s["name"]))

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="benchmarks",
            summary=f"{len(suggestions)} benchmark(s) suggested",
            data={"count": len(suggestions)},
        ))
        return AgentResult(agent=self.name, ok=True, data={"suggestions": suggestions})
