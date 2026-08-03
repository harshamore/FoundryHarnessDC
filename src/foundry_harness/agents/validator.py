"""Validator (spec.md §5.6).

Purpose: for findings the Triager marked `true-positive` with a claim of
exploitability, independently reproduce the headline impact against the
testbed. The proof filter: "exploited" means demonstrated, not argued.

FR-060 is the load-bearing independence requirement (Constitution VII): a
fresh agent instance, sharing no conversational state with the agent that
produced the finding or its PoC, receives only the artifact and the
claim. It must not be gated on a Triager-set "exploitability" hint --
that hint may raise priority but is never a precondition, because gating
on it means a miscalibrated Triager silently disables this role entirely.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole
from foundry_harness.models.finding import ExploitationRecord, Finding


class Validator(AgentRole):
    role_name: ClassVar[str] = "validator"
    purpose: ClassVar[str] = (
        "For findings claimed exploitable, independently reproduce the "
        "headline impact against the testbed in a clean room. The proof "
        "filter."
    )
    spec_section: ClassVar[str] = "§5.6"

    async def run(self) -> None:
        raise NotImplementedError

    async def reproduce(self, finding: Finding) -> ExploitationRecord:
        """FR-060: independent, clean-room reproduction attempt. FR-065:
        SHOULD limit attempts per finding before recording
        not-exploited."""
        raise NotImplementedError

    async def set_exploited(self, finding: Finding, record: ExploitationRecord) -> None:
        """FR-061: exploited is binary and high-bar. NOT exploited:
        payload accepted but downstream effect unobserved; sink reached
        via debugger manipulation; vulnerable branch reached but final
        step deliberately not triggered; any reproduction without a live
        testbed."""
        raise NotImplementedError

    async def record_failure(self, finding: Finding, what_was_attempted: str, what_was_observed: str) -> None:
        """FR-062: on reproduction failure, record a structured
        explanation. MUST NOT clear the true-positive verdict -- failure
        to reproduce on a given day does not mean the vulnerability is
        not real."""
        raise NotImplementedError

    async def degrade_no_testbed(self, finding: Finding) -> ExploitationRecord:
        """FR-066: when no testbed is configured, produce the PoC
        artifact without running it, never set exploited, record "no
        testbed" as the reason."""
        raise NotImplementedError
