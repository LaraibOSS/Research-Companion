"""Generate tests/js/fixtures_acquisition.json from the Python model.

Hand-written fixtures have encoded assumed shapes four times in this project.
The JS display model must be tested against what Python actually emits.
"""
from __future__ import annotations

import json
import pathlib

from research_companion.acquire import AcquireReason, Acquisition, Attempt, HostClass
from research_companion.acquire.copy import reason_detail, reason_headline

OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "js" / "fixtures_acquisition.json"

CASES = {
    "blocked": Acquisition(False, AcquireReason.BLOCKED_BY_HOST, (
        Attempt("https://dl.acm.org/doi/pdf/10.1145/3732941",
                HostClass.PUBLISHER, 403, "403"),)),
    "paywalled": Acquisition(False, AcquireReason.PAYWALLED, (
        Attempt("https://ieeexplore.ieee.org/stamp/1",
                HostClass.PUBLISHER, 404, "404"),)),
    "no_location": Acquisition(False, AcquireReason.NO_LOCATION_FOUND),
    "transient": Acquisition(False, AcquireReason.SOURCE_UNAVAILABLE, (
        Attempt("https://arxiv.org/pdf/1", HostClass.NATIVE, None, "timeout"),)),
    "not_a_pdf": Acquisition(False, AcquireReason.NOT_A_PDF, (
        Attempt("https://dl.acm.org/x", HostClass.PUBLISHER, 200, "not-pdf"),)),
    "not_attempted": Acquisition(False, AcquireReason.NOT_ATTEMPTED),
    "obtained": Acquisition(True, None, (
        Attempt("https://arxiv.org/pdf/1", HostClass.NATIVE, 200, "pdf"),),
        "https://arxiv.org/pdf/1"),
}

payload = {name: {**acq.to_dict(),
                  "headline": reason_headline(acq),
                  "detail": reason_detail(acq)}
           for name, acq in CASES.items()}
OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({len(payload)} cases)")
