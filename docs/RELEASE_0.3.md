# Research Companion 0.3 — What's New

This release adds five major features to the Research Lab:

## Features

### Home & Journey Guidance (W3-F2)
A new Home view shows your research journey as a timeline of events (papers added, sections extracted, alignments scored, suggestions generated, conversations started). The journey guidance nudges you toward the next natural action based on what's happened so far.

### Suggestions Engine with Revision Tracking (W3-F3)
The system continuously generates suggestions for papers you should read based on your current draft and collected papers. Each suggestion is clickable — tap to open the paper in your Library drawer. Suggestions are scored by relevance severity (critical, important, informational) and include a detail explaining the reasoning. The suggestions engine tracks revision history, so you can see what changed between runs.

### Converse — Chat About Papers (W3-F4)
A new floating-action button opens a chat panel where you can discuss specific papers, ask for clarifications, or explore ideas with an LLM that has your paper context. Conversations are threaded and persistent — tap a thread to resume. Every answer cites the papers it draws from, and you can post answers as new views in your graph.

### Temporal Timeline & Gap Analysis (W3-F5)
View your papers arranged by publication date on an interactive timeline. The system continuously scans for research gaps — topics or claims made in your papers that aren't well-covered elsewhere in your collection — and highlights them as gaps on the timeline. Tap a gap to see the detail and start a conversation about what papers might fill it.

### Saved Views (W3-F6)
After running Ask or comparing papers, save your subgraph view for later. Views capture the exact papers and sections you were looking at. Browse your saved views in the Graph view's sidebar, and click to reload any view instantly.

## Configuration & API Keys

**Optional:** Set `HF_TOKEN` environment variable to enable hybrid semantic search via Hugging Face Inference API. If unset, BM25 (lexical) search will be used as fallback.

All API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, HF_TOKEN) should be stored in a local `.env` file with permissions 0600, never committed to version control. You can manage keys and themes directly from the Settings page in the Research Lab.

## Breaking Changes

None. The extraction prompt is unchanged from 0.2, so no cache invalidation is needed.

## Version & Compatibility

- **Python:** 3.10 – 3.13
- **Dependencies:** No new external dependencies added (all features use existing packages)
