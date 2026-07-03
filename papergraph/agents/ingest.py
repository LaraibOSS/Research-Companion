"""IngestAgent: load the paper's cached extraction and build the knowledge graph."""
from __future__ import annotations

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class IngestAgent(Agent):
    name = "ingest"
    role = "Loads the paper and builds the cross-paper knowledge graph."

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.graph import build_graph
        from papergraph.prompts import extraction_prompt_sha256
        from papergraph.store import load_extraction

        ext = load_extraction(ctx.paper_id, prompt_sha=extraction_prompt_sha256())
        if ext is None:
            return AgentResult(
                agent=self.name, ok=False,
                error=f"no extraction for {ctx.paper_id}; run `papergraph build` first",
            )
        graph = build_graph()
        ctx.data["_graph"] = graph
        ctx.data["_extraction"] = ext
        data = {"graph_nodes": graph.number_of_nodes(), "graph_edges": graph.number_of_edges()}
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="graph_built",
            summary=f"graph: {data['graph_nodes']} nodes / {data['graph_edges']} edges",
            data=data,
        ))
        return AgentResult(agent=self.name, ok=True, data=data)
