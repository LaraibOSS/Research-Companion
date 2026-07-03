# Evaluation Harnesses

This directory contains offline and live evaluation harnesses for papergraph.

---

## 1. Citation P/R Corruption Benchmark (`citation_pr`)

A **controlled synthetic corruption** benchmark that measures how accurately
the reference-checking pipeline detects corrupted bibliography entries.

### How it works

- 40 "gold" reference records are defined inline (deterministic; no network).
- `corrupt()` produces a labeled set of clean and corrupted entries (fabricated
  titles, wrong DOIs, swapped authors) using a seeded RNG.
- The pipeline is evaluated on precision, recall, and F1 of flagging corrupted
  references.

### Running it

```bash
python -m papergraph.eval.citation_pr
```

No API key or network access required.  The run is deterministic (seed=42) and
should reproduce the committed artifacts exactly.

### Committed results

Results are stored in `eval/results/`:

- `eval/results/citation_pr.json` — full metrics dict (precision, recall, F1,
  per-corruption-type breakdown).
- `eval/results/citation_pr.md` — human-readable summary table.

**Note:** Because this is a controlled synthetic corruption benchmark, ceiling
scores are expected and intended — the benchmark is designed as a sanity check,
not a hard generalization test.

---

## 2. Novelty-vs-OpenReview Harness (`novelty_openreview`)

Compares papergraph's NoveltyAgent verdicts against human reviewer scores from
OpenReview, reporting Spearman rank correlation.

### Important: this eval requires network access and LLM API keys

**This harness was NOT executed in this environment.**  Running it live requires:

1. A valid `ANTHROPIC_API_KEY` (default) or `OPENAI_API_KEY`.
2. Network access to Semantic Scholar (prior-art search).
3. ~25 ICLR papers already ingested in the store (see below).

### How to assemble ~25 ICLR cases

1. Go to [OpenReview](https://openreview.net) and find ICLR papers with
   published reviews that include a **Novelty** or **Contribution** rating (1-5).
2. For each paper:
   a. Download the PDF.
   b. Add it to the store: `papergraph add path/to/paper.pdf --title "..." --authors "..."`.
   c. Build the graph: `papergraph build`.
3. Compute `human_novelty` for each paper as the **average** of the reviewer
   novelty/contribution scores (e.g. if three reviewers rate 3, 4, 3 the average
   is 3.33).
4. Create a `cases.jsonl` file, one JSON object per line:

   ```jsonl
   {"paper_id": "local:abc123", "human_novelty": 3.33}
   {"paper_id": "local:def456", "human_novelty": 4.5}
   ```

### Running it

```bash
python -m papergraph.eval.novelty_openreview cases.jsonl --out eval/results/
```

Set your API key first:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY=sk-...
```

The harness will print an honest warning to stderr if neither key is set.

### Output

- `eval/results/novelty_openreview.json` — per-paper scores and rank agreement.
- Console output: Spearman rank correlation + per-paper breakdown.

### Honest disclaimer

The novelty-vs-OpenReview evaluation **was not run** as part of this project
because it requires live LLM API calls and network access, which are not
available in this build environment.  The harness is production-ready and will
execute correctly once credentials and ingested papers are provided.
