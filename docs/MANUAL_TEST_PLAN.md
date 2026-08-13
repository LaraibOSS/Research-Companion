# Research Companion — Manual Test Plan

**Scope:** the Brainstorm/ideation arc and the clarity & trust work (per-page help, provenance, research identity, add feedback, discovery filters, Timeline).
**Audience:** a tester with no prior knowledge of this codebase.
**Last updated:** 2026-08-13 · covers everything merged up to `main` @ PR #73.

---

## 1. Before you start

### 1.1 Run the app

```bash
cd <repo root>
pip install -e ".[server]"
research-companion lab serve            # opens http://127.0.0.1:8765
```

If a server is already running on that port, use `--port 8800` and adjust the URLs below.

### 1.2 Configure it (needed for anything AI-powered)

Open **Settings** (left nav, bottom) and set:

| Setting | Why | Required for |
|---|---|---|
| **Provider + API key** (Anthropic or OpenAI) | All AI features | §5, §6, §7, §9 |
| **Contact email** | Raises the OpenAlex rate limit ("polite pool") | §4 (reduces failures) |
| **Semantic Scholar API key** — free from <https://www.semanticscholar.org/product/api> | Raises the S2 rate limit substantially | §4 (reduces failures) |

Without an AI key, the deterministic features (§3, §8, §10, §11) still work; AI features will report a missing model rather than crashing — **that is correct behavior, not a bug.**

### 1.3 Two test workspaces

Several tests need a **brand-new, empty** research. Create one from **Researches → + New research** (e.g. `QA-Empty`). Keep a second research with real papers in it (e.g. `QA-Full`) for the tests that need data.

### 1.4 Read this before filing a bug

**Rate limiting is expected, not a bug.** The paper catalogues (Semantic Scholar, OpenAlex) are free, keyless and shared. Adding 20 papers then searching repeatedly *will* trip a limit. The correct behavior is a **friendly message**, not a crash:

> "Search is rate-limited right now — the paper catalogues are free and shared, so they throttle bursts. Wait a minute and try again."

Seeing a raw `Client error '429 Too Many Requests' for url ...` **is** a bug — report it. Seeing the friendly message is a pass. Note that once a limit is hit, setting the email/API key does **not** lift it immediately; the window has to pass.

### 1.5 How to report

For each case record: **PASS / FAIL / BLOCKED**, the browser console output (F12 → Console) if anything looks broken, and a screenshot for visual issues. A blank page or a `ReferenceError` in the console is always a bug — report it with the console text.

---

## 2. Smoke test (do this first — 2 minutes)

| # | Step | Expected |
|---|---|---|
| 2.1 | Open the app | Loads without an error page |
| 2.2 | Open F12 → Console | **No red errors** (a 404 for a favicon is fine) |
| 2.3 | Click every left-nav tab in turn: Home, Brainstorm, Researches, Library, Graph, Draft, Timeline, Gaps, Report, Ask, Compare, Citations, Notes | Every tab renders content. **A blank tab is a bug** — note which one and the console text |
| 2.4 | Look at the top bar | Shows the active research name, **never** "Research: none" while a research is selected |

**If 2.3 fails, stop and report** — everything downstream will fail too.

---

## 3. Per-page help and the AI disclaimer

Applies to **every** tab.

| # | Step | Expected |
|---|---|---|
| 3.1 | On any tab, look at the bottom-right | A small round **`?`** button is present (above the chat bubble) |
| 3.2 | Click it | A panel opens with the page name, a short paragraph on **what the page does**, a **"What it uses"** section, and a reliability/verification section |
| 3.3 | Press **Escape**, then click `?` again | Panel closes, then reopens (it is permanent — it must never disappear for good) |
| 3.4 | Repeat 3.1–3.2 on **all 13 tabs** | Every tab has a `?` with copy specific to that page — not generic filler |
| 3.5 | Open `?` on **Brainstorm, Draft, Report, Ask, Gaps, Graph, Compare** | Shows an **AI disclaimer**: content is AI-assisted, can be wrong, verify before citing |
| 3.6 | Open `?` on **Library, Timeline, Citations, Notes, Researches** | States **no AI is used** and the result is deterministic |
| 3.7 | Open `?` on **Timeline** | Explains how to read the page *and* why some papers may be missing (no publication year) |

---

## 4. Brainstorm — search, result count, ranking

Use the `QA-Full` research.

| # | Step | Expected |
|---|---|---|
| 4.1 | Go to **Brainstorm**. Look at the controls beside the search box | A **result-count** dropdown (20 / 30 / 40 / 50) and a **rank** dropdown (Balanced / Most cited / Top venues) |
| 4.2 | Type a topic (e.g. `knowledge graph retrieval`) → **Search** | Results appear. Each row shows title, authors, year, citation count, and a source badge |
| 4.3 | Set count to **50**, search again | Noticeably more results than the default 20 (subject to what the source returns) |
| 4.4 | Set rank to **Most cited**, search | Results ordered by citation count, highest first |
| 4.5 | Set rank to **Top venues**, search | Papers from recognized venues (NeurIPS, ICML, ACL, EMNLP, ICLR, AAAI, …) appear **first** |
| 4.6 | Look for a **venue badge** on rows | Recognized venues show a pill with the venue name; unrecognized ones show plain text or nothing |
| 4.7 | Set rank to **Balanced**, search | A mix — heavily-cited papers still rank high, but recent top-venue papers are not buried at the bottom |
| 4.8 | Search rapidly ~10 times in a row | Eventually the **friendly rate-limit message** (§1.4), never a raw HTTP error |

> ⚠️ **§4.6 is the highest-priority unverified item.** The venue badge has never been confirmed against live data (the dev machine was continuously rate-limited). Please record **how many of ~20 results show a venue badge**. If it is near zero, that is a real finding — report it.

---

## 5. Brainstorm — adding papers

| # | Step | Expected |
|---|---|---|
| 5.1 | Search, then click **Add** on one result | A confirmation **receipt** appears near the top of the tab |
| 5.2 | Read the receipt | States how many papers are being added **and into which research by name**; links to **View in Library**; includes a disclaimer that PDFs which fail to download must be added manually |
| 5.3 | Click the receipt's **×** | It dismisses |
| 5.4 | Click **Add all** | Receipt reports the number queued |
| 5.5 | Click **Add all** again immediately (everything now in library) | Receipt says **"Nothing to add"** and reports how many were **skipped as already present** — it must not silently do nothing |
| 5.6 | Go to **Library** while papers are still being added | Papers appear with a processing state; the UI stays responsive (navigation is never blocked) |
| 5.7 | Wait for ingestion to finish | Papers reach a finished state; any that failed are clearly marked |
| 5.8 | Note a failed paper (if any) | It is marked failed with a reason — this is expected for publishers that block downloads, and the receipt already told you to add those manually |

---

## 6. Brainstorm — Research Directions

| # | Step | Expected |
|---|---|---|
| 6.1 | Scroll to **Research Directions** | An intro paragraph explains what it does and what it reads (your topic, the papers you added, the concept graph, open gaps) |
| 6.2 | While papers are still being added, look above the button | A notice: *"N papers are still being added. Generate now and directions will only use the M already analyzed."* |
| 6.3 | Wait until ingestion finishes, watch the notice | It updates on its own — it must not stay stale |
| 6.4 | With papers that were never analyzed (e.g. failed), check the notice | Says they have **not been analyzed yet** and to retry from the Library — it must **not** say "still being added" (that would imply waiting for something that will never arrive) |
| 6.5 | Click **Generate directions** | A ranked list of directions appears, each with a rationale, a type badge, and **citation chips** |
| 6.6 | Look directly under the results | A **provenance line**: *"Grounded in X papers, Y concepts from your graph, and Z open gaps."* The numbers should be plausible for your library |
| 6.7 | Look at the bottom of the section | A disclaimer that results are AI-suggested, **not exhaustive**, and come only from the papers you added |
| 6.8 | Click a citation chip | Opens that paper in the Library |
| 6.9 | Click **Check novelty** on a direction | A verdict against real prior work, clearly labelled as a model judgment |

---

## 7. Brainstorm — the Brief

| # | Step | Expected |
|---|---|---|
| 7.1 | Scroll to **Brief** → click **Generate brief** | Section headings appear, each with several bullet points |
| 7.2 | Inspect the bullets | Every AI bullet carries a **citation chip** to one of your papers. A bullet with no citation should not exist |
| 7.3 | Read the caption | States the brief is AI-suggested, grounded in your papers, and free to edit |
| 7.4 | Hover a bullet | Row actions appear: **Edit, ↑, ↓, + note, ×** |
| 7.5 | Click **Edit**, change the text, **Save** | The bullet updates and keeps the change |
| 7.6 | Use **↑ / ↓** | The bullet moves within its section; it cannot move past the first/last position |
| 7.7 | Click **+ bullet** under a section, type text, save | Your bullet is added and marked as **your note** (no citation — correct, since you wrote it) |
| 7.8 | Click **×** on a bullet, and **Remove** on a section | They are deleted |
| 7.9 | Click **+ note** on a bullet, write something, save | Confirmation appears; the note shows up in the **Notes** tab |
| 7.10 | Click a citation chip | Opens that paper in the Library |

---

## 8. Session persistence

| # | Step | Expected |
|---|---|---|
| 8.1 | In Brainstorm: search, add papers, generate directions, generate a brief | All present |
| 8.2 | Navigate to another tab, then back to Brainstorm | **Everything is still there** — topic in the box, results, directions, brief |
| 8.3 | Reload the browser (F5), return to Brainstorm | Still there |
| 8.4 | Switch to a **different research**, go to Brainstorm | That research's own session (likely empty) — sessions must not leak between researches |
| 8.5 | Switch back to the first research | Its session is restored |

---

## 9. Research identity (top bar, Home, first entry)

| # | Step | Expected |
|---|---|---|
| 9.1 | With a research selected, check the top bar | Shows the **research name**. "Research: none" here is a bug |
| 9.2 | Go to **Home** with a draft set | Shows **"◆ Research Companion / \<research name\>"** — both the product name and the active research, even in dashboard mode |
| 9.3 | Switch research from the top-bar dropdown | Top bar and Home both update to the new name |
| 9.4 | Open **Brainstorm** in a research where none is active (or a fresh install) | You are prompted to **name the research project** up front |
| 9.5 | Dismiss that prompt | An inline banner remains: *"Name your research project to get started"* with a button — work must never land nowhere |
| 9.6 | Click that button and name it | Prompt disappears; the name appears in the top bar |
| 9.7 | On a **brand-new empty** workspace, open **Home** | A two-path chooser: **Brainstorm from an idea** / **I already have a draft** |
| 9.8 | Click each path | First goes to Brainstorm; second opens the draft-upload flow |
| 9.9 | Add a paper, return to Home | The chooser is gone (it is first-run only) |

---

## 10. Draft tab

| # | Step | Expected |
|---|---|---|
| 10.1 | In Brainstorm, click **Draft this direction** on a direction | A draft is created and becomes active |
| 10.2 | Open the **Draft** tab | The draft's **outline sections are listed immediately** — "No sections found" is a bug |
| 10.3 | Look at the toolbar | A hint that the draft has not been analyzed yet, plus an **Analyze this draft** button |
| 10.4 | Click a section | The detail pane shows it, saying no papers are aligned yet |
| 10.5 | Click **Analyze this draft** | A background job starts with progress; the UI stays usable |
| 10.6 | Wait for it to finish | Sections populate with stance chips (strengthens / challenges / alternative) |
| 10.7 | Open an alignment card | Shows rationale and evidence quotes, with verified/unverified badges |
| 10.8 | With no papers analyzed at all, click **Analyze this draft** | A clear message explaining why it cannot run — never a crash |
| 10.9 | Check the draft in **Library** | It is **not** stuck showing as pending/unprocessed |

---

## 11. Timeline

| # | Step | Expected |
|---|---|---|
| 11.1 | Open **Timeline** | Below the toolbar, an explanation of **how to read the grid**: what a row is, what a column is, what a dot means |
| 11.2 | Read it | It says what to *conclude* (a long row = an enduring idea, a recent row = emerging, an empty stretch = a period your library misses) — not just labels |
| 11.3 | Check the colour key | **Concept / Method / Dataset** swatches whose colours match the dots in the chart |
| 11.4 | If any papers lack a year | A note states how many cannot be placed and to add the year from the Library |
| 11.5 | Toggle **Concepts / Methods / Datasets** chips | Rows filter accordingly |
| 11.6 | Toggle **Gap overlay** | Gap diamonds appear/disappear; the diamond legend explains open / partial / addressed / your draft |

---

## 12. Regression sweep (things that broke before — verify they stay fixed)

| # | Check | Expected |
|---|---|---|
| 12.1 | Open Brainstorm and check the console | No `ReferenceError`. The tab has been blanked twice by this exact bug |
| 12.2 | Top bar with a research active | Never "Research: none" |
| 12.3 | Draft tab on a newly created draft | Outline shows immediately, not "No sections found" |
| 12.4 | Trigger a search rate limit | Friendly message, never a raw `429` HTTP dump |
| 12.5 | Settings → set **Contact email**, save, reload | The value **persists** (it was silently discarded before) |
| 12.6 | Settings → set the **Semantic Scholar API key**, save, reload | Persists (shown masked) |

---

## 13. Known limitations (do not file these)

- **Rate limiting** — see §1.4. Expected under bursty use; the settings in §1.2 reduce but cannot eliminate it, and never lift a limit already hit.
- **Venue recognition is best-effort.** The venue knowledge base holds short names (NeurIPS, ACL…). A source reporting only a long form with no acronym will not be badged. Still worth reporting *how often* badges appear (§4.6).
- **AI output can be wrong.** Directions, briefs, novelty verdicts, alignments and reports are model-generated. Content being imperfect is not a bug; content presented as *verified fact*, or a citation pointing at a paper you do not have, **is**.
- **Coverage percentages** in the Report are a keyword-search heuristic, labelled as such — not ground truth.

---

## 14. Summary sheet

| Section | Area | Result | Notes |
|---|---|---|---|
| 2 | Smoke test | | |
| 3 | Per-page help + AI disclaimer | | |
| 4 | Search, count, ranking, venue badge | | **record badge count (§4.6)** |
| 5 | Adding papers | | |
| 6 | Research Directions | | |
| 7 | Brief | | |
| 8 | Session persistence | | |
| 9 | Research identity | | |
| 10 | Draft tab | | |
| 11 | Timeline | | |
| 12 | Regression sweep | | |
