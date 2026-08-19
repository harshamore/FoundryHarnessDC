"""SQLite connection helper: WAL mode, row access by name, schema creation.

Constitution XI (Persist Atomically): every write elsewhere in the substrate
goes through a transaction; nothing is ever deleted-then-rewritten.
Constitution IV (Claims Are Atomic And Mortal) depends on SQLite's own
transaction isolation for the work queue's atomic claim -- WAL mode lets
multiple connections read concurrently while a single writer's `BEGIN
IMMEDIATE` transaction serializes writes.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    normalized_path TEXT NOT NULL,
    symbol TEXT NOT NULL,
    vulnerability_class TEXT NOT NULL,
    description TEXT NOT NULL,
    technique TEXT NOT NULL,
    verdict TEXT,
    investigation_report TEXT,
    exploited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS work_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'claimed', 'done', 'blocked')),
    claimed_by TEXT,
    leased_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rule_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_fingerprint TEXT NOT NULL,
    vulnerability_class TEXT NOT NULL,
    pattern TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budget_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS functions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file TEXT NOT NULL,
    name TEXT NOT NULL,
    lineno INTEGER NOT NULL,
    end_lineno INTEGER NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(file, name)
);

CREATE TABLE IF NOT EXISTS call_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file TEXT NOT NULL,
    caller TEXT NOT NULL,
    callee TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('llm', 'fallback')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coverage_checklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT NOT NULL,
    goal TEXT NOT NULL,
    bar TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    closed_at TEXT,
    UNIQUE(area, goal)
);

CREATE TABLE IF NOT EXISTS coverage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT NOT NULL,
    technique TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS finding_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_fingerprint TEXT NOT NULL UNIQUE,
    severity TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    weakness_class TEXT,
    report_path TEXT NOT NULL,
    published_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cloud_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    attributes TEXT NOT NULL,
    UNIQUE(file, resource_type, resource_name)
);

CREATE TABLE IF NOT EXISTS cloud_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file TEXT NOT NULL,
    from_address TEXT NOT NULL,
    to_address TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cloud_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file TEXT NOT NULL,
    principal TEXT NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('Allow', 'Deny')),
    actions TEXT NOT NULL,
    resources TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


_connection_locks: dict[int, threading.RLock] = {}
_locks_guard = threading.Lock()


def lock_for(conn: sqlite3.Connection) -> threading.RLock:
    """One reentrant lock per connection, shared by every store operating
    on it, guarding EVERY access -- reads included, not just transactional
    writes.

    DeepAgents (and LangGraph's tool-calling machinery generally) can
    dispatch multiple tool calls from a single LLM turn concurrently, on
    real OS threads -- and every store built on a given `conn` shares that
    same connection object. Two failure modes were observed live, both
    fixed by the same lock:

      1. Two threads issuing `BEGIN IMMEDIATE` back to back on the same
         connection: "cannot start a transaction within a transaction".
      2. Two threads issuing plain, non-transactional `execute()` /
         `fetchall()` calls on the same connection *concurrently*, with no
         BEGIN involved at all: Python's sqlite3.Connection is not safe for
         truly simultaneous access from multiple threads even for reads --
         reproduced as `InterfaceError: bad parameter or other API misuse`
         and a nonsensical `IndexError` from `sqlite3.Row.__getitem__`.

    Every store method that touches `self._conn` -- reads and writes alike
    -- takes this lock around its entire body, not just around explicit
    transactions. It's an RLock (reentrant) because store methods
    legitimately call other locked methods on the same store (e.g.
    `SecurityMapStore.digest()` calls `get_section()` per section); a plain
    `Lock` would deadlock the thread that already holds it.

    Keyed by `id(conn)` rather than a weak reference -- `sqlite3.Connection`
    doesn't support weak references. The connections this harness creates
    live for an entire notebook/process session, so the registry never
    meaningfully grows; the only real risk is a stale lock being reused if
    a connection's id is recycled after garbage collection, which would at
    worst cause unrelated connections to serialize unnecessarily, not any
    correctness violation.
    """
    with _locks_guard:
        key = id(conn)
        lock = _connection_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _connection_locks[key] = lock
        return lock
