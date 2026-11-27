# Evaluation Harnesses

This directory contains offline and live evaluation harnesses for research-companion.

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
python -m research_companion.eval.citation_pr
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
not a hard generalization test.  Precision is 1.0 by construction under the oracle lookup (clean refs self-match the same GOLD list); only recall is diagnostic.

---

## 2. Novelty-vs-OpenReview Harness (`novelty_openreview`)

Compares research-companion's NoveltyAgent verdicts against human reviewer scores from
OpenReview, reporting Spearman rank correlation.

### Important: this eval requires network access and LLM API keys

Running it live requires:

1. A valid `ANTHROPIC_API_KEY` (default) or `OPENAI_API_KEY`.
2. Network access to Semantic Scholar (prior-art search).
3. ~25 ICLR papers already ingested in the store (see below).

### How to assemble ~25 ICLR cases

1. Go to [OpenReview](https://openreview.net) and find ICLR papers with
   published reviews that include a **Novelty** or **Contribution** rating (1-5).
2. For each paper:
   a. Download the PDF.
   b. Add it to the store: `research-companion add path/to/paper.pdf --title "..." --authors "..."`.
   c. Build the graph: `research-companion build`.
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
python -m research_companion.eval.novelty_openreview cases.jsonl --out eval/results/
```

Set your API key first:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY=sk-...
```

The harness will print an honest warning to stderr if neither key is set.

### Output

- `eval/results/novelty_openreview.json` — per-paper scores and rank agreement.
- Console output: Spearman rank correlation + per-paper breakdown.

### Committed result: a small pilot, not significant

It has been run once, live, as a pilot: `eval/results/novelty_openreview.md`
and `.json` (2026-07-03, 10 ICLR 2025 papers, all agent runs succeeded).
Spearman rank agreement with the averaged reviewer scores was rho = 0.283,
with a seeded two-sided permutation p = 0.416 (10,000 permutations) -- **not
significant**. System scores compress toward "novel" (4.4-5.0) while reviewer
scores spread from 2.3 to 5.0. Ten papers cannot support a claim either way;
read it as a pilot null, not as evidence the screen works or fails.

---

## 3. Reference-checker benchmark (`refcheck_bench`)

Measures how often `refcheck` catches a fabricated reference and how often it
accuses a real one, on any labelled file. Every entry goes through the real
validation path -- parse, catalogue lookup, validate -- exactly as a
bibliography line does in `research-companion refcheck`. Only the catalogue
behind the lookup is swappable.

It is a module entry point, like the other harnesses here, rather than a
product command: it is a measurement tool for people working on the checker.

### File formats

**Native JSONL**, one object per line:

```jsonl
{"entry": "Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Deep residual learning for image recognition. In CVPR, 2016.", "label": "real"}
{"entry": "@article{k, title={Some Invented Title}, author={Doe, Jane}, year={2020}}", "label": "fabricated", "type": "invented_title"}
```

- `entry` -- a bibliography line (parsed by `parse_reference_string`, as the
  checker parses a paper's bibliography) or a BibTeX entry (its authors are
  kept structured, as the MCP tool passes them, so the author-overlap check
  runs).
- `label` -- `real` or `fabricated`.
- `type` -- optional category for the per-type breakdown.

**HALLMARK** ([rpatrik96/hallmark](https://github.com/rpatrik96/hallmark),
MIT; 2,526 labelled BibTeX entries, 14 hallucination types), via `--format
hallmark` or auto-detection. **The adapter is unverified against the real
file**: its field mapping was designed from the dataset's published
description, and the dataset has not been downloaded here. It accepts the
entry as `bibtex` / `bibtex_entry` / `raw_bibtex` / `entry` (a BibTeX string)
or `fields` (a dict of BibTeX fields); the label as `label` (`VALID` /
`HALLUCINATED`, case-insensitive) or a boolean `is_hallucinated`; the type as
`hallucination_type` / `type` / `category`. A file that matches neither format
fails with a message naming these fields -- if the real file differs, fix the
adapter (`_entry_from_hallmark`) rather than the data, and say so when
reporting.

Rows that cannot be read are reported with their line numbers and excluded;
they are never silently dropped.

### Running it

Offline, against the shipped smoke set and its catalogue fixture:

```bash
python -m research_companion.eval.refcheck_bench eval/cases/refcheck_smoke.jsonl \
    --catalogue eval/cases/refcheck_smoke_catalogue.json
```

Live, against arXiv -> CrossRef -> OpenAlex (network, no API key, no model):

```bash
python -m research_companion.eval.refcheck_bench hallmark.jsonl --format hallmark \
    --cache eval/results/hallmark_catalogue_cache.jsonl --delay 1.0 --limit 200
```

- Requests are sequential, with `--delay` seconds (default 1.0) between
  network calls. At three catalogues per entry, the full 2,526-entry file is
  a few hours; start with `--limit`.
- `--cache FILE` records every catalogue **response** (not verdicts) as one
  JSONL line. Re-running with the same file replays what was recorded and asks
  only for the rest, so an interrupted run resumes; a truncated last line is
  ignored. Because verdicts are always recomputed, the same cache re-measures
  the matcher after a change. An outage is never recorded. Use one cache file
  per catalogue source -- do not mix a fixture run's cache with a live one.
- `--json` prints the full result, including every row's verdict and reasons.

### What it reports

- **Confusion matrix**: label (real / fabricated) against verdict (verified /
  suspect / unverified / not checked).
- **Detection rate**: fabricated entries judged `suspect` or `unverified`,
  over fabricated entries a catalogue answered for.
- **False-accusation rate**: real entries judged `suspect` or `unverified`,
  over real entries a catalogue answered for. This is the number that matters
  most: at a low base rate of fabrication, a checker that cries wolf gets
  ignored.
- **Not checked**: entries for which no catalogue could be reached. Counted
  separately and excluded from both rates.
- **Per type**: the same rates for each `type`, each with its denominator.

### The smoke set

`eval/cases/refcheck_smoke.jsonl` has 30 entries: 15 real references to
well-known papers in several citation styles (two as BibTeX), and 15
fabricated ones across eight types (invented title, wrong authors as a line and
as BibTeX, a short real title as the prefix of an invented longer one -- with
and without the real authors -- wrong year, invented venue, wrong arXiv id).
`refcheck_smoke_catalogue.json` is a hand-written catalogue of the real
papers, not a recording of a live API: it is served through the real
`arxiv_lookup` / `crossref_lookup`, with a search that returns the five best
word-overlap candidates for any query, as a catalogue search does.

Current results, pinned in `tests/test_eval_refcheck_bench.py`:

| | |
|---|---|
| Detection rate | 60.0% (9 of 15 checked) |
| False-accusation rate | 6.7% (1 of 15 checked) |
| Not checked | 0 |

The containment fix holds (all three short-title-prefix fabrications with
invented authors are caught). The misses are properties of the checker:
wrong authors on a freeform line verify (the line parser extracts no authors;
the same error in BibTeX is caught); wrong year and invented venue verify
(neither is compared); a fabrication that reuses the real authors defeats the
containment rule. The one false accusation is the real "Deep learning"
(LeCun, Bengio and Hinton, Nature 2015), rejected by the 15-character
shared-run floor that exists to block short generic phrases.

This is 30 hand-picked entries against a hand-written catalogue. It shows
which kinds of fabrication the checker can and cannot see; it is not an
estimate of field accuracy. That needs a live run on a set like HALLMARK.

---

## 4. Claim-audit benchmark (`claim_audit_bench`)

Measures the claim audit -- does a cited passage support a claim -- on a
labelled file. Each case goes through the real `audit_claim` (prompt,
response parsing, minimum-passage rule, fail-closed paths) with the passage as
the anchored source text. One model call per case.

```jsonl
{"claim": "Graph retrieval reduces error by 12 points.", "passage": "...", "label": "supported"}
{"claim": "Graph retrieval cuts hallucination by 40%.", "passage": "...", "label": "not_supported", "type": "contradict"}
```

```bash
python -m research_companion.eval.claim_audit_bench claims.jsonl --limit 50 [--provider P --model M] [--json]
```

It reports the **detection rate** (`not_supported` cases judged NOT_SUPPORTED)
and the **false-accusation rate** (`supported` cases judged NOT_SUPPORTED),
each over cases with a conclusive verdict. **Inconclusive** audits -- a model
error, an "unclear" answer, a passage under 40 characters, no model configured
-- are counted separately and excluded from both rates.

**SciFact** (Wadden et al., 2020) converts to this format: one case per claim
and cited abstract, the passage being the rationale sentences (or the
abstract), `SUPPORT` -> `supported`, `CONTRADICT` -> `not_supported` (type
`contradict`), `NOINFO` -> `not_supported` (type `noinfo`), since a passage
that says nothing about a claim does not support it. No converter ships, and
this harness has not been run on SciFact or any other real set: the tests use
a fake model.

---

## Reporting results honestly

These rules apply to every number from these harnesses, in a pull request, a
paper or a README:

1. **State the denominator.** "60% detection" means nothing without "9 of 15
   checked". The harnesses print both; quote both.
2. **Unreachable is not a pass.** An entry no catalogue answered for (or an
   audit that did not conclude) is neither a detection nor an acceptance.
   Report the not-checked count beside the rates; never fold it into either.
3. **Lead with the false-accusation rate.** It is the rate that decides
   whether a user keeps trusting the warnings.
4. **Say what the set is.** A hand-built smoke set measures which failure
   kinds are visible, not field accuracy. A live run depends on catalogue
   state on the day: record the date, the `--limit`, and the cache file.
5. **Say what is unverified.** Results through the HALLMARK adapter must say
   that its field mapping was designed from the dataset description, unless
   it has since been checked against the real file.
6. **A matcher or prompt change needs a before-and-after on the same set.**
   Re-run with the same cache file and report which entries moved.
