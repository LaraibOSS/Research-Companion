"""Alignment must not score a paper it has not read.

get_paper_text raising FileNotFoundError was caught and turned into "", and
the model was asked anyway. It returned a confident stance and relevance from
the title alone, and nothing in the payload said so -- an output
indistinguishable from one built on a full text.

align_papers takes `llm` as a keyword parameter, so these tests inject a fake
that records whether it was called at all. No patching.
"""
from __future__ import annotations

import json

from research_companion import alignment
from research_companion.store import PaperMetadata


def _draft(paper_id="local:draft"):
    m = PaperMetadata(paper_id=paper_id, title="Draft", authors=["D"], year=2026)
    m.save()
    from research_companion import store
    store.save_text(paper_id, "Introduction\nWe argue that speculative decoding "
                              "degrades under memory pressure.\n")
    store.set_draft_paper_id(paper_id)
    return m


def _counting_llm(payload=None):
    calls = []

    def llm(prompt: str) -> str:
        calls.append(prompt)
        # align_papers requires a top-level "sections" list to parse the
        # response at all; the section_id need not match a real draft
        # section -- entries with an unknown id are simply filtered out.
        return json.dumps(payload or {"sections": [
            {"section_id": "s1", "relation": "strengthens", "relevance": 0.7,
             "rationale": "r", "evidence": []},
        ]})

    llm.calls = calls
    return llm


def test_a_paper_with_no_text_and_no_abstract_is_not_scored():
    _draft()
    PaperMetadata(paper_id="doi:10.1109/x", title="Some Title",
                  authors=["A"], year=2024, abstract="").save()
    llm = _counting_llm()
    out = alignment.align_papers("local:draft", "doi:10.1109/x", llm=llm,
                                 persist=False)
    assert llm.calls == [], "no model call for a paper we have not read"
    assert out["skipped"] is True
    assert out["reason"] == "no_text"


def test_the_skip_is_visible_in_the_payload():
    """Silence here is what made the old behaviour indefensible."""
    _draft()
    PaperMetadata(paper_id="doi:10.1109/x", title="T", authors=[], year=2024).save()
    out = alignment.align_papers("local:draft", "doi:10.1109/x",
                                 llm=_counting_llm(), persist=False)
    assert out.get("relation") is None
    assert out.get("score") is None
    assert out["evidence_depth"] == "metadata"


def test_an_abstract_is_enough_to_score():
    """An abstract is the authors' own statement of their contribution. It
    cannot support a quote, but it can support a stance."""
    _draft()
    PaperMetadata(paper_id="doi:10.1109/y", title="T", authors=[], year=2024,
                  abstract="We show that speculative decoding degrades under "
                           "memory pressure at batch sizes above 24.").save()
    llm = _counting_llm()
    out = alignment.align_papers("local:draft", "doi:10.1109/y", llm=llm,
                                 persist=False)
    assert len(llm.calls) == 1
    assert out.get("skipped") is not True
    assert out["evidence_depth"] == "abstract"


def test_a_whitespace_only_abstract_is_treated_as_absent():
    """A blank-looking abstract must not slip past the refusal as if it
    were real content -- the .strip() has to actually do its job."""
    _draft()
    PaperMetadata(paper_id="doi:10.1109/w", title="Some Title",
                  authors=["A"], year=2024, abstract="   ").save()
    llm = _counting_llm()
    out = alignment.align_papers("local:draft", "doi:10.1109/w", llm=llm,
                                 persist=False)
    assert llm.calls == [], "whitespace-only abstract is not content"
    assert out["skipped"] is True
    assert out["reason"] == "no_text"
    assert out["evidence_depth"] == "metadata"


def test_a_full_text_paper_is_marked_as_such(monkeypatch):
    _draft()
    PaperMetadata(paper_id="doi:10.1109/z", title="T", authors=[], year=2024).save()
    monkeypatch.setattr(alignment, "get_paper_text",
                        lambda meta: "full body text of the candidate")
    out = alignment.align_papers("local:draft", "doi:10.1109/z",
                                 llm=_counting_llm(), persist=False)
    assert out["evidence_depth"] == "full_text"
