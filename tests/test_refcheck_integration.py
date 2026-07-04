"""End-to-end integration: real parsing + real validation over a bibliography.

No network and no validator stubbing — the only test double is a small in-memory
authoritative database searched by title similarity, standing in for CrossRef.
This exercises the full pipeline the `refcheck` command runs:
    related_work strings -> parse -> validate_bibliography -> verdicts.
"""
from __future__ import annotations

from research_companion.refcheck import matching
from research_companion.refcheck.parse import references_from_extraction
from research_companion.refcheck.validate import validate_bibliography

# A tiny authoritative "database" of real records.
_DB = [
    {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "year": 2017,
        "doi": "10.5555/3295222.3295349",
        "arxiv_id": "1706.03762",
    },
    {
        "title": "Deep Residual Learning for Image Recognition",
        "authors": ["Kaiming He"],
        "year": 2016,
        "doi": "10.1109/cvpr.2016.90",
        "arxiv_id": "1512.03385",
    },
]


def _db_lookup(ref):
    """Resolve a Reference to the best title match in _DB, mirroring a retriever."""
    best, best_score = None, -1.0
    for record in _DB:
        score = matching.title_similarity(ref.title, record["title"])
        if score > best_score:
            best, best_score = record, score
    return best if best_score >= 0.7 else None


def test_full_pipeline_classifies_a_realistic_bibliography():
    # As research-companion extraction produces: mostly clean titles, sometimes with an
    # identifier appended. One entry carries a wrong DOI; one is fabricated.
    extraction = {
        "related_work": [
            "Attention Is All You Need. arXiv:1706.03762",          # verified
            "Deep Residual Learning for Image Recognition. doi:10.9999/wrong",  # suspect: DOI conflict
            "A Fabricated Method That Was Never Actually Published",  # unverified
        ]
    }

    refs = references_from_extraction(extraction)
    report = validate_bibliography(refs, _db_lookup)

    assert report.counts() == {"verified": 1, "suspect": 1, "unverified": 1}

    by_status = {verdict.status: (ref, verdict) for ref, verdict in report.entries}
    # The arXiv id was parsed out and matches the record.
    assert by_status["verified"][0].arxiv_id == "1706.03762"
    # The suspect entry is flagged specifically for the DOI conflict.
    assert any("doi" in r.lower() for r in by_status["suspect"][1].reasons)
