"""Reference-checker benchmark: how often does refcheck catch a fabricated
reference, and how often does it accuse a real one?

No checker in this tool had a measured accuracy. The offline corruption
benchmark (``citation_pr``) is precise by construction and the live spot check
(``eval/live_spotcheck.py``) has only real inputs, so neither says how the
checker behaves on a labelled mix of real and fabricated entries. This does.

Every entry goes through the REAL validation path -- parse, lookup, validate --
exactly as a bibliography line does in ``research-companion refcheck``. Only
the catalogue behind the lookup is swappable:

* live (default): arXiv -> CrossRef -> OpenAlex, sequential, with a delay
  between network calls, optionally recording every catalogue response to a
  cache file so an interrupted run resumes without re-asking;
* ``--catalogue FILE``: an offline fixture of catalogue records, used by the
  shipped smoke set (``eval/cases/refcheck_smoke.jsonl``) and the tests.

The cache records raw catalogue RESPONSES, not verdicts or matched records, so
re-running after a matcher change re-measures the matcher instead of replaying
its old decisions. An outage is never cached.

Honesty rules the report follows (see ``eval/README.md``):

* fabricated entry detected = verdict ``suspect`` or ``unverified``;
  real entry accepted = verdict ``verified``;
* an entry whose catalogues could not be reached is NOT CHECKED: it is counted
  separately and excluded from both rates, never scored as a pass or a miss;
* every rate is printed with its denominator.

Input formats
-------------
``jsonl`` (native)::

    {"entry": "<bibliography line or BibTeX>", "label": "real"|"fabricated",
     "type": "<optional category>"}

``hallmark``: an adapter for the HALLMARK dataset (github.com/rpatrik96/hallmark,
MIT, 2,526 labelled BibTeX entries, 14 hallucination types). **The field
mapping is designed from HALLMARK's published description and has NOT been
verified against the real file**, which this project has not downloaded. It
accepts, per JSONL row: the entry as ``bibtex`` / ``bibtex_entry`` /
``raw_bibtex`` / ``entry`` (a BibTeX string) or ``fields`` (a dict of BibTeX
fields); the label as ``label`` (``VALID``/``HALLUCINATED``, case-insensitive;
``real``/``fabricated`` also accepted) or a boolean ``is_hallucinated``; the
type as ``hallucination_type`` / ``type`` / ``category``. If the real file
differs, loading fails with a message naming these fields -- adjust the adapter
rather than the data.

Run::

    python -m research_companion.eval.refcheck_bench FILE [--format auto|jsonl|hallmark]
        [--limit N] [--cache FILE] [--delay SECONDS] [--catalogue FIXTURE] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from research_companion.eval._common import BenchFormatError, fmt_rate, rate, read_jsonl
from research_companion.refcheck.validate import Reference, RefVerdict

LABELS = ("real", "fabricated")
VERDICTS = ("verified", "suspect", "unverified")

JSONL_EXPECTED = ('each line a JSON object: {"entry": "<bibliography line or BibTeX>", '
                  '"label": "real" | "fabricated", "type": "<optional category>"}')
HALLMARK_EXPECTED = ('HALLMARK rows: the entry in "bibtex" / "bibtex_entry" / "raw_bibtex" / '
                     '"entry" (BibTeX string) or "fields" (dict of BibTeX fields); the label in '
                     '"label" ("VALID" / "HALLUCINATED") or boolean "is_hallucinated"; optional '
                     'type in "hallucination_type" / "type" / "category"')

_HALLMARK_ENTRY_KEYS = ("bibtex", "bibtex_entry", "raw_bibtex", "entry")
_HALLMARK_TYPE_KEYS = ("hallucination_type", "type", "category")
_REAL_WORDS = {"valid", "real", "genuine", "clean"}
_FAKE_WORDS = {"hallucinated", "hallucination", "fabricated", "fake", "invalid"}
_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")

Lookup = Callable[[Reference], dict | None]


# ---------------------------------------------------------------------------
# Entries -> References
# ---------------------------------------------------------------------------

def _display_name(author: str) -> str:
    """"He, Kaiming" -> "Kaiming He"; anything else unchanged."""
    if "," in author:
        last, first = (p.strip() for p in author.split(",", 1))
        return f"{first} {last}".strip()
    return author.strip()


def reference_from_bibtex(fields: dict) -> Reference:
    """A Reference from parsed BibTeX fields (lower-cased keys).

    Structured fields are kept structured -- the authors list reaches the
    validator's author-overlap check, as it does through the MCP tool -- and
    ``raw`` is rendered as the "Authors. Title. Venue, Year." line the
    containment rules read.
    """
    from research_companion.refcheck.parse import extract_arxiv_id

    f = {str(k).lower(): v for k, v in fields.items()}
    title = str(f.get("title") or "").strip()
    if not title:
        raise ValueError("BibTeX entry has no title")
    authors = f.get("authors")
    if authors is None:
        raw_authors = f.get("author") or ""
        authors = (re.split(r"\s+and\s+", raw_authors) if isinstance(raw_authors, str)
                   else list(raw_authors))
    authors = [_display_name(str(a)) for a in authors if str(a).strip()]
    year = f.get("year")
    if not isinstance(year, int):
        m = re.search(r"\d{4}", str(year or ""))
        year = int(m.group(0)) if m else None
    venue = str(f.get("journal") or f.get("booktitle") or f.get("publisher") or "").strip()
    doi = str(f.get("doi") or "").strip() or None
    if doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    eprint = str(f.get("eprint") or "").strip()
    where = f"{venue} {f.get('url') or ''} {f.get('archiveprefix') or ''}"
    if _ARXIV_ID_RE.match(eprint):
        arxiv_id = extract_arxiv_id(eprint)
    elif "arxiv" in where.lower():
        arxiv_id = extract_arxiv_id(where)
    else:
        arxiv_id = None
    tail = ", ".join(p for p in (venue, str(year) if year else "") if p)
    line = ". ".join(p for p in (", ".join(authors), title, tail) if p) + "."
    return Reference(title=title, authors=authors, year=year, doi=doi,
                     arxiv_id=arxiv_id, raw=line)


def reference_from_entry(text: str) -> Reference:
    """Parse one benchmark entry: BibTeX when it starts with ``@``, else a line."""
    from research_companion.interop.bibtex import parse_bibtex
    from research_companion.refcheck.parse import parse_reference_string

    text = (text or "").strip()
    if not text:
        raise ValueError("entry is empty")
    if text.startswith("@"):
        parsed = parse_bibtex(text)
        if not parsed:
            raise ValueError("BibTeX entry could not be parsed")
        return reference_from_bibtex(parsed[0])
    return parse_reference_string(text)


@dataclass(frozen=True)
class BenchEntry:
    line: int
    entry: str
    label: str
    type: str
    reference: Reference


@dataclass
class LoadedFile:
    entries: list[BenchEntry]
    skipped: list[dict]
    format: str


def _entry_from_jsonl(no: int, obj: dict) -> BenchEntry:
    entry = obj.get("entry")
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError('missing "entry" (a non-empty string)')
    label = str(obj.get("label") or "").strip().lower()
    if label not in LABELS:
        raise ValueError(f'"label" must be "real" or "fabricated", got {obj.get("label")!r}')
    etype = str(obj.get("type") or "").strip() or ("real" if label == "real" else "untyped")
    return BenchEntry(no, entry.strip(), label, etype, reference_from_entry(entry))


def _hallmark_label(obj: dict) -> str:
    for key in ("is_hallucinated", "hallucinated"):
        if isinstance(obj.get(key), bool):
            return "fabricated" if obj[key] else "real"
    raw = str(obj.get("label") or "").strip().lower()
    if raw in _REAL_WORDS:
        return "real"
    if raw in _FAKE_WORDS:
        return "fabricated"
    raise ValueError(f"unrecognised HALLMARK label {obj.get('label')!r} "
                     '(expected "VALID" / "HALLUCINATED" or boolean "is_hallucinated")')


def _entry_from_hallmark(no: int, obj: dict) -> BenchEntry:
    label = _hallmark_label(obj)
    etype = next((str(obj[k]).strip() for k in _HALLMARK_TYPE_KEYS
                  if obj.get(k) not in (None, "")), "")
    etype = etype or ("valid" if label == "real" else "untyped")
    fields = obj.get("fields")
    if isinstance(obj.get("entry"), dict):
        fields = obj["entry"]
    if isinstance(fields, dict):
        ref = reference_from_bibtex(fields)
        return BenchEntry(no, ref.raw, label, etype, ref)
    text = next((obj[k] for k in _HALLMARK_ENTRY_KEYS
                 if isinstance(obj.get(k), str) and obj[k].strip()), None)
    if text is None:
        raise ValueError("no entry text: expected one of " +
                         ", ".join(f'"{k}"' for k in _HALLMARK_ENTRY_KEYS) + ' or "fields"')
    return BenchEntry(no, text.strip(), label, etype, reference_from_entry(text))


def _detect_format(obj: dict) -> str | None:
    if isinstance(obj.get("entry"), str) and str(obj.get("label", "")).lower() in LABELS:
        return "jsonl"
    if (any(k in obj for k in _HALLMARK_ENTRY_KEYS + ("fields",))
            and ("label" in obj or "is_hallucinated" in obj or "hallucinated" in obj)):
        return "hallmark"
    return None


def load_entries(path: str | Path, fmt: str = "auto") -> LoadedFile:
    """Read a labelled file. Malformed rows are returned in ``skipped``, never
    dropped silently; a file with no usable row raises with the expected fields.
    """
    rows = read_jsonl(path)
    objects = [obj for _, obj, _ in rows if obj is not None]
    if fmt == "auto":
        fmt = next((f for f in map(_detect_format, objects) if f), "")
        if not fmt:
            raise BenchFormatError(
                f"{path} does not look like a reference benchmark file. Expected "
                f"either the native format -- {JSONL_EXPECTED} -- or {HALLMARK_EXPECTED}.")
    if fmt not in ("jsonl", "hallmark"):
        raise BenchFormatError(f"unknown format {fmt!r}; use jsonl, hallmark or auto")
    parse_row = _entry_from_jsonl if fmt == "jsonl" else _entry_from_hallmark
    entries: list[BenchEntry] = []
    skipped: list[dict] = []
    for no, obj, err in rows:
        if obj is None:
            skipped.append({"line": no, "error": err})
            continue
        try:
            entries.append(parse_row(no, obj))
        except ValueError as exc:
            skipped.append({"line": no, "error": str(exc)})
    if not entries:
        expected = JSONL_EXPECTED if fmt == "jsonl" else HALLMARK_EXPECTED
        first = "; ".join(f"line {s['line']}: {s['error']}" for s in skipped[:3])
        raise BenchFormatError(
            f"No usable rows in {path} as {fmt}" + (f" ({first})" if first else "") +
            f". Expected {expected}.")
    return LoadedFile(entries, skipped, fmt)


# ---------------------------------------------------------------------------
# Lookups: live (rate-limited, optionally cached) and offline fixture
# ---------------------------------------------------------------------------

class CatalogueCache:
    """Append-only JSONL recording of catalogue responses.

    One line per response: ``{"source", "query", "response"}``. Appending
    makes a run resume-safe -- an interrupted run leaves at most one truncated
    last line, which is ignored on load (and fenced off with a newline so the
    next record does not fuse onto it). Responses only: verdicts are always
    recomputed, so the cache never hides a matcher change.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict[tuple[str, str], object] = {}
        self.unreadable_lines = 0
        self.hits = 0
        self.stored = 0
        if self.path.exists():
            text = self.path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    self._data[(rec["source"], rec["query"])] = rec["response"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    self.unreadable_lines += 1
            if text and not text.endswith("\n"):
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write("\n")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, source: str, query: str) -> tuple[bool, object]:
        key = (source, query)
        if key in self._data:
            self.hits += 1
            return True, self._data[key]
        return False, None

    def put(self, source: str, query: str, response: object) -> None:
        self._data[(source, query)] = response
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"source": source, "query": query, "response": response},
                                ensure_ascii=False) + "\n")
            fh.flush()
        self.stored += 1


def build_live_lookup(
    *,
    cache: CatalogueCache | None = None,
    delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    crossref_search: Callable[..., list[dict]] | None = None,
    openalex_search: Callable[..., list[dict]] | None = None,
    arxiv_fetch: Callable[[str], dict | None] | None = None,
) -> Lookup:
    """The production chain -- arXiv, then CrossRef, then OpenAlex, as
    ``retrieval.default_lookup(connectors=[])`` -- with every network call
    spaced by *delay* seconds and recorded to *cache*.

    A response is cached only when the call recorded no transport failure, so
    an outage is retried on resume instead of replayed as "nothing found".
    """
    from research_companion.refcheck import retrieval as r

    calls = {"n": 0}

    def recorded(source: str, fn: Callable) -> Callable:
        def call(query: str, **_kw):
            if cache is not None:
                hit, value = cache.get(source, query)
                if hit:
                    return value
            if delay > 0 and calls["n"] > 0:
                sleep(delay)
            calls["n"] += 1
            before = r.transport_failures_recorded()
            value = fn(query)
            after = r.transport_failures_recorded()
            if cache is not None and before is not None and after == before:
                cache.put(source, query, value)
            return value
        return call

    return r.chained_lookup(
        partial(r.arxiv_lookup, fetch=recorded("arxiv", arxiv_fetch or r._arxiv_fetch)),
        partial(r.crossref_lookup, search=recorded("crossref", crossref_search or r._crossref_search)),
        partial(r.openalex_lookup, search=recorded("openalex", openalex_search or r._openalex_search)),
    )


def _crossref_item(rec: dict) -> dict:
    """A fixture record in the shape CrossRef's search API returns, so the
    real ``parse_crossref_item`` parses it."""
    authors = []
    for name in rec.get("authors") or []:
        parts = name.rsplit(" ", 1)
        authors.append({"given": parts[0], "family": parts[1]} if len(parts) == 2
                       else {"family": name})
    item = {"title": [rec["title"]], "author": authors}
    if rec.get("year"):
        item["issued"] = {"date-parts": [[rec["year"]]]}
    if rec.get("doi"):
        item["DOI"] = rec["doi"]
    return item


def fixture_lookup(path: str | Path) -> Lookup:
    """An offline lookup over a catalogue fixture (``{"records": [...]}``).

    Search is simulated the way a catalogue behaves: any query returns its
    five best word-overlap candidates, related or not, and the REAL
    ``crossref_lookup`` / ``arxiv_lookup`` decide which (if any) is a match.
    """
    from research_companion.refcheck import retrieval as r
    from research_companion.refcheck.matching import normalize_title, title_similarity

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise BenchFormatError(f'{path}: a catalogue fixture is {{"records": [{{title, authors, '
                               f'year, doi, arxiv_id}}, ...]}}')
    items = [_crossref_item(rec) for rec in records]
    by_arxiv = {rec["arxiv_id"]: rec for rec in records if rec.get("arxiv_id")}

    def search(query: str, **_kw) -> list[dict]:
        q = set(normalize_title(query).split())
        scored = []
        for idx, item in enumerate(items):
            shared = len(q & set(normalize_title(item["title"][0]).split()))
            if shared:
                scored.append((-shared, -title_similarity(query, item["title"][0]), idx))
        return [items[idx] for _, _, idx in sorted(scored)[:5]]

    def fetch(arxiv_id: str) -> dict | None:
        rec = by_arxiv.get(arxiv_id)
        if rec is None:
            return None
        return {"title": rec["title"], "authors": list(rec.get("authors") or []),
                "year": rec.get("year")}

    return r.chained_lookup(partial(r.arxiv_lookup, fetch=fetch),
                            partial(r.crossref_lookup, search=search))


# ---------------------------------------------------------------------------
# Running and scoring
# ---------------------------------------------------------------------------

def _was_checked(ref: Reference, verdict: RefVerdict) -> bool:
    """Whether a catalogue answered at all -- decided by the same adapter the
    product uses, so the benchmark and the UI cannot disagree about it."""
    from research_companion.checker_signals import refcheck_signals
    from research_companion.refcheck.validate import BibReport
    from research_companion.signals import CheckStatus

    for sig in refcheck_signals(BibReport(entries=[(ref, verdict)])):
        if sig.name == "reference_exists":
            return sig.check_status is CheckStatus.CHECKED
    return True


def _outcome(label: str, status: str, checked: bool) -> str:
    if not checked:
        return "not_checked"
    if label == "fabricated":
        return "missed" if status == "verified" else "detected"
    return "accepted" if status == "verified" else "falsely_accused"


def run_bench(entries: list[BenchEntry], lookup: Lookup, *,
              progress: Callable[[int, int], None] | None = None) -> list[dict]:
    """Validate every entry, in order, through the real validator."""
    from research_companion.refcheck.validate import validate_reference

    rows = []
    for i, e in enumerate(entries, start=1):
        verdict = validate_reference(e.reference, lookup)
        checked = _was_checked(e.reference, verdict)
        rows.append({
            "line": e.line, "label": e.label, "type": e.type,
            "entry": e.entry, "status": verdict.status, "checked": checked,
            "outcome": _outcome(e.label, verdict.status, checked),
            "reasons": list(verdict.reasons),
            "matched_title": (verdict.matched or {}).get("title"),
        })
        if progress:
            progress(i, len(entries))
    return rows


def summarize(rows: list[dict]) -> dict:
    """Confusion matrix and rates. Not-checked entries are counted and
    excluded from both rates: an outage is neither a pass nor a miss."""
    confusion = {lbl: {v: 0 for v in VERDICTS + ("not_checked",)} for lbl in LABELS}
    for r in rows:
        confusion[r["label"]][r["status"] if r["checked"] else "not_checked"] += 1

    fab, real = confusion["fabricated"], confusion["real"]
    fab_checked = fab["verified"] + fab["suspect"] + fab["unverified"]
    real_checked = real["verified"] + real["suspect"] + real["unverified"]
    detected = fab["suspect"] + fab["unverified"]
    accused = real["suspect"] + real["unverified"]

    groups: dict[tuple[str, str], dict] = {}
    for r in rows:
        g = groups.setdefault((r["type"], r["label"]), {
            "type": r["type"], "label": r["label"], "total": 0, "checked": 0,
            "not_checked": 0, "flagged": 0})
        g["total"] += 1
        if not r["checked"]:
            g["not_checked"] += 1
            continue
        g["checked"] += 1
        g["flagged"] += r["status"] != "verified"
    per_type = []
    for (_t, lbl), g in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        g["rate_name"] = "detection_rate" if lbl == "fabricated" else "false_accusation_rate"
        g["rate"] = rate(g["flagged"], g["checked"])
        per_type.append(g)

    return {
        "entries_run": len(rows),
        "confusion_matrix": confusion,
        "fabricated": {
            "total": sum(fab.values()), "checked": fab_checked,
            "detected": detected, "detected_as_suspect": fab["suspect"],
            "detected_as_not_found": fab["unverified"], "missed": fab["verified"],
            "detection_rate": rate(detected, fab_checked),
        },
        "real": {
            "total": sum(real.values()), "checked": real_checked,
            "accepted": real["verified"], "falsely_accused": accused,
            "accused_as_suspect": real["suspect"], "accused_as_not_found": real["unverified"],
            "false_accusation_rate": rate(accused, real_checked),
        },
        "not_checked": {
            "total": fab["not_checked"] + real["not_checked"],
            "real": real["not_checked"], "fabricated": fab["not_checked"],
        },
        "per_type": per_type,
        "definitions": {
            "detection_rate": "fabricated entries judged suspect or unverified, "
                              "over fabricated entries a catalogue answered for",
            "false_accusation_rate": "real entries judged suspect or unverified, "
                                     "over real entries a catalogue answered for",
            "not_checked": "no catalogue could be reached; excluded from both rates, "
                           "never counted as a pass or a failure",
        },
    }


def format_summary(result: dict) -> str:
    m = result["metrics"]
    fab, real, nc = m["fabricated"], m["real"], m["not_checked"]
    out = [f"Reference-checker benchmark: {result['file']} ({result['format']})",
           f"Entries run: {m['entries_run']} of {result['usable_rows']} usable"
           + (f" (--limit {result['limit']})" if result.get("limit") else ""),
           f"Rows skipped as malformed: {len(result['skipped'])}"]
    for s in result["skipped"][:10]:
        out.append(f"  line {s['line']}: {s['error']}")
    out += [f"Not checked (no catalogue reachable): {nc['total']} "
            f"({nc['real']} real, {nc['fabricated']} fabricated) -- excluded from both rates",
            "",
            f"Fabricated: {fab['total']} entries, {fab['checked']} checked",
            f"  detected {fab['detected']} (suspect {fab['detected_as_suspect']}, "
            f"not found {fab['detected_as_not_found']}), missed {fab['missed']}",
            f"  Detection rate:        {fmt_rate(fab['detected'], fab['checked'])}",
            f"Real: {real['total']} entries, {real['checked']} checked",
            f"  accepted {real['accepted']}, falsely accused {real['falsely_accused']} "
            f"(suspect {real['accused_as_suspect']}, not found {real['accused_as_not_found']})",
            f"  False-accusation rate: {fmt_rate(real['falsely_accused'], real['checked'])}",
            "",
            "Confusion matrix (rows: label, columns: verdict)",
            f"  {'':<11}{'verified':>9}{'suspect':>9}{'unverified':>11}{'not checked':>13}"]
    for lbl in LABELS:
        c = m["confusion_matrix"][lbl]
        out.append(f"  {lbl:<11}{c['verified']:>9}{c['suspect']:>9}"
                   f"{c['unverified']:>11}{c['not_checked']:>13}")
    out += ["", "Per type (flagged = suspect or unverified)",
            f"  {'type':<34}{'label':<12}{'checked':>8}{'flagged':>8}  rate"]
    for g in m["per_type"]:
        name = "detection" if g["label"] == "fabricated" else "false accusation"
        out.append(f"  {g['type'][:33]:<34}{g['label']:<12}{g['checked']:>8}{g['flagged']:>8}  "
                   f"{name} {fmt_rate(g['flagged'], g['checked'])}"
                   + (f", {g['not_checked']} not checked" if g["not_checked"] else ""))
    errors = [r for r in result["rows"] if r["outcome"] in ("missed", "falsely_accused")]
    if errors:
        out += ["", "Errors"]
        for r in errors:
            why = "; ".join(r["reasons"]) or "verified"
            out.append(f"  line {r['line']} [{r['label']}/{r['type']}] -> {r['status']}: "
                       f"{r['entry'][:70]} :: {why[:90]}")
    if result.get("cache"):
        c = result["cache"]
        out += ["", f"Cache {c['path']}: {c['hits']} responses replayed, {c['stored']} recorded"
                + (f", {c['unreadable_lines']} unreadable lines ignored"
                   if c["unreadable_lines"] else "")]
    return "\n".join(out)


def evaluate(path: str | Path, lookup: Lookup, *, fmt: str = "auto",
             limit: int | None = None,
             progress: Callable[[int, int], None] | None = None) -> dict:
    """Load *path*, run the first *limit* entries, and score them."""
    loaded = load_entries(path, fmt)
    entries = loaded.entries[:limit] if limit else loaded.entries
    rows = run_bench(entries, lookup, progress=progress)
    return {"file": str(path), "format": loaded.format, "limit": limit,
            "usable_rows": len(loaded.entries), "skipped": loaded.skipped,
            "metrics": summarize(rows), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m research_companion.eval.refcheck_bench",
        description="Measure the reference checker on a labelled bibliography file.")
    parser.add_argument("file", help="labelled JSONL file (native or HALLMARK)")
    parser.add_argument("--format", default="auto", choices=("auto", "jsonl", "hallmark"))
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="run only the first N usable entries")
    parser.add_argument("--catalogue", metavar="FIXTURE",
                        help="offline catalogue fixture instead of the live catalogues")
    parser.add_argument("--cache", metavar="FILE",
                        help="record live catalogue responses here and replay them on resume")
    parser.add_argument("--delay", type=float, default=1.0, metavar="SECONDS",
                        help="pause between live network calls (default 1.0)")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    cache = None
    try:
        if args.catalogue:
            lookup = fixture_lookup(args.catalogue)
        else:
            cache = CatalogueCache(args.cache) if args.cache else None
            lookup = build_live_lookup(cache=cache, delay=max(0.0, args.delay))
            print(f"Live run: arXiv -> CrossRef -> OpenAlex, sequential, {args.delay:g}s "
                  "between network calls. Results depend on catalogue state at run time.",
                  file=sys.stderr)

        def progress(i: int, n: int) -> None:
            if not args.catalogue and (i % 25 == 0 or i == n):
                print(f"  {i}/{n}", file=sys.stderr)

        result = evaluate(args.file, lookup, fmt=args.format, limit=args.limit,
                          progress=progress)
    except BenchFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if cache is not None:
        result["cache"] = {"path": str(cache.path), "hits": cache.hits,
                           "stored": cache.stored, "unreadable_lines": cache.unreadable_lines}
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json
          else format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
