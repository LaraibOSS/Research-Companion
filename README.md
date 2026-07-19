# Research Companion

[![CI](https://github.com/Laraib-Hasan-Future/Research-Companion/actions/workflows/ci.yml/badge.svg)](https://github.com/Laraib-Hasan-Future/Research-Companion/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10–3.13](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)](pyproject.toml)

> Drop arXiv URLs, DOIs, or PDFs in. Get a knowledge graph and a chat interface that answers questions with paper citations. Local-first. Open source.

This repository is the canonical home of Research Companion. The source tree is at
`0.7.1`; the latest PyPI release is `0.5.14` (publishing is currently held), so a
`pip install -e .` from source is ahead of PyPI.

```bash
git clone https://github.com/Laraib-Hasan-Future/Research-Companion.git && cd Research-Companion && pip install -e .
research-companion add https://arxiv.org/abs/2410.05779
research-companion add https://arxiv.org/abs/2404.16130
research-companion build
research-companion view                                  # opens an interactive HTML graph
research-companion chat "what are the main approaches?"  # KG-aware Q&A with citations
```

---

## Research Lab (new in 0.2)

The Research Lab is a live-growing knowledge-graph workspace that runs in your browser.  Drop a folder of PDFs in — or point the CLI at one — and papers stream into a vis.js graph in real time over SSE.  As each paper lands, the system builds a section-wise subgraph (one subgraph per logical section), scores every section against your draft paper with alignment verdicts (`strengthens / challenges / alternative`) backed by verified evidence quotes, and colours each paper node by its evidence-strength score (strong / moderate / weak).

Use **Ask** for token-efficient, section-scoped Q&A — every answer cites the exact section it draws from — and **Compare** for a structured head-to-head comparison of any two papers.

```bash
pip install -e ".[server]"
research-companion lab serve              # opens http://127.0.0.1:8765
research-companion lab ingest <folder>   # ingest a folder from the CLI
research-companion set-draft <paper-id>  # set the paper you are writing
research-companion align <paper-id>      # score a paper against your draft
research-companion ask "how does X compare to Y?"
research-companion compare <paper-a> <paper-b>

# Lab CLI twins
research-companion lab failures          # list ingestion failures
python examples/demo_lab_offline.py      # zero-key, zero-network demo
```

Section-wise subgraphs keep retrieval focused: when you Ask or Align, only the subgraph for the matching sections is used, which cuts token cost and improves precision over whole-paper retrieval.

## Documentation

- **[Full Documentation](docs/DOCUMENTATION.md)** ([PDF](docs/DOCUMENTATION.pdf)) — the single consolidated reference: overview, architecture, every feature, CLI, agents, Lab UI, tech stack, and roadmap, all in one place.
- **[User Manual](docs/USER_MANUAL.md)** ([PDF](docs/USER_MANUAL.pdf)) — every feature, how to use it, and how to read outputs honestly.
- [Developer Guide](docs/DEVELOPER_GUIDE.md) — how the ingestion pipeline works end to end (parsing, quality gate/OCR, sectioning, chunking, retrieval) and how to extend or test it.
- [Roadmap](docs/ROADMAP.md) — what's shipped and what's next.
- Release notes: [0.7](docs/RELEASE_0.7.md) · [0.6](docs/RELEASE_0.6.md) · [0.5](docs/RELEASE_0.5.md) · [0.4](docs/RELEASE_0.4.md) · [0.3](docs/RELEASE_0.3.md) · [0.2](docs/RELEASE_0.2.md)

## What's new since 0.7 — the integrity & trust layer

Research Companion grew from "help me read papers" into "help me get a paper submission-ready." The review now opens with a single go/no-go verdict, and everything under it is checkable:

- **Submission-readiness verdict** — every review is topped with *ready / revise / not ready* and a prioritized, cross-lane "fix this first" list, aggregated from whatever checks ran, with honest caveats for what didn't. Opt into the `readiness_narrative` setting for an LLM "reviewer's take" on top (grounded strictly in the verdict — it can reorder and rephrase the fix list, never invent findings).
- **Desk-reject compliance linter** (`check-compliance`, and inside `review --venue`) — deterministic checks for what gets papers desk-rejected before review: page/length limits, missing required sections, double-blind anonymization leaks, and citation completeness.
- **Statistical soundness** (`check-stats`) — recomputes reported p-values (Statcheck) and sanity-checks reported means (GRIM), flagging numbers that don't add up. No LLM.
- **Near-duplicate & paraphrase overlap** (`check-overlap`) — flags passages that duplicate another paper in your library; an opt-in local-embedding pass also catches reworded/translated reuse.
- **Domain connectors** — opt-in **PubMed**, **Europe PMC**, and **DBLP** sources so biomedical and CS references verify and prior-art reaches beyond the general databases (`--connectors dblp` etc.; off by default, byte-identical when disabled).
- **MCP trust-layer server** (`mcp serve`) — exposes four deterministic, key-free verification tools (verify a citation, ground a claim, check citation coverage, search your library) to any MCP-capable agent, plus two opt-in costed tools (`ask_library`, `review_draft`) behind an explicit setting, a configured key, and a per-call cost cap — off by default.
- **Interoperability** — BibTeX/RIS export, `.bib` import from Zotero/Mendeley, and LaTeX `\cite`-key resolution (`export-bib` / `import-bib` / `cite-tex`).

Everything above is deterministic at the core, opt-in wherever it costs money or sends data anywhere, and designed to leave the tool byte-identical when a feature is off. See the [Roadmap](docs/ROADMAP.md).

## What's new in 0.6

The review team learned to answer three more of a reviewer's questions — deterministically, with the same evidence-first discipline as the rest of the tool. A `review` now also tells you **whether the paper fits its target venue**, **which problems to fix first**, **whether the work is reproducible**, and **whether the required integrity declarations are present**:

- **Venue-fit checker** (`research-companion review <paper> --venue neurips`) — matches your contributions and abstract against a target venue's scope using a deterministic topic-overlap prefilter that grounds an LLM fit verdict (strong / moderate / weak / out-of-scope) plus a desk-reject risk. Backed by a **cross-discipline venue knowledge base** (`research_companion/data/venues.json`, 19 venues across 9 disciplines) that you extend by editing JSON — no code change (see [docs/VENUE_KB.md](docs/VENUE_KB.md)).
- **Severity-ranked findings** — the review's signals (novelty, unverified evidence, citation health, confidence) are now classified **critical / major / minor** and surfaced worst-first at the top of the report, so you know what to fix first.
- **Reproducibility checker** — a deterministic scan for public code/data links, availability statements, methods-completeness signals, and EQUATOR/PRISMA/CONSORT checklist mentions → a high / medium / low reproducibility level with the specific gaps.
- **Integrity-declaration detector** — checks for the declarations venues increasingly require (funding, conflict-of-interest, ethics/IRB approval, informed consent, author contributions) and reports what's missing.

All four are **deterministic and LLM-free at the core** (the venue-fit verdict is the only LLM step, and it's grounded by the deterministic overlap). See the [Release Notes](docs/RELEASE_0.6.md).

## What's new in 0.5

Citation coverage: the papers your draft **cites** are now first-class. The Lab parses your draft's bibliography, shows which cited papers are in your library and which are missing, downloads missing ones in one click ("Add all"), and displays a persistent disclaimer whenever the analysis is running on partial coverage — *"Analysis covers N of M cited papers"* — so incomplete context is never silent. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.17** — reliability & UX pass: ingestion never takes the server down (Docling OCR now runs in an isolated subprocess — a native crash/timeout falls back to the fast reader instead of killing the Lab); citation coverage is accurate (truncated parses fall back to pypdfium so the reference list survives, and a new parser reads line-numbered ACL/arXiv bibliographies); citation-**placement** now handles author-year styles ("(Smith et al., 2020)"), not just `[n]`; the library de-duplicates the same paper added via arXiv **and** as a local PDF; the Ask tab no longer 500s under an OpenAI-only key. Plus a first-launch "Get set up" key prompt, a closable Settings page (× / Esc), a "start a new research" nudge, clearer duplicate-upload feedback, and honest counts/labels. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.16** — pick exactly which files to ingest, and a proper front door: the "Ingest folder" scan-review list now has a **checkbox per PDF** so you can select or deselect specific files (already-in-library ones are locked) and ingest only the ones you want. The no-project home screen is now a clean, professional **Research Companion** welcome — the product is named Research Companion throughout the app. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.15** — folder ingest, file by file: choosing a folder now **scans it first** — you see every PDF and which ones are already in your library before committing — and during the run the progress dock shows a live per-file list, each file moving Queued → Reading → Added ✓ / Failed ✗ / Skipped. Already-in-library files, previously skipped silently, are now shown explicitly. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.14** — ingestion transparency: the Lab now records and shows *how* each paper was read. Scanned PDFs that need OCR show a clear **"OCR-ing scanned PDF (may take a few minutes)…"** state while it runs (instead of a progress bar that appeared to stall), and papers recovered by OCR carry a quiet **OCR** badge in the library so you know their text came from image recognition rather than an embedded text layer. Purely additive. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.13** — internal cleanup: trimmed an unused dependency (`pypdf` — the PDF backend is pypdfium2), removed a dead frontend module and its stale test, and hardened test isolation so the suite is reliably green. No user-facing changes. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.12** — knowledge-graph entity provenance: every concept, method, dataset, claim, and result node now records which of your papers it appears in — the node detail panel shows **"Appears in N papers"** with the contributing papers listed, so you can see at a glance which methods/datasets/concepts your library shares. Purely additive; no graph restructure. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.11** — verifiable answers: clicking a `[n]` citation in Ask or the Companion now opens the source paper in the reader scrolled to and highlighting the exact passage the answer drew from (using precise char offsets), instead of just opening the paper — the "verify it yourself" moment for Q&A. Semantic (embedding) retrieval now keys vectors per sub-chunk instead of per section, so each chunk of a long section is scored on its own content (completes the 0.5.10 sub-chunking work). See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.10** — sharper retrieval: long sections are now split into overlapping, boundary-aware sub-chunks instead of one blob, and BM25 tokenizes the **full** text of each chunk rather than just the first 300 characters of a section — so content deep in a long section is finally findable by keyword search. Retrieval sources now carry char-level offsets (`char_start`/`char_end`/`chunk_index`) for precise evidence spans. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.9** — robust ingestion: a pluggable PDF parser layer replaces the single hard-wired reader. The default is now **pypdfium2** (permissive, better layout than pypdf); installing the optional **Docling** engine adds layout-aware reading order, real sections, tables/figures, and **OCR for scanned/image PDFs**. A scanned PDF that yields no text now **fails honestly** with a clear message ("No extractable text — scanned/image PDF; install `research-companion[docling]` for OCR or add metadata by hand") instead of silently entering your library empty — and retrieval no longer indexes empty-text papers. See the [Release Notes](docs/RELEASE_0.5.md).

**0.5.8** — one-click citation linking: tell the app *"this cited reference is that paper I already have"* in one move — from a not-in-library row in the **Citations panel** (a **Link…** dropdown of your library papers, ones needing metadata listed first) or from a library paper's drawer (**"This is a cited reference…"**). Linking marks the citation **In library** durably (it survives coverage recomputes and reverts only if you delete the paper) and backfills the paper's **year** from the citation so it appears on the **timeline** — with a disclaimer that the titles/years shown come from your draft's citations, not the papers themselves. New endpoint `POST /api/draft/citations/link`.

**0.5.7** — real paper metadata: each paper's **title, authors, and year** are now read from its text automatically (uploaded PDFs used to have only a filename), existing papers are backfilled once on open, and the **timeline** and **citation matching** (first-author surname + year) use them — so "Add N missing" stops nagging about papers you already have. Papers with no extractable metadata get a **"Needs metadata"** indicator, a count banner, and an **Edit metadata** form in the paper drawer to set title/authors/year by hand.

**0.5.6** — read it yourself: click any draft section, graph section, or paper to open a built-in reader with a section-navigation rail and the section highlighted; click a verified evidence quote on an alignment card and the cited paper opens with that exact quote highlighted; **View original PDF** opens the stored file, and scanned PDFs with no extracted text show a clear empty-state that points there.

**0.5.5** — clean top-of-screen: the coverage banner gets its own row everywhere (it used to overlap the graph's Draft/Explore toggle and side panel), banners are single-line, and scrollbars are thin and theme-colored.

**0.5.4** — deletion everywhere: delete a whole research from the Researches screen (confirmation with paper count, auto-switch if it's the one you're in, blocked while jobs run), a visible **Remove** button on every library card and list row, **Unset draft** from the paper drawer, and per-thread **Clear chat** in the Companion.

## What's new in 0.4

One researcher, many researches: every project now gets its own isolated **workspace** (papers, graph, draft, suggestions — fully segregated; keys and theme stay global), navigated from a premium **Researches** overview screen and a top-bar switcher. The library gains a **list view** with live status (queued / processing / ingested / failed) and each paper's relation to your draft. The knowledge graph gains a deterministic **Draft view** — your draft at the center, sections as an inner ring, papers arranged in sectors by whether they strengthen, challenge, or offer alternatives to your work. Existing stores migrate automatically and losslessly. See the [Release Notes](docs/RELEASE_0.4.md).

## What's new in 0.3

Research Companion 0.3 adds five major features to the Research Lab: a guided research journey with a home view showing your discovery timeline, a suggestions engine that recommends papers to read with revision tracking, a converse panel for floating-chat conversations about specific papers, a temporal timeline view with gap analysis to find uncovered research areas, and saved views to preserve and restore your graph snapshots. 0.3.1 adds direct PDF upload: drag your draft into the Lab and mark it as your draft in one step. See the [Release Notes](docs/RELEASE_0.3.md) for details.

## Configuration & Security

API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `HF_TOKEN` for semantic search) should be stored in a local `.env` file with permissions 0600 and never committed to version control. You can manage all keys and settings directly from the Settings page in the Research Lab. The `HF_TOKEN` is optional and enables hybrid semantic search; if unset, BM25 (lexical) fallback is used.

## Why this exists

Reading 50 papers to get up to speed on a research field takes weeks. Existing tools fall into two camps and neither does what researchers actually want:

| | Open source | Concept graph | Chat over papers | Self-hosted | Your own corpus |
|---|---|---|---|---|---|
| Connected Papers | ✗ | ✗ (citation-only) | ✗ | ✗ | ✗ |
| ResearchRabbit | ✗ | ✗ | ✗ | ✗ | partial |
| Elicit / Consensus | ✗ | ✗ | ✓ | ✗ | partial |
| Semantic Scholar | partial API | ✗ | ✗ | ✗ | ✗ |
| **Research Companion** | **✓** | **✓** | **✓** | **✓** | **✓** |

research-companion builds a *concept-level* knowledge graph (concepts, methods, datasets, claims, results, citations) from your own PDFs and arXiv links, then lets you both **navigate** it visually and **chat** with it. Every chat answer cites the exact papers it draws from, so you can verify before you cite.

## Install

```bash
git clone https://github.com/Laraib-Hasan-Future/Research-Companion.git
cd Research-Companion
pip install -e ".[server]"   # core + Research Lab server (fastapi, uvicorn)

# you also need ONE of:
export ANTHROPIC_API_KEY=sk-ant-...   # default
# or
export OPENAI_API_KEY=sk-...          # use --provider openai
```

### Better PDF ingestion (optional)

```bash
pip install research-companion[docling]   # OCR + layout-aware parsing
```

The core install parses digital PDFs with pypdfium2. Installing the optional
**Docling** engine adds **OCR** for scanned/image PDFs plus layout-aware reading
order, real sections, and table/figure capture for complex or multi-column
papers. It is auto-detected and used when present (override with
`RESEARCH_COMPANION_PARSER=pypdfium|docling`). Without it, scanned PDFs fail
with a clear message telling you to install the extra or add metadata by hand.

## Quickstart

```bash
# Add papers — arXiv, DOI, Semantic Scholar, or local PDF
research-companion add https://arxiv.org/abs/2404.16130   # GraphRAG (Edge et al., 2024)
research-companion add https://arxiv.org/abs/2410.05779   # LightRAG (Guo et al., 2024)
research-companion add https://doi.org/10.1145/1234567    # any DOI
research-companion add ./my-paper.pdf --title "My Paper" --authors "Alice,Bob" --year 2024

# Batch add from a file (one URL/path per line)
research-companion add -f examples/graph-rag-corpus/papers.txt

# Check the cost before building (~$0.05–$0.20 per paper)
research-companion cost-estimate

# Extract entities + build the cross-paper graph
research-companion build

# View the interactive graph in your browser
research-companion view

# Ask questions — every answer cites the papers it uses
research-companion chat "what are the differences between GraphRAG and LightRAG?"
research-companion chat                                    # interactive REPL

# Search the graph without opening the browser
research-companion search "attention" --kind concept

# Discover papers you're missing (via Semantic Scholar)
research-companion discover "graph-based RAG"          # topic search
research-companion discover --expand                   # follow citations of your papers
research-companion discover "knowledge graphs" --add   # auto-add discovered papers

# Export to Obsidian, markdown, CSV, or JSON
research-companion export --format obsidian --output ./my-vault/research-companion/
```

Output ends up in `~/.research-companion/`:

```
~/.research-companion/
├── papers/
│   ├── arxiv__2404_16130/{paper.pdf, metadata.json, text.txt, extraction.json}
│   ├── arxiv__2410_05779/...
│   └── arxiv__2005_11401/...
├── graph.json     # NetworkX node-link format, hackable
└── graph.html     # interactive viz, double-click to open
```

## What research-companion extracts from each paper

```json
{
  "concepts":     [{"name": "Knowledge graph", "definition": "..."}],
  "methods":      [{"name": "GraphRAG", "description": "..."}],
  "datasets":     [{"name": "HotpotQA", "description": "..."}],
  "claims":       [{"text": "Graph-based RAG outperforms vector RAG on multi-hop."}],
  "results":      [{"metric": "F1", "value": "78.9", "dataset": "HotpotQA"}],
  "related_work": ["Lewis et al. 2020", "..."]
}
```

When the same `GraphRAG` method appears in five papers, it becomes **one node** in the merged graph, with five `contains` edges back to the papers that mention it. When two concepts co-occur in 2+ papers, you get a `co_mentioned` edge weighted by how often.

## How the chat works

Given your question:

1. **Lexical seed selection** — find the top-K nodes whose label/definition contains your question terms.
2. **BFS** — expand outward from those seeds (default depth 2) to assemble a relevant subgraph.
3. **Render** — turn the subgraph into a structured text context (papers, concepts, methods, results, relationships).
4. **Answer** — send context + question to Claude/GPT with a citation-required system prompt.

Every fact in the answer cites a paper title in square brackets — `[GraphRAG paper (Edge et al., 2024)]` — that you can verify against the corresponding node in the graph view.

This is **graph-traversal RAG**, not vector RAG. No embeddings step. The graph topology is the relevance signal. For research papers — where the value is in *cross-paper* relationships, not in finding a nearest-neighbour chunk — graph traversal gives a more useful retrieval pattern.

## Supported paper sources

| Source | Example | Metadata | PDF |
|--------|---------|----------|-----|
| **arXiv** | `2410.05779` or `https://arxiv.org/abs/2410.05779` | arXiv API | always free |
| **DOI** | `10.1145/...` or `https://doi.org/10.1145/...` | Crossref API | varies (paywalled = metadata only) |
| **Semantic Scholar** | S2 URL or 40-char hex ID | S2 API | via arXiv/DOI fallback |
| **Local PDF** | `./paper.pdf` | manual `--title`/`--authors` | your file |

## Export formats

Export your knowledge graph to use in other tools:

```bash
research-companion export --format markdown   # per-paper markdown notes + index
research-companion export --format obsidian   # markdown with [[wikilinks]] — one note per entity
research-companion export --format csv        # nodes.csv + edges.csv for spreadsheets/neo4j
research-companion export --format json       # raw graph.json + papers.json
```

The **Obsidian export** creates a fully-linked vault: each paper, concept, method, and dataset gets its own note with `[[wikilinks]]` back to the papers that mention it. Open the output directory as an Obsidian vault and you get a navigable graph view for free.

## Discover missing papers

Don't have a complete reading list? research-companion can discover papers you're missing using Semantic Scholar (free, no API key needed):

```bash
# Search by topic — returns papers ranked by citation count
research-companion discover "graph-based RAG" --limit 15

# Filter by year range
research-companion discover "knowledge graphs" --year-min 2022 --year-max 2025

# Follow citations: scan references + citing papers of your existing papers
research-companion discover --expand

# Auto-add everything discovered (then run `research-companion build`)
research-companion discover "retrieval augmented generation" --add

# JSON output for scripting
research-companion discover --expand --json
```

**Topic search** queries Semantic Scholar's corpus of 200M+ papers, deduplicates against your local store, and ranks results by citation count.

**Citation expansion** (`--expand`) follows the references and citations of every paper in your store, surfaces the most-cited papers you're missing, and filters out anything you already have. This is the fastest way to go from 5 seed papers to a comprehensive literature graph.

## Agentic review

A team of specialized agents analyses a paper end-to-end, every verdict carries evidence, and the whole report opens with a single **submission-readiness verdict** — *ready / revise / not ready* — plus a prioritized "fix this first" list:

```bash
research-companion review <paper-id>                  # full review (all lanes)
research-companion review <paper-id> --venue neurips  # + venue-fit and desk-reject compliance
research-companion review <paper-id> --fast           # skip the LLM lanes (no API key needed)
research-companion review <paper-id> --report out/    # write out/report.html + out/report.json
research-companion review <paper-id> --serve          # live browser dashboard (SSE) while agents run
```

What the lanes do (each self-skips when its inputs are absent):

- **citation** — validates every reference against CrossRef/OpenAlex/arXiv/S2 (plus the opt-in PubMed/Europe PMC/DBLP connectors) and reports each as verified, suspect, or unverified.
- **priorart** — finds related work via Semantic Scholar.
- **novelty** — extracts the paper's claimed contributions, compares each against prior art, and verifies every evidence quote against the paper's own text.
- **statistical soundness** — recomputes reported p-values (Statcheck) and checks reported means for arithmetic plausibility (GRIM). Deterministic, no LLM.
- **reproducibility** — scans for public code/data links, availability statements, and reporting-checklist mentions → high / medium / low.
- **ethics** — checks for the integrity declarations venues require (funding, conflicts, ethics/IRB approval, consent, author contributions).
- **overlap** — flags passages that near-duplicate another paper in your library (local shingling; opt-in embedding-based paraphrase pass).
- **venue-fit** (`--venue`) — matches your contributions against a venue's scope → strong / moderate / weak / out-of-scope + desk-reject risk.
- **compliance** (`--venue`) — a deterministic desk-reject linter: page/length limit, required sections, anonymization leaks, citation completeness.
- **severity, confidence, benchmark, citation-polarity, taxonomy** — findings ranked worst-first, per-claim confidence bands, suggested benchmarks, typed citation edges, and a labeled prior-art taxonomy.

At the top of every report, the **submission-readiness synthesis** aggregates whatever lanes ran into one honest verdict + a cross-lane action list (blockers are deterministic desk-reject risks; everything else is a warning), with explicit caveats for lanes that didn't run. Enable the optional `readiness_narrative` setting to add an LLM-written "reviewer's take" and fix plan on top — grounded strictly in that verdict, never inventing findings.

Every run writes a JSONL audit log to `~/.research-companion/runs/`. Two additional library-level agents (not yet CLI-wired): problem (refines a research problem against the graph) and tracker (one-shot new-related-work sweep).

## Try it in 30 seconds (no API key)

```bash
# Review pipeline demo (6 agent lanes + rebuttal, entirely offline):
python examples/demo_offline.py

# Research Lab demo (fixture event replay — papers, sections, graph, strength):
python examples/demo_lab_offline.py
```

Both demos seed synthetic data, run their respective pipelines, and print a narrative summary — no API keys or network required.

## Answer reviewers (rebuttal assistant)

```bash
research-companion rebuttal <paper-id> --reviews reviews.txt            # grounded point-by-point replies
research-companion rebuttal <paper-id> --reviews reviews.txt \
    --emit-segments seg.json                                    # split reviews, edit, then:
research-companion rebuttal <paper-id> --segments seg.json --tone firm  # resume from edited segments
```

Replies quote only real passages from your paper; any span the model cannot ground is flagged
`CHECK` instead of shipped. Duplicate concerns raised by multiple reviewers are grouped, and a
planned-revisions changelog is assembled automatically.

## Example corpus

`examples/graph-rag-corpus/papers.txt` is a curated list of 10 papers on graph-based RAG. Run it as a one-liner:

```bash
research-companion add -f examples/graph-rag-corpus/papers.txt
research-companion build
research-companion chat "how do GraphRAG and LightRAG differ in indexing cost?"
```

## CLI reference

```
research-companion add <url-or-pdf>... [-f FILE] [--title T] [--authors A,B] [--year Y]
research-companion build [--provider anthropic|openai] [--model M] [--force]
research-companion cost-estimate [--provider anthropic|openai] [--model M]
research-companion discover <topic> [-n LIMIT] [--year-min Y] [--year-max Y] [--add] [--json]
research-companion discover --expand [-n LIMIT] [--min-citations N] [--add] [--json]
research-companion view [--no-open]
research-companion chat [<question>] [--provider P] [--depth N]
research-companion search <query> [-k concept|method|...] [-n LIMIT] [--json]
research-companion list [--json]
research-companion remove <paper-id>
research-companion stats
research-companion export [--format markdown|csv|json|obsidian] [--output DIR]

# Research Lab (new in 0.2 — requires [server] extra)
research-companion lab serve [--port N] [--no-open]
research-companion lab ingest <folder>
research-companion lab failures
research-companion set-draft <paper-id>
research-companion align <paper-id> [--against <draft-id>] [--force]
research-companion ask "<question>" [--section <section-id>]
research-companion compare <paper-a> <paper-b>
research-companion gaps [--refresh] [--json]
research-companion timeline [--json]

# Multiple researches (workspaces)
research-companion workspace list                    # * marks the active workspace
research-companion workspace create <name>
research-companion workspace use <name>

# Review & integrity checks
research-companion review <paper-id> [--venue SLUG] [--fast] [--report DIR] [--serve] [--json]
research-companion refcheck <paper-id> [--connectors europepmc,pubmed,dblp] [--json]
research-companion check-compliance <paper-id> --venue SLUG [--json]   # desk-reject linter
research-companion check-stats <paper-id> [--json]                     # Statcheck + GRIM
research-companion check-overlap <paper-id> [--semantic] [--allow-remote] [--json]
research-companion rebuttal <paper-id> --reviews FILE [--tone deferential|balanced|firm]
research-companion mcp serve                                           # MCP trust-layer server

# Interoperability
research-companion export-bib [--format bibtex|ris] [--output FILE]
research-companion import-bib <file.bib>
research-companion cite-tex <paper.tex>
```

## Programmatic API

```python
from research_companion import add_paper, build_graph, chat, view

add_paper("https://arxiv.org/abs/2410.05779")
add_paper("10.1145/1234567.1234568")       # DOI
G = build_graph()                          # NetworkX Graph
view()                                     # opens HTML
ans = chat("what is GraphRAG?")
print(ans.answer)                          # cited answer
print(ans.papers)                          # papers used in retrieval
```

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `PAPERGRAPH_DIR` | Where research-companion stores papers + graph | `~/.research-companion/` |
| `ANTHROPIC_API_KEY` | Required for `--provider anthropic` (default) | – |
| `OPENAI_API_KEY` | Required for `--provider openai` | – |

Cost guidance per paper (Claude Sonnet): ~$0.02–$0.10 per extraction depending on length. Run `research-companion cost-estimate` to see projected costs before building. Re-running `build` is **free** — extractions are cached on disk and only re-run when the prompt changes.

## Roadmap

- **v0.1** — CLI, arXiv + DOI + Semantic Scholar + local PDFs, graph viz, chat with citations, search, export (markdown/obsidian/csv/json), cost estimation.
- **v0.2** — Research Lab UI (live graph, SSE, section-wise subgraphs, draft alignment, evidence-strength colours, Ask, Compare, folder ingest).
- **v0.3** — True-companion release: guided home/journey with next-best-action, suggestions engine with revision tracking, talk-to-the-analysis converse panel, temporal timeline + gap analysis, hybrid semantic search (HF Inference API with exact BM25 fallback), saved subgraphs, in-UI settings/keys, themes, PyPI packaging; 0.3.1 added direct PDF upload with a draft-first flow.
- **v0.4** — Organized research: isolated workspaces per research with lossless migration, Researches overview + switcher, library list view with live status and draft relations, deterministic draft-centric graph mode.
- **v0.5** — Citation coverage (your draft's bibliography as ground truth), robust pluggable ingestion with Docling OCR isolated in a subprocess, sub-chunk retrieval with char-span provenance, verifiable answers (jump to the exact source span), KG entity provenance, folder ingest with per-file selection, and a reliability/UX pass (0.5.17).
- **v0.6** — Reviewer-grade integrity checks: venue-fit checker with a cross-discipline venue knowledge base, severity-ranked findings, a reproducibility/data-availability checker, and an integrity-declaration detector; plus a statistical-soundness checker (Statcheck + GRIM, 0.6.1) and interoperability (BibTeX/RIS export, `.bib` import, LaTeX `\cite` resolution, 0.6.2).
- **v0.7 (current) — the integrity & trust layer** — MCP trust-layer server (`mcp serve`) with four deterministic, key-free verification tools, plus two opt-in costed tools (`ask_library` / `review_draft`) gated behind a setting, a configured key, and a per-call cost cap; near-duplicate detection plus an opt-in embedding/paraphrase pass (`check-overlap`); statistical-soundness checks (Statcheck + GRIM, `check-stats`); a desk-reject compliance linter (`check-compliance`); a **submission-readiness verdict** with an optional LLM "reviewer's take" at the top of every review; interoperability (BibTeX/RIS, `.bib` import, LaTeX `\cite`); and opt-in **PubMed / Europe PMC / DBLP** domain connectors for biomedical and CS references.
- **Future** — true web-corpus plagiarism detection and additional entity-metadata sources. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Contributing

PRs welcome — anyone can raise one. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for
setup, design principles, and the PR checklist, and
**[SECURITY.md](SECURITY.md)** for reporting vulnerabilities privately. The
codebase is intentionally small (MIT-licensed, no heavy frameworks). Every PR must
pass the three gates that CI runs on Python 3.10–3.13 across Ubuntu and Windows:

```bash
pip install -e ".[dev]"
python -m pytest -q
node --test tests/js/*.test.mjs
ruff check research_companion tests examples
```

## Acknowledgements

research-companion's design is inspired by [GraphRAG](https://github.com/microsoft/graphrag) (Microsoft Research) for the cross-document community-summary concept.

## License

MIT © 2026 Laraib Hasan
