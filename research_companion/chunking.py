"""Section-aware sub-chunking with absolute char provenance.

A retrieval unit used to be one whole section, and its BM25 tokens were built
from only the first 300 chars of that section — so content deep in a long
section was invisible to keyword search. This module splits a section into
overlapping windows that each carry ABSOLUTE char offsets into the paper text,
so callers can (a) tokenize the FULL chunk for recall and (b) highlight the
exact span in the reader.

Pure/stdlib, deterministic. No I/O, no globals mutated.
"""
from __future__ import annotations

# Defaults (chars). Tuned for academic prose: ~1200-char windows keep a chunk
# focused on one idea while staying large enough for meaningful BM25 signal.
DEFAULT_TARGET_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150
DEFAULT_MIN_TAIL = 400

# How far back from a window's hard edge we look for a natural break
# (paragraph or sentence boundary) before falling back to a hard cut.
_BOUNDARY_SEARCH = 200


def _find_break(text: str, start: int, hard_end: int) -> int:
    """Return a cut position in ``(start, hard_end]`` on a natural boundary.

    Prefer the last paragraph break ("\\n\\n"), then the last sentence break
    (". "), within the last ``_BOUNDARY_SEARCH`` chars of the window. Fall back
    to ``hard_end`` (a hard cut) when no boundary is found. The returned cut is
    always > ``start`` so the loop makes forward progress.
    """
    region_start = max(start + 1, hard_end - _BOUNDARY_SEARCH)
    if region_start >= hard_end:
        return hard_end

    para = text.rfind("\n\n", region_start, hard_end)
    if para != -1:
        return para + 2  # end the chunk after the paragraph break

    sent = text.rfind(". ", region_start, hard_end)
    if sent != -1:
        return sent + 2  # end the chunk after the sentence terminator + space

    return hard_end


def chunk_section(
    text: str,
    sec_char_start: int,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    min_tail: int = DEFAULT_MIN_TAIL,
) -> list[dict]:
    """Split ``text`` into overlapping chunks with absolute char provenance.

    Args:
        text:            The section's text slice
                         (``paper_text[sec_char_start:sec_char_end]``).
        sec_char_start:  Absolute offset of ``text`` within the paper text.
        target_chars:    Approximate window size.
        overlap_chars:   How many chars each window overlaps the previous one.
        min_tail:        A trailing chunk shorter than this is merged into the
                         previous chunk (avoids a tiny orphan chunk).

    Returns:
        A list of dicts ``{text, char_start, char_end, chunk_index}`` where
        ``char_start``/``char_end`` are ABSOLUTE offsets into the paper text
        (i.e. ``sec_char_start + local_offset``), so
        ``paper_text[char_start:char_end] == text_of_chunk``. Chunks tile the
        section contiguously with overlap (no gaps, no lost content) and
        ``chunk_index`` is 0-based sequential.

        A section at or below ``target_chars`` (including empty text) yields a
        single chunk covering the whole section.
    """
    n = len(text)

    # Short (or empty) section -> exactly one chunk covering the whole span.
    if n <= target_chars:
        return [{
            "text": text,
            "char_start": sec_char_start,
            "char_end": sec_char_start + n,
            "chunk_index": 0,
        }]

    # Build local (start, end) windows.
    spans: list[tuple[int, int]] = []
    pos = 0
    while pos < n:
        hard_end = min(pos + target_chars, n)
        if hard_end < n:
            hard_end = _find_break(text, pos, hard_end)
        spans.append((pos, hard_end))
        if hard_end >= n:
            break
        next_pos = hard_end - overlap_chars
        if next_pos <= pos:  # guard against non-progress (e.g. tiny target)
            next_pos = hard_end
        pos = next_pos

    # Merge a tiny trailing span into the previous one.
    if len(spans) > 1:
        ls, le = spans[-1]
        if le - ls < min_tail:
            ps, _pe = spans[-2]
            spans[-2] = (ps, le)
            spans.pop()

    return [
        {
            "text": text[ls:le],
            "char_start": sec_char_start + ls,
            "char_end": sec_char_start + le,
            "chunk_index": i,
        }
        for i, (ls, le) in enumerate(spans)
    ]
