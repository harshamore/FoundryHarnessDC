"""Cartographer (spec.md §5.3).

Purpose: build and maintain the security map -- the contextual knowledge
every other role reasons against. Where the Indexer answers "what is the
code's structure", the Cartographer answers "what is the code's security
posture": what it exposes, where the trust boundaries are, how data
flows, what an attacker sees.

Whether the Cartographer gates fleet spawn the way the Indexer does is an
open [NEEDS CLARIFICATION] (spec.md §5.3); the seed's default is no gate,
with roles reading whatever map exists when they need it (FR-036).
FR-036a requires a minimal fallback (file tree, function index, testbed
endpoints) if authoring produces empty output -- an empty security map is
a Cartographer failure, not graceful degradation.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class Cartographer(AgentRole):
    role_name: ClassVar[str] = "cartographer"
    purpose: ClassVar[str] = (
        "Build and maintain the security map: architecture overview, "
        "attack-surface enumeration, trust boundaries, data flows, "
        "threat model. The contextual knowledge every other role reasons "
        "against."
    )
    spec_section: ClassVar[str] = "§5.3"

    async def run(self) -> None:
        raise NotImplementedError

    async def build_architecture_overview(self) -> None:
        """FR-030."""
        raise NotImplementedError

    async def build_attack_surface_enumeration(self) -> None:
        """FR-031: every entry point reachable by an actor outside the
        target's trust boundary, with the authentication required at
        each."""
        raise NotImplementedError

    async def build_trust_boundary_map(self) -> None:
        """FR-032: where untrusted input becomes trusted, where one
        privilege level acts on behalf of another, what validation (if
        any) guards each crossing. This is what makes evidence-gate leg
        (b) tractable for the Triager (§7.3)."""
        raise NotImplementedError

    async def build_data_flow_description(self) -> None:
        """FR-033: for credentials, secrets, user data, control commands
        -- where each enters, what it passes through, where it leaves."""
        raise NotImplementedError

    async def build_threat_model(self) -> None:
        """FR-034: synthesizes the above plus the operator's evaluation
        goals into attacker positions, goals, and threat categories per
        entry point / trust boundary."""
        raise NotImplementedError

    async def fallback_for_empty_section(self, section: str) -> None:
        """FR-036a: if any of the above fails to produce non-empty
        output, write a minimal fallback of mechanically-derivable facts
        so downstream roles have something to cite."""
        raise NotImplementedError
