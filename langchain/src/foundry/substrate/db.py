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
