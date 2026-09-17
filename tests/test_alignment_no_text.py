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


# ---------------------------------------------------------------------------
# The refusal has to reach the Lab, not just the return value
# ---------------------------------------------------------------------------

def test_the_refusal_is_persisted_so_the_lab_can_load_it():
    """Returned-only, the refusal reached nothing: the Lab saw no alignment
    at all and rendered the paper as merely unscored -- 8.1's
    "indistinguishable from its siblings", relocated rather than removed.
    It is stored under the keys store.load_alignment matches on."""
    from research_companion import store

    _draft()
    PaperMetadata(paper_id="doi:10.1109/p", title="T", authors=[], year=2024).save()
    alignment.align_papers("local:draft", "doi:10.1109/p",
                           llm=_counting_llm(), persist=True)

    stored = store.load_alignment("doi:10.1109/p", draft_paper_id="local:draft")
    assert stored is not None, "load_alignment must find the refusal"
    assert stored["skipped"] is True
    assert stored["sections"] == [], "an empty sections list keeps every reader working"


def test_persist_false_still_writes_nothing():
    from research_companion import store

    _draft()
    PaperMetadata(paper_id="doi:10.1109/q", title="T", authors=[], year=2024).save()
    alignment.align_papers("local:draft", "doi:10.1109/q",
                           llm=_counting_llm(), persist=False)
    assert store.load_alignment("doi:10.1109/q") is None


def test_the_lab_marks_a_refused_paper_rather_than_scoring_it():
    from fastapi.testclient import TestClient

    from research_companion.agents.bus import Bus
    from research_companion.lab_api import create_lab_app

    _draft()
    PaperMetadata(paper_id="doi:10.1109/r", title="Refused", authors=[],
                  year=2024).save()
    alignment.align_papers("local:draft", "doi:10.1109/r",
                           llm=_counting_llm(), persist=True)

    client = TestClient(create_lab_app(Bus()))
    paper = next(p for p in client.get("/api/papers").json()
                 if p["paper_id"] == "doi:10.1109/r")
    note = paper["alignment_note"]
    assert note is not None, "a refusal must be visible in the Lab"
    assert note["kind"] == "refused"
    assert note["evidence_depth"] == "metadata"
    assert "not been read" in note["headline"]
    assert paper["stance_counts"] == {"strengthens": 0, "challenges": 0,
                                      "alternative": 0}


def test_the_lab_marks_an_abstract_only_score(monkeypatch):
    """A stance resting on the authors' own summary is defensible, but it is
    not a stance resting on the paper, and it must not look like one."""
    from fastapi.testclient import TestClient

    from research_companion.agents.bus import Bus
    from research_companion.lab_api import create_lab_app

    _draft()
    PaperMetadata(paper_id="doi:10.1109/s", title="Abstract only", authors=[],
                  year=2024,
                  abstract="We show speculative decoding degrades under "
                           "memory pressure.").save()
    alignment.align_papers("local:draft", "doi:10.1109/s",
                           llm=_counting_llm(), persist=True)

    client = TestClient(create_lab_app(Bus()))
    paper = next(p for p in client.get("/api/papers").json()
                 if p["paper_id"] == "doi:10.1109/s")
    assert paper["alignment_note"]["kind"] == "abstract_only"


def test_the_refusal_event_carries_no_score():
    """lab_api's bulk analyze coerced score to float(... or 0.0), publishing a
    refusal as a neutral 0.0 the Library rendered like any other score."""
    from research_companion.agents.events import AlignmentReady, event_to_dict

    evt = AlignmentReady(paper_id="doi:x", draft_paper_id="local:draft",
                         verdict="", score=None, skipped=True, reason="no_text",
                         evidence_depth="metadata")
    payload = event_to_dict(evt)
    assert payload["skipped"] is True
    assert payload["score"] is None
    assert payload["reason"] == "no_text"
