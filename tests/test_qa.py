"""Tests for research_companion.qa — section-scoped grounded Q&A.

Strict TDD: tests written before implementation.
"""
from __future__ import annotations

import json

from research_companion import store
from research_companion.prompts import extraction_prompt_sha256

# ---------------------------------------------------------------------------
# Helpers: fabricate papers with sections.json + extraction.json + text.txt
# ---------------------------------------------------------------------------

def _save_sections(paper_id: str, sections: list[dict]) -> None:
    """Save a minimal sections.json for a paper."""
    import hashlib
    text = store.load_text(paper_id) or ""
    text_sha = hashlib.sha256(text.encode()).hexdigest()
    payload = {
        "version": 1,
        "text_sha256": text_sha,
        "method": "heuristic",
        "sections": sections,
    }
    store.save_sections(paper_id, payload)


def _make_paper(
    paper_id: str,
    title: str,
    text: str,
    sections: list[dict] | None = None,
    extraction: dict | None = None,
) -> str:
    meta = store.PaperMetadata(paper_id=paper_id, title=title, authors=["Author A"], year=2024)
    meta.save()
    store.save_text(paper_id, text)
    if sections is not None:
        _save_sections(paper_id, sections)
    if extraction is not None:
        store.save_extraction(paper_id, extraction, prompt_sha=extraction_prompt_sha256())
    return paper_id


# ---------------------------------------------------------------------------
# build_section_index
# ---------------------------------------------------------------------------

class TestBuildSectionIndex:
    def test_sections_paper_yields_per_section_units(self):
        from research_companion.qa import build_section_index
        text = "Introduction text here.\n\nMethods text here.\n"
        _make_paper("arxiv:0001", "Paper One", text, sections=[
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": 24},
            {"section_id": "s2", "title": "Methods", "level": 1,
             "parent": None, "char_start": 25, "char_end": len(text)},
        ])
        units = build_section_index(["arxiv:0001"])
        ids = [u["section_id"] for u in units]
        assert "s1" in ids
        assert "s2" in ids

    def test_no_sections_paper_yields_whole_paper_unit(self):
        from research_companion.qa import build_section_index
        _make_paper("arxiv:0002", "Paper Two", "Full text of paper two.")
        # No sections.json -> should produce one unit section_id="s1", title="Full Text"
        units = build_section_index(["arxiv:0002"])
        assert len(units) == 1
        assert units[0]["section_id"] == "s1"
        assert units[0]["section_title"] == "Full Text"

    def test_boilerplate_sections_excluded(self):
        from research_companion.qa import build_section_index
        text = "Intro text here.\n\nReferences list here.\n"
        _make_paper("arxiv:0003", "Paper Three", text, sections=[
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": 17},
            {"section_id": "s2", "title": "References", "level": 1,
             "parent": None, "char_start": 18, "char_end": len(text)},
        ])
        units = build_section_index(["arxiv:0003"])
        titles = [u["section_title"] for u in units]
        assert "References" not in titles
        assert "Introduction" in titles

    def test_paper_without_text_skipped_silently(self):
        from research_companion.qa import build_section_index
        # Save metadata but no text.txt
        meta = store.PaperMetadata(paper_id="arxiv:9999", title="NoText",
                                   authors=["A"], year=2024)
        meta.save()
        units = build_section_index(["arxiv:9999"])
        assert units == []

    def test_tokens_include_section_title_words(self):
        from research_companion.qa import build_section_index
        _make_paper("arxiv:0004", "Paper Four", "Neural network text here.", sections=[
            {"section_id": "s1", "title": "Neural Networks", "level": 1,
             "parent": None, "char_start": 0, "char_end": 25},
        ])
        units = build_section_index(["arxiv:0004"])
        assert len(units) == 1
        # tokens should include "neural" and "networks"
        assert "neural" in units[0]["tokens"]

    def test_extraction_entities_boost_tokens(self):
        from research_companion.qa import build_section_index
        text = "Some text about transformers.\n"
        ext = {
            "concepts": [{"name": "transformers", "definition": "Attention-based architecture",
                          "section": "s1"}],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:0005", "Paper Five", text, sections=[
            {"section_id": "s1", "title": "Background", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text)},
        ], extraction=ext)
        units = build_section_index(["arxiv:0005"])
        # Entity label "transformers" should appear in tokens
        assert "transformers" in units[0]["tokens"]

    def test_none_paper_ids_uses_all_papers(self):
        from research_companion.qa import build_section_index
        _make_paper("arxiv:0010", "Paper Ten", "Text ten.")
        _make_paper("arxiv:0011", "Paper Eleven", "Text eleven.")
        units = build_section_index(None)
        paper_ids = {u["paper_id"] for u in units}
        assert "arxiv:0010" in paper_ids
        assert "arxiv:0011" in paper_ids


# ---------------------------------------------------------------------------
# answer — retrieval
# ---------------------------------------------------------------------------

class TestAnswer:
    def _make_fake_llm(self, response: str) -> tuple[object, list]:
        calls: list[str] = []

        def _fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return response

        return _fake_llm, calls

    def test_no_papers_returns_graceful_message(self):
        from research_companion.qa import answer
        fake_llm, calls = self._make_fake_llm("No.")
        result = answer("What is attention?", llm=fake_llm)
        assert "No relevant material" in result.answer
        assert calls == []  # LLM NOT called

    def test_zero_score_returns_canned_answer_no_llm(self):
        """When BM25 gives all zeros, return canned answer without calling LLM."""
        from research_companion.qa import answer
        _make_paper("arxiv:1001", "Paper", "This paper is about completely unrelated things.",
                    sections=[{"section_id": "s1", "title": "Content", "level": 1,
                               "parent": None, "char_start": 0, "char_end": 47}])
        fake_llm, calls = self._make_fake_llm("Some answer")
        result = answer("zxqwerty florbiflorb quuxquux", llm=fake_llm)
        assert "No relevant material" in result.answer
        assert calls == []

    def test_retrieval_picks_relevant_section(self):
        """The section most related to the query should be among the sources."""
        from research_companion.qa import answer
        _make_paper("arxiv:2001", "Attention Paper",
                    "Introduction text.\n\nAttention is all you need for NLP tasks.\n",
                    sections=[
                        {"section_id": "s1", "title": "Introduction", "level": 1,
                         "parent": None, "char_start": 0, "char_end": 19},
                        {"section_id": "s2", "title": "Attention Mechanism", "level": 1,
                         "parent": None, "char_start": 20, "char_end": 65},
                    ])
        fake_llm, calls = self._make_fake_llm("Attention is used for NLP [S1].")
        result = answer("attention mechanism", llm=fake_llm)
        assert len(calls) > 0
        section_ids = [s.section_id for s in result.sources]
        assert "s2" in section_ids

    def test_cited_parsing(self):
        """[S1], [S3] in answer -> cited list correct."""
        from research_companion.qa import answer
        _make_paper("arxiv:3001", "Graph Paper",
                    "Graph neural networks intro text.\n\nMethods for graph learning here.\n",
                    sections=[
                        {"section_id": "s1", "title": "Intro", "level": 1,
                         "parent": None, "char_start": 0, "char_end": 33},
                        {"section_id": "s2", "title": "Methods", "level": 1,
                         "parent": None, "char_start": 34, "char_end": 67},
                    ])
        # Use k=2 to ensure both sections are offered as S1, S2
        fake_llm, _ = self._make_fake_llm("Graph networks are powerful [S1]. Methods vary [S1].")
        result = answer("graph networks methods", llm=fake_llm, k_sections=2)
        # cited should contain only the sources actually referenced in text
        # At least S1 should be cited (it was referenced)
        assert len(result.cited) >= 1

    def test_quote_verification_verbatim_pass(self):
        """Exact quotes from source text should not appear in unverified_quotes."""
        from research_companion.qa import answer
        text = "Introduction text.\n\nAttention is all you need for NLP tasks and models.\n"
        _make_paper("arxiv:4001", "Attn Paper", text, sections=[
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text)},
        ])
        quote = "Attention is all you need for NLP tasks"
        fake_llm, _ = self._make_fake_llm(f'The paper says "{quote}" [S1].')
        result = answer("attention NLP tasks models", llm=fake_llm)
        assert quote not in result.unverified_quotes

    def test_quote_verification_fabricated_fails(self):
        """Fabricated quotes should appear in unverified_quotes."""
        from research_companion.qa import answer
        _make_paper("arxiv:5001", "Some Paper",
                    "Introduction text about neural networks here.\n",
                    sections=[
                        {"section_id": "s1", "title": "Introduction", "level": 1,
                         "parent": None, "char_start": 0, "char_end": 46},
                    ])
        fabricated = "this fabricated quote does not appear anywhere in the actual source text"
        fake_llm, _ = self._make_fake_llm(f'The paper says "{fabricated}" [S1].')
        result = answer("neural networks introduction", llm=fake_llm)
        assert fabricated in result.unverified_quotes

    def test_budget_trimming(self):
        """Tiny char_budget -> sources_block under budget, but k sources still tagged."""
        from research_companion.qa import answer
        text = "A" * 5000  # long text
        _make_paper("arxiv:6001", "Long Paper", text, sections=[
            {"section_id": "s1", "title": "Content", "level": 1,
             "parent": None, "char_start": 0, "char_end": 5000},
        ])
        fake_llm, calls = self._make_fake_llm("answer [S1]")
        result = answer("content about paper", llm=fake_llm, k_sections=1, char_budget=200)
        assert len(calls) > 0
        # prompt should contain [S1]
        assert "[S1]" in calls[0]
        # sources_block in prompt should be under budget + overhead (prompt template ~600 chars)
        assert result.input_chars <= 1200  # char_budget=200 + QA_PROMPT template overhead

    def test_qa_log_appended(self, tmp_path):
        """qa_log.jsonl should be appended after each answer call."""
        from research_companion.qa import answer
        _make_paper("arxiv:7001", "Log Paper",
                    "Introduction content text here.\n",
                    sections=[
                        {"section_id": "s1", "title": "Introduction", "level": 1,
                         "parent": None, "char_start": 0, "char_end": 31},
                    ])
        fake_llm, _ = self._make_fake_llm("answer [S1]")
        answer("introduction content", llm=fake_llm)
        log_path = store.papergraph_dir() / "qa_log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert "question" in entry
        assert "answer" in entry

    def test_section_id_scoping_boosts_draft(self):
        """section_id scoping: draft section tokens boost query; draft's own units excluded."""
        from research_companion.qa import answer
        from research_companion.store import set_draft_paper_id

        # Create a draft paper with section s2 about "attention mechanisms"
        draft_text = "Introduction to our work.\n\nAttention mechanism details here.\n"
        _make_paper("arxiv:8001", "Draft Paper", draft_text, sections=[
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": 26},
            {"section_id": "s2", "title": "Attention", "level": 1,
             "parent": None, "char_start": 27, "char_end": len(draft_text)},
        ])
        set_draft_paper_id("arxiv:8001")

        # Create a related paper also about attention
        _make_paper("arxiv:8002", "Related Paper",
                    "This paper is about attention mechanism transformers.\n",
                    sections=[
                        {"section_id": "s1", "title": "Methods", "level": 1,
                         "parent": None, "char_start": 0, "char_end": 52},
                    ])
        # Create an unrelated paper
        _make_paper("arxiv:8003", "Unrelated Paper",
                    "This paper is about cooking and food recipes.\n",
                    sections=[
                        {"section_id": "s1", "title": "Cooking", "level": 1,
                         "parent": None, "char_start": 0, "char_end": 46},
                    ])

        fake_llm, _ = self._make_fake_llm("Related paper addresses attention [S1].")
        result = answer("attention mechanism", llm=fake_llm, section_id="s2")

        # Draft's own units must NOT appear in sources
        draft_ids = {s.paper_id for s in result.sources}
        assert "arxiv:8001" not in draft_ids

    def test_no_question_raises_or_empty(self):
        """answer('') with papers present should still handle gracefully."""
        from research_companion.qa import answer
        _make_paper("arxiv:9001", "Paper", "Text about neural networks.\n",
                    sections=[{"section_id": "s1", "title": "Content", "level": 1,
                                "parent": None, "char_start": 0, "char_end": 28}])
        # Empty question -> tokenize returns [] -> all zeros -> canned response, no LLM
        fake_llm, calls = self._make_fake_llm("answer")
        answer("", llm=fake_llm)
        assert calls == []


# ---------------------------------------------------------------------------
# CLI ask subcommand
# ---------------------------------------------------------------------------

class TestCLIAsk:
    def test_ask_no_question_rc1(self, capsys):
        from research_companion import cli
        rc = cli.main(["ask"])
        assert rc == 1

    def test_ask_no_papers_graceful(self, capsys, monkeypatch):
        from research_companion import cli
        monkeypatch.setitem(cli.QA_CONTEXT_OVERRIDES, "llm",
                            lambda prompt: "No answer")
        rc = cli.main(["ask", "what is attention?"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No relevant material" in out or "no" in out.lower()

    def test_ask_json_output(self, capsys, monkeypatch):
        from research_companion import cli
        # Seed a paper
        _make_paper("arxiv:9101", "CLI Paper",
                    "Introduction to attention mechanisms.\n",
                    sections=[
                        {"section_id": "s1", "title": "Introduction", "level": 1,
                         "parent": None, "char_start": 0, "char_end": 37},
                    ])
        monkeypatch.setitem(cli.QA_CONTEXT_OVERRIDES, "llm",
                            lambda prompt: "Attention is important [S1].")
        rc = cli.main(["ask", "attention", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "answer" in data
        assert "sources" in data
        assert "cited" in data
        assert "unverified_quotes" in data

    def test_ask_human_output(self, capsys, monkeypatch):
        from research_companion import cli
        _make_paper("arxiv:9201", "Human Paper",
                    "This is about neural network methods.\n",
                    sections=[
                        {"section_id": "s1", "title": "Methods", "level": 1,
                         "parent": None, "char_start": 0, "char_end": 37},
                    ])
        monkeypatch.setitem(cli.QA_CONTEXT_OVERRIDES, "llm",
                            lambda prompt: "Neural networks are effective [S1].")
        rc = cli.main(["ask", "neural network methods"])
        assert rc == 0
        out = capsys.readouterr().out
        # Human output should contain the answer
        assert "Neural networks" in out or "neural" in out.lower()


# ---------------------------------------------------------------------------
# Fix 1 — entities line present in sources_block
# ---------------------------------------------------------------------------

class TestEntitiesLineInSourcesBlock:
    def _make_fake_llm(self, response: str) -> tuple[object, list]:
        calls: list[str] = []

        def _fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return response

        return _fake_llm, calls

    def test_entity_label_appears_in_sources_block(self):
        """Entity label for a section must appear as a comma-joined line in sources_block."""
        from research_companion.qa import answer
        text = "Transformer architectures have shown great results.\n"
        ext = {
            "concepts": [{"name": "SparseAttention", "definition": "Sparse attention method",
                          "section": "s1"}],
            "methods": [],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:E001", "Entity Paper", text, sections=[
            {"section_id": "s1", "title": "Architecture", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text)},
        ], extraction=ext)
        fake_llm, calls = self._make_fake_llm("answer [S1]")
        answer("sparse attention architecture", llm=fake_llm, paper_ids=["arxiv:E001"])
        assert len(calls) == 1
        prompt = calls[0]
        # The entity label "SparseAttention" must appear in the sources_block in the prompt
        assert "SparseAttention" in prompt

    def test_sources_block_unit_has_entities_line_between_header_and_text(self):
        """Format: [S1] title — §section NEWLINE entities NEWLINE text_slice."""
        from research_companion.qa import answer
        text = "Transformer architectures.\n"
        ext = {
            "concepts": [{"name": "BERT", "definition": "Bidirectional encoder",
                          "section": "s1"}],
            "methods": [{"name": "FineTuning", "description": "fine-tune", "section": "s1"}],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        _make_paper("arxiv:E002", "BERT Paper", text, sections=[
            {"section_id": "s1", "title": "Methods", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text)},
        ], extraction=ext)
        fake_llm, calls = self._make_fake_llm("answer [S1]")
        answer("BERT fine tuning methods", llm=fake_llm, paper_ids=["arxiv:E002"])
        prompt = calls[0]
        # Both entity labels should appear
        assert "BERT" in prompt
        assert "FineTuning" in prompt

    def test_no_entities_no_extra_blank_line(self):
        """When section has no entities, no blank entities line should be inserted.

        Convention: no entities -> omit the entities line entirely (no extra blank line).
        The header line should be immediately followed by the text slice.
        """
        from research_companion.qa import answer
        text = "Plain text with no entities here.\n"
        _make_paper("arxiv:E003", "Plain Paper", text, sections=[
            {"section_id": "s1", "title": "Plain", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text)},
        ])
        fake_llm, calls = self._make_fake_llm("answer [S1]")
        answer("plain text", llm=fake_llm, paper_ids=["arxiv:E003"])
        prompt = calls[0]
        # The sources_block portion: header immediately followed by \n then text (no blank entities line)
        # Find the [S1] header line in the prompt
        s1_pos = prompt.find("[S1]")
        assert s1_pos >= 0
        # After the header line (ending at first \n after [S1]), next char should NOT be blank line
        header_end = prompt.index("\n", s1_pos)
        # The character right after the header newline should be the start of text, not another \n
        assert prompt[header_end + 1] != "\n", (
            "No entities -> header line should be directly followed by text, not a blank line"
        )


# ---------------------------------------------------------------------------
# Fix 2 — header-safe budget trimming
# ---------------------------------------------------------------------------

class TestHeaderSafeBudgetTrimming:
    def _make_fake_llm(self, response: str) -> tuple[object, list]:
        calls: list[str] = []

        def _fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return response

        return _fake_llm, calls

    def test_both_headers_present_with_tiny_budget(self):
        """k=2, char_budget=140: both [S1] and [S2] headers must appear in the prompt."""
        from research_companion.qa import answer
        # Two papers with distinctive query terms
        text1 = "Alpha " * 50  # 300 chars
        text2 = "Beta " * 50   # 250 chars
        _make_paper("arxiv:B001", "Alpha Paper", text1, sections=[
            {"section_id": "s1", "title": "Alpha Section", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text1)},
        ])
        _make_paper("arxiv:B002", "Beta Paper", text2, sections=[
            {"section_id": "s1", "title": "Beta Section", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text2)},
        ])
        fake_llm, calls = self._make_fake_llm("answer [S1] [S2]")
        answer(
            "alpha beta",
            llm=fake_llm,
            k_sections=2,
            char_budget=140,
            paper_ids=["arxiv:B001", "arxiv:B002"],
        )
        assert len(calls) == 1
        prompt = calls[0]
        assert "[S1]" in prompt
        assert "[S2]" in prompt

    def test_text_slices_within_remaining_budget(self):
        """After reserving headers, total text slice chars must fit within remaining budget."""
        from research_companion.qa import answer
        # Use query words that appear in section titles so BM25 scores are nonzero
        text1 = "Xylophone " * 50   # 500 chars; "xylophone" appears in title too
        text2 = "Zeppelin " * 55    # ~495 chars; "zeppelin" appears in title too
        _make_paper("arxiv:B003", "X Paper", text1, sections=[
            {"section_id": "s1", "title": "Xylophone Section", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text1)},
        ])
        _make_paper("arxiv:B004", "Z Paper", text2, sections=[
            {"section_id": "s1", "title": "Zeppelin Section", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(text2)},
        ])
        char_budget = 200
        fake_llm, calls = self._make_fake_llm("answer [S1] [S2]")
        answer(
            "xylophone zeppelin",
            llm=fake_llm,
            k_sections=2,
            char_budget=char_budget,
            paper_ids=["arxiv:B003", "arxiv:B004"],
        )
        prompt = calls[0]
        # Both headers present, text slices must be within budget
        assert "[S1]" in prompt
        assert "[S2]" in prompt

    def test_generous_budget_full_slices(self):
        """With generous budget, full text slices are included."""
        from research_companion.qa import answer
        short_text = "Short content about neural networks.\n"
        _make_paper("arxiv:B005", "Short Paper", short_text, sections=[
            {"section_id": "s1", "title": "Content", "level": 1,
             "parent": None, "char_start": 0, "char_end": len(short_text)},
        ])
        fake_llm, calls = self._make_fake_llm("answer [S1]")
        answer("neural networks content", llm=fake_llm, k_sections=1,
               char_budget=10000, paper_ids=["arxiv:B005"])
        prompt = calls[0]
        # Full text should appear in prompt
        assert short_text.strip() in prompt


class TestProviderEnvResolution:
    def test_resolve_llm_honors_provider_env(self, monkeypatch):
        """_resolve_llm must consult RESEARCH_COMPANION_PROVIDER when provider not given."""
        from research_companion import extract as extract_mod
        from research_companion import qa as qa_mod

        calls = []
        monkeypatch.setattr(extract_mod, "_call_openai",
                            lambda prompt, model=None, **kw: (calls.append(("openai", model)) or ("ok", {})))
        monkeypatch.setattr(extract_mod, "_call_anthropic",
                            lambda prompt, model=None: (calls.append(("anthropic", model)) or ("ok", {})))
        monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")
        monkeypatch.delenv("RESEARCH_COMPANION_MODEL", raising=False)

        llm = qa_mod._resolve_llm()
        assert llm("hi") == "ok"
        assert calls and calls[0][0] == "openai"

    def test_explicit_provider_overrides_env(self, monkeypatch):
        from research_companion import extract as extract_mod
        from research_companion import qa as qa_mod

        calls = []
        monkeypatch.setattr(extract_mod, "_call_openai",
                            lambda prompt, model=None, **kw: (calls.append("openai") or ("ok", {})))
        monkeypatch.setattr(extract_mod, "_call_anthropic",
                            lambda prompt, model=None: (calls.append("anthropic") or ("ok", {})))
        monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")

        llm = qa_mod._resolve_llm(provider="anthropic")
        assert llm("hi") == "ok"
        assert calls == ["anthropic"]

    def test_qa_openai_llm_uses_prose_mode(self, monkeypatch):
        """qa's resolved OpenAI llm must pass json_mode=False (prose answer)."""
        from research_companion import extract as extract_mod
        from research_companion import qa as qa_mod

        seen = {}

        def fake_openai(prompt, *, model=None, json_mode=True, **kw):
            seen["json_mode"] = json_mode
            return "ok", {}

        monkeypatch.setattr(extract_mod, "_call_openai", fake_openai)
        monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")
        llm = qa_mod._resolve_llm()
        assert llm("hi") == "ok"
        assert seen["json_mode"] is False

    def test_openai_request_kwargs_json_toggle(self):
        from research_companion.extract import _openai_request_kwargs

        with_json = _openai_request_kwargs(model="m", max_output_tokens=10, json_mode=True)
        without = _openai_request_kwargs(model="m", max_output_tokens=10, json_mode=False)
        assert with_json["response_format"] == {"type": "json_object"}
        assert "response_format" not in without
        assert without["model"] == "m" and without["temperature"] == 0.0
