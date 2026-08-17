"""IndexStore: persists the deterministic index and exposes the query
interface spec.md FR-022 requires: get-function-body, get-callers,
get-callees, find-symbol, full-text search.

`symbol_exists()` is the real Citation resolver for
`FindingStore.assign_verdict()`'s evidence gate (Constitution I) -- it
replaces the fake in-memory symbol table used as a stand-in in the
Substrate section, with no change to `assign_verdict()` itself.
"""
from __future__ import annotations

import sqlite3

from foundry.indexer.parser import CallEdge, FunctionDef
from foundry.substrate.db import write_lock_for


class IndexStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        """The underlying connection, shared with other substrate stores on the same DB."""
        return self._conn

    def write_index(
        self, file_path: str, functions: list[FunctionDef], call_edges: list[CallEdge]
    ) -> None:
        """Atomically replace one file's index entries (Constitution XI, FR-025/026).

        Delete-then-insert for this file's rows only, inside a single
        transaction -- a reader never observes a partially-updated index for
        that file, and re-indexing an unchanged file leaves row counts
        unchanged rather than accumulating duplicates. Locked per-connection
        (see `foundry.substrate.db.write_lock_for`) so concurrent tool calls
        sharing this connection can't collide on `BEGIN IMMEDIATE`.
        """
        with write_lock_for(self._conn):
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM functions WHERE file = ?", (file_path,))
                self._conn.execute("DELETE FROM call_edges WHERE file = ?", (file_path,))

                for fn in functions:
                    self._conn.execute(
                        """
                        INSERT INTO functions (file, name, lineno, end_lineno, source)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (fn.file, fn.name, fn.lineno, fn.end_lineno, fn.source),
                    )

                seen: set[tuple[str, str]] = set()
                for edge in call_edges:
                    key = (edge.caller, edge.callee)
                    if key in seen:
                        continue
                    seen.add(key)
                    self._conn.execute(
                        "INSERT INTO call_edges (file, caller, callee) VALUES (?, ?, ?)",
                        (file_path, edge.caller, edge.callee),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_function_body(self, name: str) -> str | None:
        row = self._conn.execute("SELECT source FROM functions WHERE name = ?", (name,)).fetchone()
        return row["source"] if row else None

    def find_symbol(self, name: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT file, name, lineno, end_lineno FROM functions WHERE name = ?", (name,)
        ).fetchone()

    def get_callers(self, name: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT caller FROM call_edges WHERE callee = ?", (name,)
        ).fetchall()
        return [r["caller"] for r in rows]

    def get_callees(self, name: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT callee FROM call_edges WHERE caller = ?", (name,)
        ).fetchall()
        return [r["callee"] for r in rows]

    def full_text_search(self, query: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT name FROM functions WHERE source LIKE ?", (f"%{query}%",)
        ).fetchall()
        return [r["name"] for r in rows]

    def list_functions(self, file: str | None = None) -> list[str]:
        if file:
            rows = self._conn.execute(
                "SELECT name FROM functions WHERE file = ? ORDER BY name", (file,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT name FROM functions ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    def symbol_exists(self, path: str, symbol: str) -> bool:
        """The real Citation resolver for Constitution I's evidence gate."""
        row = self._conn.execute(
            "SELECT 1 FROM functions WHERE file = ? AND name = ?", (path, symbol)
        ).fetchone()
        return row is not None
