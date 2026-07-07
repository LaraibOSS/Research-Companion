# Research Companion — Demo Video Script (≤ 2:30, target 2:20)

**EMNLP 2026 System Demonstrations. HARD CAP: 2.5 minutes** — this script
targets 2:20 to leave editing headroom. Screencast with audio narration
(the format the call prefers). Record at 1440×900 or 1920×1080, dark theme,
100% zoom. Every claim shown on screen must be real output.

Three beats: **zero-to-companion → it verifies and tells you what to do →
it knows the history** — then a 15-second close.

## Setup before recording
- Fresh research (create a new workspace in the UI — do NOT reuse Main) with
  your draft PDF ready and a folder of ~10 related PDFs, including one
  corrupt/scanned PDF for the failure beat. The draft should have a real
  bibliography so citation coverage fires on camera.
- API key already configured (do NOT show key entry — it costs seconds and
  shows nothing; the Settings page appears in the paper instead).
- Terminal one-liner ready: `pip install research-companion` typed but not
  yet run, then `research-companion lab serve`.
- Rehearse once so the auto-downloads land during the take (they start
  within ~3 seconds of setting the draft).

---

## Beat 1 — "Zero to companion" (0:00 – 0:40)

**Action:** run `pip install research-companion` (2 s, pre-cached), then
`research-companion lab serve`; browser opens on Home onboarding. Create the
research from the switcher ("New research"). Click "Add your draft" — the
Upload tab opens with "This is my draft ★" pre-checked; drag the PDF in.
Then "Ingest folder…" → cut to the **Graph view**: nodes bloom paper by
paper, LIVE badge, counters ticking; the corrupt PDF becomes a red failure
card with the reason and a Retry button.

> "One pip install. Research Companion turns your draft and the folder of
> papers around it into a live knowledge graph — sections, claims, methods,
> results. When a PDF can't be parsed, it tells you which one and why. No
> silent failures, ever."

## Beat 2 — "It verifies, downloads, and tells you what to do" (0:40 – 1:40)

**Action:** back on Home: the banner reads **"Analysis covers N of M cited
papers"**; the topbar spinner shows *"Downloading …"* and the Citations
panel rows flip **Downloading… → In library ✓** live — papers your draft
cites, fetched automatically; whatever can't be fetched stays honestly
listed as *Unresolved*. Then the Draft view: a section with an alignment
card — stance banner, evidence quote with **✓ verified** badge; point at an
**unverified** badge on another card. Open the suggestions bell: concrete,
sectioned advice. Click **Discuss** on one → the Companion answers with [n]
citations and — if present — the unverified-quote warning.

> "Your bibliography is ground truth: cited papers you're missing download
> themselves, and the banner tells you exactly how complete the analysis
> is. Every paper gets a verdict against YOUR sections — strengthens,
> challenges, alternative — with evidence quotes verified verbatim against
> the source. When a quote can't be found, it says so instead of hiding it.
> Don't agree? Ask. Answers are grounded, cited, and honest about what
> couldn't be verified."

## Beat 3 — "It knows the history" (1:40 – 2:05)

**Action:** **Timeline** view, Draft mode of the graph first for 3 seconds
(draft under the gold halo, papers arranged in STRENGTHENS / CHALLENGES /
ALTERNATIVE sectors), then Timeline with the gap overlay: amber diamonds =
limitations papers admitted themselves; click one → the verified quote from
that paper's limitations section; your draft is the blue diamond.

> "The graph arranges the literature around your draft by stance. The
> timeline shows how the field evolved — and which gaps papers admitted in
> their own words, quoted and verified. Gaps your draft addresses light up."

## Close (2:05 – 2:20)

**Action:** end frame: Home with the journey (v1 → v2, suggestions flipping
to Addressed), then the repo/PyPI line on screen:
`pip install research-companion · MIT · 1,435 tests`.

> "When you revise, it notices what you incorporated. Everything runs
> local, everything is checkable. Research Companion: a research assistant
> you can verify."

---

## Recording checklist
- [ ] **Total length ≤ 2:30** — time every take; cut Beat 3's graph shot
      first if over.
- [ ] Citation banner + rows flipping Downloading → In library on camera
      (money shot #1) — rehearse timing.
- [ ] LIVE graph growth + one real failure card with Retry (money shot #2).
- [ ] One ✓ verified AND one unverified evidence badge visible.
- [ ] Companion answer with citation chips + unverified-quote panel.
- [ ] Gap diamond click → verified limitation quote.
- [ ] No API keys or personal paths visible anywhere.
- [ ] Export MPEG-4; upload to YouTube (unlisted is fine); put the link in
      paper/main.tex abstract footnote (replace [LINK]) AND in the
      submission form.
