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

from foundry.coverage.store import CoverageStore
from foundry.reporter.classification import find_forbidden_mentions
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

    def build_rollup(self, coverage_store: CoverageStore) -> str:
        """FR-081: finding count by severity and by exploited status,
        findings grouped by owning component, coverage status against each
        stated goal. Entirely deterministic aggregation; no LLM needed.

        "Owning component" uses the finding's function (`symbol`) as the
        grouping key -- a proxy for this toy target's single-file
        architecture, where the security map's architecture overview isn't
        structured enough to name real sub-components.
        """
        with lock_for(self._conn):
            published = self._conn.execute(
                """
                SELECT f.symbol, f.vulnerability_class, f.exploited, r.severity
                FROM findings f JOIN finding_reports r ON f.fingerprint = r.finding_fingerprint
                ORDER BY f.symbol
                """
            ).fetchall()

        lines = ["# Evaluation Rollup", "", f"**{len(published)} confirmed finding(s) published.**", ""]

        by_severity: dict[str, int] = {}
        by_exploited = {"exploited": 0, "not_exploited": 0}
        by_component: dict[str, list[sqlite3.Row]] = {}
        for r in published:
            by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1
            by_exploited["exploited" if r["exploited"] else "not_exploited"] += 1
            by_component.setdefault(r["symbol"], []).append(r)

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
        open_items = coverage_store.open_items()
        closed_items = coverage_store.closed_items()
        lines.append(f"- {len(closed_items)} goal(s) credibly attempted and closed, {len(open_items)} still open")
        for r in closed_items:
            lines.append(f"  - closed: {r['area']} / {r['goal']}")
        for r in open_items:
            lines.append(f"  - open: {r['area']} / {r['goal']}")

        rollup_text = "\n".join(lines)
        rollup_path = self._output_dir / "rollup.md"
        rollup_path.write_text(rollup_text, encoding="utf-8")
        return rollup_text
