"""IndexStore: persists the deterministic index and exposes the query
interface spec.md FR-022 requires: get-function-body, get-callers,
get-callees, find-symbol, full-text search.

`symbol_exists()` is the real Citation resolver for
`FindingStore.assign_verdict()`'s evidence gate (Constitution I) -- it
replaces the fake in-memory symbol table used as a stand-in in the
Substrate section, with no change to `assign_verdict()` itself.

Every method here takes `foundry.substrate.db.lock_for(self._conn)` around
its whole body -- not just the transactional write in `write_index()`.
Python's sqlite3.Connection isn't safe for truly concurrent access from
multiple threads even for plain reads, and DeepAgents can dispatch several
tool calls from one LLM turn on real threads against this same connection.

The `functions` table has always been `UNIQUE(file, name)`, not
`UNIQUE(name)` -- a bare function name was never actually guaranteed
unique, it just never collided against the single-file toy target.
`get_function_body`/`find_symbol`/`get_callers`/`get_callees` now take an
optional `file` to disambiguate once more than one file is indexed;
omitting it preserves the original single-match behavior when there's no
collision, and `get_function_body` raises rather than silently guessing
when there is one. `get_callers`/`get_callees` are call-graph lookups, not
functions-table lookups: `call_edges.file` records which file's AST an
edge was extracted *from* (the caller's file), not which file the callee
is actually defined in -- resolving that would need real cross-file import
resolution, a separate, harder feature this does not attempt. Passing
`file` here filters to edges recorded while parsing that specific file,
which narrows collisions but does not fully resolve callee identity.
"""
from __future__ import annotations

import sqlite3

from foundry.indexer.parser import CallEdge, FunctionDef
from foundry.substrate.db import lock_for


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
        unchanged rather than accumulating duplicates.
        """
        with lock_for(self._conn):
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

    def get_function_body(self, name: str, file: str | None = None) -> str | None:
        """The full source of the function named `name`. If `file` is
        omitted and more than one indexed file defines a function with
        this name, raises ValueError naming the candidates rather than
        silently returning one of them -- the caller must disambiguate."""
        with lock_for(self._conn):
            if file:
                row = self._conn.execute(
                    "SELECT source FROM functions WHERE file = ? AND name = ?", (file, name)
                ).fetchone()
                return row["source"] if row else None
            rows = self._conn.execute(
                "SELECT file, source FROM functions WHERE name = ?", (name,)
            ).fetchall()
            if len(rows) > 1:
                files = ", ".join(sorted(r["file"] for r in rows))
                raise ValueError(
                    f"'{name}' is defined in more than one file ({files}) -- pass file= to disambiguate."
                )
            return rows[0]["source"] if rows else None

    def find_symbol(self, name: str, file: str | None = None) -> list[sqlite3.Row]:
        """Where a function named `name` is defined -- a discovery tool, so
        ambiguity is a valid answer, not an error: returns every matching
        (file, name, lineno, end_lineno) row, filtered to `file` if given."""
        with lock_for(self._conn):
            if file:
                rows = self._conn.execute(
                    "SELECT file, name, lineno, end_lineno FROM functions WHERE file = ? AND name = ?",
                    (file, name),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT file, name, lineno, end_lineno FROM functions WHERE name = ?", (name,)
                ).fetchall()
            return rows

    def get_callers(self, name: str, file: str | None = None) -> list[str]:
        with lock_for(self._conn):
            if file:
                rows = self._conn.execute(
                    "SELECT DISTINCT caller FROM call_edges WHERE callee = ? AND file = ?", (name, file)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT DISTINCT caller FROM call_edges WHERE callee = ?", (name,)
                ).fetchall()
            return [r["caller"] for r in rows]

    def get_callees(self, name: str, file: str | None = None) -> list[str]:
        with lock_for(self._conn):
            if file:
                rows = self._conn.execute(
                    "SELECT DISTINCT callee FROM call_edges WHERE caller = ? AND file = ?", (name, file)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT DISTINCT callee FROM call_edges WHERE caller = ?", (name,)
                ).fetchall()
            return [r["callee"] for r in rows]

    def full_text_search(self, query: str) -> list[tuple[str, str]]:
        """(file, name) pairs for every function whose source contains
        `query` -- (file, name), not bare name, so a match in two
        different files' same-named function doesn't collapse into one
        result via DISTINCT."""
        with lock_for(self._conn):
            rows = self._conn.execute(
                "SELECT DISTINCT file, name FROM functions WHERE source LIKE ?", (f"%{query}%",)
            ).fetchall()
            return [(r["file"], r["name"]) for r in rows]

    def list_functions(self, file: str | None = None) -> list[str]:
        with lock_for(self._conn):
            if file:
                rows = self._conn.execute(
                    "SELECT name FROM functions WHERE file = ? ORDER BY name", (file,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT name FROM functions ORDER BY name").fetchall()
            return [r["name"] for r in rows]

    def symbol_exists(self, path: str, symbol: str) -> bool:
        """The real Citation resolver for Constitution I's evidence gate."""
        with lock_for(self._conn):
            row = self._conn.execute(
                "SELECT 1 FROM functions WHERE file = ? AND name = ?", (path, symbol)
            ).fetchone()
            return row is not None
