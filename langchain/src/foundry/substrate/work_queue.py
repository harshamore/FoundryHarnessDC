"""Atomic, mortal work claims — Constitution III & IV made structural.

Liveness is heartbeat-based: a claim is reclaimable only once its lease has
expired (`leased_until` in the past), never on a wall-clock agent-runtime
timeout (Constitution III). `claim_next()` selects and updates inside one
`BEGIN IMMEDIATE` transaction, re-checking the same WHERE clause on the
UPDATE, so two callers racing for the same row cannot both win
(Constitution IV) — proved by a concurrent-thread test in
tests/test_finding_store.py, not just asserted here.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: int
    task_type: str
    payload: dict


class WorkQueue:
    def __init__(self, conn: sqlite3.Connection, lease_seconds: int = 60) -> None:
        self._conn = conn
        self._lease_seconds = lease_seconds

    def enqueue(self, task_type: str, payload: dict) -> int:
        cur = self._conn.execute(
            "INSERT INTO work_queue (task_type, payload) VALUES (?, ?)",
            (task_type, json.dumps(payload)),
        )
        return cur.lastrowid

    def claim_next(self, worker_id: str, task_type: str | None = None) -> Task | None:
        """Atomically claim one pending-or-lease-expired task."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if task_type:
                row = self._conn.execute(
                    """
                    SELECT id, task_type, payload FROM work_queue
                     WHERE (status = 'pending'
                            OR (status = 'claimed' AND leased_until < datetime('now')))
                       AND task_type = ?
                     ORDER BY id LIMIT 1
                    """,
                    (task_type,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    """
                    SELECT id, task_type, payload FROM work_queue
                     WHERE (status = 'pending'
                            OR (status = 'claimed' AND leased_until < datetime('now')))
                     ORDER BY id LIMIT 1
                    """
                ).fetchone()

            if row is None:
                self._conn.execute("COMMIT")
                return None

            self._conn.execute(
                """
                UPDATE work_queue
                   SET status = 'claimed',
                       claimed_by = ?,
                       leased_until = datetime('now', ?),
                       attempts = attempts + 1
                 WHERE id = ?
                   AND (status = 'pending'
                        OR (status = 'claimed' AND leased_until < datetime('now')))
                """,
                (worker_id, f"+{self._lease_seconds} seconds", row["id"]),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return Task(id=row["id"], task_type=row["task_type"], payload=json.loads(row["payload"]))

    def heartbeat(self, task_id: int, worker_id: str) -> bool:
        cur = self._conn.execute(
            """
            UPDATE work_queue
               SET leased_until = datetime('now', ?)
             WHERE id = ? AND claimed_by = ? AND status = 'claimed'
            """,
            (f"+{self._lease_seconds} seconds", task_id, worker_id),
        )
        return cur.rowcount > 0

    def release(self, task_id: int, worker_id: str, status: str = "done") -> bool:
        cur = self._conn.execute(
            """
            UPDATE work_queue
               SET status = ?, claimed_by = NULL, leased_until = NULL
             WHERE id = ? AND claimed_by = ?
            """,
            (status, task_id, worker_id),
        )
        return cur.rowcount > 0
