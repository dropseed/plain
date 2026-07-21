"""Dev-side database policy on top of a reachable Postgres server.

The SQL lives in `plain.postgres.databases`. What lives here is everything that
is dev's opinion rather than Postgres' mechanism: what metadata a dev database
carries, and how to fork one without disrupting whoever is using the source.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .backends import Server
from .identity import current_branch

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
    is_test: bool = False

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

    def record_created(
        self,
        name: str,
        *,
        checkout: str | None,
        created_via: str,
        project_root: Path,
    ) -> None:
        """Stamp a database with who made it, how, and on which branch.

        The one place the metadata schema is spelled out — every creation path
        (create, fork, reset, ensure, guard) records the same three facts.
        """
        self.set_metadata(
            name,
            {
                "checkout": checkout,
                "branch": current_branch(project_root),
                "created_via": created_via,
            },
        )

    def update_metadata(self, name: str, **changes: Any) -> None:
        metadata = self.get_metadata(name) or {}
        metadata.update(changes)
        self.set_metadata(name, metadata)

    def list_databases(self, project_name: str) -> list[DevDatabase]:
        """Every database in this project, however it got its name.

        Name prefix alone isn't enough: `plain db fork scratch` produces a
        perfectly real database that doesn't start with the project name, and a
        database you can't see is one you can't drop. So a database counts as
        ours if it carries our metadata *or* it's named the way we name them.

        Test databases (`test_{project}` / `test_{project}_{checkout}`) count
        too, even though they carry no metadata. They're dropped on normal exit,
        so one that exists at rest is usually debris from a crashed run — and
        invisible debris is unreclaimable debris.

        Going the other way — listing everything on the cluster — is wrong for
        the local backend, where one server holds databases we never created.
        """
        from plain.postgres.databases import list_databases

        databases = []
        for info in list_databases(self.config):
            metadata = _decode_metadata(info.comment) or {}
            ours = "created_via" in metadata
            named_like_ours = info.name == project_name or info.name.startswith(
                f"{project_name}_"
            )
            is_test = info.name == f"test_{project_name}" or info.name.startswith(
                f"test_{project_name}_"
            )
            if not (ours or named_like_ours or is_test):
                continue
            databases.append(
                DevDatabase(
                    name=info.name,
                    checkout=metadata.get("checkout"),
                    branch=metadata.get("branch"),
                    created_via=metadata.get("created_via"),
                    size_bytes=info.size_bytes,
                    is_test=is_test,
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
          once it drains; if it won't drain in time, fall back to dump-restore
        """
        from plain.postgres.databases import terminate_connections

        busy = self.connection_count(source) > 0
        if busy and force:
            terminate_connections(self.config, name=source)
            # pg_terminate_backend only signals; backends exit asynchronously,
            # and a running `plain dev` pool may reconnect. Wait briefly for it
            # to drain — if it doesn't, the dump-restore path below handles a
            # busy source anyway.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and self.connection_count(source) > 0:
                time.sleep(0.1)
            busy = self.connection_count(source) > 0

        if not busy:
            self.create_database(dest, template=source)
            return "template"

        self.create_database(dest)
        try:
            self._dump_restore(source, dest)
        except Exception:
            self.drop_database(dest)  # don't strand a half-copied database
            raise
        return "dump-restore"

    def _dump_restore(self, source: str, dest: str) -> None:
        """Logical copy, streaming the dump straight into the restore.

        Two processes joined by a real pipe, both exit codes checked: a
        `pg_dump` that dies mid-stream would otherwise be masked by
        `pg_restore`'s status, and `--exit-on-error` stops `pg_restore` from
        finishing "successfully" over a truncated dump. Run where the server's
        own binaries live so tool and server versions match — see
        `Server.server_command`.
        """
        server = self.server
        user = server.user
        port = str(server.internal_port)
        dump_argv, dump_env = server.server_command(
            "pg_dump", "-U", user, "-h", "127.0.0.1", "-p", port, "-Fc", source
        )
        restore_argv, restore_env = server.server_command(
            "pg_restore",
            "-U",
            user,
            "-h",
            "127.0.0.1",
            "-p",
            port,
            "--no-owner",
            "--exit-on-error",
            "-d",
            dest,
            stdin=True,
        )

        # pg_dump's stdout is the binary custom-format dump, so it must not be
        # decoded — only stderr is text here.
        dump = subprocess.Popen(
            dump_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dump_env
        )
        assert dump.stdout is not None
        assert dump.stderr is not None
        restore = subprocess.run(
            restore_argv,
            stdin=dump.stdout,
            capture_output=True,
            text=True,
            env=restore_env,
        )
        dump.stdout.close()  # let pg_dump see EOF/SIGPIPE if restore exited early
        dump_stderr = dump.stderr.read().decode(errors="replace")
        dump.stderr.close()
        dump_rc = dump.wait()

        if dump_rc != 0:
            raise RuntimeError(
                f"pg_dump of {source!r} failed (exit {dump_rc}): "
                f"{dump_stderr.strip()[-2000:]}"
            )
        if restore.returncode != 0:
            raise RuntimeError(
                f"pg_restore into {dest!r} failed (exit {restore.returncode}): "
                f"{restore.stderr.strip()[-2000:]}"
            )


def _decode_metadata(comment: str | None) -> dict[str, Any] | None:
    if not comment:
        return None
    try:
        decoded = json.loads(comment)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None
