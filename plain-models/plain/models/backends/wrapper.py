from __future__ import annotations

import _thread
import copy
import datetime
import logging
import os
import signal
import subprocess
import threading
import time
import warnings
import zoneinfo
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, Any, LiteralString, cast

import psycopg as Database
from psycopg import ClientCursor, IsolationLevel, adapt, adapters, errors
from psycopg import sql as psycopg_sql
from psycopg.abc import Buffer, PyFormat
from psycopg.postgres import types as pg_types
from psycopg.pq import Format
from psycopg.types.datetime import TimestamptzLoader
from psycopg.types.range import BaseRangeDumper, Range, RangeDumper
from psycopg.types.string import TextLoader

from plain.exceptions import ImproperlyConfigured
from plain.models.backends import utils

# Import component classes directly (no longer need lazy imports since we only support PostgreSQL)
from plain.models.backends.creation import DatabaseCreation
from plain.models.backends.introspection import DatabaseIntrospection
from plain.models.backends.schema import DatabaseSchemaEditor
from plain.models.backends.sql import MAX_NAME_LENGTH, quote_name
from plain.models.backends.utils import CursorDebugWrapper as BaseCursorDebugWrapper
from plain.models.backends.utils import debug_transaction
from plain.models.db import (
    DatabaseError,
    DatabaseErrorWrapper,
    NotSupportedError,
    db_connection,
)
from plain.models.db import DatabaseError as WrappedDatabaseError
from plain.models.transaction import TransactionManagementError
from plain.runtime import settings

if TYPE_CHECKING:
    from psycopg import Connection as PsycopgConnection

    from plain.models.connections import DatabaseConfig
    from plain.models.fields import Field

RAN_DB_VERSION_CHECK = False

logger = logging.getLogger("plain.models.backends")

# Type OIDs
TIMESTAMPTZ_OID = adapters.types["timestamptz"].oid
TSRANGE_OID = pg_types["tsrange"].oid
TSTZRANGE_OID = pg_types["tstzrange"].oid


class BaseTzLoader(TimestamptzLoader):
    """
    Load a PostgreSQL timestamptz using a specific timezone.
    The timezone can be None too, in which case it will be chopped.
    """

    timezone: datetime.tzinfo | None = None

    def load(self, data: Buffer) -> datetime.datetime:
        res = super().load(data)
        return res.replace(tzinfo=self.timezone)


def register_tzloader(tz: datetime.tzinfo | None, context: Any) -> None:
    class SpecificTzLoader(BaseTzLoader):
        timezone = tz

    context.adapters.register_loader("timestamptz", SpecificTzLoader)


class PlainRangeDumper(RangeDumper):
    """A Range dumper customized for Plain."""

    def upgrade(self, obj: Range[Any], format: PyFormat) -> BaseRangeDumper:
        dumper = super().upgrade(obj, format)
        if dumper is not self and dumper.oid == TSRANGE_OID:
            dumper.oid = TSTZRANGE_OID
        return dumper


@lru_cache
def get_adapters_template(timezone: datetime.tzinfo | None) -> adapt.AdaptersMap:
    ctx = adapt.AdaptersMap(adapters)
    # No-op JSON loader to avoid psycopg3 round trips
    ctx.register_loader("jsonb", TextLoader)
    # Treat inet/cidr as text
    ctx.register_loader("inet", TextLoader)
    ctx.register_loader("cidr", TextLoader)
    ctx.register_dumper(Range, PlainRangeDumper)
    register_tzloader(timezone, ctx)
    return ctx


def _psql_settings_to_cmd_args_env(
    settings_dict: DatabaseConfig, parameters: list[str]
) -> tuple[list[str], dict[str, str] | None]:
    """Build psql command-line arguments from database settings."""
    args = ["psql"]
    options = settings_dict.get("OPTIONS", {})

    host = settings_dict.get("HOST")
    port = settings_dict.get("PORT")
    dbname = settings_dict.get("NAME")
    user = settings_dict.get("USER")
    passwd = settings_dict.get("PASSWORD")
    passfile = options.get("passfile")
    service = options.get("service")
    sslmode = options.get("sslmode")
    sslrootcert = options.get("sslrootcert")
    sslcert = options.get("sslcert")
    sslkey = options.get("sslkey")

    if not dbname and not service:
        # Connect to the default 'postgres' db.
        dbname = "postgres"
    if user:
        args += ["-U", user]
    if host:
        args += ["-h", host]
    if port:
        args += ["-p", str(port)]
    args.extend(parameters)
    if dbname:
        args += [dbname]

    env = {}
    if passwd:
        env["PGPASSWORD"] = str(passwd)
    if service:
        env["PGSERVICE"] = str(service)
    if sslmode:
        env["PGSSLMODE"] = str(sslmode)
    if sslrootcert:
        env["PGSSLROOTCERT"] = str(sslrootcert)
    if sslcert:
        env["PGSSLCERT"] = str(sslcert)
    if sslkey:
        env["PGSSLKEY"] = str(sslkey)
    if passfile:
        env["PGPASSFILE"] = str(passfile)
    return args, (env or None)


class DatabaseWrapper:
    """
    PostgreSQL database connection wrapper.

    This is the only database backend supported by Plain.
    """

    # Type checker hints for component classes
    creation: DatabaseCreation
    introspection: DatabaseIntrospection

    queries_limit: int = 9000
    executable_name: str = "psql"

    # PostgreSQL backend-specific attributes.
    _named_cursor_idx = 0

    def __init__(self, settings_dict: DatabaseConfig):
        # Connection related attributes.
        # The underlying database connection (from the database library, not a wrapper).
        self.connection: PsycopgConnection[Any] | None = None
        # `settings_dict` should be a dictionary containing keys such as
        # NAME, USER, etc. It's called `settings_dict` instead of `settings`
        # to disambiguate it from Plain settings modules.
        self.settings_dict: DatabaseConfig = settings_dict
        # Query logging in debug mode or when explicitly enabled.
        self.queries_log: deque[dict[str, Any]] = deque(maxlen=self.queries_limit)
        self.force_debug_cursor: bool = False

        # Transaction related attributes.
        # Tracks if the connection is in autocommit mode. Per PEP 249, by
        # default, it isn't.
        self.autocommit: bool = False
        # Tracks if the connection is in a transaction managed by 'atomic'.
        self.in_atomic_block: bool = False
        # Increment to generate unique savepoint ids.
        self.savepoint_state: int = 0
        # List of savepoints created by 'atomic'.
        self.savepoint_ids: list[str] = []
        # Stack of active 'atomic' blocks.
        self.atomic_blocks: list[Any] = []
        # Tracks if the outermost 'atomic' block should commit on exit,
        # ie. if autocommit was active on entry.
        self.commit_on_exit: bool = True
        # Tracks if the transaction should be rolled back to the next
        # available savepoint because of an exception in an inner block.
        self.needs_rollback: bool = False
        self.rollback_exc: Exception | None = None

        # Connection termination related attributes.
        self.close_at: float | None = None
        self.closed_in_transaction: bool = False
        self.errors_occurred: bool = False
        self.health_check_enabled: bool = False
        self.health_check_done: bool = False

        # Thread-safety related attributes.
        self._thread_sharing_lock: threading.Lock = threading.Lock()
        self._thread_sharing_count: int = 0
        self._thread_ident: int = _thread.get_ident()

        # A list of no-argument functions to run when the transaction commits.
        # Each entry is an (sids, func, robust) tuple, where sids is a set of
        # the active savepoint IDs when this function was registered and robust
        # specifies whether it's allowed for the function to fail.
        self.run_on_commit: list[tuple[set[str], Any, bool]] = []

        # Should we run the on-commit hooks the next time set_autocommit(True)
        # is called?
        self.run_commit_hooks_on_set_autocommit_on: bool = False

        # A stack of wrappers to be invoked around execute()/executemany()
        # calls. Each entry is a function taking five arguments: execute, sql,
        # params, many, and context. It's the function's responsibility to
        # call execute(sql, params, many, context).
        self.execute_wrappers: list[Any] = []

        # Instantiate component classes directly
        self.creation = DatabaseCreation(self)
        self.introspection = DatabaseIntrospection(self)

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__} vendor='postgresql'>"

    @cached_property
    def timezone(self) -> datetime.tzinfo:
        """
        Return a tzinfo of the database connection time zone.

        When a datetime is read from the database, it is returned in this time
        zone. Since PostgreSQL supports time zones, it doesn't matter which
        time zone Plain uses, as long as aware datetimes are used everywhere.
        Other users connecting to the database can choose their own time zone.
        """
        if self.settings_dict["TIME_ZONE"] is None:
            return datetime.UTC
        else:
            return zoneinfo.ZoneInfo(self.settings_dict["TIME_ZONE"])

    @cached_property
    def timezone_name(self) -> str:
        """
        Name of the time zone of the database connection.
        """
        if self.settings_dict["TIME_ZONE"] is None:
            return "UTC"
        else:
            return self.settings_dict["TIME_ZONE"]

    @property
    def queries_logged(self) -> bool:
        return self.force_debug_cursor or settings.DEBUG

    @property
    def queries(self) -> list[dict[str, Any]]:
        if len(self.queries_log) == self.queries_log.maxlen:
            warnings.warn(
                f"Limit for query logging exceeded, only the last {self.queries_log.maxlen} queries "
                "will be returned."
            )
        return list(self.queries_log)

    def check_database_version_supported(self) -> None:
        """
        Raise an error if the database version isn't supported by this
        version of Plain. PostgreSQL 12+ is required.
        """
        major, minor = divmod(self.pg_version, 10000)
        if major < 12:
            raise NotSupportedError(
                f"PostgreSQL 12 or later is required (found {major}.{minor})."
            )

    # ##### Connection and cursor methods #####

    def get_connection_params(self) -> dict[str, Any]:
        """Return a dict of parameters suitable for get_new_connection."""
        settings_dict = self.settings_dict
        options = settings_dict.get("OPTIONS", {})
        # None may be used to connect to the default 'postgres' db
        if settings_dict.get("NAME") == "" and not options.get("service"):
            raise ImproperlyConfigured(
                "settings.DATABASE is improperly configured. "
                "Please supply the NAME or OPTIONS['service'] value."
            )
        db_name = settings_dict.get("NAME")
        if len(db_name or "") > MAX_NAME_LENGTH:
            raise ImproperlyConfigured(
                "The database name '%s' (%d characters) is longer than "  # noqa: UP031
                "PostgreSQL's limit of %d characters. Supply a shorter NAME "
                "in settings.DATABASE."
                % (
                    db_name,
                    len(db_name or ""),
                    MAX_NAME_LENGTH,
                )
            )
        conn_params: dict[str, Any] = {"client_encoding": "UTF8"}
        if db_name:
            conn_params = {
                "dbname": db_name,
                **options,
            }
        elif db_name is None:
            # Connect to the default 'postgres' db.
            options.pop("service", None)
            conn_params = {"dbname": "postgres", **options}
        else:
            conn_params = {**options}

        conn_params.pop("assume_role", None)
        conn_params.pop("isolation_level", None)
        conn_params.pop("server_side_binding", None)
        if settings_dict["USER"]:
            conn_params["user"] = settings_dict["USER"]
        if settings_dict["PASSWORD"]:
            conn_params["password"] = settings_dict["PASSWORD"]
        if settings_dict["HOST"]:
            conn_params["host"] = settings_dict["HOST"]
        if settings_dict["PORT"]:
            conn_params["port"] = settings_dict["PORT"]
        conn_params["context"] = get_adapters_template(self.timezone)
        # Disable prepared statements by default to keep connection poolers
        # working. Can be reenabled via OPTIONS in the settings dict.
        conn_params["prepare_threshold"] = conn_params.pop("prepare_threshold", None)
        return conn_params

    def get_new_connection(self, conn_params: dict[str, Any]) -> PsycopgConnection[Any]:
        """Open a connection to the database."""
        # self.isolation_level must be set:
        # - after connecting to the database in order to obtain the database's
        #   default when no value is explicitly specified in options.
        # - before calling _set_autocommit() because if autocommit is on, that
        #   will set connection.isolation_level to ISOLATION_LEVEL_AUTOCOMMIT.
        options = self.settings_dict.get("OPTIONS", {})
        set_isolation_level = False
        try:
            isolation_level_value = options["isolation_level"]
        except KeyError:
            self.isolation_level = IsolationLevel.READ_COMMITTED
        else:
            # Set the isolation level to the value from OPTIONS.
            try:
                self.isolation_level = IsolationLevel(isolation_level_value)
                set_isolation_level = True
            except ValueError:
                raise ImproperlyConfigured(
                    f"Invalid transaction isolation level {isolation_level_value} "
                    f"specified. Use one of the psycopg.IsolationLevel values."
                )
        connection = Database.connect(**conn_params)
        if set_isolation_level:
            connection.isolation_level = self.isolation_level
        # Use server-side binding cursor if requested, otherwise standard cursor
        connection.cursor_factory = (
            ServerBindingCursor
            if options.get("server_side_binding") is True
            else Cursor
        )
        return connection

    def ensure_timezone(self) -> bool:
        """
        Ensure the connection's timezone is set to `self.timezone_name` and
        return whether it changed or not.
        """
        if self.connection is None:
            return False
        conn_timezone_name = self.connection.info.parameter_status("TimeZone")
        timezone_name = self.timezone_name
        if timezone_name and conn_timezone_name != timezone_name:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('TimeZone', %s, false)", [timezone_name]
                )
            return True
        return False

    def ensure_role(self) -> bool:
        if self.connection is None:
            return False
        if new_role := self.settings_dict.get("OPTIONS", {}).get("assume_role"):
            with self.connection.cursor() as cursor:
                sql_str = self.compose_sql("SET ROLE %s", [new_role])
                cursor.execute(sql_str)  # type: ignore[arg-type]
            return True
        return False

    def init_connection_state(self) -> None:
        """Initialize the database connection settings."""
        global RAN_DB_VERSION_CHECK
        if not RAN_DB_VERSION_CHECK:
            self.check_database_version_supported()
            RAN_DB_VERSION_CHECK = True

        # Commit after setting the time zone.
        commit_tz = self.ensure_timezone()
        # Set the role on the connection. This is useful if the credential used
        # to login is not the same as the role that owns database resources. As
        # can be the case when using temporary or ephemeral credentials.
        commit_role = self.ensure_role()

        if (commit_role or commit_tz) and not self.get_autocommit():
            assert self.connection is not None
            self.connection.commit()

    def create_cursor(self, name: str | None = None) -> Any:
        """Create a cursor. Assume that a connection is established."""
        assert self.connection is not None
        if name:
            # In autocommit mode, the cursor will be used outside of a
            # transaction, hence use a holdable cursor.
            cursor = self.connection.cursor(
                name, scrollable=False, withhold=self.connection.autocommit
            )
        else:
            cursor = self.connection.cursor()

        # Register the cursor timezone only if the connection disagrees, to avoid copying the adapter map.
        tzloader = self.connection.adapters.get_loader(TIMESTAMPTZ_OID, Format.TEXT)
        if self.timezone != tzloader.timezone:  # type: ignore[union-attr]
            register_tzloader(self.timezone, cursor)
        return cursor

    def chunked_cursor(self) -> utils.CursorWrapper:
        """
        Return a server-side cursor that avoids caching results in memory.
        """
        self._named_cursor_idx += 1
        # Get the current async task
        # Note that right now this is behind @async_unsafe, so this is
        # unreachable, but in future we'll start loosening this restriction.
        # For now, it's here so that every use of "threading" is
        # also async-compatible.
        task_ident = "sync"
        # Use that and the thread ident to get a unique name
        return self._cursor(
            name="_plain_curs_%d_%s_%d"  # noqa: UP031
            % (
                # Avoid reusing name in other threads / tasks
                threading.current_thread().ident,
                task_ident,
                self._named_cursor_idx,
            )
        )

    def _set_autocommit(self, autocommit: bool) -> None:
        """Backend-specific implementation to enable or disable autocommit."""
        assert self.connection is not None
        with self.wrap_database_errors:
            self.connection.autocommit = autocommit

    def check_constraints(self, table_names: list[str] | None = None) -> None:
        """
        Check constraints by setting them to immediate. Return them to deferred
        afterward.
        """
        with self.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")

    def is_usable(self) -> bool:
        """
        Test if the database connection is usable.

        This method may assume that self.connection is not None.

        Actual implementations should take care not to raise exceptions
        as that may prevent Plain from recycling unusable connections.
        """
        assert self.connection is not None
        try:
            # Use a psycopg cursor directly, bypassing Plain's utilities.
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Database.Error:
            return False
        else:
            return True

    @contextmanager
    def _nodb_cursor(self) -> Generator[utils.CursorWrapper, None, None]:
        """
        Return a cursor from an alternative connection to be used when there is
        no need to access the main database, specifically for test db
        creation/deletion. This also prevents the production database from
        being exposed to potential child threads while (or after) the test
        database is destroyed. Refs #10868, #17786, #16969.
        """
        cursor = None
        try:
            conn = self.__class__({**self.settings_dict, "NAME": None})
            try:
                with conn.cursor() as cursor:
                    yield cursor
            finally:
                conn.close()
        except (Database.DatabaseError, WrappedDatabaseError):
            if cursor is not None:
                raise
            warnings.warn(
                "Normally Plain will use a connection to the 'postgres' database "
                "to avoid running initialization queries against the production "
                "database when it's not needed (for example, when running tests). "
                "Plain was unable to create a connection to the 'postgres' database "
                "and will use the first PostgreSQL database instead.",
                RuntimeWarning,
            )
            conn = self.__class__(
                {
                    **self.settings_dict,
                    "NAME": db_connection.settings_dict["NAME"],
                },
            )
            try:
                with conn.cursor() as cursor:
                    yield cursor
            finally:
                conn.close()

    @cached_property
    def pg_version(self) -> int:
        with self.temporary_connection():
            assert self.connection is not None
            return self.connection.info.server_version

    def make_debug_cursor(self, cursor: Any) -> CursorDebugWrapper:
        return CursorDebugWrapper(cursor, self)

    # ##### Connection lifecycle #####

    def connect(self) -> None:
        """Connect to the database. Assume that the connection is closed."""
        # In case the previous connection was closed while in an atomic block
        self.in_atomic_block = False
        self.savepoint_ids = []
        self.atomic_blocks = []
        self.needs_rollback = False
        # Reset parameters defining when to close/health-check the connection.
        self.health_check_enabled = self.settings_dict["CONN_HEALTH_CHECKS"]
        max_age = self.settings_dict["CONN_MAX_AGE"]
        self.close_at = None if max_age is None else time.monotonic() + max_age
        self.closed_in_transaction = False
        self.errors_occurred = False
        # New connections are healthy.
        self.health_check_done = True
        # Establish the connection
        conn_params = self.get_connection_params()
        self.connection = self.get_new_connection(conn_params)
        self.set_autocommit(self.settings_dict["AUTOCOMMIT"])
        self.init_connection_state()

        self.run_on_commit = []

    def ensure_connection(self) -> None:
        """Guarantee that a connection to the database is established."""
        if self.connection is None:
            with self.wrap_database_errors:
                self.connect()

    # ##### PEP-249 connection method wrappers #####

    def _prepare_cursor(self, cursor: Any) -> utils.CursorWrapper:
        """
        Validate the connection is usable and perform database cursor wrapping.
        """
        self.validate_thread_sharing()
        if self.queries_logged:
            wrapped_cursor = self.make_debug_cursor(cursor)
        else:
            wrapped_cursor = self.make_cursor(cursor)
        return wrapped_cursor

    def _cursor(self, name: str | None = None) -> utils.CursorWrapper:
        self.close_if_health_check_failed()
        self.ensure_connection()
        with self.wrap_database_errors:
            return self._prepare_cursor(self.create_cursor(name))

    def _commit(self) -> None:
        if self.connection is not None:
            with debug_transaction(self, "COMMIT"), self.wrap_database_errors:
                return self.connection.commit()

    def _rollback(self) -> None:
        if self.connection is not None:
            with debug_transaction(self, "ROLLBACK"), self.wrap_database_errors:
                return self.connection.rollback()

    def _close(self) -> None:
        if self.connection is not None:
            with self.wrap_database_errors:
                return self.connection.close()

    # ##### Generic wrappers for PEP-249 connection methods #####

    def cursor(self) -> utils.CursorWrapper:
        """Create a cursor, opening a connection if necessary."""
        return self._cursor()

    def commit(self) -> None:
        """Commit a transaction and reset the dirty flag."""
        self.validate_thread_sharing()
        self.validate_no_atomic_block()
        self._commit()
        # A successful commit means that the database connection works.
        self.errors_occurred = False
        self.run_commit_hooks_on_set_autocommit_on = True

    def rollback(self) -> None:
        """Roll back a transaction and reset the dirty flag."""
        self.validate_thread_sharing()
        self.validate_no_atomic_block()
        self._rollback()
        # A successful rollback means that the database connection works.
        self.errors_occurred = False
        self.needs_rollback = False
        self.run_on_commit = []

    def close(self) -> None:
        """Close the connection to the database."""
        self.validate_thread_sharing()
        self.run_on_commit = []

        # Don't call validate_no_atomic_block() to avoid making it difficult
        # to get rid of a connection in an invalid state. The next connect()
        # will reset the transaction state anyway.
        if self.closed_in_transaction or self.connection is None:
            return
        try:
            self._close()
        finally:
            if self.in_atomic_block:
                self.closed_in_transaction = True
                self.needs_rollback = True
            else:
                self.connection = None

    # ##### Savepoint management #####

    def _savepoint(self, sid: str) -> None:
        with self.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {quote_name(sid)}")

    def _savepoint_rollback(self, sid: str) -> None:
        with self.cursor() as cursor:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {quote_name(sid)}")

    def _savepoint_commit(self, sid: str) -> None:
        with self.cursor() as cursor:
            cursor.execute(f"RELEASE SAVEPOINT {quote_name(sid)}")

    # ##### Generic savepoint management methods #####

    def savepoint(self) -> str | None:
        """
        Create a savepoint inside the current transaction. Return an
        identifier for the savepoint that will be used for the subsequent
        rollback or commit. Return None if in autocommit mode (no transaction).
        """
        if self.get_autocommit():
            return None

        thread_ident = _thread.get_ident()
        tid = str(thread_ident).replace("-", "")

        self.savepoint_state += 1
        sid = "s%s_x%d" % (tid, self.savepoint_state)  # noqa: UP031

        self.validate_thread_sharing()
        self._savepoint(sid)

        return sid

    def savepoint_rollback(self, sid: str) -> None:
        """
        Roll back to a savepoint. Do nothing if in autocommit mode.
        """
        if self.get_autocommit():
            return

        self.validate_thread_sharing()
        self._savepoint_rollback(sid)

        # Remove any callbacks registered while this savepoint was active.
        self.run_on_commit = [
            (sids, func, robust)
            for (sids, func, robust) in self.run_on_commit
            if sid not in sids
        ]

    def savepoint_commit(self, sid: str) -> None:
        """
        Release a savepoint. Do nothing if in autocommit mode.
        """
        if self.get_autocommit():
            return

        self.validate_thread_sharing()
        self._savepoint_commit(sid)

    def clean_savepoints(self) -> None:
        """
        Reset the counter used to generate unique savepoint ids in this thread.
        """
        self.savepoint_state = 0

    # ##### Generic transaction management methods #####

    def get_autocommit(self) -> bool:
        """Get the autocommit state."""
        self.ensure_connection()
        return self.autocommit

    def set_autocommit(self, autocommit: bool) -> None:
        """Enable or disable autocommit."""
        self.validate_no_atomic_block()
        self.close_if_health_check_failed()
        self.ensure_connection()

        if autocommit:
            self._set_autocommit(autocommit)
        else:
            with debug_transaction(self, "BEGIN"):
                self._set_autocommit(autocommit)
        self.autocommit = autocommit

        if autocommit and self.run_commit_hooks_on_set_autocommit_on:
            self.run_and_clear_commit_hooks()
            self.run_commit_hooks_on_set_autocommit_on = False

    def get_rollback(self) -> bool:
        """Get the "needs rollback" flag -- for *advanced use* only."""
        if not self.in_atomic_block:
            raise TransactionManagementError(
                "The rollback flag doesn't work outside of an 'atomic' block."
            )
        return self.needs_rollback

    def set_rollback(self, rollback: bool) -> None:
        """
        Set or unset the "needs rollback" flag -- for *advanced use* only.
        """
        if not self.in_atomic_block:
            raise TransactionManagementError(
                "The rollback flag doesn't work outside of an 'atomic' block."
            )
        self.needs_rollback = rollback

    def validate_no_atomic_block(self) -> None:
        """Raise an error if an atomic block is active."""
        if self.in_atomic_block:
            raise TransactionManagementError(
                "This is forbidden when an 'atomic' block is active."
            )

    def validate_no_broken_transaction(self) -> None:
        if self.needs_rollback:
            raise TransactionManagementError(
                "An error occurred in the current transaction. You can't "
                "execute queries until the end of the 'atomic' block."
            ) from self.rollback_exc

    # ##### Connection termination handling #####

    def close_if_health_check_failed(self) -> None:
        """Close existing connection if it fails a health check."""
        if (
            self.connection is None
            or not self.health_check_enabled
            or self.health_check_done
        ):
            return

        if not self.is_usable():
            self.close()
        self.health_check_done = True

    def close_if_unusable_or_obsolete(self) -> None:
        """
        Close the current connection if unrecoverable errors have occurred
        or if it outlived its maximum age.
        """
        if self.connection is not None:
            self.health_check_done = False
            # If the application didn't restore the original autocommit setting,
            # don't take chances, drop the connection.
            if self.get_autocommit() != self.settings_dict["AUTOCOMMIT"]:
                self.close()
                return

            # If an exception other than DataError or IntegrityError occurred
            # since the last commit / rollback, check if the connection works.
            if self.errors_occurred:
                if self.is_usable():
                    self.errors_occurred = False
                    self.health_check_done = True
                else:
                    self.close()
                    return

            if self.close_at is not None and time.monotonic() >= self.close_at:
                self.close()
                return

    # ##### Thread safety handling #####

    @property
    def allow_thread_sharing(self) -> bool:
        with self._thread_sharing_lock:
            return self._thread_sharing_count > 0

    def validate_thread_sharing(self) -> None:
        """
        Validate that the connection isn't accessed by another thread than the
        one which originally created it, unless the connection was explicitly
        authorized to be shared between threads (via the `inc_thread_sharing()`
        method). Raise an exception if the validation fails.
        """
        if not (self.allow_thread_sharing or self._thread_ident == _thread.get_ident()):
            raise DatabaseError(
                "DatabaseWrapper objects created in a "
                "thread can only be used in that same thread. The connection "
                f"was created in thread id {self._thread_ident} and this is "
                f"thread id {_thread.get_ident()}."
            )

    # ##### Miscellaneous #####

    def prepare_database(self) -> None:
        """
        Hook to do any database check or preparation, generally called before
        migrating a project or an app.
        """
        pass

    @cached_property
    def wrap_database_errors(self) -> DatabaseErrorWrapper:
        """
        Context manager and decorator that re-throws backend-specific database
        exceptions using Plain's common wrappers.
        """
        return DatabaseErrorWrapper(self)

    def make_cursor(self, cursor: Any) -> utils.CursorWrapper:
        """Create a cursor without debug logging."""
        return utils.CursorWrapper(cursor, self)

    @contextmanager
    def temporary_connection(self) -> Generator[utils.CursorWrapper, None, None]:
        """
        Context manager that ensures that a connection is established, and
        if it opened one, closes it to avoid leaving a dangling connection.
        This is useful for operations outside of the request-response cycle.

        Provide a cursor: with self.temporary_connection() as cursor: ...
        """
        must_close = self.connection is None
        try:
            with self.cursor() as cursor:
                yield cursor
        finally:
            if must_close:
                self.close()

    def schema_editor(self, *args: Any, **kwargs: Any) -> DatabaseSchemaEditor:
        """Return a new instance of the schema editor."""
        return DatabaseSchemaEditor(self, *args, **kwargs)

    def runshell(self, parameters: list[str]) -> None:
        """Run an interactive psql shell."""
        args, env = _psql_settings_to_cmd_args_env(self.settings_dict, parameters)
        env = {**os.environ, **env} if env else None
        sigint_handler = signal.getsignal(signal.SIGINT)
        try:
            # Allow SIGINT to pass to psql to abort queries.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            subprocess.run(args, env=env, check=True)
        finally:
            # Restore the original SIGINT handler.
            signal.signal(signal.SIGINT, sigint_handler)

    def on_commit(self, func: Any, robust: bool = False) -> None:
        if not callable(func):
            raise TypeError("on_commit()'s callback must be a callable.")
        if self.in_atomic_block:
            # Transaction in progress; save for execution on commit.
            self.run_on_commit.append((set(self.savepoint_ids), func, robust))
        elif not self.get_autocommit():
            raise TransactionManagementError(
                "on_commit() cannot be used in manual transaction management"
            )
        else:
            # No transaction in progress and in autocommit mode; execute
            # immediately.
            if robust:
                try:
                    func()
                except Exception as e:
                    logger.error(
                        f"Error calling {func.__qualname__} in on_commit() (%s).",
                        e,
                        exc_info=True,
                    )
            else:
                func()

    def run_and_clear_commit_hooks(self) -> None:
        self.validate_no_atomic_block()
        current_run_on_commit = self.run_on_commit
        self.run_on_commit = []
        while current_run_on_commit:
            _, func, robust = current_run_on_commit.pop(0)
            if robust:
                try:
                    func()
                except Exception as e:
                    logger.error(
                        f"Error calling {func.__qualname__} in on_commit() during "
                        f"transaction (%s).",
                        e,
                        exc_info=True,
                    )
            else:
                func()

    @contextmanager
    def execute_wrapper(self, wrapper: Any) -> Generator[None, None, None]:
        """
        Return a context manager under which the wrapper is applied to suitable
        database query executions.
        """
        self.execute_wrappers.append(wrapper)
        try:
            yield
        finally:
            self.execute_wrappers.pop()

    # ##### SQL generation methods that require connection state #####

    def compose_sql(self, query: str, params: Any) -> str:
        """
        Compose a SQL query with parameters using psycopg's mogrify.

        This requires an active connection because it uses the connection's
        cursor to properly format parameters.
        """
        assert self.connection is not None
        return ClientCursor(self.connection).mogrify(
            psycopg_sql.SQL(cast(LiteralString, query)), params
        )

    def last_executed_query(
        self,
        cursor: utils.CursorWrapper,
        sql: str,
        params: Any,
    ) -> str | None:
        """
        Return a string of the query last executed by the given cursor, with
        placeholders replaced with actual values.
        """
        try:
            return self.compose_sql(sql, params)
        except errors.DataError:
            return None

    def unification_cast_sql(self, output_field: Field) -> str:
        """
        Given a field instance, return the SQL that casts the result of a union
        to that type. The resulting string should contain a '%s' placeholder
        for the expression being cast.
        """
        internal_type = output_field.get_internal_type()
        if internal_type in (
            "GenericIPAddressField",
            "TimeField",
            "UUIDField",
        ):
            # PostgreSQL will resolve a union as type 'text' if input types are
            # 'unknown'.
            # https://www.postgresql.org/docs/current/typeconv-union-case.html
            # These fields cannot be implicitly cast back in the default
            # PostgreSQL configuration so we need to explicitly cast them.
            # We must also remove components of the type within brackets:
            # varchar(255) -> varchar.
            db_type = output_field.db_type(self)
            if db_type:
                return "CAST(%s AS {})".format(db_type.split("(")[0])
        return "%s"

    def copy(self) -> DatabaseWrapper:
        """
        Return a copy of this connection.

        For tests that require two connections to the same database.
        """
        settings_dict = copy.deepcopy(self.settings_dict)
        return type(self)(settings_dict)


class CursorMixin:
    """
    A subclass of psycopg cursor implementing callproc.
    """

    def callproc(
        self, name: str | psycopg_sql.Identifier, args: list[Any] | None = None
    ) -> list[Any] | None:
        if not isinstance(name, psycopg_sql.Identifier):
            name = psycopg_sql.Identifier(name)

        qparts: list[psycopg_sql.Composable] = [
            psycopg_sql.SQL("SELECT * FROM "),
            name,
            psycopg_sql.SQL("("),
        ]
        if args:
            for item in args:
                qparts.append(psycopg_sql.Literal(item))
                qparts.append(psycopg_sql.SQL(","))
            del qparts[-1]

        qparts.append(psycopg_sql.SQL(")"))
        stmt = psycopg_sql.Composed(qparts)
        self.execute(stmt)  # type: ignore[attr-defined]
        return args


class ServerBindingCursor(CursorMixin, Database.Cursor):
    pass


class Cursor(CursorMixin, Database.ClientCursor):
    pass


class CursorDebugWrapper(BaseCursorDebugWrapper):
    def copy(self, statement: Any) -> Any:
        with self.debug_sql(statement):
            return self.cursor.copy(statement)
