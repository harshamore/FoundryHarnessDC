"""Attack-Mapper (spec.md §6.3).

Assembles confirmed findings into a privilege graph: nodes are positions
an attacker can occupy (network vantage, application role, shell on host,
possession of a credential); edges are transitions, each either a finding
or a by-design capability. Computes paths from attacker entry positions
to operator-defined goal positions. Output: the graph plus a prose report
of complete chains, near-complete chains and the gap that would close
them, and keystone findings whose fix breaks the most chains. Plugs in
downstream of Reporter; reads finding reports and the security map,
writes the chain analysis Reporter's rollup (FR-082) consumes.

[NEEDS CLARIFICATION §6.3]: the capability reviewers most often ask for
after seeing a flat finding list, but requires enough confirmed findings
to be meaningful (typically 10+).
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class AttackMapper(AgentRole):
    role_name: ClassVar[str] = "attack-mapper"
    purpose: ClassVar[str] = (
        "Assemble confirmed findings into a privilege graph showing how "
        "they chain from attacker entry points to operator-defined "
        "goals."
    )
    spec_section: ClassVar[str] = "§6.3"

    async def run(self) -> None:
        raise NotImplementedError
