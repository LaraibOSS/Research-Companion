"""Tests for research_companion.chunking — section-aware sub-chunking.

Strict TDD: tests written before implementation.

The chunker splits a section's text into overlapping windows carrying ABSOLUTE
char offsets into the paper text, so downstream code can highlight the exact
span and BM25 can tokenize the FULL chunk (not just a leading slice).
"""
from __future__ import annotations

from research_companion.chunking import (
    DEFAULT_MIN_TAIL,
    DEFAULT_OVERLAP_CHARS,
    DEFAULT_TARGET_CHARS,
    chunk_section,
)


class TestShortSection:
    def test_short_section_single_chunk(self):
        text = "A short section that fits comfortably in one chunk."
        chunks = chunk_section(text, 0)
        assert len(chunks) == 1
        c = chunks[0]
        assert c["text"] == text
        assert c["char_start"] == 0
        assert c["char_end"] == len(text)
        assert c["chunk_index"] == 0

    def test_short_section_absolute_offsets(self):
        """char_start/char_end are absolute — offset by sec_char_start."""
        text = "Body of the section."
        chunks = chunk_section(text, 500)
        assert len(chunks) == 1
        assert chunks[0]["char_start"] == 500
        assert chunks[0]["char_end"] == 500 + len(text)

    def test_exactly_target_is_single_chunk(self):
        text = "x" * DEFAULT_TARGET_CHARS
        chunks = chunk_section(text, 0)
        assert len(chunks) == 1
        assert chunks[0]["text"] == text

    def test_empty_section(self):
        chunks = chunk_section("", 42)
        assert len(chunks) == 1
        assert chunks[0]["text"] == ""
        assert chunks[0]["char_start"] == 42
        assert chunks[0]["char_end"] == 42
        assert chunks[0]["chunk_index"] == 0


class TestLongSection:
    def _long_text(self) -> str:
        # ~5000 chars of sentences with paragraph breaks so boundary logic engages.
        paras = []
        for i in range(50):
            paras.append(f"This is sentence number {i} in a fairly long paragraph of text. "
                         f"It carries some distinctive content for token {i}.")
        return "\n\n".join(paras)

    def test_multiple_chunks(self):
        text = self._long_text()
        chunks = chunk_section(text, 0)
        assert len(chunks) > 1

    def test_offsets_reconstruct_chunk(self):
        """paper_text[char_start:char_end] must reconstruct each chunk exactly."""
        text = self._long_text()
        paper_text = "PREFIX " + text  # section starts at offset 7
        sec_start = 7
        chunks = chunk_section(text, sec_start)
        for c in chunks:
            assert paper_text[c["char_start"]:c["char_end"]] == c["text"]

    def test_chunk_index_sequential(self):
        text = self._long_text()
        chunks = chunk_section(text, 0)
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))

    def test_no_content_lost(self):
        """Union of chunk spans must cover [0, len(text)) — nothing dropped."""
        text = self._long_text()
        chunks = chunk_section(text, 0)
        # chunks are in order and contiguous/overlapping
        assert chunks[0]["char_start"] == 0
        assert chunks[-1]["char_end"] == len(text)
        for prev, cur in zip(chunks, chunks[1:], strict=False):
            # next chunk must start at or before the previous chunk's end (no gap)
            assert cur["char_start"] <= prev["char_end"]
            # and must make forward progress
            assert cur["char_start"] > prev["char_start"]

    def test_overlap_present(self):
        text = self._long_text()
        chunks = chunk_section(text, 0)
        # consecutive chunks overlap (start of next < end of prev)
        overlaps = [prev["char_end"] - cur["char_start"]
                    for prev, cur in zip(chunks, chunks[1:], strict=False)]
        assert all(o > 0 for o in overlaps)

    def test_no_tiny_trailing_chunk(self):
        text = self._long_text()
        chunks = chunk_section(text, 0)
        if len(chunks) > 1:
            last_len = chunks[-1]["char_end"] - chunks[-1]["char_start"]
            assert last_len >= DEFAULT_MIN_TAIL

    def test_deterministic(self):
        text = self._long_text()
        a = chunk_section(text, 0)
        b = chunk_section(text, 0)
        assert a == b

    def test_chunks_respect_target_size_loosely(self):
        text = self._long_text()
        chunks = chunk_section(text, 0)
        # no chunk should be wildly larger than target + one merged tail
        for c in chunks:
            length = c["char_end"] - c["char_start"]
            assert length <= DEFAULT_TARGET_CHARS + DEFAULT_MIN_TAIL + 10

    def test_custom_params(self):
        text = "y" * 3000
        chunks = chunk_section(text, 0, target_chars=1000, overlap_chars=100, min_tail=200)
        assert len(chunks) > 1
        assert chunks[0]["char_start"] == 0
        assert chunks[-1]["char_end"] == 3000

    def test_defaults_exported(self):
        assert DEFAULT_TARGET_CHARS > 0
        assert 0 <= DEFAULT_OVERLAP_CHARS < DEFAULT_TARGET_CHARS
        assert DEFAULT_MIN_TAIL > 0
