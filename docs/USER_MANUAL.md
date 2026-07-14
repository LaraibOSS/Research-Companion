# Research Companion — User Manual

**Version 0.6.2 · 2026-07-14 · MIT License · https://github.com/Laraib-Hasan-Future/Research-Companion**

This manual explains everything Research Companion does, how to use it, and —
just as important — how to read its outputs honestly. It assumes no prior
knowledge of the tool.

---

## 1. What is Research Companion?

Research Companion is an open-source assistant for people writing and
evaluating research papers. You give it papers — your own draft and the
literature around it — and a team of specialized AI agents reads them, builds
a shared knowledge graph, and answers the questions every author faces:
*Are my references real? Is my contribution actually novel? Which papers
support or threaten my draft, and where? Have I read everything my own
bibliography cites?*

The one-sentence version: **a team of AI helpers that reads your papers and
checks its own answers before showing you.** Most AI tools hand you fluent
text and leave you to wonder what is real. Research Companion is built the
other way around: every verdict carries evidence you can check, every quote
is verified verbatim against the source text, and when something cannot be
verified the tool says so on screen instead of hiding it.

It runs entirely on your machine (a local store in `~/.research-companion`),
talks to an AI provider you configure (Anthropic or OpenAI) only when a task
needs it, and costs pennies per paper. It ships with zero-key offline demos
so you can see everything work before configuring any account.

**Who it is for:** researchers and students preparing a submission; anyone
managing a growing pile of PDFs; reviewers and educators who want a working
example of verification-first LLM system design.

## 2. Installation & first launch

```
pip install research-companion
research-companion lab serve
```

Your browser opens **Research Companion** at `http://127.0.0.1:8765`. On first
launch a **"Get set up"** dialog prompts for your LLM key (required) and an
optional Hugging Face token for semantic search, and a four-step onboarding
walks you in:

1. **Connect a model** — open Settings, paste an Anthropic or OpenAI API key.
   Keys are stored in a local `.env` file (never in JSON, never committed),
   masked everywhere in the UI, and take effect immediately — no restart.
2. **Add your draft** — the Add Papers dialog opens on the Upload tab; drag
   your PDF in and tick **"This is my draft ★"**.
3. **Ingest a folder** — point it at the directory where your PDFs already
   live and watch the knowledge graph grow in real time.
4. **Meet your suggestions** — the bell icon opens concrete, sectioned advice.

Zero-key demos (from a source checkout): `python examples/demo_offline.py`
runs the full review pipeline with no network; `python examples/demo_lab_offline.py`
replays the Lab's event stream.

## 3. Core concepts

- **Research (workspace)** — one isolated project: its own papers, graph,
  draft, suggestions, gaps, timeline, saved views, and chat history. API keys
  and appearance settings are global; everything else is per-research.
- **Draft ★** — the one paper that is *yours*. Everything else is analyzed
  relative to it: alignments, suggestions, citation coverage, gaps.
- **Library** — the papers you have ingested. Each is split into sections,
  distilled into concepts/methods/datasets/claims/results, and merged into
  the cross-paper knowledge graph.
- **Verification** — the design principle. Citations are checked against
  live scholarly databases; evidence quotes are located verbatim in source
  text and badged verified/unverified; confidence scores are deterministic
  formulas with visible weights.

## 4. Researches (workspaces)

The top bar shows the active research as a dropdown (e.g. **"Main ▾"**).

- **Switch** — pick another research from the dropdown; the whole Lab reloads
  into it. Other open tabs reload automatically.
- **All researches…** — a card-per-research overview screen (name, draft
  title, paper count, open suggestions, last activity) with **create**,
  **rename**, **archive**, and **delete** actions.
- **Delete** — the trash icon on any card (archived ones included) deletes
  that research and everything in it. The confirmation names the research
  and its paper count so you know exactly what you are removing. If you
  delete the research you are currently in, the Lab switches you to another
  one automatically (Main preferred) and reloads. Deletion is blocked with
  a clear message while a background job is running. **Archive** remains the
  non-destructive option — it hides a research without deleting anything.
- **CLI:** `research-companion workspace list|create <name>|use <id-or-name>`;
  a single invocation can also be redirected with the
  `RESEARCH_COMPANION_WORKSPACE` environment variable.
- **Isolated per research:** papers, graph, draft pointer, suggestions, gaps,
  saved views, journey, conversations, event log. **Global:** API keys
  (`.env`), theme/accent/density, provider/model, retrieval knobs.
- **Upgrading from pre-0.4:** your existing store migrates automatically and
  losslessly into `workspaces/main/` on first run — atomic, resumable if
  interrupted, nothing re-ingested, `.env` untouched.

## 5. Adding papers

Click **"+ Add papers"** (top right). Three tabs:

- **Upload PDF** (default) — drag a PDF onto the dropzone or click to browse.
  The **"This is my draft ★"** checkbox uploads and marks your draft in one
  step. Duplicate uploads are recognized by content hash and answered gently
  ("Already in your library").
- **arXiv / URL / path** — type an arXiv ID (`2312.12345`), a DOI, a URL, or
  an absolute path to a PDF on disk.
- **Ingest folder** — a directory path; every PDF inside (including
  subfolders) is discovered and processed. The tab **scans the folder first**:
  before anything is ingested you see every PDF listed with a **New** or
  **Already in library** chip and a summary line (e.g. *"12 PDFs — 9 new, 3
  already in your library"*). Each file has a **checkbox** — new files are
  ticked by default; untick any you don't want (or use Select all / none), while
  files already in your library are locked. The button reads **"Ingest N
  selected"** and only the files you picked are ingested. During the run the
  progress dock (bottom-right) shows the full
  file list live — each file moves **Queued → Reading… → Added ✓ / Failed ✗
  / Skipped** — so you can watch exactly where the pipeline is and which files
  were already in your library. The list scrolls for large folders, and when
  the run finishes the dock summarizes *"X added, Y skipped, Z failed."*

Files that cannot be parsed (scanned/corrupt PDFs) become red failure cards
with the exact reason and a one-click **Retry** — no silent failures.

### What parses automatically, and what needs OCR

Every PDF goes through a pluggable parser layer. **Digital PDFs** (a real text
layer — most papers you download) parse automatically: the text is extracted,
split into sections, and analysed with no setup. By default this uses
**pypdfium2**, which handles single- and most multi-column layouts well.

**Scanned or image-only PDFs** have no text layer — there is nothing to read —
so out of the box they cannot be parsed. Rather than entering your library
empty and quietly breaking search, such a PDF now **fails honestly** with the
message *"No extractable text — the PDF appears to be scanned/image-only.
Install the OCR engine (pip install research-companion[docling]) or add the
paper's metadata by hand."* You have two ways to fix it:

- **Install the OCR engine.** `pip install research-companion[docling]` adds the
  optional **Docling** parser. It is detected and used automatically, and it
  brings three things: **OCR** (so scanned PDFs become readable text),
  **layout-aware reading order** (better on complex, multi-column, or
  figure-heavy papers), and **real document structure** (sections, tables, and
  figure captions read from the document itself rather than guessed). With it
  installed, retry the failed paper and it will ingest. OCR is slower than
  normal parsing — expect a scanned paper to take noticeably longer — because it
  runs full-page recognition over every page. While OCR runs, the progress
  indicator shows **"OCR-ing scanned PDF (may take a few minutes)…"** so a slow
  scan reads as *working*, not stalled. Once ingested, a paper whose text was
  recovered by OCR wears a quiet **OCR** badge in the Library (card and list
  views): a reminder that its text came from image recognition and may contain
  recognition errors, unlike a paper read from an embedded text layer. Digital
  PDFs show no badge.
- **Add metadata by hand.** If you don't want to install the OCR engine, you can
  still keep the paper: set its **title, authors, and year** with **Edit
  metadata** (section 6) so it appears on the timeline and in citation matching,
  and use **View original PDF** in the reader (section 11) to read the scanned
  source directly. The paper simply won't contribute its text to search or
  alignment until it has extractable text.

## 6. The Library

Two views, toggled at the top right of the Library:

- **Grid** — cards with strength colors and stance chips.
- **List** — a sortable table: Title (your draft pinned first with ★), Year,
  **Status** (`Queued` → `Processing` → `Ingested`, or `Failed` with inline
  Retry), **Strength**, **Relation** to your draft (strengthens / challenges
  / alternative), and Added. Status pills update live during a folder ingest.

**Strength** is a deterministic triage score computed from four visible
signals — extraction completeness (0.30), citation health (0.25), alignment
with your draft (0.25), recency (0.20) — renormalized over whichever signals
exist. Green = strong, yellow = moderate, orange = weak, gray = unscored.
It is a convenience for triage, not a judgment of the paper's science.

Every card (grid) and every row (list) carries a **Remove** button, so you
never have to open the drawer just to delete a paper. Removing the paper
marked as your draft ★ clears the draft flag automatically.

Click any row/card for the drawer: metadata, sections, alignment summary,
**Set as draft** / **Unset draft** (marking a draft is no longer one-way),
and Remove.

### Paper metadata — automatic and manual

Every paper carries a **title, authors, and year**. These are no longer just
the filename: when a paper is analysed the tool reads them straight from its
text and fills them in automatically, and existing papers that predate this
are backfilled once — any paper that has extracted text but no year is re-read
the first time you open its workspace to recover its metadata. **Scanned or
image-only PDFs with no extractable text cannot be auto-filled** — there is
nothing to read — so you set their metadata by hand.

- **"Needs metadata" indicator.** Any paper still missing authors or a year
  wears an amber **"Needs metadata"** marker in the Library, and a banner
  tells you how many papers need attention so nothing quietly stays
  half-identified.
- **Edit it by hand.** Open the paper's drawer and click **Edit metadata** to
  reveal a form for the **title**, **authors**, and **year** (the year is
  constrained to 1900–2100). Fill in what is missing or correct what was
  extracted and **Save**; the indicator clears once the paper has both authors
  and a year.

Metadata is not cosmetic — two features depend on it. The **Timeline**
(section 16) needs a year to place a paper at all, so papers only appear there
once their year is set. **Citation coverage** (section 7) matches a cited
reference to a paper you already own by **first-author surname + exact year**
as well as by title, so accurate authors and year stop the tool from urging
you to "Add" a paper that is already in your library.

## 7. Citation coverage — your bibliography as ground truth

When you set a draft, its References section is parsed (four splitting
strategies with sanity checks) and every cited paper is matched against your
library by arXiv ID, DOI, title, or **first-author surname + year**.

- **Automatic downloads** (default on): missing cited papers with a
  recognizable arXiv ID or DOI are downloaded and ingested with **zero
  clicks** the moment your draft or library changes. Title-only references
  get one automatic resolution pass against CrossRef/OpenAlex — deliberately
  conservative, because a false match would download the wrong paper.
  Settings → Citations → "Automatically download papers cited by your draft"
  is the off-switch (each download costs one model extraction call,
  ~$0.02–0.10).
- **The Citations panel** lists every cited paper with its status:
  *In library ✓*, *Downloading…*, *Add ↓* (one-click, or "Add all"),
  *Not checked*, *Unresolved ?* (could not be fetched — hover any row for
  the raw citation string).
- **The disclaimer banner** — whenever coverage is incomplete, every view
  shows a slim banner: *"Analysis covers N of M cited papers — Add missing."*
  Alignments, suggestions, and gaps are only as complete as the library they
  run against; the tool says so rather than letting partial coverage
  masquerade as a full picture. Collapsible per session; never disappears
  for good until coverage is complete.
- **Honest fallback:** if PDF text defeats bibliography parsing, the list
  falls back to the related-work extraction and says so in an amber note —
  labeled, never silent.

When automatic matching misses — a cited reference worded differently from a
paper's real title, say — you can **link it by hand**, from either side:

- **From the Citations panel.** Each not-in-library citation row has a
  **"Link…"** control that opens an inline dropdown of your library papers
  (the ones still needing metadata are listed first, since they are the
  likeliest matches). Pick the paper and the citation is linked to it.
- **From the paper drawer.** Open a library paper and use **"This is a cited
  reference…"** to attach it to one of your draft's citations from the paper
  side.
- **What the titles and years mean.** The picker shows titles and years drawn
  from your **draft's citations**, not from the papers themselves — a
  disclaimer says so — so you are choosing on the citation's terms, not the
  library's.
- **What linking does.** The citation is marked **In library** and the mark is
  durable: it survives coverage recomputes and reverts only if you delete the
  paper it points to. Linking also **backfills the paper's year** from the
  citation (year only) when the paper had none, so a previously yearless paper
  appears on the **Timeline** (section 16) right away. Authors are left
  untouched — fill those in with **Edit metadata** (section 6) when you want
  them.

## 8. Citation placement

Citation coverage asks *whether* each cited paper is in your library.
**Citation placement** asks a different question: is each cited paper
discussed in the draft section where it is **most relevant**? Open it from
the **map-pin button in the top bar** (visible with a draft set). Each cited
paper gets one of three verdicts:

- **Well-placed** — the paper is cited in the section it fits best.
- **Misplaced** — the paper would be more relevant in a different section
  than the one that cites it; the panel names the section it suggests.
- **Unknown** — placement could not be determined for that reference.

**Limitation (v1).** Placement only activates for **numbered `[n]`
bibliographies** parsed from the draft's References section — the analysis
needs the `[n]` markers to tie each in-text citation to a reference. Drafts
that use author–year (e.g. *(Smith et al., 2021)*) or any other
non-numbered citation style show **"not applicable"** rather than a guess.
There is no CLI command for placement; it is a Lab-only view.

## 9. The knowledge graph

Every paper becomes concepts, methods, datasets, claims, and results, merged
across papers (five papers mentioning GraphRAG = one node, five connections).

- **Draft view** (default when a draft is set) — a deterministic layout with
  your draft at the center under a gold halo, its sections as an inner ring,
  and every library paper placed in labeled sectors by how it relates:
  STRENGTHENS / CHALLENGES / ALTERNATIVE / unaligned, with relation-colored
  edges (green / red / amber). Click a paper to expand its extracted
  entities. Same graph, same picture, every time.
- **Explore view** — the free-form physics layout for open-ended browsing,
  with kind filters and search.
- **Section subgraphs** — the left panel filters the graph to any section of
  your draft.
- **Saved views** — save the subgraph behind any Ask answer (or hand-picked
  nodes) as a named view; pin, rename, reload from the Graph sidebar.
- **Entity provenance** — click a concept, method, or dataset node and its
  detail panel shows **"Appears in N papers"** with the contributing papers
  listed, so you can see at a glance which of your papers share it.

## 10. Draft analysis (alignments)

Every library paper gets a verdict against *your* sections: which it
**strengthens**, **challenges**, or offers an **alternative** to — each with
a relevance meter, a written rationale, and evidence quotes from the other
paper **verified verbatim** against its text (✓ verified / unverified badge
when the quote cannot be found). The Draft view shows your section tree with
stance chips; "view in graph" jumps to that section's subgraph.

## 11. Reading papers and sections

The Lab has a built-in **reader** so the source text is always one click from
any claim about it — you never have to leave the app to check what a paper
actually says.

**Ways to open it:**

- **A draft section** — click a section in the draft view's section list, or
  a section in the **graph** section list, to open the reader on your draft's
  extracted text, scrolled to that section and highlighted.
- **A paper** — the graph node's **"Read paper"** action, the **Read** button
  on any library card or list row, or the same button in the paper drawer,
  opens that paper's full extracted text.
- **An evidence quote** — click a **verified evidence quote** on a draft
  alignment card and the cited paper opens with that exact quote highlighted.
  Locating the quote is whitespace- and case-insensitive; if it cannot be
  located, the paper still opens with a notice rather than failing silently.

**Inside the reader:**

- A **section-navigation rail** lists the paper's sections; click any one to
  jump to it. The current section (or the located quote) is highlighted.
- **View original PDF** opens the stored PDF in a new browser tab.
- **Scanned PDFs** (and any paper with no extracted text) show a clear
  empty-state — *"No extracted text — use View original PDF"* — instead of a
  blank pane, so you always have a way to reach the source.

## 12. The review team

`research-companion review <paper-id> --serve --report out/` runs the full
pre-submission review with a live dashboard:

| Lane | What it does | What you get |
|---|---|---|
| citation | Resolves every bibliography entry against CrossRef → OpenAlex (arXiv IDs first) | verified / suspect / unverified per reference, with reasons |
| priorart | Retrieves related work via Semantic Scholar (OpenAlex fallback) | ranked closest prior papers |
| novelty | Extracts your claimed contributions with verbatim quotes; compares against prior art; verifies every quote | per-claim verdicts: novel / incremental / overlaps / anticipated |
| confidence | Deterministic score per claim from three signals (evidence verification 1.0, novelty confidence 0.8, citation health 0.6) | e.g. `0.72 ± 0.15` — the band widens when signals disagree |
| benchmark | Mines the graph and related work for evaluation benchmarks | suggested benchmarks you may be expected to report |
| statsoundness | Recomputes reported p-values from the test statistic + df (Statcheck) and checks reported means for arithmetic plausibility (GRIM) | consistent / inconsistent / decision-flip per test; impossible means |
| reproducibility | Deterministic scan for public code/data links, availability statements, methods-completeness, and EQUATOR/PRISMA/CONSORT mentions | high / medium / low reproducibility level + the specific gaps |
| ethics | Detects integrity declarations (funding, conflict-of-interest, ethics/IRB, informed consent, author contributions) | which declarations are present / missing |
| severity | Classifies all of the above signals critical / major / minor | a worst-first ranked list at the top of the report |
| venuefit | *(with `--venue <slug>`)* matches contributions + abstract against the venue's scope via a deterministic topic-overlap prefilter grounding an LLM verdict | strong / moderate / weak / out-of-scope + desk-reject risk |
| rebuttal | (own command) grounds point-by-point reviewer responses in retrieved passages | replies with honesty badges |

`statsoundness`, `reproducibility`, and `ethics` are deterministic and **always
on**; `severity` runs in the full pass; `venuefit` runs when you pass `--venue` (e.g.
`--venue neurips`). Venue scope, checklists, and desk-reject rules come from a
knowledge base you can extend without code — see [VENUE_KB.md](VENUE_KB.md).

Lanes run concurrently with failure isolation: one failing lane degrades the
report, never the run. `--fast` runs only LLM-free lanes. Every run appends
to a JSONL audit log.

## 13. Suggestions & revision tracking

Deterministic rules read your review, alignments, and gap map and produce
concrete, sectioned advice: *discuss paper X as an alternative in related
work*, *back this claim with evidence*, *fix this unverified citation*. Each
suggestion has a severity, a rationale, and a source; they live in the bell
panel with Dismiss / Discuss actions.

**Revision tracking:** when you upload a new version of your draft,
conservative matchers detect what you incorporated and flip those suggestions
to **addressed** automatically. Dismissals are sticky. The **Home** view
shows your journey: version pills, open/addressed counts, a severity donut,
and a "Do this next" card driven by simple rules.

## 14. Ask & search

Type a question in **Ask**; the tool ranks all paper sections and sends only
the best slices to the model. Answers come back with numbered citation chips
(hover for a mini-card; **click through to open the source paper in the
reader, scrolled to and highlighting the exact passage the answer drew
from** — verify it yourself, not just "somewhere in this paper"), a
grounding strip ("Grounded in 6 sources across 2 papers"), and a warning
panel listing any quoted span that could not be verified against the
sources. Questions can be scoped to a single section of your draft.

**Hybrid semantic search:** add a free Hugging Face token in Settings and
retrieval fuses BM25 with embedding similarity. Without the token, ranking
is byte-identical to pure BM25 — a tested degradation contract.

**Long sections are chunked, not truncated.** A section longer than roughly
1200 characters is split into overlapping, boundary-aware sub-chunks before
retrieval, and each chunk's full text is searchable — content deep in a long
section is no longer invisible to keyword search. Every retrieved chunk
carries its exact character span in the paper, so citation chips and the
reader (section 11) can point to and highlight the precise passage an answer
drew from, not just "somewhere in this section."

## 15. The Companion (chat)

The floating chat button opens the Companion — a candid senior-colleague
persona that can discuss any artifact: the review, a section's alignment, a
specific suggestion (click **Discuss** on it), a gap, or a paper. Answers are
grounded in retrieved sections with [S#] citations; quotes are verified
verbatim; unverifiable spans are flagged, not hidden. Clicking a citation
opens the reader at the exact source passage, the same span-jump as Ask.
Conversations persist on disk per research. With no review report yet, it
degrades to a project overview — it always answers.

Each thread has a **Clear chat** button that wipes its history and deletes
the conversation stored on disk — it works even if nothing has been
persisted yet.

## 16. Timeline & gaps

The **Timeline** lays out concepts, methods, and datasets by year — when each
first appeared and how it evolved. Toggle the **gap overlay**: amber diamonds
are limitations papers admitted in their own limitation/future-work sections
(quoted and verified verbatim); your draft is the blue diamond. Click a gap
for the evidence quote and a Discuss button. Gaps your draft addresses are
highlighted; open gaps relevant to your draft become suggestions.

## 17. Background activity

The Lab tells you what it is doing:

- **Topbar spinner** — appears whenever anything runs, with a live label:
  *"Downloading 1810.04805"*, *"Checking references…"*, *"3 tasks running"*.
- **Progress dock** (bottom) — one line per running task.
- **Downloading… chips** on citation rows being fetched right now.
- The coverage banner switches to in-flight text while downloads run.

A tab opened mid-work picks up running tasks immediately. Idle = invisible.

## 18. Settings reference

- **Model** — provider (Anthropic/OpenAI), model override, API keys
  (write-only fields, masked, stored in local `.env`, applied without
  restart).
- **Semantic search** — Hugging Face token for hybrid retrieval.
- **Appearance** — dark/light theme, three accents, comfortable/compact
  density.
- **Retrieval** — `k_sections` (default 6) and `char_budget` (default 8000)
  control how much context Ask/Companion retrieve.
- **Citations** — "Automatically download papers cited by your draft"
  (default on).
- **About** — replay the intro tour; links to docs.

Close Settings with the **×** button (top-right) or **Escape** — it returns you
to the view you came from.

## 19. CLI reference

Everything in the web UI has a command-line twin:

```
research-companion add <arXiv-id|DOI|URL|PDF...>   # add papers (batch/--from-file supported)
research-companion build                            # run extraction, build the graph (cached)
research-companion cost-estimate                    # projected API cost before building
research-companion list | remove | stats | search   # library management & keyword search
research-companion view                             # standalone interactive graph page
research-companion chat ["question"]                # conversational Q&A (REPL without arg)
research-companion ask "question"                   # token-efficient, citation-checked QA
research-companion set-draft <paper-id>             # anchor your draft
research-companion align <paper-id>                 # one alignment verdict
research-companion compare <A> <B>                  # side-by-side comparison
research-companion review <paper-id> [--serve] [--venue <slug>]  # the full review (+ dashboard, venue-fit)
research-companion rebuttal <paper-id> <reviews>    # grounded reviewer responses
research-companion refcheck <paper-id>              # citation validator standalone
research-companion check-stats <paper-id>           # recompute p-values + GRIM (Statcheck)
research-companion export-bib [--format bibtex|ris] # export the library as BibTeX/RIS
research-companion import-bib <file.bib>            # import a Zotero/Mendeley .bib into the library
research-companion cite-tex <file.tex> [--bib f.bib]  # resolve a LaTeX draft's \cite keys
research-companion discover <topic> [--expand]      # find new papers via Semantic Scholar
research-companion gaps | timeline                  # gap analysis / temporal view
research-companion export <format>                  # markdown, CSV, JSON, Obsidian vault
research-companion workspace list|create|use        # manage researches
research-companion lab serve|ingest|failures        # the web Lab
```

## 20. Data, privacy & costs

- **Everything is local.** The store lives at `~/.research-companion/`
  (override with `RESEARCH_COMPANION_DIR`): global `.env` (keys),
  `settings.json`, `workspaces.json`, and one folder per research under
  `workspaces/` — plain JSON and PDFs you can inspect.
- **What leaves your machine:** paper text goes to the AI provider you
  configured, only when a task needs it (extraction, alignment, answers);
  bibliographic lookups query CrossRef/OpenAlex/arXiv/Semantic Scholar;
  optional embeddings go to the Hugging Face Inference API. Nothing else.
- **Costs, measured live:** extraction ≈ $0.02 per paper (GPT-4o class);
  re-extracting a 16-paper library cost $0.51; an alignment or a grounded
  answer is one model call. Everything cached is free to re-run.

## 21. Reading outputs honestly

- **"Verified" means the quote exists** in the source text — it does *not*
  mean the claim is true. A real paper can be cited for a false claim; quote
  verification cannot detect that, and the tool never claims it can.
- **Quote verification is paraphrase-blind.** A fabricated paraphrase passes
  unflagged as long as nothing is quoted.
- **Novelty verdicts are relative to what retrieval surfaced.** If search
  missed the killer prior paper, the verdict cannot know about it. A pilot
  against human reviewers (n=10, published as an honest null) found the
  system identifies genuinely novel papers but under-penalizes weak ones —
  treat novelty as a structured second opinion, not a referee.
- **Scores are honest guesses.** Confidence weights (1.0/0.8/0.6) and
  strength weights (0.30/0.25/0.25/0.20) were chosen by judgment, not tuned
  on held-out data — they are printed on screen precisely so you can
  disagree.
- **Coverage caveats are load-bearing.** The "Analysis covers N of M cited
  papers" banner and the amber related-work-fallback note exist because
  partial context should never masquerade as a full picture.

## 22. Troubleshooting & FAQ

- **A PDF failed to ingest** — usually scanned (no text layer) or corrupt.
  The failure card shows the exact reason. If it says the PDF is
  scanned/image-only, install the OCR engine with
  `pip install research-companion[docling]` and Retry, or add the paper's
  metadata by hand and read the original PDF (see "What parses automatically,
  and what needs OCR" in section 5). Corrupt files: fix or re-download, then
  Retry.
- **"Bibliography could not be parsed" (amber note)** — two-column PDF text
  sometimes defeats the splitter; coverage falls back to the related-work
  extraction, clearly labeled. Hover rows to see raw strings.
- **"Connect a model" shows although I set a key** — keys entered in
  Settings apply instantly; keys set via environment variables are also
  detected. Check Settings → Model shows the provider you intend.
- **A cited paper stays "Unresolved"** — the conservative resolver refused
  to guess. Add it manually via the arXiv/DOI tab; precision beats a wrong
  download.
- **Where did my pre-0.4 store go?** — migrated automatically into
  `~/.research-companion/workspaces/main/`; nothing was lost.
- **Switching research reloads other tabs** — intentional; a tab must never
  show one research's data against another's store.

---

### Roadmap (planned, not yet shipped)

An MCP trust server ("a local, bounded, key-free trust server for citation
verification, quote grounding, citation coverage, and library search"),
biomedical/CS metadata connectors (PubMed, Europe PMC, DBLP), and
venue-checklist skill packs. See `docs/superpowers/specs/` for the design.

*Companion document: `docs/RESEARCH_COMPANION_GUIDE.pdf` — the guide &
critical analysis, including measured evaluations and known failure modes.*
