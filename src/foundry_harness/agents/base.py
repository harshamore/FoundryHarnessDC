"""Base interface every agent role implements.

An `AgentRole` is one running instance of a role (spec.md §2 Glossary: "An
LLM-backed worker with a defined role, running in a loop, coordinating
with peers via the shared substrate"). Many instances of the same role may
run concurrently (a "fleet").

This module defines shape only. No detection, triage, validation, or
orchestration logic is implemented here -- see each role's docstring in
this package for its functional requirements, and docs/ARCHITECTURE.md
for how the roles compose.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from foundry_harness.orchestration.substrate import HeartbeatSink


class AgentRole(ABC):
    """Base class for all Foundry agent roles.

    Concrete roles override `role_name`, `purpose`, and `run`. The
    constructor intentionally takes only an id and a heartbeat sink here:
    each role's real dependency list (index, security map, work queue,
    finding store, sandbox, ...) differs and is declared on the subclass,
    not forced into a one-size-fits-all base signature.
    """

    role_name: ClassVar[str]
    purpose: ClassVar[str]
    """One-line responsibility, matching the table in spec.md §4.2."""
    spec_section: ClassVar[str]
    """Pointer into spec.md for the full requirement list, e.g. "§5.4"."""

    def __init__(self, agent_id: str, heartbeat_sink: HeartbeatSink) -> None:
        self.agent_id = agent_id
        self._heartbeat_sink = heartbeat_sink

    @abstractmethod
    async def run(self) -> None:
        """The role's main loop.

        MUST emit heartbeats on an execution lane independent of its
        primary work (FR-101, Constitution III) -- a heartbeat blocked
        behind CPU-bound or upstream-blocked work is indistinguishable
        from a dead agent to anything relying on liveness. MUST NOT be
        spawned or terminated by anything other than the Orchestrator
        (FR-002, FR-002a).
        """
        raise NotImplementedError

    async def heartbeat(self) -> None:
        """Emit one liveness signal (FR-100).

        Wall-clock runtime is never a substitute for this (FR-005,
        Constitution III): an agent that is alive and waiting on a
        rate-limited upstream still calls this; only a dead agent does
        not.
        """
        await self._beat()

    async def _beat(self) -> None:
        raise NotImplementedError(
            "Wire this role's heartbeat() to a HeartbeatSink.beat() call "
            "on its own execution lane (FR-101)."
        )
