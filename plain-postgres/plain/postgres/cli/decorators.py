from __future__ import annotations

import functools
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import click
import psycopg

from plain.runtime import settings

from ..connection import DatabaseConnection
from ..db import get_connection, use_management_connection
from ..readiness import (
    ReadinessStatus,
    _classify_connection_failure,
    _with_connect_timeout,
)
from ..schema_lock import SchemaLockLost, SchemaLockTimeout, schema_lock
from ..sources import DirectSource


@contextmanager
def cli_schema_lock() -> Iterator[Callable[[], None]]:
    """`schema_lock()` for CLI commands: a timeout or lost lock surfaces as a
    clean one-line error instead of a traceback burying it. Yields the lock's
    verify callable for multi-phase commands to check between phases."""
    try:
        with schema_lock() as verify:
            yield verify
    except (SchemaLockTimeout, SchemaLockLost) as e:
        raise click.ClickException(str(e)) from e


_WAIT_RETRY_INTERVAL_SECONDS = 2.0


def cli_wait_for_database() -> None:
    """Wait for the command's database to accept connections.

    Schema commands call this first so a database that's still starting
    (a deploy, dev services coming up, a failover) is retried for up to
    `POSTGRES_WAIT_TIMEOUT` seconds instead of failing instantly. It probes
    whatever connection the command will use — the management connection
    when one is configured. Configuration errors (bad credentials, bad URL,
    invalid options) fail immediately with a clean message; retrying can't
    fix those.
    """
    conn = get_connection()
    if conn.connection is not None:
        # Already connected (e.g. a command invoked from another command
        # that already waited) — nothing to wait for.
        return

    # Probe on a separate short-lived connection with a bounded connect
    # timeout, so an unroutable host can't hang an attempt for minutes.
    probe = DatabaseConnection(DirectSource(_with_connect_timeout(conn.settings_dict)))
    deadline = time.monotonic() + settings.POSTGRES_WAIT_TIMEOUT
    attempts = 0

    try:
        while True:
            try:
                probe.ensure_connection()
                return
            except psycopg.OperationalError as e:
                if _classify_connection_failure(e) is ReadinessStatus.CONFIG_ERROR:
                    raise click.ClickException(str(e).strip()) from e
                # `or` fallback: an empty error message would otherwise crash
                # the progress line's splitlines()[0].
                error = str(e).strip() or "connection error"
            except psycopg.ProgrammingError as e:
                # An invalid connection option in the URL — config-shaped.
                raise click.ClickException(str(e).strip()) from e

            attempts += 1
            if time.monotonic() >= deadline:
                raise click.ClickException(
                    f"Database not reachable after {attempts} attempt(s) "
                    f"(POSTGRES_WAIT_TIMEOUT={settings.POSTGRES_WAIT_TIMEOUT:g}):\n"
                    f"{error}"
                )
            # Progress goes to stderr so wrappers that capture stdout (like
            # plain-dev's sync --check) still stream the waiting lines live.
            click.secho(
                f"Waiting for database (attempt {attempts}): {error.splitlines()[0]}",
                fg="yellow",
                err=True,
            )
            time.sleep(
                min(_WAIT_RETRY_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic()))
            )
    finally:
        probe.close()


def database_management_command[F: Callable[..., Any]](f: F) -> F:
    """Run a click command's body through `use_management_connection()`.

    Apply to CLI commands that perform schema changes, migrations, or other
    database management operations. Inside the command, `get_connection()`
    returns a connection opened against `POSTGRES_MANAGEMENT_URL` (falling
    back to `POSTGRES_URL` when unset).
    """

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with use_management_connection():
            return f(*args, **kwargs)

    return wrapper  # ty: ignore[invalid-return-type]
