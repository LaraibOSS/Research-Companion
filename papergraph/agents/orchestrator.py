"""Run agents as a dependency DAG: every ready agent runs concurrently,
one agent's failure never kills the run, and dependents of a failed agent
are skipped with an explanatory error.
"""
from __future__ import annotations

import asyncio

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


def _validate(agents: list[Agent]) -> None:
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


async def _run_one(agent: Agent, ctx: AgentContext) -> AgentResult:
    await ctx.bus.publish(events.AgentStarted(agent=agent.name))
    try:
        result = await agent.run(ctx)
    except Exception as exc:  # noqa: BLE001 — failure isolation is the contract
        result = AgentResult(agent=agent.name, ok=False, error=str(exc))
    if result.ok:
        ctx.data[agent.name] = result.data
        await ctx.bus.publish(events.AgentDone(agent=agent.name, summary=str(result.data)[:200]))
    else:
        await ctx.bus.publish(events.AgentError(agent=agent.name, error=result.error))
    return result


async def run_agents(agents: list[Agent], ctx: AgentContext) -> dict[str, AgentResult]:
    _validate(agents)
    pending = {a.name: a for a in agents}
    results: dict[str, AgentResult] = {}
    while pending:
        ready = [
            a for a in pending.values()
            if all(d in results for d in a.depends_on)
        ]
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
