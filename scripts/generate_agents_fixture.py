"""Regenerate tests/js/fixtures_agents.json from the real agent catalogue.

The Agents page's JS tests read this file. It is generated, not hand-written,
so the tests check the page against the catalogue the server actually serves.
Run after changing research_companion/agents/catalog.py:

    python scripts/generate_agents_fixture.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research_companion.agents.catalog import catalog  # noqa: E402

OUT = ROOT / "tests" / "js" / "fixtures_agents.json"


def main() -> int:
    OUT.write_text(json.dumps({"agents": catalog()}, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
