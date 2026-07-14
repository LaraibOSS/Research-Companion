"""Deterministic near-duplicate / textual-overlap detection.

Flags passages in a paper that are near-duplicates of another paper **in the local
library** — self-plagiarism, duplicated passages, or a draft too close to something
already ingested. Lexical and local by default: it uses k-word shingling over the
existing tokenizer and reports the overlapping passage with absolute char offsets,
so the finding is verifiable in the reader. Nothing leaves the machine.

The honest label is a *near-duplicate / textual overlap with library paper X*,
never "plagiarism" or "misconduct". True web-corpus plagiarism needs an external
similarity service; that is available only through the opt-in, consent-gated
:func:`check_external` seam — no provider ships by default, and no text is sent
anywhere without both a registered provider and explicit consent.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from research_companion.chunking import chunk_section
from research_companion.rank import tokenize

DEFAULT_K = 5
DEFAULT_THRESHOLD = 0.6
DEFAULT_MIN_SHINGLES = 8
DEFAULT_PASSAGE_CHARS = 500


def shingles(text: str, k: int = DEFAULT_K) -> set[str]:
    """Set of k-word shingles over the tokenized text (order-preserving windows)."""
    toks = tokenize(text or "")
    if not toks:
        return set()
    if len(toks) < k:
        return {" ".join(toks)}
    return {" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}


def containment(a: set[str], b: set[str]) -> float:
    """Fraction of shingles in ``a`` that also appear in ``b`` (0..1).

    Containment (not Jaccard) is the right metric for "is this passage reproduced
    inside that larger document": a passage fully contained in ``b`` scores 1.0
    regardless of how much longer ``b`` is.
    """
    if not a:
        return 0.0
    return len(a & b) / len(a)


def jaccard(a: set[str], b: set[str]) -> float:
    """Symmetric Jaccard overlap of two shingle sets (0..1)."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def near_duplicate_passages(
    target_text: str,
    corpus: list[tuple[str, str]],
    *,
    k: int = DEFAULT_K,
    threshold: float = DEFAULT_THRESHOLD,
    min_shingles: int = DEFAULT_MIN_SHINGLES,
    passage_chars: int = DEFAULT_PASSAGE_CHARS,
) -> dict:
    """Find passages of *target_text* that near-duplicate a paper in *corpus*.

    Args:
        target_text: the paper being checked.
        corpus: list of ``(paper_id, text)`` for the rest of the library.
        k: shingle size (words).
        threshold: minimum containment (0..1) for a passage to be flagged.
        min_shingles: passages with fewer shingles are skipped (too short to judge).
        passage_chars: approximate passage window size.

    Returns a JSON-safe dict ``{findings, summary}``; each finding is
    ``{matched_paper_id, score, char_start, char_end, snippet}`` with target-side
    char offsets for reader highlighting.
    """
    corpus_shingles = [(pid, shingles(text, k)) for pid, text in corpus if text]

    findings: list[dict] = []
    if target_text and corpus_shingles:
        passages = chunk_section(
            target_text, 0,
            target_chars=passage_chars,
            overlap_chars=min(100, passage_chars - 1),
        )
        for ch in passages:
            sh = shingles(ch["text"], k)
            if len(sh) < min_shingles:
                continue
            best_pid, best_score = None, 0.0
            for pid, csh in corpus_shingles:
                score = containment(sh, csh)
                if score > best_score:
                    best_score, best_pid = score, pid
            if best_pid is not None and best_score >= threshold:
                findings.append({
                    "matched_paper_id": best_pid,
                    "score": round(best_score, 4),
                    "char_start": ch["char_start"],
                    "char_end": ch["char_end"],
                    "snippet": ch["text"][:200],
                })

    by_paper: dict[str, float] = {}
    for f in findings:
        pid = f["matched_paper_id"]
        by_paper[pid] = max(by_paper.get(pid, 0.0), f["score"])

    if not corpus_shingles:
        text = "no other library papers to compare against"
    elif not findings:
        text = "no near-duplicate passages found"
    else:
        top_pid = max(by_paper, key=lambda p: by_paper[p])
        text = (f"{len(findings)} passage(s) near-duplicate library paper "
                f"{top_pid} (max {round(max(by_paper.values()) * 100)}% overlap)")

    return {
        "findings": findings,
        "summary": {
            "n_passages": len(findings),
            "papers": sorted(by_paper),
            "max_score": round(max(by_paper.values()), 4) if by_paper else 0.0,
            "text": text,
        },
    }


# --- Opt-in, consent-gated external similarity seam -------------------------

@runtime_checkable
class ExternalOverlapProvider(Protocol):
    """A pluggable external similarity service (e.g. a web-corpus plagiarism API).

    Implementations must set ``name`` and return a list of match dicts from
    ``check``. None ships with Research Companion — the user registers one.
    """

    name: str

    def check(self, text: str) -> list[dict]:
        ...


_PROVIDER: ExternalOverlapProvider | None = None


def register_external_provider(provider: ExternalOverlapProvider | None) -> None:
    """Register (or clear, with None) the process-wide external provider."""
    global _PROVIDER
    _PROVIDER = provider


def get_external_provider() -> ExternalOverlapProvider | None:
    return _PROVIDER


def check_external(text: str, *, provider: ExternalOverlapProvider | None = None,
                   consent: bool = False) -> dict:
    """Run an external similarity check — only with a provider AND explicit consent.

    Privacy contract: ``provider.check`` is called **only** when a provider is
    present and ``consent`` is True. Otherwise nothing is sent and the return says
    why it is disabled.
    """
    prov = provider or _PROVIDER
    if prov is None:
        return {"enabled": False,
                "reason": "no external overlap provider is configured"}
    if not consent:
        return {"enabled": False,
                "reason": "external overlap check requires explicit consent"}
    return {
        "enabled": True,
        "provider": getattr(prov, "name", "external"),
        "matches": list(prov.check(text or "")),
    }
