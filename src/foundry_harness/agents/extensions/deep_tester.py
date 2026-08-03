"""Deep-Tester (spec.md §6.1).

Given a specific target (a function the Triager confirmed vulnerable, a
high-exposure endpoint the Cartographer flagged, an operator-nominated
component), applies input-generation testing -- coverage-guided fuzzing,
property-based testing -- to surface defects breadth-first detection
missed. Produces candidates into the finding store like the Detector.
Plugs in downstream of Triager (targets are usually chosen because triage
found something there) and upstream of Triager (its findings are triaged
like any other).

[NEEDS CLARIFICATION §6.1]: requires the target (or units of it) to be
buildable and executable in the evaluation environment -- a significant
infrastructure prerequisite. Not in scope until the core pipeline is
trustworthy.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class DeepTester(AgentRole):
    role_name: ClassVar[str] = "deep-tester"
    purpose: ClassVar[str] = (
        "Input-generation testing (fuzzing, property-based testing) "
        "against specific functions or endpoints the core pipeline "
        "already flagged. Depth where Detector gave breadth."
    )
    spec_section: ClassVar[str] = "§6.1"

    async def run(self) -> None:
        raise NotImplementedError
