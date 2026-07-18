from dataclasses import dataclass

from research_companion.compliance import DISCLAIMER, check_compliance
from research_companion.venues import Venue


def _v(**kw):
    base = dict(slug="v", name="V", kind="conference", scope="")
    base.update(kw)
    return Venue(**base)

def _find(res, name):
    return next(c for c in res["checks"] if c["check"] == name)

def test_page_over_limit_is_desk_reject():
    res = check_compliance(_v(page_limit=8), fulltext="body", page_count=14)
    c = _find(res, "page_limit")
    assert c["status"] == "finding" and c["severity"] == "desk_reject"
    assert res["counts"]["desk_reject"] == 1
    assert res["disclaimer"] == DISCLAIMER

def test_page_within_slack_is_ok():
    # limit 8, slack 4 -> up to 12 pages passes
    res = check_compliance(_v(page_limit=8), fulltext="body", page_count=11)
    assert _find(res, "page_limit")["status"] == "ok"

def test_page_skipped_without_pdf():
    res = check_compliance(_v(page_limit=8), fulltext="body", page_count=None)
    c = _find(res, "page_limit")
    assert c["status"] == "skipped" and "no PDF" in c["message"]

def test_page_skipped_when_venue_has_no_limit():
    res = check_compliance(_v(), fulltext="body", page_count=20)
    assert _find(res, "page_limit")["status"] == "skipped"

def test_abstract_over_limit_is_warning():
    res = check_compliance(_v(abstract_word_limit=5), fulltext="b",
                           abstract="one two three four five six seven")
    c = _find(res, "abstract_word_limit")
    assert c["status"] == "finding" and c["severity"] == "warning"

@dataclass
class _S:  # minimal stand-in for sections.Section
    title: str

def test_required_section_present_via_tree():
    v = _v(required_sections=(("limitations",),))
    res = check_compliance(v, fulltext="x", sections=[_S("5. Limitations"), _S("Introduction")])
    assert _find(res, "section:limitations")["status"] == "ok"

def test_required_section_missing_is_desk_reject():
    v = _v(required_sections=(("limitations",),))
    res = check_compliance(v, fulltext="Intro\nResults\n", sections=[_S("Introduction")])
    c = _find(res, "section:limitations")
    assert c["status"] == "finding" and c["severity"] == "desk_reject"

def test_required_section_synonym_group_any_match():
    v = _v(required_sections=(("broader impact", "ethics statement"),))
    res = check_compliance(v, fulltext="x", sections=[_S("Ethics Statement")])
    assert _find(res, "section:broader impact")["status"] == "ok"

def test_required_section_fulltext_fallback():
    # section missed by the tree but present as a heading-like line in fulltext
    v = _v(required_sections=(("limitations",),))
    res = check_compliance(v, fulltext="Intro text\nLimitations\nWe discuss...\n", sections=[])
    assert _find(res, "section:limitations")["status"] == "ok"

def test_required_section_fulltext_fallback_rejects_prose():
    v = _v(required_sections=(("limitations",),))
    res = check_compliance(v, fulltext="Limitations of this dataset are notable in practice.\n", sections=[])
    c = _find(res, "section:limitations")
    assert c["status"] == "finding" and c["severity"] == "desk_reject"

def test_required_section_fulltext_fallback_accepts_heading_with_colon():
    v = _v(required_sections=(("limitations",),))
    res = check_compliance(v, fulltext="Body\nLimitations:\nWe note...\n", sections=[])
    assert _find(res, "section:limitations")["status"] == "ok"

def test_required_sections_skipped_when_venue_has_none():
    res = check_compliance(_v(), fulltext="x", sections=[])
    assert _find(res, "required_sections")["status"] == "skipped"

def test_anonymization_skipped_when_not_blind():
    res = check_compliance(_v(anonymized=False), fulltext="a@b.com")
    assert _find(res, "anonymization")["status"] == "skipped"

def test_anonymization_flags_email_in_header():
    res = check_compliance(_v(anonymized=True), fulltext="Title\njane@univ.edu\nBody")
    hits = [c for c in res["checks"] if c["check"] == "anonymization" and c["status"] == "finding"]
    assert hits and all(c["severity"] == "warning" for c in hits)

def test_anonymization_flags_self_reference():
    res = check_compliance(_v(anonymized=True),
                           fulltext="In our previous work [3] we showed X.")
    assert any(c["check"] == "anonymization" and c["status"] == "finding" for c in res["checks"])

def test_anonymization_clean_is_ok():
    res = check_compliance(_v(anonymized=True), fulltext="A fully blind body with no leaks.")
    assert _find(res, "anonymization")["status"] == "ok"
