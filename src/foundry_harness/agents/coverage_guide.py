"""Coverage-Guide (spec.md §5.7).

Purpose: translate the operator's stated evaluation goals into a finite
checklist, steer the fleet toward uncovered items, judge when each item
has been credibly attempted, and declare coverage complete. Half of the
"done" signal (the other half is yield decay, tracked by the budget
governor -- see Constitution VI: coverage before yield, never yield
alone).

FR-068 is the important discipline here: if the goals document is empty
or placeholder text, this role waits and re-checks rather than
synthesizing plausible goals of its own. The operator's stated goals are
the only authority for what "done" means (Constitution X).

FR-072: this role reads, judges, and steers -- it MUST NOT itself detect,
triage, validate, or close the work-queue tasks it queues. The role that
decides whether work is done must not also be the role doing the work.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class CoverageGuide(AgentRole):
    role_name: ClassVar[str] = "coverage-guide"
    purpose: ClassVar[str] = (
        "Translate the operator's goals into a checklist, track the "
        "fleet's progress against it, declare coverage complete. Half of "
        "the 'done' signal."
    )
    spec_section: ClassVar[str] = "§5.7"

    async def run(self) -> None:
        raise NotImplementedError

    async def build_checklist(self) -> None:
        """FR-067: derive a finite checklist of (component x goal)
        coverage items from goals + security map, each with a stated bar
        for "credibly attempted". FR-068: never invent goals -- wait on
        an empty/placeholder goals document."""
        raise NotImplementedError

    async def review_cycle(self) -> None:
        """FR-069: gather evidence per open item from the coverage log,
        finding store, and work-queue history; check off items where the
        bar is met. "Swept and found nothing" satisfies an item exactly
        as well as "swept and filed three findings" -- coverage measures
        attempt, not outcome."""
        raise NotImplementedError

    async def queue_directed_tasks(self) -> None:
        """FR-070: for checklist items with no matching activity, phrased
        so a Detector instance with no other context can act on them."""
        raise NotImplementedError

    async def is_coverage_complete(self) -> bool:
        """FR-071: True only when every checklist item is closed. Cleared
        if the operator changes the goals."""
        raise NotImplementedError
