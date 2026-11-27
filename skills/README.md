# Claude Code skills

Research Companion's checks work from the terminal, from the browser Lab, and —
with these — from inside [Claude Code](https://claude.com/claude-code), so an
agent can run them on a paper you are working on without you learning the CLI.

Four of them are **free**: no model calls, no API cost. Two can spend money,
and each one says so, with a cost estimate, before it runs anything paid.

| skill | question it answers | cost |
|---|---|---|
| [`submission-check`](submission-check/SKILL.md) | Would this get desk-rejected? | free — nothing but the PDF |
| [`refcheck`](refcheck/SKILL.md) | Do these references actually exist? Are any retracted? | free — network (CrossRef / OpenAlex / arXiv) |
| [`literature-scout`](literature-scout/SKILL.md) | What should I read on this topic? | free — network (Semantic Scholar) |
| [`research-agents`](research-agents/SKILL.md) | Which agent do I want, and what will it cost? | free — reads a built-in list |
| [`paper-review`](paper-review/SKILL.md) | What would a reviewer flag in this draft? | fast review free after a one-time **paid** extraction; full review **paid** — asks first |
| [`rebuttal`](rebuttal/SKILL.md) | Help me answer these reviews. | splitting the reviews free; drafting **paid** — asks first |

## Install

Copy the directories you want into your Claude Code skills folder:

```bash
# macOS / Linux
cp -r skills/refcheck skills/submission-check skills/literature-scout \
      skills/paper-review skills/rebuttal skills/research-agents ~/.claude/skills/

# Windows (PowerShell)
Copy-Item -Recurse skills\refcheck, skills\submission-check, skills\literature-scout, `
    skills\paper-review, skills\rebuttal, skills\research-agents $HOME\.claude\skills\
```

Then in Claude Code:

```
/refcheck path/to/paper.pdf
/submission-check path/to/paper.pdf --venue neurips
/literature-scout speculative decoding --year-min 2023
/research-agents what checks my statistics?
/paper-review path/to/paper.pdf
/rebuttal path/to/paper.pdf reviews.txt
```

They also fire on their own when you ask the question in your own words
("are these citations real?", "will this get desk-rejected?", "what should I
read on graph RAG?", "help me answer these reviews") — that is what each
skill's `description` front-matter is for.

Requires `research-companion` on your `PATH` (`pip install research-companion`).

## Two design rules these skills follow

All of them exist to be *trusted*, which means they are written to avoid one specific
failure: reporting something as fine when it was never checked.

**A skipped check is never shown as a pass.** Every report separates CLEAN from
NOT CHECKED. `0 statistical tests found` means nothing was verified — not that
the statistics are sound. Lines of a bibliography that could not be parsed are
reported as a count, so the numerator is never mistaken for the whole.

**"Not found" is not "fabricated".** `refcheck` reports references it could not
locate, and real ones land there routinely — books, theses, workshop papers,
very recent preprints, non-English venues, anything outside the catalogues
searched. The skill is written to say *could not be found, check by hand*, never
*this citation is fake*. A checker whose warnings are mostly wrong gets ignored,
and then the real problems go unread too. The same holds for a retracted
reference (it exists; the notice is a separate fact), a paper missing from a
reading list, and a rebuttal quote that could not be matched in the paper's
text.

A third rule follows from the first: **every report states its denominator.**
Retractions are "flagged of checked", a review verdict lists the checks that
did not run, and a reading list names the one catalogue that was searched.

## Cost is said before it is spent

`paper-review` and `rebuttal` can make paid model calls. Both show the
estimate first (`research-companion cost-estimate`), default to the free path,
and run nothing paid until you say yes.

## Writing another one

The CLI has ~30 subcommands; these six wrap the ones that answer a
question a researcher already asks. If you add a skill, keep the
workspace discipline: Research Companion writes to a **global** store with named
workspaces, so a skill must set `RESEARCH_COMPANION_WORKSPACE` inline on every
command and default to a scratch workspace. Otherwise an agent invoked from any
directory writes into whichever research the user last had open.
