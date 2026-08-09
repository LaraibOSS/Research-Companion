"""Local persistence for research_companion.

Layout under RESEARCH_COMPANION_DIR (default: ~/.research-companion/):

    papers/
        arxiv__2410_05779/
            metadata.json     # title, authors, year, abstract, source URL
            paper.pdf         # downloaded source
            text.txt          # extracted plain text (cached)
            extraction.json   # LLM-extracted entities (cached, keyed on prompt sha256)
        local__a1b2c3d4/
            ...
        doi__10_1145_1234567_1234568/
            ...
        s2__abc123.../
            ...
    graph.json                # merged cross-paper graph (NetworkX node-link)
    graph.html                # rendered interactive viz

Paper IDs:
    arXiv papers:    "arxiv:2410.05779"           -> dir "arxiv__2410_05779"
    Local PDFs:      "local:<sha256[:12]>"        -> dir "local__<sha256[:12]>"
    DOI papers:      "doi:10.1145/1234567"        -> dir "doi__10_1145_1234567"
    S2 papers:       "s2:<40-char hex>"           -> dir "s2__<40-char hex>"
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def root_dir() -> Path:
    """Root directory for research-companion state. Override with $RESEARCH_COMPANION_DIR.

    The root holds GLOBAL state (.env secrets, settings.json, the workspace
    registry); everything research-specific lives under workspaces/<id>/.
    """
    custom = os.environ.get("RESEARCH_COMPANION_DIR")
    if custom:
        return Path(custom)
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    return home / ".research-companion"


# ---------------------------------------------------------------------------
# Workspaces: registry, active-workspace resolution, legacy migration
# ---------------------------------------------------------------------------

_DEFAULT_WORKSPACE = "main"

# Per-process caches: roots whose migration state has been verified, and the
# (registry mtime_ns -> active id) resolution cache.
_verified_roots: set[str] = set()
_active_cache: dict[str, tuple[int, str]] = {}


def _reset_workspace_caches() -> None:
    """Invalidate per-process workspace caches (tests + in-process activation)."""
    _verified_roots.clear()
    _active_cache.clear()


def workspaces_root() -> Path:
    return root_dir() / "workspaces"


def registry_path() -> Path:
    return root_dir() / "workspaces.json"


def _default_registry() -> dict:
    return {
        "version": 2,
        "active": None,
        "workspaces": [],
    }


# Reentrancy flag: _migrate_legacy_store itself calls save_registry/
# save_root_settings — those must not re-trigger migration.
_migrating = False


def _default_main_is_empty() -> bool:
    """True when the legacy default 'main' workspace has no papers and no draft.

    Direct filesystem checks only (no import of workspaces.py — that module
    imports store, so importing it back here would be circular).
    """
    base = workspaces_root() / _DEFAULT_WORKSPACE
    papers = base / "papers"
    try:
        has_paper = papers.is_dir() and any(
            d.is_dir() and (d / "metadata.json").exists() for d in papers.iterdir())
    except OSError:
        has_paper = False
    if has_paper:
        return False
    cfg = base / "config.json"
    try:
        c = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
        return not (isinstance(c, dict) and c.get("draft_paper_id"))
    except (json.JSONDecodeError, OSError):
        return True


def load_registry() -> dict:
    """Load the workspace registry; synthesize the empty default when missing/corrupt.

    Ensures legacy migration has run FIRST: writing the registry before a
    pre-0.4 store migrates would make _needs_migration() False forever and
    orphan the library (final-review Critical).

    Also runs a TRUE one-time migration, gated on registry version (< 2),
    that normalizes a still-default-named "main" record (name == "Main")
    left over from a pre-0.4 store now that main is an ordinary workspace,
    not the special default:

      * EMPTY (no papers, no draft) -> the record is DROPPED from the
        registry (an upgrader with nothing in their default workspace lands
        on "Research: none", same as a fresh install). If it was active,
        `active` is set to None. No directory is deleted — only the
        registry entry goes.
      * Has data -> relabeled to "My research" (no data loss, no directory
        moves).

    This must NOT key on name-equality alone forever: a user who creates a
    brand-new workspace and happens to name it "Main" post-upgrade must
    never have it silently removed just because it is momentarily empty.
    The version gate is what prevents that — a registry written by this
    (or any later) code is already version 2, so the migration block never
    runs against it again, full stop, regardless of what workspaces it
    contains. Only a genuinely old (version < 2, including version-less)
    registry — i.e. one this code has not yet touched — gets the one-time
    pass. After running it (even when it is a no-op, e.g. no legacy "main"
    present), `version` is bumped to 2 and saved so it can never run again
    on that registry.
    """
    if not _migrating:
        _ensure_root_ready(root_dir())
    p = registry_path()
    if not p.exists():
        return _default_registry()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("workspaces"), list):
            return _default_registry()
        data.setdefault("version", 1)
        data.setdefault("active", None)
    except (json.JSONDecodeError, OSError):
        return _default_registry()

    if data.get("version", 1) < 2:
        kept: list[dict] = []
        for rec in data["workspaces"]:
            if rec.get("id") == _DEFAULT_WORKSPACE and rec.get("name") == "Main":
                if _default_main_is_empty():
                    if data.get("active") == _DEFAULT_WORKSPACE:
                        data["active"] = None
                    continue  # drop: do not keep this record
                rec["name"] = "My research"
            kept.append(rec)
        data["workspaces"] = kept
        data["version"] = 2
        if not _migrating:
            save_registry(data)
    return data


def save_registry(reg: dict) -> None:
    """Atomic write (tmp + os.replace); invalidates the resolution cache.

    Runs legacy migration first (see load_registry) — the registry file
    doubles as the migration-done marker.
    """
    if not _migrating:
        _ensure_root_ready(root_dir())
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    _active_cache.pop(str(root_dir()), None)


def _slugify_workspace(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:64]


def active_workspace_id() -> str | None:
    """$RESEARCH_COMPANION_WORKSPACE > registry active > None.

    Registry reads are cached keyed on the file's mtime_ns so external
    `workspace use` invocations are picked up by long-lived processes.
    """
    env_ws = os.environ.get("RESEARCH_COMPANION_WORKSPACE", "").strip()
    if env_ws:
        return _slugify_workspace(env_ws) or None

    root_key = str(root_dir())
    p = registry_path()
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return None
    cached = _active_cache.get(root_key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    active = load_registry().get("active")
    active = str(active) if active else None
    _active_cache[root_key] = (mtime, active)
    return active


# Per-workspace artifacts moved by the legacy migration, papers/ LAST so the
# migration predicate stays true until everything else is across.
_MIGRATE_ENTRIES = (
    "graph.json", "graph.html", "failed.json", "gap_resolution.json",
    "saved_views.json", "journey.json", "qa_log.jsonl", "lab_events.jsonl",
    "reviews", "suggestions", "conversations", "runs", "papers",
)


def _needs_migration(root: Path) -> bool:
    if registry_path().exists():
        return False
    return any((root / entry).exists() for entry in ("papers", "graph.json", "config.json"))


def _migrate_legacy_store(root: Path) -> None:
    """Move a pre-0.4 store (artifacts at root) into workspaces/main/.

    Crash-safe: every step skips if already done; the trigger predicate stays
    true while any legacy artifact remains, so an interrupted run resumes on
    the next resolution. The registry write is the completion marker (and a
    crash after all moves but before the write self-heals: load_registry
    synthesizes the default). `.env` never moves.
    """
    ws = root / "workspaces" / _DEFAULT_WORKSPACE
    ws.mkdir(parents=True, exist_ok=True)

    # Split config.json: settings -> root/settings.json, remainder -> workspace
    legacy_cfg = root / "config.json"
    if legacy_cfg.exists():
        cfg = None
        try:
            cfg = json.loads(legacy_cfg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cfg = None
        if isinstance(cfg, dict):
            settings = cfg.pop("settings", None)
            if isinstance(settings, dict) and settings and not (root / "settings.json").exists():
                save_root_settings(settings)
            (ws / "config.json").write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            # Corrupt / non-dict config: preserve the original bytes for hand
            # recovery instead of silently destroying them.
            import contextlib
            with contextlib.suppress(OSError):
                (ws / "config.json.bak").write_bytes(legacy_cfg.read_bytes())
        legacy_cfg.unlink()

    for entry in _MIGRATE_ENTRIES:
        src = root / entry
        dst = ws / entry
        if not src.exists() or dst.exists():
            continue
        os.rename(src, dst)

    from datetime import datetime, timezone
    reg = {
        "version": 1,
        "active": _DEFAULT_WORKSPACE,
        "workspaces": [{
            "id": _DEFAULT_WORKSPACE,
            "name": "Main",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "archived": False,
        }],
    }
    save_registry(reg)


def _ensure_root_ready(root: Path) -> None:
    global _migrating
    key = str(root)
    if key in _verified_roots:
        return
    if _needs_migration(root):
        _migrating = True
        try:
            _migrate_legacy_store(root)
        finally:
            _migrating = False
    _verified_roots.add(key)


def papergraph_dir() -> Path | None:
    """Directory of the ACTIVE workspace, or None when none is active.

    All research state lives here when it is not None.
    """
    root = root_dir()
    _ensure_root_ready(root)
    ws = active_workspace_id()
    if ws is None:
        return None
    return workspaces_root() / ws


def workspace_path(*parts: str) -> Path | None:
    """Join *parts onto the active workspace's directory, or None when none
    is active.

    The single guarded join point every per-workspace path helper (in this
    module and in journey.py, notes_store.py, views.py, converse.py) routes
    through instead of calling papergraph_dir() directly, so "no active
    workspace" degrades to "this path does not exist" instead of crashing on
    `None / "x"`.
    """
    base = papergraph_dir()
    return None if base is None else base.joinpath(*parts)


# ---------------------------------------------------------------------------
# Global (root-level) settings
# ---------------------------------------------------------------------------

def root_settings_path() -> Path:
    return root_dir() / "settings.json"


def load_root_settings() -> dict:
    p = root_settings_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_root_settings(settings: dict) -> None:
    p = root_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def papers_dir() -> Path | None:
    d = workspace_path("papers")
    if d is None:
        return None
    d.mkdir(parents=True, exist_ok=True)
    return d


def graph_json_path() -> Path | None:
    return workspace_path("graph.json")


def graph_html_path() -> Path | None:
    return workspace_path("graph.html")


def _id_to_dirname(paper_id: str) -> str:
    """Convert paper ID to filesystem-safe directory name.

    "arxiv:2410.05779"     -> "arxiv__2410_05779"
    "local:a1b2c3d4e5f6"   -> "local__a1b2c3d4e5f6"
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", paper_id.replace(":", "__"))


def paper_dir(paper_id: str) -> Path | None:
    base = papers_dir()
    if base is None:
        return None
    d = base / _id_to_dirname(paper_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_local_id(pdf_bytes: bytes) -> str:
    """Stable local-PDF ID derived from content hash."""
    return f"local:{hashlib.sha256(pdf_bytes).hexdigest()[:12]}"


def make_arxiv_id(arxiv_id: str) -> str:
    """Normalize an arXiv ID like '2410.05779' or '2410.05779v3' to 'arxiv:2410.05779'."""
    # Strip version suffix if present.
    base = re.sub(r"v\d+$", "", arxiv_id.strip())
    return f"arxiv:{base}"


def make_doi_id(doi: str) -> str:
    """Create a paper ID from a DOI string, e.g. 'doi:10.1145/1234567.1234568'."""
    return f"doi:{doi.strip()}"


def make_s2_id(s2_id: str) -> str:
    """Create a paper ID from a Semantic Scholar paper ID, e.g. 's2:<hex>'."""
    return f"s2:{s2_id.strip()}"


def make_pmid_id(pmid: str) -> str:
    """Create a paper ID from a PubMed id, e.g. 'pmid:30449619'."""
    return f"pmid:{str(pmid).strip()}"


def make_pmcid_id(pmcid: str) -> str:
    """Create a paper ID from a PMC id, e.g. 'pmcid:PMC6289601'."""
    p = pmcid.strip().upper()
    return f"pmcid:{p if p.startswith('PMC') else 'PMC' + p}"


# arXiv id (new-style YYMM.NNNNN) / DOI embedded in a filename — folder exports
# are commonly named like "author2025_title_arXiv-2501.13956.pdf".
_ARXIV_IN_NAME_RE = re.compile(r"\b(\d{4}\.\d{4,5})\b")
_DOI_IN_NAME_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", re.IGNORECASE)


def find_existing_paper_for(pdf_bytes: bytes, *, filename: str | None = None) -> str | None:
    """Return the id of a library paper that is the SAME work as this PDF, else None.

    Cross-namespace dedup so the same paper added via arXiv/DOI and again as a
    local PDF isn't duplicated. Checks, cheapest first:
      1. exact content id (``local:<hash>``) already in the library;
      2. an arXiv id / DOI found in *filename* that matches an existing paper;
      3. a byte-identical stored PDF among non-local papers (arXiv/DOI/S2) —
         local papers are keyed by content hash, so step 1 already covers them.
    Never creates directories (unlike ``paper_dir``)."""
    def _dir(pid: str) -> Path:
        return papers_dir() / _id_to_dirname(pid)

    target = make_local_id(pdf_bytes)
    tdir = _dir(target)
    if (tdir / "metadata.json").exists() and (tdir / "paper.pdf").exists():
        return target

    if filename:
        name = str(filename)
        for m in _ARXIV_IN_NAME_RE.finditer(name):
            cand = make_arxiv_id(m.group(1))
            if (_dir(cand) / "metadata.json").exists():
                return cand
        for m in _DOI_IN_NAME_RE.finditer(name):
            cand = make_doi_id(m.group(1))
            if (_dir(cand) / "metadata.json").exists():
                return cand

    for p in list_papers():
        if p.paper_id.startswith("local:"):
            continue  # id IS the content hash — step 1 already handled it
        pdf = _dir(p.paper_id) / "paper.pdf"
        try:
            if pdf.exists() and make_local_id(pdf.read_bytes()) == target:
                return p.paper_id
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# Paper metadata + extraction records
# ---------------------------------------------------------------------------

@dataclass
class PaperMetadata:
    paper_id: str
    title: str
    authors: list[str]
    year: int | None = None
    abstract: str = ""
    source_url: str = ""
    arxiv_categories: list[str] = field(default_factory=list)
    added_at: str = ""
    parse_source: str = ""   # which parser produced the stored text: "pypdfium" | "docling" | "docling+ocr"
    ocr_used: bool = False    # True when the forced-full-page-OCR fallback recovered the text
    pmid: str | None = None
    pmcid: str | None = None
    full_text_available: bool = False

    def save(self) -> None:
        p = paper_dir(self.paper_id) / "metadata.json"
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, paper_id: str) -> PaperMetadata | None:
        d = paper_dir(paper_id)
        if d is None:
            return None
        p = d / "metadata.json"
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(**data)


class _Unset:
    """Sentinel type for 'argument omitted', distinct from an explicit None."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "<UNSET>"


# Module-level sentinel: lets update_paper_metadata tell "field not passed"
# (leave unchanged) apart from "field passed as None" (e.g. clear the year).
_UNSET: Any = _Unset()


def update_paper_metadata(
    paper_id: str,
    *,
    title: Any = _UNSET,
    authors: Any = _UNSET,
    year: Any = _UNSET,
) -> PaperMetadata | None:
    """Manually correct a paper's title/authors/year. Returns the updated
    metadata, or None if the paper does not exist.

    Sentinel semantics (via module-level _UNSET): an omitted field is left
    unchanged; a passed field is applied. This is what lets a caller CLEAR the
    year with ``year=None`` while ``update_paper_metadata(pid)`` (year omitted)
    leaves it. title/authors use the same sentinel for consistency, but an
    explicit ``title=None``/``authors=None`` is treated as "leave unchanged"
    (title is required; use ``authors=[]`` to clear authors). Year-RANGE
    validation is the caller/endpoint's job.
    """
    meta = PaperMetadata.load(paper_id)
    if meta is None:
        return None
    if title is not _UNSET and title is not None:
        meta.title = title.strip() or meta.title
    if authors is not _UNSET and authors is not None:
        meta.authors = [a.strip() for a in authors if a and a.strip()]
    if year is not _UNSET:
        meta.year = year  # None clears; int stored as-is
    meta.save()
    return meta


def save_pdf(paper_id: str, pdf_bytes: bytes) -> Path:
    p = paper_dir(paper_id) / "paper.pdf"
    p.write_bytes(pdf_bytes)
    return p


def pdf_path(paper_id: str) -> Path | None:
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "paper.pdf"
    return p if p.exists() else None


def pdf_page_count(paper_id: str) -> int | None:
    """Number of pages in the stored PDF, or None when there is no PDF or it
    cannot be opened. Never raises (used by the best-effort compliance lane)."""
    p = pdf_path(paper_id)
    if p is None:
        return None
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(p))
        try:
            return len(pdf)
        finally:
            pdf.close()
    except Exception:
        return None


def save_text(paper_id: str, text: str) -> Path:
    p = paper_dir(paper_id) / "text.txt"
    p.write_text(text, encoding="utf-8")
    return p


def load_text(paper_id: str) -> str | None:
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "text.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


def save_extraction(paper_id: str, extraction: dict[str, Any], *, prompt_sha: str) -> Path:
    """Save extraction keyed on the prompt SHA so prompt changes invalidate cache."""
    payload = {"prompt_sha256": prompt_sha, "extraction": extraction}
    p = paper_dir(paper_id) / "extraction.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_extraction(paper_id: str, *, prompt_sha: str) -> dict[str, Any] | None:
    """Return cached extraction iff the saved prompt SHA matches the current one."""
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "extraction.json"
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        # Corrupt/legacy file: treat as a cache miss rather than aborting the
        # caller (build_graph iterates every paper — one bad file must not fail
        # an unrelated draft's ingest in a migrated 'Main').
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("prompt_sha256") != prompt_sha:
        return None
    return payload.get("extraction")


def save_simplified(paper_id: str, payload: dict) -> Path:
    """Save the LLM 'Simplify further' rewrite to papers/<dir>/simplified.json.
    Display-only comprehension aid — never read by Ask/Draft/analysis paths."""
    p = paper_dir(paper_id) / "simplified.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_simplified(paper_id: str) -> dict | None:
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "simplified.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def save_citation_polarity(paper_id: str, mapping: dict[str, Any]) -> Path:
    """Persist per-citation polarity for a paper, keyed by the raw related_work
    string. Consumed by build_graph to type cites edges."""
    p = paper_dir(paper_id) / "citation_polarity.json"
    p.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_citation_polarity(paper_id: str) -> dict[str, Any]:
    """Return the polarity mapping for a paper, or {} when absent/corrupt/no
    active workspace. Must never raise: build_graph iterates every paper, and
    one bad sidecar must not fail an unrelated paper's ingest (same
    discipline as load_extraction).
    """
    d = paper_dir(paper_id)
    if d is None:
        return {}
    p = d / "citation_polarity.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def list_papers() -> list[PaperMetadata]:
    """All papers currently in the local store, sorted by added_at desc.

    Returns [] when no research is active — never raises.
    """
    d = papers_dir()
    if d is None:
        return []
    out: list[PaperMetadata] = []
    for entry in d.iterdir():
        if not entry.is_dir():
            continue
        meta_path = entry / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            out.append(PaperMetadata(**data))
        except (json.JSONDecodeError, TypeError):
            continue
    # Tie-break equal added_at by paper_id so ordering never depends on
    # filesystem iteration order (sorted on NTFS, arbitrary on ext4).
    out.sort(key=lambda m: m.paper_id)
    out.sort(key=lambda m: m.added_at, reverse=True)
    return out


def _rmtree_retry(path: Path) -> None:
    """Delete a directory tree, retrying transient Windows sharing violations.

    Windows refuses to delete files another thread has momentarily open
    (WinError 32) — background coverage/stats reads race deletes — so retry
    briefly before giving up; the 5th PermissionError propagates.
    """
    import shutil
    import time as _time
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            _time.sleep(0.15 * (attempt + 1))


def remove_paper(paper_id: str) -> bool:
    """Delete a paper's directory. Returns True if removed, False if not present."""
    d = papers_dir() / _id_to_dirname(paper_id)
    if not d.exists():
        return False
    _rmtree_retry(d)
    return True


# ---------------------------------------------------------------------------
# Research Lab persistence: config, sections, alignment, strength, failures
# ---------------------------------------------------------------------------


def config_path() -> Path | None:
    """Return papergraph_dir()/config.json, or None when none is active."""
    return workspace_path("config.json")


def load_config() -> dict:
    """Load config.json. Returns {} if missing, unparseable, or no active workspace."""
    p = config_path()
    if p is None or not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    """Save config dict to config.json with indent=2, utf-8 encoding."""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def get_draft_paper_id() -> str | None:
    """Return draft_paper_id from config, or None if not set."""
    cfg = load_config()
    return cfg.get("draft_paper_id")


def set_draft_paper_id(paper_id: str | None) -> None:
    """Set or clear draft_paper_id in config."""
    cfg = load_config()
    if paper_id is None:
        cfg.pop("draft_paper_id", None)
    else:
        cfg["draft_paper_id"] = paper_id
    save_config(cfg)


def save_sections(paper_id: str, payload: dict) -> Path:
    """Save sections JSON to papers/<dir>/sections.json."""
    p = paper_dir(paper_id) / "sections.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_sections(paper_id: str, *, text_sha: str | None = None) -> dict | None:
    """Load sections from papers/<dir>/sections.json.

    Returns None if file missing, JSON unparseable, or if text_sha given and
    payload["text_sha256"] does not match (stale cache).
    """
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "sections.json"
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None

    if text_sha is not None and payload.get("text_sha256") != text_sha:
        return None

    return payload


def save_structure(paper_id: str, payload: dict) -> Path:
    """Save parser-derived structure (tables/figures) to papers/<dir>/structure.json.

    Small, additive artifact written best-effort by the ingest pipeline when a
    layout-aware parser (docling) recovers tables/figures. Not read back yet.
    """
    p = paper_dir(paper_id) / "structure.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_structure(paper_id: str) -> dict | None:
    """Load papers/<dir>/structure.json. Returns None if missing, unparseable,
    or no active workspace."""
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "structure.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def save_alignment(paper_id: str, payload: dict) -> Path:
    """Save alignment JSON to papers/<dir>/alignment.json."""
    p = paper_dir(paper_id) / "alignment.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_alignment(paper_id: str, *, draft_paper_id: str | None = None) -> dict | None:
    """Load alignment from papers/<dir>/alignment.json.

    Returns None if file missing, JSON unparseable, or if draft_paper_id given and
    payload["draft_paper_id"] does not match (stale cache).
    """
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "alignment.json"
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None

    if draft_paper_id is not None and payload.get("draft_paper_id") != draft_paper_id:
        return None

    return payload


def save_strength(paper_id: str, payload: dict) -> Path:
    """Save strength JSON to papers/<dir>/strength.json."""
    p = paper_dir(paper_id) / "strength.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_strength(paper_id: str) -> dict | None:
    """Load strength from papers/<dir>/strength.json.

    Returns None if file missing or JSON unparseable.
    """
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "strength.json"
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return payload
    except (json.JSONDecodeError, ValueError):
        return None


def embedding_key(section_id: str, chunk_index: int) -> str:
    """Composite vector-map key for one retrieval unit.

    Vectors are keyed per (section_id, chunk_index) so multi-chunk sections keep
    a distinct vector per chunk instead of collapsing to one (last chunk wins).
    Format defined once here and reused by embed/retrieve/store.
    """
    return f"{section_id}#{chunk_index}"


def save_embeddings(paper_id: str, payload: dict) -> Path:
    """Save embeddings JSON to papers/<dir>/embeddings.json.

    Payload shape::

        {
            "embed_model": str,
            "vectors": {
                "<section_id>#<chunk_index>": {"text_sha256": str, "vector": [floats]}
            }
        }

    Keys are the composite key from :func:`embedding_key`. Legacy files keyed by
    bare ``section_id`` still load, but composite lookups miss them (cache-miss).
    """
    p = paper_dir(paper_id) / "embeddings.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_embeddings(paper_id: str, *, embed_model: str | None = None) -> dict | None:
    """Load embeddings from papers/<dir>/embeddings.json.

    Returns None if:
    * The file is missing or unparseable.
    * *embed_model* is given and ``payload["embed_model"]`` does not match.
    """
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "embeddings.json"
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None

    if embed_model is not None and payload.get("embed_model") != embed_model:
        return None

    return payload


def failed_json_path() -> Path | None:
    """Return papergraph_dir()/failed.json, or None when none is active."""
    return workspace_path("failed.json")


def record_failure(key: str, info: dict) -> None:
    """Record or update a failure entry under key. Adds 'at' timestamp if absent."""
    failures = list_failures()

    # Add timestamp if not present
    if "at" not in info:
        from datetime import datetime, timezone
        info = dict(info)  # Don't mutate caller's dict
        info["at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    failures[key] = info

    p = failed_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_failure(key: str, *, paper_id: str | None = None) -> None:
    """Remove a failure entry by key. No-op if nothing matched.

    When ``paper_id`` is given, also drops any entry whose recorded ``paper_id``
    matches — a paper may have been recorded under a different key on an earlier
    attempt (e.g. a folder path vs. an ``upload://`` key), and failure lookups
    match by paper_id OR key, so a stale entry under the old key would otherwise
    keep pinning the paper to 'failed' after a successful re-ingest.
    """
    failures = list_failures()
    to_remove = {k for k in failures if k == key}
    if paper_id is not None:
        to_remove |= {
            k for k, info in failures.items()
            if isinstance(info, dict) and info.get("paper_id") == paper_id
        }
    if to_remove:
        for k in to_remove:
            del failures[k]
        p = failed_json_path()
        p.write_text(json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8")


def list_failures() -> dict[str, dict]:
    """Load and return all failures. Returns {} if file missing, unparseable,
    or no active workspace."""
    p = failed_json_path()
    if p is None or not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Review-report persistence
# ---------------------------------------------------------------------------


def review_report_path(paper_id: str) -> Path | None:
    """Return papergraph_dir()/reviews/<dirname>/report.json, or None when
    none is active."""
    dirname = _id_to_dirname(paper_id)
    return workspace_path("reviews", dirname, "report.json")


def save_review_report(paper_id: str, report: dict) -> Path:
    """Save a review report dict to the reviews store. Returns the saved path."""
    p = review_report_path(paper_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_review_report(paper_id: str) -> dict | None:
    """Load a saved review report. Returns None if missing, corrupt, or no
    active workspace."""
    p = review_report_path(paper_id)
    if p is None or not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Gap persistence (gaps.py / gaps engine)
# ---------------------------------------------------------------------------


def save_gaps(paper_id: str, payload: dict, *, prompt_sha: str | None = None) -> Path:
    """Save gaps JSON to papers/<dir>/gaps.json.

    The payload is expected to include "prompt_sha256" already, but *prompt_sha*
    can be provided as a convenience to set/override it before writing.
    """
    if prompt_sha is not None:
        payload = dict(payload)
        payload["prompt_sha256"] = prompt_sha
    p = paper_dir(paper_id) / "gaps.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_gaps(paper_id: str, *, prompt_sha: str | None = None) -> dict | None:
    """Load gaps from papers/<dir>/gaps.json.

    Returns None if file missing, JSON unparseable, or if prompt_sha given and
    payload["prompt_sha256"] does not match (stale cache).
    """
    d = paper_dir(paper_id)
    if d is None:
        return None
    p = d / "gaps.json"
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    if prompt_sha is not None and payload.get("prompt_sha256") != prompt_sha:
        return None

    return payload


def gap_resolution_path() -> Path | None:
    """Return papergraph_dir()/gap_resolution.json, or None when none is active."""
    return workspace_path("gap_resolution.json")


def save_gap_resolution(payload: dict) -> Path:
    """Save store-level gap resolution to gap_resolution.json."""
    p = gap_resolution_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_gap_resolution() -> dict | None:
    """Load gap_resolution.json. Returns None if missing, unparseable, or no
    active workspace."""
    p = gap_resolution_path()
    if p is None or not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def gap_synthesis_path() -> Path | None:
    """Return papergraph_dir()/gap_synthesis.json, or None when none is active."""
    return workspace_path("gap_synthesis.json")


def save_gap_synthesis(payload: dict) -> Path:
    """Save store-level gap-theme synthesis to gap_synthesis.json.

    Mirrors save_gap_resolution: the caller embeds whatever staleness-key sha
    fields it wants (gap_prompt_sha256, resolution_prompt_sha256,
    papers_sha256, synthesis_prompt_sha256) in *payload*; this function writes
    it as-is.
    """
    p = gap_synthesis_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_gap_synthesis() -> dict | None:
    """Load gap_synthesis.json. Returns None if missing, unparseable, not a
    dict, or no active workspace. Staleness (sha comparison against current
    gap/resolution/papers/synthesis-prompt shas) is the caller's job, exactly
    like load_gap_resolution."""
    p = gap_synthesis_path()
    if p is None or not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
