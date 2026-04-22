from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import ContextDecorator, contextmanager
from typing import Any

import psycopg

from plain.postgres.db import get_connection


class TransactionManagementError(psycopg.ProgrammingError):
    """Transaction management is used improperly."""

    pass


@contextmanager
def mark_for_rollback_on_error() -> Generator[None]:
    """
    Internal low-level utility to mark a transaction as "needs rollback" when
    an exception is raised while not enforcing the enclosed block to be in a
    transaction. This is needed by Model.save() and friends to avoid starting a
    transaction when in autocommit mode and a single query is executed.

    It's equivalent to:

        if get_connection().get_autocommit():
            yield
        else:
            with transaction.atomic(savepoint=False):
                yield

    but it uses low-level utilities to avoid performance overhead.
    """
    try:
        yield
    except Exception as exc:
        conn = get_connection()
        if conn.in_atomic_block:
            conn.needs_rollback = True
            conn.rollback_exc = exc
        raise


def on_commit(func: Callable[[], Any], robust: bool = False) -> None:
    """
    Register `func` to be called when the current transaction is committed.
    If the current transaction is rolled back, `func` will not be called.
    """
    get_connection().on_commit(func, robust)


#################################
# Decorators / context managers #
#################################


class Atomic(ContextDecorator):
    """
    Guarantee the atomic execution of a given block.

    An instance can be used either as a decorator or as a context manager.

    When it's used as a decorator, __call__ wraps the execution of the
    decorated function in the instance itself, used as a context manager.

    When it's used as a context manager, __enter__ creates a transaction or a
    savepoint, depending on whether a transaction is already in progress, and
    __exit__ commits the transaction or releases the savepoint on normal exit,
    and rolls back the transaction or to the savepoint on exceptions.

    It's possible to disable the creation of savepoints if the goal is to
    ensure that some code runs within a transaction without creating overhead.

    A stack of savepoints identifiers is maintained as an attribute of the
    connection. None denotes the absence of a savepoint.

    This allows reentrancy even if the same AtomicWrapper is reused. For
    example, it's possible to define `oa = atomic('other')` and use `@oa` or
    `with oa:` multiple times.

    Since database connections are stored per-context (ContextVar), this is thread-safe.

    An atomic block can be tagged as durable. In this case, raise a
    RuntimeError if it's nested within another atomic block. This guarantees
    that database changes in a durable block are committed to the database when
    the block exists without error.

    This is a private API.
    """

    def __init__(self, savepoint: bool, durable: bool) -> None:
        self.savepoint = savepoint
        self.durable = durable
        self._from_testcase = False

    def __enter__(self) -> None:
        conn = get_connection()
        if (
            self.durable
            and conn.atomic_blocks
            and not conn.atomic_blocks[-1]._from_testcase
        ):
            raise RuntimeError(
                "A durable atomic block cannot be nested within another atomic block."
            )
        if not conn.in_atomic_block:
            # Reset state when entering an outermost atomic block.
            conn.needs_rollback = False
        if conn.in_atomic_block:
            # We're already in a transaction; create a savepoint, unless we
            # were told not to or we're already waiting for a rollback. The
            # second condition avoids creating useless savepoints and prevents
            # overwriting needs_rollback until the rollback is performed.
            if self.savepoint and not conn.needs_rollback:
                sid = conn.savepoint()
                conn.savepoint_ids.append(sid)
            else:
                conn.savepoint_ids.append(None)
        else:
            conn.set_autocommit(False)
            conn.in_atomic_block = True

        if conn.in_atomic_block:
            conn.atomic_blocks.append(self)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        conn = get_connection()
        if conn.in_atomic_block:
            conn.atomic_blocks.pop()

        if conn.savepoint_ids:
            sid = conn.savepoint_ids.pop()
        else:
            # Prematurely unset this flag to allow using commit or rollback.
            conn.in_atomic_block = False

        try:
            if exc_type is None and not conn.needs_rollback:
                if conn.in_atomic_block:
                    # Release savepoint if there is one
                    if sid is not None:
                        try:
                            conn.savepoint_commit(sid)
                        except psycopg.DatabaseError:
                            try:
                                conn.savepoint_rollback(sid)
                                # The savepoint won't be reused. Release it to
                                # minimize overhead for the database server.
                                conn.savepoint_commit(sid)
                            except psycopg.Error:
                                # If rolling back to a savepoint fails, mark for
                                # rollback at a higher level and avoid shadowing
                                # the original exception.
                                conn.needs_rollback = True
                            raise
                else:
                    # Commit transaction
                    try:
                        conn.commit()
                    except psycopg.DatabaseError:
                        try:
                            conn.rollback()
                        except psycopg.Error:
                            # An error during rollback means that something
                            # went wrong with the connection. Drop it.
                            conn.close()
                        raise
            else:
                # This flag will be set to True again if there isn't a savepoint
                # allowing to perform the rollback at this level.
                conn.needs_rollback = False
                if conn.in_atomic_block:
                    # Roll back to savepoint if there is one, mark for rollback
                    # otherwise.
                    if sid is None:
                        conn.needs_rollback = True
                    else:
                        try:
                            conn.savepoint_rollback(sid)
                            # The savepoint won't be reused. Release it to
                            # minimize overhead for the database server.
                            conn.savepoint_commit(sid)
                        except psycopg.Error:
                            # If rolling back to a savepoint fails, mark for
                            # rollback at a higher level and avoid shadowing
                            # the original exception.
                            conn.needs_rollback = True
                else:
                    # Roll back transaction
                    try:
                        conn.rollback()
                    except psycopg.Error:
                        # An error during rollback means that something
                        # went wrong with the connection. Drop it.
                        conn.close()

        finally:
            # Outermost block exit when autocommit was enabled. Skip when
            # the connection was dropped during rollback/commit failure —
            # ensure_connection() would otherwise acquire a fresh pool
            # connection just to flip autocommit while the original error
            # is still propagating.
            if not conn.in_atomic_block and conn.connection is not None:
                conn.set_autocommit(True)


def atomic[F: Callable[..., Any]](
    func: F | None = None, *, savepoint: bool = True, durable: bool = False
) -> F | Atomic:
    """Create an atomic transaction context or decorator."""
    if callable(func):
        return Atomic(savepoint, durable)(func)
    return Atomic(savepoint, durable)
