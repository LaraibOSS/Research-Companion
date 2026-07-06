"""Tests for research_companion.journey — draft versions, conservative auto-match, summary."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(s: str) -> datetime:
    """Parse an ISO-8601 datetime string into a timezone-aware datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _make_paper(tmp_store: Path, paper_id: str, text: str = "", title: str = "Test Paper") -> None:
    """Create a minimal paper in the store."""
    from research_companion import store

    meta = store.PaperMetadata(
        paper_id=paper_id,
        title=title,
        authors=["Author"],
        year=2024,
        added_at="2024-01-01T00:00:00Z",
    )
    meta.save()
    if text:
        store.save_text(paper_id, text)


def _make_suggestion(kind: str, source_type: str = "lane", **kwargs) -> dict:
    """Build a minimal suggestion dict."""
    base = {
        "id": f"sug_{kind}_test",
        "kind": kind,
        "severity": "medium",
        "title": kwargs.get("title", f"Test {kind} suggestion"),
        "detail": kwargs.get("detail", f"Detail for {kind}"),
        "section_id": None,
        "source": {"type": source_type},
        "status": "open",
        "created_at": "2024-01-01T00:00:00Z",
        "addressed_at": None,
        "addressed_by": None,
        "_source_key": kwargs.get("source_key", "test"),
    }
    if source_type == "paper":
        base["source"]["paper_id"] = kwargs.get("paper_id", "arxiv:candidate001")
    if source_type == "lane":
        base["source"]["lane"] = kwargs.get("lane", kind)
    base.update({k: v for k, v in kwargs.items()
                  if k not in ("title", "detail", "source_key", "paper_id", "lane")})
    return base


# ---------------------------------------------------------------------------
# Tests: record_draft_version
# ---------------------------------------------------------------------------

class TestRecordDraftVersion:
    def test_first_version_is_one(self, isolated_papergraph_dir):
        from research_companion.journey import load_journey, record_draft_version
        _make_paper(isolated_papergraph_dir, "local:aabbcc")

        ver = record_draft_version("local:aabbcc")
        assert ver is not None
        assert ver["version"] == 1
        assert ver["paper_id"] == "local:aabbcc"

        j = load_journey()
        assert len(j["draft_versions"]) == 1

    def test_same_paper_no_op(self, isolated_papergraph_dir):
        from research_companion.journey import load_journey, record_draft_version
        _make_paper(isolated_papergraph_dir, "local:aabbcc")

        record_draft_version("local:aabbcc")
        result = record_draft_version("local:aabbcc")

        assert result is None
        j = load_journey()
        assert len(j["draft_versions"]) == 1

    def test_new_paper_increments_version(self, isolated_papergraph_dir):
        from research_companion.journey import load_journey, record_draft_version
        _make_paper(isolated_papergraph_dir, "local:aabbcc")
        _make_paper(isolated_papergraph_dir, "local:ddeeff")

        record_draft_version("local:aabbcc")
        ver2 = record_draft_version("local:ddeeff")

        assert ver2 is not None
        assert ver2["version"] == 2
        j = load_journey()
        assert len(j["draft_versions"]) == 2

    def test_counts_from_sections(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import record_draft_version

        paper_id = "local:withsections"
        _make_paper(isolated_papergraph_dir, paper_id)
        store.save_sections(paper_id, {
            "sections": [
                {"section_id": "s1", "title": "Intro", "level": 1, "text": "intro text"},
                {"section_id": "s2", "title": "Methods", "level": 1, "text": "methods text"},
            ]
        })

        ver = record_draft_version(paper_id)
        assert ver is not None
        assert ver["n_sections"] == 2

    def test_counts_zero_when_no_sections(self, isolated_papergraph_dir):
        from research_companion.journey import record_draft_version
        _make_paper(isolated_papergraph_dir, "local:nosections")

        ver = record_draft_version("local:nosections")
        assert ver is not None
        assert ver["n_sections"] == 0
        assert ver["n_claims"] == 0

    def test_version_added_event_logged(self, isolated_papergraph_dir):
        from research_companion.journey import load_journey, record_draft_version
        _make_paper(isolated_papergraph_dir, "local:aabbcc")

        record_draft_version("local:aabbcc")
        j = load_journey()
        events = j["events"]
        assert any(e["kind"] == "version_added" for e in events)
        ver_evt = next(e for e in events if e["kind"] == "version_added")
        assert ver_evt["data"]["version"] == 1
        assert ver_evt["data"]["paper_id"] == "local:aabbcc"


# ---------------------------------------------------------------------------
# Tests: fold_counts
# ---------------------------------------------------------------------------

class TestFoldCounts:
    def test_empty_versions_returns_empty(self):
        from research_companion.journey import fold_counts
        result = fold_counts([], [], [])
        assert result == []

    def test_single_version_no_events(self):
        from research_companion.journey import fold_counts
        versions = [{"version": 1, "added_at": "2024-01-01T10:00:00Z"}]
        result = fold_counts(versions, [], [])
        assert len(result) == 1
        assert result[0]["version"] == 1
        assert result[0]["open"] == 0
        assert result[0]["addressed"] == 0
        assert result[0]["dismissed"] == 0

    def test_addressed_events_counted_before_version(self):
        from research_companion.journey import fold_counts
        versions = [
            {"version": 1, "added_at": "2024-01-01T10:00:00Z"},
            {"version": 2, "added_at": "2024-01-03T10:00:00Z"},
        ]
        events = [
            {"at": "2024-01-02T10:00:00Z", "kind": "suggestion_addressed",
             "data": {"suggestion_id": "sug_a"}},
            {"at": "2024-01-02T12:00:00Z", "kind": "suggestion_addressed",
             "data": {"suggestion_id": "sug_b"}},
        ]
        suggestions = [
            {"id": "sug_a", "status": "addressed"},
            {"id": "sug_b", "status": "addressed"},
            {"id": "sug_c", "status": "open"},
        ]
        result = fold_counts(versions, events, suggestions)
        # Version 1: no events before it
        assert result[0]["addressed"] == 0
        # Version 2: 2 addressed events before it
        assert result[1]["addressed"] == 2

    def test_dismissed_events_counted(self):
        from research_companion.journey import fold_counts
        versions = [{"version": 1, "added_at": "2024-01-05T00:00:00Z"}]
        events = [
            {"at": "2024-01-03T00:00:00Z", "kind": "suggestion_dismissed",
             "data": {"suggestion_id": "sug_x"}},
        ]
        suggestions = [{"id": "sug_x", "status": "dismissed"}]
        result = fold_counts(versions, events, suggestions)
        assert result[0]["dismissed"] == 1

    def test_open_count_never_negative(self):
        from research_companion.journey import fold_counts
        versions = [{"version": 1, "added_at": "2024-01-10T00:00:00Z"}]
        # 5 addressed events but only 3 suggestions
        events = [
            {"at": "2024-01-01T00:00:00Z", "kind": "suggestion_addressed", "data": {}},
            {"at": "2024-01-02T00:00:00Z", "kind": "suggestion_addressed", "data": {}},
            {"at": "2024-01-03T00:00:00Z", "kind": "suggestion_addressed", "data": {}},
            {"at": "2024-01-04T00:00:00Z", "kind": "suggestion_addressed", "data": {}},
            {"at": "2024-01-05T00:00:00Z", "kind": "suggestion_addressed", "data": {}},
        ]
        suggestions = [
            {"id": "s1", "status": "addressed"},
            {"id": "s2", "status": "addressed"},
            {"id": "s3", "status": "open"},
        ]
        result = fold_counts(versions, events, suggestions)
        assert result[0]["open"] >= 0


# ---------------------------------------------------------------------------
# Tests: match_open_suggestions — related_work
# ---------------------------------------------------------------------------

class TestMatchRelatedWork:
    def test_related_work_positive_title_in_references(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft001"
        candidate_id = "arxiv:transformer001"
        _make_paper(isolated_papergraph_dir, draft_id)
        _make_paper(isolated_papergraph_dir, candidate_id,
                    title="Attention Is All You Need")

        # Draft text includes references section with the candidate title
        draft_text = """Introduction
        We propose a new method.

        Related Work
        Attention Is All You Need transformer architecture is widely used.
        Many papers build upon Attention Is All You Need for NLP tasks.

        References
        Vaswani et al. Attention Is All You Need. 2017.
        """
        store.save_text(draft_id, draft_text)

        sug = {
            "id": "sug_relwork_001",
            "kind": "related_work",
            "severity": "medium",
            "title": "Discuss Attention Is All You Need",
            "detail": "Consider discussing Attention Is All You Need",
            "section_id": None,
            "source": {"type": "paper", "paper_id": candidate_id},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id)
        assert len(newly) == 1
        assert newly[0]["id"] == "sug_relwork_001"
        assert newly[0]["status"] == "addressed"
        assert newly[0]["addressed_by"]["by"] == "auto"

    def test_related_work_negative_not_in_text(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft002"
        candidate_id = "arxiv:cand002"
        _make_paper(isolated_papergraph_dir, draft_id)
        _make_paper(isolated_papergraph_dir, candidate_id,
                    title="Graph Neural Network Survey Paper")

        # Draft text that does NOT mention the candidate title
        store.save_text(draft_id, "Introduction. This is about transformers only. References: Smith 2020.")

        sug = {
            "id": "sug_relwork_002",
            "kind": "related_work",
            "severity": "medium",
            "title": "Discuss Graph Neural Network Survey Paper",
            "detail": "Missing discussion",
            "section_id": None,
            "source": {"type": "paper", "paper_id": candidate_id},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id)
        assert len(newly) == 0


# ---------------------------------------------------------------------------
# Tests: match_open_suggestions — gap
# ---------------------------------------------------------------------------

class TestMatchGap:
    def test_gap_positive_all_idf_tokens_present(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft003"
        _make_paper(isolated_papergraph_dir, draft_id)

        # Gap about unique tokens that ARE present in the draft text.
        # Use words that are distinctive (high IDF) and present in draft.
        gap_detail = "evaluation benchmark ablation study missing experiments"
        draft_text = (
            "Abstract. This paper presents evaluation benchmark results. "
            "We include ablation study and extensive missing experiments. "
            "Our evaluation demonstrates benchmark superiority. "
            "The ablation missing study evaluation shows benchmark improvement."
        )
        store.save_text(draft_id, draft_text)

        sug = {
            "id": "sug_gap_001",
            "kind": "gap",
            "severity": "medium",
            "title": "Research gap not addressed",
            "detail": gap_detail,
            "section_id": None,
            "source": {"type": "lane", "lane": "gap"},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id)
        assert len(newly) == 1
        assert newly[0]["addressed_by"]["by"] == "auto"

    def test_gap_negative_tokens_absent(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft004"
        _make_paper(isolated_papergraph_dir, draft_id)

        gap_detail = "quantum entanglement cryptography distributed verification protocol"
        store.save_text(draft_id, "This paper is about transformers and attention mechanisms only.")

        sug = {
            "id": "sug_gap_002",
            "kind": "gap",
            "severity": "medium",
            "title": "Gap not addressed",
            "detail": gap_detail,
            "section_id": None,
            "source": {"type": "lane", "lane": "gap"},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id)
        assert len(newly) == 0


# ---------------------------------------------------------------------------
# Tests: claim-rewrite candidate (novelty/evidence lane-sourced)
# ---------------------------------------------------------------------------

class TestClaimRewriteCandidate:
    def test_candidate_stays_open_without_llm(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft005"
        _make_paper(isolated_papergraph_dir, draft_id)

        # Old claim text; new draft text is totally different (low Jaccard)
        claim_text = "Our method achieves superior performance on quantum benchmarks"
        store.save_text(draft_id, "This paper presents language model evaluation only.")

        sug = {
            "id": "sug_novelty_001",
            "kind": "novelty",
            "severity": "high",
            "title": "Novelty concern",
            "detail": "Claim may overlap with prior work",
            "section_id": None,
            "source": {"type": "lane", "lane": "novelty"},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
            "_source_key": claim_text,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        # Without LLM: candidate stays open
        newly = match_open_suggestions(draft_id, llm=None)
        assert len(newly) == 0

    def test_candidate_addressed_with_llm_verified(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft006"
        _make_paper(isolated_papergraph_dir, draft_id)

        claim_text = "Our method achieves superior performance on quantum benchmarks"
        # Draft text is completely different — low Jaccard so becomes candidate
        draft_text = "This paper presents language model evaluation methodology only."
        store.save_text(draft_id, draft_text)

        # Store sections so rank_units has something to work with
        store.save_sections(draft_id, {
            "sections": [
                {"section_id": "s1", "title": "Introduction",
                 "text": draft_text, "level": 1},
            ]
        })

        # The LLM returns addressed=true with a verbatim evidence quote
        evidence_quote = "language model evaluation"

        def _fake_llm(prompt: str) -> str:
            return json.dumps({
                "addressed": True,
                "evidence": evidence_quote,
            })

        sug = {
            "id": "sug_novelty_002",
            "kind": "novelty",
            "severity": "high",
            "title": "Novelty concern",
            "detail": "Claim may overlap with prior work",
            "section_id": None,
            "source": {"type": "lane", "lane": "novelty"},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
            "_source_key": claim_text,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id, llm=_fake_llm)
        assert len(newly) == 1
        assert newly[0]["addressed_by"]["by"] == "llm"

    def test_candidate_stays_open_with_llm_unverified_evidence(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft007"
        _make_paper(isolated_papergraph_dir, draft_id)

        claim_text = "Our method achieves superior performance on quantum benchmarks"
        draft_text = "This paper presents language model evaluation methodology only."
        store.save_text(draft_id, draft_text)
        store.save_sections(draft_id, {
            "sections": [
                {"section_id": "s1", "title": "Introduction",
                 "text": draft_text, "level": 1},
            ]
        })

        # LLM returns addressed=true but with FABRICATED evidence (not in text)
        def _fake_llm_unverified(prompt: str) -> str:
            return json.dumps({
                "addressed": True,
                "evidence": "this quote does not exist in the draft text at all",
            })

        sug = {
            "id": "sug_novelty_003",
            "kind": "novelty",
            "severity": "high",
            "title": "Novelty concern",
            "detail": "Claim may overlap",
            "section_id": None,
            "source": {"type": "lane", "lane": "novelty"},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
            "_source_key": claim_text,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id, llm=_fake_llm_unverified)
        assert len(newly) == 0

    def test_candidate_stays_open_with_bad_json_from_llm(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft008"
        _make_paper(isolated_papergraph_dir, draft_id)

        claim_text = "Our method achieves superior performance on quantum benchmarks"
        draft_text = "This paper presents language model evaluation methodology only."
        store.save_text(draft_id, draft_text)
        store.save_sections(draft_id, {
            "sections": [
                {"section_id": "s1", "title": "Introduction", "text": draft_text, "level": 1},
            ]
        })

        def _bad_json_llm(prompt: str) -> str:
            return "this is not json at all!!!"

        sug = {
            "id": "sug_novelty_004",
            "kind": "novelty",
            "severity": "high",
            "title": "Novelty concern",
            "detail": "Claim may overlap",
            "section_id": None,
            "source": {"type": "lane", "lane": "novelty"},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
            "_source_key": claim_text,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id, llm=_bad_json_llm)
        assert len(newly) == 0


# ---------------------------------------------------------------------------
# Tests: citation/benchmark/structure never matched
# ---------------------------------------------------------------------------

class TestNeverMatchedKinds:
    @pytest.mark.parametrize("kind", ["citation", "benchmark", "structure"])
    def test_never_auto_matched(self, isolated_papergraph_dir, kind):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft_never"
        _make_paper(isolated_papergraph_dir, draft_id)
        # Draft text contains all sorts of content that might match anything
        store.save_text(draft_id, "citation benchmark structure everything is here")

        sug = {
            "id": f"sug_{kind}_001",
            "kind": kind,
            "severity": "medium",
            "title": f"{kind} suggestion",
            "detail": "citation benchmark structure detail text",
            "section_id": None,
            "source": {"type": "lane", "lane": kind},
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": None,
            "addressed_by": None,
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, draft_id)  # wrong call just to init
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id)
        assert len(newly) == 0


# ---------------------------------------------------------------------------
# Tests: dismissed suggestions never matched
# ---------------------------------------------------------------------------

class TestDismissedNotMatched:
    def test_dismissed_suggestion_not_re_addressed(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import match_open_suggestions
        from research_companion.suggestions import save_suggestions

        draft_id = "local:draft_dismissed"
        candidate_id = "arxiv:dismissed_cand"
        _make_paper(isolated_papergraph_dir, draft_id)
        _make_paper(isolated_papergraph_dir, candidate_id, title="Attention Mechanism Survey")

        # Draft text has the candidate title — would normally be matched
        store.save_text(draft_id, "Related Work. Attention Mechanism Survey is well known. References: Attention Mechanism Survey paper.")

        sug = {
            "id": "sug_dismissed_001",
            "kind": "related_work",
            "severity": "medium",
            "title": "Discuss Attention Mechanism Survey",
            "detail": "Missing discussion",
            "section_id": None,
            "source": {"type": "paper", "paper_id": candidate_id},
            "status": "dismissed",  # already dismissed
            "created_at": "2024-01-01T00:00:00Z",
            "addressed_at": "2024-01-02T00:00:00Z",
            "addressed_by": {"by": "user", "note": "dismissed"},
        }
        payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [sug],
        }
        save_suggestions(draft_id, payload)

        newly = match_open_suggestions(draft_id)
        assert len(newly) == 0


# ---------------------------------------------------------------------------
# Tests: journey_summary
# ---------------------------------------------------------------------------

class TestJourneySummary:
    def test_empty_summary_shape(self, isolated_papergraph_dir):
        from research_companion.journey import journey_summary
        summary = journey_summary()
        assert "versions" in summary
        assert "events" in summary
        assert "counts_over_time" in summary
        assert "current" in summary
        assert isinstance(summary["versions"], list)
        assert isinstance(summary["events"], list)
        assert isinstance(summary["counts_over_time"], list)
        assert "open" in summary["current"]
        assert "addressed" in summary["current"]
        assert "dismissed" in summary["current"]

    def test_events_newest_first(self, isolated_papergraph_dir):
        from datetime import timezone

        from research_companion.journey import journey_summary, log_event

        t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
        log_event("review_run", {"paper_id": "p1"}, now=t1)
        log_event("review_run", {"paper_id": "p2"}, now=t2)

        summary = journey_summary()
        events = summary["events"]
        assert len(events) >= 2
        # Events should be newest first
        assert events[0]["at"] >= events[1]["at"]

    def test_current_counts_with_suggestions(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.journey import journey_summary
        from research_companion.suggestions import save_suggestions

        paper_id = "local:summary_draft"
        _make_paper(isolated_papergraph_dir, paper_id)
        store.set_draft_paper_id(paper_id)

        payload = {
            "version": 1,
            "draft_paper_id": paper_id,
            "draft_version": "",
            "generated_at": "2024-01-01T00:00:00Z",
            "suggestions": [
                {"id": "s1", "status": "open", "kind": "gap"},
                {"id": "s2", "status": "addressed", "kind": "gap"},
                {"id": "s3", "status": "dismissed", "kind": "gap"},
            ],
        }
        save_suggestions(paper_id, payload)

        summary = journey_summary()
        assert summary["current"]["open"] == 1
        assert summary["current"]["addressed"] == 1
        assert summary["current"]["dismissed"] == 1


# ---------------------------------------------------------------------------
# Tests: log_event
# ---------------------------------------------------------------------------

class TestLogEvent:
    def test_log_event_appends(self, isolated_papergraph_dir):
        from research_companion.journey import load_journey, log_event
        log_event("review_run", {"paper_id": "p1"})
        log_event("alignment_run", {"paper_id": "p2", "verdict": "supports"})

        j = load_journey()
        assert len(j["events"]) == 2
        assert j["events"][0]["kind"] == "review_run"
        assert j["events"][1]["kind"] == "alignment_run"

    def test_log_event_has_at_field(self, isolated_papergraph_dir):
        from research_companion.journey import load_journey, log_event
        log_event("review_run", {"paper_id": "x"})
        j = load_journey()
        assert "at" in j["events"][0]

    def test_load_journey_returns_default_when_missing(self, isolated_papergraph_dir):
        from research_companion.journey import load_journey
        j = load_journey()
        assert j["version"] == 1
        assert j["draft_versions"] == []
        assert j["events"] == []
