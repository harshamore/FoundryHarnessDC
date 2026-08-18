"""Generic bounded-concurrency helper -- Constitution V ("The Provider Is
The Rate Arbiter") made structural: every concurrent-agent entry point in
this package goes through `run_bounded`, so "how many subagent invocations
run at once" is always an explicit, capped number this code controls,
never however many DeepAgents happens to batch into one LLM turn.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


async def run_bounded(factories: Sequence[Callable[[], Awaitable[T]]], max_concurrent: int) -> list[T]:
    """Run every zero-arg async factory in `factories`, at most
    `max_concurrent` at once, and return their results in the same order
    as `factories` (not completion order).

    Takes *factories* -- callables that return a coroutine when called --
    rather than already-created coroutines/tasks, so a factory's own work
    (including opening its own sqlite connection; see
    `foundry.orchestration.detection`) only begins once the semaphore
    actually admits it, not the moment this function is invoked. Passing
    live coroutines instead would start all of them immediately regardless
    of the semaphore, defeating the bound entirely.
    """
    if max_concurrent < 1:
        raise ValueError(f"max_concurrent must be at least 1, got {max_concurrent}")
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _run_one(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    return await asyncio.gather(*(_run_one(f) for f in factories))
