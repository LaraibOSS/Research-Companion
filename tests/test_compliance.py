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
