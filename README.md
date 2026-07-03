# papergraph

> Drop arXiv URLs, DOIs, or PDFs in. Get a knowledge graph and a chat interface that answers questions with paper citations. Local-first. Open source.

```bash
pip install papergraph
papergraph add https://arxiv.org/abs/2410.05779
papergraph add https://arxiv.org/abs/2404.16130
papergraph build
papergraph view                                  # opens an interactive HTML graph
papergraph chat "what are the main approaches?"  # KG-aware Q&A with citations
```

---

## Why this exists

Reading 50 papers to get up to speed on a research field takes weeks. Existing tools fall into two camps and neither does what researchers actually want:

| | Open source | Concept graph | Chat over papers | Self-hosted | Your own corpus |
|---|---|---|---|---|---|
| Connected Papers | ✗ | ✗ (citation-only) | ✗ | ✗ | ✗ |
| ResearchRabbit | ✗ | ✗ | ✗ | ✗ | partial |
| Elicit / Consensus | ✗ | ✗ | ✓ | ✗ | partial |
| Semantic Scholar | partial API | ✗ | ✗ | ✗ | ✗ |
| **papergraph** | **✓** | **✓** | **✓** | **✓** | **✓** |

papergraph builds a *concept-level* knowledge graph (concepts, methods, datasets, claims, results, citations) from your own PDFs and arXiv links, then lets you both **navigate** it visually and **chat** with it. Every chat answer cites the exact papers it draws from, so you can verify before you cite.

## Install

```bash
pip install papergraph

# you also need ONE of:
export ANTHROPIC_API_KEY=sk-ant-...   # default
# or
export OPENAI_API_KEY=sk-...          # use --provider openai
```

## Quickstart

```bash
# Add papers — arXiv, DOI, Semantic Scholar, or local PDF
papergraph add https://arxiv.org/abs/2404.16130   # GraphRAG (Edge et al., 2024)
papergraph add https://arxiv.org/abs/2410.05779   # LightRAG (Guo et al., 2024)
papergraph add https://doi.org/10.1145/1234567    # any DOI
papergraph add ./my-paper.pdf --title "My Paper" --authors "Alice,Bob" --year 2024

# Batch add from a file (one URL/path per line)
papergraph add -f examples/graph-rag-corpus/papers.txt

# Check the cost before building (~$0.05–$0.20 per paper)
papergraph cost-estimate

# Extract entities + build the cross-paper graph
papergraph build

# View the interactive graph in your browser
papergraph view

# Ask questions — every answer cites the papers it uses
papergraph chat "what are the differences between GraphRAG and LightRAG?"
papergraph chat                                    # interactive REPL

# Search the graph without opening the browser
papergraph search "attention" --kind concept

# Discover papers you're missing (via Semantic Scholar)
papergraph discover "graph-based RAG"          # topic search
papergraph discover --expand                   # follow citations of your papers
papergraph discover "knowledge graphs" --add   # auto-add discovered papers

# Export to Obsidian, markdown, CSV, or JSON
papergraph export --format obsidian --output ./my-vault/papergraph/
```

Output ends up in `~/.papergraph/`:

```
~/.papergraph/
├── papers/
│   ├── arxiv__2404_16130/{paper.pdf, metadata.json, text.txt, extraction.json}
│   ├── arxiv__2410_05779/...
│   └── arxiv__2005_11401/...
├── graph.json     # NetworkX node-link format, hackable
└── graph.html     # interactive viz, double-click to open
```

## What papergraph extracts from each paper

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
papergraph export --format markdown   # per-paper markdown notes + index
papergraph export --format obsidian   # markdown with [[wikilinks]] — one note per entity
papergraph export --format csv        # nodes.csv + edges.csv for spreadsheets/neo4j
papergraph export --format json       # raw graph.json + papers.json
```

The **Obsidian export** creates a fully-linked vault: each paper, concept, method, and dataset gets its own note with `[[wikilinks]]` back to the papers that mention it. Open the output directory as an Obsidian vault and you get a navigable graph view for free.

## Discover missing papers

Don't have a complete reading list? papergraph can discover papers you're missing using Semantic Scholar (free, no API key needed):

```bash
# Search by topic — returns papers ranked by citation count
papergraph discover "graph-based RAG" --limit 15

# Filter by year range
papergraph discover "knowledge graphs" --year-min 2022 --year-max 2025

# Follow citations: scan references + citing papers of your existing papers
papergraph discover --expand

# Auto-add everything discovered (then run `papergraph build`)
papergraph discover "retrieval augmented generation" --add

# JSON output for scripting
papergraph discover --expand --json
```

**Topic search** queries Semantic Scholar's corpus of 200M+ papers, deduplicates against your local store, and ranks results by citation count.

**Citation expansion** (`--expand`) follows the references and citations of every paper in your store, surfaces the most-cited papers you're missing, and filters out anything you already have. This is the fastest way to go from 5 seed papers to a comprehensive literature graph.

## Agentic review (new)

A team of specialized agents analyzes a paper end-to-end, and every verdict carries evidence:

```bash
papergraph review <paper-id>                 # 6 agents: ingest, citation, priorart,
                                             # novelty, confidence, benchmark
papergraph review <paper-id> --fast          # skip the LLM lanes (no API key needed)
papergraph review <paper-id> --report out/   # write out/report.html + out/report.json
papergraph review <paper-id> --serve         # live browser dashboard (SSE) while agents run
```

What each lane does:

- **citation** - validates every reference against CrossRef/OpenAlex; flags fabricated,
  wrong-DOI, and author-mismatch citations.
- **priorart** - maps related work via Semantic Scholar.
- **novelty** - extracts the paper's claimed contributions, compares each against prior art,
  and verifies every evidence quote against the paper's own text.
- **confidence** - deterministic score with an uncertainty band per claim (no LLM).
- **benchmark** - suggests evaluation benchmarks mined from the knowledge graph + related work.

Every run writes a JSONL audit log to `~/.papergraph/runs/`.

## Answer reviewers (rebuttal assistant)

```bash
papergraph rebuttal <paper-id> --reviews reviews.txt            # grounded point-by-point replies
papergraph rebuttal <paper-id> --reviews reviews.txt \
    --emit-segments seg.json                                    # split reviews, edit, then:
papergraph rebuttal <paper-id> --segments seg.json --tone firm  # resume from edited segments
```

Replies quote only real passages from your paper; any span the model cannot ground is flagged
`CHECK` instead of shipped. Duplicate concerns raised by multiple reviewers are grouped, and a
planned-revisions changelog is assembled automatically.

## Example corpus

`examples/graph-rag-corpus/papers.txt` is a curated list of 10 papers on graph-based RAG. Run it as a one-liner:

```bash
papergraph add -f examples/graph-rag-corpus/papers.txt
papergraph build
papergraph chat "how do GraphRAG and LightRAG differ in indexing cost?"
```

## CLI reference

```
papergraph add <url-or-pdf>... [-f FILE] [--title T] [--authors A,B] [--year Y]
papergraph build [--provider anthropic|openai] [--model M] [--force]
papergraph cost-estimate [--provider anthropic|openai] [--model M]
papergraph discover <topic> [-n LIMIT] [--year-min Y] [--year-max Y] [--add] [--json]
papergraph discover --expand [-n LIMIT] [--min-citations N] [--add] [--json]
papergraph view [--no-open]
papergraph chat [<question>] [--provider P] [--depth N]
papergraph search <query> [-k concept|method|...] [-n LIMIT] [--json]
papergraph list [--json]
papergraph remove <paper-id>
papergraph stats
papergraph export [--format markdown|csv|json|obsidian] [--output DIR]
```

## Programmatic API

```python
import papergraph

papergraph.add_paper("https://arxiv.org/abs/2410.05779")
papergraph.add_paper("10.1145/1234567.1234568")  # DOI
G = papergraph.build_graph()              # NetworkX Graph
papergraph.view()                          # opens HTML
ans = papergraph.chat("what is GraphRAG?")
print(ans.answer)                          # cited answer
print(ans.papers)                          # papers used in retrieval
```

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `PAPERGRAPH_DIR` | Where papergraph stores papers + graph | `~/.papergraph/` |
| `ANTHROPIC_API_KEY` | Required for `--provider anthropic` (default) | – |
| `OPENAI_API_KEY` | Required for `--provider openai` | – |

Cost guidance per paper (Claude Sonnet): ~$0.02–$0.10 per extraction depending on length. Run `papergraph cost-estimate` to see projected costs before building. Re-running `build` is **free** — extractions are cached on disk and only re-run when the prompt changes.

## Roadmap

- **v0.1 (current)** — CLI, arXiv + DOI + Semantic Scholar + local PDFs, graph viz, chat with citations, search, export (markdown/obsidian/csv/json), cost estimation.
- **v0.2** — Semantic Scholar integration for proper citation graph; concept-level cross-paper deduplication via embedding similarity (optional); MCP server so Claude desktop can query papergraph directly; graph export to Obsidian Canvas.
- **v0.3** — Web UI (Streamlit), multi-corpus support (one user, many topic graphs), live arXiv watch (`papergraph watch cs.CL --since today`).
- **v0.4** — Hosted cloud version for non-technical users.

## Contributing

PRs welcome. Issues even more welcome. The codebase is intentionally small (~2.5k LoC, MIT-licensed, no heavy frameworks). Run tests:

```bash
pip install -e .[dev]
pytest
```

## Acknowledgements

papergraph's design is inspired by [graphify](https://github.com/safishamsi/graphify) (Safi Shamsi) for the topology-based clustering approach and the EXTRACTED/INFERRED tagging idea, and by [GraphRAG](https://github.com/microsoft/graphrag) (Microsoft Research) for the cross-document community-summary concept.

## License

MIT © 2026 Azizur
