# Research Companion 0.3 — What's New

The "true companion" release: the Lab now guides you, talks back, tracks your
revisions, and knows the history of your field.

## Features

### Home & Journey (W3-F2)
The Lab now opens on a Home view: a hero with your draft, open/addressed suggestion
counts and a severity donut; a **Do this next** card driven by deterministic rules
(connect a model → add a draft → ingest papers → review suggestions → explore the
timeline); your journey as a timeline of events (draft versions, suggestions
addressed, papers added); and a skippable 4-step onboarding for first launch.

### Suggestions engine with revision tracking (W3-T6/T8/F3)
Deterministic rules read your draft's review, alignments and the gap map and produce
concrete, sectioned advice: *discuss this paper as an alternative in related work*,
*back this claim with evidence*, *fix this unverified citation*. Each suggestion has
a stable id, a severity, a rationale and a source (paper/section), and lives in a
docked panel (bell icon) with Dismiss/Discuss actions. When you post a new draft
version, conservative matchers check what you incorporated and flip those suggestions
to **addressed** automatically — dismissals are sticky, and your open/addressed
counts are tracked per version.

### Converse — talk to the analysis (W3-T10/F4)
A floating Companion panel lets you discuss any artifact: the review, a section's
alignment, a suggestion, a gap, or a paper. Answers are grounded in retrieved
sections with [S#] citations, quotes are verified verbatim against the sources
(unverifiable spans are flagged, not hidden), and conversations persist on disk.
With no review report yet, the companion degrades to a project overview — it always
answers.

### Temporal timeline & gap analysis (W3-T4/T9/F5)
A Timeline view lays out concepts, methods and datasets by year — when each first
appeared and how it evolved. The **gap overlay** extracts limitations that papers
admit in their own limitation/future-work sections (quoted and verified verbatim),
then maps whether later papers — or your draft — address them. Open gaps that are
relevant to your draft become suggestions.

### Hybrid semantic search (W3-T2/T5)
Ask and Converse retrieval now fuse BM25 with embedding cosine similarity
(Hugging Face Inference API, `all-MiniLM-L6-v2`, vectors cached on disk). Without an
HF token the ranking is byte-identical to 0.2's pure BM25 — an exact, tested
degradation contract.

### Saved views (W3-T3/F6)
Save the subgraph behind any Ask answer (or hand-picked nodes) as a named view; pin,
rename, and reload views from the Graph sidebar. Views store node ids honestly —
nodes that no longer exist are reported as missing rather than silently dropped.

### Settings, themes & self-explanatory UI (W3-T1/F1/F7)
Enter provider/model and API keys from the Settings page — keys live in a local
`.env` (0600), are masked in every response, and take effect without a restart.
Dark/light themes, three accents, density toggle. Every view opens with a
dismissable one-line explainer, badges carry plain-English glossary tooltips, and
the Help panel documents the five core flows with a glossary table.

## Configuration & API keys

**Optional:** set `HF_TOKEN` (env or Settings page) to enable hybrid semantic
search. Without it, retrieval falls back to pure BM25 — identical to 0.2.

All keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `HF_TOKEN`) live in a local `.env`
with best-effort 0600 permissions, never in JSON and never committed. Manage them
from the Settings page.

## Breaking changes

None. The extraction prompt is unchanged from 0.2, so existing extraction caches
remain valid.

## Version & compatibility

- **Python:** 3.10 – 3.13
- **Dependencies:** no new external dependencies (all features use existing packages)
- **Install:** `pip install research-companion` (PyPI, new in this release)

## 0.3.1 (fast-follow)

Direct PDF upload: the "+ Add papers" modal now opens on an **Upload PDF** tab —
drag a PDF in or click to browse — with a **"This is my draft ★"** checkbox that
uploads and marks your draft in one step. Onboarding's "Add your draft" and the
home Do-this-next card route straight to it. Backed by `POST /api/papers/upload`
(raw body, no new dependencies); duplicate uploads are recognized by content
hash and answered gently.
