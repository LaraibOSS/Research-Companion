"""OverlapAgent: deterministic near-duplicate lane (local library only).

Thin blackboard wrapper around overlap.near_duplicate_passages — no LLM,
always-on in review. Compares the paper against the rest of the local library
and flags near-duplicate passages. An opt-in paraphrase (semantic) pass can
additionally run here, gated by the `semantic_overlap` setting: it uses local
embeddings by default and only reaches a remote embedding backend with the
user's explicit `semantic_overlap_allow_remote` consent. The opt-in,
consent-gated external similarity check is deliberately NOT run here (see the
`check-overlap --external` CLI): the always-on review never sends text off
the machine unless the user has turned semantic overlap on.
"""
from __future__ import annotations

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class OverlapAgent(Agent):
    name = "overlap"
    role = "Flags passages that near-duplicate another paper in your local library."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.overlap import near_duplicate_passages
        from research_companion.store import list_papers, load_text

        target = load_text(ctx.paper_id) or ""
        corpus = [
            (p.paper_id, load_text(p.paper_id) or "")
            for p in list_papers()
            if p.paper_id != ctx.paper_id
        ]
        result = near_duplicate_passages(target, corpus)
        result = self._maybe_semantic(
            ctx.paper_id, [pid for pid, _ in corpus], result)

        data = {"n_passages": result["summary"]["n_passages"],
                "papers": result["summary"]["papers"]}
        if "n_semantic" in result["summary"]:
            data["n_semantic"] = result["summary"]["n_semantic"]

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="overlap",
            summary=result["summary"]["text"],
            data=data,
        ))
        return AgentResult(agent=self.name, ok=True, data=result)

    @staticmethod
    def _maybe_semantic(paper_id: str, corpus_ids: list[str], lexical: dict) -> dict:
        """Opt-in paraphrase pass. Off / no backend / any failure -> lexical
        result returned untouched: the always-on lane never crashes and its
        default output is byte-identical to the lexical-only detector."""
        try:
            from research_companion import embed, semoverlap, settings

            s = settings.get_settings()
            if not s.get("semantic_overlap"):
                return lexical
            model = s.get("embed_model") or embed.DEFAULT_EMBED_MODEL
            resolved = embed.resolve_embedder(
                model=model,
                allow_remote=bool(s.get("semantic_overlap_allow_remote")))
            if resolved is None:
                return lexical
            embed_fn, _label = resolved
            semantic = semoverlap.collect_semantic_findings(
                paper_id, corpus_ids, embed_fn=embed_fn, embed_model=model,
                threshold=float(s.get("semantic_overlap_threshold")
                                or semoverlap.DEFAULT_SEMANTIC_THRESHOLD))
            return semoverlap.merge_overlap_results(lexical, semantic)
        except Exception:
            return lexical
