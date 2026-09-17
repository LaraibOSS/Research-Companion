# Claude Code skills

Research Companion's checks work from the terminal, from the browser Lab, and —
with these — from inside [Claude Code](https://claude.com/claude-code), so an
agent can run them on a paper you are working on without you learning the CLI.

Both skills here are **deterministic and free**: no model calls, no API cost.
They are the checks where an LLM would add nothing but expense.

| skill | question it answers | needs |
|---|---|---|
| [`submission-check`](submission-check/SKILL.md) | Would this get desk-rejected? | nothing but the PDF |
| [`refcheck`](refcheck/SKILL.md) | Do these references actually exist? | network (CrossRef / OpenAlex / arXiv) |

## Install

Copy either directory into your Claude Code skills folder:

```bash
# macOS / Linux
cp -r skills/refcheck skills/submission-check ~/.claude/skills/

# Windows (PowerShell)
Copy-Item -Recurse skills\refcheck, skills\submission-check $HOME\.claude\skills\
```

Then in Claude Code:

```
/refcheck path/to/paper.pdf
/submission-check path/to/paper.pdf --venue neurips
```

They also fire on their own when you ask the question in your own words
("are these citations real?", "will this get desk-rejected?") — that is what
each skill's `description` front-matter is for.

Requires `research-companion` on your `PATH` (`pip install research-companion`).

## Two design rules these skills follow

Both exist to be *trusted*, which means they are written to avoid one specific
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
and then the real problems go unread too.

## Writing another one

The CLI has ~30 subcommands; these two wrap the checks that are both free and
answer a question a researcher already asks. If you add a skill, keep the
workspace discipline: Research Companion writes to a **global** store with named
workspaces, so a skill must set `RESEARCH_COMPANION_WORKSPACE` inline on every
command and default to a scratch workspace. Otherwise an agent invoked from any
directory writes into whichever research the user last had open.
