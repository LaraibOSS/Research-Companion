# Release notes — 0.6

Research Companion 0.6 extends the multi-agent review team from *"are your
citations real and is your contribution novel?"* to the rest of a reviewer's
desk-check: **does the paper fit its venue, which problems matter most, is the
work reproducible, and are the required integrity declarations present?** Every
new check keeps the project's discipline — deterministic at the core, evidence
you can inspect, and honest about what it does *not* do (no misconduct or
plagiarism claims; the venue-fit verdict is the only LLM step, and it is grounded
by a deterministic topic-overlap prefilter).

---

## 0.6.0 — Reviewer-grade integrity checks

### Venue-fit checker
- `research-companion review <paper-id> --venue <slug>` scores your
  contributions + abstract against a target venue's scope. A deterministic
  **topic-overlap prefilter** (`research_companion/venues.py::topic_overlap`)
  grounds an LLM fit verdict — **strong / moderate / weak / out_of_scope** — with
  a desk-reject risk, so the model can't free-associate a venue match.
- Rendered as a verdict block in the review report.
- Modules: `research_companion/venues.py`, `research_companion/agents/venuefit.py`
  (`VenueFitAgent`, `normalize_verdict`).

### Cross-discipline venue knowledge base
- A data-driven KB — `research_companion/data/venues.json` — with **19 venues
  across 9 disciplines** (ML, NLP, vision, data-mining/IR, biomedical, physics,
  psychology, economics, general). Each venue carries a scope blurb, topic
  keywords, reporting checklists, and common desk-reject rules.
- A discipline model (`infer_discipline`, `suggest_alternatives`,
  `venues_for_discipline`) routes cross-discipline papers and proposes
  alternative venues.
- **Extending it needs no code change** — add a venue by editing the JSON. See
  [docs/VENUE_KB.md](VENUE_KB.md).

### Severity-ranked findings
- The review's existing signals (novelty verdicts, unverified evidence, citation
  health, per-claim confidence) are now classified **critical > major > minor**
  and surfaced worst-first at the top of the report (OpenJudge
  Criticality-Verification pattern), so an author knows what to fix first.
- Modules: `research_companion/agents/severity.py` (`rank_findings`,
  `SeverityAgent`), rendered by `report.py`.

### Reproducibility / data-availability checker
- A deterministic, LLM-free scan for the artifacts that make a result
  reproducible: public **code/data links** (GitHub/GitLab/Zenodo/OSF/Dryad/HF
  datasets/…), **availability statements**, **methods-completeness signals**
  (hyperparameters, training details, compute, seeds, dataset splits), and
  **reporting-checklist mentions** (EQUATOR family — PRISMA/CONSORT/STROBE).
  Produces a **high / medium / low** level with the specific gaps.
- Modules: `research_companion/reproducibility.py`,
  `research_companion/agents/reproducibility.py` (`ReproducibilityAgent`).

### Integrity-declaration detector
- Checks whether a paper includes the declarations reviewers and venues
  increasingly require: **funding, conflict-of-interest, ethics/IRB approval,
  informed consent, author contributions.** Consent/ethics are reported but never
  flagged "missing" (they only apply to human/animal-subjects work).
- Deliberately **not** plagiarism detection — true near-duplicate detection needs
  an external similarity corpus/service and is tracked as a future item.
- Modules: `research_companion/ethics.py`,
  `research_companion/agents/ethics.py` (`EthicsAgent`).

### Pipeline wiring
- `ReproducibilityAgent` and `EthicsAgent` are **always-on** in `review` (cheap,
  deterministic); `SeverityAgent` runs in the full (non-`--fast`) pass;
  `VenueFitAgent` runs when `--venue` is supplied.

### Carried-forward known issues — resolved
- **`settings.embed_model` is now consumed** — wired through `qa`/`converse`
  ranking and the embedding backfill; switching models re-embeds instead of
  silently falling back to BM25.
- **Gap-relevance threshold is mode-independent** — `gaps._relevance_score()`
  normalizes the prefilter score to `[0, 1]`, so `sim_threshold` means the same
  thing with or without an HF token.
- **`publish.yml` re-runs are idempotent** — `twine upload --skip-existing`.

### Documentation
- New consolidated reference **[docs/DOCUMENTATION.md](DOCUMENTATION.md)** (+ PDF):
  overview, architecture, the full feature catalog, tech stack, and roadmap in one
  place.
- README, User Manual, and Developer Guide refreshed for the 0.6 features.

**Upgrade notes:** none — all additive. No store or settings migration. Publish
(tag → PyPI) is held pending explicit go-ahead, consistent with 0.5.x.
