# Research Companion

> Drop arXiv URLs, DOIs, or PDFs in. Get a knowledge graph and a chat interface that answers questions with paper citations. Local-first. Open source.

```bash
git clone https://github.com/Laraib-Hasan-Future/Research-Companion.git && cd research-companion && pip install -e .
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
cd research-companion
pip install -e ".[server]"   # core + Research Lab server (fastapi, uvicorn)

# you also need ONE of:
export ANTHROPIC_API_KEY=sk-ant-...   # default
# or
export OPENAI_API_KEY=sk-...          # use --provider openai
```

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

## Agentic review (new)

A team of specialized agents analyzes a paper end-to-end, and every verdict carries evidence:

```bash
research-companion review <paper-id>                 # 6 agents: ingest, citation, priorart,
                                             # novelty, confidence, benchmark
research-companion review <paper-id> --fast          # skip the LLM lanes (no API key needed)
research-companion review <paper-id> --report out/   # write out/report.html + out/report.json
research-companion review <paper-id> --serve         # live browser dashboard (SSE) while agents run
```

What each lane does:

- **citation** - validates every reference against CrossRef/OpenAlex; flags fabricated,
  wrong-DOI, and author-mismatch citations.
- **priorart** - maps related work via Semantic Scholar.
- **novelty** - extracts the paper's claimed contributions, compares each against prior art,
  and verifies every evidence quote against the paper's own text.
- **confidence** - deterministic score with an uncertainty band per claim (no LLM).
- **benchmark** - suggests evaluation benchmarks mined from the knowledge graph + related work.

Every run writes a JSONL audit log to `~/.research-companion/runs/`.

Two additional library-level agents (not yet CLI-wired): problem (refines a research problem against the graph) and tracker (one-shot new-related-work sweep).

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
research-companion lab failures [--retry <paper-id>]
research-companion set-draft <paper-id>
research-companion align <paper-id> [--against <draft-id>] [--force]
research-companion ask "<question>" [--section <section-id>]
research-companion compare <paper-a> <paper-b>
```

## Programmatic API

```python
import research-companion

research-companion.add_paper("https://arxiv.org/abs/2410.05779")
research-companion.add_paper("10.1145/1234567.1234568")  # DOI
G = research-companion.build_graph()              # NetworkX Graph
research-companion.view()                          # opens HTML
ans = research-companion.chat("what is GraphRAG?")
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
- **v0.4 (current)** — Organized research: isolated workspaces per research with lossless migration, Researches overview + switcher, library list view with live status and draft relations, deterministic draft-centric graph mode.
- **v0.5** — MCP server so Claude desktop can query research-companion directly; live arXiv watch (`research-companion watch cs.CL --since today`); hosted cloud version for non-technical users.

## Contributing

PRs welcome. Issues even more welcome. The codebase is intentionally small (MIT-licensed, no heavy frameworks). Run tests:

```bash
pip install -e ".[dev]"
python -m pytest -q   # 1,250+ Python tests
node --test tests/js/reducer.test.mjs tests/js/sse.test.mjs tests/js/format.test.mjs \
  tests/js/mapping.test.mjs tests/js/snapshotRefresher.test.mjs \
  tests/js/graphview.test.mjs tests/js/graph_pipeline.test.mjs \
  tests/js/draftdock.test.mjs tests/js/ingesthelpers.test.mjs \
  tests/js/askcompare.test.mjs tests/js/converse.test.mjs \
  tests/js/glossary.test.mjs tests/js/home.test.mjs \
  tests/js/settingsHelpers.test.mjs tests/js/suggestionHelpers.test.mjs \
  tests/js/theme.test.mjs tests/js/timelineLayout.test.mjs \
  tests/js/viewsHelpers.test.mjs   # 322 JS tests
```

## Acknowledgements

research-companion's design is inspired by [graphify](https://github.com/safishamsi/graphify) (Safi Shamsi) for the topology-based clustering approach and the EXTRACTED/INFERRED tagging idea, and by [GraphRAG](https://github.com/microsoft/graphrag) (Microsoft Research) for the cross-document community-summary concept.

## License

MIT © 2026 Azizur
