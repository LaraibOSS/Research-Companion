# Research Companion — Demo Video Script (~2:40)

Target: EMNLP 2026 System Demonstrations. Screen recording of the Research Lab
(`research-companion lab serve`) + one terminal. Record at 1440x900 or 1920x1080,
dark theme, browser at 100% zoom. Speak plainly; every claim shown on screen must be
real output.

Four beats: **zero-to-companion → it tells you what to do → it knows the history →
it's yours.**

## Setup before recording
- Fresh store (`RESEARCH_COMPANION_DIR` pointed at a clean dir) with your draft PDF ready
  and a folder of ~10 related PDFs (include one corrupt/scanned PDF for the failure beat).
- No `.env` yet — Beat 1 enters the API key through the Settings UI on camera (use a
  throwaway key and keep the field masked; the UI never echoes it back).
- `pip install research-companion` done (or `-e ".[server]"` from a checkout).
- Terminal one-liner ready: `research-companion lab serve`.

---

## Beat 1 — "Zero to companion" (0:00–0:45)

Action: `pip install research-companion` in the terminal, then `research-companion lab
serve`; the browser opens on **Home**, which greets you with the 4-step onboarding:
*Connect a model → Add your draft → Ingest a folder → Meet your suggestions*. Follow it:
open **Settings** from the onboarding card, paste the API key (masked ****xxxx), no
restart. Back on Home, add the draft PDF, then **Ingest folder...** — cut to the
**Graph view**: nodes bloom paper by paper, LIVE badge pulsing, counters ticking. The
corrupt PDF fails → red toast, honest failure card with one-click Retry.

> "One pip install and the Lab walks you in: connect a model, add your draft, point it
> at the folder where your papers already live. Agents split every paper into sections,
> extract claims, methods and results, and you watch your knowledge graph grow live.
> When a PDF can't be parsed it tells you which one and why — no silent failures."

## Beat 2 — "It tells you what to do next" (0:45–1:30)

Action: Home has become a dashboard: hero with the draft title, severity donut, paper
count, and the **Do this next** card. The **Open Suggestions** list shows concrete,
sectioned advice (§-labels visible). Click the bell → the suggestions panel docks right:
severity-grouped cards, each with a rationale and paper/Discuss/Dismiss. Click
**Discuss** on one → the Companion panel opens with that suggestion as context; ask
*"which of these related papers matters most for my related work?"* — a grounded answer
renders with [n] citation chips and, if present, the unverified-quote warning. Then
paste a revised draft (POST a v2 via the Draft view): the journey timeline records
**v2**, and watch suggestions flip to **Addressed** — the hero counter updates to
"N/M Addressed".

> "The Companion reads your draft against the literature and tells you what to do
> about it: discuss this paper as an alternative, back this claim, fix this citation —
> each tied to a section of YOUR draft. Don't agree? Talk to it. Every answer is
> grounded and cited, and any quote it can't verify verbatim is flagged. When you
> revise, it notices what you incorporated and marks it addressed — your revision
> history becomes a journey it tracks with you."

## Beat 3 — "It knows the history" (1:30–2:10)

Action: **Timeline view**. Concept/method/dataset strands per year; toggle the **Gap
overlay** — amber diamonds mark limitations papers left open, the blue diamond is your
draft. Click an open gap → detail panel with the verified evidence quote from the
source paper's limitations section + **Discuss** button. Point at a gap your draft
addresses (glowing/green). Quick cut: **Ask** with hybrid semantic search on (HF token
in Settings), grounding strip "Grounded in 6 sources across 2 papers" → **Save this
subgraph**, reopen it from the Graph view's Saved section.

> "The Lab also knows where the field has been: how concepts evolved year over year,
> and which gaps each paper admitted in its own limitations — quoted and verified. Gaps
> your draft addresses light up; open ones become suggestions. Every question you ask
> can be saved as a living subgraph of your library."

## Beat 4 — "It's yours" (2:10–2:40)

Action: **Settings**: flip dark → light theme, switch the accent, show masked keys and
the retrieval knobs. Open **Help** (?) — glossary table, five core flows. End frame:
full graph + stats line, then the repo/PyPI line on screen:
`pip install research-companion`.

> "Everything runs local: your papers, your graph, your keys — in a plain folder you
> own. Themes, accents, retrieval budgets: yours to tune. It degrades honestly too —
> no embeddings token, and search falls back to pure BM25; no LLM key, and the graph,
> timeline and search still work. MIT-licensed, 1,500+ tests, one pip install.
> Research Companion: a research companion you can verify."

---

## Recording checklist
- [ ] Onboarding stepper + in-UI key entry (masked) shown in Beat 1
- [ ] LIVE badge + growing graph clearly visible in Beat 1 (money shot #1)
- [ ] One real failure card + Retry shown
- [ ] Suggestion → Discuss → grounded cited answer chain shown in Beat 2 (money shot #2)
- [ ] A suggestion flipping open → Addressed after the v2 draft (money shot #3)
- [ ] Gap diamond click → verified evidence quote shown in Beat 3
- [ ] Theme flip + Help panel shown in Beat 4
- [ ] No real API keys or personal paths visible on screen
- [ ] Replace [LINK] in paper/main.tex abstract footnote with the uploaded video URL
