"""Remediator (spec.md §6.4).

For a confirmed finding, generates a candidate source patch, verifies it
compiles/passes tests, and verifies (via Validator) that the PoC no
longer reproduces. Output is a proposed change for human review, never an
auto-applied fix. Plugs in downstream of Validator.

[NEEDS CLARIFICATION §6.4]: moves the system from "evaluation" toward
"remediation", which may be a different team's mandate. The "never
auto-applied" constraint is the seed's own language, not an inference --
this is the extension role most directly touching the human-in-the-loop
guarantee described in docs/INTEGRATION.md.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class Remediator(AgentRole):
    role_name: ClassVar[str] = "remediator"
    purpose: ClassVar[str] = (
        "Generate and verify candidate patches for confirmed findings. "
        "Never auto-applies a fix -- output is a proposal for human "
        "review."
    )
    spec_section: ClassVar[str] = "§6.4"

    async def run(self) -> None:
        raise NotImplementedError
