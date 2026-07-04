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
