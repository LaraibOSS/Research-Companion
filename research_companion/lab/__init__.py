"""Lab folder-ingestion pipeline.

Ingests a folder of PDFs through the full pipeline:
    add -> text -> sections -> extract -> graph delta -> align vs draft -> strength

Publishes typed events on the Bus so a web UI can show the knowledge graph growing live.
Failures are per-stage, persisted, never abort the run, and re-runs are idempotent.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from research_companion.agents.events import (
    AlignmentReady,
    EmbeddingsReady,
    GraphDelta,
    IngestFailed,
    IngestProgress,
    IngestSkipped,
    JobDone,
    PaperAdded,
    SectionExtracted,
    SectionTreeBuilt,
    StrengthUpdated,
    SuggestionsUpdated,
)

# Sentinel for "not provided" — distinguishes explicit None (skip) from unset (use default).
_UNSET = object()

# Shown when text extraction yields nothing usable (scanned/image-only PDF).
# Making this an honest failure stops empty text from polluting the pipeline.
EMPTY_TEXT_ERROR = (
    "No extractable text — the PDF appears to be scanned/image-only. "
    "Install the OCR engine (pip install research-companion[docling]) "
    "or add the paper's metadata by hand."
)

# Shown when the forced full-page OCR fallback ran (docling present) but STILL
# recovered no usable text — the PDF is likely corrupt or genuinely text-free.
OCR_FAILED_ERROR = (
    "Could not extract text even with OCR — the PDF may be corrupt or "
    "contain no recognizable text."
)

# Module-level lock to serialize graph read/write operations across concurrent tasks.
_GRAPH_LOCK = asyncio.Lock()


@dataclass
class IngestResult:
    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)


def scan_pdfs(folder: Path) -> list[Path]:
    """Return sorted list of PDF paths found recursively under *folder*.

    Raises ValueError if folder is missing or not a directory.
    """
    folder = Path(folder)
    if not folder.exists():
        raise ValueError(f"folder does not exist: {folder}")
    if not folder.is_dir():
        raise ValueError(f"not a directory: {folder}")
    return sorted(folder.rglob("*.pdf"))


def _default_aligner():
    """Return align_papers if importable, else None."""
    try:
        from research_companion.alignment import align_papers
        return align_papers
    except ImportError:
        return None


def _default_strengther():
    """Return strength_for_paper if importable, else None."""
    try:
        from research_companion.strength import strength_for_paper
        return strength_for_paper
    except ImportError:
        return None


def _default_embedder():
    """Return embed_paper_sections if importable, else None."""
    try:
        from research_companion.embed import embed_paper_sections
        return embed_paper_sections
    except ImportError:
        return None


def _build_llm_callable(provider: str, model: str | None) -> Callable[[str], str]:
    """Build a real LLM callable for the given provider/model (lazy import)."""
    from research_companion.extract import _call_anthropic, _call_openai, resolve_model

    resolved_model = resolve_model(provider, model)
    call = _call_openai if provider == "openai" else _call_anthropic

    def _llm(prompt: str) -> str:
        text, _usage = call(prompt, model=resolved_model)
        return text

    return _llm


def _acquisition_failure(paper_id: str, stage: str, error: str) -> dict:
    """The failure record for one ingest-stage failure, carrying the paper's
    acquisition outcome whenever that outcome is what actually went wrong.

    This is the path every real failure takes. ``add_doi``/``add_s2``/
    ``add_arxiv`` do NOT raise when the PDF cannot be got -- they save the
    metadata, print a warning and return -- so the add job succeeds, no
    exception ever reaches lab_api's add-failure handler (the only other
    place that attaches an ``acquisition``), and the paper instead fails
    here, three stages downstream, with ``FileNotFoundError("no PDF on disk
    for ...")`` from extract.py. Recorded bare, that sentence is the symptom
    and not the cause, and it is what all 17 recorded failures on disk say.

    ``acquire.policy.stored_acquisition`` is the ONE place that decides which
    acquisition a failure record is about (it returns None when a PDF IS on
    disk, so a genuine parse/OCR/graph failure is left exactly as it was);
    ``acquire.copy.failure_sentence`` is the ONE place that phrases it. This
    function only joins them to a record.
    """
    info = {"stage": stage, "error": error, "paper_id": paper_id}
    try:
        from research_companion.acquire import Acquisition
        from research_companion.acquire.copy import failure_sentence
        from research_companion.acquire.policy import stored_acquisition

        acquisition = stored_acquisition({"paper_id": paper_id}, paper_id)
        if not isinstance(acquisition, dict):
            return info
        sentence = failure_sentence(Acquisition.from_dict(acquisition))
        info["acquisition"] = acquisition
        if sentence:
            info["error"] = sentence
    except Exception:  # noqa: BLE001 — enrichment must never lose the failure
        return {"stage": stage, "error": error, "paper_id": paper_id}
    return info


def _persist_parser_sections(paper_id: str, parsed) -> list | None:
    """Persist parser-provided (docling) sections via the store, matching the
    sections.py payload shape so downstream ``build_and_save_sections`` treats
    them as a cache hit (keyed on the text SHA) instead of rebuilding heuristically.

    Returns the list of Section objects, or None when nothing usable was
    persisted (caller then falls back to the heuristic sectioner).
    """
    import hashlib
    from dataclasses import asdict

    from research_companion import store
    from research_companion.sections import Section

    try:
        secs = [Section(**s) for s in parsed.sections]
    except (TypeError, ValueError):
        return None
    if not secs:
        return None

    text_sha = hashlib.sha256(parsed.text.encode()).hexdigest()
    store.save_sections(paper_id, {
        "version": 1,
        "text_sha256": text_sha,
        "method": "docling",
        "sections": [asdict(s) for s in secs],
    })
    return secs


def _persist_structure(paper_id: str, parsed) -> None:
    """Best-effort persistence of parser-derived tables/figures. Never raises."""
    try:
        from research_companion import store
        tables = getattr(parsed, "tables", None) or []
        figures = getattr(parsed, "figures", None) or []
        if tables or figures:
            store.save_structure(paper_id, {"tables": tables, "figures": figures})
    except Exception:
        pass


async def ingest_one(
    meta,
    path_str: str,
    *,
    bus,
    provider: str,
    model: str | None,
    align: bool,
    aligner,
    strengther,
    extractor,
    sectioner,
    embedder=_UNSET,
) -> bool:
    """Run the full pipeline for a single paper (stages 2–7).

    Assumes Stage 1 (add_pdf) has already been called and *meta* is the resulting
    PaperMetadata.  *path_str* is the string path used as the failure-record key.

    Returns True if the paper was successfully processed (added), False if a fatal
    stage (sections / extract / graph) failed.

    Publishes:
      - SectionTreeBuilt, SectionExtracted  (stage 2)
      - SectionExtracted per section        (stage 3)
      - GraphDelta                          (stage 4, under _GRAPH_LOCK)
      - AlignmentReady or IngestFailed      (stage 5, non-fatal)
      - StrengthUpdated or IngestFailed     (stage 6, non-fatal)
      - EmbeddingsReady or IngestFailed     (stage 7, non-fatal)
      - clear_failure on success            (stage 8)
    """
    from research_companion import graph as _graph
    from research_companion import store
    from research_companion.extract import get_paper_parsed, ocr_fallback_parse
    from research_companion.parsers import ParserError, text_quality
    from research_companion.sections import group_extraction_by_section

    paper_id = meta.paper_id

    # -----------------------------------------------------------------------
    # Stage 2: text + sections
    # -----------------------------------------------------------------------
    try:
        parsed = await asyncio.to_thread(get_paper_parsed, meta)
        # Honesty gate: empty/degenerate text (scanned/image-only PDF) must not
        # silently proceed to `done` with an empty text.txt. Before failing, try
        # a forced full-page OCR fallback — this recovers text from image-only
        # scans (docling default OCR does not). It is slow, so it only runs on
        # this failure path; digital PDFs that pass the gate never pay the cost.
        ocr_used = False
        if not text_quality(parsed.text)["ok"]:
            await bus.publish(IngestProgress(done=0, total=0, current="OCR-ing scanned PDF (may take a few minutes)…"))
            ocr_parsed = await asyncio.to_thread(ocr_fallback_parse, meta)
            if ocr_parsed is not None and text_quality(ocr_parsed.text)["ok"]:
                parsed = ocr_parsed  # OCR recovered usable text -> continue as success
                ocr_used = True
            else:
                # ocr_parsed is None -> docling not installed (advise install);
                # otherwise OCR ran but still failed (corrupt/text-free PDF).
                error = OCR_FAILED_ERROR if ocr_parsed is not None else EMPTY_TEXT_ERROR
                store.record_failure(path_str, {"stage": "extract", "error": error,
                                                "paper_id": paper_id})
                await bus.publish(IngestFailed(path=path_str, stage="extract",
                                               error=error, paper_id=paper_id))
                return False
        # Record how the text was produced (ingestion transparency). Never
        # DOWNGRADE a prior OCR flag: a re-ingest of an already-OCR'd paper hits
        # the cached-text path (the parser does not re-run), so overwriting here
        # would wrongly clear ocr_used and drop the OCR badge even though the
        # on-disk text is still the OCR-recovered text.
        if ocr_used:
            meta.parse_source = "docling+ocr"
            meta.ocr_used = True
            meta.save()
        elif not getattr(meta, "ocr_used", False):
            from research_companion.parsers import get_parser
            # Honor the actual parser recorded by get_paper_parsed (it may have
            # fallen back from docling to pypdfium on a truncated layout parse).
            meta.parse_source = (parsed.meta or {}).get("parse_source") or get_parser().name
            meta.ocr_used = False
            meta.save()
        # Prefer parser-provided (docling) structural sections; fall back to the
        # heuristic sectioner when the parser recovered none.
        paper_sections = None
        if parsed.sections:
            paper_sections = await asyncio.to_thread(_persist_parser_sections, paper_id, parsed)
        if paper_sections is None:
            paper_sections = await asyncio.to_thread(sectioner, paper_id)
        # Persist parser-derived tables/figures best-effort (never fatal).
        await asyncio.to_thread(_persist_structure, paper_id, parsed)
        await bus.publish(SectionTreeBuilt(
            paper_id=paper_id,
            n_sections=len(paper_sections),
        ))
    except ParserError as exc:
        # docling convert failure -> a text/parse extraction failure, not a
        # sectioning failure; consistent with the empty-text gate above.
        info = _acquisition_failure(paper_id, "extract",
                                    f"Failed to parse the PDF ({exc})")
        store.record_failure(path_str, info)
        await bus.publish(IngestFailed(path=path_str, stage="extract",
                                       error=info["error"], paper_id=paper_id))
        return False
    except Exception as exc:
        # The missing-PDF FileNotFoundError from extract.py arrives here.
        info = _acquisition_failure(paper_id, "sections", str(exc))
        store.record_failure(path_str, info)
        await bus.publish(IngestFailed(path=path_str, stage="sections",
                                       error=info["error"], paper_id=paper_id))
        return False

    # -----------------------------------------------------------------------
    # Stage 3: extract
    # -----------------------------------------------------------------------
    try:
        extraction, _usage = await asyncio.to_thread(
            extractor, meta, provider=provider, model=model
        )
        # Group extraction by section and publish SectionExtracted for each
        # non-boilerplate section with any entities (only non-zero keys)
        try:
            from research_companion.sections import is_boilerplate
            grouped = group_extraction_by_section(extraction, paper_sections)
            for sec in paper_sections:
                if is_boilerplate(sec.title):
                    continue
                sec_data = grouped.get(sec.section_id, {})
                counts = {
                    k: len(v)
                    for k, v in sec_data.items()
                    if isinstance(v, list) and len(v) > 0
                }
                if counts:
                    await bus.publish(SectionExtracted(
                        paper_id=paper_id,
                        section_id=sec.section_id,
                        title=sec.title,
                        counts=counts,
                    ))
        except Exception:
            # Section grouping is best-effort; don't abort on failure
            pass
    except Exception as exc:
        error_str = str(exc)
        store.record_failure(path_str, {"stage": "extract", "error": error_str, "paper_id": paper_id})
        await bus.publish(IngestFailed(path=path_str, stage="extract", error=error_str, paper_id=paper_id))
        return False

    # -----------------------------------------------------------------------
    # Stage 4: graph delta (serialized under lock)
    # -----------------------------------------------------------------------
    try:
        async with _GRAPH_LOCK:
            old_g = await asyncio.to_thread(_graph.load_graph)
            new_g = await asyncio.to_thread(_graph.build_graph)
            delta = _graph.graph_delta(old_g, new_g)
            await asyncio.to_thread(_graph.save_graph, new_g)
        await bus.publish(GraphDelta(
            paper_id=paper_id,
            nodes_added=delta["nodes_added"],
            edges_added=delta["edges_added"],
        ))
    except Exception as exc:
        error_str = str(exc)
        store.record_failure(path_str, {"stage": "graph", "error": error_str, "paper_id": paper_id})
        await bus.publish(IngestFailed(path=path_str, stage="graph", error=error_str, paper_id=paper_id))
        return False

    # -----------------------------------------------------------------------
    # Stage 5: alignment (optional)
    # -----------------------------------------------------------------------
    if align and aligner is not None:
        draft_id = store.get_draft_paper_id()
        if draft_id is not None and paper_id != draft_id:
            try:
                # Build LLM callable lazily only when needed
                _llm = _build_llm_callable(provider, model)
                align_payload = await asyncio.to_thread(
                    aligner,
                    draft_id,
                    paper_id,
                    llm=_llm,
                )
                await bus.publish(AlignmentReady(
                    paper_id=paper_id,
                    draft_paper_id=draft_id,
                    verdict=align_payload.get("verdict", ""),
                    score=align_payload.get("score", 0.0),
                ))
            except Exception as exc:
                # Alignment failures are non-fatal; publish IngestFailed but do NOT
                # record_failure and do NOT count the file as failed.
                await bus.publish(IngestFailed(
                    path=path_str,
                    stage="align",
                    error=str(exc),
                    paper_id=paper_id,
                ))

    # -----------------------------------------------------------------------
    # Stage 6: strength (optional)
    # -----------------------------------------------------------------------
    if strengther is not None:
        try:
            strength_payload = await asyncio.to_thread(strengther, paper_id)
            await bus.publish(StrengthUpdated(
                paper_id=paper_id,
                score=strength_payload.get("score"),
                band=strength_payload.get("band", ""),
                color=strength_payload.get("color", ""),
            ))
        except Exception as exc:
            # Strength failures are non-fatal; publish IngestFailed but do NOT
            # record_failure and do NOT count the file as failed.
            await bus.publish(IngestFailed(
                path=path_str,
                stage="strength",
                error=str(exc),
                paper_id=paper_id,
            ))

    # -----------------------------------------------------------------------
    # Stage 7: embed (optional, non-fatal)
    # -----------------------------------------------------------------------
    _embedder_resolved = _default_embedder() if embedder is _UNSET else embedder
    if _embedder_resolved is not None:
        try:
            embed_payload = await asyncio.to_thread(_embedder_resolved, paper_id)
            if embed_payload is not None:
                vectors = embed_payload.get("vectors", {})
                await bus.publish(EmbeddingsReady(
                    paper_id=paper_id,
                    n_vectors=len(vectors),
                ))
            # else: no token / no-op — publish nothing, continue silently
        except Exception as exc:
            # Embed failures are non-fatal; publish IngestFailed but do NOT
            # record_failure and do NOT count the file as failed.
            await bus.publish(IngestFailed(
                path=path_str,
                stage="embed",
                error=str(exc),
                paper_id=paper_id,
            ))

    # -----------------------------------------------------------------------
    # Stage 8: clear failure, signal success
    # -----------------------------------------------------------------------
    store.clear_failure(path_str, paper_id=paper_id)
    return True


async def ingest_folder(
    folder,
    *,
    bus,
    paths: list[str] | None = None,
    add_pdf=None,
    extractor=None,
    sectioner=None,
    aligner=_UNSET,
    strengther=_UNSET,
    embedder=_UNSET,
    suggester=_UNSET,
    provider: str = "anthropic",
    model: str | None = None,
    align: bool = True,
) -> IngestResult:
    """Ingest all PDFs in *folder* through the full pipeline, publishing events on *bus*.

    All seams are injectable (tests inject fakes for all of them).
    Failures are per-stage: record_failure, publish IngestFailed, continue.

    *paths*: when given, ingest exactly these paths instead of scanning the
    folder; caller must have validated they are real PDFs in the folder.

    Returns IngestResult with lists of added, skipped, and failed paper path strings.
    """
    from research_companion import store

    # Resolve seam defaults
    if add_pdf is None:
        from research_companion.fetch import add_local_pdf
        add_pdf = add_local_pdf

    if extractor is None:
        from research_companion.extract import extract_paper
        extractor = extract_paper

    if sectioner is None:
        from research_companion.sections import build_and_save_sections
        sectioner = build_and_save_sections

    # aligner: sentinel _UNSET -> try real default; None -> explicitly skip
    _aligner_resolved = _default_aligner() if aligner is _UNSET else aligner  # None or a callable

    # strengther: sentinel _UNSET -> try real default; None -> explicitly skip
    _strengther_resolved = _default_strengther() if strengther is _UNSET else strengther

    # embedder: sentinel _UNSET -> try real default; None -> explicitly skip
    _embedder_resolved = _default_embedder() if embedder is _UNSET else embedder

    # suggester: sentinel _UNSET -> try real default; None -> explicitly skip
    def _default_suggester():
        try:
            from research_companion.suggestions import generate_suggestions
            return generate_suggestions
        except ImportError:
            return None
    _suggester_resolved = _default_suggester() if suggester is _UNSET else suggester

    pdfs = [Path(p) for p in paths] if paths is not None else scan_pdfs(Path(folder))
    total = len(pdfs)
    result = IngestResult()

    for done_count, pdf_path in enumerate(pdfs):
        path_str = str(pdf_path)

        # Publish progress before each file
        await bus.publish(IngestProgress(done=done_count, total=total, current=path_str))

        paper_id: str = ""

        # -----------------------------------------------------------------------
        # Stage 1: add_pdf
        # -----------------------------------------------------------------------
        try:
            meta = await asyncio.to_thread(add_pdf, pdf_path)
        except Exception as exc:
            error_str = str(exc)
            store.record_failure(path_str, {"stage": "add", "error": error_str})
            await bus.publish(IngestFailed(path=path_str, stage="add", error=error_str))
            result.failed.append({"path": path_str, "stage": "add", "error": error_str})
            continue

        paper_id = meta.paper_id

        # Determine skip: paper already existed AND extraction is cached
        from research_companion.prompts import extraction_prompt_sha256
        prompt_sha = extraction_prompt_sha256()
        cached_ext = store.load_extraction(paper_id, prompt_sha=prompt_sha)

        # Check if this was a fresh add or an existing one.
        # add_local_pdf returns the existing meta if already present — we detect
        # by checking extraction cache. If cached, count as skipped.
        if cached_ext is not None:
            await bus.publish(IngestSkipped(
                path=path_str, paper_id=paper_id, reason="already in library"))
            result.skipped.append(path_str)
            continue

        # Publish PaperAdded for genuinely new (or extraction-missing) papers
        await bus.publish(PaperAdded(
            paper_id=paper_id,
            title=meta.title,
            source=meta.source_url,
            path=path_str,
        ))

        # -----------------------------------------------------------------------
        # Stages 2–7: run shared pipeline
        # -----------------------------------------------------------------------
        ok = await ingest_one(
            meta,
            path_str,
            bus=bus,
            provider=provider,
            model=model,
            align=align,
            aligner=_aligner_resolved,
            strengther=_strengther_resolved,
            extractor=extractor,
            sectioner=sectioner,
            embedder=_embedder_resolved,
        )

        if ok:
            result.added.append(path_str)
        else:
            result.failed.append({"path": path_str, "stage": "pipeline", "error": "pipeline stage failed"})

    # -----------------------------------------------------------------------
    # Post-loop: suggestions auto-regen (once per ingest run, non-fatal)
    # -----------------------------------------------------------------------
    draft_id = store.get_draft_paper_id()
    if draft_id is not None and _suggester_resolved is not None:
        try:
            updated_payload = await asyncio.to_thread(
                _suggester_resolved,
                draft_id=draft_id,
            )
            sugs = updated_payload.get("suggestions", [])
            await bus.publish(SuggestionsUpdated(
                draft_paper_id=draft_id,
                open=sum(1 for s in sugs if s.get("status") == "open"),
                addressed=sum(1 for s in sugs if s.get("status") == "addressed"),
                dismissed=sum(1 for s in sugs if s.get("status") == "dismissed"),
            ))
        except Exception:
            pass

    # Final progress and done signal
    await bus.publish(IngestProgress(done=total, total=total))
    await bus.publish(JobDone(job="ingest"))

    return result
