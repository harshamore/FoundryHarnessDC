"""CloudResourceStore: persists parsed IaC/IAM content and exposes the
query interface Phase 7 (exposure/reachability analysis) and Phase 8
(exploitability classification) are built on -- the cloud-domain
equivalent of `foundry.indexer.store.IndexStore`, same shape
deliberately: `write_resources` deletes-then-inserts scoped to one file
inside a single transaction (Constitution XI, same as
`IndexStore.write_index`), so re-parsing an unchanged file never
accumulates duplicates and a reader never observes a partially-updated
file's rows.
"""
from __future__ import annotations

import json
import sqlite3

from foundry.cloud.models import CloudParseResult, CloudResource, Grant
from foundry.substrate.db import lock_for


class CloudResourceStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def write_resources(self, file_path: str, result: CloudParseResult) -> None:
        with lock_for(self._conn):
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM cloud_resources WHERE file = ?", (file_path,))
                self._conn.execute("DELETE FROM cloud_references WHERE file = ?", (file_path,))
                self._conn.execute("DELETE FROM cloud_grants WHERE file = ?", (file_path,))

                for r in result.resources:
                    self._conn.execute(
                        """
                        INSERT INTO cloud_resources (file, resource_type, resource_name, provider, attributes)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (r.file, r.resource_type, r.resource_name, r.provider, json.dumps(r.attributes, default=str)),
                    )

                for from_address, to_address in result.references:
                    self._conn.execute(
                        "INSERT INTO cloud_references (file, from_address, to_address) VALUES (?, ?, ?)",
                        (file_path, from_address, to_address),
                    )

                for g in result.grants:
                    self._conn.execute(
                        """
                        INSERT INTO cloud_grants (file, principal, effect, actions, resources)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (g.file, g.principal, g.effect, json.dumps(g.actions), json.dumps(g.resources)),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _row_to_resource(self, row: sqlite3.Row) -> CloudResource:
        return CloudResource(
            file=row["file"],
            resource_type=row["resource_type"],
            resource_name=row["resource_name"],
            provider=row["provider"],
            attributes=json.loads(row["attributes"]),
        )

    def list_resources(self, file: str | None = None) -> list[CloudResource]:
        with lock_for(self._conn):
            if file:
                rows = self._conn.execute(
                    "SELECT * FROM cloud_resources WHERE file = ? ORDER BY resource_type, resource_name", (file,)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM cloud_resources ORDER BY resource_type, resource_name"
                ).fetchall()
            return [self._row_to_resource(r) for r in rows]

    def get_resource(self, address: str) -> CloudResource | None:
        """`address` is `resource_type.resource_name` (`CloudResource.address`)."""
        with lock_for(self._conn):
            rows = self._conn.execute("SELECT * FROM cloud_resources").fetchall()
            for row in rows:
                if f"{row['resource_type']}.{row['resource_name']}" == address:
                    return self._row_to_resource(row)
            return None

    def list_references(self, from_address: str | None = None) -> list[tuple[str, str]]:
        with lock_for(self._conn):
            if from_address:
                rows = self._conn.execute(
                    "SELECT from_address, to_address FROM cloud_references WHERE from_address = ?", (from_address,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT from_address, to_address FROM cloud_references").fetchall()
            return [(r["from_address"], r["to_address"]) for r in rows]

    def _row_to_grant(self, row: sqlite3.Row) -> Grant:
        return Grant(
            file=row["file"],
            principal=row["principal"],
            effect=row["effect"],
            actions=json.loads(row["actions"]),
            resources=json.loads(row["resources"]),
        )

    def list_grants(self, principal: str | None = None) -> list[Grant]:
        with lock_for(self._conn):
            if principal:
                rows = self._conn.execute(
                    "SELECT * FROM cloud_grants WHERE principal = ?", (principal,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM cloud_grants").fetchall()
            return [self._row_to_grant(r) for r in rows]
