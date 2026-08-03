"""Finding Lifecycle data models.

Mirrors spec.md §7 (Finding Lifecycle) exactly: states (§7.1), verdicts
(§7.2), the evidence gate (§7.3), the exploited flag (§7.4), and the
fingerprint (§7.5). FR references below point at the functional
requirement each field or validator enforces.

These models are the "strictly bounded, prioritized, verifiable" contract
between agent roles: a Detector may only ever write a `Finding` at stage
CANDIDATE; only a Triager-authored `InvestigationReport` with a complete
`EvidenceGate` can carry a `true-positive` verdict (FR-052); only a
Validator may set `ExploitationRecord.exploited` (FR-089). No role logic
lives here -- only the shape those roles must produce and the structural
invariants a finding must satisfy at each stage.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Verdict(str, Enum):
    """§7.2. Exactly one verdict per triaged finding; mutable (re-triage
    replaces, FR-085)."""

    TRUE_POSITIVE = "true-positive"
    FALSE_POSITIVE = "false-positive"
    NEEDS_REVIEW = "needs-review"
    NOT_APPLICABLE = "not-applicable"
    CODE_QUALITY = "code-quality"


class FindingStage(str, Enum):
    """§7.1 lifecycle states. Non-`true-positive` verdicts terminate at
    TRIAGED and stay internal ("recorded", never published) per FR-057/
    Constitution II -- humans see only what survives triage."""

    CANDIDATE = "candidate"
    TRIAGED = "triaged"
    VALIDATED = "validated"
    PUBLISHED = "published"


class Severity(str, Enum):
    """Placeholder qualitative scheme.

    [NEEDS CLARIFICATION FR-077 / §11.9]: the spec does not prescribe a
    severity scheme (CVSS vs. qualitative tiers vs. an org-internal
    scheme). This is the seed authors' worked example only. Whatever
    scheme is chosen, FR-117 recommends a roughly geometric weighting
    across tiers (the seed authors used ~3.15x, i.e. approximately root
    10, per tier) so trailing yield is dominated by the highest-severity
    finding in the window rather than by low-severity volume.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class EvidenceCitation(BaseModel):
    """A single code-location citation.

    FR-088: every citation backing a `true-positive` verdict MUST be
    mechanically verified to resolve to real code in the target at
    verdict time; a citation that does not resolve demotes the verdict to
    `needs-review`. `resolved` records that check's outcome -- it is not
    self-asserted by the citing agent.
    """

    file_path: str
    symbol: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    excerpt: str | None = None
    resolved: bool = False


class EvidenceGate(BaseModel):
    """§7.3. The structural requirement a finding must satisfy before it
    may be classified `true-positive` (FR-087).

    Three legs, each a cited code location:
      - reachability:    an attacker-controlled entry point from which the
                          vulnerable sink is reachable.
      - trust_boundary:  where untrusted data crosses into trusted
                          processing without sufficient validation.
      - impact:          the concrete security consequence at the sink.

    FR-087a carve-out: for "presence is the vulnerability" classes
    (hardcoded credential/key/token, deprecated crypto primitive, a
    committed secret), `trust_boundary` MAY be satisfied by citing "the
    source repository itself" and `reachability` by the file's inclusion
    in the build; `impact` MUST still be cited. This carve-out does NOT
    apply to data-flow classes (injection, IDOR, SSRF, traversal), where
    all three legs require a real citation.
    """

    reachability: EvidenceCitation
    trust_boundary: EvidenceCitation
    impact: EvidenceCitation
    presence_is_vulnerability_carveout: bool = False

    @model_validator(mode="after")
    def _all_citations_resolved(self) -> "EvidenceGate":
        """FR-088: an unresolved citation cannot back a true-positive
        gate. Enforced here as the gate's own invariant, not left to the
        Triager to remember."""
        for leg_name, citation in (
            ("reachability", self.reachability),
            ("trust_boundary", self.trust_boundary),
            ("impact", self.impact),
        ):
            if not citation.resolved:
                raise ValueError(
                    f"EvidenceGate.{leg_name} citation must be resolved "
                    "(FR-088) before it can back a true-positive verdict"
                )
        return self


class Fingerprint(BaseModel):
    """§7.5. A finding's identity, keyed on code structure, not text
    position (FR-090). MUST NOT include line numbers, snippets, or
    detection timestamps -- those change on any nearby edit and would
    cause every re-run to re-file everything as new.
    """

    normalized_path: str
    symbol: str
    vulnerability_class: str

    def digest(self) -> str:
        """Deterministic hash used for deduplication (FR-045, FR-058,
        FR-091) and cross-run inheritance (FR-058)."""
        key = f"{self.normalized_path}::{self.symbol}::{self.vulnerability_class}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


class ProvenanceEvent(BaseModel):
    """One entry in a finding's audit trail.

    NFR-007 / SC-009: for any published finding, the full chain --
    detection technique, triage transcript, validation attempt, report
    render -- MUST be reconstructable from logs alone. A `Finding`'s
    `provenance` list is that reconstruction, not a substitute for the
    underlying session logs (FR-122).
    """

    stage: Literal["detection", "triage", "validation", "report"]
    role: str
    agent_id: str
    technique: str | None = None
    session_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str


class InvestigationReport(BaseModel):
    """Triager's output (§5.5).

    FR-054: a verdict without an investigation report MUST be rejected by
    the finding store -- the reasoning is what a reviewer audits; the
    verdict label is just an index into it.
    """

    reasoning: str
    evidence_gate: EvidenceGate | None = None
    consulted_testbed: bool = False


class ExploitationRecord(BaseModel):
    """Validator's output (§5.6, §7.4).

    FR-089: `exploited` is set only by the Validator, never by Detector,
    Triager, or Reporter, and never inferred. FR-061: the bar is binary
    and high -- payload-accepted-but-effect-unobserved, debugger-assisted
    reproduction, and "a similar issue was exploited" are all NOT
    exploited.
    """

    attempted: bool = False
    exploited: bool = False
    poc_reference: str | None = None
    testbed_used: bool = False
    reason_not_exploited: str | None = None

    @model_validator(mode="after")
    def _failure_requires_reason(self) -> "ExploitationRecord":
        """FR-062: on reproduction failure, a structured explanation is
        required."""
        if self.attempted and not self.exploited and not self.reason_not_exploited:
            raise ValueError(
                "reason_not_exploited is required when attempted=True and "
                "exploited=False (FR-062)"
            )
        return self


class Finding(BaseModel):
    """A claimed vulnerability at any lifecycle stage (§2 Glossary).

    Stage transitions are one-directional: CANDIDATE -> TRIAGED ->
    VALIDATED -> PUBLISHED (§7.1). A finding may terminate at TRIAGED
    (any non-true-positive verdict) and never advance further -- it stays
    in the internal store, visible via dashboard/Orchestrator query, but
    is never surfaced to humans (FR-057, Constitution II).
    """

    id: str
    fingerprint: Fingerprint
    title: str
    description: str
    scope_location: EvidenceCitation
    detection_technique: str
    """Which rule fired, or "exploratory" (FR-043)."""

    stage: FindingStage = FindingStage.CANDIDATE
    verdict: Verdict | None = None
    weakness_class: str | None = None
    """[NEEDS CLARIFICATION FR-076]: taxonomy is an integration choice.
    Recommended default: a CWE identifier (e.g. "CWE-89")."""
    severity: Severity | None = None
    """[NEEDS CLARIFICATION FR-077]: see Severity docstring."""

    investigation: InvestigationReport | None = None
    exploitation: ExploitationRecord | None = None
    provenance: list[ProvenanceEvent] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    """Minimal fixed set encoding source-system, verdict, severity tier,
    exploited yes/no, weakness class (FR-092)."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _true_positive_requires_evidence_gate(self) -> "Finding":
        """FR-052: MUST NOT assign true-positive unless the evidence gate
        is satisfied. Structural check only -- mechanical resolution of
        each citation (FR-088) is the Triager's job, enforced inside
        EvidenceGate itself."""
        if self.verdict == Verdict.TRUE_POSITIVE and (
            self.investigation is None or self.investigation.evidence_gate is None
        ):
            raise ValueError(
                "verdict=true-positive requires investigation.evidence_gate "
                "(FR-052, §7.3)"
            )
        return self

    @model_validator(mode="after")
    def _exploited_requires_true_positive(self) -> "Finding":
        """FR-089: exploited is a flag on a true-positive finding only."""
        if (
            self.exploitation
            and self.exploitation.exploited
            and self.verdict != Verdict.TRUE_POSITIVE
        ):
            raise ValueError(
                "exploitation.exploited requires verdict=true-positive (FR-089)"
            )
        return self

    def is_human_visible(self) -> bool:
        """FR-057: only true-positive findings, once published, are
        surfaced to humans via the Reporter. Everything else stays in the
        internal store (Constitution II)."""
        return self.stage == FindingStage.PUBLISHED and self.verdict == Verdict.TRUE_POSITIVE
