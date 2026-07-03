"""Rebuttal drafting pipeline: classify -> retrieve -> draft -> verify -> assemble."""
from __future__ import annotations

import json
import re
from collections.abc import Callable

from papergraph.rebuttal.dedup import group_concerns
from papergraph.rebuttal.models import Concern, RebuttalReport, ResponseDraft
from papergraph.rebuttal.retrieve import retrieve_passages
from papergraph.rebuttal.verify import verify_reply_quotes

_VALID_KINDS = ("factual_error", "misunderstanding", "valid_weakness", "clarification")


def _parse(raw: str, what: str) -> dict:
    from papergraph.extract import _strip_code_fences

    try:
        parsed = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"rebuttal: LLM returned invalid JSON for {what}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"rebuttal: LLM returned non-object JSON for {what}")
    return parsed


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
        if c.kind and c.kind in _VALID_KINDS:
            kind = c.kind
        else:
            kind = _parse(llm(format_classify_prompt(c.text)), "classification").get(
                "kind", "clarification")
            if kind not in _VALID_KINDS:
                kind = "clarification"
            c.kind = kind
        passages = retrieve_passages(c.text, fulltext)
        passage_block = "\n".join(f"{p.location}: {p.text}" for p in passages) or "(none found)"
        out = _parse(llm(format_rebuttal_prompt(c.text, c.kind, passage_block, tone)), "draft")
        reply = out.get("reply", "")
        unverified = verify_reply_quotes(reply, fulltext)
        revision = out.get("planned_revision", "")
        if revision and revision not in changelog:
            changelog.append(revision)
        spans = [s for s in re.findall(r'"([^"]+)"', reply) if len(s) >= 15]
        if unverified:
            evidence_status = "unverified"
        elif spans:
            evidence_status = "verified"
        else:
            evidence_status = "no_quotes"
        drafts.append(ResponseDraft(
            concern_id=c.concern_id, reply=reply, cited_passages=passages,
            verified=not unverified, unverified_spans=unverified,
            planned_revision=revision, evidence_status=evidence_status,
        ))
    return RebuttalReport(drafts=drafts, changelog=changelog, groups=group_concerns(concerns))
