"""Entry point: `python -m research-companion ...`."""
from __future__ import annotations

import sys

from research_companion.cli import main

if __name__ == "__main__":
    sys.exit(main())
