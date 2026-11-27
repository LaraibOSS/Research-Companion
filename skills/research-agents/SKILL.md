---
name: research-agents
description: "Use when someone asks which of Research Companion's agents or checks they should use, what an agent does, what it costs, whether it needs an API key or sends data online, or how to run it. Reads the tool's own agent catalogue and explains each agent's cost in plain words (free, online lookup, or paid model calls) and which command runs it. Reads a built-in list only: no LLM calls, no network, no cost."
---

# /research-agents

Answer one question: **which agent do I want, and what will it cost?**

Research Companion does its review work with named agents — a reference checker, a statistics checker, a novelty assessor, a rebuttal drafter and so on. This skill reads the tool's own catalogue of them and helps the user pick, with the cost of each stated plainly. Reading the catalogue costs nothing: no model, no network.

## Usage

```
/research-agents                       # what is there, grouped by stage
/research-agents what checks my stats? # pick the agent for a question
/research-agents what is free?         # only the agents that cost nothing
```

## The two rules

These are the project's core promise, and every agent in the catalogue is built to follow them. Pass them on when you describe an agent.

- **A check that did not run is never presented as a pass.** An agent that could not run, or had nothing to examine, reports *not checked* or *not assessed* — and when you describe what a command will do, you say which agents it will **not** run.
- **Something not found is never called fabricated.** The reference checker reports references it could not find in public catalogues; that means "check by hand", not "fake".

## Workspace safety

Research Companion writes to a **global** store with named workspaces. Listing the agents reads nothing from the user's library, but keep the same habit as every other skill and set a scratch workspace inline:

```bash
RESEARCH_COMPANION_WORKSPACE=agents-scratch research-companion agents --json
```

PowerShell has no inline env-var prefix — use the Bash tool, or set `$env:RESEARCH_COMPANION_WORKSPACE` and restore it afterwards.

## What You Must Do When Invoked

### Step 1 — read the catalogue

```bash
RESEARCH_COMPANION_WORKSPACE=agents-scratch research-companion agents --json
```

Always read it live. The catalogue changes between versions; never answer from memory or from the example below.

### Step 2 — read the output

```json
{
  "agents": [
    {
      "name": "citation",
      "title": "Reference checker",
      "does": "Looks every reference up and reports it as found, found with mismatched details, or not found.",
      "stage": "check",
      "cost": "network",
      "needs": [],
      "reads": [],
      "writes": [],
      "reachable_from": ["review"],
      "depends_on": ["ingest"]
    }
  ]
}
```

What each field means for the user:

- `title` and `does` — the plain-language name and what they get back. Use these, not `name`, when talking to the user.
- `stage` — where it sits in the research process: `prepare`, `check` (check the paper), `position` (position the work against others), `prioritise` (decide what to fix first), `respond` (respond to reviewers).
- `cost` — exactly one of three words:

| cost | means | needs an API key? | sends anything off the machine? |
|---|---|---|---|
| `free` | runs entirely on this machine | no | no |
| `network` | looks titles or identifiers up in public scholarly catalogues | no | yes — titles and identifiers only, to public catalogues |
| `model` | makes **paid** calls to the user's model provider | yes | yes — passages of the paper, to the model provider |

  Say `network` as "free, but looks things up online" and `model` as "paid: uses your model provider". Never describe a `model` agent as free.
- `needs` — input the user must supply for it to run, such as `venue`, `reviewer comments`, or `problem statement`.
- `reachable_from` — the commands that run it. **An empty list means the agent exists but cannot be run from any command yet.** Say so plainly; do not suggest a way to run it.
- `depends_on` — agents it needs to run first.

### Step 3 — the cost of running an agent is the cost of its command

No command runs a single agent. A command runs a set of agents together, so the user pays for the command, not the agent. Tell them that, then give the cost of the command that would run the agent they picked:

| command | what it runs | cost |
|---|---|---|
| `review --fast` | reader, reference checker, related-work search, statistics, reproducibility, declarations, self-overlap | free (some online lookups) — **after** a one-time paid extraction (`build`) |
| `review --fast --venue <v>` | the above, plus the venue rules checker (free) and the venue-fit judgement | **one paid model call**, plus the one-time extraction |
| `review` (no `--fast`) | everything `review --fast` runs, plus novelty, how citations are used, related-work themes, benchmarks, confidence and severity ranking | **paid** — several model calls |
| `rebuttal` | the reader and the rebuttal drafter | **paid** — up to two model calls per reviewer concern, plus the one-time extraction |

Every agent that depends on the reader (`ingest`) needs the paper extracted first, and extraction (`build`) is paid. Recommend `cost-estimate` before it.

Several checks also exist as free stand-alone commands that need **no** extraction. Point to them when the user only wants that one thing:

| want | free command | skill |
|---|---|---|
| do the references exist? | `refcheck` | `/refcheck` |
| statistics, venue rules, self-overlap | `check-stats`, `check-compliance`, `check-overlap` | `/submission-check` |
| what to read on a topic | `discover` (a topic search, separate from the related-work agent) | `/literature-scout` |
| a full review with a readiness verdict | `review` | `/paper-review` |
| answers to reviewers | `rebuttal` | `/rebuttal` |

### Step 4 — report

Answer the user's question first, then the cost. Suggested shape for "what checks my statistics?":

```
Statistics checker — free, runs on this machine
  Recomputes reported p-values and tests whether reported means are arithmetically possible.

How to run it
  On its own, free, no extraction needed: /submission-check (check-stats)
  As part of a review: research-companion review --fast — free after a one-time
  paid extraction
```

For an overview, group by `stage` and give each agent one line: title, cost in words, what it does. List the agents with an empty `reachable_from` separately, under "Not available from a command yet".

Rules:

- **Never understate cost.** If any agent a command runs is `model`, the command is paid. Say so before the user runs it.
- Never offer to run an agent whose `reachable_from` is empty.
- If the user asks for something no agent does, say so. Do not stretch an agent's `does` to fit.

## What this does NOT do

Say it in one closing line if the user seems to expect it: this skill only describes the agents. It runs none of them. To run one, use the skill for its command, which states the cost again before anything is spent.
