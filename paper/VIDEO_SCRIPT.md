# Demo Video Script — Research Companion (≤ 2.5 min)

Format per CFP: screencast + voice narration; production quality not a priority. Record at
1920x1080, terminal font ≥16pt, browser at 100% zoom. Total target: **2:20**.

## Prep (before recording)
- Fresh terminal in the repo; `pip install -e ".[demo]"` done; `ANTHROPIC_API_KEY` set.
- A paper already added + built (e.g. the GraphRAG arXiv paper) so `review` runs live; ALSO keep
  the offline demo as fallback if network misbehaves during recording.
- A `reviews.txt` with 3 concerns (two reviewers, one duplicated concern) in the repo root.
- Browser tab ready (blank); OBS/any recorder.

## Shot list

**[0:00–0:15] Hook — the problem (terminal, title card optional).**
NARRATION: "Half of desk rejections cite lack of novelty. And LLM-assisted writing now adds a new
failure: citations that don't exist. Research Companion is a team of agents that reviews your paper
before reviewers do — and every verdict it gives can be checked."

**[0:15–0:45] Live agent run (terminal + browser).**
TYPE: `research-companion review arxiv:2404.16130 --serve --report out/`
ACTION: browser opens the dashboard; lanes light up: ingest → citation/priorart in parallel →
novelty → confidence → benchmark. Point cursor at the findings feed as events stream.
NARRATION: "Six agents run in parallel on a dependency graph. Watch them live: ingest builds a
knowledge graph; citation validates every reference against CrossRef and OpenAlex; prior art,
novelty, confidence, and benchmark follow. If one agent fails, the others keep going."

**[0:45–1:10] The fabricated-citation catch (dashboard/report).**
ACTION: click into the report (out/report.html); scroll to the citation card showing
`[unverified] <fabricated title> — No matching record found in authoritative sources`.
NARRATION: "This reference doesn't exist in any scholarly database. Compliance tools check
formatting; Research Companion checks existence — fabricated, wrong-DOI, and author-mismatch
citations are flagged with reasons."

**[1:10–1:40] Novelty with verified evidence + confidence band (report).**
ACTION: scroll to the claims table: verdict `overlaps`, closest prior work, `evidence verified: yes`;
then the confidence card `0.72 +/- 0.15` with its three signals.
NARRATION: "The novelty agent extracts what the paper claims as new, compares each claim against
retrieved prior art, and — critically — verifies the supporting quote against the paper's own text.
The confidence score is deterministic: three inspectable signals and an explicit uncertainty band.
No black boxes."

**[1:40–2:10] Rebuttal (terminal).**
TYPE: `research-companion rebuttal arxiv:2404.16130 --reviews reviews.txt`
ACTION: output shows R1.1/R1.2/R2.1 with kinds, one `[OK all quotes verified]`, grouped duplicate
concerns, planned-revisions changelog.
NARRATION: "Paste your reviews and get grounded point-by-point replies. Any sentence that quotes
the paper is verified verbatim — unverifiable spans are flagged, not shipped. Duplicate concerns
across reviewers are grouped, and promised revisions become a changelog."

**[2:10–2:20] Close (terminal).**
TYPE: `python examples/demo_offline.py`
NARRATION: "Open source, MIT, 213 tests — and a full offline demo that runs in thirty seconds with
no API keys. Research Companion: agents you can watch, and verify."
SHOW: repo URL on screen: github.com/Laraib-Hasan/Research-Companion

## Fallback plan
If live network/LLM misbehaves on take day: record the offline demo path
(`python examples/demo_offline.py` then open demo-out/report.html) for shots 2–3; the narration
stands unchanged except "running against the bundled offline fixtures".
