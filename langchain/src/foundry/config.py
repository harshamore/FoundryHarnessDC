"""Runtime configuration for the Foundry harness.

Deliberately minimal in this phase: no LLM provider wiring yet (that lands
with the Indexer notebook, notebook 02). Only what the substrate itself
needs to run standalone, with no OpenAI calls.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: Path = REPO_ROOT / "data" / "foundry.sqlite3"
    codeguard_rules_dir: Path = REPO_ROOT / "data" / "codeguard" / "rules"
    heartbeat_lease_seconds: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=Path(os.environ.get("FOUNDRY_DB_PATH") or cls.db_path),
            heartbeat_lease_seconds=int(
                os.environ.get("FOUNDRY_LEASE_SECONDS") or cls.heartbeat_lease_seconds
            ),
        )


SETTINGS = Settings.from_env()
