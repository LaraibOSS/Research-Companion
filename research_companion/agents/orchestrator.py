"""Run agents as a dependency DAG: every ready agent runs concurrently,
one agent's failure never kills the run, and dependents of a failed agent
are skipped with an explanatory error.
"""
from __future__ import annotations

import asyncio

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


def _validate(agents: list[Agent]) -> None:
    names_list = [a.name for a in agents]
    for n in names_list:
        if not n:
            raise ValueError("empty agent name")
    if len(set(names_list)) != len(names_list):
        dupes = sorted({n for n in names_list if names_list.count(n) > 1})
        raise ValueError(f"duplicate agent name(s): {dupes}")
    names = {a.name for a in agents}
    for a in agents:
        for dep in a.depends_on:
            if dep not in names:
                raise ValueError(f"unknown dependency: {a.name} -> {dep}")
    # Kahn's algorithm for cycle detection.
    remaining = {a.name: set(a.depends_on) for a in agents}
    while remaining:
        ready = [n for n, deps in remaining.items() if not deps]
        if not ready:
            raise ValueError(f"cycle among agents: {sorted(remaining)}")
        for n in ready:
            del remaining[n]
        for deps in remaining.values():
            deps.difference_update(ready)


# Per-agent wall-clock cap: a hung lane (e.g. a stalled scholarly lookup) is
# demoted to a failed result instead of hanging the whole review indefinitely.
AGENT_TIMEOUT_SECONDS = 300


async def _run_one(agent: Agent, ctx: AgentContext) -> AgentResult:
    await ctx.bus.publish(events.AgentStarted(agent=agent.name))
    try:
        result = await asyncio.wait_for(agent.run(ctx), timeout=AGENT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        result = AgentResult(agent=agent.name, ok=False,
                             error=f"agent timed out after {AGENT_TIMEOUT_SECONDS}s")
    except Exception as exc:  # noqa: BLE001 — failure isolation is the contract
        result = AgentResult(agent=agent.name, ok=False, error=str(exc))
    # Trust the SCHEDULED name, not a value the agent returned — otherwise a
    # mismatched result.agent would mis-key results / KeyError del pending.
    result.agent = agent.name
    if result.ok:
        ctx.data[agent.name] = result.data
        await ctx.bus.publish(events.AgentDone(agent=agent.name, summary=str(result.data)[:200]))
    else:
        await ctx.bus.publish(events.AgentError(agent=agent.name, error=result.error))
    return result


async def run_agents(agents: list[Agent], ctx: AgentContext) -> dict[str, AgentResult]:
    """Run agents as a dependency DAG; every ready agent runs concurrently.

    Event semantics: a running agent gets AgentStarted before run() and AgentDone
    (ok) or AgentError (failed) after. Agents skipped because a dependency failed
    get ONLY AgentError (no AgentStarted) with error "dependency failed: <dep>".
    An agent that returns ok=False without raising is treated as failed
    (AgentError, no AgentDone).
    """
    _validate(agents)
    pending = {a.name: a for a in agents}
    results: dict[str, AgentResult] = {}
    while pending:
        ready = [
            a for a in pending.values()
            if all(d in results for d in a.depends_on)
        ]
        assert ready, f"internal error: DAG invariant violated among {sorted(pending)}"
        skipped = []
        runnable = []
        for a in ready:
            failed = next((d for d in a.depends_on if not results[d].ok), None)
            if failed is not None:
                skipped.append((a, failed))
            else:
                runnable.append(a)
        for a, failed_dep in skipped:
            results[a.name] = AgentResult(
                agent=a.name, ok=False, error=f"dependency failed: {failed_dep}"
            )
            await ctx.bus.publish(events.AgentError(agent=a.name, error=results[a.name].error))
            del pending[a.name]
        if not runnable:
            continue
        outcomes = await asyncio.gather(*(_run_one(a, ctx) for a in runnable))
        for r in outcomes:
            results[r.agent] = r
            del pending[r.agent]
    return results
