from research_companion.nudge import connectors_nudge
from research_companion.refcheck.validate import Reference


def test_nudge_when_pmid_refs_and_connectors_off():
    refs = [Reference(title="a", pmid="1"), Reference(title="b")]
    msg = connectors_nudge(refs, connectors_enabled=False, discipline=None)
    assert msg and "biomedical" in msg.lower()


def test_nudge_when_biomedical_discipline_off():
    msg = connectors_nudge([Reference(title="a")], connectors_enabled=False, discipline="biomedical")
    assert msg is not None


def test_no_nudge_when_connectors_enabled():
    refs = [Reference(title="a", pmid="1")]
    assert connectors_nudge(refs, connectors_enabled=True, discipline="biomedical") is None


def test_no_nudge_when_no_signal():
    assert connectors_nudge([Reference(title="a")], connectors_enabled=False, discipline="ml") is None
