from research_companion.nudge import connectors_nudge
from research_companion.refcheck.validate import Reference


def test_nudge_when_pmid_refs_and_connectors_off():
    refs = [Reference(title="a", pmid="1"), Reference(title="b")]
    msg = connectors_nudge(refs, enabled=set(), discipline=None)
    assert msg and "biomedical" in msg.lower()


def test_nudge_when_biomedical_discipline_off():
    msg = connectors_nudge([Reference(title="a")], enabled=set(), discipline="biomedical")
    assert msg is not None


def test_no_nudge_when_connectors_enabled():
    refs = [Reference(title="a", pmid="1")]
    assert connectors_nudge(refs, enabled={"pubmed"}, discipline="biomedical") is None


def test_no_nudge_when_no_signal():
    assert connectors_nudge([Reference(title="a")], enabled=set(), discipline="ml") is None


def _ref(pmid=None):
    from research_companion.refcheck.validate import Reference
    r = Reference(title="t", authors=[], year=None)
    if pmid:
        r.pmid = pmid
    return r


def test_dblp_nudge_fires_for_cs_paper_with_unverified_refs():
    from research_companion.nudge import connectors_nudge
    msg = connectors_nudge([_ref()], enabled=set(), discipline="machine_learning",
                           n_unverified=3)
    assert msg is not None and "dblp" in msg.lower()


def test_dblp_nudge_silent_when_all_verified():
    from research_companion.nudge import connectors_nudge
    assert connectors_nudge([_ref()], enabled=set(), discipline="nlp",
                            n_unverified=0) is None


def test_dblp_nudge_silent_when_dblp_enabled():
    from research_companion.nudge import connectors_nudge
    assert connectors_nudge([_ref()], enabled={"dblp"}, discipline="nlp",
                            n_unverified=5) is None


def test_dblp_nudge_fires_even_when_biomed_connector_enabled():
    # A CS paper with europepmc on but dblp off should still be nudged toward dblp.
    from research_companion.nudge import connectors_nudge
    msg = connectors_nudge([_ref()], enabled={"europepmc"}, discipline="computer_vision",
                           n_unverified=2)
    assert msg is not None and "dblp" in msg.lower()


def test_biomed_precedence_when_both_could_fire():
    # biomedical discipline is not in CS_DISCIPLINES, but a pmid ref + CS-less disc → biomed wins
    from research_companion.nudge import connectors_nudge
    msg = connectors_nudge([_ref(pmid="123")], enabled=set(), discipline="biomedical",
                           n_unverified=2)
    assert "PubMed/Europe PMC" in msg


def test_non_cs_non_biomed_no_nudge():
    from research_companion.nudge import connectors_nudge
    assert connectors_nudge([_ref()], enabled=set(), discipline="economics",
                            n_unverified=4) is None
