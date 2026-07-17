"""Classify whether the database is ready for this application to serve.

Two checks with disjoint coverage:

1. **Unapplied migrations** — the same plan `plain postgres sync` would run.
   Catches pending data migrations that schema presence can't see.
2. **Schema satisfies models** — every model's table and concrete columns
   exist. Existence only: index/constraint/nullability drift is convergence's
   job, not a serving cliff. Catches what migration records can't — restored
   backups, rollbacks, manual damage, an empty database.

The result is a classification, not a verb. Whether a process should wait,
refuse, or serve anyway is deployment policy that belongs to the operator —
typically an entrypoint script wrapping `plain postgres ready`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import psycopg

from plain.exceptions import ImproperlyConfigured

from .connection import DatabaseConnection, get_migratable_models
from .db import _db_conn
from .fields.base import ColumnField
from .migrations.executor import MigrationExecutor
from .migrations.operations import RunPython
from .sources import DirectSource, _parse_runtime_url

if TYPE_CHECKING:
    from .database_url import DatabaseConfig


class ReadinessStatus(StrEnum):
    READY = "ready"
    PENDING_MIGRATIONS = "pending-migrations"
    SCHEMA_NOT_SATISFIED = "schema-not-satisfied"
    UNREACHABLE = "unreachable"
    CONFIG_ERROR = "config-error"


@dataclass
class ReadinessResult:
    """A readiness classification plus the facts behind it."""

    status: ReadinessStatus
    pending_migrations: list[str] = field(default_factory=list)
    pending_data_migrations: list[str] = field(default_factory=list)
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    connection_error: str | None = None

    def summary(self) -> str:
        """One-line description, suitable for a poll loop's log output."""
        match self.status:
            case ReadinessStatus.READY:
                return "ready"
            case ReadinessStatus.PENDING_MIGRATIONS:
                return f"{len(self.pending_migrations)} migration(s) pending"
            case ReadinessStatus.SCHEMA_NOT_SATISFIED:
                return (
                    f"schema missing {len(self.missing_tables)} table(s) "
                    f"and {len(self.missing_columns)} column(s)"
                )
            case _:  # UNREACHABLE / CONFIG_ERROR
                error = self.connection_error or ""
                return error.splitlines()[0] if error else str(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "summary": self.summary(),
            "pending_migrations": self.pending_migrations,
            "pending_data_migrations": self.pending_data_migrations,
            "missing_tables": self.missing_tables,
            "missing_columns": self.missing_columns,
            "connection_error": self.connection_error,
        }


def check_database_ready(conn: DatabaseConnection | None = None) -> ReadinessResult:
    """Run the readiness checks and classify the result.

    With no connection given, opens a short-lived direct connection against
    `POSTGRES_URL` — the URL the app serves through — and closes it when
    done. A direct connection (not the runtime pool) so a connection failure
    surfaces as a classifiable error instead of an opaque pool timeout.

    Pass `conn` to run the checks over an existing connection instead — an
    in-process caller that already holds one (tests, error diagnosis).

    Either way, the connection is installed as the active connection while
    the checks run, so ORM reads inside them (the migration recorder) go
    through it rather than opening the runtime pool.
    """
    owns_connection = conn is None
    if conn is None:
        try:
            conn = DatabaseConnection(
                DirectSource(_with_connect_timeout(_parse_runtime_url()))
            )
        except (ImproperlyConfigured, ValueError) as e:
            # An unusable POSTGRES_URL — unsupported scheme, bad port,
            # too-long database name — is permanent; a human must fix it.
            return ReadinessResult(
                status=ReadinessStatus.CONFIG_ERROR, connection_error=str(e)
            )

    token = _db_conn.set(conn)
    try:
        return _run_checks(conn)
    finally:
        _db_conn.reset(token)
        if owns_connection:
            conn.close()


# Without a bounded connect timeout, an unroutable host hangs a readiness
# probe for the full TCP timeout (minutes) with no output.
_CONNECT_TIMEOUT_SECONDS = 10


def _with_connect_timeout(config: DatabaseConfig) -> DatabaseConfig:
    """Copy of `config` with a bounded connect timeout for probing.

    A `connect_timeout` already present in the URL wins. Also used by
    `cli_wait_for_database()` for the schema commands' connectivity wait.
    """
    return {
        **config,
        "OPTIONS": {
            "connect_timeout": _CONNECT_TIMEOUT_SECONDS,
            **config.get("OPTIONS", {}),
        },
    }


def _run_checks(conn: DatabaseConnection) -> ReadinessResult:
    try:
        conn.ensure_connection()
    except psycopg.OperationalError as e:
        return ReadinessResult(
            status=_classify_connection_failure(e),
            connection_error=str(e).strip(),
        )
    except psycopg.ProgrammingError as e:
        # psycopg rejects an unknown connection option (a typo'd URL query
        # param) with ProgrammingError, not OperationalError. Config-shaped —
        # only caught around connect, so a ProgrammingError from the check
        # queries themselves (a bug) still propagates loudly.
        return ReadinessResult(
            status=ReadinessStatus.CONFIG_ERROR,
            connection_error=str(e).strip(),
        )

    try:
        pending, pending_data = _pending_migrations(conn)
        if pending:
            # Missing schema objects are expected while migrations are
            # pending — the pending verdict wins, so skip the schema check.
            return ReadinessResult(
                status=ReadinessStatus.PENDING_MIGRATIONS,
                pending_migrations=pending,
                pending_data_migrations=pending_data,
            )
        missing_tables, missing_columns = _missing_schema_objects(conn)
    except psycopg.errors.InsufficientPrivilege as e:
        # The role can't read something the checks need — typically SELECT
        # on plainmigrations when a runtime/management role split misses a
        # grant. A human must fix it. Kept narrow (42501, not all
        # ProgrammingError) so a bug in our own check SQL still propagates
        # loudly instead of classifying.
        return ReadinessResult(
            status=ReadinessStatus.CONFIG_ERROR,
            connection_error=str(e).strip(),
        )
    except psycopg.OperationalError as e:
        return ReadinessResult(
            status=_classify_connection_failure(e),
            connection_error=str(e).strip(),
        )

    if missing_tables or missing_columns:
        status = ReadinessStatus.SCHEMA_NOT_SATISFIED
    else:
        status = ReadinessStatus.READY

    return ReadinessResult(
        status=status,
        pending_data_migrations=pending_data,
        missing_tables=missing_tables,
        missing_columns=missing_columns,
    )


def _pending_migrations(conn: DatabaseConnection) -> tuple[list[str], list[str]]:
    """Unapplied migrations, split into (schema-affecting, data-only).

    A migration whose operations are all `RunPython` can't change the
    schema — a long backfill is legitimately pending for hours while new
    processes serve fine, so those warn instead of gate.
    """
    executor = MigrationExecutor(conn)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())

    pending: list[str] = []
    data_only: list[str] = []
    for migration in plan:
        if migration.operations and all(
            isinstance(op, RunPython) for op in migration.operations
        ):
            data_only.append(str(migration))
        else:
            pending.append(str(migration))
    return pending, data_only


def _missing_schema_objects(conn: DatabaseConnection) -> tuple[list[str], list[str]]:
    """Model tables and columns missing from the database.

    Existence only, mirroring what the ORM requires to run at all: Plain's
    SELECTs enumerate model columns, so a missing table or column is always
    fatal to serving. Type/nullability/index drift is deliberately ignored —
    that's convergence's gradient, not a serving cliff (Hibernate's
    `validate` checks types too and earned its false-positive reputation
    for it).

    One catalog query across all tables, rather than
    `introspection.introspect_table()` per table — that path also pulls
    constraints, indexes, and storage parameters, far more than existence
    needs.
    """
    expected: dict[str, list[str]] = {}
    for model in get_migratable_models():
        columns = []
        for f in model._model_meta.local_fields:
            if isinstance(f, ColumnField) and f.db_type() is not None:
                columns.append(f.column)
        expected[model.model_options.db_table] = columns

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, a.attname
            FROM pg_class c
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE c.relname = ANY(%s)
              AND c.relkind IN ('r', 'p', 'v', 'f', 'm')
              AND pg_catalog.pg_table_is_visible(c.oid)
              AND a.attnum > 0 AND NOT a.attisdropped
            """,
            [list(expected)],
        )
        actual: dict[str, set[str]] = {}
        for table, column in cursor.fetchall():
            actual.setdefault(table, set()).add(column)

    missing_tables: list[str] = []
    missing_columns: list[str] = []
    for table, columns in expected.items():
        if table not in actual:
            missing_tables.append(table)
            continue
        missing_columns.extend(
            f"{table}.{column}" for column in columns if column not in actual[table]
        )
    return sorted(missing_tables), sorted(missing_columns)


# Server-sent FATAL messages that mean the configuration is wrong and a
# human must change something — retrying can never fix these. Matched as
# substrings of the connection error because psycopg3 exposes no sqlstate
# on connection-time failures (verified against psycopg 3.2: auth failure,
# bad database, refused, and DNS all raise OperationalError with
# sqlstate=None). Localized servers won't match and fall through to
# UNREACHABLE — the safe direction, since a wrongly-permanent verdict
# during a DB restart would mislead the operator, while a wrongly-retryable
# one just keeps polling with the real error printed.
_CONFIG_ERROR_MESSAGES = (
    "password authentication failed",  # 28P01
    "no pg_hba.conf entry",  # 28000
    '" does not exist',  # 3D000 database / 28000 role
)

# libpq rejects a bad value for a recognized connection option client-side,
# before any network I/O: 'invalid sslmode value: "bogus"', "invalid
# integer value ... for connection option ...", "invalid channel_binding
# value", etc. One pattern covers the family.
_INVALID_OPTION_VALUE_RE = re.compile(r"\binvalid \w+ value")


def _classify_connection_failure(error: psycopg.OperationalError) -> ReadinessStatus:
    """Split connection failures into permanent (config) vs retryable.

    Everything unmatched is retryable: "server starting up", "too many
    connections", refused, timeout, DNS — all resolve on their own or with
    time, and defaulting to retryable is the direction that never misleads.
    """
    if error.sqlstate:
        # Query-time failures carry a sqlstate. Class 28 (auth) and class 3D
        # (invalid catalog) are config-shaped; everything else that reaches
        # here (connection loss, admin shutdown, resource limits) is
        # retryable. Today 3D000 only occurs at connect time where sqlstate
        # is None (psycopg 3.2), so it's handled by the message matching
        # below — the sqlstate hedge is for a future psycopg that populates
        # it.
        if error.sqlstate.startswith(("28", "3D")):
            return ReadinessStatus.CONFIG_ERROR
        return ReadinessStatus.UNREACHABLE

    message = str(error)
    if any(marker in message for marker in _CONFIG_ERROR_MESSAGES):
        return ReadinessStatus.CONFIG_ERROR
    if _INVALID_OPTION_VALUE_RE.search(message):
        return ReadinessStatus.CONFIG_ERROR
    return ReadinessStatus.UNREACHABLE
