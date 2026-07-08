"""Tests for research_companion.extract — mocked LLM, no API calls."""
from __future__ import annotations

import json

import pytest

from research_companion import extract, fetch, prompts, store


def test_strip_code_fences():
    assert extract._strip_code_fences("{}") == "{}"
    assert extract._strip_code_fences("```json\n{}\n```") == "{}"
    assert extract._strip_code_fences("```\n{}\n```") == "{}"
    assert extract._strip_code_fences('  {"a": 1}  ') == '{"a": 1}'


def test_validate_extraction_fills_missing_keys(sample_extraction: dict):
    out = extract._validate_extraction(sample_extraction)
    for k in ("concepts", "methods", "datasets", "claims", "results", "related_work"):
        assert k in out

    # Missing keys default to empty lists.
    minimal = {"concepts": []}
    out2 = extract._validate_extraction(minimal)
    assert out2["methods"] == []
    assert out2["datasets"] == []


def test_validate_extraction_rejects_non_dict():
    with pytest.raises(extract.ExtractionError):
        extract._validate_extraction([1, 2, 3])


def test_validate_extraction_rejects_non_list_value():
    with pytest.raises(extract.ExtractionError):
        extract._validate_extraction({"concepts": "not a list"})


def test_truncate_keeps_head_and_tail():
    text = "A" * 100_000
    out = extract._truncate(text, max_chars=1000)
    assert len(out) < len(text)
    assert out.startswith("A")
    assert out.endswith("A")
    assert "truncated" in out


def test_extract_paper_uses_cache(monkeypatch: pytest.MonkeyPatch, fake_pdf_bytes: bytes,
                                   sample_extraction: dict, tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta = fetch.add_local_pdf(pdf, title="t")

    # Pre-seed the cache.
    store.save_extraction(meta.paper_id, sample_extraction,
                          prompt_sha=prompts.extraction_prompt_sha256())

    # Anthropic client must NOT be called when cache hits.
    def _fail(*a, **k):
        raise AssertionError("LLM was called despite cache hit")
    monkeypatch.setattr(extract, "_call_anthropic", _fail)
    monkeypatch.setattr(extract, "_call_openai", _fail)

    result, usage = extract.extract_paper(meta)
    assert result == sample_extraction
    assert usage["cached"] is True


def test_extract_paper_calls_llm_on_miss(monkeypatch: pytest.MonkeyPatch,
                                          fake_pdf_bytes: bytes, tmp_path,
                                          sample_extraction: dict):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta = fetch.add_local_pdf(pdf, title="t")

    monkeypatch.setattr(
        extract, "_call_anthropic",
        lambda prompt, model, max_output_tokens=2048: (
            json.dumps(sample_extraction),
            {"input_tokens": 1234, "output_tokens": 567},
        ),
    )
    result, usage = extract.extract_paper(meta, provider="anthropic")
    assert result == sample_extraction
    assert usage["input_tokens"] == 1234
    assert usage["output_tokens"] == 567
    assert usage["cached"] is False

    # Subsequent call must hit cache.
    monkeypatch.setattr(extract, "_call_anthropic",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should be cached")))
    result2, usage2 = extract.extract_paper(meta, provider="anthropic")
    assert result2 == sample_extraction
    assert usage2["cached"] is True


def test_extract_paper_handles_code_fenced_response(monkeypatch: pytest.MonkeyPatch,
                                                     fake_pdf_bytes: bytes, tmp_path,
                                                     sample_extraction: dict):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta = fetch.add_local_pdf(pdf, title="t")

    fenced = "```json\n" + json.dumps(sample_extraction) + "\n```"
    monkeypatch.setattr(
        extract, "_call_anthropic",
        lambda prompt, model, max_output_tokens=2048: (fenced, {"input_tokens": 0, "output_tokens": 0}),
    )
    result, _ = extract.extract_paper(meta, provider="anthropic")
    assert result == sample_extraction


def test_extract_paper_raises_on_invalid_json(monkeypatch: pytest.MonkeyPatch,
                                                fake_pdf_bytes: bytes, tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta = fetch.add_local_pdf(pdf, title="t")

    monkeypatch.setattr(
        extract, "_call_anthropic",
        lambda *a, **k: ("this is not json at all", {"input_tokens": 0, "output_tokens": 0}),
    )
    with pytest.raises(extract.ExtractionError):
        extract.extract_paper(meta, provider="anthropic")


def test_resolve_model_defaults_per_provider():
    from research_companion.extract import resolve_model
    assert resolve_model("anthropic")           # non-empty default
    assert resolve_model("openai")
    assert resolve_model("anthropic", "custom-x") == "custom-x"


# ===========================================================================
# paper_meta backfill — prompt schema + pure decision helper + write-back
# ===========================================================================

def test_extraction_prompt_mentions_paper_meta():
    """The extraction prompt asks for a paper_meta object with title/authors/year."""
    p = prompts.EXTRACTION_PROMPT
    assert "paper_meta" in p
    assert "authors" in p
    # year documented as its own field inside paper_meta
    assert "publication year" in p.lower()


def _upload_meta(**kw) -> store.PaperMetadata:
    base = dict(paper_id="local:deadbeef", title="somefile.pdf", authors=[],
                year=None, source_url="upload://somefile.pdf")
    base.update(kw)
    return store.PaperMetadata(**base)


def test_backfill_upload_fills_all_three():
    meta = _upload_meta()
    pm = {"title": "Attention Is All You Need", "authors": ["A. Vaswani", "N. Shazeer"], "year": 2017}
    changes = extract._backfilled_metadata(meta, pm)
    assert changes["year"] == 2017
    assert changes["authors"] == ["A. Vaswani", "N. Shazeer"]
    assert changes["title"] == "Attention Is All You Need"


def test_backfill_strong_meta_not_overwritten():
    meta = store.PaperMetadata(
        paper_id="arxiv:1706.03762", title="Real ArXiv Title", authors=["A"],
        year=2020, source_url="https://arxiv.org/abs/1706.03762",
    )
    pm = {"title": "Different Title", "authors": ["X", "Y"], "year": 2017}
    changes = extract._backfilled_metadata(meta, pm)
    assert changes == {}


def test_backfill_title_only_for_uploads():
    """A local file whose source_url is a filesystem path (not upload://) keeps its title."""
    meta = store.PaperMetadata(
        paper_id="local:abc", title="filename", authors=[], year=None,
        source_url="/home/user/paper.pdf",
    )
    pm = {"title": "Real Title", "authors": [], "year": None}
    changes = extract._backfilled_metadata(meta, pm)
    assert "title" not in changes


def test_backfill_missing_paper_meta_no_change():
    meta = _upload_meta()
    assert extract._backfilled_metadata(meta, None) == {}
    assert extract._backfilled_metadata(meta, "not a dict") == {}
    assert extract._backfilled_metadata(meta, {}) == {}


def test_backfill_year_out_of_range_or_nonnumeric():
    meta = _upload_meta()
    assert "year" not in extract._backfilled_metadata(meta, {"year": 1200})
    assert "year" not in extract._backfilled_metadata(meta, {"year": 3000})
    assert "year" not in extract._backfilled_metadata(meta, {"year": "abcd"})
    assert "year" not in extract._backfilled_metadata(meta, {"year": None})
    # valid string year coerces
    assert extract._backfilled_metadata(meta, {"year": "2019"})["year"] == 2019


def test_backfill_empty_authors_left_empty():
    meta = _upload_meta()
    assert "authors" not in extract._backfilled_metadata(meta, {"authors": []})
    assert "authors" not in extract._backfilled_metadata(meta, {"authors": [""]})
    assert "authors" not in extract._backfilled_metadata(meta, {"authors": ["  "]})
    assert "authors" not in extract._backfilled_metadata(meta, {"authors": "not a list"})


def test_backfill_authors_stripped_and_capped():
    meta = _upload_meta()
    pm = {"authors": ["  Alice  ", "", "Bob", 123] + [f"X{i}" for i in range(40)]}
    changes = extract._backfilled_metadata(meta, pm)
    assert changes["authors"][0] == "Alice"
    assert changes["authors"][1] == "Bob"
    assert len(changes["authors"]) <= 25


def test_backfill_title_capped_length():
    meta = _upload_meta()
    changes = extract._backfilled_metadata(meta, {"title": "T" * 500})
    assert len(changes["title"]) <= 300


def test_extract_paper_backfills_on_cache_hit(monkeypatch: pytest.MonkeyPatch,
                                              fake_pdf_bytes: bytes, tmp_path,
                                              sample_extraction: dict):
    """A cached extraction carrying paper_meta backfills weak metadata (no LLM call)."""
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta = fetch.add_local_pdf_bytes(fake_pdf_bytes, source="upload://p.pdf", title="p.pdf")
    assert meta.year is None and meta.authors == []

    cached = dict(sample_extraction)
    cached["paper_meta"] = {"title": "Graph RAG Survey", "authors": ["Jane Doe"], "year": 2024}
    store.save_extraction(meta.paper_id, cached, prompt_sha=prompts.extraction_prompt_sha256())

    def _fail(*a, **k):
        raise AssertionError("LLM was called despite cache hit")
    monkeypatch.setattr(extract, "_call_anthropic", _fail)
    monkeypatch.setattr(extract, "_call_openai", _fail)

    result, usage = extract.extract_paper(meta)
    assert usage["cached"] is True
    reloaded = store.PaperMetadata.load(meta.paper_id)
    assert reloaded.year == 2024
    assert reloaded.authors == ["Jane Doe"]
    assert reloaded.title == "Graph RAG Survey"


def test_extract_paper_backfills_on_fresh_llm(monkeypatch: pytest.MonkeyPatch,
                                              fake_pdf_bytes: bytes, tmp_path,
                                              sample_extraction: dict):
    """A fresh LLM extraction returning paper_meta backfills + persists weak metadata."""
    meta = fetch.add_local_pdf_bytes(fake_pdf_bytes, source="upload://p.pdf", title="p.pdf")

    fresh = dict(sample_extraction)
    fresh["paper_meta"] = {"title": "Real Paper", "authors": ["A. One", "B. Two"], "year": 2021}
    monkeypatch.setattr(
        extract, "_call_anthropic",
        lambda prompt, model, max_output_tokens=2048: (json.dumps(fresh),
                                                        {"input_tokens": 1, "output_tokens": 1}),
    )
    extract.extract_paper(meta, provider="anthropic")
    reloaded = store.PaperMetadata.load(meta.paper_id)
    assert reloaded.year == 2021
    assert reloaded.authors == ["A. One", "B. Two"]
    assert reloaded.title == "Real Paper"
