from __future__ import annotations

import _thread
import warnings
from collections import deque
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, LiteralString, NamedTuple, cast

import psycopg
from psycopg import errors
from psycopg import sql as psycopg_sql

from plain.logs import get_framework_logger
from plain.postgres import utils
from plain.postgres.dialect import quote_name
from plain.postgres.fields import GenericIPAddressField, TimeField, UUIDField
from plain.postgres.indexes import Index
from plain.postgres.schema import DatabaseSchemaEditor
from plain.postgres.sources import ConnectionSource
from plain.postgres.transaction import TransactionManagementError
from plain.postgres.utils import CursorDebugWrapper as BaseCursorDebugWrapper
from plain.postgres.utils import CursorWrapper, debug_transaction
from plain.runtime import settings

if TYPE_CHECKING:
    from psycopg import Connection as PsycopgConnection

    from plain.postgres.database_url import DatabaseConfig
    from plain.postgres.fields import Field

logger = get_framework_logger()


def get_migratable_models() -> Generator[Any]:
    """Return all models that should be included in migrations."""
    from plain.packages import packages_registry
    from plain.postgres import models_registry

    return (
        model
        for package_config in packages_registry.get_package_configs()
        for model in models_registry.get_models(
            package_label=package_config.package_label
        )
    )


class TableInfo(NamedTuple):
    """Structure returned by DatabaseConnection.get_table_list()."""

    name: str
    type: str
    comment: str | None


class DatabaseConnection:
    """
    PostgreSQL database connection.

    This is the only database backend supported by Plain.
    """

    queries_limit: int = 9000

    index_default_access_method = "btree"
    ignored_tables: list[str] = []

    def __init__(self, source: ConnectionSource):
        # Lazy — acquired on first use via self._source.
        self.connection: PsycopgConnection[Any] | None = None
        self._source: ConnectionSource = source
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
        self.savepoint_ids: list[str | None] = []
        # Stack of active 'atomic' blocks.
        self.atomic_blocks: list[Any] = []
        # Tracks if the transaction should be rolled back to the next
        # available savepoint because of an exception in an inner block.
        self.needs_rollback: bool = False
        self.rollback_exc: Exception | None = None

        # A list of no-argument functions to run when the transaction commits.
        # Each entry is an (sids, func, robust) tuple, where sids is a set of
        # the active savepoint IDs when this function was registered and robust
        # specifies whether it's allowed for the function to fail.
        self.run_on_commit: list[tuple[set[str | None], Any, bool]] = []

        # Should we run the on-commit hooks the next time set_autocommit(True)
        # is called?
        self.run_commit_hooks_on_set_autocommit_on: bool = False

        # A stack of wrappers to be invoked around execute()/executemany()
        # calls. Each entry is a function taking five arguments: execute, sql,
        # params, many, and context. It's the function's responsibility to
        # call execute(sql, params, many, context).
        self.execute_wrappers: list[Any] = []

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__} vendor='postgresql'>"

    def __del__(self) -> None:
        # Safety net for wrappers GC'd without an explicit close() —
        # e.g. inside a short-lived `asyncio.to_thread` context copy.
        # Returns the pooled connection to the pool. Guards handle
        # interpreter shutdown, when attrs may already be cleared.
        conn = getattr(self, "connection", None)
        if conn is None:
            return
        source = getattr(self, "_source", None)
        if source is None:
            return
        try:
            source.release(conn)
        except Exception:
            pass

    @property
    def settings_dict(self) -> DatabaseConfig:
        """Config of the server this wrapper talks to. For pool-backed
        wrappers this always reflects the live `POSTGRES_URL`."""
        return self._source.config

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

    # ##### Connection and cursor methods #####

    def _set_autocommit(self, autocommit: bool) -> None:
        """Backend-specific implementation to enable or disable autocommit."""
        assert self.connection is not None
        self.connection.autocommit = autocommit

    def check_constraints(self, table_names: list[str] | None = None) -> None:
        """
        Check constraints by setting them to immediate. Return them to deferred
        afterward.
        """
        with self.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")

    def make_debug_cursor(self, cursor: psycopg.Cursor[Any]) -> CursorDebugWrapper:
        return CursorDebugWrapper(cursor, self)

    # ##### Connection lifecycle #####

    def connect(self) -> None:
        """Connect to the database. Assume that the connection is closed."""
        self.connection = self._source.acquire()
        self.set_autocommit(True)

    def ensure_connection(self) -> None:
        """Guarantee that a connection to the database is established."""
        if self.connection is None:
            self.connect()

    # ##### PEP-249 connection method wrappers #####

    def _prepare_cursor(self, cursor: psycopg.Cursor[Any]) -> utils.CursorWrapper:
        """
        Validate the connection is usable and perform database cursor wrapping.
        """
        if self.queries_logged:
            wrapped_cursor = self.make_debug_cursor(cursor)
        else:
            wrapped_cursor = self.make_cursor(cursor)
        return wrapped_cursor

    def _cursor(self) -> utils.CursorWrapper:
        self.ensure_connection()
        assert self.connection is not None
        return self._prepare_cursor(self.connection.cursor())

    def _commit(self) -> None:
        if self.connection is not None:
            with debug_transaction(self, "COMMIT"):
                return self.connection.commit()

    def _rollback(self) -> None:
        if self.connection is not None:
            with debug_transaction(self, "ROLLBACK"):
                return self.connection.rollback()

    # ##### Generic wrappers for PEP-249 connection methods #####

    def cursor(self) -> utils.CursorWrapper:
        """Create a cursor, opening a connection if necessary."""
        return self._cursor()

    def commit(self) -> None:
        """Commit a transaction and reset the dirty flag."""
        self.validate_no_atomic_block()
        self._commit()
        self.run_commit_hooks_on_set_autocommit_on = True

    def rollback(self) -> None:
        """Roll back a transaction and reset the dirty flag."""
        self.validate_no_atomic_block()
        self._rollback()
        self.needs_rollback = False
        self.run_on_commit = []

    def close(self) -> None:
        """Close the connection to the database."""
        # Closing mid-atomic would reopen a fresh autocommit connection on
        # the next cursor() and silently run the rest of the block outside
        # its transaction. Callers that drop a connection during error
        # recovery (see Atomic.__exit__) unwind the atomic state first.
        self.validate_no_atomic_block()

        self.run_on_commit = []
        if self.connection is None:
            return
        try:
            self._source.release(self.connection)
        finally:
            # Null the reference so __del__ (and ensure_connection) can't
            # touch an already-released psycopg connection.
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

        self._savepoint(sid)

        return sid

    def savepoint_rollback(self, sid: str) -> None:
        """
        Roll back to a savepoint. Do nothing if in autocommit mode.
        """
        if self.get_autocommit():
            return

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
        """
        Enable or disable autocommit.

        Used internally by atomic() to manage transactions. Don't call this
        directly — use atomic() instead.
        """
        self.validate_no_atomic_block()
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

    # ##### Miscellaneous #####

    def make_cursor(self, cursor: psycopg.Cursor[Any]) -> utils.CursorWrapper:
        """Create a cursor without debug logging."""
        return utils.CursorWrapper(cursor, self)

    def schema_editor(self, *args: Any, **kwargs: Any) -> DatabaseSchemaEditor:
        """Return a new instance of the schema editor."""
        return DatabaseSchemaEditor(self, *args, **kwargs)

    def on_commit(self, func: Any, robust: bool = False) -> None:
        if not callable(func):
            raise TypeError("on_commit()'s callback must be a callable.")
        if self.in_atomic_block:
            # Transaction in progress; save for execution on commit.
            self.run_on_commit.append((set(self.savepoint_ids), func, robust))
        else:
            # No transaction in progress; execute immediately.
            if robust:
                try:
                    func()
                except Exception as e:
                    logger.error(
                        "Error calling on_commit() handler",
                        exc_info=True,
                        extra={"handler": func.__qualname__, "error": str(e)},
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
                        "Error calling on_commit() handler during transaction",
                        exc_info=True,
                        extra={"handler": func.__qualname__, "error": str(e)},
                    )
            else:
                func()

    @contextmanager
    def execute_wrapper(self, wrapper: Any) -> Generator[None]:
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
        return psycopg.ClientCursor(self.connection).mogrify(
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
        if isinstance(output_field, GenericIPAddressField | TimeField | UUIDField):
            # PostgreSQL will resolve a union as type 'text' if input types are
            # 'unknown'.
            # https://www.postgresql.org/docs/current/typeconv-union-case.html
            # These fields cannot be implicitly cast back in the default
            # PostgreSQL configuration so we need to explicitly cast them.
            # We must also remove components of the type within brackets:
            # varchar(255) -> varchar.
            db_type = output_field.db_type()
            if db_type:
                return "CAST(%s AS {})".format(db_type.split("(")[0])
        return "%s"

    # ##### Introspection methods #####

    def table_names(
        self, cursor: CursorWrapper | None = None, include_views: bool = False
    ) -> list[str]:
        """
        Return a list of names of all tables that exist in the database.
        Sort the returned table list by Python's default sorting. Do NOT use
        the database's ORDER BY here to avoid subtle differences in sorting
        order between databases.
        """

        def get_names(cursor: CursorWrapper) -> list[str]:
            return sorted(
                ti.name
                for ti in self.get_table_list(cursor)
                if include_views or ti.type == "t"
            )

        if cursor is None:
            with self.cursor() as cursor:
                return get_names(cursor)
        return get_names(cursor)

    def get_table_list(self, cursor: CursorWrapper) -> Sequence[TableInfo]:
        """
        Return an unsorted list of TableInfo named tuples of all tables and
        views that exist in the database.
        """
        cursor.execute(
            """
            SELECT
                c.relname,
                CASE
                    WHEN c.relispartition THEN 'p'
                    WHEN c.relkind IN ('m', 'v') THEN 'v'
                    ELSE 't'
                END,
                obj_description(c.oid, 'pg_class')
            FROM pg_catalog.pg_class c
            LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('f', 'm', 'p', 'r', 'v')
                AND n.nspname NOT IN ('pg_catalog', 'pg_toast')
                AND pg_catalog.pg_table_is_visible(c.oid)
        """
        )
        return [
            TableInfo(*row)
            for row in cursor.fetchall()
            if row[0] not in self.ignored_tables
        ]

    def plain_table_names(
        self, only_existing: bool = False, include_views: bool = True
    ) -> list[str]:
        """
        Return a list of all table names that have associated Plain models and
        are in INSTALLED_PACKAGES.

        If only_existing is True, include only the tables in the database.
        """
        tables = set()
        for model in get_migratable_models():
            tables.add(model.model_options.db_table)
            tables.update(
                f.m2m_db_table() for f in model._model_meta.local_many_to_many
            )
        tables = list(tables)
        if only_existing:
            existing_tables = set(self.table_names(include_views=include_views))
            tables = [t for t in tables if t in existing_tables]
        return tables

    def get_sequences(
        self, cursor: CursorWrapper, table_name: str, table_fields: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        """
        Return a list of introspected sequences for table_name. Each sequence
        is a dict: {'table': <table_name>, 'column': <column_name>, 'name': <sequence_name>}.
        """
        cursor.execute(
            """
            SELECT
                s.relname AS sequence_name,
                a.attname AS colname
            FROM
                pg_class s
                JOIN pg_depend d ON d.objid = s.oid
                    AND d.classid = 'pg_class'::regclass
                    AND d.refclassid = 'pg_class'::regclass
                JOIN pg_attribute a ON d.refobjid = a.attrelid
                    AND d.refobjsubid = a.attnum
                JOIN pg_class tbl ON tbl.oid = d.refobjid
                    AND tbl.relname = %s
                    AND pg_catalog.pg_table_is_visible(tbl.oid)
            WHERE
                s.relkind = 'S';
        """,
            [table_name],
        )
        return [
            {"name": row[0], "table": table_name, "column": row[1]}
            for row in cursor.fetchall()
        ]

    def get_constraints(
        self, cursor: CursorWrapper, table_name: str
    ) -> dict[str, dict[str, Any]]:
        """
        Retrieve any constraints or keys (unique, pk, fk, check, index) across
        one or more columns. Also retrieve the definition of expression-based
        indexes.
        """
        constraints: dict[str, dict[str, Any]] = {}
        # Loop over the key table, collecting things as constraints. The column
        # array must return column names in the same order in which they were
        # created.
        cursor.execute(
            """
            SELECT
                c.conname,
                array(
                    SELECT attname
                    FROM unnest(c.conkey) WITH ORDINALITY cols(colid, arridx)
                    JOIN pg_attribute AS ca ON cols.colid = ca.attnum
                    WHERE ca.attrelid = c.conrelid
                    ORDER BY cols.arridx
                ),
                c.contype,
                (SELECT fkc.relname || '.' || fka.attname
                FROM pg_attribute AS fka
                JOIN pg_class AS fkc ON fka.attrelid = fkc.oid
                WHERE fka.attrelid = c.confrelid AND fka.attnum = c.confkey[1]),
                cl.reloptions,
                c.convalidated,
                pg_get_constraintdef(c.oid),
                c.confdeltype
            FROM pg_constraint AS c
            JOIN pg_class AS cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND pg_catalog.pg_table_is_visible(cl.oid)
        """,
            [table_name],
        )
        for (
            constraint,
            columns,
            kind,
            used_cols,
            options,
            validated,
            constraintdef,
            confdeltype,
        ) in cursor.fetchall():
            constraints[constraint] = {
                "columns": columns,
                "primary_key": kind == "p",
                "unique": kind in ["p", "u"],
                "foreign_key": tuple(used_cols.split(".", 1)) if kind == "f" else None,
                "check": kind == "c",
                "contype": kind,
                "index": False,
                "definition": constraintdef,
                "options": options,
                "validated": validated,
                "on_delete_action": confdeltype if kind == "f" else None,
            }
        # Now get indexes
        cursor.execute(
            """
            SELECT
                indexname,
                array_agg(attname ORDER BY arridx),
                indisunique,
                indisprimary,
                array_agg(ordering ORDER BY arridx),
                amname,
                exprdef,
                s2.attoptions,
                s2.indisvalid
            FROM (
                SELECT
                    c2.relname as indexname, idx.*, attr.attname, am.amname,
                    pg_get_indexdef(idx.indexrelid) AS exprdef,
                    CASE am.amname
                        WHEN %s THEN
                            CASE (option & 1)
                                WHEN 1 THEN 'DESC' ELSE 'ASC'
                            END
                    END as ordering,
                    c2.reloptions as attoptions
                FROM (
                    SELECT *
                    FROM
                        pg_index i,
                        unnest(i.indkey, i.indoption)
                            WITH ORDINALITY koi(key, option, arridx)
                ) idx
                LEFT JOIN pg_class c ON idx.indrelid = c.oid
                LEFT JOIN pg_class c2 ON idx.indexrelid = c2.oid
                LEFT JOIN pg_am am ON c2.relam = am.oid
                LEFT JOIN
                    pg_attribute attr ON attr.attrelid = c.oid AND attr.attnum = idx.key
                WHERE c.relname = %s AND pg_catalog.pg_table_is_visible(c.oid)
            ) s2
            GROUP BY indexname, indisunique, indisprimary, amname, exprdef, attoptions, indisvalid;
        """,
            [self.index_default_access_method, table_name],
        )
        for (
            index,
            columns,
            unique,
            primary,
            orders,
            type_,
            definition,
            options,
            valid,
        ) in cursor.fetchall():
            if index not in constraints:
                basic_index = (
                    type_ == self.index_default_access_method and options is None
                )
                constraints[index] = {
                    "columns": columns if columns != [None] else [],
                    "orders": orders if orders != [None] else [],
                    "primary_key": primary,
                    "unique": unique,
                    "foreign_key": None,
                    "check": False,
                    "index": True,
                    "type": Index.suffix if basic_index else type_,
                    "definition": definition,
                    "options": options,
                    "valid": valid,
                }
        return constraints


class CursorDebugWrapper(BaseCursorDebugWrapper):
    def copy(self, statement: Any) -> Any:
        with self.debug_sql(statement):
            return self.cursor.copy(statement)
