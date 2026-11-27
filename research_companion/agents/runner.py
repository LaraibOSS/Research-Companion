"""Run a chosen set of agents on one paper: plan, check, execute, record.

The review command runs a fixed list. A person choosing agents in the Lab picks
some of them, and each picked agent may depend on others. This module turns a
selection into a runnable plan, says plainly why a selection cannot run, and
merges the result into the paper's saved review so earlier results are kept.

It holds no web or CLI concerns, so the CLI, the Lab and the MCP server can all
start agents the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from research_companion.agents.catalog import CARDS, STAGES, agent_classes, card_for

#: What a person can supply when starting agents from the Lab, mapped to the
#: card's plain "needs" wording. An agent whose needs fall outside this set
#: (the rebuttal drafter needs reviewer comments) is not runnable here.
SUPPLIABLE = {
    "venue": "venue",
    "problem statement": "problem_statement",
}


@dataclass
class RunPlan:
    """The agents that will run, in order, and anything that blocks the run."""

    agents: list[str] = field(default_factory=list)
    #: Agents added because something picked depends on them.
    added: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    #: True when any agent in the plan makes paid model calls.
    uses_model: bool = False
    #: True when any agent in the plan sends lookups to public catalogues.
    uses_network: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.agents)


def runnable_here(name: str) -> bool:
    """Can this agent be started with what a Lab user can supply?"""
    card = card_for(name)
    return card is not None and all(need in SUPPLIABLE for need in card.needs)


def plan_run(selected: list[str], *, inputs: dict | None = None) -> RunPlan:
    """Expand *selected* with its dependencies and check it can run.

    ``inputs`` holds what the person supplied, keyed as in ``SUPPLIABLE``
    values (``venue``, ``problem_statement``). Every problem is reported, not
    just the first, so a person can fix them in one go.
    """
    inputs = inputs or {}
    classes = agent_classes()
    plan = RunPlan()

    unknown = [n for n in selected if n not in classes]
    for name in unknown:
        plan.problems.append(f"There is no agent called {name!r}.")
    wanted = [n for n in dict.fromkeys(selected) if n in classes]
    if not wanted and not unknown:
        plan.problems.append("Choose at least one agent.")

    closure: set[str] = set()
    stack = list(wanted)
    while stack:
        name = stack.pop()
        if name in closure:
            continue
        closure.add(name)
        stack.extend(classes[name].depends_on)

    # Run order follows the catalogue: by stage, then as the cards are listed,
    # so a run reads in the same order a person sees the agents.
    order = {card.name: i for i, card in enumerate(CARDS)}

    def _key(name: str) -> tuple[int, int]:
        card = card_for(name)
        stage = STAGES.index(card.stage) if card else len(STAGES)
        return stage, order.get(name, len(order))

    plan.agents = sorted(closure, key=_key)
    plan.added = [n for n in plan.agents if n not in wanted]

    for name in plan.agents:
        card = card_for(name)
        if card is None:
            plan.problems.append(f"{name} has no description, so it cannot be offered.")
            continue
        if card.cost == "model":
            plan.uses_model = True
        if card.cost == "network":
            plan.uses_network = True
        for need in card.needs:
            key = SUPPLIABLE.get(need)
            if key is None:
                plan.problems.append(
                    f"{card.title} needs {need}, which can only be given from the command line.")
            elif not str(inputs.get(key) or "").strip():
                plan.problems.append(f"{card.title} needs a {need}.")
    return plan


def context_data(plan: RunPlan, *, inputs: dict | None = None, llm=None,
                 lookup=None, search=None) -> dict:
    """The shared context a run starts with: what the caller supplies.

    Only the keys the catalogue declares as caller-supplied are set, so an
    agent never finds a value it was not promised.
    """
    inputs = inputs or {}
    data: dict = {}
    if str(inputs.get("venue") or "").strip():
        data["_venue"] = str(inputs["venue"]).strip()
    if str(inputs.get("problem_statement") or "").strip():
        data["_problem_statement"] = str(inputs["problem_statement"]).strip()
    if llm is not None and plan.uses_model:
        data["_llm"] = llm
    if lookup is not None:
        data["_lookup"] = lookup
    if search is not None:
        data["_search"] = search
    return data


def build_agents(plan: RunPlan) -> list:
    classes = agent_classes()
    return [classes[name]() for name in plan.agents]


def merge_report(previous: dict | None, fresh: dict) -> dict:
    """Fold a run's lanes into the saved review, keeping earlier lanes.

    Running one agent must not erase the results of the others. Lanes from
    this run replace their earlier versions; readiness is recomputed over the
    merged set so it always describes everything known.
    """
    from research_companion.readiness import build_readiness

    lanes = dict((previous or {}).get("lanes") or {})
    lanes.update(fresh.get("lanes") or {})
    merged = dict(previous or {})
    merged.update({k: v for k, v in fresh.items() if k not in ("lanes", "readiness")})
    merged["lanes"] = lanes
    readiness = build_readiness(lanes)
    if readiness:
        merged["readiness"] = readiness
    else:
        merged.pop("readiness", None)
    return merged


def lane_summary(name: str, lane: dict | None) -> dict:
    """One agent's last result, reduced to what a list of agents can show."""
    if not lane:
        return {"agent": name, "state": "not_run", "error": ""}
    if not lane.get("ok"):
        return {"agent": name, "state": "failed", "error": str(lane.get("error") or "")}
    return {"agent": name, "state": "done", "error": ""}
