"""The shipped Claude Code skills must stay true to the CLI they wrap.

A skill is prose telling an agent which commands to run. Nothing at runtime
checks it, so a renamed subcommand or flag leaves a confidently-wrong document
that fails only in front of a user. These tests bind the prose to the parser.
"""
from __future__ import annotations

import argparse
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
SKILL_FILES = sorted(SKILLS.glob("*/SKILL.md"))
EXPECTED = {"refcheck", "submission-check", "literature-scout", "paper-review",
            "rebuttal", "research-agents"}
# Skills added after the first two state the project's two honesty rules in
# their own words, in a section of their own.
STATES_BOTH_RULES = ("literature-scout", "paper-review", "rebuttal", "research-agents")
# Skills that can make paid model calls.
CAN_SPEND = ("paper-review", "rebuttal")


def _cli_subcommands() -> set[str]:
    """Top-level subcommand names the real parser accepts."""
    from research_companion.cli import _build_parser

    parser = _build_parser()
    names: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            names.update(action.choices)
    return names


def test_every_skill_is_shipped():
    assert {p.parent.name for p in SKILL_FILES} == EXPECTED
    assert (SKILLS / "README.md").is_file(), "skills/ needs a README for GitHub readers"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_frontmatter_has_a_name_and_a_trigger_description(skill):
    """Claude Code routes on the description; without one the skill never fires
    unless invoked by its exact slash name."""
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "missing YAML front-matter"
    block = text.split("---", 2)[1]
    name = re.search(r"^name:\s*(\S+)", block, re.M)
    desc = re.search(r"^description:\s*(.+)", block, re.M)
    assert name and name.group(1) == skill.parent.name
    assert desc and len(desc.group(1)) > 60, "description too thin to route on"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_command_the_skill_tells_an_agent_to_run_exists(skill):
    text = skill.read_text(encoding="utf-8")
    referenced = set(re.findall(r"research-companion\s+([a-z][a-z-]+)", text))
    unknown = referenced - _cli_subcommands()
    assert not unknown, f"{skill.parent.name} references non-existent commands: {unknown}"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_the_scratch_workspace_discipline_is_stated(skill):
    """Research Companion writes to a GLOBAL store. A skill that omits this
    writes into whichever research the user last had open."""
    text = skill.read_text(encoding="utf-8")
    assert "RESEARCH_COMPANION_WORKSPACE" in text
    assert "scratch" in text.lower()


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_a_skipped_check_is_never_presented_as_a_pass(skill):
    """The reporting rule the whole tool is built on."""
    text = skill.read_text(encoding="utf-8").lower()
    assert "not checked" in text


def _subparser_options() -> dict[str, set[str]]:
    """Option strings each top-level subcommand accepts."""
    from research_companion.cli import _build_parser

    out: dict[str, set[str]] = {}
    for action in _build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                out[name] = {o for a in sub._actions for o in a.option_strings}
    return out


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_flag_the_skill_passes_to_a_command_exists(skill):
    """A command can exist while the flag the skill hands it does not -- argparse
    then exits 2 in front of the user. Bind every `--flag` on a
    `research-companion <cmd>` line to that command's real options."""
    options = _subparser_options()
    bad = []
    for line in skill.read_text(encoding="utf-8").splitlines():
        for m in re.finditer(r"research-companion\s+([a-z][a-z-]+)([^`|]*)", line):
            cmd, rest = m.group(1), m.group(2)
            if cmd not in options:
                continue  # unknown commands are the other test's failure
            bad += [(cmd, f) for f in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", rest)
                    if f not in options[cmd]]
    assert not bad, f"{skill.parent.name} passes flags the CLI does not accept: {bad}"


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_workspace_subcommand_the_skill_names_exists(skill):
    """`workspace` exists, so the top-level binding passed while both original
    skills told the agent to run `workspace remove` -- a subcommand that has
    never existed. Bind the nested name too."""
    from research_companion.cli import _build_parser

    parser = _build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    ws = sub.choices["workspace"]
    ws_sub = next(a for a in ws._actions if isinstance(a, argparse._SubParsersAction))
    text = skill.read_text(encoding="utf-8")
    named = set(re.findall(r"research-companion\s+workspace\s+([a-z][a-z-]+)", text))
    unknown = named - set(ws_sub.choices)
    assert not unknown, f"{skill.parent.name} names non-existent workspace commands: {unknown}"


@pytest.mark.parametrize("name", STATES_BOTH_RULES)
def test_the_skill_states_both_honesty_rules(name):
    """The project's one promise: a check that did not run is never a pass, and
    something not found is never called fabricated."""
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8").lower()
    assert "a check that did not run is never presented as a pass" in text
    assert "something not found is never called fabricated" in text


@pytest.mark.parametrize("name", CAN_SPEND)
def test_a_skill_that_can_spend_money_says_so_before_running(name):
    """Cost must be stated before it is spent, with the estimate the CLI gives."""
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    front = text.split("---", 2)[1].lower()
    assert "paid" in front, "the routing description must not hide the cost"
    body = text.lower()
    assert "say this before running anything" in body
    assert "research-companion cost-estimate" in body
    assert re.search(r"(ask first|after a yes|wait for a yes)", body)


@pytest.mark.parametrize("name", sorted(EXPECTED - set(CAN_SPEND)))
def test_a_free_skill_runs_nothing_that_costs_model_calls(name):
    """A skill advertised as free must never tell an agent to run `build`, the
    paid extraction. The two existing skills mention it only as an option to
    offer, never as a command line to run."""
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    assert "research-companion build" not in text.replace("`research-companion build`", "")


def test_paper_review_reads_the_readiness_block_the_code_emits():
    """The skill teaches verdicts and coverage keys by name. Pin them to what
    readiness.build_readiness actually produces."""
    from research_companion import readiness

    sample = readiness.build_readiness(
        {"citation": {"ok": True, "data": {"counts": {"verified": 1}}}})
    text = (SKILLS / "paper-review" / "SKILL.md").read_text(encoding="utf-8")
    for key in sample["coverage"]:
        assert f"`{key}`" in text or f"coverage.{key}" in text, f"coverage key {key} not taught"
    for verdict in ("not_ready", "revise", "ready", "not_assessed"):
        assert f"`{verdict}`" in text
    # the verdict set is closed: a new one must be taught before it ships
    src = (REPO / "research_companion" / "readiness.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'verdict = "([a-z_]+)"', src))
    assert emitted == {"not_ready", "revise", "ready", "not_assessed"}
    assert "not a pass" in text.lower()


def test_refcheck_teaches_the_retraction_fields_the_cli_emits():
    """Retraction is reported over its own denominator. The skill must name
    every count the CLI returns and every notice value it can carry."""
    from research_companion.cli import _NOTICE_LABELS
    from research_companion.refcheck.validate import BibReport

    text = (SKILLS / "refcheck" / "SKILL.md").read_text(encoding="utf-8")
    for key in BibReport().retraction_counts():
        assert f"`{key}`" in text, f"retraction.{key} not explained"
    for notice in _NOTICE_LABELS:
        assert f"`{notice}`" in text, f"notice {notice} not explained"
    assert "`retraction_checked`" in text
    assert "flagged of checked" in text.lower()
    assert "a retracted paper exists" in text.lower()


def test_rebuttal_reads_evidence_status_not_the_verified_flag():
    """`verified` is True for a reply that quotes nothing. The skill must route
    the report through evidence_status, whose values are pinned to the code."""
    src = (REPO / "research_companion" / "rebuttal" / "draft.py").read_text(encoding="utf-8")
    statuses = set(re.findall(r'evidence_status = "([a-z_]+)"', src))
    assert statuses == {"verified", "unverified", "no_quotes"}
    text = (SKILLS / "rebuttal" / "SKILL.md").read_text(encoding="utf-8")
    for s in statuses:
        assert f"`{s}`" in text
    assert "read `evidence_status`, not `verified`" in text.lower()
    assert "drafts are drafts" in text.lower()


def test_research_agents_explains_every_cost_word_the_catalogue_uses():
    from research_companion.agents.catalog import catalog

    costs = {row["cost"] for row in catalog()}
    text = (SKILLS / "research-agents" / "SKILL.md").read_text(encoding="utf-8")
    for cost in costs:
        assert f"| `{cost}` |" in text, f"cost word {cost!r} not explained"
    assert "reachable_from" in text and "cannot be run from any command yet" in text


def test_refcheck_forbids_calling_a_missing_reference_fake():
    """`unverified` means "not found in the catalogues searched". Books, theses,
    workshop papers and recent preprints land there. Calling those fabricated is
    the failure that makes people stop reading the warnings."""
    text = (SKILLS / "refcheck" / "SKILL.md").read_text(encoding="utf-8")
    assert "not proof" in text.lower() or "never as" in text.lower()
    assert re.search(r"never\s+(call|as)\b", text, re.I), "no explicit prohibition"


def test_venues_named_by_submission_check_are_real():
    """The skill lists venue slugs; a stale list sends users to a silent no-op."""
    import json

    kb = json.loads((REPO / "research_companion" / "data" / "venues.json")
                    .read_text(encoding="utf-8"))
    known = {v["slug"] for v in kb["venues"]}
    text = (SKILLS / "submission-check" / "SKILL.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"`([a-z][a-z-]{2,})`", text)) & (known | {"nonsense-venue"})
    assert listed, "no venue slugs found in the skill"
    assert listed <= known, f"unknown venues listed: {listed - known}"


def test_readme_points_at_the_skills():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## Claude Code skills" in readme
    for name in EXPECTED:
        assert f"skills/{name}/SKILL.md" in readme, f"README does not link {name}"


# ---------------------------------------------------------------------------
# Documented configuration must exist
#
# README documented `PAPERGRAPH_DIR` for the store location. Nothing in the code
# has ever read it -- anyone following the README to relocate their library was
# silently ignored. A wrong env var is worse than an undocumented one: it looks
# like it worked.
# ---------------------------------------------------------------------------

def _documented_env_vars() -> set[str]:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    table = readme[readme.index("## Configuration & security"):]
    table = table[:table.index("## Roadmap")]
    return set(re.findall(r"`([A-Z][A-Z0-9_]{3,})`", table))


def _env_vars_read_by_code() -> set[str]:
    found: set[str] = set()
    for path in (REPO / "research_companion").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        found.update(re.findall(r'(?:environ\.get|getenv)\(\s*"([A-Z][A-Z0-9_]+)"', text))
        # some are referenced through a module-level constant
        found.update(re.findall(r'_ENV_VAR\s*=\s*"([A-Z][A-Z0-9_]+)"', text))
    return found


def test_every_env_var_the_readme_documents_is_read_somewhere():
    documented = _documented_env_vars()
    assert documented, "no env vars found in the configuration table"
    unknown = documented - _env_vars_read_by_code()
    assert not unknown, (
        f"README documents env vars nothing reads: {sorted(unknown)}. "
        "A variable that looks supported but is ignored is worse than none."
    )


def test_env_example_covers_the_keys_a_new_user_needs():
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    for required in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert required in example
    assert "RESEARCH_COMPANION_DIR" in example
    # it must not ship a real-looking secret
    assert not re.search(r"=\s*sk-[A-Za-z0-9_-]{10,}", example)


# ---------------------------------------------------------------------------
# Unpublished material must stay unpublished
#
# The paper/ directory is an EMNLP submission and the competitor/ARS analyses
# are internal teardowns of named projects. They are kept local. A file that
# re-enters tracking is easy to miss in a diff and impossible to recall once the
# repository is public.
# ---------------------------------------------------------------------------

PRIVATE_PATHS = (
    "paper",
    "docs/COMPETITOR_ARCHITECTURES.md",
    "docs/ARS_COMPARATIVE_ANALYSIS.md",
    "docs/ARS_INTEGRATION_STUDY.md",
)


def _tracked_files() -> set[str]:
    import subprocess

    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, check=False)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return set(out.stdout.split())


def test_unpublished_material_is_not_tracked():
    tracked = _tracked_files()
    leaked = sorted(f for f in tracked
                    if any(f == p or f.startswith(p + "/") for p in PRIVATE_PATHS))
    assert not leaked, f"private material is tracked again: {leaked}"


def test_gitignore_still_covers_the_private_paths():
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    for path in PRIVATE_PATHS:
        needle = path + "/" if path == "paper" else path
        assert needle in ignore, f".gitignore no longer covers {path}"


def test_nothing_public_links_to_private_material():
    """A dead link in shipped docs advertises that the material exists and
    points readers at a 404."""
    import re
    import subprocess

    names = ("COMPETITOR_ARCHITECTURES", "ARS_COMPARATIVE_ANALYSIS",
             "ARS_INTEGRATION_STUDY", "PAPER_DRAFT")
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, check=False)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    this_file = pathlib.Path(__file__).relative_to(REPO).as_posix()
    offenders = []
    for rel in out.stdout.split():
        if not rel.endswith((".md", ".py", ".json", ".cff")):
            continue
        if rel == this_file:
            continue          # this guard necessarily names them
        text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        if any(re.search(rf"\b{n}\b", text) for n in names):
            offenders.append(rel)
    assert not offenders, f"tracked files link to private material: {offenders}"


# ---------------------------------------------------------------------------
# The walkthrough tells a newcomer exactly what to type
#
# It is the first document a new user reads, so a command that does not exist
# there is worse than a missing doc: it teaches the wrong thing and fails in
# front of someone who cannot tell whether they or the tool is broken.
# ---------------------------------------------------------------------------

WALKTHROUGH = REPO / "docs" / "WALKTHROUGH.md"


def test_the_walkthrough_exists_and_is_linked():
    assert WALKTHROUGH.is_file()
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "docs/WALKTHROUGH.md" in readme, "README does not link the walkthrough"


def test_every_command_the_walkthrough_teaches_exists():
    text = WALKTHROUGH.read_text(encoding="utf-8")
    referenced = set(re.findall(r"research-companion\s+([a-z][a-z-]+)", text))
    assert referenced, "no commands found in the walkthrough"
    unknown = referenced - _cli_subcommands()
    assert not unknown, f"walkthrough teaches non-existent commands: {sorted(unknown)}"


def test_every_venue_the_walkthrough_lists_is_real():
    import json

    kb = json.loads((REPO / "research_companion" / "data" / "venues.json")
                    .read_text(encoding="utf-8"))
    known = {v["slug"] for v in kb["venues"]}
    text = WALKTHROUGH.read_text(encoding="utf-8")
    listed = set(re.findall(r"`([a-z][a-z-]{2,})`", text)) & known
    assert len(listed) >= 10, "venue list looks truncated"
    assert listed <= known


def test_the_walkthrough_covers_every_lab_tab():
    """A walkthrough that silently omits a tab leaves a feature undiscoverable."""
    help_js = (REPO / "research_companion" / "lab" / "static" / "js"
               / "helpContent.js").read_text(encoding="utf-8")
    tabs = set(re.findall(r"^  ([a-z]+): \{", help_js, re.M))
    text = WALKTHROUGH.read_text(encoding="utf-8").lower()
    missing = sorted(t for t in tabs if t not in text)
    assert not missing, f"walkthrough never mentions these tabs: {missing}"


def test_the_walkthrough_states_what_is_free_and_what_costs():
    """Cost is the thing a new user most needs to know before clicking."""
    text = WALKTHROUGH.read_text(encoding="utf-8").lower()
    assert "what it costs" in text
    assert "no model call" in text
    assert "cost-estimate" in text


def test_the_walkthrough_keeps_the_not_checked_rule_visible():
    """The reporting rule the whole tool is built on must reach the reader."""
    text = WALKTHROUGH.read_text(encoding="utf-8").lower()
    assert "not checked" in text
    assert "fabricated" in text and "not found" in text, (
        "the walkthrough must warn that 'not found' does not mean fabricated"
    )
