from __future__ import annotations

import functools
import logging
import time
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from hashlib import md5
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

import psycopg

from plain.models.db import NotSupportedError
from plain.models.otel import db_span
from plain.utils.dateparse import parse_time

if TYPE_CHECKING:
    from plain.models.postgres.wrapper import DatabaseWrapper

logger = logging.getLogger("plain.models.postgres")


class CursorWrapper:
    def __init__(self, cursor: Any, db: DatabaseWrapper) -> None:
        self.cursor = cursor
        self.db = db

    WRAP_ERROR_ATTRS = frozenset(["nextset"])

    def __getattr__(self, attr: str) -> Any:
        cursor_attr = getattr(self.cursor, attr)
        if attr in CursorWrapper.WRAP_ERROR_ATTRS:
            return self.db.wrap_database_errors(cursor_attr)
        else:
            return cursor_attr

    def __iter__(self) -> Iterator[tuple[Any, ...]]:
        with self.db.wrap_database_errors:
            yield from self.cursor

    def fetchone(self) -> tuple[Any, ...] | None:
        with self.db.wrap_database_errors:
            return self.cursor.fetchone()

    def fetchmany(self, size: int | None = None) -> list[tuple[Any, ...]]:
        with self.db.wrap_database_errors:
            if size is None:
                return self.cursor.fetchmany()
            return self.cursor.fetchmany(size)

    def fetchall(self) -> list[tuple[Any, ...]]:
        with self.db.wrap_database_errors:
            return self.cursor.fetchall()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Close instead of passing through to avoid backend-specific behavior
        # (#17671). Catch errors liberally because errors in cleanup code
        # aren't useful.
        try:
            self.close()
        except psycopg.Error:
            pass

    # The following methods cannot be implemented in __getattr__, because the
    # code must run when the method is invoked, not just when it is accessed.

    def callproc(
        self,
        procname: str,
        params: Sequence[Any] | None = None,
        kparams: Mapping[str, Any] | None = None,
    ) -> Any:
        # Keyword parameters for callproc aren't supported in PEP 249.
        # PostgreSQL's psycopg doesn't support them either.
        if kparams is not None:
            raise NotSupportedError(
                "Keyword parameters for callproc are not supported."
            )
        self.db.validate_no_broken_transaction()
        with self.db.wrap_database_errors:
            if params is None:
                return self.cursor.callproc(procname)
            return self.cursor.callproc(procname, params)

    def execute(
        self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> Self:
        return self._execute_with_wrappers(
            sql, params, many=False, executor=self._execute
        )

    def executemany(self, sql: str, param_list: Sequence[Sequence[Any]]) -> Self:
        return self._execute_with_wrappers(
            sql, param_list, many=True, executor=self._executemany
        )

    def _execute_with_wrappers(
        self, sql: str, params: Any, many: bool, executor: Any
    ) -> Self:
        context: dict[str, Any] = {"connection": self.db, "cursor": self}
        for wrapper in reversed(self.db.execute_wrappers):
            executor = functools.partial(wrapper, executor)
        executor(sql, params, many, context)
        return self

    def _execute(self, sql: str, params: Any, *ignored_wrapper_args: Any) -> None:
        # Wrap in an OpenTelemetry span with standard attributes.
        with db_span(self.db, sql, params=params):
            self.db.validate_no_broken_transaction()
            with self.db.wrap_database_errors:
                if params is None:
                    self.cursor.execute(sql)
                else:
                    self.cursor.execute(sql, params)

    def _executemany(
        self, sql: str, param_list: Any, *ignored_wrapper_args: Any
    ) -> None:
        with db_span(self.db, sql, many=True, params=param_list):
            self.db.validate_no_broken_transaction()
            with self.db.wrap_database_errors:
                self.cursor.executemany(sql, param_list)


class CursorDebugWrapper(CursorWrapper):
    # XXX callproc isn't instrumented at this time.

    def execute(
        self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> Self:
        with self.debug_sql(sql, params, use_last_executed_query=True):
            super().execute(sql, params)
        return self

    def executemany(self, sql: str, param_list: Sequence[Sequence[Any]]) -> Self:
        with self.debug_sql(sql, param_list, many=True):
            super().executemany(sql, param_list)
        return self

    @contextmanager
    def debug_sql(
        self,
        sql: str | None = None,
        params: Any = None,
        use_last_executed_query: bool = False,
        many: bool = False,
    ) -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
        finally:
            stop = time.monotonic()
            duration = stop - start
            if use_last_executed_query:
                sql = self.db.last_executed_query(self.cursor, sql, params)  # type: ignore[arg-type]
            try:
                times = len(params) if many else ""
            except TypeError:
                # params could be an iterator.
                times = "?"
            self.db.queries_log.append(
                {
                    "sql": f"{times} times: {sql}" if many else sql,
                    "time": f"{duration:.3f}",
                }
            )
            logger.debug(
                "(%.3f) %s; args=%s",
                duration,
                sql,
                params,
                extra={
                    "duration": duration,
                    "sql": sql,
                    "params": params,
                },
            )


@contextmanager
def debug_transaction(
    connection: DatabaseWrapper, sql: str
) -> Generator[None, None, None]:
    start = time.monotonic()
    try:
        yield
    finally:
        if connection.queries_logged:
            stop = time.monotonic()
            duration = stop - start
            connection.queries_log.append(
                {
                    "sql": f"{sql}",
                    "time": f"{duration:.3f}",
                }
            )
            logger.debug(
                "(%.3f) %s; args=%s",
                duration,
                sql,
                None,
                extra={
                    "duration": duration,
                    "sql": sql,
                },
            )


def split_tzname_delta(tzname: str) -> tuple[str, str | None, str | None]:
    """
    Split a time zone name into a 3-tuple of (name, sign, offset).
    """
    for sign in ["+", "-"]:
        if sign in tzname:
            name, offset = tzname.rsplit(sign, 1)
            if offset and parse_time(offset):
                return name, sign, offset
    return tzname, None, None


###############################################
# Converters from Python to database (string) #
###############################################


def split_identifier(identifier: str) -> tuple[str, str]:
    """
    Split an SQL identifier into a two element tuple of (namespace, name).

    The identifier could be a table, column, or sequence name might be prefixed
    by a namespace.
    """
    try:
        namespace, name = identifier.split('"."')
    except ValueError:
        namespace, name = "", identifier
    return namespace.strip('"'), name.strip('"')


def truncate_name(identifier: str, length: int | None = None, hash_len: int = 4) -> str:
    """
    Shorten an SQL identifier to a repeatable mangled version with the given
    length.

    If a quote stripped name contains a namespace, e.g. USERNAME"."TABLE,
    truncate the table portion only.
    """
    namespace, name = split_identifier(identifier)

    if length is None or len(name) <= length:
        return identifier

    digest = names_digest(name, length=hash_len)
    return "{}{}{}".format(
        f'{namespace}"."' if namespace else "",
        name[: length - hash_len],
        digest,
    )


def names_digest(*args: str, length: int) -> str:
    """
    Generate a 32-bit digest of a set of arguments that can be used to shorten
    identifying names.
    """
    h = md5(usedforsecurity=False)
    for arg in args:
        h.update(arg.encode())
    return h.hexdigest()[:length]


def strip_quotes(table_name: str) -> str:
    """
    Strip quotes off of quoted table names to make them safe for use in index
    names, sequence names, etc.
    """
    has_quotes = table_name.startswith('"') and table_name.endswith('"')
    return table_name[1:-1] if has_quotes else table_name
