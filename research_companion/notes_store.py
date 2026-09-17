"""Workspace-scoped revision notes (papergraph_dir()/notes.json).

Each note is a structured, citable record captured from an uncited-paper
opportunity suggestion. Mirrors the failures-store accessors in
research_companion.store (record_failure / list_failures / clear_failure).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from research_companion.store import workspace_path

# origin_* record WHERE the note was written (the gap/question/section the
# reader was looking at), as opposed to paper_id/draft_section_id, which
# record what the note is ABOUT. A note can legitimately have both.
# Appended at the end: save_note filters through this tuple with a ""
# default, so existing notes on disk read back with an empty origin and
# need no migration.
_FIELDS = ("draft_section_id", "draft_section_title", "paper_id", "paper_title",
           "relation", "relevance", "rationale", "evidence_quote",
           "evidence_section_id", "comment", "kind", "source_excerpt",
           "origin_kind", "origin_id", "origin_label")


def _path() -> Path | None:
    return workspace_path("notes.json")


def _as_float(value, default: float = 0.0) -> float:
    """Coerce a value to float, falling back to default on anything invalid.

    relevance itself is not validated at the API boundary (which only
    checks that `kind` is a known value and that the note isn't entirely
    empty — see create_note_endpoint in lab_api.py), so a note can
    legitimately arrive (or already exist on disk, from an older/buggy
    write) with a missing, None, or non-numeric relevance. Both the writer
    (save_note) and the reader (notes_to_markdown's sort key) must tolerate
    that without raising, since a single bad record must not 500 the whole
    export.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def list_notes() -> list[dict]:
    """Load and return all notes. Returns [] if file missing, unparseable, or
    no active workspace."""
    p = _path()
    if p is None or not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    for n in data:
        if isinstance(n, dict):
            n.setdefault("kind", "opportunity")
    return data


def _write(notes: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")


def save_note(record: dict) -> dict:
    """Create (or update-in-place, when deduping) a note and persist it.

    Assigns id/created_at/status="open" for a new note. If an OPEN note
    already exists for the same (paper_id, draft_section_id, kind), its
    fields are updated in place and returned instead of appending a
    duplicate. The kind check keeps e.g. a freeform note from clobbering
    an existing alignment/opportunity note that happens to target the
    same paper+section.
    """
    notes = list_notes()
    clean = {k: record.get(k, "") for k in _FIELDS}
    clean["relevance"] = _as_float(record.get("relevance"))
    # New saves always pass (or default) a kind; only on-disk legacy notes
    # lack one, and those are backfilled to "opportunity" on read instead.
    clean["kind"] = record.get("kind") or "freeform"
    for existing in notes:
        if (existing.get("status") == "open"
                and clean["paper_id"] and clean["draft_section_id"]
                and existing.get("paper_id") == clean["paper_id"]
                and existing.get("draft_section_id") == clean["draft_section_id"]
                and existing.get("kind") == clean["kind"]):
            merged = dict(clean)
            if not merged["comment"]:
                # Don't blank a user's existing comment just because a
                # re-save (e.g. refreshed suggestion) omitted one.
                merged["comment"] = existing.get("comment", "")
            # Preserve origin fields on re-save, just like comment. A re-save
            # without origin should not erase a previously recorded origin.
            # Only overwrite if the incoming record explicitly provides a value.
            for origin_field in ("origin_kind", "origin_id", "origin_label"):
                if not merged[origin_field]:
                    merged[origin_field] = existing.get(origin_field, "")
            existing.update(merged)
            _write(notes)
            return existing
    note = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "open",
        **clean,
    }
    notes.append(note)
    _write(notes)
    return note


def update_note(note_id: str, *, status: str | None = None, comment: str | None = None) -> dict | None:
    """Patch status/comment on an existing note. Returns None if not found."""
    notes = list_notes()
    for n in notes:
        if n.get("id") == note_id:
            if status is not None:
                n["status"] = status
            if comment is not None:
                n["comment"] = comment
            _write(notes)
            return n
    return None


def delete_note(note_id: str) -> bool:
    """Remove a note by id. Returns True if a note was removed."""
    notes = list_notes()
    kept = [n for n in notes if n.get("id") != note_id]
    if len(kept) == len(notes):
        return False
    _write(kept)
    return True


def notes_to_markdown(notes: list[dict], group_by: str = "section") -> str:
    """Render notes as a "Revision notes" markdown doc, grouped by section
    (or, when group_by="paper", by paper).

    Dismissed notes are omitted. Within each group, notes are ordered by
    relevance descending. Done notes render as checked boxes.
    """
    visible = [n for n in notes if n.get("status") != "dismissed"]
    if not visible:
        return "# Revision notes\n\n_No notes yet._\n"
    groups: dict[str, list[dict]] = {}
    for n in visible:
        if group_by == "paper":
            key = n.get("paper_title") or "Unfiled"
        else:
            key = n.get("draft_section_title") or "Unfiled"
        groups.setdefault(key, []).append(n)
    lines = ["# Revision notes", ""]
    for title in sorted(groups):
        lines.append(f"## {title}")
        for n in sorted(groups[title], key=lambda x: _as_float(x.get("relevance")), reverse=True):
            box = "x" if n.get("status") == "done" else " "
            line = (f"- [{box}] {n.get('paper_title', '')} — {n.get('relation', '')}, "
                    f"relevance {n.get('relevance', 0.0)} — {n.get('rationale', '')}")
            if n.get("source_excerpt"):
                line += f" — {n['source_excerpt']}"
            if n.get("comment"):
                line += f" — note: {n['comment']}"
            if n.get("origin_label"):
                # Only the label. An origin_id is an opaque hash and means
                # nothing in an exported document read outside the app.
                line += f" — from: {n['origin_label']}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines) + "\n"
