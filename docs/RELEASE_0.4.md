# Research Companion 0.4 — Organized Research

One researcher, many researches: 0.4 gives every research project its own
isolated space, an organized overview of all of them, a library that reads at
a glance, and a knowledge graph that arranges itself around your draft.

## Features

### Workspaces — one isolated store per research (W4-B1..B5)
Every research now lives in its own workspace: papers, knowledge graph, draft,
suggestions, gaps, timeline, saved views, journey and conversations are fully
segregated per project. API keys and appearance settings stay global. Your
existing library migrates automatically into the first workspace on upgrade —
the migration is atomic, idempotent, and resumable; nothing is re-ingested and
your `.env` is never touched. CLI: `research-companion workspace
list|create|use` (or set `RESEARCH_COMPANION_WORKSPACE` per invocation).

### Researches screen + quick switcher (W4-F1)
A new landing surface lists every research as a card — name, draft title,
paper count, open suggestions, last activity — with create, rename and archive
actions. The top bar shows the active research as a dropdown for one-click
switching. This is the organized, cross-research overview.

### Library list view with status and relevance (W4-F2)
Alongside the card grid, a proper table: Title (your draft pinned first with
★), Year, Status (queued / processing / ingested / failed — with inline
retry), Strength, Relation to your draft (strengthens / challenges /
alternative), and Added — sortable, with live status updates streaming in
during folder ingest.

### Draft-centric knowledge graph (W4-F3)
A new default "Draft view": your draft fixed at the center, its sections as an
inner ring, and every library paper placed in labeled sectors by how it
relates to your work — strengthens, challenges, alternative, unaligned —
with relation-colored edges. The layout is deterministic: same graph, same
picture, every time. Click a paper to expand its extracted entities; flip to
"Explore view" for the original free-form physics graph.

## Breaking changes

None at the API or CLI surface. On first run after upgrading, a pre-0.4 store
is migrated from `~/.research-companion/` into
`~/.research-companion/workspaces/main/` (settings move to a root-level
`settings.json`). Everything continues to work unchanged; the layout change
only matters if external tools hardcode the old paths.

## Version & compatibility

- **Python:** 3.10 – 3.13
- **Dependencies:** no new external dependencies
- **Install:** `pip install research-companion`
