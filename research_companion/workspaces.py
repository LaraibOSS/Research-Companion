"""Workspace management — one isolated research per workspace.

The registry (root_dir()/workspaces.json) is the single source of truth for
which workspaces exist and which is active; the storage layout and legacy
migration live in store.py. This module adds CRUD + the cheap per-workspace
stats the Researches screen needs (no graph loads — a handful of small JSON
reads and stat() calls per workspace).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from research_companion import store


class WorkspaceError(ValueError):
    """Raised for invalid workspace operations.

    Attributes:
        status (int): HTTP-status hint — 404 unknown, 409 conflict, 422 invalid.
    """

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def slugify(name: str) -> str:
    """Workspace id from a display name; raises 422 when nothing survives."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:64]
    if not slug:
        raise WorkspaceError(
            f"workspace name must contain letters or digits, got {name!r}",
            status=422,
        )
    return slug


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _find(reg: dict, ws_id: str) -> dict:
    for rec in reg["workspaces"]:
        if rec.get("id") == ws_id:
            return rec
    raise WorkspaceError(f"unknown workspace: {ws_id!r}", status=404)


def create_workspace(name: str) -> dict:
    ws_id = slugify(name)
    reg = store.load_registry()
    if any(w.get("id") == ws_id for w in reg["workspaces"]):
        raise WorkspaceError(f"workspace already exists: {ws_id!r}", status=409)
    rec = {
        "id": ws_id,
        "name": (name or "").strip() or ws_id,
        "created_at": _now_utc(),
        "archived": False,
    }
    reg["workspaces"].append(rec)
    (store.workspaces_root() / ws_id).mkdir(parents=True, exist_ok=True)
    store.save_registry(reg)
    return rec


def update_workspace(ws_id: str, *, name: str | None = None,
                     archived: bool | None = None) -> dict:
    reg = store.load_registry()
    rec = _find(reg, ws_id)
    if archived is True and reg.get("active") == ws_id:
        raise WorkspaceError("cannot archive the active workspace", status=409)
    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise WorkspaceError("workspace name must not be empty", status=422)
        rec["name"] = stripped
    if archived is not None:
        rec["archived"] = bool(archived)
    store.save_registry(reg)
    return rec


def delete_workspace(ws_id: str) -> dict:
    """Remove a workspace's registry entry and its directory tree.

    When the deletee is active, the registry is saved twice (new active first,
    entry removed after the rmtree) so a crash mid-delete never leaves the
    registry pointing at a removed workspace, and never orphans a directory
    behind a removed entry — a re-created research with the same slug would
    inherit the old papers.
    """
    reg = store.load_registry()
    _find(reg, ws_id)
    others = [w for w in reg["workspaces"] if w.get("id") != ws_id]
    switched = reg.get("active") == ws_id

    if not others:
        # Deleting the last workspace: fall back to a fresh default main.
        others = list(store._default_registry()["workspaces"])
        # The phase-1 save below must already list the synthesized entries —
        # `active` has to point at a listed workspace even if a crash lands
        # in the rmtree window (the deletee stays listed until phase 2).
        known = {w.get("id") for w in reg["workspaces"]}
        reg["workspaces"] = reg["workspaces"] + [
            w for w in others if w["id"] not in known]

    if switched:
        if any(w.get("id") == "main" for w in others):
            new_active = "main"
        else:
            open_ws = [w for w in others if not w.get("archived")]
            new_active = (open_ws or others)[0]["id"]
        reg["active"] = new_active
        store.save_registry(reg)
    else:
        new_active = reg.get("active") or "main"

    ws_dir = store.workspaces_root() / ws_id
    if ws_dir.exists():
        store._rmtree_retry(ws_dir)

    if switched:
        # Mirror activate_workspace: the new active's directory must exist —
        # the API repoints the persistent event log there right after the
        # switch. After the rmtree, so a self-replacing main is not undone.
        (store.workspaces_root() / new_active).mkdir(parents=True, exist_ok=True)

    reg["workspaces"] = others
    store.save_registry(reg)
    if switched:
        store._reset_workspace_caches()
    return {"removed": True, "active": new_active, "switched": switched}


def activate_workspace(ws_id: str) -> dict:
    reg = store.load_registry()
    rec = _find(reg, ws_id)
    if rec.get("archived"):
        raise WorkspaceError(f"workspace is archived: {ws_id!r}", status=409)
    reg["active"] = ws_id
    (store.workspaces_root() / ws_id).mkdir(parents=True, exist_ok=True)
    store.save_registry(reg)
    store._reset_workspace_caches()
    return {"active": ws_id}


# ---------------------------------------------------------------------------
# Stats — cheap reads only, every step guarded (a corrupt workspace must never
# break the Researches screen)
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def workspace_stats(ws_id: str) -> dict:
    ws = store.workspaces_root() / ws_id
    stats = {"papers": 0, "draft_title": None, "open_suggestions": 0,
             "last_activity": None,
             "failed": 0, "draft_versions": 0, "draft_updated": None,
             "coverage": None,
             "strength": {"strong": 0, "moderate": 0, "weak": 0, "unscored": 0}}

    papers_root = ws / "papers"
    draft_id = _read_json(ws / "config.json").get("draft_paper_id")
    try:
        if papers_root.is_dir():
            stats["papers"] = sum(
                1 for d in papers_root.iterdir()
                if d.is_dir() and (d / "metadata.json").exists())
    except OSError:
        pass

    if draft_id:
        try:
            dirname = store._id_to_dirname(draft_id)
            meta = _read_json(papers_root / dirname / "metadata.json")
            stats["draft_title"] = meta.get("title") or draft_id
            sug = _read_json(ws / "suggestions" / dirname / "suggestions.json")
            stats["open_suggestions"] = sum(
                1 for s in sug.get("suggestions", [])
                if isinstance(s, dict) and s.get("status") == "open")
        except OSError:
            pass

    mtimes = []
    for probe in ("config.json", "journey.json", "graph.json", "lab_events.jsonl"):
        try:
            mtimes.append((ws / probe).stat().st_mtime)
        except OSError:
            continue
    if mtimes:
        stats["last_activity"] = (
            datetime.fromtimestamp(max(mtimes), tz=timezone.utc)
            .isoformat().replace("+00:00", "Z"))

    # failed papers (failed.json is a dict keyed by paper/target)
    failed = _read_json(ws / "failed.json")
    if isinstance(failed, dict):
        stats["failed"] = len(failed)

    # draft versions + latest timestamp (from the journey)
    journey = _read_json(ws / "journey.json")
    versions = journey.get("draft_versions") if isinstance(journey, dict) else None
    if isinstance(versions, list) and versions:
        stats["draft_versions"] = len(versions)
        last = versions[-1]
        if isinstance(last, dict):
            stats["draft_updated"] = last.get("added_at")

    # citation coverage (cached payload only — never recompute)
    cov = _read_json(ws / "citations_coverage.json")
    counts = cov.get("counts") if isinstance(cov, dict) else None
    if isinstance(counts, dict):
        in_lib = counts.get("in_library", 0)
        total = counts.get("total", 0)
        stats["coverage"] = {
            "in_library": int(in_lib) if isinstance(in_lib, (int, float)) else 0,
            "total": int(total) if isinstance(total, (int, float)) else 0,
        }

    # strength band tally over this workspace's papers
    try:
        if papers_root.is_dir():
            tally = stats["strength"]
            for d in papers_root.iterdir():
                if not (d.is_dir() and (d / "metadata.json").exists()):
                    continue
                st = _read_json(d / "strength.json")
                band = st.get("band") if isinstance(st, dict) else None
                if band in tally:
                    tally[band] += 1
                else:
                    tally["unscored"] += 1
    except OSError:
        pass

    return stats


def list_workspaces(*, with_stats: bool = True) -> dict:
    reg = store.load_registry()
    out = []
    for rec in reg["workspaces"]:
        item = dict(rec)
        if with_stats:
            item["stats"] = workspace_stats(rec["id"])
        out.append(item)
    # Effective active id (honors $RESEARCH_COMPANION_WORKSPACE), not just the
    # registry field — the UI must label the workspace actually being served.
    return {"active": store.active_workspace_id(), "workspaces": out}
