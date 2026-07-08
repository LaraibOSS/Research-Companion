# Research Companion — User Manual

**Version 0.5.4 · 2026-07-08 · MIT License · https://github.com/Laraib-Hasan-Future/Research-Companion**

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

Your browser opens the **Research Lab** at `http://127.0.0.1:8765`. On first
launch a four-step onboarding walks you in:

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
- **Ingest folder** — a directory path; every PDF inside is discovered and
  processed. You can watch the pipeline live: sections parsed, entities
  extracted, graph nodes blooming, per-file progress in the dock.

Files that cannot be parsed (scanned/corrupt PDFs) become red failure cards
with the exact reason and a one-click **Retry** — no silent failures.

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

## 7. Citation coverage — your bibliography as ground truth

When you set a draft, its References section is parsed (four splitting
strategies with sanity checks) and every cited paper is matched against your
library by arXiv ID, DOI, or title.

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

## 8. The knowledge graph

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

## 9. Draft analysis (alignments)

Every library paper gets a verdict against *your* sections: which it
**strengthens**, **challenges**, or offers an **alternative** to — each with
a relevance meter, a written rationale, and evidence quotes from the other
paper **verified verbatim** against its text (✓ verified / unverified badge
when the quote cannot be found). The Draft view shows your section tree with
stance chips; "view in graph" jumps to that section's subgraph.

## 10. The six-lane review

`research-companion review <paper-id> --serve --report out/` runs the full
pre-submission review with a live dashboard:

| Lane | What it does | What you get |
|---|---|---|
| citation | Resolves every bibliography entry against CrossRef → OpenAlex (arXiv IDs first) | verified / suspect / unverified per reference, with reasons |
| priorart | Retrieves related work via Semantic Scholar (OpenAlex fallback) | ranked closest prior papers |
| novelty | Extracts your claimed contributions with verbatim quotes; compares against prior art; verifies every quote | per-claim verdicts: novel / incremental / overlaps / anticipated |
| confidence | Deterministic score per claim from three signals (evidence verification 1.0, novelty confidence 0.8, citation health 0.6) | e.g. `0.72 ± 0.15` — the band widens when signals disagree |
| benchmark | Mines the graph and related work for evaluation benchmarks | suggested benchmarks you may be expected to report |
| rebuttal | (own command) grounds point-by-point reviewer responses in retrieved passages | replies with honesty badges |

Lanes run concurrently with failure isolation: one failing lane degrades the
report, never the run. `--fast` runs only LLM-free lanes. Every run appends
to a JSONL audit log.

## 11. Suggestions & revision tracking

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

## 12. Ask & search

Type a question in **Ask**; the tool ranks all paper sections and sends only
the best slices to the model. Answers come back with numbered citation chips
(hover for a mini-card, click through to the paper), a grounding strip
("Grounded in 6 sources across 2 papers"), and a warning panel listing any
quoted span that could not be verified against the sources. Questions can be
scoped to a single section of your draft.

**Hybrid semantic search:** add a free Hugging Face token in Settings and
retrieval fuses BM25 with embedding similarity. Without the token, ranking
is byte-identical to pure BM25 — a tested degradation contract.

## 13. The Companion (chat)

The floating chat button opens the Companion — a candid senior-colleague
persona that can discuss any artifact: the review, a section's alignment, a
specific suggestion (click **Discuss** on it), a gap, or a paper. Answers are
grounded in retrieved sections with [S#] citations; quotes are verified
verbatim; unverifiable spans are flagged, not hidden. Conversations persist
on disk per research. With no review report yet, it degrades to a project
overview — it always answers.

Each thread has a **Clear chat** button that wipes its history and deletes
the conversation stored on disk — it works even if nothing has been
persisted yet.

## 14. Timeline & gaps

The **Timeline** lays out concepts, methods, and datasets by year — when each
first appeared and how it evolved. Toggle the **gap overlay**: amber diamonds
are limitations papers admitted in their own limitation/future-work sections
(quoted and verified verbatim); your draft is the blue diamond. Click a gap
for the evidence quote and a Discuss button. Gaps your draft addresses are
highlighted; open gaps relevant to your draft become suggestions.

## 15. Background activity

The Lab tells you what it is doing:

- **Topbar spinner** — appears whenever anything runs, with a live label:
  *"Downloading 1810.04805"*, *"Checking references…"*, *"3 tasks running"*.
- **Progress dock** (bottom) — one line per running task.
- **Downloading… chips** on citation rows being fetched right now.
- The coverage banner switches to in-flight text while downloads run.

A tab opened mid-work picks up running tasks immediately. Idle = invisible.

## 16. Settings reference

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

## 17. CLI reference

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
research-companion review <paper-id> [--serve]      # the six-lane review (+ dashboard)
research-companion rebuttal <paper-id> <reviews>    # grounded reviewer responses
research-companion refcheck <paper-id>              # citation validator standalone
research-companion discover <topic> [--expand]      # find new papers via Semantic Scholar
research-companion gaps | timeline                  # gap analysis / temporal view
research-companion export <format>                  # markdown, CSV, JSON, Obsidian vault
research-companion workspace list|create|use        # manage researches
research-companion lab serve|ingest|failures        # the web Lab
```

## 18. Data, privacy & costs

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

## 19. Reading outputs honestly

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

## 20. Troubleshooting & FAQ

- **A PDF failed to ingest** — usually scanned (no text layer) or corrupt.
  The failure card shows the exact reason; Retry after fixing the file. OCR
  is not yet supported.
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
