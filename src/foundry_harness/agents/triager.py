"""Triager (spec.md §5.5).

Purpose: investigate each candidate finding and assign a verdict. The
noise filter -- most candidates are not real, and the Triager's job is to
establish which ones are, with evidence, before any human sees them.

FR-052 / §7.3 is the single most important quality control in the whole
system (Constitution I): a `true-positive` verdict requires the evidence
gate (models.finding.EvidenceGate) -- reachability, trust boundary,
impact, each a citation mechanically verified (FR-088) to resolve to real
code. A candidate the Triager believes is likely real but cannot prove
gets `needs-review` (FR-053), never `true-positive` by charity.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole
from foundry_harness.models.finding import Finding, InvestigationReport, Verdict


class Triager(AgentRole):
    role_name: ClassVar[str] = "triager"
    purpose: ClassVar[str] = (
        "Investigate each candidate and assign a verdict, gated on "
        "structural evidence. The noise filter."
    )
    spec_section: ClassVar[str] = "§5.5"

    async def run(self) -> None:
        raise NotImplementedError

    async def investigate(self, candidate: Finding) -> InvestigationReport:
        """FR-051: read the implicated code, trace data flow from entry
        point to sink using the index, identify sanitization/validation
        on the path, locate the entry point and trust boundary in the
        security map, assess attacker reachability."""
        raise NotImplementedError

    async def assign_verdict(self, candidate: Finding, report: InvestigationReport) -> Verdict:
        """FR-050: exactly one verdict. FR-052: true-positive requires
        the evidence gate satisfied. FR-053: evidence-gate failure with a
        believed-real candidate is needs-review, never true-positive."""
        raise NotImplementedError

    async def verify_citations_resolve(self, report: InvestigationReport) -> bool:
        """FR-088: every cited code location MUST be mechanically
        verified to resolve to real code at verdict time. A citation
        that does not resolve demotes the verdict to needs-review."""
        raise NotImplementedError

    async def inherit_prior_verdict(self, fingerprint_digest: str) -> Verdict | None:
        """FR-058: a fingerprint-equivalent finding already triaged in a
        related prior evaluation -- inherit non-true-positive verdicts
        directly; treat prior true-positive verdicts as an investigation
        prior, not a conclusion."""
        raise NotImplementedError
