#!/usr/bin/env python3
"""Keep docs/DEGRADATION_REGISTRY.json honest.

A registry that documents behaviour is worthless the moment it drifts from the
code — worse than none, because it is trusted. This verifies that every row
still points at something real:

* every ``authority.file`` exists,
* every ``anchor`` still appears **verbatim** in that file (anchors are used
  instead of line numbers precisely so they survive ordinary edits — if an
  anchor stops matching, the behaviour it names has probably changed),
* every ``pinned_by`` test file exists, and a ``path::test_name`` entry names a
  function that is actually defined there,
* required fields are present and non-empty.

Run: ``python scripts/check_degradation_registry.py``
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "docs" / "DEGRADATION_REGISTRY.json"

REQUIRED_FIELDS = (
    "mechanism", "trigger", "degraded_state",
    "user_visible_signal", "authority", "pinned_by",
)


def _check_row(row: dict, problems: list[str]) -> None:
    name = row.get("mechanism") or "<unnamed>"

    for field in REQUIRED_FIELDS:
        if not row.get(field):
            problems.append(f"{name}: missing or empty field '{field}'")

    for entry in row.get("authority", []):
        rel = entry.get("file", "")
        anchor = entry.get("anchor", "")
        path = REPO_ROOT / rel
        if not rel or not path.is_file():
            problems.append(f"{name}: authority file not found: {rel!r}")
            continue
        if not anchor:
            problems.append(f"{name}: authority for {rel} has no anchor")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if anchor not in text:
            problems.append(
                f"{name}: anchor not found verbatim in {rel}: {anchor!r} "
                "(the behaviour this row documents may have changed)"
            )

    for pin in row.get("pinned_by", []):
        rel, _, qualifier = pin.partition("::")
        # pins may be `path`, `path::test_fn`, or `path::TestClass::test_fn`
        test_name = qualifier.rsplit("::", 1)[-1] if qualifier else ""
        path = REPO_ROOT / rel
        if not path.is_file():
            problems.append(f"{name}: pinned_by test file not found: {rel!r}")
            continue
        if test_name:
            text = path.read_text(encoding="utf-8", errors="replace")
            # match `def name(` for python, `test('name'` style for node is not
            # addressed here — python pins are the ones that carry ::name
            if not re.search(rf"def\s+{re.escape(test_name)}\s*\(", text):
                problems.append(
                    f"{name}: {rel} does not define {test_name}()"
                )


def main() -> int:
    if not REGISTRY.is_file():
        print(f"FAIL: {REGISTRY} not found", file=sys.stderr)
        return 1

    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL: registry is not valid JSON: {exc}", file=sys.stderr)
        return 1

    mechanisms = data.get("mechanisms")
    if not isinstance(mechanisms, list) or not mechanisms:
        print("FAIL: registry has no mechanisms", file=sys.stderr)
        return 1

    problems: list[str] = []
    seen: set[str] = set()
    for row in mechanisms:
        name = row.get("mechanism", "")
        if name in seen:
            problems.append(f"duplicate mechanism id: {name!r}")
        seen.add(name)
        _check_row(row, problems)

    if problems:
        print("FAIL: degradation registry has drifted from the code:\n",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nEither restore the documented behaviour, or update the row so "
            "the registry matches reality.",
            file=sys.stderr,
        )
        return 1

    print(f"degradation registry OK — {len(mechanisms)} mechanisms verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
