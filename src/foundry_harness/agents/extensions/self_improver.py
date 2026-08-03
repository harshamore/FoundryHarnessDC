"""Self-Improver (spec.md §6.5).

Periodically reads the fleet's own session logs, token-cost rollups,
error rates, tool-usage patterns, and the rule-gap log (FR-042); writes a
short feedback document for the operator proposing configuration,
prompt, and detection-rule changes with estimated impact. Does not act on
its own proposals. Plugs in alongside the Orchestrator; reads everything,
writes only its feedback file.

[NEEDS CLARIFICATION §6.5]: cheap to run and occasionally very valuable,
but only once there is enough log history to read.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class SelfImprover(AgentRole):
    role_name: ClassVar[str] = "self-improver"
    purpose: ClassVar[str] = (
        "Read the fleet's own logs, metrics, and rule-gap records; "
        "propose configuration, prompt, and detection-rule changes to "
        "the operator. Does not act on its own proposals."
    )
    spec_section: ClassVar[str] = "§6.5"

    async def run(self) -> None:
        raise NotImplementedError
