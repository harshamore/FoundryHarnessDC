"""Persists the Coverage-Guide's checklist and coverage log (spec.md §5.7)
and implements the mechanical review cycle: FR-067 (derive the checklist),
FR-068 (refuse to invent goals), FR-069 (check items off from evidence),
FR-070 (directed tasks for gaps), FR-071 (the coverage-complete flag),
FR-074 (persist across restarts, don't rebuild from scratch).

Deliberately has no LLM dependency for any of this. "Coverage measures
attempt, not outcome" (FR-069) is a mechanical evidence check against the
finding store and coverage log, not a judgment call -- the same way
`BudgetGovernor.should_stop()` is a mechanical conjunction, not a judgment
call. FR-072 ("MUST NOT itself detect, triage, validate, or close
work-queue tasks it queued") holds by construction here: this class has no
method that writes a finding, a verdict, or claims a work-queue task --
it can't do those things, not just "shouldn't".
"""
from __future__ import annotations

import sqlite3

from foundry.substrate.db import lock_for
from foundry.substrate.work_queue import WorkQueue


class CoverageStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        """The underlying connection, shared with other substrate stores on the same DB."""
        return self._conn

    def build_checklist(self, areas: list[str], goals: list[str], bar_template: str) -> int:
        """FR-067: derive a finite (area x goal) checklist, each item with
        a stated bar. FR-068: refuses to build anything from an empty
        areas/goals list rather than inventing a checklist. Idempotent
        (UNIQUE(area, goal)) -- matches FR-074's "do not rebuild from
        scratch on each wake": re-running with the same areas/goals leaves
        already-closed items closed, not reset to open.

        Returns the number of checklist items currently open.
        """
        if not areas or not goals:
            raise ValueError(
                "build_checklist requires non-empty areas and goals -- refusing to "
                "invent a checklist from nothing (FR-068)"
            )
        with lock_for(self._conn):
            for area in areas:
                for goal in goals:
                    self._conn.execute(
                        """
                        INSERT INTO coverage_checklist (area, goal, bar)
                        VALUES (?, ?, ?)
                        ON CONFLICT(area, goal) DO NOTHING
                        """,
                        (area, goal, bar_template.format(area=area, goal=goal)),
                    )
            return self._conn.execute(
                "SELECT COUNT(*) AS n FROM coverage_checklist WHERE status = 'open'"
            ).fetchone()["n"]

    def open_items(self) -> list[sqlite3.Row]:
        with lock_for(self._conn):
            return self._conn.execute(
                "SELECT * FROM coverage_checklist WHERE status = 'open' ORDER BY id"
            ).fetchall()

    def closed_items(self) -> list[sqlite3.Row]:
        with lock_for(self._conn):
            return self._conn.execute(
                "SELECT * FROM coverage_checklist WHERE status = 'closed' ORDER BY id"
            ).fetchall()

    def record_sweep(self, area: str, technique: str, note: str = "") -> None:
        """The coverage log: an append-only audit trail of attempts, not a
        stop-list (spec.md glossary) -- "swept X, found nothing" is
        recorded the same way as "swept X, found three things"."""
        with lock_for(self._conn):
            self._conn.execute(
                "INSERT INTO coverage_log (area, technique, note) VALUES (?, ?, ?)",
                (area, technique, note),
            )

    def evidence_for(self, area: str, goal: str) -> dict[str, int]:
        """FR-069 evidence for one checklist item: a queued finding-store
        row is evidence of an attempt regardless of verdict ("we swept X
        for Y and found nothing" satisfies "X: Y" exactly as well as
        finding three things), and so is a matching coverage-log sweep."""
        with lock_for(self._conn):
            findings = self._conn.execute(
                "SELECT COUNT(*) AS n FROM findings WHERE symbol = ? AND vulnerability_class = ?",
                (area, goal),
            ).fetchone()["n"]
            sweeps = self._conn.execute(
                "SELECT COUNT(*) AS n FROM coverage_log WHERE area = ? AND technique LIKE ?",
                (area, f"%{goal}%"),
            ).fetchone()["n"]
            return {"finding_store_rows": findings, "coverage_log_rows": sweeps}

    def review_cycle(self) -> dict[str, list[int]]:
        """FR-069: gather evidence for every open item, close what's met."""
        closed_now: list[int] = []
        with lock_for(self._conn):
            for item in self.open_items():
                ev = self.evidence_for(item["area"], item["goal"])
                if ev["finding_store_rows"] > 0 or ev["coverage_log_rows"] > 0:
                    self._conn.execute(
                        "UPDATE coverage_checklist SET status = 'closed', closed_at = datetime('now') WHERE id = ?",
                        (item["id"],),
                    )
                    closed_now.append(item["id"])
            still_open = [r["id"] for r in self.open_items()]
        return {"closed_this_cycle": closed_now, "still_open": still_open}

    def queue_directed_tasks(self, work_queue: WorkQueue) -> int:
        """FR-070: queue a directed task for every still-open checklist
        item, phrased so a Detector instance with no other context can act
        on it. Skips items that already have a pending task queued, so
        repeated review cycles don't flood the queue with duplicates --
        deduped via `task_type`, which encodes (area, goal) directly so
        the check needs no JSON parsing.
        """
        queued = 0
        for item in self.open_items():
            task_type = f"directed_detection:{item['area']}:{item['goal']}"
            with lock_for(self._conn):
                pending = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM work_queue WHERE task_type = ? AND status = 'pending'",
                    (task_type,),
                ).fetchone()["n"]
            if pending:
                continue
            work_queue.enqueue(
                task_type,
                {
                    "area": item["area"],
                    "goal": item["goal"],
                    "instruction": f"Check {item['area']} specifically for {item['goal']}. {item['bar']}",
                },
            )
            queued += 1
        return queued

    def is_complete(self) -> bool:
        """FR-071: coverage-complete only when every checklist item is
        closed -- and only if a checklist actually exists. An empty table
        is "never built", not "complete"; treating it as complete would
        let should_stop() pass a vacuous coverage flag before any
        checklist was ever derived."""
        with lock_for(self._conn):
            total = self._conn.execute("SELECT COUNT(*) AS n FROM coverage_checklist").fetchone()["n"]
            if total == 0:
                return False
            open_count = self._conn.execute(
                "SELECT COUNT(*) AS n FROM coverage_checklist WHERE status = 'open'"
            ).fetchone()["n"]
            return open_count == 0

    def clear_checklist(self) -> None:
        """FR-071: MUST clear the coverage-complete flag if the operator
        changes the goals -- implemented here by clearing the checklist
        itself, since `is_complete()` is derived from it, not stored
        separately."""
        with lock_for(self._conn):
            self._conn.execute("DELETE FROM coverage_checklist")
