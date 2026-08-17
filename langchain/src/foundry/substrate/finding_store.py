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
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Callable, Literal

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

        Returns (finding_id, fingerprint, was_new).
        """
        fp = fingerprint(normalized_path, symbol, vulnerability_class)
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
        citation that does not resolve to real code).
        """
        if verdict not in _VERDICTS:
            raise ValueError(f"unknown verdict: {verdict!r}")

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
        return self._conn.execute(
            "SELECT * FROM findings WHERE id = ?", (finding_id,)
        ).fetchone()

    def count_by_verdict(self, verdict: Verdict) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM findings WHERE verdict = ?", (verdict,)
        ).fetchone()
        return row["n"]
