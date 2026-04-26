# papergraph

> Drop arXiv URLs or PDFs in. Get a knowledge graph and a chat interface that answers questions with paper citations. Local-first. Open source.

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
# Add 3 papers on graph-based RAG
papergraph add https://arxiv.org/abs/2404.16130   # GraphRAG (Edge et al., 2024)
papergraph add https://arxiv.org/abs/2410.05779   # LightRAG (Guo et al., 2024)
papergraph add https://arxiv.org/abs/2005.11401   # RAG (Lewis et al., 2020)

# Or add a local PDF
papergraph add ./my-paper.pdf --title "My Paper" --authors "Alice,Bob" --year 2024

# Extract entities + build the cross-paper graph (~$0.05–$0.20 in API calls)
papergraph build

# View the interactive graph in your browser
papergraph view

# Ask questions
papergraph chat "what are the differences between GraphRAG and LightRAG?"
papergraph chat                                    # interactive REPL
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

## Example corpus

`examples/graph-rag-corpus/papers.txt` is a curated list of 10 papers on graph-based RAG. Run it as a one-liner:

```bash
xargs -n1 papergraph add < examples/graph-rag-corpus/papers.txt
papergraph build
papergraph chat "how do GraphRAG and LightRAG differ in indexing cost?"
```

## CLI reference

```
papergraph add <url-or-pdf> [--title T] [--authors A,B] [--year Y]
papergraph build [--provider anthropic|openai] [--model M] [--force]
papergraph view [--no-open]
papergraph chat [<question>] [--provider P] [--depth N]
papergraph list [--json]
papergraph remove <paper-id>
papergraph stats
```

## Programmatic API

```python
import papergraph

papergraph.add_paper("https://arxiv.org/abs/2410.05779")
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

Cost guidance per paper (Claude Sonnet 4.7): ~$0.02–$0.10 per extraction depending on length. Re-running `build` is **free** — extractions are cached on disk and only re-run when the prompt changes.

## Roadmap

- **v0.1 (current)** — CLI, arXiv + local PDFs, graph viz, chat with citations.
- **v0.2** — Semantic Scholar integration for proper citation graph; concept-level cross-paper deduplication via embedding similarity (optional); MCP server so Claude desktop can query papergraph directly; graph export to Obsidian Canvas.
- **v0.3** — Web UI (Streamlit), multi-corpus support (one user, many topic graphs), live arXiv watch (`papergraph watch cs.CL --since today`).
- **v0.4** — Hosted cloud version for non-technical users.

## Contributing

PRs welcome. Issues even more welcome. The codebase is intentionally small (~2k LoC, MIT-licensed, no heavy frameworks). Run tests:

```bash
pip install -e .[dev]
pytest
```

## Acknowledgements

papergraph's design is inspired by [graphify](https://github.com/safishamsi/graphify) (Safi Shamsi) for the topology-based clustering approach and the EXTRACTED/INFERRED tagging idea, and by [GraphRAG](https://github.com/microsoft/graphrag) (Microsoft Research) for the cross-document community-summary concept.

## License

MIT © 2026 Azizur
