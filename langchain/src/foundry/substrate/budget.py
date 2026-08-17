"""Budget governor: spend tracking and the coverage-before-yield stop
condition — Constitution VI made structural.

`should_stop()` is a strict conjunction: low yield alone never halts the
fleet, and coverage-complete alone never halts it either (only a hard spend
cap can stop things before coverage is complete). Both coverage-complete AND
yield-below-threshold must hold. This phase's version is simplified (no
trailing window, no runtime cap yet) but the conjunction itself — the part
Constitution VI actually constrains — is exact.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetCaps:
    max_spend_usd: float | None = None
    yield_threshold: float = 0.0  # confirmed true-positives per USD spent


class BudgetGovernor:
    def __init__(self, conn: sqlite3.Connection, caps: BudgetCaps) -> None:
        self._conn = conn
        self._caps = caps

    def record_spend(self, amount_usd: float, note: str = "") -> None:
        self._conn.execute(
            "INSERT INTO budget_events (kind, amount, note) VALUES ('spend', ?, ?)",
            (amount_usd, note),
        )

    def total_spend(self) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM budget_events WHERE kind = 'spend'"
        ).fetchone()
        return float(row["total"])

    def trailing_yield(self) -> float:
        """Confirmed true-positives per dollar spent so far (unwindowed for now)."""
        spend = self.total_spend()
        if spend <= 0:
            return float("inf")  # no spend yet: never trips the low-yield stop
        confirmed = self._conn.execute(
            "SELECT COUNT(*) AS n FROM findings WHERE verdict = 'true-positive'"
        ).fetchone()["n"]
        return confirmed / spend

    def should_stop(self, coverage_complete: bool) -> tuple[bool, str]:
        """Constitution VI: coverage AND yield — never yield alone."""
        spend = self.total_spend()
        if self._caps.max_spend_usd is not None and spend >= self._caps.max_spend_usd:
            return True, f"hard spend cap reached (${spend:.2f} >= ${self._caps.max_spend_usd:.2f})"

        if not coverage_complete:
            return False, "coverage not yet complete"

        y = self.trailing_yield()
        if y < self._caps.yield_threshold:
            return True, f"coverage complete and yield ({y:.4f}) below threshold ({self._caps.yield_threshold})"

        return False, "coverage complete but yield still above threshold"
