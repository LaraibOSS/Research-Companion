# Example corpus: graph-based RAG papers

A curated list of 10 papers on graph-based RAG. Run research-companion against this corpus to see what a fully-built graph looks like.

## Use it

```bash
# Bash / zsh
grep -v '^#' papers.txt | xargs -n1 research-companion add

# PowerShell
Get-Content papers.txt | Where-Object { $_ -notmatch '^#' -and $_ } | ForEach-Object { research-companion add $_ }

# Then
research-companion build
research-companion view
```

## Try these questions

```bash
research-companion chat "how do GraphRAG and LightRAG differ in indexing cost?"
research-companion chat "what datasets are used to evaluate multi-hop RAG?"
research-companion chat "which methods rely on community detection?"
research-companion chat "what claims does HippoRAG make that other papers don't?"
```

## Expected stats (rough, from a single build run)

```
papers       10
concepts     ~40
methods      ~25
datasets     ~10
claims       ~30
results      ~50
edges        ~250
co_mentioned ~30
cites        ~5–15 (depends on extraction quality)
```

Cost: ~$1.50 with Claude Sonnet 4.7, or ~$0.30 with `gpt-4o-mini`.

Re-runs are free — extractions are cached.
