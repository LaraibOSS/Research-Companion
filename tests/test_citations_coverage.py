"""Tests for research_companion.citations_coverage — the draft's bibliography
as ground truth for library coverage (W5-C1). Offline throughout."""
from __future__ import annotations

from research_companion import citations_coverage as cc
from research_companion import store
from research_companion.refcheck.validate import Reference

# ---------------------------------------------------------------------------
# Fixture bibliographies
# ---------------------------------------------------------------------------

_BRACKETED = """[1] A. Vaswani et al. Attention is all you need. NeurIPS, 2017.
[2] J. Devlin, M. Chang. BERT: Pre-training of deep bidirectional
transformers for language understanding. arXiv:1810.04805, 2018.
[3] T. Brown et al. Language models are few-shot learners. 2020.
[4] E. Hu et al. LoRA: Low-rank adaptation of large language models.
arXiv:2106.09685, 2021."""

_DOTTED = """1. First Author. Paper one title goes here with enough length. 2020.
2. Second Author. Paper two title also long enough to keep. 2021.
3. Third Author. Paper three title also long enough to keep. 2022."""

_BLANKSEP = """Alpha Author. The first blank-separated entry title. Journal, 2019.

Beta Author. The second blank-separated entry title. Conf, 2020.

Gamma Author. The third blank-separated entry title. Conf, 2021."""


def _mk_paper(paper_id: str, title: str) -> None:
    store.PaperMetadata(paper_id=paper_id, title=title, authors=["A"],
                        year=2021, added_at="2026-01-01T00:00:00Z").save()


# ---------------------------------------------------------------------------
# find_references_block
# ---------------------------------------------------------------------------

class TestFindReferencesBlock:
    def test_via_sections_payload(self):
        text = "Intro text here.\nReferences\n[1] Entry one.\n[2] Entry two.\n"
        payload = {"sections": [
            {"section_id": "s1", "title": "Introduction", "char_start": 0, "char_end": 17},
            {"section_id": "s9", "title": "References", "char_start": 17, "char_end": len(text)},
        ]}
        block = cc.find_references_block(text, payload)
        assert "[1] Entry one." in block
        assert "Intro text" not in block

    def test_raw_heading_fallback(self):
        text = "Body text.\n\nREFERENCES\n[1] Entry one here.\n[2] Entry two here.\n"
        block = cc.find_references_block(text, None)
        assert block is not None
        assert "[1] Entry one here." in block

    def test_bibliography_heading(self):
        text = "Body.\nBibliography\n[1] Something cited long enough.\n"
        assert "Something cited" in cc.find_references_block(text, None)

    def test_no_heading_returns_none(self):
        assert cc.find_references_block("Just body text, no refs section.", None) is None


# ---------------------------------------------------------------------------
# split_bibliography
# ---------------------------------------------------------------------------

class TestSplitBibliography:
    def test_bracket_numbered(self):
        entries = cc.split_bibliography(_BRACKETED)
        assert len(entries) == 4
        assert entries[0].startswith("[1]")
        # Wrapped lines joined
        assert "transformers for language understanding" in entries[1]

    def test_dot_numbered(self):
        entries = cc.split_bibliography(_DOTTED)
        assert len(entries) == 3
        assert "Paper two title" in entries[1]

    def test_blank_line_blocks(self):
        entries = cc.split_bibliography(_BLANKSEP)
        assert len(entries) == 3
        assert entries[2].startswith("Gamma")

    def test_requires_three_entries(self):
        assert cc.split_bibliography("[1] Only one entry that is long enough.") == []

    def test_length_filters(self):
        block = "[1] short\n[2] " + "x" * 1200 + "\n[3] A reasonable entry title here, 2020.\n[4] Another reasonable entry title, 2021.\n[5] Third reasonable entry title here, 2022."
        entries = cc.split_bibliography(block)
        assert all(20 <= len(e) <= 1000 for e in entries)

    def test_non_ascending_numbers_rejected_for_numbered_strategy(self):
        # Page numbers masquerading as entry numbers: [90], [12], [7]
        block = "[90] Alpha entry that is long enough here.\n[12] Beta entry that is long enough here.\n[7] Gamma entry that is long enough here."
        entries = cc.split_bibliography(block)
        # Bracket strategy rejected; falls through (blank-line gives 1 block -> [])
        assert entries == [] or len(entries) >= 3  # must NOT return 3 mis-split entries as bracketed
        if entries:
            assert not entries[0].startswith("[90]")


# ---------------------------------------------------------------------------
# match_reference_to_library
# ---------------------------------------------------------------------------

class TestMatchReferenceToLibrary:
    def test_arxiv_id_match_strips_version(self, isolated_papergraph_dir):
        _mk_paper("arxiv:2106.09685", "LoRA: Low-Rank Adaptation of Large Language Models")
        ref = Reference(title="whatever", authors=[], year=2021, doi=None,
                        arxiv_id="2106.09685v2", url=None, raw="raw")
        m = cc.match_reference_to_library(ref, store.list_papers())
        assert m == ("arxiv:2106.09685", "arxiv_id")

    def test_doi_match_case_insensitive(self, isolated_papergraph_dir):
        _mk_paper("doi:10.1145/3576915.1234", "Some DOI Paper")
        ref = Reference(title="t", authors=[], year=None, doi="10.1145/3576915.1234",
                        arxiv_id=None, url=None, raw="raw")
        m = cc.match_reference_to_library(ref, store.list_papers())
        assert m == ("doi:10.1145/3576915.1234", "doi")

    def test_title_containment_with_authors_in_raw(self, isolated_papergraph_dir):
        # THE critical case: parse leaves authors/venue in the "title";
        # containment of the clean library title in the raw entry must match.
        _mk_paper("arxiv:1810.04805",
                  "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding")
        raw = ("J. Devlin, M. Chang, K. Lee. BERT: Pre-training of deep "
               "bidirectional transformers for language understanding. NAACL, 2019.")
        ref = Reference(title="J Devlin M Chang K Lee BERT Pre-training of deep bidirectional transformers for language understanding NAACL",
                        authors=[], year=2019, doi=None, arxiv_id=None, url=None, raw=raw)
        m = cc.match_reference_to_library(ref, store.list_papers())
        assert m is not None
        assert m[0] == "arxiv:1810.04805"
        assert m[1] == "title_containment"

    def test_short_library_titles_not_containment_matched(self, isolated_papergraph_dir):
        _mk_paper("arxiv:9999.00001", "Attention")  # normalized len < 15
        ref = Reference(title="x", authors=[], year=None, doi=None, arxiv_id=None,
                        url=None, raw="A paper about attention mechanisms in general, 2020.")
        assert cc.match_reference_to_library(ref, store.list_papers()) is None

    def test_no_match(self, isolated_papergraph_dir):
        _mk_paper("arxiv:1234.56789", "A Completely Different Topic Entirely")
        ref = Reference(title="Unrelated citation string", authors=[], year=None,
                        doi=None, arxiv_id=None, url=None, raw="Unrelated citation string here.")
        assert cc.match_reference_to_library(ref, store.list_papers()) is None


# ---------------------------------------------------------------------------
# _ref_first_surname
# ---------------------------------------------------------------------------

class TestRefFirstSurname:
    def _ref(self, raw, year=None):
        return Reference(title=raw, authors=[], year=year, doi=None,
                         arxiv_id=None, url=None, raw=raw)

    def test_simple_et_al(self):
        assert cc._ref_first_surname(self._ref("Neumann et al. 2019")) == "neumann"

    def test_hyphenated_surname_kept_whole(self):
        assert cc._ref_first_surname(self._ref("Segura-Bedmar et al. 2013")) == "segurabedmar"

    def test_leading_enumeration_stripped(self):
        assert cc._ref_first_surname(self._ref("[12] Neumann et al. 2019")) == "neumann"

    def test_before_comma(self):
        assert cc._ref_first_surname(self._ref("Neumann, E. 2019")) == "neumann"

    def test_org_yields_non_person_token(self):
        # Leading token of an org name — will not equal any person's surname.
        sn = cc._ref_first_surname(
            self._ref("NHS Chief Clinical Information Officers Study Group 2023"))
        assert sn == "nhs"

    def test_empty_raw_returns_none(self):
        assert cc._ref_first_surname(self._ref("")) is None


# ---------------------------------------------------------------------------
# match_reference_to_library — author + year strategy
# ---------------------------------------------------------------------------

def _mk_paper_full(paper_id, title, authors, year):
    store.PaperMetadata(paper_id=paper_id, title=title, authors=authors,
                        year=year, added_at="2026-01-01T00:00:00Z").save()


class TestAuthorYearMatch:
    def _ref(self, raw, year):
        return Reference(title=raw, authors=[], year=year, doi=None,
                         arxiv_id=None, url=None, raw=raw)

    def test_surname_and_year_match(self, isolated_papergraph_dir):
        _mk_paper_full("arxiv:1111.00001", "Some Title", ["Emma Neumann", "X Author"], 2019)
        m = cc.match_reference_to_library(
            self._ref("Neumann et al. 2019", 2019), store.list_papers())
        assert m == ("arxiv:1111.00001", "author_year")

    def test_year_mismatch_no_match(self, isolated_papergraph_dir):
        _mk_paper_full("arxiv:1111.00002", "Some Title", ["Emma Neumann"], 2018)
        assert cc.match_reference_to_library(
            self._ref("Neumann et al. 2019", 2019), store.list_papers()) is None

    def test_surname_mismatch_no_match(self, isolated_papergraph_dir):
        _mk_paper_full("arxiv:1111.00003", "Some Title", ["Alice Smith"], 2019)
        assert cc.match_reference_to_library(
            self._ref("Neumann et al. 2019", 2019), store.list_papers()) is None

    def test_empty_authors_skipped(self, isolated_papergraph_dir):
        _mk_paper_full("arxiv:1111.00004", "Some Title", [], 2019)
        assert cc.match_reference_to_library(
            self._ref("Neumann et al. 2019", 2019), store.list_papers()) is None

    def test_hyphenated_surname_match(self, isolated_papergraph_dir):
        _mk_paper_full("arxiv:1111.00005", "NER Title", ["Isabel Segura-Bedmar"], 2013)
        m = cc.match_reference_to_library(
            self._ref("Segura-Bedmar et al. 2013", 2013), store.list_papers())
        assert m == ("arxiv:1111.00005", "author_year")

    def test_org_does_not_falsely_match(self, isolated_papergraph_dir):
        _mk_paper_full("arxiv:1111.00006", "Unrelated 2023 Paper", ["John Doe"], 2023)
        m = cc.match_reference_to_library(
            self._ref("NHS Chief Clinical Information Officers Study Group 2023", 2023),
            store.list_papers())
        assert m is None

    def test_no_year_no_author_year_match(self, isolated_papergraph_dir):
        _mk_paper_full("arxiv:1111.00007", "Some Title", ["Emma Neumann"], 2019)
        assert cc.match_reference_to_library(
            self._ref("Neumann et al.", None), store.list_papers()) is None

    def test_id_strategy_precedence_over_author_year(self, isolated_papergraph_dir):
        # An arxiv-id ref must still match by arxiv_id even if a different
        # paper would satisfy the author+year rule.
        _mk_paper_full("arxiv:2106.09685", "LoRA", ["Edward Hu"], 2021)
        _mk_paper_full("arxiv:9999.00009", "Other", ["Edward Hu"], 2021)
        ref = Reference(title="t", authors=[], year=2021, doi=None,
                        arxiv_id="2106.09685", url=None, raw="Hu et al. 2021")
        m = cc.match_reference_to_library(ref, store.list_papers())
        assert m == ("arxiv:2106.09685", "arxiv_id")


# ---------------------------------------------------------------------------
# compute_coverage
# ---------------------------------------------------------------------------

def _seed_draft(draft_id="local:draftcov001", bib=_BRACKETED):
    text = "Introduction\nSome body text.\n\nReferences\n" + bib + "\n"
    store.PaperMetadata(paper_id=draft_id, title="My Draft", authors=["Me"],
                        year=2026, added_at="2026-01-01T00:00:00Z").save()
    store.save_text(draft_id, text)
    store.set_draft_paper_id(draft_id)
    return draft_id


class TestComputeCoverage:
    def test_basic_coverage(self, isolated_papergraph_dir):
        draft = _seed_draft()
        _mk_paper("arxiv:2106.09685", "LoRA: Low-Rank Adaptation of Large Language Models")
        payload = cc.compute_coverage(draft)
        assert payload["source"] == "bibliography"
        assert payload["counts"]["total"] == 4
        assert payload["counts"]["in_library"] == 1
        # Ref with parsed arxiv id but not in library -> available, no network
        bert = next(r for r in payload["references"] if r["arxiv_id"] == "1810.04805")
        assert bert["status"] == "available"
        assert bert["add_target"] == "1810.04805"
        # Title-only refs -> unchecked
        assert payload["counts"]["unchecked"] >= 1
        # Persisted
        assert cc.load_coverage()["counts"]["total"] == 4

    def test_recompute_after_paper_added(self, isolated_papergraph_dir):
        draft = _seed_draft()
        p1 = cc.compute_coverage(draft)
        assert p1["counts"]["in_library"] == 0
        _mk_paper("arxiv:1810.04805", "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding")
        p2 = cc.compute_coverage(draft)
        assert p2["counts"]["in_library"] == 1

    def test_resolution_carried_over_by_raw(self, isolated_papergraph_dir):
        draft = _seed_draft()
        p1 = cc.compute_coverage(draft)
        # Simulate a resolved entry
        target = next(r for r in p1["references"] if r["status"] == "unchecked")
        target["status"] = "available"
        target["add_target"] = "10.5555/fake"
        target["resolved"] = {"title": "Resolved Title", "year": 2017, "doi": "10.5555/fake", "arxiv_id": None}
        p1["resolved_at"] = "2026-07-07T00:00:00Z"
        cc.save_coverage(p1)
        p2 = cc.compute_coverage(draft)
        again = next(r for r in p2["references"] if r["raw"] == target["raw"])
        assert again["status"] == "available"
        assert again["add_target"] == "10.5555/fake"
        assert p2["resolved_at"] == "2026-07-07T00:00:00Z"

    def test_related_work_fallback(self, isolated_papergraph_dir):
        draft = "local:draftrw001"
        store.PaperMetadata(paper_id=draft, title="D", authors=["M"],
                            year=2026, added_at="2026-01-01T00:00:00Z").save()
        store.save_text(draft, "No references heading in this text at all.")
        from research_companion.prompts import extraction_prompt_sha256
        store.save_extraction(draft, {
            "concepts": [], "methods": [], "datasets": [], "claims": [], "results": [],
            "related_work": [
                "Vaswani et al. Attention is all you need. 2017.",
                "Devlin et al. BERT pretraining paper. 2019.",
            ],
        }, prompt_sha=extraction_prompt_sha256())
        store.set_draft_paper_id(draft)
        payload = cc.compute_coverage(draft)
        assert payload["source"] == "related_work"
        assert payload["counts"]["total"] == 2

    def test_no_text_returns_none_source_without_caching(self, isolated_papergraph_dir):
        draft = "local:draftnotext"
        store.PaperMetadata(paper_id=draft, title="D", authors=["M"],
                            year=2026, added_at="2026-01-01T00:00:00Z").save()
        store.set_draft_paper_id(draft)
        payload = cc.compute_coverage(draft)
        assert payload["source"] == "none"
        assert payload["counts"]["total"] == 0
        assert cc.load_coverage() is None  # nothing cached


# ---------------------------------------------------------------------------
# resolve_missing
# ---------------------------------------------------------------------------

class TestResolveMissing:
    def test_fake_resolver_flips_statuses(self, isolated_papergraph_dir):
        draft = _seed_draft()
        payload = cc.compute_coverage(draft)
        unchecked_before = payload["counts"]["unchecked"]
        assert unchecked_before >= 1

        calls = []

        def fake_resolver(ref):
            calls.append(ref.raw)
            if "Attention" in ref.raw:
                return {"title": "Attention is All You Need", "year": 2017,
                        "doi": None, "arxiv_id": "1706.03762"}
            return None

        out = cc.resolve_missing(payload, resolver=fake_resolver)
        assert len(calls) == unchecked_before
        att = next(r for r in out["references"] if "Attention" in r["raw"])
        assert att["status"] == "available"
        assert att["add_target"] == "1706.03762"
        others = [r for r in out["references"]
                  if r["status"] == "unresolved"]
        assert len(others) == unchecked_before - 1
        assert out["resolved_at"]
        assert out["counts"]["unchecked"] == 0
        # persisted
        assert cc.load_coverage()["counts"]["unchecked"] == 0

    def test_resolver_prefers_arxiv_over_doi_target(self, isolated_papergraph_dir):
        draft = _seed_draft()
        payload = cc.compute_coverage(draft)

        def fake_resolver(ref):
            return {"title": "T", "year": 2020, "doi": "10.1/x", "arxiv_id": "2001.00001"}

        out = cc.resolve_missing(payload, resolver=fake_resolver)
        flipped = [r for r in out["references"] if r["resolved"]]
        assert all(r["add_target"] == "2001.00001" for r in flipped)


# ---------------------------------------------------------------------------
# resolve_reference acceptance rules (network functions injected)
# ---------------------------------------------------------------------------

class TestResolveReferenceAcceptance:
    def _ref(self, raw, title=None, year=None):
        return Reference(title=title or raw, authors=[], year=year, doi=None,
                         arxiv_id=None, url=None, raw=raw)

    def test_accepts_containment_and_year(self):
        candidate = {"title": "Attention Is All You Need", "year": 2017,
                     "doi": None, "arxiv_id": "1706.03762"}
        got = cc.resolve_reference(
            self._ref("A. Vaswani et al. Attention is all you need. NeurIPS, 2017.", year=2017),
            crossref_search=lambda q, **k: [candidate],
            openalex_search=lambda q, **k: [],
            parse_cr=lambda x: x, parse_oa=lambda x: x)
        assert got is not None and got["arxiv_id"] == "1706.03762"

    def test_rejects_year_mismatch(self):
        candidate = {"title": "Attention Is All You Need", "year": 2010,
                     "doi": None, "arxiv_id": "1706.03762"}
        got = cc.resolve_reference(
            self._ref("A. Vaswani et al. Attention is all you need. 2017.", year=2017),
            crossref_search=lambda q, **k: [candidate],
            openalex_search=lambda q, **k: [],
            parse_cr=lambda x: x, parse_oa=lambda x: x)
        assert got is None

    def test_rejects_unrelated_title(self):
        candidate = {"title": "A Totally Different Paper About Fish", "year": 2017,
                     "doi": "10.1/y", "arxiv_id": None}
        got = cc.resolve_reference(
            self._ref("A. Vaswani et al. Attention is all you need. 2017.", year=2017),
            crossref_search=lambda q, **k: [candidate],
            openalex_search=lambda q, **k: [],
            parse_cr=lambda x: x, parse_oa=lambda x: x)
        assert got is None
