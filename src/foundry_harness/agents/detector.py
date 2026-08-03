"""Detector (spec.md §5.4).

Purpose: produce candidate findings. Breadth-first: cover the configured
scope using every available technique, queue everything plausible, and
let the Triager sort signal from noise.

FR-044 is the load-bearing constraint: the Detector writes to the finding
store and MUST NOT create issue-tracker issues or otherwise surface
candidates to humans (Constitution II). Detection is deliberately
high-volume, low-precision; that is what makes it thorough.

FR-037 (rule sweep) and FR-040 (exploratory hunting) are not alternatives
-- they are two halves of the detection-to-prevention flywheel described
in spec.md §5.4: exploratory findings confirmed true-positive with no
matching rule become rule-gap records (FR-042), which generalize into new
rules, which the next sweep catches systematically, freeing exploration
to hunt further out. The rule corpus (FR-041) is a versioned artifact
independent of this agent's code; the seed authors' worked example is
CodeGuard (https://github.com/cosai-oasis/project-codeguard).
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class Detector(AgentRole):
    role_name: ClassVar[str] = "detector"
    purpose: ClassVar[str] = (
        "Produce candidate findings by both systematic rule application "
        "and free-form exploration. Breadth-first."
    )
    spec_section: ClassVar[str] = "§5.4"

    async def run(self) -> None:
        raise NotImplementedError

    async def sweep_rules(self) -> None:
        """FR-037: for each function in scope, apply each detection rule
        as an LLM-evaluated check, with the function's body and
        caller/callee context from the index supplied."""
        raise NotImplementedError

    async def scan_dependencies(self) -> None:
        """FR-038: third-party dependencies with known published
        vulnerabilities."""
        raise NotImplementedError

    async def scan_secrets(self) -> None:
        """FR-039: hardcoded credentials, keys, tokens in the source
        tree."""
        raise NotImplementedError

    async def explore(self) -> None:
        """FR-040: free-form agent with goals, security map, testbed
        description, and persistent notes in context. MUST consult the
        coverage log before choosing an area (FR-046) and MUST NOT treat
        any prior agent's "fully covered" note as authoritative
        (FR-047, Constitution X)."""
        raise NotImplementedError

    async def record_rule_gap(self, finding_id: str, vulnerability_class: str, pattern: str) -> None:
        """FR-042: when an exploratory finding is confirmed true-positive
        and no rule would have produced it. Recorded by the Triager on
        confirmation, but the Detector is the role that must be able to
        answer "would any current rule have caught this"."""
        raise NotImplementedError
