"""Reference-checker benchmark harness.

The harness exists to put a number on the checker, so most of what is pinned
here is the arithmetic and the honesty of that number: an entry no catalogue
answered for is excluded from both rates, rates carry their denominators, and
malformed rows are reported rather than dropped. The smoke set's results are
pinned through the real parse -> lookup -> validate path.
"""
from __future__ import annotations

import json

import pytest

from research_companion.eval import refcheck_bench as rb
from research_companion.eval._common import BenchFormatError, fmt_rate, rate


def _row(label, status, checked=True, type_=None):
    return {"label": label, "status": status, "checked": checked,
            "type": type_ or label, "outcome": rb._outcome(label, status, checked)}


def _write(tmp_path, lines, name="bench.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n",
                 encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# metrics arithmetic
# ---------------------------------------------------------------------------

def test_rates_state_their_denominator_and_unreachable_is_excluded():
    rows = [
        _row("fabricated", "suspect"), _row("fabricated", "unverified"),
        _row("fabricated", "verified"),
        _row("fabricated", "unverified", checked=False),   # outage
        _row("real", "verified"), _row("real", "verified"), _row("real", "verified"),
        _row("real", "suspect"),
        _row("real", "unverified", checked=False), _row("real", "unverified", checked=False),
    ]
    m = rb.summarize(rows)
    assert m["fabricated"] == {
        "total": 4, "checked": 3, "detected": 2, "detected_as_suspect": 1,
        "detected_as_not_found": 1, "missed": 1, "detection_rate": 0.6667}
    assert m["real"] == {
        "total": 6, "checked": 4, "accepted": 3, "falsely_accused": 1,
        "accused_as_suspect": 1, "accused_as_not_found": 0,
        "false_accusation_rate": 0.25}
    # The three unreachable entries are neither passes nor failures.
    assert m["not_checked"] == {"total": 3, "real": 2, "fabricated": 1}
    assert m["confusion_matrix"]["real"] == {
        "verified": 3, "suspect": 1, "unverified": 0, "not_checked": 2}
    assert m["confusion_matrix"]["fabricated"]["not_checked"] == 1


def test_an_all_unreachable_run_reports_no_rate_rather_than_zero():
    m = rb.summarize([_row("real", "unverified", checked=False),
                      _row("fabricated", "unverified", checked=False)])
    assert m["real"]["false_accusation_rate"] is None
    assert m["fabricated"]["detection_rate"] is None
    assert rate(0, 0) is None
    assert fmt_rate(0, 0) == "n/a (0 checked)"
    assert fmt_rate(1, 3) == "33.3% (1 of 3 checked)"


def test_per_type_breakdown_keeps_each_label_and_its_own_rate():
    rows = [
        _row("fabricated", "verified", type_="wrong_year"),
        _row("fabricated", "suspect", type_="wrong_year"),
        _row("fabricated", "unverified", checked=False, type_="wrong_year"),
        _row("fabricated", "unverified", type_="invented_title"),
        _row("real", "verified", type_="valid"),
        _row("real", "unverified", type_="valid"),
    ]
    per = {(g["type"], g["label"]): g for g in rb.summarize(rows)["per_type"]}
    assert per[("wrong_year", "fabricated")] == {
        "type": "wrong_year", "label": "fabricated", "total": 3, "checked": 2,
        "not_checked": 1, "flagged": 1, "rate_name": "detection_rate", "rate": 0.5}
    assert per[("invented_title", "fabricated")]["rate"] == 1.0
    assert per[("valid", "real")]["rate_name"] == "false_accusation_rate"
    assert per[("valid", "real")]["rate"] == 0.5


# ---------------------------------------------------------------------------
# input formats
# ---------------------------------------------------------------------------

def test_jsonl_malformed_rows_are_reported_with_line_numbers(tmp_path):
    p = _write(tmp_path, [
        {"entry": "A. Author. A real enough title for the parser. Venue, 2020.", "label": "real"},
        "{not json",
        "[1, 2]",
        {"entry": "", "label": "real"},
        {"entry": "Something", "label": "maybe"},
        {"entry": "@article{x, author={A}}", "label": "fabricated"},   # BibTeX with no title
        {"entry": "B. Writer. Another long title. Venue, 2021.", "label": "FABRICATED",
         "type": "invented_title"},
    ])
    loaded = rb.load_entries(p)
    assert loaded.format == "jsonl"
    assert [(e.line, e.label, e.type) for e in loaded.entries] == [
        (1, "real", "real"), (7, "fabricated", "invented_title")]
    errors = {s["line"]: s["error"] for s in loaded.skipped}
    assert set(errors) == {2, 3, 4, 5, 6}
    assert "not valid JSON" in errors[2]
    assert "not a JSON object" in errors[3]
    assert '"entry"' in errors[4]
    assert '"label"' in errors[5]
    assert "no title" in errors[6]


def test_a_file_in_neither_format_fails_naming_the_expected_fields(tmp_path):
    p = _write(tmp_path, [{"citation": "x", "truth": 1}])
    with pytest.raises(BenchFormatError) as exc:
        rb.load_entries(p)
    msg = str(exc.value)
    for field in ('"entry"', '"label"', '"bibtex"', '"fields"', '"is_hallucinated"',
                  '"hallucination_type"'):
        assert field in msg


def test_a_jsonl_file_with_no_usable_row_names_the_fields(tmp_path):
    p = _write(tmp_path, [{"entry": "x", "label": "nope"}])
    with pytest.raises(BenchFormatError, match='"label": "real" \\| "fabricated"'):
        rb.load_entries(p, "jsonl")


HALLMARK_ROWS = [
    {"bibtex": "@inproceedings{v17, title={Attention Is All You Need}, "
               "author={Vaswani, Ashish and Shazeer, Noam}, booktitle={NeurIPS}, year={2017}}",
     "label": "VALID"},
    {"fields": {"title": "Layer Normalization", "author": "Kowalczyk, Marta and Osei, Daniel",
                "journal": "arXiv preprint arXiv:1607.06450", "year": "2016"},
     "label": "HALLUCINATED", "hallucination_type": "author_mismatch"},
    {"bibtex_entry": "@article{k, title={Some Invented Title}, author={Doe, J}, year={2020}}",
     "is_hallucinated": True},
    {"bibtex": "@article{k, title={T}, year={2020}}", "label": "UNSURE"},
    {"label": "VALID"},
]


def test_hallmark_adapter_maps_entries_labels_and_types(tmp_path):
    p = _write(tmp_path, HALLMARK_ROWS)
    loaded = rb.load_entries(p)
    assert loaded.format == "hallmark"
    assert [(e.label, e.type) for e in loaded.entries] == [
        ("real", "valid"), ("fabricated", "author_mismatch"), ("fabricated", "untyped")]
    ref = loaded.entries[1].reference
    assert ref.title == "Layer Normalization"
    assert ref.authors == ["Marta Kowalczyk", "Daniel Osei"]
    assert ref.arxiv_id == "1607.06450"
    assert ref.year == 2016
    assert ref.raw.startswith("Marta Kowalczyk, Daniel Osei. Layer Normalization.")
    errors = {s["line"]: s["error"] for s in loaded.skipped}
    assert "UNSURE" in errors[4]
    assert '"bibtex"' in errors[5] and '"fields"' in errors[5]


def test_bibtex_entry_keeps_structured_authors_and_identifiers():
    ref = rb.reference_from_entry(
        "@article{a, title={{BERT}: Pre-training}, author={Devlin, Jacob and Ming-Wei Chang},"
        " doi={https://doi.org/10.18653/v1/N19-1423}, eprint={1810.04805v2}, year={2019}}")
    assert ref.title == "BERT: Pre-training"
    assert ref.authors == ["Jacob Devlin", "Ming-Wei Chang"]
    assert ref.doi == "10.18653/v1/N19-1423"
    assert ref.arxiv_id == "1810.04805"
    # A plain line goes through the production line parser instead.
    line = rb.reference_from_entry("Smith. A title. arXiv:1607.06450, 2016.")
    assert line.arxiv_id == "1607.06450" and line.authors == []


def test_an_unreachable_catalogue_is_not_checked_not_a_failure(tmp_path):
    """Through the real validator: a lookup that cannot reach anything yields
    "unverified", and the harness must not score that as a detection."""
    p = _write(tmp_path, [
        {"entry": "A. Person. An invented paper about nothing at all. Venue, 2020.",
         "label": "fabricated"},
        {"entry": "B. Person. A real paper title of reasonable length. Venue, 2020.",
         "label": "real"},
    ])

    def down(_ref):
        raise ConnectionError("catalogue unreachable")

    result = rb.evaluate(p, down)
    assert [r["outcome"] for r in result["rows"]] == ["not_checked", "not_checked"]
    assert all(r["status"] == "unverified" for r in result["rows"])
    m = result["metrics"]
    assert m["fabricated"]["detection_rate"] is None
    assert m["real"]["false_accusation_rate"] is None
    assert m["not_checked"]["total"] == 2


# ---------------------------------------------------------------------------
# live lookup: caching, rate limiting, --limit
# ---------------------------------------------------------------------------

def _fake_sources(calls, *, crossref_down=False):
    from research_companion.refcheck import retrieval as r

    item = {"title": ["Attention Is All You Need"],
            "author": [{"given": "Ashish", "family": "Vaswani"}],
            "issued": {"date-parts": [[2017]]}}

    def crossref(query, **_):
        calls.append(("crossref", query))
        if crossref_down:
            r._record_transport_failure("crossref", ConnectionError("down"))
            return []
        return [item] if "attention" in query.lower() else []

    def openalex(query, **_):
        calls.append(("openalex", query))
        return []

    def arxiv(arxiv_id):
        calls.append(("arxiv", arxiv_id))
        return None

    return {"crossref_search": crossref, "openalex_search": openalex, "arxiv_fetch": arxiv}


def _cases(tmp_path):
    return _write(tmp_path, [
        {"entry": "Ashish Vaswani. Attention is all you need. NeurIPS, 2017.", "label": "real"},
        {"entry": "Q. Nobody. Spectral frobnication of imaginary widgets. ICML, 2020.",
         "label": "fabricated"},
        {"entry": "Z. Third. A third entry that the limit should cut off. ACL, 2019.",
         "label": "fabricated"},
    ])


def test_cache_replays_responses_and_a_resumed_run_asks_nothing(tmp_path):
    cases, cache_file = _cases(tmp_path), tmp_path / "cache.jsonl"
    calls, sleeps = [], []
    first = rb.evaluate(cases, rb.build_live_lookup(
        cache=rb.CatalogueCache(cache_file), delay=0.5, sleep=sleeps.append,
        **_fake_sources(calls)), limit=2)
    assert first["metrics"]["entries_run"] == 2 and first["usable_rows"] == 3
    assert [r["status"] for r in first["rows"]] == ["verified", "unverified"]
    assert calls == [("crossref", "Attention is all you need"),
                     ("crossref", "Spectral frobnication of imaginary widgets"),
                     ("openalex", "Spectral frobnication of imaginary widgets")]
    # Sequential and spaced: a pause before every network call but the first.
    assert sleeps == [0.5, 0.5]

    calls2 = []
    cache = rb.CatalogueCache(cache_file)
    assert len(cache) == 3
    second = rb.evaluate(cases, rb.build_live_lookup(
        cache=cache, delay=0.5, sleep=lambda s: None, **_fake_sources(calls2)), limit=2)
    assert calls2 == []
    assert cache.hits == 3
    assert [r["status"] for r in second["rows"]] == ["verified", "unverified"]


def test_an_outage_is_never_cached(tmp_path):
    cases, cache_file = _cases(tmp_path), tmp_path / "cache.jsonl"
    calls = []
    result = rb.evaluate(cases, rb.build_live_lookup(
        cache=rb.CatalogueCache(cache_file), delay=0, **_fake_sources(calls, crossref_down=True)),
        limit=1)
    assert result["rows"][0]["outcome"] == "not_checked"
    # openalex answered, crossref did not: only the answer is recorded.
    recorded = [json.loads(x)["source"] for x in cache_file.read_text("utf-8").splitlines()]
    assert recorded == ["openalex"]


def test_a_truncated_cache_line_from_an_interrupted_run_is_ignored(tmp_path):
    cache_file = tmp_path / "cache.jsonl"
    good = json.dumps({"source": "crossref", "query": "q", "response": []})
    cache_file.write_text(good + "\n" + '{"source": "crossr', encoding="utf-8")
    cache = rb.CatalogueCache(cache_file)
    assert cache.unreadable_lines == 1
    assert cache.get("crossref", "q") == (True, [])
    cache.put("openalex", "q2", [])
    reloaded = rb.CatalogueCache(cache_file)
    assert reloaded.get("openalex", "q2") == (True, [])
    assert reloaded.unreadable_lines == 1
