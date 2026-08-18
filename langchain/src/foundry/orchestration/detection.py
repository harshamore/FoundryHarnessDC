"""Real concurrent Detector execution (Phase 2): multiple subagent
*instances* actually running at once -- via `asyncio.gather` on separate
`.ainvoke()` calls, each on its own `sqlite3.Connection` to the same
database (WAL mode, the schema's default since the Substrate section) --
not one top-level agent choosing to batch several tool calls into a single
LLM turn, which is all the Full Pipeline section's single combined agent
ever proved.

Each worker opens its own connection deliberately, rather than sharing one
across concurrent asyncio tasks: `WorkQueue.claim_next()`'s atomicity was
already proven safe this way under real concurrent *threads*
(`tests/test_finding_store.py::test_concurrent_claims_never_double_claim`);
this is the same pattern, now exercised under real concurrent *agent
invocations* going through the actual DeepAgents/LangGraph async execution
path (see `tests/test_orchestration_detection.py`, which drives real
`create_deep_agent(...)` graphs with a scripted fake chat model rather than
mocking around the framework).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent

from foundry.agents._middleware import minimal_filesystem_middleware
from foundry.agents.detector import (
    build_detector_directed_subagent,
    build_detector_exploratory_subagent,
    build_detector_rule_sweep_subagent,
)
from foundry.codeguard.loader import Rule
from foundry.coverage.store import CoverageStore
from foundry.indexer.store import IndexStore
from foundry.observability.galileo import galileo_run_config
from foundry.orchestration.concurrency import run_bounded
from foundry.substrate.db import connect
from foundry.substrate.finding_store import FindingStore
from foundry.substrate.work_queue import WorkQueue

DEFAULT_MODEL = "openai:gpt-5.6-luna"


@dataclass(frozen=True)
class WorkerResult:
    run_name: str
    response_text: str


async def _run_single_subagent(
    *, model: str | Any, subagent: dict, main_system_prompt: str, user_message: str, galileo_callback, run_name: str
) -> WorkerResult:
    """One concurrent worker's real, complete unit of work: its own
    single-subagent main agent, one real `.ainvoke()` call. `model` is
    typed `str | Any` (not `str | BaseChatModel`) so tests can pass a
    scripted fake chat model instance without importing langchain_core
    here just for a type hint."""
    agent = create_deep_agent(
        model=model,
        subagents=[subagent],
        middleware=[minimal_filesystem_middleware()],
        system_prompt=main_system_prompt,
    )
    response = await agent.ainvoke(
        {"messages": [{"role": "user", "content": user_message}]},
        config=galileo_run_config(galileo_callback, run_name=run_name),
    )
    return WorkerResult(run_name=run_name, response_text=response["messages"][-1].content)


async def run_broad_detection_concurrently(
    *,
    db_path: Path,
    rules: list[Rule],
    security_map_digest: str,
    model: str | Any = DEFAULT_MODEL,
    galileo_callback=None,
) -> list[WorkerResult]:
    """Rule-sweep and exploratory Detector, run as two genuinely concurrent
    subagent instances against the same database -- the first half of
    Phase 2's "detect" step. Both write through `queue_candidate`
    (Constitution II) exactly like the sequential notebook cells already
    proved; running them concurrently changes nothing about what either
    one is allowed to do, only how many wall-clock seconds both together
    take."""

    async def rule_sweep_factory() -> WorkerResult:
        conn = connect(db_path)
        try:
            subagent = build_detector_rule_sweep_subagent(FindingStore(conn), IndexStore(conn), rules)
            return await _run_single_subagent(
                model=model,
                subagent=subagent,
                main_system_prompt=(
                    "You are the harness main agent. Delegate to the 'detector-rule-sweep' "
                    "subagent to check every function against the CodeGuard rule corpus."
                ),
                user_message=(
                    "Using the detector-rule-sweep subagent, check every function in the "
                    "index against the CodeGuard rule corpus and queue a candidate for "
                    "anything that plausibly violates a rule."
                ),
                galileo_callback=galileo_callback,
                run_name="detector-rule-sweep",
            )
        finally:
            conn.close()

    async def exploratory_factory() -> WorkerResult:
        conn = connect(db_path)
        try:
            subagent = build_detector_exploratory_subagent(FindingStore(conn), IndexStore(conn), security_map_digest)
            return await _run_single_subagent(
                model=model,
                subagent=subagent,
                main_system_prompt=(
                    "You are the harness main agent. Delegate to the 'detector-exploratory' "
                    "subagent to freely hunt for vulnerabilities in the target."
                ),
                user_message=(
                    "Using the detector-exploratory subagent, hunt this target for "
                    "vulnerabilities a generic rule checklist might miss."
                ),
                galileo_callback=galileo_callback,
                run_name="detector-exploratory",
            )
        finally:
            conn.close()

    return await run_bounded([rule_sweep_factory, exploratory_factory], max_concurrent=2)


def _directed_worker_factory(worker_index: int, *, db_path: Path, model: str | Any, galileo_callback):
    async def factory() -> WorkerResult:
        conn = connect(db_path)
        try:
            subagent = build_detector_directed_subagent(
                FindingStore(conn), IndexStore(conn), WorkQueue(conn), CoverageStore(conn)
            )
            return await _run_single_subagent(
                model=model,
                subagent=subagent,
                main_system_prompt=(
                    "You are the harness main agent. Delegate to the 'detector-directed' "
                    "subagent to work through every directed-detection task Coverage-Guide "
                    "has queued, one at a time, until none remain."
                ),
                user_message=(
                    "Using the detector-directed subagent, claim and investigate every "
                    "directed-detection task in the queue until none remain."
                ),
                galileo_callback=galileo_callback,
                run_name=f"detector-directed-{worker_index}",
            )
        finally:
            conn.close()

    return factory


async def run_directed_workers_concurrently(
    *,
    db_path: Path,
    n_workers: int = 4,
    max_concurrent: int = 4,
    model: str | Any = DEFAULT_MODEL,
    galileo_callback=None,
) -> list[WorkerResult]:
    """`n_workers` directed-detection worker instances, each independently
    looping `claim_directed_task`/investigate/`complete_directed_task`
    against the real `WorkQueue` (see `src/foundry/detector/tools.py`)
    until it finds nothing left to claim, run as genuinely concurrent
    subagent instances bounded to `max_concurrent` at once (Constitution
    V). More workers than pending tasks is fine -- the extras simply claim
    nothing and finish immediately, the same as an idle rule-sweep pass
    over an empty index would."""
    factories = [
        _directed_worker_factory(i, db_path=db_path, model=model, galileo_callback=galileo_callback)
        for i in range(n_workers)
    ]
    return await run_bounded(factories, max_concurrent=max_concurrent)
