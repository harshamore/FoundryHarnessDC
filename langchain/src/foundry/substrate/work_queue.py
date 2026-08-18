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

from foundry.substrate.db import lock_for


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
        with lock_for(self._conn):
            cur = self._conn.execute(
                "INSERT INTO work_queue (task_type, payload) VALUES (?, ?)",
                (task_type, json.dumps(payload)),
            )
            return cur.lastrowid

    def claim_next(
        self,
        worker_id: str,
        task_type: str | None = None,
        task_type_prefix: str | None = None,
    ) -> Task | None:
        """Atomically claim one pending-or-lease-expired task.

        `task_type` matches exactly; `task_type_prefix` matches any task
        type starting with the given string (e.g. Coverage-Guide's
        directed-detection tasks are each queued with a distinct
        `task_type` encoding their specific area and goal --
        `"directed_detection:{area}:{goal}"` -- so a consumer that wants
        "any directed-detection task, whichever" claims by prefix
        `"directed_detection:"` rather than knowing the exact type up
        front). Passing both is not supported; `task_type` wins if both are
        given, since exact match is the more common and more precise case.

        Locked per-connection (see `foundry.substrate.db.lock_for`): two
        separate WorkQueue instances on two separate connections (the
        normal multi-agent-process shape, and what
        tests/test_finding_store.py::test_concurrent_claims_never_double_claim
        exercises) still race correctly through SQLite's own transaction
        isolation, unaffected by this lock. This lock protects against two
        callers sharing the *same* connection object concurrently (e.g.
        multiple DeepAgents tool calls from one LLM turn), where even
        non-transactional concurrent access on one connection can corrupt
        cursor state, not just collide on `BEGIN IMMEDIATE`.
        """
        with lock_for(self._conn):
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
                elif task_type_prefix:
                    row = self._conn.execute(
                        """
                        SELECT id, task_type, payload FROM work_queue
                         WHERE (status = 'pending'
                                OR (status = 'claimed' AND leased_until < datetime('now')))
                           AND task_type LIKE ? ESCAPE '\\'
                         ORDER BY id LIMIT 1
                        """,
                        (task_type_prefix.replace("%", "\\%").replace("_", "\\_") + "%",),
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
        with lock_for(self._conn):
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
        with lock_for(self._conn):
            cur = self._conn.execute(
                """
                UPDATE work_queue
                   SET status = ?, claimed_by = NULL, leased_until = NULL
                 WHERE id = ? AND claimed_by = ?
                """,
                (status, task_id, worker_id),
            )
            return cur.rowcount > 0
