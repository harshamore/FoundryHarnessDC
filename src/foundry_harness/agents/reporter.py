"""Reporter (spec.md §5.8).

Purpose: produce the human-facing output -- a self-contained writeup for
each confirmed finding, severity and weakness classification, and an
evaluation-level rollup a reviewer can act on.

FR-079: MUST NOT publish anything whose verdict is not `true-positive`
(Constitution II). FR-083: reports MUST NOT name the LLM model/provider,
internal agent identifiers, or internal hostnames -- reports are
forwarded outside the operating team. FR-076/FR-077 (weakness taxonomy,
severity scheme) are open [NEEDS CLARIFICATION]s; see
models.finding.Severity.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole
from foundry_harness.models.finding import Finding


class Reporter(AgentRole):
    role_name: ClassVar[str] = "reporter"
    purpose: ClassVar[str] = (
        "Produce the human-facing output: per-finding writeups with "
        "severity and classification, and the evaluation-level rollup."
    )
    spec_section: ClassVar[str] = "§5.8"

    async def run(self) -> None:
        raise NotImplementedError

    async def render_finding_report(self, finding: Finding) -> str:
        """FR-075: title, affected component/location, description,
        attacker prerequisites, impact, reproduction steps, the
        Triager's evidence, and (if exploited) the PoC reference. FR-084:
        every code location MUST be a permalink that resolves for the
        report's reader."""
        raise NotImplementedError

    async def publish(self, finding: Finding) -> str:
        """FR-078: exactly one issue-tracker issue, labels encoding at
        minimum source/verdict/severity/exploited (FR-092). FR-079: only
        for verdict=true-positive. FR-080: update, don't duplicate, on
        change."""
        raise NotImplementedError

    async def build_rollup(self) -> str:
        """FR-081: finding counts by severity and exploited status,
        grouped by owning component, coverage status against each stated
        goal. FR-082: SHOULD identify keystone findings (those whose fix
        breaks the most attack paths)."""
        raise NotImplementedError
