"""DBLP connector — pure parsers + seam-injected class (all offline)."""
from research_companion.connectors.dblp import (
    DBLPConnector,
    _arxiv_from_ee,
    dblp_url,
    parse_dblp_hit,
)
from research_companion.refcheck.validate import Reference

_HIT = {
    "info": {
        "authors": {"author": [
            {"@pid": "1/2", "text": "Ashish Vaswani"},
            {"@pid": "3/4", "text": "Noam Shazeer 0001"},
        ]},
        "title": "Attention Is All You Need.",
        "venue": "NeurIPS",
        "year": "2017",
        "key": "conf/nips/VaswaniSPUJGKP17",
        "doi": "10.5555/3295222.3295349",
        "ee": "https://arxiv.org/abs/1706.03762",
        "url": "https://dblp.org/rec/conf/nips/VaswaniSPUJGKP17",
    },
}


def test_parse_hit_maps_record_shape_and_strips_author_suffix():
    rec = parse_dblp_hit(_HIT)
    assert rec["title"] == "Attention Is All You Need"       # trailing period stripped
    assert rec["authors"] == ["Ashish Vaswani", "Noam Shazeer"]  # " 0001" stripped
    assert rec["year"] == 2017
    assert rec["doi"] == "10.5555/3295222.3295349"
    assert rec["arxiv_id"] == "1706.03762"
    assert rec["pmid"] is None and rec["pmcid"] is None


def test_parse_hit_single_author_object():
    hit = {"info": {"title": "Solo.", "authors": {"author": {"@pid": "x", "text": "Solo Writer"}}}}
    assert parse_dblp_hit(hit)["authors"] == ["Solo Writer"]


def test_parse_hit_missing_authors_and_bad_year():
    hit = {"info": {"title": "No Authors.", "year": "n/a"}}
    rec = parse_dblp_hit(hit)
    assert rec["authors"] == []
    assert rec["year"] is None
    assert rec["doi"] is None and rec["arxiv_id"] is None


def test_arxiv_from_ee_forms():
    assert _arxiv_from_ee("https://arxiv.org/abs/1706.03762") == "1706.03762"
    assert _arxiv_from_ee(
        ["https://doi.org/10.1/x", "https://doi.org/10.48550/arXiv.2001.01234"]) == "2001.01234"
    assert _arxiv_from_ee("https://doi.org/10.1145/nonarxiv") is None
    assert _arxiv_from_ee(None) is None


def test_dblp_url_fallback():
    assert dblp_url(_HIT) == "https://dblp.org/rec/conf/nips/VaswaniSPUJGKP17"
    assert dblp_url({"info": {}}) == "https://dblp.org/"


def test_resolve_returns_record_on_good_title_match():
    conn = DBLPConnector(search=lambda q, **kw: [_HIT])
    ref = Reference(title="Attention Is All You Need", authors=[], year=None)
    rec = conn.resolve(ref)
    assert rec is not None and rec["doi"] == "10.5555/3295222.3295349"


def test_resolve_none_below_floor():
    conn = DBLPConnector(search=lambda q, **kw: [_HIT])
    ref = Reference(title="An Entirely Unrelated Paper About Marine Biology", authors=[], year=None)
    assert conn.resolve(ref) is None


def test_resolve_none_when_search_empty():
    conn = DBLPConnector(search=lambda q, **kw: [])
    assert conn.resolve(Reference(title="Whatever", authors=[], year=None)) is None


def test_search_builds_discovered_paper():
    conn = DBLPConnector(search=lambda q, **kw: [_HIT])
    out = conn.search("attention", limit=5)
    assert len(out) == 1
    p = out[0]
    assert p.source == "dblp" and p.citation_count == 0 and p.abstract == ""
    assert p.doi == "10.5555/3295222.3295349" and p.arxiv_id == "1706.03762"
    assert p.url == "https://dblp.org/rec/conf/nips/VaswaniSPUJGKP17"


def test_search_skips_empty_title_and_respects_limit():
    hits = [{"info": {"title": ""}}, _HIT, _HIT]
    conn = DBLPConnector(search=lambda q, **kw: hits)
    assert len(conn.search("q", limit=1)) == 1


def test_fetch_fulltext_always_none():
    assert DBLPConnector(search=lambda q, **kw: []).fetch_fulltext("anything") is None


class _RecordingLimiter:
    def __init__(self):
        self.waits = 0

    def wait(self):
        self.waits += 1


def test_resolve_and_search_wait_on_limiter():
    lim = _RecordingLimiter()
    conn = DBLPConnector(search=lambda q, **kw: [_HIT], limiter=lim)
    conn.resolve(Reference(title="Attention Is All You Need", authors=[], year=None))
    conn.search("attention", limit=3)
    assert lim.waits == 2


def test_parse_hit_non_dict_info_and_authors_do_not_raise():
    assert parse_dblp_hit({"info": "not-a-dict"})["authors"] == []
    rec = parse_dblp_hit({"info": {"title": "X", "authors": "weird-string"}})
    assert rec["authors"] == [] and rec["title"] == "X"


def test_dblp_url_non_dict_info():
    assert dblp_url({"info": "not-a-dict"}) == "https://dblp.org/"


def test_search_and_resolve_never_raise_on_odd_shapes():
    from research_companion.refcheck.validate import Reference

    hits = [{"info": {"title": "X", "authors": ["a", "b"]}}, {"info": "nope"}, {}]
    conn = DBLPConnector(search=lambda *a, **k: hits)
    conn.search("q", limit=5)  # must not raise
    conn.resolve(Reference(title="X", authors=[], year=None))  # must not raise


def test_arxiv_from_ee_strips_trailing_punctuation():
    assert _arxiv_from_ee("https://arxiv.org/abs/1706.03762.") == "1706.03762"
