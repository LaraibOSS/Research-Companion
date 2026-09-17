"""Whether a person could act on a failure record, and which Acquisition
that record is actually about.

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


def stored_acquisition(info: dict, key: str) -> dict | None:
    """The Acquisition dict this failure record is about, or None.

    THE fallback rule, in one place. Two things write an acquisition
    outcome, and only one of them used to be readable:

    * ``failed.json`` records grow an ``acquisition`` block when the failure
      was recorded by a code path that HELD the Acquisition
      (research_companion/lab_api.py's ``_queue_add_paper`` except-block,
      ``_find_pdf_for_failure``).
    * ``PaperMetadata.last_acquisition`` (research_companion/fetch.py) is
      written by EVERY add, including the ones that do not raise --
      ``add_doi``/``add_s2``/``add_arxiv`` save metadata and return when the
      PDF cannot be got, so no exception ever reaches the except-block above
      and the failure is instead recorded three stages downstream, by
      research_companion/lab/__init__.py, with no acquisition attached.

    The second case is the primary failure path -- every one of the 17 real
    recorded failures took it -- so reading only the first meant the typed
    chain never reached the surface that actually fails. This falls back to
    the paper's own ``last_acquisition``.

    Guarded twice, so the fallback can only ever describe THIS failure:

    * a PDF already on disk means the paper's stored acquisition is stale
      history (the user supplied the file themselves, or a later retry got
      it) and this failure is a parse/OCR/graph failure instead -- return
      None and let the caller fall back to its own rule.
    * an ``obtained: true`` acquisition likewise describes a success, not
      this failure.
    """
    acquisition = info.get("acquisition") if isinstance(info, dict) else None
    if isinstance(acquisition, dict):
        return acquisition

    from research_companion.store import PaperMetadata, pdf_path

    paper_id = (info.get("paper_id") if isinstance(info, dict) else None) or key
    if not paper_id:
        return None
    if pdf_path(paper_id) is not None:
        return None
    meta = PaperMetadata.load(paper_id)
    last = getattr(meta, "last_acquisition", None) if meta is not None else None
    if isinstance(last, dict) and not last.get("obtained"):
        return last
    return None


def human_can_help(info: dict, key: str) -> bool:
    """Whether a person could do something about this failure -- the only
    class of failure a retry (CLI ``acquire``, Lab find-pdf) can actually
    fix.

    Reads the persisted ``acquisition.human_can_help`` flag -- computed once
    in ``Acquisition.human_can_help`` (research_companion/acquire/types.py)
    -- rather than re-deriving it from the reason or the attempts a second
    time. Which acquisition that is, is ``stored_acquisition``'s decision
    and only its decision.

    A failure with no acquisition anywhere -- a failure stage that never
    went through acquire(), e.g. "PDF not found" (fetch.py's
    add_local_pdf), or a bare add-stage failure -- falls back to whether a
    PDF actually exists on disk for the paper this record is about: the
    record's own ``paper_id`` when it has one, else ``key`` itself (the
    failure-record key -- often a DOI/path/upload:// string -- doubles as
    the paper_id on these older records). That is exactly what "a human
    could help by supplying the missing file" means. A parse/OCR/graph
    failure on a PDF that IS present on disk must not get this affordance
    -- re-running acquisition and re-saving a hit would silently overwrite
    a file the user already has.
    """
    acquisition = stored_acquisition(info, key)
    if isinstance(acquisition, dict):
        return bool(acquisition.get("human_can_help", True))
    from research_companion.store import pdf_path

    paper_id = (info.get("paper_id") if isinstance(info, dict) else None) or key
    return pdf_path(paper_id) is None
