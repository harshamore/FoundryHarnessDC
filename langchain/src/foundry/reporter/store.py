"""Persists published finding reports and produces the evaluation rollup
(spec.md §5.8). FR-079 ("MUST NOT publish a finding whose verdict is
anything other than true-positive") and FR-083 (no model/provider/internal
identifiers in a report) are enforced here, in code -- not left to the
model's discretion, the same way FR-054 and the evidence gate are enforced
in `FindingStore`, not asked of the Triager politely.

Scope note: this build's Reporter output is local markdown files, not an
issue tracker (see docs/ARCHITECTURE.md's confirmed scope). FR-078's "one
issue per finding" and FR-080's "update, not duplicate" become "one file
per finding, keyed by fingerprint (Constitution VIII), overwritten on
re-publish" -- the same idempotency property, different backend.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from foundry.coverage.store import CoverageStore
from foundry.reporter.classification import find_forbidden_mentions
from foundry.reporter.executive_summary import RollupFacts, build_executive_summary
from foundry.substrate.db import lock_for

SEVERITIES = ("critical", "high", "medium", "low")


class ReporterStore:
    def __init__(self, conn: sqlite3.Connection, output_dir: Path) -> None:
        self._conn = conn
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def publish_finding_report(
        self,
        finding_id: int,
        title: str,
        report_body: str,
        severity: str,
        weakness_class: str | None,
    ) -> Path:
        """FR-075/078/079/080/083, enforced structurally:
          - the finding must actually be true-positive (FR-079) -- checked
            against the finding store, not trusted from the caller
          - severity must be one of the fixed set, the same pattern as the
            Verdict enum
          - the full report text must not mention the model, provider, or
            internal identifiers (FR-083) -- checked with a denylist scan,
            not a prompt instruction
          - one file per finding, keyed by fingerprint, overwritten rather
            than duplicated on re-publish (FR-078/080)
        """
        with lock_for(self._conn):
            row = self._conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
        if row is None:
            raise ValueError(f"no finding with id {finding_id}")
        if row["verdict"] != "true-positive":
            raise ValueError(
                f"finding {finding_id} has verdict {row['verdict']!r}, not true-positive -- "
                "refusing to publish (FR-079)"
            )
        if severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {severity!r}, must be one of {SEVERITIES}")

        full_text = f"# {title}\n\n{report_body}"
        forbidden = find_forbidden_mentions(full_text)
        if forbidden:
            raise ValueError(
                f"report mentions forbidden term(s) {forbidden} -- FR-083 prohibits naming "
                "the model, provider, or internal identifiers in a finding report"
            )

        report_path = self._output_dir / f"{row['fingerprint']}.md"
        report_path.write_text(full_text, encoding="utf-8")

        with lock_for(self._conn):
            self._conn.execute(
                """
                INSERT INTO finding_reports (finding_fingerprint, severity, weakness_class, report_path)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(finding_fingerprint) DO UPDATE SET
                    severity = excluded.severity,
                    weakness_class = excluded.weakness_class,
                    report_path = excluded.report_path,
                    updated_at = datetime('now')
                """,
                (row["fingerprint"], severity, weakness_class, str(report_path)),
            )
        return report_path

    def list_published(self) -> list[sqlite3.Row]:
        with lock_for(self._conn):
            return self._conn.execute("SELECT * FROM finding_reports ORDER BY id").fetchall()

    def _gather(self, coverage_store: CoverageStore):
        """Shared aggregation behind both `build_rollup` and
        `build_ciso_report` -- one query, one grouping pass, so the two
        report formats can never disagree about the underlying facts."""
        with lock_for(self._conn):
            published = self._conn.execute(
                """
                SELECT f.fingerprint, f.symbol, f.vulnerability_class, f.exploited, r.severity
                FROM findings f JOIN finding_reports r ON f.fingerprint = r.finding_fingerprint
                ORDER BY f.symbol
                """
            ).fetchall()

        by_severity: dict[str, int] = {}
        by_exploited = {"exploited": 0, "not_exploited": 0}
        by_component: dict[str, list[sqlite3.Row]] = {}
        for r in published:
            by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1
            by_exploited["exploited" if r["exploited"] else "not_exploited"] += 1
            by_component.setdefault(r["symbol"], []).append(r)

        open_items = coverage_store.open_items()
        closed_items = coverage_store.closed_items()
        return published, by_severity, by_exploited, by_component, open_items, closed_items

    def _exploitability_section(self, published, exploitability_store: Any) -> list[str]:
        """Phase 8: groups `published` findings by their exploitability
        classification (if one was recorded -- a finding the mapper
        never reached, e.g. the LLM step was skipped or failed entirely,
        is listed as unclassified rather than silently omitted)."""
        buckets: dict[str, list[str]] = {"exploitable": [], "contained": [], "not_correlated": [], "unclassified": []}
        for r in published:
            verdict = exploitability_store.get(r["fingerprint"])
            label = f"{r['symbol']} [{r['vulnerability_class']}]"
            if verdict is None:
                buckets["unclassified"].append(label)
                continue
            detail = f"{label}: {verdict['reasoning']}"
            if verdict["correlated_resource"]:
                detail += f" (resource: {verdict['correlated_resource']})"
            buckets[verdict["classification"]].append(detail)

        lines = ["## Exploitability"]
        lines.append(
            f"- {len(buckets['exploitable'])} exploitable, {len(buckets['contained'])} contained, "
            f"{len(buckets['not_correlated'])} not correlated, {len(buckets['unclassified'])} unclassified"
        )
        for title, key in (("Exploitable", "exploitable"), ("Contained", "contained"), ("Not Correlated", "not_correlated")):
            if not buckets[key]:
                continue
            lines.append(f"### {title}")
            lines.extend(f"- {item}" for item in buckets[key])
        return lines

    def build_rollup(self, coverage_store: CoverageStore) -> str:
        """FR-081: finding count by severity and by exploited status,
        findings grouped by owning component, coverage status against each
        stated goal. Entirely deterministic aggregation; no LLM needed.

        "Owning component" uses the finding's function (`symbol`) as the
        grouping key -- a proxy for this toy target's single-file
        architecture, where the security map's architecture overview isn't
        structured enough to name real sub-components.
        """
        published, by_severity, by_exploited, by_component, open_items, closed_items = self._gather(coverage_store)

        lines = ["# Evaluation Rollup", "", f"**{len(published)} confirmed finding(s) published.**", ""]

        lines.append("## By severity")
        for sev in SEVERITIES:
            lines.append(f"- {sev}: {by_severity.get(sev, 0)}")

        lines.append("")
        lines.append("## By exploited status")
        lines.append(f"- exploited: {by_exploited['exploited']}")
        lines.append(f"- not exploited: {by_exploited['not_exploited']}")

        lines.append("")
        lines.append("## By component")
        for component, rows in sorted(by_component.items()):
            classes = ", ".join(r["vulnerability_class"] for r in rows)
            lines.append(f"- {component}: {len(rows)} finding(s) ({classes})")

        lines.append("")
        lines.append("## Coverage status")
        lines.append(f"- {len(closed_items)} goal(s) credibly attempted and closed, {len(open_items)} still open")
        for r in closed_items:
            lines.append(f"  - closed: {r['area']} / {r['goal']}")
        for r in open_items:
            lines.append(f"  - open: {r['area']} / {r['goal']}")

        rollup_text = "\n".join(lines)
        rollup_path = self._output_dir / "rollup.md"
        rollup_path.write_text(rollup_text, encoding="utf-8")
        return rollup_text

    async def build_ciso_report(
        self,
        coverage_store: CoverageStore,
        model: str | Any | None = None,
        stop_reason: str = "",
        exploitability_store: Any | None = None,
    ) -> str:
        """The downloadable CISO-ready report (Phase 5): the same facts
        `build_rollup` aggregates, restructured severity-first with an
        LLM-authored executive summary on top (real model call, a
        deterministic paragraph underneath as a fallback -- see
        `foundry.reporter.executive_summary`) and a deterministic
        remediation-priority ordering. Everything except the executive
        summary paragraph is exactly as mechanically derivable as
        `build_rollup`'s own output; only that one paragraph ever touches
        an LLM, and FR-083's denylist scan is checked before it's ever
        included (see `build_executive_summary`).

        `exploitability_store` (Phase 8, `foundry.cloud.exploitability.
        ExploitabilityStore`, typed `Any` here to avoid this module
        depending on `foundry.cloud` for a type hint alone) is optional
        and backward compatible -- omitted, the report looks exactly like
        Phase 5's. Given, each published finding's exploitable/contained/
        not_correlated classification (if one was ever recorded) is
        surfaced in its own section, exploitable findings first with
        their evidence, so a reader doesn't have to guess which findings
        actually matter in this specific deployment.
        """
        published, by_severity, by_exploited, by_component, open_items, closed_items = self._gather(coverage_store)
        total_goals = len(open_items) + len(closed_items)

        facts = RollupFacts(
            total_findings=len(published),
            by_severity=dict(by_severity),
            exploited_count=by_exploited["exploited"],
            not_exploited_count=by_exploited["not_exploited"],
            component_count=len(by_component),
            closed_goal_count=len(closed_items),
            open_goal_count=len(open_items),
            stop_reason=stop_reason or "not recorded",
        )
        summary = await build_executive_summary(facts, model)

        lines = ["# CISO Security Assessment Report", "", "## Executive Summary", "", summary, ""]

        lines.append("## Key Findings by Severity")
        any_findings = False
        for sev in SEVERITIES:
            count = by_severity.get(sev, 0)
            if not count:
                continue
            any_findings = True
            classes = sorted({r["vulnerability_class"] for rows in by_component.values() for r in rows if r["severity"] == sev})
            lines.append(f"- **{sev}** ({count}): {', '.join(classes)}")
        if not any_findings:
            lines.append("- No confirmed findings were published.")

        if exploitability_store is not None:
            lines.append("")
            lines.extend(self._exploitability_section(published, exploitability_store))

        lines.append("")
        lines.append("## Remediation Priorities")
        priority = 0
        for sev in SEVERITIES:
            components = sorted(c for c, rows in by_component.items() if any(r["severity"] == sev for r in rows))
            if not components:
                continue
            priority += 1
            lines.append(f"{priority}. **{sev}** -- {', '.join(components)}")
        if priority == 0:
            lines.append("- No remediation items -- no confirmed findings were published.")

        lines.append("")
        lines.append("## Coverage & Scope")
        lines.append(
            f"- {len(closed_items)} of {total_goals} stated goal(s) credibly attempted and closed"
            + (f", {len(open_items)} still open." if open_items else ".")
        )
        lines.append(f"- {len(by_component)} component(s) with at least one confirmed finding.")

        lines.append("")
        lines.append("## By Component")
        for component, rows in sorted(by_component.items()):
            classes = ", ".join(r["vulnerability_class"] for r in rows)
            lines.append(f"- {component}: {len(rows)} finding(s) ({classes})")

        lines.append("")
        lines.append("## Coverage Detail")
        for r in closed_items:
            lines.append(f"- closed: {r['area']} / {r['goal']}")
        for r in open_items:
            lines.append(f"- open: {r['area']} / {r['goal']}")

        report_text = "\n".join(lines)
        report_path = self._output_dir / "ciso_report.md"
        report_path.write_text(report_text, encoding="utf-8")
        return report_text
