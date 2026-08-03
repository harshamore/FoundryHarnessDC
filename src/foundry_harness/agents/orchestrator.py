"""Orchestrator (spec.md §5.1).

Purpose: the operator's sole interface, in two facets that must not block
each other (FR-019):
  - lifecycle:      validate config, spawn/maintain the fleet, expose
                     status, enforce budget, shut down cleanly.
  - conversational: answer questions about evaluation state, accept
                     operator tasks and steering, resolve help requests.

The Orchestrator is the only component that spawns or terminates agent
processes (FR-002); agents MUST NOT spawn peers directly (FR-002a). It
MUST NOT itself perform detection, triage, validation, or reporting
(FR-012) -- every time that boundary was blurred, inline analysis work
grew until lifecycle handling starved.

This is also where Constitution X ("The Operator Outranks Every Agent")
and NFR-009 (every automated decision is operator-overridable) are load-
bearing: FR-018 explicitly forbids the conversational facet from
modifying verdicts, setting `exploited`, or marking coverage complete on
its own initiative.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class OrchestratorLifecycleFacet:
    """Deterministic, latency-sensitive half of the Orchestrator.

    FR-019: MUST run on an execution lane separate from the conversational
    facet -- an in-flight LLM-backed answer must never delay respawn,
    heartbeat checking, status response, or shutdown.
    """

    async def validate_config(self) -> None:
        """FR-001: refuse to start with a specific, actionable error on
        invalid configuration."""
        raise NotImplementedError

    async def spawn_fleet(self) -> None:
        """FR-003: gate spawn of all non-Indexer roles on the Indexer
        reporting its knowledge base queryable (FR-024)."""
        raise NotImplementedError

    async def maintain_fleet(self) -> None:
        """FR-004: maintain configured role counts; respawn on exit,
        subject to crash-loop backoff (FR-007). FR-005: detect death by
        heartbeat absence (FR-100), never by wall-clock runtime."""
        raise NotImplementedError

    async def status(self) -> dict:
        """FR-008: per-agent role, instance index, alive/dead, current
        claim, heartbeat age, restart count."""
        raise NotImplementedError

    async def drain_and_stop(self) -> None:
        """FR-006: steer each agent to wrap up, wait a grace period, then
        terminate."""
        raise NotImplementedError


class OrchestratorConversationalFacet:
    """Model-backed, latency-variable half of the Orchestrator.

    FR-018: MUST NOT modify verdicts, set `exploited`, or mark coverage
    complete on its own initiative -- only on explicit operator
    instruction, with the override recorded (NFR-009).
    """

    async def answer(self, question: str) -> str:
        """FR-013: grounded in actual substrate contents, citing the
        records consulted -- never the model's general knowledge."""
        raise NotImplementedError

    async def queue_operator_task(self, description: str, priority: int) -> str:
        """FR-014."""
        raise NotImplementedError

    async def resolve_help_request(self, request_id: str) -> None:
        """FR-015: do what is asked, comment with what was done, clear
        the request marker."""
        raise NotImplementedError

    async def steer(self, target_role: str, message: str, *, disruptive: bool) -> None:
        """FR-016: deliver at the agent's next idle point (non-disruptive)
        or immediately with interruption (disruptive)."""
        raise NotImplementedError


class Orchestrator(AgentRole):
    role_name: ClassVar[str] = "orchestrator"
    purpose: ClassVar[str] = (
        "The operator's sole interface: validate configuration, spawn "
        "and maintain the fleet, expose status, enforce budget; and "
        "answer operator questions, accept tasks and steering, resolve "
        "help requests. One role, two facets that must not block each "
        "other."
    )
    spec_section: ClassVar[str] = "§5.1"

    def __init__(self, agent_id: str, heartbeat_sink) -> None:  # noqa: ANN001
        super().__init__(agent_id, heartbeat_sink)
        self.lifecycle = OrchestratorLifecycleFacet()
        self.conversational = OrchestratorConversationalFacet()

    async def run(self) -> None:
        """Not implemented: must schedule `lifecycle` and `conversational`
        on independent execution lanes (FR-019), not sequentially in one
        loop."""
        raise NotImplementedError
