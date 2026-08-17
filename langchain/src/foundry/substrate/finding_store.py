"""Finding Lifecycle: Fingerprint, Citation, Finding — Constitution I & VIII
made structural rather than aspirational.

- `fingerprint()` is computed from (normalized_path, symbol,
  vulnerability_class) only — never a line number or code snippet — so an
  unrelated edit nearby does not re-file an existing finding as new
  (spec.md FR-090, Constitution VIII).
- `FindingStore.assign_verdict()` will not accept `true-positive` unless
  every citation resolves against the caller-supplied `resolver`. A citation
  that fails to resolve demotes the verdict to `needs-review` regardless of
  how the caller labeled it (spec.md FR-052/FR-088, Constitution I) — the
  gate is enforced by this code, not by asking the model to be careful.

`resolver` is injected rather than bound to a specific Indexer
implementation: this phase's tests exercise it with a fake in-memory symbol
table; the real Indexer (built in notebook 02) supplies the real one without
any change to this module.

Every method here takes `foundry.substrate.db.lock_for(self._conn)` around
its whole body -- not just the transactional write in `queue_candidate()`.
Python's sqlite3.Connection isn't safe for truly concurrent access from
multiple threads even for plain reads, and DeepAgents can dispatch several
tool calls from one LLM turn on real threads against this same connection.
The lock is reentrant, so a `resolver` callback that itself touches this
same connection (e.g. `IndexStore.symbol_exists`) nests without deadlock.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Callable, Literal

from foundry.substrate.db import lock_for

Verdict = Literal[
    "true-positive", "false-positive", "needs-review", "not-applicable", "code-quality"
]

_VERDICTS: tuple[Verdict, ...] = (
    "true-positive",
    "false-positive",
    "needs-review",
    "not-applicable",
    "code-quality",
)


@dataclass(frozen=True)
class Citation:
    path: str
    symbol: str
    claim: str  # what this citation is meant to establish, e.g. "reachability"


Resolver = Callable[[Citation], bool]


def fingerprint(normalized_path: str, symbol: str, vulnerability_class: str) -> str:
    """Constitution VIII: identity keyed on structure, never line number or snippet."""
    key = f"{normalized_path}::{symbol}::{vulnerability_class}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class FindingStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def queue_candidate(
        self,
        *,
        normalized_path: str,
        symbol: str,
        vulnerability_class: str,
        description: str,
        technique: str,
    ) -> tuple[int, str, bool]:
        """Insert a candidate finding, deduplicating by fingerprint (FR-045).

        Returns (finding_id, fingerprint, was_new). The dedup check and the
        insert both happen under this connection's lock -- concurrent tool
        calls sharing one connection would otherwise race between the
        SELECT and the INSERT.
        """
        fp = fingerprint(normalized_path, symbol, vulnerability_class)

        with lock_for(self._conn):
            existing = self._conn.execute(
                "SELECT id FROM findings WHERE fingerprint = ?", (fp,)
            ).fetchone()
            if existing:
                return existing["id"], fp, False

            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    """
                    INSERT INTO findings
                        (fingerprint, normalized_path, symbol, vulnerability_class,
                         description, technique)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (fp, normalized_path, symbol, vulnerability_class, description, technique),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return cur.lastrowid, fp, True

    def assign_verdict(
        self,
        finding_id: int,
        verdict: Verdict,
        citations: list[Citation],
        investigation_report: str,
        resolver: Resolver,
    ) -> Verdict:
        """Constitution I: `true-positive` requires every citation to resolve.

        Mirrors spec.md FR-052 (evidence gate) and FR-088 (auto-demotion on a
        citation that does not resolve to real code). FR-054: "A verdict
        without an investigation report MUST be rejected by the finding
        store" -- a bare label is an unverifiable model assertion; the
        reasoning is what a reviewer audits, the label is just an index
        into it.
        """
        if verdict not in _VERDICTS:
            raise ValueError(f"unknown verdict: {verdict!r}")
        if not investigation_report or not investigation_report.strip():
            raise ValueError(
                "assign_verdict requires a non-empty investigation_report (FR-054)"
            )

        with lock_for(self._conn):
            final_verdict: Verdict = verdict
            report = investigation_report

            if verdict == "true-positive":
                unresolved = [c for c in citations if not resolver(c)]
                if not citations or unresolved:
                    final_verdict = "needs-review"
                    bad = [f"{c.path}:{c.symbol}" for c in unresolved]
                    report = (
                        f"{investigation_report}\n\n"
                        f"[evidence-gate] demoted from true-positive: "
                        f"{len(unresolved)} of {len(citations)} citation(s) did not resolve: {bad}"
                    )

            self._conn.execute(
                """
                UPDATE findings
                   SET verdict = ?, investigation_report = ?, updated_at = datetime('now')
                 WHERE id = ?
                """,
                (final_verdict, report, finding_id),
            )
            return final_verdict

    def get(self, finding_id: int) -> sqlite3.Row | None:
        with lock_for(self._conn):
            return self._conn.execute(
                "SELECT * FROM findings WHERE id = ?", (finding_id,)
            ).fetchone()

    def list_untriaged(self) -> list[sqlite3.Row]:
        """Every candidate the Detector queued that no verdict has been
        assigned to yet -- what a Triager works through (spec.md §5.5)."""
        with lock_for(self._conn):
            return self._conn.execute(
                "SELECT * FROM findings WHERE verdict IS NULL ORDER BY id"
            ).fetchall()

    def count_by_verdict(self, verdict: Verdict) -> int:
        with lock_for(self._conn):
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM findings WHERE verdict = ?", (verdict,)
            ).fetchone()
            return row["n"]

    def record_rule_gap(self, finding_fingerprint: str, vulnerability_class: str, pattern: str) -> None:
        """FR-042: when the Detector's exploratory hunting confirms a
        finding no CodeGuard rule would have produced, record the gap --
        the input to growing the rule corpus (spec.md §5.4's rule-gap loop,
        Constitution's detection-compounds-into-prevention argument)."""
        with lock_for(self._conn):
            self._conn.execute(
                "INSERT INTO rule_gaps (finding_fingerprint, vulnerability_class, pattern) VALUES (?, ?, ?)",
                (finding_fingerprint, vulnerability_class, pattern),
            )

    def list_rule_gaps(self) -> list[sqlite3.Row]:
        with lock_for(self._conn):
            return self._conn.execute("SELECT * FROM rule_gaps ORDER BY id").fetchall()
