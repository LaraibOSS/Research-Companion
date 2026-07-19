"""BibTeX export and parsing — deterministic, no dependencies.

Export accepts records that are either ``PaperMetadata`` instances or plain dicts
(so it is decoupled from the store), and parsing returns plain dicts. Cite keys
are ``FirstauthorsurnameYear`` with a/b/... disambiguation, the convention most
reference managers use.
"""
from __future__ import annotations

import re
from typing import Any

_FIELD_RE = re.compile(r"(\w+)\s*=\s*", re.IGNORECASE)


def _get(rec: Any, key: str, default: Any = None) -> Any:
    if isinstance(rec, dict):
        return rec.get(key, default)
    return getattr(rec, key, default)


def _surname(author: str) -> str:
    author = author.strip()
    if "," in author:  # "Surname, Given"
        return author.split(",", 1)[0].strip()
    parts = author.split()
    return parts[-1] if parts else author


def cite_key(rec: Any) -> str:
    """Deterministic base cite key: first-author surname + year (sanitized).

    Falls back to the sanitized ``paper_id`` (without a year suffix) when the
    record has no authors.
    """
    authors = _get(rec, "authors") or []
    if authors:
        year = _get(rec, "year")
        year_str = str(year) if year else "nd"
        key = re.sub(r"[^A-Za-z0-9]", "", f"{_surname(authors[0])}{year_str}")
    else:
        key = re.sub(r"[^A-Za-z0-9]", "", str(_get(rec, "paper_id", "") or ""))
    return key or "ref"


def _escape(value: str) -> str:
    """LaTeX-escape a field value for BibTeX export (title/author/doi/url/abstract).

    NOT used for RIS export — RIS is plain tag-based text, not LaTeX, and
    ``interop/ris.py`` writes field values verbatim (only ``.strip()``ped).

    Order matters:
      1. Braces are stripped first (pre-existing behavior) — this module's own
         ``_split_top_level``/``_strip_value`` do naive brace-depth counting, and
         so does the ``{...}`` field wrapper this function's output gets embedded
         in; a literal ``{`` or ``}`` surviving in the value would unbalance both.
      2. Backslash is escaped next, before any other replacement below — several
         of those (``~`` and ``^``) themselves introduce backslashes/braces
         (``\\textbackslash{}`` etc.), and escaping backslash first ensures none
         of those get double-escaped.
      3. The remaining LaTeX specials are escaped in a fixed order chosen so no
         replacement's output is itself matched by a later replacement.
    """
    s = str(value)
    s = s.replace("{", "").replace("}", "")
    s = s.replace("\\", r"\textbackslash{}")
    s = s.replace("&", r"\&")
    s = s.replace("%", r"\%")
    s = s.replace("$", r"\$")
    s = s.replace("#", r"\#")
    s = s.replace("_", r"\_")
    s = s.replace("~", r"\textasciitilde{}")
    s = s.replace("^", r"\textasciicircum{}")
    return s.strip()


def paper_to_bibtex(rec: Any, key: str | None = None, entry_type: str = "article") -> str:
    """Render a single record as a BibTeX entry string."""
    key = key or cite_key(rec)
    fields: list[tuple[str, str]] = []
    title = _get(rec, "title")
    if title:
        fields.append(("title", _escape(title)))
    authors = _get(rec, "authors") or []
    if authors:
        fields.append(("author", " and ".join(_escape(a) for a in authors)))
    year = _get(rec, "year")
    if year:
        fields.append(("year", str(year)))
    doi = _get(rec, "doi")
    if doi:
        fields.append(("doi", _escape(doi)))
    url = _get(rec, "url") or _get(rec, "source_url")
    if url:
        fields.append(("url", _escape(url)))
    abstract = _get(rec, "abstract")
    if abstract:
        fields.append(("abstract", _escape(abstract)))

    body = ",\n".join(f"  {name} = {{{val}}}" for name, val in fields)
    return f"@{entry_type}{{{key},\n{body}\n}}"


def _alpha_suffix(index: int) -> str:
    """Bijective base-26 letter suffix: 0->'a', 25->'z', 26->'aa', 27->'ab', ...

    Keeps disambiguated cite keys within [a-z] even past 26 collisions (a naive
    ``chr(ord('a') + n)`` would emit '{' and corrupt the BibTeX).
    """
    letters = []
    index += 1  # 1-based for bijective base-26
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters.append(chr(ord("a") + rem))
    return "".join(reversed(letters))


def papers_to_bibtex(records: list[Any], entry_type: str = "article") -> str:
    """Render a list of records as a BibTeX document with unique cite keys."""
    used: dict[str, int] = {}
    entries: list[str] = []
    for rec in records:
        base = cite_key(rec)
        if base in used:
            used[base] += 1
            key = f"{base}{_alpha_suffix(used[base] - 1)}"
        else:
            used[base] = 0
            key = base
        entries.append(paper_to_bibtex(rec, key=key, entry_type=entry_type))
    return "\n\n".join(entries) + ("\n" if entries else "")


def _split_top_level(body: str) -> list[str]:
    """Split a bibtex entry body on top-level commas.

    Commas inside ``{...}`` braces or inside a ``"..."`` quoted value are ignored
    (e.g. an author list ``"Smith, Jane and Doe, John"``).
    """
    parts, depth, in_quote, cur = [], 0, False, []
    for ch in body:
        if ch == '"' and depth == 0:
            in_quote = not in_quote
            cur.append(ch)
            continue
        if not in_quote:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
        if ch == "," and depth == 0 and not in_quote:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def _strip_value(raw: str) -> str:
    raw = raw.strip()
    if (raw.startswith("{") and raw.endswith("}")) or (raw.startswith('"') and raw.endswith('"')):
        raw = raw[1:-1]
    # Remove remaining BibTeX protective braces (e.g. "A {Nested} Title").
    raw = raw.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", raw).strip()


def parse_bibtex(text: str) -> list[dict]:
    """Parse a BibTeX string into a list of entry dicts.

    Each dict has ``entry_type``, ``key``, and lowercased fields; ``authors`` is a
    split list (on ' and '). Robust to nested braces and quoted values; ignores
    ``@comment``/``@string`` and malformed entries rather than raising.
    """
    text = text or ""
    entries: list[dict] = []
    i = 0
    while True:
        at = text.find("@", i)
        if at == -1:
            break
        m = re.match(r"@(\w+)\s*\{", text[at:])
        if not m:
            i = at + 1
            continue
        entry_type = m.group(1).lower()
        brace_start = at + m.end() - 1  # position of '{'
        depth = 0
        j = brace_start
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner = text[brace_start + 1:j]
        i = j + 1
        if entry_type in ("comment", "string", "preamble"):
            continue
        parts = _split_top_level(inner)
        if not parts:
            continue
        entry: dict = {"entry_type": entry_type, "key": parts[0].strip()}
        for part in parts[1:]:
            part = part.strip()
            fm = _FIELD_RE.match(part)
            if not fm:
                continue
            name = fm.group(1).lower()
            value = _strip_value(part[fm.end():])
            entry[name] = value
        if "author" in entry:
            entry["authors"] = [a.strip() for a in re.split(r"\s+and\s+", entry["author"]) if a.strip()]
        if "year" in entry:
            ym = re.search(r"\d{4}", entry["year"])
            entry["year"] = int(ym.group(0)) if ym else None
        entries.append(entry)
    return entries
