# Research Companion — Demo Video Script (~2:20)

Target: EMNLP 2026 System Demonstrations. Screen recording of the Research Lab
(`research-companion lab serve`) + one terminal. Record at 1440x900 or 1920x1080,
dark theme, browser at 100% zoom. Speak plainly; every claim shown on screen must be
real output.

## Setup before recording
- Fresh store (`RESEARCH_COMPANION_DIR` pointed at a clean dir) with your draft PDF ready
  and a folder of ~10 related PDFs (include one corrupt/scanned PDF for the failure beat).
- `.env` with your provider key; `pip install -e ".[server]"` done.
- Terminal one-liner ready: `research-companion lab serve`.

---

## Beat 1 — "Drop your research into the lab" (0:00–0:55)

Action: launch `lab serve`; browser opens to the empty Library ("Drop your research
into the lab"). Add the draft PDF via "+ Add papers", click the card -> **Set as draft**
(★ badge appears). Click **Ingest folder...**, pick the folder, Start ingest — immediately
switch to the **Graph view**: nodes bloom outward paper by paper, the LIVE badge pulses,
counters tick (nodes/edges/papers), the progress dock shows `4/10 · extracting`. The corrupt
PDF fails -> red toast; cut to Library: red failed card with the reason -> click **Retry**
(it fails again honestly — leave it red; that is the point).

> "This is Research Companion's Research Lab. Point it at the folder where your papers
> already live. A team of agents fetches, splits each paper into its sections, extracts
> concepts, methods, datasets, claims, and results — and you watch your knowledge graph
> grow in real time. When a PDF can't be parsed, the Lab tells you exactly which one and
> why, with one-click retry — no silent failures."

## Beat 2 — "Verdicts on your draft" (0:55–1:40)

Action: Library settles into strength colors (strong/moderate/unscored). Open the **Draft
view**: the draft's section tree on the left with stance chips; select a section with
alignments; scroll an alignment card: stance banner, relevance meter, rationale, evidence
quote with **✓ verified** badge; point at an **unverified** badge on another card. Click
"view in graph" -> the section's subgraph filters instantly.

> "Set one paper as your draft, and every paper you add gets a verdict: which of YOUR
> sections it strengthens, challenges, or offers an alternative to — with evidence quoted
> from the source paper and verified verbatim against its text. When a quote can't be
> found, the Lab shows it anyway and says so. Cards are color-coded by an explainable
> strength score — every signal visible, nothing hidden."

## Beat 3 — "Ask the lab" (1:40–2:20)

Action: **Ask view**. Type a real question about the corpus, scope "Whole lab" (or a
draft section). The grounded answer renders with [n] citation chips; hover one (mini-card),
click through to the paper. Show the grounding strip ("Grounded in 6 sources across 2
papers") and — if present — the unverified-quote warning panel. Quick cut: **Compare** two
papers -> shared/unique entity columns + results table. End frame: full graph, stats line.

> "Ask anything. Answers come only from your library — retrieved section by section for
> token efficiency, cited so you can check, and any quotation the model can't back up
> verbatim is flagged. Everything you saw is one pip install, MIT-licensed, with 868 tests
> and a zero-key offline demo. Research Companion: a research assistant you can verify."

---

## Recording checklist
- [ ] LIVE badge + growing graph clearly visible in Beat 1 (this is the money shot)
- [ ] One real failure card + Retry shown
- [ ] One ✓ verified AND one unverified evidence badge shown in Beat 2
- [ ] Citation chip hover + click shown in Beat 3
- [ ] No API keys or personal paths visible on screen
- [ ] Replace [LINK] in paper/main.tex abstract footnote with the uploaded video URL
