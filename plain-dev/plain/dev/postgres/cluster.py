"""Dev-side database policy on top of a reachable Postgres server.

The SQL lives in `plain.postgres.databases`. What lives here is everything that
is dev's opinion rather than Postgres' mechanism: what metadata a dev database
carries, and how to fork one without disrupting whoever is using the source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .backends import Server

if TYPE_CHECKING:
    from plain.postgres.database_url import DatabaseConfig


@dataclass(frozen=True)
class DevDatabase:
    """A database in the project's cluster, with its dev metadata."""

    name: str
    checkout: str | None
    branch: str | None
    created_via: str | None
    size_bytes: int

    @property
    def checkout_exists(self) -> bool:
        return self.checkout is not None and Path(self.checkout).exists()


@dataclass(frozen=True)
class Cluster:
    """The project's Postgres server, as dev sees it."""

    server: Server

    def url(self, db_name: str) -> str:
        return self.server.url(db_name)

    @property
    def config(self) -> DatabaseConfig:
        from plain.postgres.database_url import parse_database_url

        return parse_database_url(self.url("postgres"))

    # -- lifecycle ---------------------------------------------------------

    def database_exists(self, name: str) -> bool:
        from plain.postgres.databases import database_exists

        return database_exists(self.config, name=name)

    def connection_count(self, name: str) -> int:
        from plain.postgres.databases import connection_count

        return connection_count(self.config, name=name)

    def create_database(self, name: str, *, template: str | None = None) -> None:
        from plain.postgres.databases import create_database

        create_database(self.config, name=name, template=template)

    def drop_database(self, name: str) -> None:
        from plain.postgres.databases import drop_database

        drop_database(self.config, name=name, force=True)

    # -- metadata ----------------------------------------------------------

    def set_metadata(self, name: str, metadata: dict[str, Any]) -> None:
        """Stamp dev metadata onto the database itself.

        Postgres stores this cluster-wide in `pg_shdescription`, which is why
        there's no registry file: the metadata travels with the database, can't
        drift from the real database list, and disappears when it's dropped.
        """
        from plain.postgres.databases import set_database_comment

        set_database_comment(self.config, name=name, comment=json.dumps(metadata))

    def get_metadata(self, name: str) -> dict[str, Any] | None:
        from plain.postgres.databases import get_database_comment

        return _decode_metadata(get_database_comment(self.config, name=name))

    def update_metadata(self, name: str, **changes: Any) -> None:
        metadata = self.get_metadata(name) or {}
        metadata.update(changes)
        self.set_metadata(name, metadata)

    def list_databases(self, prefix: str) -> list[DevDatabase]:
        from plain.postgres.databases import list_databases

        databases = []
        for info in list_databases(self.config, prefix=prefix):
            metadata = _decode_metadata(info.comment) or {}
            databases.append(
                DevDatabase(
                    name=info.name,
                    checkout=metadata.get("checkout"),
                    branch=metadata.get("branch"),
                    created_via=metadata.get("created_via"),
                    size_bytes=info.size_bytes,
                )
            )
        return databases

    # -- forking -----------------------------------------------------------

    def fork_database(self, source: str, dest: str, *, force: bool = False) -> str:
        """Copy `source` to `dest` with its data. Returns the mechanism used.

        `CREATE DATABASE … TEMPLATE` is a file-level copy — near-instant at any
        data size — but Postgres refuses it while anything else is connected to
        the source. In the agentic case the source main is often running its own
        `plain dev`, so we pick by whether it's actually busy rather than
        forcing everyone off it:

        - idle source  → TEMPLATE
        - busy source  → `pg_dump | pg_restore`, which takes an MVCC snapshot
          and never blocks the source
        - `force`      → terminate the source's connections and use TEMPLATE
        """
        from plain.postgres.databases import terminate_connections

        busy = self.connection_count(source) > 0
        if busy and force:
            terminate_connections(self.config, name=source)
            busy = False

        if not busy:
            self.create_database(dest, template=source)
            return "template"

        self.create_database(dest)
        self._dump_restore(source, dest)
        return "dump-restore"

    def _dump_restore(self, source: str, dest: str) -> None:
        """Logical copy, streaming the dump straight into the restore.

        Run where the server's own binaries live so tool and server versions
        always match — see `Server.run_server_shell`.
        """
        user = self.server.user
        port = self.server.internal_port
        self.server.run_server_shell(
            f"pg_dump -U {user} -h 127.0.0.1 -p {port} -Fc {source} | "
            f"pg_restore -U {user} -h 127.0.0.1 -p {port} --no-owner -d {dest}"
        )


def _decode_metadata(comment: str | None) -> dict[str, Any] | None:
    if not comment:
        return None
    try:
        decoded = json.loads(comment)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None
