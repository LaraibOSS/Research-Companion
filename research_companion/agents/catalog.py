"""The agent catalogue: what each agent is for, what it costs, and what it hands on.

The agents in this package are run as a dependency graph over a shared context
(see ``orchestrator.run_agents``). Until now the only description of them was
their class attributes, and the only record of what one agent passes to another
was whichever keys its code happened to read. This module states both.

Two audiences:

* A researcher choosing what to run needs a plain sentence, the cost, and what
  must be supplied first. That is :class:`AgentCard`.
* The pipeline needs the hand-offs between agents to be sound: an agent may
  only read what an agent it depends on has written, or what the caller
  supplies. That is :func:`contract_problems`, which the test suite runs so a
  new agent cannot silently read a value that may not be there yet.

Costs are stated because they are the first thing a user asks:
``free`` runs on this machine with no key, ``network`` sends titles or
identifiers to public catalogues, ``model`` makes paid calls to the configured
model provider.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import asdict, dataclass

from research_companion.agents.base import Agent

COSTS = ("free", "network", "model")

#: What stage of the work an agent belongs to, in the order a researcher meets
#: them. Used to group the catalogue, not to schedule anything.
STAGES = ("prepare", "check", "position", "prioritise", "respond")

#: Shared-context keys supplied by whoever starts a run, not by an agent.
EXTERNAL_INPUTS = frozenset({
    "_llm",                # the model call, when a key is configured
    "_lookup",             # reference resolver (Crossref, OpenAlex, arXiv)
    "_search",             # literature search
    "_search_recent",      # literature search restricted to recent work
    "_venue",              # target venue slug
    "_problem_statement",  # the researcher's own problem statement
    "_reviews_text",       # reviewer comments, for the rebuttal
    "_concerns",           # pre-segmented reviewer concerns
    "_tone",               # rebuttal tone
})


@dataclass(frozen=True)
class AgentCard:
    """One agent, described for the person deciding whether to run it."""

    name: str
    title: str
    #: One plain sentence: what you get back.
    does: str
    stage: str
    cost: str
    #: What the researcher must supply beyond the paper itself.
    needs: tuple[str, ...] = ()
    #: Private shared-context keys this agent reads / writes for other agents.
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    #: Commands that run this agent today. Empty means it exists and is tested
    #: but nothing a user can reach starts it yet.
    reachable_from: tuple[str, ...] = ()


CARDS: tuple[AgentCard, ...] = (
    AgentCard(
        "ingest", "Reader",
        "Loads the paper and what was extracted from it, and places it in your library's graph.",
        "prepare", "free", writes=("_graph", "_extraction"),
        reachable_from=("review", "rebuttal")),
    AgentCard(
        "priorart", "Literature scout",
        "Searches scholarly catalogues for work related to the paper.",
        "prepare", "network", reads=("_extraction", "_search"),
        writes=("_priorart_papers",), reachable_from=("review",)),

    AgentCard(
        "citation", "Reference checker",
        "Looks every reference up and reports it as found, found with mismatched details, "
        "or not found.",
        "check", "network", reads=("_extraction", "_lookup"), reachable_from=("review",)),
    AgentCard(
        "statsoundness", "Statistics checker",
        "Recomputes reported p-values and tests whether reported means are arithmetically "
        "possible.",
        "check", "free", reachable_from=("review",)),
    AgentCard(
        "overlap", "Overlap checker",
        "Flags passages that closely repeat another paper in your own library.",
        "check", "free", reachable_from=("review",)),
    AgentCard(
        "compliance", "Venue rules checker",
        "Checks the paper against the target venue's submission rules.",
        "check", "free", needs=("venue",), reads=("_extraction", "_venue"),
        reachable_from=("review",)),
    AgentCard(
        "reproducibility", "Reproducibility checker",
        "Looks for public code and data, an availability statement, and a complete methods "
        "description.",
        "check", "free", reachable_from=("review",)),
    AgentCard(
        "ethics", "Declarations checker",
        "Looks for funding, conflict-of-interest, ethics and consent statements.",
        "check", "free", reachable_from=("review",)),

    AgentCard(
        "novelty", "Novelty assessor",
        "Compares each claimed contribution with the related work that was found.",
        "position", "model", reads=("_llm", "_priorart_papers"), reachable_from=("review",)),
    AgentCard(
        "citation_polarity", "Citation stance reader",
        "Labels how the paper uses each citation: builds on it, supports it, or contrasts "
        "with it.",
        "position", "model", reads=("_extraction", "_llm"), reachable_from=("review",)),
    AgentCard(
        "taxonomy", "Theme mapper",
        "Groups the related work into labelled themes.",
        "position", "model", reads=("_llm", "_priorart_papers"), reachable_from=("review",)),
    AgentCard(
        "benchmark", "Benchmark finder",
        "Suggests evaluation benchmarks that related work used.",
        "position", "free", reads=("_graph", "_priorart_papers"), reachable_from=("review",)),
    AgentCard(
        "venuefit", "Venue fit assessor",
        "Judges whether the paper's scope matches the target venue.",
        "position", "model", needs=("venue",), reads=("_extraction", "_llm", "_venue"),
        reachable_from=("review",)),
    AgentCard(
        "problem", "Problem statement refiner",
        "Sharpens your problem statement against your library and the related work found.",
        "position", "model", needs=("problem statement",),
        reads=("_graph", "_llm", "_priorart_papers", "_problem_statement")),
    AgentCard(
        "tracker", "New work watcher",
        "Sweeps recent publications for new work on the paper's topics.",
        "position", "network", reads=("_extraction", "_search_recent")),

    AgentCard(
        "confidence", "Confidence scorer",
        "Gives each claim a confidence value and an uncertainty band from the checks above.",
        "prioritise", "free", reachable_from=("review",)),
    AgentCard(
        "severity", "Triage",
        "Ranks every finding so you fix what matters first.",
        "prioritise", "free", reachable_from=("review",)),

    AgentCard(
        "rebuttal", "Rebuttal drafter",
        "Drafts a response to each reviewer concern, grounded in the paper.",
        "respond", "model", needs=("reviewer comments",),
        reads=("_concerns", "_llm", "_reviews_text", "_tone"), reachable_from=("rebuttal",)),
)

_BY_NAME = {c.name: c for c in CARDS}


def card_for(name: str) -> AgentCard | None:
    return _BY_NAME.get(name)


def agent_classes() -> dict[str, type[Agent]]:
    """Every concrete agent in this package, by its ``name``."""
    import research_companion.agents as pkg

    found: dict[str, type[Agent]] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        module = importlib.import_module(f"{pkg.__name__}.{info.name}")
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, Agent) and obj is not Agent
                    and obj.__module__ == module.__name__ and obj.name):
                found[obj.name] = obj
    return found


def _upstream(name: str, classes: dict[str, type[Agent]]) -> set[str]:
    """Every agent *name* depends on, directly or through another agent."""
    seen: set[str] = set()
    stack = list(classes[name].depends_on) if name in classes else []
    while stack:
        dep = stack.pop()
        if dep in seen or dep not in classes:
            continue
        seen.add(dep)
        stack.extend(classes[dep].depends_on)
    return seen


def catalog() -> list[dict]:
    """The catalogue as plain dicts, in stage order, for the CLI and the API."""
    classes = agent_classes()
    rows = []
    for card in sorted(CARDS, key=lambda c: (STAGES.index(c.stage), CARDS.index(c))):
        row = asdict(card)
        cls = classes.get(card.name)
        row["depends_on"] = list(cls.depends_on) if cls else []
        for key in ("needs", "reads", "writes", "reachable_from"):
            row[key] = list(row[key])
        rows.append(row)
    return rows


def handoffs() -> list[dict]:
    """Every hand-off between agents: who gives what to whom.

    An agent receives its dependency's result (stored under the dependency's
    name) and any private key that dependency wrote and this agent reads.
    """
    classes = agent_classes()
    writer_of = {key: card.name for card in CARDS for key in card.writes}
    edges = []
    for card in CARDS:
        cls = classes.get(card.name)
        if cls is None:
            continue
        direct = set(cls.depends_on)
        via: dict[str, list[str]] = {dep: [dep] for dep in cls.depends_on}
        for key in card.reads:
            writer = writer_of.get(key)
            if writer and writer != card.name:
                via.setdefault(writer, []).append(key)
        for giver, keys in via.items():
            edges.append({"from": giver, "to": card.name, "passes": keys,
                          "direct": giver in direct})
    return edges


def contract_problems() -> list[str]:
    """Everything wrong with the hand-off contracts. Empty means sound.

    The pipeline runs ready agents concurrently, so an agent that reads a value
    written by an agent it does not depend on is a race: it works when the
    writer happens to finish first and reads nothing when it does not.
    """
    classes = agent_classes()
    problems: list[str] = []

    for name in sorted(set(classes) - set(_BY_NAME)):
        problems.append(f"{name}: no catalogue card")
    for name in sorted(set(_BY_NAME) - set(classes)):
        problems.append(f"{name}: card for an agent that does not exist")

    writer_of: dict[str, str] = {}
    for card in CARDS:
        if card.stage not in STAGES:
            problems.append(f"{card.name}: unknown stage {card.stage!r}")
        if card.cost not in COSTS:
            problems.append(f"{card.name}: unknown cost {card.cost!r}")
        for key in card.writes:
            if key in EXTERNAL_INPUTS:
                problems.append(f"{card.name}: writes {key}, which the caller supplies")
            if key in writer_of:
                problems.append(f"{key}: written by both {writer_of[key]} and {card.name}")
            writer_of[key] = card.name

    for card in CARDS:
        if card.name not in classes:
            continue
        upstream = _upstream(card.name, classes)
        for key in card.reads:
            if key in EXTERNAL_INPUTS:
                continue
            writer = writer_of.get(key)
            if writer is None:
                problems.append(f"{card.name}: reads {key}, which nothing writes")
            elif writer != card.name and writer not in upstream:
                problems.append(
                    f"{card.name}: reads {key} from {writer} without depending on it")
        if card.cost != "model" and "_llm" in card.reads:
            problems.append(f"{card.name}: reads the model but is not marked cost='model'")
        if card.cost == "free" and any(
                k in card.reads for k in ("_lookup", "_search", "_search_recent")):
            problems.append(f"{card.name}: uses the network but is marked cost='free'")
    return problems
