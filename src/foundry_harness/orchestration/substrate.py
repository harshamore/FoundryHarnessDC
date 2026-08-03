"""Substrate interfaces: the non-agent machinery every role depends on.

Specified as *behavior*, not mechanism (spec.md §8). Whether the backing
implementation is a database, a directory of files, or a message bus is an
§11 integration decision, deliberately left open by the seed spec. These
are `Protocol`s (structural typing), not base classes to subclass -- any
object with the right shape satisfies them.

No implementation logic lives here. Each method's docstring cites the
functional requirement(s) it must satisfy so an implementer can trace
behavior back to the spec.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WorkQueue(Protocol):
    """Ordered, claimable task queue. spec.md §8.1 (FR-094 - FR-099)."""

    def claim(self, role: str) -> Any | None:
        """Atomically claim one open task for `role`. FR-095: concurrent
        claims MUST receive different tasks, or "none available"."""
        ...

    def release(self, task_id: str) -> None:
        """Release a claim. MUST also happen automatically within bounded
        time of the holder's death, with no operator action. FR-096."""
        ...

    def add(self, title: str, description: str, priority: int) -> str:
        """Queue a new task. Operator- and agent-writable at runtime. FR-098."""
        ...

    def complete(self, task_id: str) -> None:
        """Mark a claimed task done."""
        ...


@runtime_checkable
class FindingStore(Protocol):
    """Durable, fingerprint-indexed record of every finding at every
    lifecycle stage. Internal; distinct from the issue tracker. spec.md
    §7, §8.1."""

    def write_candidate(self, finding: Any) -> None:
        """FR-044: candidates land here, never directly in the issue
        tracker. FR-045: MUST dedupe by fingerprint before writing."""
        ...

    def get_by_fingerprint(self, fingerprint: str) -> Any | None:
        ...

    def update(self, finding: Any) -> None:
        """FR-059: re-triage replaces the verdict; it does not duplicate
        the finding. FR-106a: atomic persist, never delete-then-write."""
        ...

    def query(self, **filters: Any) -> list[Any]:
        ...


@runtime_checkable
class CoverageLog(Protocol):
    """Append-only audit trail of (area x technique) attempts. An audit
    trail, not a stop-list (FR-046, FR-047, Constitution X)."""

    def record_attempt(self, area: str, technique: str, agent_id: str) -> None:
        ...

    def attempts_for(self, area: str) -> list[Any]:
        ...


@runtime_checkable
class BudgetGovernor(Protocol):
    """Tracks spend/runtime against operator caps; computes trailing yield;
    signals halt. spec.md §9.3-§9.4 (FR-112 - FR-117)."""

    def record_spend(self, role: str, usd: float, tokens: int) -> None:
        ...

    def trailing_yield(self) -> float:
        ...

    def should_halt(self, coverage_complete: bool) -> bool:
        """FR-116: yield-below-threshold halts ONLY when a full trailing
        window has accumulated, minimum runtime has elapsed, AND
        coverage_complete is True. Never on yield alone (Constitution VI)."""
        ...


@runtime_checkable
class Sandbox(Protocol):
    """Isolation boundary enforced by infrastructure, never by prompt.
    spec.md §9.1 (FR-107 - FR-109), Constitution IX."""

    def is_host_allowed(self, host: str) -> bool:
        ...

    def read_only_paths(self) -> tuple[str, ...]:
        ...


@runtime_checkable
class Dashboard(Protocol):
    """Operator-facing live view. MUST agree with `status` and the
    substrate's actual contents (FR-124). spec.md §10."""

    def publish_status(self, snapshot: Any) -> None:
        ...


@runtime_checkable
class HeartbeatSink(Protocol):
    """Liveness channel. An agent is alive iff it heartbeated recently;
    wall-clock runtime is never a liveness signal (FR-100, FR-101,
    Constitution III)."""

    def beat(self, agent_id: str, role: str) -> None:
        ...
