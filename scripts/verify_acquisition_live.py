"""Run the real chain against the 12 DOIs that actually failed.

Every significant bug in this codebase was found by running on real data, not
by the suite. Network-dependent by design, so it is a script and not a test.

Expected: 5 obtained, 2 blocked_by_host, 5 paywalled.

Measurement history, kept because each change was investigated rather than
matched:

  * 2026-09-01, title="": 2 obtained, 5 blocked_by_host, 5 paywalled.
  * 2026-09-02, title="": 1 obtained, 6 blocked_by_host, 5 paywalled. The one
    that moved was 10.1145/3767742, obtained the day before via a direct-PDF
    link on its institutional repository mirror (ink.library.smu.edu.sg, a
    bepress `viewcontent.cgi` URL). That URL began returning HTTP 200 with an
    Incapsula bot-challenge page instead of the PDF, regardless of
    User-Agent (checked with a browser UA and with curl -- both challenged
    identically). A host-side access change, not a change here.
  * 2026-09-02, with REAL titles: 5 obtained, 2 blocked_by_host, 5 paywalled.

That last jump is the script being fixed, not the chain changing. It passed
`title=""`, and `arxiv_title`/`pmc_title` only run when a title is present --
so the branch's marquee capability, recovering a paywalled paper from its
arXiv preprint by title (spec 5.2 step 4, worked through for TAPAS in 5.5),
was verified by nothing at all. add_doi has the Crossref title in hand when
it calls acquire(), so passing "" made this run a strict subset of
production. With the real title, every one of the five obtained papers came
from the arXiv title search after the publisher answered 403:

    10.1145/3676641.3716025  TAPAS     -> arxiv.org/pdf/2501.02600
    10.1145/3620666.3651380  NeuPIMs   -> arxiv.org/pdf/2403.00579
    10.1145/3727200.3727217            -> arxiv.org/pdf/2407.04014
    10.1145/3767742                    -> arxiv.org/pdf/2504.03360
    10.1145/3404835.3462963            -> arxiv.org/pdf/2104.10353

TAPAS and NeuPIMs are exactly the two 1.1 predicted were recoverable
automatically. The other three were not known about when the design was
written; nothing was loosened to admit them -- _parse_arxiv_feed still
requires an exact normalized title match, so a near-miss attaches nothing.

The two that remain blocked_by_host are ACM's own open-access articles
answering 403 to a robot (10.1145/3732941 and 10.1145/3695053.3731008); the
five IEEE papers have no free copy in existence. Both groups are components
3 and 4's job, exactly as designed.

If a future run disagrees with 5/2/5, do not adjust the numbers to match
without first checking which of three things happened: the classification
logic is wrong, the chain is wrong, or a paper's open-access status
genuinely changed since this was last measured.
"""
from __future__ import annotations

import sys
from collections import Counter
from types import SimpleNamespace

import httpx

from research_companion.acquire import acquire

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CROSSREF = "https://api.crossref.org/works/{doi}"
_UA = "research-companion (https://github.com/LaraibOSS/Research-Companion)"


def crossref_title(doi: str) -> str:
    """The paper's REAL title, from Crossref.

    This script used to pass title="", which silently disabled the two steps
    the branch exists for: arxiv_title and pmc_title only run when a title is
    present, so the marquee capability -- recovering TAPAS and NeuPIMs from
    their arXiv preprints by title -- was verified by nothing. add_doi has
    the Crossref title in hand when it calls acquire(), so fetching it here
    is what makes this run resemble production rather than a subset of it.
    """
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": _UA},
                          follow_redirects=True) as client:
            resp = client.get(CROSSREF.format(doi=doi))
            resp.raise_for_status()
            titles = (resp.json().get("message") or {}).get("title") or []
    except Exception as exc:      # noqa: BLE001 -- a lookup miss is reportable
        print(f"  ! crossref lookup failed for {doi}: {exc}")
        return ""
    return (titles[0] if titles else "").strip()

DOIS = [
    "10.1145/3732941", "10.1145/3727200.3727217", "10.1109/mm.2024.3375352",
    "10.1109/lca.2024.3406038", "10.1145/3676641.3716025", "10.1145/3620666.3651380",
    "10.1145/3767742", "10.1109/iiswc63097.2024.00024", "10.1109/tmc.2024.3513457",
    "10.1109/tmc.2024.3415661", "10.1145/3695053.3731008", "10.1145/3404835.3462963",
]

counts = Counter()
for doi in DOIS:
    title = crossref_title(doi)
    meta = SimpleNamespace(paper_id=f"doi:{doi}", title=title, authors=[], year=None)
    body, acq = acquire(meta)
    key = "obtained" if acq.obtained else acq.reason.value
    counts[key] += 1
    print(f"  {key:20} {doi:34} ({len(acq.attempts)} attempts)  {title[:60]}")

print("\n" + str(dict(counts)))
expected = {"obtained": 5, "blocked_by_host": 2, "paywalled": 5}
sys.exit(0 if dict(counts) == expected else 1)
