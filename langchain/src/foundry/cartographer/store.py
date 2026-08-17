"""Persists the Cartographer's security map (spec.md §5.3) and exposes it
as both individual sections and a bounded digest (FR-035) other roles can
front-load into their own prompts rather than fetching the full map via
tools.

Constitution XI (Persist Atomically): each section write replaces its row
inside a single transaction; a reader never observes a half-written
section.

Every method here takes `foundry.substrate.db.lock_for(self._conn)` around
its whole body -- not just the transactional write in `write_section()`.
Python's sqlite3.Connection isn't safe for truly concurrent access from
multiple threads even for plain reads, and the Cartographer subagent has
five independent write tools DeepAgents can dispatch concurrently from one
LLM turn, all sharing this connection.
"""
from __future__ import annotations

import sqlite3

from foundry.substrate.db import lock_for

SECTIONS = (
    "architecture_overview",
    "attack_surface",
    "trust_boundaries",
    "data_flows",
    "threat_model",
)


class SecurityMapStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        """The underlying connection, shared with other substrate stores on the same DB."""
        return self._conn

    def write_section(self, section: str, content: str, source: str) -> None:
        if section not in SECTIONS:
            raise ValueError(f"unknown security-map section: {section!r}")
        if source not in ("llm", "fallback"):
            raise ValueError(f"unknown source: {source!r}")

        with lock_for(self._conn):
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM security_map WHERE section = ?", (section,))
                self._conn.execute(
                    "INSERT INTO security_map (section, content, source) VALUES (?, ?, ?)",
                    (section, content, source),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_section(self, section: str) -> str | None:
        with lock_for(self._conn):
            row = self._conn.execute(
                "SELECT content FROM security_map WHERE section = ?", (section,)
            ).fetchone()
            return row["content"] if row else None

    def get_source(self, section: str) -> str | None:
        with lock_for(self._conn):
            row = self._conn.execute(
                "SELECT source FROM security_map WHERE section = ?", (section,)
            ).fetchone()
            return row["source"] if row else None

    def is_complete(self) -> bool:
        """FR-036a: an empty security map is a Cartographer failure, not
        graceful degradation -- every section must have *some* content,
        LLM-authored or fallback, before this returns True."""
        with lock_for(self._conn):
            rows = self._conn.execute("SELECT section FROM security_map").fetchall()
            present = {r["section"] for r in rows}
            return set(SECTIONS) <= present

    def digest(self, max_chars_per_section: int = 500) -> str:
        """FR-035: a bounded summary small enough to front-load directly
        into another role's prompt context. Locked across the whole loop
        (the lock is reentrant, so the per-section get_section() calls
        nest fine) for a consistent snapshot across all sections, not just
        each one individually."""
        with lock_for(self._conn):
            parts = []
            for section in SECTIONS:
                content = self.get_section(section)
                if not content:
                    continue
                trimmed = (
                    content
                    if len(content) <= max_chars_per_section
                    else content[:max_chars_per_section] + "…"
                )
                title = section.replace("_", " ").title()
                parts.append(f"## {title}\n{trimmed}")
            return "\n\n".join(parts)
