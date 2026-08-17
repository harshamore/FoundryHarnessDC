"""LangChain tool wrappers for the Detector's writes: queuing candidates
(spec.md FR-043/044/045) and recording rule gaps (FR-042).

`queue_candidate` is the Detector's *only* path to a human-visible result,
and it isn't one -- it writes to the internal finding store, never an
issue tracker or any other human-facing surface (FR-044, Constitution II:
"Surface Only What Survives"). Only the Reporter (not built yet) has a
tool that produces human-facing output.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.substrate.finding_store import FindingStore


def build_detector_tools(store: FindingStore) -> list[BaseTool]:
    @tool
    def queue_candidate(
        normalized_path: str,
        symbol: str,
        vulnerability_class: str,
        description: str,
        technique: str,
    ) -> str:
        """Queue a candidate finding for later triage -- never surfaces to a human directly.
        `technique` should name the CodeGuard rule id used (e.g. 'codeguard-1-hardcoded-credentials'),
        or the literal string 'exploratory' for free-form findings."""
        finding_id, fp, was_new = store.queue_candidate(
            normalized_path=normalized_path,
            symbol=symbol,
            vulnerability_class=vulnerability_class,
            description=description,
            technique=technique,
        )
        status = "queued as a new candidate" if was_new else "already queued (deduplicated by fingerprint)"
        return f"Finding {finding_id} ({fp}) {status}."

    @tool
    def record_rule_gap(finding_fingerprint: str, vulnerability_class: str, pattern: str) -> str:
        """Record that a finding you believe is real has no matching CodeGuard rule --
        the seed for growing the rule corpus. Only call this for exploratory findings you're
        confident about, not for anything a rule already covers."""
        store.record_rule_gap(finding_fingerprint, vulnerability_class, pattern)
        return "Rule gap recorded."

    return [queue_candidate, record_rule_gap]
