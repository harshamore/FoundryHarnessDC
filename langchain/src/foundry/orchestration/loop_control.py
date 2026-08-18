"""The real "index -> map -> detect -> triage -> check coverage -> detect
the gaps -> re-triage -> report" sequence's decision logic (Phase 2) --
pure, deterministic, no agent or model involved, fully testable without
any LLM, exactly like `BudgetGovernor`/`CoverageStore` themselves.

This is where the pipeline-reordering discussion paused earlier in this
build resolves: `BudgetGovernor.should_stop()` and `CoverageStore.
review_cycle()`/`is_complete()` had zero callers anywhere in `src/` before
this module -- only in tests and hand-sequenced notebook cells. A real
loop needs a real sequence, not just concurrent workers to run inside one.
"""
from __future__ import annotations

from dataclasses import dataclass

from foundry.coverage.store import CoverageStore
from foundry.substrate.budget import BudgetGovernor


@dataclass(frozen=True)
class CycleOutcome:
    cycle: int
    closed_this_cycle: int
    still_open: int
    coverage_complete: bool
    should_stop: bool
    stop_reason: str


def evaluate_cycle(coverage_store: CoverageStore, budget_governor: BudgetGovernor, cycle: int) -> CycleOutcome:
    """One iteration's worth of the loop's decision: given the CURRENT
    state of the real CoverageStore/BudgetGovernor (after whatever
    detection/triage already ran this cycle), close what evidence now
    supports and decide whether to stop. Mechanical -- `review_cycle()`
    and `should_stop()` are the same conjunction proven in the Substrate
    and Coverage-Guide sections; this only sequences the calls."""
    review = coverage_store.review_cycle()
    complete = coverage_store.is_complete()
    stop, reason = budget_governor.should_stop(coverage_complete=complete)
    return CycleOutcome(
        cycle=cycle,
        closed_this_cycle=len(review["closed_this_cycle"]),
        still_open=len(review["still_open"]),
        coverage_complete=complete,
        should_stop=stop,
        stop_reason=reason,
    )


def has_directed_work_available(coverage_store: CoverageStore) -> bool:
    """Whether there's any still-open checklist item worth directing a
    Detector pass at. `CoverageStore.queue_directed_tasks` is itself
    idempotent (dedups on `task_type`), so calling it every cycle is
    always safe -- this just tells the caller whether doing so (and then
    spinning up a round of directed workers) is worth it, versus stopping
    with nothing left to direct."""
    return len(coverage_store.open_items()) > 0
