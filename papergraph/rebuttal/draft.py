"""Rebuttal drafting pipeline: classify -> retrieve -> draft -> verify -> assemble."""
from __future__ import annotations

import json
from collections.abc import Callable

from papergraph.rebuttal.dedup import group_concerns
from papergraph.rebuttal.models import Concern, RebuttalReport, ResponseDraft
from papergraph.rebuttal.retrieve import retrieve_passages
from papergraph.rebuttal.verify import verify_reply_quotes


def _parse(raw: str, what: str) -> dict:
    from papergraph.extract import _strip_code_fences

    try:
        return json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"rebuttal: LLM returned invalid JSON for {what}: {exc}") from exc


def draft_rebuttal(
    concerns: list[Concern],
    fulltext: str,
    llm: Callable[[str], str],
    tone: str = "balanced",
) -> RebuttalReport:
    from papergraph.prompts import format_classify_prompt, format_rebuttal_prompt

    drafts: list[ResponseDraft] = []
    changelog: list[str] = []
    for c in concerns:
        c.kind = _parse(llm(format_classify_prompt(c.text)), "classification").get(
            "kind", "clarification")
        passages = retrieve_passages(c.text, fulltext)
        passage_block = "\n".join(f"{p.location}: {p.text}" for p in passages) or "(none found)"
        out = _parse(llm(format_rebuttal_prompt(c.text, c.kind, passage_block, tone)), "draft")
        reply = out.get("reply", "")
        unverified = verify_reply_quotes(reply, fulltext)
        revision = out.get("planned_revision", "")
        if revision and revision not in changelog:
            changelog.append(revision)
        drafts.append(ResponseDraft(
            concern_id=c.concern_id, reply=reply, cited_passages=passages,
            verified=not unverified, unverified_spans=unverified,
            planned_revision=revision,
        ))
    return RebuttalReport(drafts=drafts, changelog=changelog, groups=group_concerns(concerns))
