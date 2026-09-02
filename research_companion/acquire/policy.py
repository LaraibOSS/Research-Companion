"""Whether a person could act on a failure record.

This is the one place both the CLI and the Lab decide "a human could help"
-- previously implemented twice (research_companion/lab_api.py and
research_companion/cli.py), and the two copies disagreed on what to do when
a failure record predates acquire() and carries no ``paper_id`` either (e.g.
research_companion/lab/__init__.py's bare ``{"stage": "add", "error": ...}``
records): the Lab substituted the failure-record key for the missing
paper_id and ran the disk check; the CLI skipped the disk check for that
case and returned True unconditionally. This module adopts the Lab's
behaviour as the one behaviour both sides call.

Depends on nothing beyond stdlib and research_companion.store, so the CLI
(which must run without the ``[server]`` extra -- no FastAPI/uvicorn) can
import it exactly as freely as the Lab does.
"""
from __future__ import annotations


def human_can_help(info: dict, key: str) -> bool:
    """Whether a person could do something about this failure -- the only
    class of failure a retry (CLI ``acquire``, Lab find-pdf) can actually
    fix.

    Reads the persisted ``acquisition.human_can_help`` flag -- computed once
    in ``Acquisition.human_can_help`` (research_companion/acquire/types.py)
    -- rather than re-deriving it from the reason or the attempts a second
    time.

    A failure recorded with no acquisition at all -- a failure stage that
    never went through acquire(), e.g. a stale "no PDF on disk" (extract.py),
    "PDF not found" (fetch.py's add_local_pdf), or a bare add-stage failure
    (research_companion/lab/__init__.py, which writes no ``paper_id`` at
    all) -- falls back to whether a PDF actually exists on disk for the
    paper this record is about: the record's own ``paper_id`` when it has
    one, else ``key`` itself (the failure-record key -- often a DOI/path/
    upload:// string -- doubles as the paper_id on these older records).
    That is exactly what "a human could help by supplying the missing file"
    means. A parse/OCR/graph failure on a PDF that IS present on disk must
    not get this affordance -- re-running acquisition and re-saving a hit
    would silently overwrite a file the user already has.
    """
    acquisition = info.get("acquisition") if isinstance(info, dict) else None
    if isinstance(acquisition, dict):
        return bool(acquisition.get("human_can_help", True))
    from research_companion.store import pdf_path

    paper_id = (info.get("paper_id") if isinstance(info, dict) else None) or key
    return pdf_path(paper_id) is None
