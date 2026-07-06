"""Tests for research_companion.converse — talk-to-the-analysis.

TDD: tests written before / alongside implementation.
"""
from __future__ import annotations

import json

import pytest

from research_companion import store
from research_companion.prompts import extraction_prompt_sha256

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_paper(
    paper_id: str,
    title: str,
    text: str,
    sections: list[dict] | None = None,
    extraction: dict | None = None,
) -> str:
    import hashlib

    meta = store.PaperMetadata(paper_id=paper_id, title=title, authors=["Author A"], year=2024)
    meta.save()
    store.save_text(paper_id, text)
    if sections is not None:
        text_sha = hashlib.sha256(text.encode()).hexdigest()
        store.save_sections(paper_id, {
            "version": 1,
            "text_sha256": text_sha,
            "method": "heuristic",
            "sections": sections,
        })
    if extraction is not None:
        store.save_extraction(paper_id, extraction, prompt_sha=extraction_prompt_sha256())
    return paper_id


def _fake_llm(response: str):
    calls: list[str] = []

    def _llm(prompt: str) -> str:
        calls.append(prompt)
        return response

    _llm.calls = calls  # type: ignore[attr-defined]
    return _llm


# ---------------------------------------------------------------------------
# ConverseError + empty message
# ---------------------------------------------------------------------------

class TestConverseValidation:
    def test_empty_message_raises_converse_error(self):
        from research_companion.converse import ConverseError, converse

        with pytest.raises(ConverseError) as exc_info:
            converse("", context={"type": "paper"}, llm=_fake_llm("hi"))
        assert exc_info.value.status == 400

    def test_whitespace_message_raises_converse_error(self):
        from research_companion.converse import ConverseError, converse

        with pytest.raises(ConverseError) as exc_info:
            converse("   ", context={"type": "paper"}, llm=_fake_llm("hi"))
        assert exc_info.value.status == 400

    def test_unknown_context_type_raises_converse_error(self):
        from research_companion.converse import ConverseError, converse

        with pytest.raises(ConverseError) as exc_info:
            converse("hello", context={"type": "bogus"}, llm=_fake_llm("hi"))
        assert exc_info.value.status == 400


# ---------------------------------------------------------------------------
# Context builders — each type renders its artifact
# ---------------------------------------------------------------------------

class TestContextBuilderReview:
    def test_review_renders_ok(self):
        from research_companion.converse import _context_block_review

        paper_id = "arxiv:r001"
        _make_paper(paper_id, "Review Paper", "text")
        report = {
            "lanes": {
                "structure": {"ok": True, "items": []},
                "coverage": {"ok": False, "items": [{"message": "Missing related work"}]},
            }
        }
        store.save_review_report(paper_id, report)
        rendered, texts = _context_block_review({"type": "review", "id": paper_id})
        assert paper_id in rendered
        assert "Missing related work" in rendered
        assert len(texts) >= 1

    def test_review_missing_raises_404(self):
        from research_companion.converse import ConverseError, _context_block_review

        with pytest.raises(ConverseError) as exc_info:
            _context_block_review({"type": "review", "id": "arxiv:nonexistent99"})
        assert exc_info.value.status == 404


class TestContextBuilderAlignment:
    def test_alignment_renders_ok(self):
        from research_companion.converse import _context_block_alignment

        paper_id = "arxiv:a001"
        draft_id = "arxiv:draft001"
        _make_paper(paper_id, "Cand Paper", "candidate text")
        _make_paper(draft_id, "Draft Paper", "draft text")
        store.set_draft_paper_id(draft_id)
        alignment = {
            "draft_paper_id": draft_id,
            "verdict": "relevant",
            "score": 0.75,
            "sections": [
                {
                    "section_id": "s1",
                    "relation": "strengthens",
                    "rationale": "Highly relevant to the topic.",
                    "evidence": [{"quote": "This is verbatim evidence text."}],
                }
            ],
        }
        store.save_alignment(paper_id, alignment)
        rendered, texts = _context_block_alignment({"type": "alignment", "id": paper_id})
        assert "strengthens" in rendered
        assert "Highly relevant to the topic." in rendered
        # rationale text should be in artifact_texts for quote verification
        assert any("Highly relevant" in t for t in texts)

    def test_alignment_missing_raises_404(self):
        from research_companion.converse import ConverseError, _context_block_alignment

        with pytest.raises(ConverseError) as exc_info:
            _context_block_alignment({"type": "alignment", "id": "arxiv:noalign99"})
        assert exc_info.value.status == 404

    def test_alignment_no_id_raises_400(self):
        from research_companion.converse import ConverseError, _context_block_alignment

        with pytest.raises(ConverseError) as exc_info:
            _context_block_alignment({"type": "alignment"})
        assert exc_info.value.status == 400


class TestContextBuilderSuggestions:
    def test_suggestions_renders_ok(self):
        from research_companion.converse import _context_block_suggestions
        from research_companion.suggestions import _suggestions_path

        paper_id = "arxiv:sug001"
        _make_paper(paper_id, "Sug Paper", "text")
        # Write suggestions directly
        sugs_path = _suggestions_path(paper_id)
        sugs_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "draft_paper_id": paper_id,
            "suggestions": [
                {
                    "id": "sug_abc123",
                    "kind": "structure",
                    "severity": "high",
                    "title": "Add related work section",
                    "detail": "The paper lacks a related work section.",
                    "status": "open",
                    "section_id": None,
                }
            ],
        }
        sugs_path.write_text(json.dumps(payload), encoding="utf-8")
        rendered, texts = _context_block_suggestions({"type": "suggestions", "id": paper_id})
        assert "Add related work section" in rendered
        assert "high" in rendered.lower()

    def test_suggestions_missing_raises_404(self):
        from research_companion.converse import ConverseError, _context_block_suggestions

        with pytest.raises(ConverseError) as exc_info:
            _context_block_suggestions({"type": "suggestions", "id": "arxiv:nosugs99"})
        assert exc_info.value.status == 404


class TestContextBuilderGaps:
    def test_gaps_missing_returns_empty_not_error(self):
        from research_companion.converse import _context_block_gaps

        paper_id = "arxiv:gap001"
        _make_paper(paper_id, "Gap Paper", "text")
        # No gaps.json — should not raise
        rendered, texts = _context_block_gaps({"type": "gaps", "id": paper_id})
        assert "No gaps identified" in rendered

    def test_gaps_renders_when_present(self):
        from research_companion.converse import _context_block_gaps

        paper_id = "arxiv:gap002"
        _make_paper(paper_id, "Gap Paper", "text")
        gaps_path = store.paper_dir(paper_id) / "gaps.json"
        gaps_path.write_text(json.dumps([
            {"title": "Missing ablation study", "status": "open"}
        ]), encoding="utf-8")
        rendered, _ = _context_block_gaps({"type": "gaps", "id": paper_id})
        assert "Missing ablation study" in rendered


class TestContextBuilderPaper:
    def test_paper_renders_ok(self):
        from research_companion.converse import _context_block_paper

        paper_id = "arxiv:p001"
        _make_paper(paper_id, "The Paper Title", "text content")
        rendered, texts = _context_block_paper({"type": "paper", "id": paper_id})
        assert "The Paper Title" in rendered
        assert "Author A" in rendered

    def test_paper_missing_raises_404(self):
        from research_companion.converse import ConverseError, _context_block_paper

        with pytest.raises(ConverseError) as exc_info:
            _context_block_paper({"type": "paper", "id": "arxiv:nopaper99"})
        assert exc_info.value.status == 404

    def test_paper_with_extraction_shows_claims(self):
        from research_companion.converse import _context_block_paper

        paper_id = "arxiv:p002"
        ext = {
            "concepts": [],
            "methods": [],
            "datasets": [],
            "claims": [{"text": "This method outperforms the baseline."}],
            "results": [],
            "related_work": [],
        }
        _make_paper(paper_id, "Claim Paper", "text", extraction=ext)
        rendered, _ = _context_block_paper({"type": "paper", "id": paper_id})
        assert "This method outperforms the baseline." in rendered


# ---------------------------------------------------------------------------
# converse() end-to-end
# ---------------------------------------------------------------------------

class TestConverseEndToEnd:
    def test_basic_response_returned(self):
        from research_companion.converse import converse

        paper_id = "arxiv:e001"
        _make_paper(paper_id, "E2E Paper", "text about attention mechanisms.")
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)
        llm = _fake_llm("The review looks good.")

        result = converse("What does the review say?", context={"type": "review", "id": paper_id},
                          llm=llm)
        assert result.answer == "The review looks good."
        assert result.conversation_id.startswith("conv_")

    def test_citations_parsed(self):
        from research_companion.converse import converse

        paper_id = "arxiv:e002"
        text = "Neural network methods are state of the art. " * 20
        _make_paper(paper_id, "Citation Paper", text, sections=[
            {"section_id": "s1", "title": "Methods", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text)},
        ])
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)
        llm = _fake_llm("See the methods section [S1] for details.")

        result = converse("what are the methods?",
                          context={"type": "review", "id": paper_id},
                          llm=llm)
        cited_ns = [c["n"] for c in result.citations if c.get("cited")]
        assert 1 in cited_ns

    def test_fabricated_quote_in_unverified(self):
        from research_companion.converse import converse

        paper_id = "arxiv:e003"
        text = "Introduction text about neural networks here.\n"
        _make_paper(paper_id, "Quote Paper", text)
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)
        fabricated = "this completely fabricated quote does not appear anywhere"
        llm = _fake_llm(f'The paper says "{fabricated}" [S1].')

        result = converse("describe the paper",
                          context={"type": "review", "id": paper_id},
                          llm=llm)
        assert fabricated in result.unverified_quotes

    def test_alignment_rationale_quote_verifies(self):
        """A quote drawn from the alignment rationale text should NOT be unverified."""
        from research_companion.converse import converse

        paper_id = "arxiv:e004"
        draft_id = "arxiv:edraft004"
        _make_paper(paper_id, "Cand Paper", "candidate text")
        _make_paper(draft_id, "Draft Paper", "draft text")
        store.set_draft_paper_id(draft_id)
        rationale_text = "This candidate paper strongly supports the draft methodology."
        alignment = {
            "draft_paper_id": draft_id,
            "verdict": "relevant",
            "score": 0.9,
            "sections": [
                {
                    "section_id": "s1",
                    "relation": "strengthens",
                    "rationale": rationale_text,
                    "evidence": [],
                }
            ],
        }
        store.save_alignment(paper_id, alignment)
        llm = _fake_llm(f'The rationale states: "{rationale_text}".')
        result = converse("explain the alignment",
                          context={"type": "alignment", "id": paper_id},
                          llm=llm)
        assert rationale_text not in result.unverified_quotes


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------

class TestConversationHistory:
    def test_conversation_persisted(self):
        from research_companion.converse import converse, load_conversation

        paper_id = "arxiv:h001"
        _make_paper(paper_id, "History Paper", "text content about methods.")
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)
        llm = _fake_llm("Turn 1 answer.")

        result = converse("first message",
                          context={"type": "review", "id": paper_id},
                          llm=llm)
        conv = load_conversation(result.conversation_id)
        assert conv is not None
        assert conv["meta"]["conversation_id"] == result.conversation_id
        turns = conv["turns"]
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[0]["content"] == "first message"
        assert turns[1]["role"] == "assistant"
        assert turns[1]["content"] == "Turn 1 answer."

    def test_conversation_id_reuse(self):
        """Second call with same conversation_id continues the conversation."""
        from research_companion.converse import converse, load_conversation

        paper_id = "arxiv:h002"
        _make_paper(paper_id, "History Paper 2", "text content about models.")
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)

        llm1 = _fake_llm("First answer.")
        result1 = converse("first question",
                           context={"type": "review", "id": paper_id},
                           llm=llm1)

        llm2 = _fake_llm("Second answer.")
        result2 = converse("second question",
                           context={"type": "review", "id": paper_id},
                           conversation_id=result1.conversation_id,
                           llm=llm2)

        assert result2.conversation_id == result1.conversation_id
        conv = load_conversation(result1.conversation_id)
        assert conv is not None
        assert len(conv["turns"]) == 4  # 2 turns each call

    def test_history_included_in_prompt(self):
        """Second call should include prior turns in the prompt."""
        from research_companion.converse import converse

        paper_id = "arxiv:h003"
        _make_paper(paper_id, "History Paper 3", "text content about results.")
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)

        llm1 = _fake_llm("First answer here.")
        result1 = converse("first turn message",
                           context={"type": "review", "id": paper_id},
                           llm=llm1)

        llm2 = _fake_llm("Second answer here.")
        converse("second turn message",
                 context={"type": "review", "id": paper_id},
                 conversation_id=result1.conversation_id,
                 llm=llm2)

        # The second llm call's prompt should contain first turn content
        assert len(llm2.calls) == 1
        prompt = llm2.calls[0]
        assert "first turn message" in prompt or "First answer here." in prompt

    def test_history_trimmed_to_budget(self):
        """Tiny history budget should exclude old turns but keep newest turn."""
        from research_companion.converse import converse

        paper_id = "arxiv:h004"
        _make_paper(paper_id, "Budget Paper", "text content about budget.")
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)

        # "old turn" distinctive content — must NOT appear in the trimmed prompt
        old_distinctive = "XQZOLD_DISTINCTIVE_CONTENT_XQZOLD"
        llm1 = _fake_llm(f"Answer to old turn: {old_distinctive}.")
        result1 = converse(f"old turn: {old_distinctive}",
                           context={"type": "review", "id": paper_id},
                           llm=llm1)

        llm2 = _fake_llm("Answer to middle turn.")
        result2 = converse("middle turn text here",
                           context={"type": "review", "id": paper_id},
                           conversation_id=result1.conversation_id,
                           llm=llm2)

        # "newest turn" distinctive content — MUST appear in the prompt
        newest_distinctive = "XQZNEWEST_DISTINCTIVE_CONTENT_XQZNEW"
        llm3 = _fake_llm("Final answer.")
        # history_char_budget=80 fits the newest turn (short) but NOT the old long turn
        converse(f"newest: {newest_distinctive}",
                 context={"type": "review", "id": paper_id},
                 conversation_id=result2.conversation_id,
                 llm=llm3,
                 history_char_budget=80)

        assert len(llm3.calls) == 1
        prompt = llm3.calls[0]
        # Old distinctive content must NOT appear — it was trimmed away
        assert old_distinctive not in prompt
        # Newest distinctive content MUST appear — it's the current user message
        assert newest_distinctive in prompt


# ---------------------------------------------------------------------------
# Bounded history read (Fix 2)
# ---------------------------------------------------------------------------

class TestBoundedHistoryRead:
    def test_large_file_newest_turns_present(self):
        """Build a conversation with many turns whose total size exceeds 64 KB;
        verify that newest turns appear in the rendered history and the old bulk
        content is not required to be loaded."""
        import uuid

        from research_companion.converse import _conv_path, _load_history

        conv_id = f"conv_bounded_{uuid.uuid4().hex[:8]}"
        path = _conv_path(conv_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write a meta line first
        meta_line = json.dumps({"meta": {"conversation_id": conv_id}})
        # Write many filler turns totalling > 64 KB
        filler_content = "X" * 500  # 500 chars each
        filler_turns = []
        for _i in range(200):  # 200 * ~500 chars * 2 lines ≈ 200 KB total
            filler_turns.append(json.dumps({"role": "user", "content": filler_content}))
            filler_turns.append(json.dumps({"role": "assistant", "content": filler_content}))

        # Write a clearly distinctive newest turn at the very end
        newest_user = "BOUNDED_NEWEST_USER_TURN_MARKER"
        newest_asst = "BOUNDED_NEWEST_ASST_TURN_MARKER"
        newest_user_line = json.dumps({"role": "user", "content": newest_user})
        newest_asst_line = json.dumps({"role": "assistant", "content": newest_asst})

        with path.open("w", encoding="utf-8") as fh:
            fh.write(meta_line + "\n")
            for line in filler_turns:
                fh.write(line + "\n")
            fh.write(newest_user_line + "\n")
            fh.write(newest_asst_line + "\n")

        assert path.stat().st_size > 64 * 1024, "test file should exceed 64 KB"

        # Use a large enough budget to include the newest turns
        rendered = _load_history(conv_id, history_char_budget=10_000)

        # Newest distinctive markers must appear
        assert newest_user in rendered, "newest user turn must be in rendered history"
        assert newest_asst in rendered, "newest assistant turn must be in rendered history"

    def test_small_file_all_turns_present(self):
        """A file smaller than 64 KB should still have all its turns rendered."""
        import uuid

        from research_companion.converse import _conv_path, _load_history

        conv_id = f"conv_small_{uuid.uuid4().hex[:8]}"
        path = _conv_path(conv_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            json.dumps({"meta": {"conversation_id": conv_id}}),
            json.dumps({"role": "user", "content": "hello world"}),
            json.dumps({"role": "assistant", "content": "hello back"}),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rendered = _load_history(conv_id, history_char_budget=10_000)
        assert "hello world" in rendered
        assert "hello back" in rendered


# ---------------------------------------------------------------------------
# Orphaned meta when client supplies unknown conversation_id (Fix 3)
# ---------------------------------------------------------------------------

class TestOrphanedMetaOnClientId:
    def test_fresh_client_id_writes_meta(self):
        """Passing a fresh conversation_id that does not yet exist should create
        the file with a meta line (treated as a new conversation)."""
        from research_companion.converse import converse, load_conversation

        paper_id = "arxiv:om001"
        _make_paper(paper_id, "Orphan Meta Paper", "text content about orphan meta.")
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)

        fresh_id = "conv_fresh_client_supplied_id_xyz"
        llm = _fake_llm("Answer for fresh id.")
        result = converse(
            "question with fresh id",
            context={"type": "review", "id": paper_id},
            conversation_id=fresh_id,
            llm=llm,
        )

        # The returned conversation_id should be the one we supplied
        assert result.conversation_id == fresh_id

        # load_conversation should return a dict with meta
        conv = load_conversation(fresh_id)
        assert conv is not None
        assert conv["meta"]["conversation_id"] == fresh_id

    def test_existing_client_id_no_duplicate_meta(self):
        """Passing the same conversation_id a second time must NOT write a second
        meta line — the conversation continues normally."""
        from research_companion.converse import converse, load_conversation

        paper_id = "arxiv:om002"
        _make_paper(paper_id, "Orphan Meta Paper 2", "text content about orphan meta 2.")
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)

        fresh_id = "conv_existing_client_id_abc"
        llm1 = _fake_llm("First answer.")
        converse(
            "first question",
            context={"type": "review", "id": paper_id},
            conversation_id=fresh_id,
            llm=llm1,
        )

        llm2 = _fake_llm("Second answer.")
        converse(
            "second question",
            context={"type": "review", "id": paper_id},
            conversation_id=fresh_id,
            llm=llm2,
        )

        conv = load_conversation(fresh_id)
        assert conv is not None
        # Should have exactly 4 turns (2 per call), and only one meta
        assert len(conv["turns"]) == 4
        assert conv["meta"]["conversation_id"] == fresh_id


# ---------------------------------------------------------------------------
# load_conversation + 404 shape
# ---------------------------------------------------------------------------

class TestLoadConversation:
    def test_unknown_conversation_returns_none(self):
        from research_companion.converse import load_conversation

        result = load_conversation("conv_does_not_exist")
        assert result is None

    def test_known_conversation_returns_meta_and_turns(self):
        from research_companion.converse import converse, load_conversation

        paper_id = "arxiv:lc001"
        _make_paper(paper_id, "Load Conv Paper", "text content.")
        report = {"lanes": {"structure": {"ok": True, "items": []}}}
        store.save_review_report(paper_id, report)

        llm = _fake_llm("Test answer.")
        result = converse("test question",
                          context={"type": "review", "id": paper_id},
                          llm=llm)
        conv = load_conversation(result.conversation_id)
        assert conv is not None
        assert "meta" in conv
        assert "turns" in conv
        assert conv["meta"]["context"]["type"] == "review"
        assert conv["meta"]["prompt_sha256"] is not None


# ---------------------------------------------------------------------------
# Direct unit tests for extracted qa helpers
# ---------------------------------------------------------------------------

class TestQAHelpers:
    def test_build_sources_block_structure(self):
        from research_companion.qa import build_sources_block

        units = [
            {
                "paper_id": "p1", "paper_title": "Paper One",
                "section_id": "s1", "section_title": "Introduction",
                "tokens": ["intro"], "text": "Introduction text here.",
                "entity_labels": ["BM25"],
            },
            {
                "paper_id": "p2", "paper_title": "Paper Two",
                "section_id": "s1", "section_title": "Methods",
                "tokens": ["methods"], "text": "Methods text here.",
                "entity_labels": [],
            },
        ]
        scores = [0.7, 0.3]
        block, offered = build_sources_block(units, scores, char_budget=2000)
        assert "[S1]" in block
        assert "[S2]" in block
        assert "BM25" in block  # entity label present
        assert len(offered) == 2
        assert offered[0] == "Introduction text here."

    def test_build_sources_block_tiny_budget_headers_present(self):
        from research_companion.qa import build_sources_block

        units = [
            {"paper_id": "p1", "paper_title": "Paper", "section_id": "s1",
             "section_title": "Intro", "tokens": [], "text": "A" * 1000, "entity_labels": []},
            {"paper_id": "p2", "paper_title": "Paper B", "section_id": "s1",
             "section_title": "Meth", "tokens": [], "text": "B" * 1000, "entity_labels": []},
        ]
        block, _ = build_sources_block(units, [0.5, 0.5], char_budget=100)
        assert "[S1]" in block
        assert "[S2]" in block

    def test_parse_citations_extracts_correct_indices(self):
        from research_companion.qa import QASource, parse_citations

        sources = [
            QASource("p1", "Paper One", "s1", "Intro", 0.9),
            QASource("p2", "Paper Two", "s1", "Methods", 0.7),
            QASource("p3", "Paper Three", "s1", "Results", 0.5),
        ]
        text = "First result [S1]. Also see methods [S2]. No [S5] here."
        cited = parse_citations(text, sources)
        assert len(cited) == 2
        assert cited[0].paper_id == "p1"
        assert cited[1].paper_id == "p2"

    def test_parse_citations_out_of_range_ignored(self):
        from research_companion.qa import QASource, parse_citations

        sources = [QASource("p1", "Paper", "s1", "Intro", 0.9)]
        text = "See [S1] and also [S99]."
        cited = parse_citations(text, sources)
        assert len(cited) == 1
        assert cited[0].paper_id == "p1"

    def test_parse_citations_deduplicates(self):
        from research_companion.qa import QASource, parse_citations

        sources = [QASource("p1", "Paper", "s1", "Intro", 0.9)]
        text = "Mentioned [S1] and again [S1]."
        cited = parse_citations(text, sources)
        assert len(cited) == 1

    def test_extract_unverified_quotes_fabricated(self):
        from research_companion.qa import extract_unverified_quotes

        offered = ["The real source text is this sentence."]
        answer = 'The model says "this completely fabricated quote not in source".'
        unverified = extract_unverified_quotes(answer, offered)
        assert "this completely fabricated quote not in source" in unverified

    def test_extract_unverified_quotes_verbatim_passes(self):
        from research_companion.qa import extract_unverified_quotes

        offered = ["The real source text is this sentence exactly."]
        answer = 'The paper says "The real source text is this sentence exactly."'
        unverified = extract_unverified_quotes(answer, offered)
        assert unverified == []

    def test_extract_unverified_quotes_short_spans_ignored(self):
        from research_companion.qa import extract_unverified_quotes

        offered = ["Some text."]
        answer = 'The paper says "short".'
        unverified = extract_unverified_quotes(answer, offered)
        assert unverified == []  # under 20 chars threshold

    def test_extract_unverified_quotes_smart_quotes_normalised(self):
        from research_companion.qa import extract_unverified_quotes

        offered = ["The real source text is this sentence exactly."]
        answer = "“The real source text is this sentence exactly.”"
        unverified = extract_unverified_quotes(answer, offered)
        assert unverified == []
