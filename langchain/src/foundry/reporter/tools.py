"""LangChain tool wrappers for the Reporter role (spec.md §5.8).

`publish_finding_report` is the one that matters structurally: it binds
`ReporterStore.publish_finding_report()`, which checks the finding is
actually `true-positive` (FR-079) and scans the report text for forbidden
mentions (FR-083) before writing anything -- the model supplies content,
the tool decides whether it's allowed to be published.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.reporter.classification import lookup_cwe
from foundry.reporter.store import ReporterStore
from foundry.substrate.finding_store import FindingStore


def build_reporter_tools(finding_store: FindingStore, reporter_store: ReporterStore) -> list[BaseTool]:
    @tool
    def list_true_positives() -> str:
        """List every finding with verdict true-positive -- the only ones eligible for publication."""
        rows = finding_store.list_by_verdict("true-positive")
        if not rows:
            return "No true-positive findings yet."
        return "\n".join(
            f"#{r['id']} {r['symbol']} [{r['vulnerability_class']}] exploited={bool(r['exploited'])}"
            for r in rows
        )

    @tool
    def get_finding_detail(finding_id: int) -> str:
        """Get full details for one finding, including the Triager's investigation report."""
        row = finding_store.get(finding_id)
        if row is None:
            return f"No finding with id {finding_id}."
        return (
            f"id={row['id']} path={row['normalized_path']} symbol={row['symbol']} "
            f"class={row['vulnerability_class']} verdict={row['verdict']} "
            f"exploited={bool(row['exploited'])}\n"
            f"investigation report: {row['investigation_report']}"
        )

    @tool
    def suggest_weakness_class(vulnerability_class: str) -> str:
        """Look up a known CWE id for a vulnerability class, if one is mapped.
        Returns 'unmapped' if not -- use your own judgment for the weakness_class in that case."""
        cwe = lookup_cwe(vulnerability_class)
        return cwe if cwe else "unmapped"

    @tool
    def publish_finding_report(
        finding_id: int,
        title: str,
        report_body: str,
        severity: str,
        weakness_class: str,
    ) -> str:
        """Publish a self-contained report for a true-positive finding. severity must be
        one of critical/high/medium/low. report_body must include: affected component and
        location, description, attacker prerequisites, impact, reproduction steps, and the
        Triager's evidence -- and must NOT name any LLM model, provider, or internal
        system identifier (rejected automatically if it does)."""
        try:
            path = reporter_store.publish_finding_report(
                finding_id, title, report_body, severity, weakness_class
            )
        except ValueError as e:
            return f"publish_finding_report rejected: {e}"
        return f"Published to {path.name}."

    return [list_true_positives, get_finding_detail, suggest_weakness_class, publish_finding_report]
