# AGENTS.md

Guidance for AI coding agents (and people) working on Research Companion.
For what the product does, read `README.md`; for how to contribute,
`CONTRIBUTING.md`. This file is the short list of things that are easy to get
wrong here.

## What this project is

A local-first workspace for researchers and students: add papers, map their
ideas, ask questions with citations, see what is unsolved, write with the
literature beside you, and check a draft before a reviewer does.

Its one promise is honesty about what it knows. **A check that did not run is
never shown as a pass, and something not found is never called fabricated.**
Every rule below follows from that.

## The agents inside the product

Review work is done by named agents in `research_companion/agents/`, run as a
dependency graph over a shared context. See them with:

```bash
research-companion agents          # what each does, what it costs, how to run it
research-companion agents --json
```

`research_companion/agents/catalog.py` is the source of truth. Each agent has a
card stating its cost in one of three words:

| Cost | Meaning |
|---|---|
| `free` | Runs on this machine. No key, no network. |
| `network` | Sends titles or identifiers to public catalogues. No key. |
| `model` | Makes paid calls to the user's model provider. |

### Rules for agents

1. **Agents decide what to look at. Deterministic code decides what is true.**
   Whether a reference exists, whether a p-value recomputes, whether a page
   limit is exceeded: these are computed, never asked of a model. A model may
   summarise, rank, or judge support; it may not overrule a computed result.
2. **Declare every hand-off.** An agent may read only what an agent in its
   `depends_on` wrote, or what the caller supplies. Ready agents run
   concurrently, so an undeclared read is a race. Add the key to the agent's
   card; `tests/test_agent_catalog.py` reads your source and fails if the card
   and the code disagree.
3. **Fail closed.** When an agent cannot determine something (empty search,
   unreadable model answer, source unreachable), it returns "not assessed" with
   the reason. It never falls back to the reassuring answer. Search for
   `verdict = "novel"`-style defaults before you add one.
4. **State the denominator.** "3 flagged" means little without "of 40 checked,
   12 could not be checked". Return both.
5. **Never understate cost.** If an agent starts calling a model, its card
   becomes `model` in the same change. A test enforces this.
6. **Write the card for a researcher.** One plain sentence on what they get
   back. No internal names.

### Adding an agent

1. Subclass `Agent` in `research_companion/agents/`, with `name`, `role`,
   `depends_on`.
2. Add its `AgentCard` to `CARDS` in `catalog.py`.
3. Run `python -m pytest tests/test_agent_catalog.py`. It checks the card
   against your code.
4. Wire it into a command only when it is ready; until then leave
   `reachable_from` empty, and the catalogue says so honestly.

## Context given to a model

Every prompt lives in `research_companion/prompts.py`. When you write or change
one:

- **Give the model only what it must judge.** The passage and the claim, not
  the paper. Retrieval picks the passages; the prompt does not ask the model to
  find them.
- **Paper text is data, not instructions.** It comes from PDFs anyone can
  write. Fence it, say it is untrusted, and never let it choose a tool or a
  verdict.
- **Ask for a quote, then check the quote.** A judgement must come with the
  words it rests on, and the code verifies those words are in the source.
- **Fix the vocabulary.** Enumerate allowed verdicts, and treat anything else
  as a failed call (rule 3).
- **Record what was dropped.** If text was truncated to fit, store that fact
  with the result.
- **A prompt change is a behaviour change.** Several prompts are hashed and cached
  results are keyed on that hash. Do not call a prompt "improved" without a
  before-and-after measurement on a labelled set.

## Working on the code

```bash
pip install -e ".[dev]"
python -m pytest -q                              # about 3,300 tests
node --test tests/js/*.test.mjs                  # about 1,100 tests
ruff check research_companion tests examples
python scripts/check_test_count.py               # the count may not shrink
python scripts/check_degradation_registry.py
```

- **Tests are the specification.** Many assert exact wording, because the
  wording is the honesty. If a test pins behaviour you are changing on purpose,
  change the test in the same commit and say why.
- **Fixtures come from the real system.** Generate them by running the code,
  not by hand. Hand-written fixtures have repeatedly encoded an assumption the
  parser never produces.
- **Write through `store.atomic_write_text`.** A plain write can leave a
  half-written file that the next save replaces with almost nothing.
- **The Lab has no login.** Its API refuses requests from other web origins
  (`cross_origin_rejection` in `lab_api.py`). Do not add an endpoint that
  changes state or spends money on a bare GET.
- **No new heavy dependencies** without a reason recorded in the pull request.
  The core install is deliberately small, and optional features are extras.
- **The frontend has no build step.** Plain ES modules under
  `research_companion/lab/static/js/`. Escape everything that reaches
  `innerHTML`.

## Commits and pull requests

- One fix or feature per commit, with its tests.
- Say what was wrong and why the change is right, not only what changed.
- If something is untested or only tested on crafted cases, say so in the
  pull request.
