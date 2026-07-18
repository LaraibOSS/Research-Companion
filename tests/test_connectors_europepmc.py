from research_companion.connectors.europepmc import (
    EuropePMCConnector,
    jats_to_text,
    parse_europepmc_result,
)
from research_companion.refcheck.validate import Reference

_RESULT = {
    "title": "CRISPR screening in T cells",
    "authorString": "Shifrut E, Carnevale J",
    "pubYear": "2018",
    "doi": "10.1016/j.cell.2018.10.024",
    "pmid": "30449619",
    "pmcid": "PMC6289601",
}


def test_parse_europepmc_result_maps_record_shape():
    rec = parse_europepmc_result(_RESULT)
    assert rec["title"] == "CRISPR screening in T cells"
    assert rec["authors"] == ["Shifrut E", "Carnevale J"]
    assert rec["year"] == 2018
    assert rec["doi"] == "10.1016/j.cell.2018.10.024"
    assert rec["pmid"] == "30449619"
    assert rec["pmcid"] == "PMC6289601"
    assert rec["arxiv_id"] is None


def test_parse_handles_missing_fields():
    rec = parse_europepmc_result({"title": "T"})
    assert rec["authors"] == [] and rec["year"] is None and rec["doi"] is None


def test_parse_europepmc_result_carries_abstract():
    rec = parse_europepmc_result({**_RESULT, "abstractText": "X"})
    assert rec["abstract"] == "X"


def test_jats_to_text_keeps_headings_and_paragraphs_skips_refs_tables():
    xml = """<article><body>
      <sec><title>Methods</title><p>We did <italic>things</italic>.</p>
        <table-wrap><table><tr><td>skip me</td></tr></table></table-wrap></sec>
      <sec><title>Results</title><p>It worked.</p></sec>
      <ref-list><ref>skip citation</ref></ref-list>
    </body></article>"""
    text = jats_to_text(xml)
    assert "Methods" in text and "We did things." in text
    assert "Results" in text and "It worked." in text
    assert "skip me" not in text and "skip citation" not in text


def test_connector_resolve_uses_injected_search_and_best_title_match():
    conn = EuropePMCConnector(search=lambda q, **kw: [_RESULT])
    rec = conn.resolve(Reference(title="CRISPR screening in T cells"))
    assert rec["pmid"] == "30449619"


def test_connector_resolve_none_on_poor_match():
    conn = EuropePMCConnector(search=lambda q, **kw: [_RESULT])
    assert conn.resolve(Reference(title="Totally unrelated frog paper")) is None


def test_connector_search_returns_discovered_papers():
    conn = EuropePMCConnector(search=lambda q, **kw: [_RESULT])
    papers = conn.search("crispr t cells", limit=5)
    assert papers[0].title == "CRISPR screening in T cells"
    assert papers[0].pmid == "30449619"


def test_connector_fetch_fulltext_none_when_not_open_access():
    conn = EuropePMCConnector(fetch_xml=lambda pmcid: None)
    assert conn.fetch_fulltext("PMC0000000") is None
