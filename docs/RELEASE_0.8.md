# Release notes — 0.8

Research Companion 0.8 is about **honest denominators**. 0.7 exposed the
verification layer to other agents; 0.8 makes sure that when a check does not
run, nothing anywhere reports it as a check that passed — and takes the paid
gate off the checks that never needed a model.

---

## 0.8.0 — Free deterministic checks, Claude Code skills, honest coverage

### Checks that cost nothing no longer demand a paid step

`check-stats` (statcheck/GRIM) and `check-overlap` need the paper's **text and
nothing else**. Extracting text is a local parse — no model, no network. But
only the LLM-costing ingest path ever saved it, so on a freshly added local PDF
both failed with `no text for <id>. Add or ingest the paper first`, pointing the
user at a paid step to satisfy a free check. Text is now parsed on demand.

`refcheck` had the same shape: it read an LLM build's reference list, so
verifying that citations exist — deterministic plus a catalogue lookup — required
`build`. It now falls back to the paper's own bibliography, parsed
deterministically, and reports the lines it could **not** read as references so
the summary counts are never mistaken for the whole bibliography.

Verified on a real 40-reference paper: **39 verified, 0 suspect, 0 unparsed**,
with no model calls.

### Two Claude Code skills

`/refcheck` and `/submission-check` run the free checks from inside
[Claude Code](https://claude.com/claude-code), on a scratch workspace that never
touches a real research. See [`skills/`](../skills/).

### Claim audit reaches the Draft view

`POST /api/claim-audit {target: "draft"}` ran a runner built for a different
payload shape. It did not raise — it found no evidence, audited nothing, and
returned a summary of zero, which on screen is indistinguishable from a document
with no citations to check. Every draft audit had been silently checking nothing.
Verdict badges now appear on alignment evidence, matched on section + paper +
quote so a re-ordered alignment never labels the wrong passage.

### Report answers stopped failing

The report resolved one model in JSON mode and used it for both question
generation (JSON, correct) and answering (prose). OpenAI rejects
`response_format: json_object` outright unless the message contains the word
"json", so every answer failed and coverage could only ever read 0%. The
answering path now resolves a prose model, and a guard drops the JSON format
when a prompt cannot satisfy the API's precondition rather than failing the
whole request.

### Report page copy

The empty state said the same thing whether you had 0 papers or 200 — the first
is a missing prerequisite that Generate cannot satisfy. Cost is now stated
**before** the click, in model calls. `Generate plan` became the primary action:
planning is one call and free to edit, answering costs one call per question,
and the expensive path should not be the one that looks like the default.

### Fixes

- **mcp 2.x** removed `mcp.server.fastmcp`; the server resolves either layout,
  and an SDK that is present but unrecognised no longer reports as missing.
- **`refcheck` no longer accuses correct citations.** A line read from a
  bibliography carries authors and venue around the title and scored below the
  match threshold, so real papers came back `suspect`. Matching now tolerates
  both surrounding text and truncated titles without excusing a wrong one.
- **README documented `PAPERGRAPH_DIR`**, which nothing has ever read. The
  variable is `RESEARCH_COMPANION_DIR`.
