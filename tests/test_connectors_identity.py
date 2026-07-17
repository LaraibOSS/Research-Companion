from research_companion.connectors import identity


def test_canonical_id_precedence_doi_first():
    rec = {"doi": "10.1/x", "pmid": "123", "pmcid": "PMC9", "arxiv_id": "2401.00001", "title": "T"}
    assert identity.canonical_id(rec) == "doi:10.1/x"


def test_canonical_id_falls_through_to_pmid_then_pmcid_then_arxiv():
    assert identity.canonical_id({"pmid": "123", "title": "T"}) == "pmid:123"
    assert identity.canonical_id({"pmcid": "PMC9", "title": "T"}) == "pmcid:PMC9"
    assert identity.canonical_id({"arxiv_id": "2401.00001", "title": "T"}) == "arxiv:2401.00001"


def test_canonical_id_title_hash_when_no_identifiers():
    cid = identity.canonical_id({"title": "Deep Learning"})
    assert cid.startswith("title:")
    # stable + normalization-insensitive
    assert cid == identity.canonical_id({"title": "  deep   learning "})


def test_alt_ids_collects_all_present_namespaced():
    rec = {"doi": "10.1/x", "pmid": "123", "arxiv_id": "2401.00001", "title": "T"}
    assert identity.alt_ids(rec) == {"doi:10.1/x", "pmid:123", "arxiv:2401.00001"}


def test_preprint_published_warning_when_both_doi_and_arxiv():
    assert identity.preprint_published_warning(
        {"doi": "10.1/x", "arxiv_id": "2401.00001"}) is not None
    assert identity.preprint_published_warning({"doi": "10.1/x"}) is None
