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
EXPECTED = {"refcheck", "submission-check"}


def _cli_subcommands() -> set[str]:
    """Top-level subcommand names the real parser accepts."""
    from research_companion.cli import _build_parser

    parser = _build_parser()
    names: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            names.update(action.choices)
    return names


def test_both_skills_are_shipped():
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
