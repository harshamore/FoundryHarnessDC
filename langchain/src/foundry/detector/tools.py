"""LangChain tool wrappers for the Detector's writes: queuing candidates
(spec.md FR-043/044/045) and recording rule gaps (FR-042), plus consuming
Coverage-Guide's directed-detection tasks (FR-070's other half).

`queue_candidate` is the Detector's *only* path to a human-visible result,
and it isn't one -- it writes to the internal finding store, never an
issue tracker or any other human-facing surface (FR-044, Constitution II:
"Surface Only What Survives"). Only the Reporter has a tool that produces
human-facing output.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.coverage.store import CoverageStore
from foundry.substrate.finding_store import FindingStore
from foundry.substrate.work_queue import WorkQueue


def build_detector_tools(store: FindingStore) -> list[BaseTool]:
    @tool
    def queue_candidate(
        normalized_path: str,
        symbol: str,
        vulnerability_class: str,
        description: str,
        technique: str,
    ) -> str:
        """Queue a candidate finding for later triage -- never surfaces to a human directly.
        `technique` should name the CodeGuard rule id used (e.g. 'codeguard-1-hardcoded-credentials'),
        or the literal string 'exploratory' for free-form findings."""
        finding_id, fp, was_new = store.queue_candidate(
            normalized_path=normalized_path,
            symbol=symbol,
            vulnerability_class=vulnerability_class,
            description=description,
            technique=technique,
        )
        status = "queued as a new candidate" if was_new else "already queued (deduplicated by fingerprint)"
        return f"Finding {finding_id} ({fp}) {status}."

    @tool
    def record_rule_gap(finding_fingerprint: str, vulnerability_class: str, pattern: str) -> str:
        """Record that a finding you believe is real has no matching CodeGuard rule --
        the seed for growing the rule corpus. Only call this for exploratory findings you're
        confident about, not for anything a rule already covers."""
        store.record_rule_gap(finding_fingerprint, vulnerability_class, pattern)
        return "Rule gap recorded."

    return [queue_candidate, record_rule_gap]


def build_directed_task_tools(
    work_queue: WorkQueue, coverage_store: CoverageStore, worker_id: str = "detector-directed"
) -> list[BaseTool]:
    """Tools letting a Detector consume Coverage-Guide's directed-detection
    tasks (spec.md FR-070) instead of leaving them queued and unread --
    `CoverageStore.queue_directed_tasks` writes real, claimable tasks; these
    tools are what finally reads and finishes them.

    Completing a task always records a `coverage_log` sweep (FR-069:
    "coverage measures attempt, not outcome"), not just a queue-status
    change -- otherwise a directed pass that checks an area and finds
    nothing would drain the queue without ever closing the checklist item
    it was sent to close, leaving the loop only superficially closed. The
    area/goal recorded come from the claimed task's own payload, tracked
    server-side in `claimed`, not re-supplied by the model -- the same
    "tool decides, model supplies inputs it can't fake" shape as the
    Triager's real resolver.

    `worker_id` is a fixed string rather than something unique per call:
    this is a single subagent claiming tasks sequentially within one
    invocation, not multiple concurrent workers, so there's no real
    identity to disambiguate.
    """
    claimed: dict[int, dict] = {}

    @tool
    def claim_directed_task() -> str:
        """Claim one pending directed-detection task queued by Coverage-Guide,
        if any exist. Returns its task id, area, goal, and instruction, or a
        message saying none are available. Call this in a loop -- investigate
        and complete each task you claim, then call it again -- until it says
        none are left."""
        task = work_queue.claim_next(worker_id, task_type_prefix="directed_detection:")
        if task is None:
            return "No directed tasks available."
        claimed[task.id] = {"area": task.payload["area"], "goal": task.payload["goal"]}
        return (
            f"task_id={task.id} area={task.payload['area']} goal={task.payload['goal']}\n"
            f"{task.payload['instruction']}"
        )

    @tool
    def complete_directed_task(task_id: int, note: str) -> str:
        """Mark a claimed directed-detection task done, after investigating it --
        whether or not you found anything. Call queue_candidate first if you found
        something; call this regardless, with a short note on what you actually
        checked -- this is what leaves permanent evidence the area/goal was
        checked, closing the coverage-checklist item for it."""
        info = claimed.get(task_id)
        if info is None:
            return f"Could not complete task {task_id} -- it wasn't claimed by this worker."
        released = work_queue.release(task_id, worker_id, status="done")
        if not released:
            return f"Could not complete task {task_id} -- it wasn't claimed by this worker."
        del claimed[task_id]
        coverage_store.record_sweep(info["area"], f"directed_detection:{info['goal']}", note=note)
        return f"Task {task_id} completed and recorded as covered ({info['area']} / {info['goal']})."

    return [claim_directed_task, complete_directed_task]
