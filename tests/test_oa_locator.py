"""oa_locator: pure parsers + orchestration. All offline (seams injected)."""
from research_companion.oa_locator import (
    _derive_ids,
    _parse_openalex,
    _parse_s2,
    _parse_unpaywall,
    locate_pdf,
)
from research_companion.store import PaperMetadata


def _meta(paper_id="doi:10.1234/x", title="A Sample Paper", source_url=""):
    return PaperMetadata(paper_id=paper_id, title=title, authors=["A"], source_url=source_url)


# ---------- identifier derivation ----------

def test_derive_ids_doi_arxiv_s2():
    assert _derive_ids(_meta("doi:10.18653/v1/2021.naacl-main.168")) == {
        "doi": "10.18653/v1/2021.naacl-main.168", "arxiv": None, "s2": None}
    assert _derive_ids(_meta("arxiv:1603.08983"))["arxiv"] == "1603.08983"
    assert _derive_ids(_meta("s2:abc123def"))["s2"] == "abc123def"

def test_derive_ids_local_paper_has_none():
    ids = _derive_ids(_meta("local:deadbeef"))
    assert ids == {"doi": None, "arxiv": None, "s2": None}


# ---------- pure parsers (fixtures = captured API shapes) ----------

S2_HIT = {"title": "A Sample Paper",
          "openAccessPdf": {"url": "https://aclanthology.org/x.pdf", "status": "GOLD"},
          "externalIds": {"ArXiv": "2101.00001"},
          "paperId": "abc123def"}
S2_MISS = {"title": "A Sample Paper", "openAccessPdf": None, "externalIds": {}}

def test_parse_s2_hit_and_miss():
    hit = _parse_s2(S2_HIT)
    assert hit["pdf_url"] == "https://aclanthology.org/x.pdf"
    assert hit["arxiv"] == "2101.00001"
    assert hit["landing"] == "https://www.semanticscholar.org/paper/abc123def"
    miss = _parse_s2(S2_MISS)
    assert miss["pdf_url"] is None
    assert _parse_s2(None) == {"pdf_url": None, "landing": None, "arxiv": None}

UPW_HIT = {"best_oa_location": {"url_for_pdf": "https://repo.org/y.pdf",
                                "url_for_landing_page": "https://repo.org/y"}}
UPW_MISS = {"best_oa_location": None}

def test_parse_unpaywall():
    assert _parse_unpaywall(UPW_HIT)["pdf_url"] == "https://repo.org/y.pdf"
    assert _parse_unpaywall(UPW_MISS) == {"pdf_url": None, "landing": None}
    assert _parse_unpaywall(None) == {"pdf_url": None, "landing": None}

OAX_HIT = {"best_oa_location": {"pdf_url": "https://oa.org/z.pdf",
                                "landing_page_url": "https://oa.org/z"},
           "ids": {"openalex": "https://openalex.org/W1"}}

def test_parse_openalex():
    assert _parse_openalex(OAX_HIT)["pdf_url"] == "https://oa.org/z.pdf"
    assert _parse_openalex({"best_oa_location": None})["pdf_url"] is None
    assert _parse_openalex(None) == {"pdf_url": None, "landing": None}


# ---------- orchestration ----------

def test_locate_stops_at_first_pdf(monkeypatch):
    import research_companion.oa_locator as oa
    calls = []
    monkeypatch.setattr(oa, "_fetch_s2", lambda ids, title: (calls.append("s2"), S2_HIT)[1])
    monkeypatch.setattr(oa, "_fetch_unpaywall", lambda doi, email: (calls.append("upw"), UPW_HIT)[1])
    monkeypatch.setattr(oa, "_fetch_openalex", lambda ids, title: (calls.append("oax"), OAX_HIT)[1])
    loc = locate_pdf(_meta(), settings={"contact_email": "a@b.c"})
    assert loc.pdf_url == "https://aclanthology.org/x.pdf"
    assert loc.source == "s2"
    assert calls == ["s2"]  # stopped — unpaywall/openalex never called

def test_locate_collects_links_when_no_pdf(monkeypatch):
    import research_companion.oa_locator as oa
    monkeypatch.setattr(oa, "_fetch_s2", lambda ids, title: S2_MISS)
    monkeypatch.setattr(oa, "_fetch_unpaywall", lambda doi, email: UPW_MISS)
    monkeypatch.setattr(oa, "_fetch_openalex", lambda ids, title: {"best_oa_location": {"pdf_url": None, "landing_page_url": "https://oa.org/z"}})
    loc = locate_pdf(_meta("doi:10.1/x", title="Sample T"), settings={"contact_email": "a@b.c"})
    assert loc.pdf_url is None
    urls = [link["url"] for link in loc.links]
    assert "https://oa.org/z" in urls
    assert "https://doi.org/10.1/x" in urls                       # DOI page fallback
    assert any("scholar.google.com" in u for u in urls)           # Scholar search fallback
    labels = [link["label"] for link in loc.links]
    assert "Google Scholar" in labels

def test_locate_skips_unpaywall_without_email(monkeypatch):
    import research_companion.oa_locator as oa
    called = []
    monkeypatch.setattr(oa, "_fetch_s2", lambda ids, title: S2_MISS)
    monkeypatch.setattr(oa, "_fetch_unpaywall", lambda doi, email: called.append(1) or None)
    monkeypatch.setattr(oa, "_fetch_openalex", lambda ids, title: None)
    locate_pdf(_meta(), settings={"contact_email": ""})
    assert called == []

def test_locate_arxiv_id_surfaced_by_s2_yields_direct_pdf(monkeypatch):
    import research_companion.oa_locator as oa
    s2_no_pdf_but_arxiv = {"title": "t", "openAccessPdf": None,
                           "externalIds": {"ArXiv": "1603.08983"}, "paperId": "p1"}
    monkeypatch.setattr(oa, "_fetch_s2", lambda ids, title: s2_no_pdf_but_arxiv)
    monkeypatch.setattr(oa, "_fetch_unpaywall", lambda doi, email: None)
    monkeypatch.setattr(oa, "_fetch_openalex", lambda ids, title: None)
    loc = locate_pdf(_meta(), settings={"contact_email": ""})
    assert loc.pdf_url == "https://arxiv.org/pdf/1603.08983"
    assert loc.source == "arxiv"

def test_locate_all_fail_is_empty_plus_string_fallback_links(monkeypatch):
    import research_companion.oa_locator as oa
    monkeypatch.setattr(oa, "_fetch_s2", lambda ids, title: None)
    monkeypatch.setattr(oa, "_fetch_unpaywall", lambda doi, email: None)
    monkeypatch.setattr(oa, "_fetch_openalex", lambda ids, title: None)
    loc = locate_pdf(_meta("local:abc", title="Only A Title"), settings={"contact_email": ""})
    assert loc.pdf_url is None and loc.source is None
    assert [link["label"] for link in loc.links] == ["Google Scholar"]  # no DOI ⇒ Scholar only

def test_extra_ids_doi_enables_unpaywall_for_s2_paper(monkeypatch):
    """An s2: paper has no derivable DOI on its own, so unpaywall is normally
    skipped. extra_ids={"doi": ...} (from the caller's already-fetched
    external_ids) must merge over the derived ids and unlock it."""
    import research_companion.oa_locator as oa
    calls = []
    monkeypatch.setattr(oa, "_fetch_s2", lambda ids, title: S2_MISS)
    def fake_unpaywall(doi, email):
        calls.append(doi)
        return UPW_HIT
    monkeypatch.setattr(oa, "_fetch_unpaywall", fake_unpaywall)
    monkeypatch.setattr(oa, "_fetch_openalex", lambda ids, title: None)
    loc = locate_pdf(_meta("s2:abc123def"), settings={"contact_email": "a@b.c"},
                      extra_ids={"doi": "10.1/x"})
    assert calls == ["10.1/x"]
    assert loc.pdf_url == "https://repo.org/y.pdf"
    assert loc.source == "unpaywall"


def test_extra_ids_arxiv_suppresses_arxiv_fallback_retry(monkeypatch):
    """When the caller already knows the arXiv id (and already tried it
    directly, per fetch.add_s2), extra_ids={"arxiv": ...} must make
    ids.get("arxiv") truthy so the arxiv-fallback branch does not redundantly
    retry the same id."""
    import research_companion.oa_locator as oa
    s2_no_pdf_but_arxiv = {"title": "t", "openAccessPdf": None,
                           "externalIds": {"ArXiv": "1603.08983"}, "paperId": "p1"}
    monkeypatch.setattr(oa, "_fetch_s2", lambda ids, title: s2_no_pdf_but_arxiv)
    monkeypatch.setattr(oa, "_fetch_unpaywall", lambda doi, email: None)
    monkeypatch.setattr(oa, "_fetch_openalex", lambda ids, title: None)
    loc = locate_pdf(_meta("s2:abc123def"), settings={"contact_email": ""},
                      extra_ids={"arxiv": "1603.08983"})
    assert loc.pdf_url is None
    assert loc.source is None


def test_links_dedup_by_url(monkeypatch):
    import research_companion.oa_locator as oa
    dup = {"best_oa_location": {"pdf_url": None, "landing_page_url": "https://doi.org/10.1/x"}}
    monkeypatch.setattr(oa, "_fetch_s2", lambda ids, title: None)
    monkeypatch.setattr(oa, "_fetch_unpaywall", lambda doi, email: None)
    monkeypatch.setattr(oa, "_fetch_openalex", lambda ids, title: dup)
    loc = locate_pdf(_meta("doi:10.1/x"), settings={"contact_email": ""})
    assert len([link for link in loc.links if link["url"] == "https://doi.org/10.1/x"]) == 1
