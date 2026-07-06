"""Deterministic suggestions engine for Research Companion v0.3.

Turns lane data + alignment + optional gap list into tracked, actionable
suggestion objects with stable IDs and merge/dismiss semantics.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_companion.store import _id_to_dirname, papergraph_dir

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"high": 2, "medium": 1, "low": 0}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm(name: str) -> str:
    """Inline copy of graph._norm — lowercase, drop spaces/hyphens/underscores, strip non-alnum."""
    s = name.lower()
    s = re.sub(r"[ \-_]+", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def _make_sug_id(kind: str, source_key: str, title: str) -> str:
    """Stable deterministic ID: sug_<sha256(kind|source_key|_norm(title))[:12]>."""
    raw = f"{kind}|{source_key}|{_norm(title)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"sug_{digest}"


def _sug(
    *,
    kind: str,
    severity: str,
    source_key: str,
    title: str,
    detail: str,
    section_id: str | None,
    source: dict,
    now_str: str | None = None,
) -> dict:
    ts = now_str or _now_utc()
    return {
        "id": _make_sug_id(kind, source_key, title),
        "kind": kind,
        "severity": severity,
        "section_id": section_id,
        "title": title,
        "detail": detail,
        "source": source,
        "status": "open",
        "created_at": ts,
        "addressed_at": None,
        "addressed_by": None,
        "_source_key": source_key,
    }


def _strip_internal(sugs: list[dict]) -> list[dict]:
    """Remove keys beginning with '_' before output/persistence."""
    return [{k: v for k, v in s.items() if not k.startswith("_")} for s in sugs]


# ---------------------------------------------------------------------------
# Lane rules
# ---------------------------------------------------------------------------

def _apply_citation_rules(report: dict, now_str: str) -> list[dict]:
    lane = report.get("lanes", {}).get("citation", {})
    if not lane.get("ok"):
        return []
    refs = lane.get("data", {}).get("references", [])
    sugs = []
    for ref in refs:
        status = ref.get("status", "")
        title = ref.get("title", "")
        if status == "unverified":
            sugs.append(_sug(
                kind="citation",
                severity="high",
                source_key=title,
                title=f"Unverified citation: {title}",
                detail=f"The citation '{title}' could not be verified in the reference graph. Confirm it exists and is cited correctly.",
                section_id=None,
                source={"type": "lane", "lane": "citation"},
                now_str=now_str,
            ))
        elif status == "suspect":
            sugs.append(_sug(
                kind="citation",
                severity="medium",
                source_key=title,
                title=f"Suspect citation: {title}",
                detail=f"The citation '{title}' has low confidence in the reference graph. Review for accuracy.",
                section_id=None,
                source={"type": "lane", "lane": "citation"},
                now_str=now_str,
            ))
    return sugs


def _apply_novelty_rules(report: dict, now_str: str) -> list[dict]:
    lane = report.get("lanes", {}).get("novelty", {})
    if not lane.get("ok"):
        return []
    claims = lane.get("data", {}).get("claims", [])
    sugs = []
    for claim in claims:
        text = claim.get("text", "")
        verdict = claim.get("verdict", "")
        evidence_verified = claim.get("evidence_verified", True)
        closest_prior = claim.get("closest_prior") or []

        if verdict in ("overlaps", "anticipated"):
            prior_str = ", ".join(closest_prior) if closest_prior else "prior work"
            sugs.append(_sug(
                kind="novelty",
                severity="high",
                source_key=text,
                title=f"Novelty concern ({verdict}): {text[:80]}",
                detail=f"This claim ({verdict!r}) overlaps with prior work: {prior_str}. Differentiate your contribution clearly.",
                section_id=None,
                source={"type": "lane", "lane": "novelty"},
                now_str=now_str,
            ))
        elif verdict == "incremental":
            sugs.append(_sug(
                kind="novelty",
                severity="medium",
                source_key=text,
                title=f"Incremental novelty: {text[:80]}",
                detail="This contribution is incremental relative to prior work. Consider strengthening the novelty argument.",
                section_id=None,
                source={"type": "lane", "lane": "novelty"},
                now_str=now_str,
            ))

        if not evidence_verified:
            sugs.append(_sug(
                kind="evidence",
                severity="medium",
                source_key=text,
                title=f"Unverified evidence: {text[:80]}",
                detail="Evidence for this claim could not be verified. Provide citations or empirical support.",
                section_id=None,
                source={"type": "lane", "lane": "novelty"},
                now_str=now_str,
            ))
    return sugs


def _apply_confidence_rules(report: dict, now_str: str) -> list[dict]:
    lane = report.get("lanes", {}).get("confidence", {})
    if not lane.get("ok"):
        return []
    claims = lane.get("data", {}).get("claims", [])
    sugs = []
    for claim in claims:
        text = claim.get("text", "")
        score = claim.get("score", 1.0)
        if score < 0.3:
            sugs.append(_sug(
                kind="evidence",
                severity="high",
                source_key=text,
                title=f"Low-confidence claim: {text[:80]}",
                detail=f"Confidence score {score:.2f} is very low. This claim needs stronger empirical or citation support.",
                section_id=None,
                source={"type": "lane", "lane": "confidence"},
                now_str=now_str,
            ))
        elif score < 0.5:
            sugs.append(_sug(
                kind="evidence",
                severity="medium",
                source_key=text,
                title=f"Low-confidence claim: {text[:80]}",
                detail=f"Confidence score {score:.2f} is below threshold. Consider adding supporting evidence.",
                section_id=None,
                source={"type": "lane", "lane": "confidence"},
                now_str=now_str,
            ))
    return sugs


def _apply_benchmark_rules(report: dict, now_str: str) -> list[dict]:
    lane = report.get("lanes", {}).get("benchmark", {})
    if not lane.get("ok"):
        return []
    bmark_sugs = lane.get("data", {}).get("suggestions", [])
    sugs = []
    for b in bmark_sugs:
        name = b.get("name", "")
        sugs.append(_sug(
            kind="benchmark",
            severity="low",
            source_key=name,
            title=f"Consider benchmark: {name}",
            detail=f"The benchmark '{name}' appears in related prior art but is not discussed. Adding comparison may strengthen evaluation.",
            section_id=None,
            source={"type": "lane", "lane": "benchmark"},
            now_str=now_str,
        ))
    return sugs


def _apply_alignment_rules(alignments: list[dict], now_str: str) -> list[dict]:
    sugs = []
    for alignment in alignments:
        candidate_id = alignment.get("candidate_paper_id", "")
        # Resolve display label: prefer paper title over bare id
        try:
            from research_companion.store import PaperMetadata as _PM
            _meta = _PM.load(candidate_id)
            paper_label = _meta.title if _meta is not None else candidate_id
        except Exception:
            paper_label = candidate_id

        for sec in alignment.get("sections", []):
            section_id = sec.get("section_id")
            section_title = sec.get("section_title", "")
            relation = sec.get("relation", "")
            relevance = sec.get("relevance", 0.0)
            rationale = sec.get("rationale", "")

            if relation == "challenges":
                if relevance >= 0.7:
                    sev = "high"
                elif relevance >= 0.5:
                    sev = "medium"
                else:
                    continue
                sugs.append(_sug(
                    kind="evidence",
                    severity=sev,
                    source_key=f"{candidate_id}:{section_id}:{relation}",
                    title=f"Strengthen §{section_title} against challenge from {paper_label}",
                    detail=rationale or f"Section '{section_title}' is challenged by {paper_label}. Review and address.",
                    section_id=section_id,
                    source={"type": "paper", "paper_id": candidate_id, "section_id": section_id},
                    now_str=now_str,
                ))
            elif relation == "alternative":
                if relevance >= 0.5:
                    sugs.append(_sug(
                        kind="related_work",
                        severity="medium",
                        source_key=f"{candidate_id}:{section_id}:{relation}",
                        title=f"Discuss {paper_label} as an alternative in related work",
                        detail=rationale or f"Section '{section_title}' presents an alternative approach. Discuss similarities and differences.",
                        section_id=section_id,
                        source={"type": "paper", "paper_id": candidate_id, "section_id": section_id},
                        now_str=now_str,
                    ))
    return sugs


def _apply_gaps_rules(gaps: list[dict] | None, now_str: str) -> list[dict]:
    if not gaps:
        return []
    sugs = []
    for gap in gaps:
        if not gap.get("relevant", False):
            continue
        if gap.get("addressed_by_draft", False):
            continue
        statement = gap.get("statement", "")
        gap_id = gap.get("gap_id", statement)
        sugs.append(_sug(
            kind="gap",
            severity="medium",
            source_key=gap_id,
            title=f"Research gap not addressed: {statement[:80]}",
            detail=f"The research gap '{statement}' is relevant to this draft but has not been addressed.",
            section_id=None,
            source={"type": "lane", "lane": "gap"},
            now_str=now_str,
        ))
    return sugs


# ---------------------------------------------------------------------------
# Evidence dedup — keep highest severity per source_key among `kind=evidence`
# ---------------------------------------------------------------------------

def _dedup_evidence(raw: list[dict]) -> list[dict]:
    evidence_by_key: dict[str, dict] = {}
    others = []
    for s in raw:
        if s["kind"] == "evidence":
            key = s["_source_key"]
            if key not in evidence_by_key:
                evidence_by_key[key] = s
            else:
                existing = evidence_by_key[key]
                if _SEVERITY_RANK[s["severity"]] > _SEVERITY_RANK[existing["severity"]]:
                    evidence_by_key[key] = s
        else:
            others.append(s)
    return others + list(evidence_by_key.values())


# ---------------------------------------------------------------------------
# LLM structure pass (optional)
# ---------------------------------------------------------------------------

def _apply_structure_pass(
    open_sugs: list[dict],
    report: dict,
    llm: Callable[[str], str],
    now_str: str,
) -> list[dict]:
    from research_companion.prompts import format_suggest_structure_prompt
    from research_companion.store import load_sections

    paper_id = report.get("paper_id", "")
    sections_payload = load_sections(paper_id)
    valid_sec_ids: set[str] = set()
    if sections_payload:
        sec_list = sections_payload.get("sections", [])
        section_outline = "\n".join(
            f"{s['section_id']} {s.get('title', '')}" for s in sec_list
        )
        valid_sec_ids = {s["section_id"] for s in sec_list}
    else:
        section_outline = "(no section outline available)"

    open_titles = "\n".join(s["title"] for s in open_sugs)
    prompt = format_suggest_structure_prompt(
        section_outline=section_outline,
        open_suggestions=open_titles or "(none)",
    )

    try:
        raw_response = llm(prompt)
        payload = json.loads(raw_response)
        proposals = payload.get("suggestions", [])[:3]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []

    sugs = []
    for p in proposals:
        title = p.get("title", "")
        detail = p.get("detail", "")
        sec_id = p.get("section_id")
        severity = p.get("severity", "medium")
        if sec_id not in valid_sec_ids:
            sec_id = None
        if severity not in _SEVERITY_RANK:
            severity = "medium"
        sugs.append(_sug(
            kind="structure",
            severity=severity,
            source_key=title,
            title=title,
            detail=detail,
            section_id=sec_id,
            source={"type": "lane", "lane": "structure"},
            now_str=now_str,
        ))
    return sugs


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _merge(fresh: list[dict], previous: list[dict], now_str: str) -> list[dict]:
    """Merge fresh suggestions with previous, applying status persistence rules."""
    fresh_by_id = {s["id"]: s for s in fresh}
    prev_by_id = {s["id"]: s for s in previous}

    result_by_id: dict[str, dict] = {}

    # Start with fresh set
    for sid, sug in fresh_by_id.items():
        if sid in prev_by_id:
            prev = prev_by_id[sid]
            prev_status = prev.get("status", "open")
            prev_addressed_by = prev.get("addressed_by") or {}

            if prev_status == "dismissed":
                # User-dismissed never reopens
                merged = dict(sug)
                merged["status"] = "dismissed"
                merged["addressed_at"] = prev.get("addressed_at")
                merged["addressed_by"] = prev.get("addressed_by")
                merged["created_at"] = prev.get("created_at", sug["created_at"])
                result_by_id[sid] = merged
            elif prev_status == "addressed" and prev_addressed_by.get("by") == "auto":
                # Auto-addressed that reappears → reopen
                merged = dict(sug)
                merged["status"] = "open"
                merged["addressed_at"] = None
                merged["addressed_by"] = None
                merged["created_at"] = prev.get("created_at", sug["created_at"])
                result_by_id[sid] = merged
            else:
                # Open or user/llm addressed — preserve status
                merged = dict(sug)
                merged["status"] = prev_status
                merged["addressed_at"] = prev.get("addressed_at")
                merged["addressed_by"] = prev.get("addressed_by")
                merged["created_at"] = prev.get("created_at", sug["created_at"])
                result_by_id[sid] = merged
        else:
            result_by_id[sid] = sug

    # Handle items from previous that are absent in fresh
    for sid, prev in prev_by_id.items():
        if sid in fresh_by_id:
            continue
        prev_status = prev.get("status", "open")
        prev_addressed_by = prev.get("addressed_by") or {}

        if prev_status == "open":
            # Was open but no longer detected — auto-address
            gone = dict(prev)
            gone["status"] = "addressed"
            gone["addressed_at"] = now_str
            gone["addressed_by"] = {"by": "auto", "note": "no longer detected"}
            result_by_id[sid] = gone
        elif prev_status == "dismissed":
            # Keep dismissed ones even if absent from fresh
            result_by_id[sid] = prev
        elif prev_status == "addressed" and prev_addressed_by.get("by") == "auto":
            # Drop old auto-addressed if still absent (don't accumulate stale)
            pass
        else:
            # Keep user/llm addressed items
            result_by_id[sid] = prev

    return list(result_by_id.values())


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _suggestions_path(draft_id: str) -> Path:
    dirname = _id_to_dirname(draft_id)
    return papergraph_dir() / "suggestions" / dirname / "suggestions.json"


def save_suggestions(draft_id: str, payload: dict) -> Path:
    p = _suggestions_path(draft_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_suggestions(draft_id: str) -> dict | None:
    p = _suggestions_path(draft_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_suggestions(
    *,
    draft_id: str,
    report: dict | None = None,
    alignments: list[dict] | None = None,
    gaps: list[dict] | None = None,
    llm: Callable[[str], str] | None = None,
    include_llm: bool = False,
    now: datetime | None = None,
) -> dict:
    """Generate, merge, persist, and return the full suggestions payload."""
    now_dt = now or datetime.now(timezone.utc)
    now_str = now_dt.isoformat().replace("+00:00", "Z")

    # Fallback: load report from store when not explicitly provided
    if report is None:
        from research_companion.store import load_review_report
        report = load_review_report(draft_id)
        if report is None:
            report = {"paper_id": draft_id, "lanes": {}}

    # Fallback: load alignments from store for all non-draft papers
    if alignments is None:
        from research_companion import store as _store
        papers = _store.list_papers()
        alignments = []
        for p in papers:
            if p.paper_id == draft_id:
                continue
            al = _store.load_alignment(p.paper_id, draft_paper_id=draft_id)
            if al is not None:
                alignments.append(al)

    # Fallback: load gaps from gaps engine when not explicitly provided
    if gaps is None:
        try:
            from research_companion.gaps import gaps_for_suggestions as _gaps_for_suggestions
            gaps = _gaps_for_suggestions()
        except Exception:  # noqa: BLE001
            gaps = None

    # Collect raw suggestions from all lanes
    raw: list[dict] = []
    raw.extend(_apply_citation_rules(report, now_str))
    raw.extend(_apply_novelty_rules(report, now_str))
    raw.extend(_apply_confidence_rules(report, now_str))
    raw.extend(_apply_benchmark_rules(report, now_str))
    raw.extend(_apply_alignment_rules(alignments, now_str))
    raw.extend(_apply_gaps_rules(gaps, now_str))

    # Dedup evidence by source_key
    fresh = _dedup_evidence(raw)

    # LLM structure pass (optional) — record sha when it runs
    from research_companion.prompts import suggest_structure_prompt_sha256 as _struct_sha
    struct_sha: str | None = None
    if include_llm and llm is not None:
        open_sugs = _strip_internal(fresh)
        struct_sugs = _apply_structure_pass(open_sugs, report, llm, now_str)
        fresh.extend(struct_sugs)
        struct_sha = _struct_sha()

    # Load previous and merge
    previous_payload = load_suggestions(draft_id)
    previous: list[dict] = []
    if previous_payload:
        # Re-attach _source_key for merge (not needed since merge uses id, but stay safe)
        previous = previous_payload.get("suggestions", [])

    merged = _merge(fresh, previous, now_str)

    # Strip internal keys before output
    final_sugs = _strip_internal(merged)

    payload: dict[str, Any] = {
        "version": 1,
        "draft_paper_id": draft_id,
        "draft_version": report.get("draft_version", ""),
        "generated_at": now_str,
        "suggestions": final_sugs,
        "structure_prompt_sha256": struct_sha,
    }

    save_suggestions(draft_id, payload)
    return payload


def dismiss_suggestion(
    sug_id: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Mark a suggestion as user-dismissed. Raises KeyError if not found."""
    now_dt = now or datetime.now(timezone.utc)
    now_str = now_dt.isoformat().replace("+00:00", "Z")

    # Find which draft owns this suggestion
    suggestions_root = papergraph_dir() / "suggestions"
    if not suggestions_root.exists():
        raise KeyError(sug_id)

    for draft_dir in suggestions_root.iterdir():
        if not draft_dir.is_dir():
            continue
        p = draft_dir / "suggestions.json"
        if not p.exists():
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            continue

        sugs = payload.get("suggestions", [])
        for i, sug in enumerate(sugs):
            if sug.get("id") == sug_id:
                sugs[i] = dict(sug)
                sugs[i]["status"] = "dismissed"
                sugs[i]["addressed_at"] = now_str
                sugs[i]["addressed_by"] = {"by": "user", "note": "dismissed"}
                payload["suggestions"] = sugs
                p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                return sugs[i]

    raise KeyError(sug_id)
