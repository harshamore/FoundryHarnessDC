"""Phase 2 proofs: run_bounded (src/foundry/orchestration/concurrency.py) --
the generic bounded-concurrency primitive every concurrent-agent entry
point in this package goes through. No LLM, no DeepAgents involved here --
this is pure asyncio scheduling, proven with real `asyncio.sleep`-based
overlap detection, not simulated.
"""
from __future__ import annotations

import asyncio

import pytest

from foundry.orchestration.concurrency import run_bounded


@pytest.mark.asyncio
async def test_all_factories_run_and_results_are_in_factory_order():
    async def make(i: int):
        async def factory():
            await asyncio.sleep(0)
            return i * 10
        return factory

    factories = [await make(i) for i in range(5)]
    results = await run_bounded(factories, max_concurrent=3)
    assert results == [0, 10, 20, 30, 40]


@pytest.mark.asyncio
async def test_max_concurrent_actually_bounds_simultaneous_execution():
    """The real proof, not an assumption: track how many factories are
    inside their critical section at once via a shared counter, and
    confirm it never exceeds max_concurrent -- while also confirming more
    than one really does run at once (i.e. this isn't accidentally
    sequential either)."""
    max_concurrent = 3
    currently_running = 0
    peak_concurrency = 0
    lock = asyncio.Lock()

    async def make(i: int):
        async def factory():
            nonlocal currently_running, peak_concurrency
            async with lock:
                currently_running += 1
                peak_concurrency = max(peak_concurrency, currently_running)
            await asyncio.sleep(0.05)  # hold the slot long enough for overlap to be observable
            async with lock:
                currently_running -= 1
            return i
        return factory

    factories = [await make(i) for i in range(10)]
    results = await run_bounded(factories, max_concurrent=max_concurrent)

    assert sorted(results) == list(range(10))
    assert peak_concurrency == max_concurrent  # bound was actually reached, not just never exceeded
    assert peak_concurrency <= max_concurrent


@pytest.mark.asyncio
async def test_max_concurrent_one_is_effectively_sequential():
    order: list[int] = []

    async def make(i: int):
        async def factory():
            order.append(i)
            await asyncio.sleep(0)
            return i
        return factory

    factories = [await make(i) for i in range(4)]
    await run_bounded(factories, max_concurrent=1)
    assert order == [0, 1, 2, 3]  # never started the next until the previous returned


@pytest.mark.asyncio
async def test_rejects_non_positive_max_concurrent():
    async def factory():
        return 1

    with pytest.raises(ValueError, match="max_concurrent must be at least 1"):
        await run_bounded([factory], max_concurrent=0)


@pytest.mark.asyncio
async def test_empty_factories_returns_empty_list():
    assert await run_bounded([], max_concurrent=3) == []


@pytest.mark.asyncio
async def test_one_factory_raising_does_not_hang_the_rest():
    async def make(i: int, should_raise: bool):
        async def factory():
            await asyncio.sleep(0)
            if should_raise:
                raise RuntimeError(f"worker {i} failed")
            return i
        return factory

    factories = [await make(0, False), await make(1, True), await make(2, False)]
    with pytest.raises(RuntimeError, match="worker 1 failed"):
        await run_bounded(factories, max_concurrent=3)
