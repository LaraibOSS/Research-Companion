from research_companion.connectors.pubmed import PubMedConnector, parse_esummary_doc
from research_companion.refcheck.validate import Reference

_DOC = {
    "uid": "30449619",
    "title": "Genome-wide CRISPR screens in primary human T cells.",
    "authors": [{"name": "Shifrut E"}, {"name": "Carnevale J"}],
    "pubdate": "2018 Dec 13",
    "articleids": [{"idtype": "doi", "value": "10.1016/j.cell.2018.10.024"},
                   {"idtype": "pmcid", "value": "PMC6289601"}],
}


def test_parse_esummary_doc_maps_record():
    rec = parse_esummary_doc(_DOC)
    assert rec["pmid"] == "30449619"
    assert rec["year"] == 2018
    assert rec["doi"] == "10.1016/j.cell.2018.10.024"
    assert rec["pmcid"] == "PMC6289601"
    assert rec["authors"] == ["Shifrut E", "Carnevale J"]


def test_resolve_by_pmid_skips_search():
    def _boom_search(q, **kw):
        raise AssertionError("search must not run when the ref already has a PMID")
    conn = PubMedConnector(esearch=_boom_search, esummary=lambda ids: {"30449619": _DOC})
    rec = conn.resolve(Reference(title="whatever", pmid="30449619"))
    assert rec["pmid"] == "30449619"


def test_resolve_by_title_search_when_no_pmid():
    conn = PubMedConnector(esearch=lambda q, **kw: ["30449619"],
                           esummary=lambda ids: {"30449619": _DOC})
    rec = conn.resolve(Reference(title="Genome-wide CRISPR screens in primary human T cells"))
    assert rec["pmid"] == "30449619"


def test_resolve_none_when_search_empty():
    conn = PubMedConnector(esearch=lambda q, **kw: [], esummary=lambda ids: {})
    assert conn.resolve(Reference(title="nothing here")) is None
