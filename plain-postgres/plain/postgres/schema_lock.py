"""One session-level advisory lock serializing schema-changing commands.

`plain postgres sync`, `plain migrations apply`, `plain postgres converge`,
and `plain postgres drop-unknown-tables` all take the same lock, so concurrent
processes (a retried migrate Job, two operators, overlapping release phases)
can't interleave schema changes.

The lock is held on a dedicated connection, separate from the connection the
DDL runs on. Session-level advisory locks aren't bound to a transaction, so
non-transactional DDL (CREATE INDEX CONCURRENTLY, VALIDATE CONSTRAINT) runs
freely on the working connection while the lock connection just sits there
holding it. If the process dies, the session closes and Postgres releases the
lock automatically — no stale-lock cleanup step.

Advisory locks are per-database, so parallel test databases and multi-tenant
clusters don't contend.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import psycopg

from plain.exceptions import ImproperlyConfigured
from plain.logs import get_framework_logger
from plain.runtime import settings

from .db import get_connection
from .sources import build_connection_params

logger = get_framework_logger()

# Guards against nested schema_lock() in the same process, which would block
# on itself until the retry budget ran out (each entry is its own database
# session, so Postgres sees two different lock requesters). Commands are
# single-threaded, so a module flag is enough.
_held_by_this_process = False

# Fixed key so every version of Plain computes the same value (mixed-version
# deploys must contend on the same lock). Derived once from the lock's name —
# zlib.crc32(b"plain/schema") — and frozen as a literal. The name identifies
# the concept, not this module, so it stays true if the code moves; any future
# Plain advisory lock should follow the same crc32(b"plain/<lock-name>")
# convention. Debuggable directly:
#   SELECT * FROM pg_locks WHERE locktype = 'advisory' AND objid = 1047265496
SCHEMA_LOCK_KEY = 1047265496


class SchemaLockTimeout(Exception):
    """The schema advisory lock couldn't be acquired within the retry budget."""


class SchemaLockLost(Exception):
    """The lock session died mid-hold, so the lock may now be held elsewhere."""


@contextmanager
def schema_lock() -> Iterator[Callable[[], None]]:
    """Hold the schema advisory lock for the duration of the block.

    Acquisition is non-blocking with retry (`pg_try_advisory_lock`), so a
    dead lock holder surfaces as a clear timeout instead of hanging forever.
    Retry behavior is controlled by `POSTGRES_SCHEMA_LOCK_RETRY_INTERVAL` and
    `POSTGRES_SCHEMA_LOCK_MAX_RETRIES`.

    Yields a verify callable: it raises `SchemaLockLost` if the lock session
    has died (the lock releases with it, so another process may now hold it).
    Multi-phase callers check it between phases — losing the lock mid-phase
    is left to the environment guidance in the README (keepalives are enabled;
    don't set `idle_session_timeout` on the management role).

    Not reentrant: a nested `schema_lock()` raises immediately (it would open
    a second session and block on the outer one). Commands take the lock once,
    at the top.
    """
    global _held_by_this_process
    if _held_by_this_process:
        raise RuntimeError(
            "Schema lock is already held by this process — schema_lock() is "
            "not reentrant. Take the lock once, at the top of the command."
        )

    config = get_connection().settings_dict
    params = build_connection_params(config)
    # The lock connection sits idle while DDL runs elsewhere — TCP keepalives
    # stop NAT/LB idle timeouts from silently killing it (and the lock with it).
    params["keepalives"] = 1
    params["keepalives_idle"] = 30
    params["keepalives_interval"] = 10
    params["keepalives_count"] = 3

    retry_interval: float = settings.POSTGRES_SCHEMA_LOCK_RETRY_INTERVAL
    max_retries: int = settings.POSTGRES_SCHEMA_LOCK_MAX_RETRIES
    if retry_interval <= 0:
        raise ImproperlyConfigured(
            "POSTGRES_SCHEMA_LOCK_RETRY_INTERVAL must be greater than 0 "
            f"(got {retry_interval!r})."
        )
    # Warn immediately, then re-warn about once a minute so a long wait
    # reads as "still waiting" in deploy logs, not a hang.
    warn_every = max(1, round(60 / retry_interval))

    with psycopg.connect(**params, autocommit=True) as lock_conn:
        attempts = 0
        while True:
            row = lock_conn.execute(
                "SELECT pg_try_advisory_lock(%s)", [SCHEMA_LOCK_KEY]
            ).fetchone()
            assert row is not None
            if row[0]:
                break

            attempts += 1
            # Sleeps happen after this counter bumps, so the elapsed wait is
            # one interval behind the attempt count.
            waited_seconds = round((attempts - 1) * retry_interval)
            if attempts == 1 or attempts % warn_every == 0:
                logger.warning(
                    "Waiting for schema lock held by another process",
                    extra={
                        "context": {
                            "holder": _describe_holder(lock_conn),
                            "waited_seconds": waited_seconds,
                        }
                    },
                )
            if attempts >= max_retries:
                raise SchemaLockTimeout(
                    f"Could not acquire the schema lock after {attempts} attempt(s) "
                    f"({waited_seconds}s). Another process is running schema "
                    f"changes: {_describe_holder(lock_conn)}. If that process "
                    "is gone, its lock releases when its database session closes."
                )
            time.sleep(retry_interval)

        def verify() -> None:
            """Raise SchemaLockLost if the lock session is no longer alive."""
            try:
                lock_conn.execute("SELECT 1")
            except psycopg.Error as e:
                raise SchemaLockLost(
                    "The schema lock session died while work was running, so "
                    "the lock has been released and another process may now be "
                    "making schema changes. Stopping here — re-run the command."
                ) from e

        _held_by_this_process = True
        try:
            yield verify
        finally:
            _held_by_this_process = False
            # No explicit pg_advisory_unlock: closing the session (the
            # `with psycopg.connect(...)` exit below) releases the lock, and
            # an unlock attempt on a connection that died mid-block would
            # raise here and mask the block's real exception.


def _describe_holder(lock_conn: psycopg.Connection) -> str:
    """Best-effort description of the session currently holding the lock."""
    # A bigint advisory key shows up in pg_locks split across classid
    # (high half) and objid (low half), with objsubid = 1.
    row = lock_conn.execute(
        """
        SELECT l.pid, a.application_name, a.usename, a.query_start
        FROM pg_locks l
        LEFT JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.locktype = 'advisory'
          AND l.classid = %s
          AND l.objid = %s
          AND l.objsubid = 1
          AND l.granted
          AND l.database = (
            SELECT oid FROM pg_database WHERE datname = current_database()
          )
        LIMIT 1
        """,
        [SCHEMA_LOCK_KEY >> 32, SCHEMA_LOCK_KEY & 0xFFFFFFFF],
    ).fetchone()

    if row is None:
        return "no holder found (it may have just released)"

    pid, application_name, usename, query_start = row
    details = [f"pid={pid}"]
    if application_name:
        details.append(f"application={application_name}")
    if usename:
        details.append(f"user={usename}")
    if query_start:
        details.append(f"since={query_start:%Y-%m-%d %H:%M:%S}")
    return ", ".join(details)
