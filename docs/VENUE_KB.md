# Venue knowledge base

The venue-fit checker (`review --venue <slug>`, roadmap #7/#11) is driven by a
data file — **no code change is needed to add or edit a venue.**

- **Data:** `research_companion/data/venues.json`
- **Loader / API:** `research_companion/venues.py`
- **Consumer:** `research_companion/agents/venuefit.py`

## Adding a venue

Append an object to the `venues` array in `venues.json`:

```json
{
  "slug": "chi",
  "name": "CHI",
  "kind": "conference",
  "discipline": "hci",
  "scope": "Human-Computer Interaction: interaction techniques, user studies, and systems for human use.",
  "topics": ["human-computer interaction", "user study", "interface", "usability", "interaction"],
  "checklists": ["study pre-registration where applicable"],
  "desk_reject_rules": ["over the page limit", "no evaluation with users where claims require it"],
  "aliases": []
}
```

### Field reference

| Field | Required | Purpose |
|---|---|---|
| `slug` | yes | Unique lookup key (lowercase, hyphenated). |
| `name` | yes | Display name; also matched by `get_venue` (case/space-insensitive). |
| `kind` | yes | `conference` or `journal`. |
| `discipline` | yes | Groups venues for `infer_discipline` / in-discipline alternatives. Reuse an existing discipline string when possible. |
| `scope` | yes | Human-readable blurb handed to the LLM. |
| `topics` | recommended | Lowercase keywords for the deterministic `topic_overlap` prefilter. Multi-word entries are matched as **phrases**; single words as tokens. These also drive discipline inference, so choose discriminating terms. |
| `checklists` | optional | Reporting standards a submission is expected to follow (e.g. CONSORT, PRISMA, datasheets). Surfaced in the prompt and report. |
| `desk_reject_rules` | optional | Common desk-reject triggers (page limits, anonymization, scope). The LLM weighs these when scoring fit. |
| `aliases` | optional | Alternative names resolvable by `get_venue` (e.g. `nips` → `neurips`). |

## How it's used

1. `topic_overlap(paper_terms, venue)` — deterministic `[0,1]` scope prefilter.
2. The LLM venue-fit prompt is grounded in `scope` + `checklists` + `desk_reject_rules`.
3. For a weak/out-of-scope fit, `suggest_alternatives` recommends other venues in
   the same `discipline`, ranked by topic overlap.
4. `infer_discipline(paper_terms)` picks the best-matching discipline from the KB.

## Guidance

- Keep `topics` discriminating — overly generic terms ("method", "results")
  dilute both the overlap prefilter and discipline inference.
- Group venues under a shared `discipline` so alternatives stay relevant.
- The KB is intentionally curated, not exhaustive; grow it as new target venues
  come up. This is expected maintenance, not a roadmap blocker.
