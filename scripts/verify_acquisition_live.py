"""Run the real chain against the 12 DOIs that actually failed.

Every significant bug in this codebase was found by running on real data, not
by the suite. Network-dependent by design, so it is a script and not a test.

Expected: 1 obtained, 6 blocked_by_host, 5 paywalled.

This expectation was originally measured live on 2026-09-01 as 2 obtained, 5
blocked_by_host, 5 paywalled. Re-run on 2026-09-02 (this file's numbers) came
back 1/6/5 instead, and the difference was investigated rather than silently
matched:

  * the 5 IEEE DOIs (paywalled) and 6 of the 7 ACM DOIs (blocked_by_host,
    ACM's own OA article returning HTTP 403) were unchanged between the two
    runs.
  * the one that moved is 10.1145/3767742. On 2026-09-01 it was obtained via
    a direct-PDF link on its institutional repository mirror
    (ink.library.smu.edu.sg, a bepress `viewcontent.cgi` URL) after ACM itself
    refused it. On 2026-09-02 that same repository URL returns HTTP 200 with
    an Incapsula bot-challenge page (`<script src="/_Incapsula_Resource...`)
    instead of the PDF, regardless of User-Agent (checked with a browser UA
    and with curl's -- both challenged identically). The repository added (or
    activated) bot-management on this endpoint sometime in the intervening
    day; nothing in this codebase's classification or retrieval logic
    changed. Since ACM already refuses the same paper with a 403, the paper's
    overall classification was already BLOCKED_BY_HOST-eligible on that
    front; what changed is that its one working automated path closed, which
    is precisely a genuine, host-side access change of the kind this note
    exists to distinguish from a bug. The expectation below reflects that.

If a future run disagrees with 1/6/5, do not adjust the numbers to match
without first checking which of three things happened: the classification
logic is wrong, the chain is wrong, or (as happened here) a paper's
open-access status genuinely changed since this was last measured.
"""
from __future__ import annotations

import sys
from collections import Counter
from types import SimpleNamespace

from research_companion.acquire import acquire

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DOIS = [
    "10.1145/3732941", "10.1145/3727200.3727217", "10.1109/mm.2024.3375352",
    "10.1109/lca.2024.3406038", "10.1145/3676641.3716025", "10.1145/3620666.3651380",
    "10.1145/3767742", "10.1109/iiswc63097.2024.00024", "10.1109/tmc.2024.3513457",
    "10.1109/tmc.2024.3415661", "10.1145/3695053.3731008", "10.1145/3404835.3462963",
]

counts = Counter()
for doi in DOIS:
    meta = SimpleNamespace(paper_id=f"doi:{doi}", title="", authors=[], year=None)
    body, acq = acquire(meta)
    key = "obtained" if acq.obtained else acq.reason.value
    counts[key] += 1
    print(f"  {key:20} {doi:34} ({len(acq.attempts)} attempts)")

print("\n" + str(dict(counts)))
expected = {"obtained": 1, "blocked_by_host": 6, "paywalled": 5}
sys.exit(0 if dict(counts) == expected else 1)
