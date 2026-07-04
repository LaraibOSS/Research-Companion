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


def papergraph_dir() -> Path:
    """Root directory for research-companion state. Override with $RESEARCH_COMPANION_DIR."""
    custom = os.environ.get("RESEARCH_COMPANION_DIR")
    if custom:
        return Path(custom)
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    return home / ".research-companion"


def papers_dir() -> Path:
    d = papergraph_dir() / "papers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def graph_json_path() -> Path:
    return papergraph_dir() / "graph.json"


def graph_html_path() -> Path:
    return papergraph_dir() / "graph.html"


def _id_to_dirname(paper_id: str) -> str:
    """Convert paper ID to filesystem-safe directory name.

    "arxiv:2410.05779"     -> "arxiv__2410_05779"
    "local:a1b2c3d4e5f6"   -> "local__a1b2c3d4e5f6"
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", paper_id.replace(":", "__"))


def paper_dir(paper_id: str) -> Path:
    d = papers_dir() / _id_to_dirname(paper_id)
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

    def save(self) -> None:
        p = paper_dir(self.paper_id) / "metadata.json"
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, paper_id: str) -> PaperMetadata | None:
        p = paper_dir(paper_id) / "metadata.json"
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(**data)


def save_pdf(paper_id: str, pdf_bytes: bytes) -> Path:
    p = paper_dir(paper_id) / "paper.pdf"
    p.write_bytes(pdf_bytes)
    return p


def pdf_path(paper_id: str) -> Path | None:
    p = paper_dir(paper_id) / "paper.pdf"
    return p if p.exists() else None


def save_text(paper_id: str, text: str) -> Path:
    p = paper_dir(paper_id) / "text.txt"
    p.write_text(text, encoding="utf-8")
    return p


def load_text(paper_id: str) -> str | None:
    p = paper_dir(paper_id) / "text.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


def save_extraction(paper_id: str, extraction: dict[str, Any], *, prompt_sha: str) -> Path:
    """Save extraction keyed on the prompt SHA so prompt changes invalidate cache."""
    payload = {"prompt_sha256": prompt_sha, "extraction": extraction}
    p = paper_dir(paper_id) / "extraction.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_extraction(paper_id: str, *, prompt_sha: str) -> dict[str, Any] | None:
    """Return cached extraction iff the saved prompt SHA matches the current one."""
    p = paper_dir(paper_id) / "extraction.json"
    if not p.exists():
        return None
    payload = json.loads(p.read_text(encoding="utf-8"))
    if payload.get("prompt_sha256") != prompt_sha:
        return None
    return payload.get("extraction")


def list_papers() -> list[PaperMetadata]:
    """All papers currently in the local store, sorted by added_at desc."""
    out: list[PaperMetadata] = []
    for d in papers_dir().iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            out.append(PaperMetadata(**data))
        except (json.JSONDecodeError, TypeError):
            continue
    out.sort(key=lambda m: m.added_at, reverse=True)
    return out


def remove_paper(paper_id: str) -> bool:
    """Delete a paper's directory. Returns True if removed, False if not present."""
    d = papers_dir() / _id_to_dirname(paper_id)
    if not d.exists():
        return False
    import shutil
    shutil.rmtree(d)
    return True
