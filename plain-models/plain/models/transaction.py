from contextlib import ContextDecorator, contextmanager

from plain.models.db import DatabaseError, Error, ProgrammingError, db_connection


class TransactionManagementError(ProgrammingError):
    """Transaction management is used improperly."""

    pass


@contextmanager
def mark_for_rollback_on_error():
    """
    Internal low-level utility to mark a transaction as "needs rollback" when
    an exception is raised while not enforcing the enclosed block to be in a
    transaction. This is needed by Model.save() and friends to avoid starting a
    transaction when in autocommit mode and a single query is executed.

    It's equivalent to:

        if db_connection.get_autocommit():
            yield
        else:
            with transaction.atomic(savepoint=False):
                yield

    but it uses low-level utilities to avoid performance overhead.
    """
    try:
        yield
    except Exception as exc:
        if db_connection.in_atomic_block:
            db_connection.needs_rollback = True
            db_connection.rollback_exc = exc
        raise


def on_commit(func, robust=False):
    """
    Register `func` to be called when the current transaction is committed.
    If the current transaction is rolled back, `func` will not be called.
    """
    db_connection.on_commit(func, robust)


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
    db_connection. None denotes the absence of a savepoint.

    This allows reentrancy even if the same AtomicWrapper is reused. For
    example, it's possible to define `oa = atomic('other')` and use `@oa` or
    `with oa:` multiple times.

    Since database connections are thread-local, this is thread-safe.

    An atomic block can be tagged as durable. In this case, raise a
    RuntimeError if it's nested within another atomic block. This guarantees
    that database changes in a durable block are committed to the database when
    the block exists without error.

    This is a private API.
    """

    def __init__(self, savepoint, durable):
        self.savepoint = savepoint
        self.durable = durable
        self._from_testcase = False

    def __enter__(self):
        if (
            self.durable
            and db_connection.atomic_blocks
            and not db_connection.atomic_blocks[-1]._from_testcase
        ):
            raise RuntimeError(
                "A durable atomic block cannot be nested within another atomic block."
            )
        if not db_connection.in_atomic_block:
            # Reset state when entering an outermost atomic block.
            db_connection.commit_on_exit = True
            db_connection.needs_rollback = False
            if not db_connection.get_autocommit():
                # Pretend we're already in an atomic block to bypass the code
                # that disables autocommit to enter a transaction, and make a
                # note to deal with this case in __exit__.
                db_connection.in_atomic_block = True
                db_connection.commit_on_exit = False

        if db_connection.in_atomic_block:
            # We're already in a transaction; create a savepoint, unless we
            # were told not to or we're already waiting for a rollback. The
            # second condition avoids creating useless savepoints and prevents
            # overwriting needs_rollback until the rollback is performed.
            if self.savepoint and not db_connection.needs_rollback:
                sid = db_connection.savepoint()
                db_connection.savepoint_ids.append(sid)
            else:
                db_connection.savepoint_ids.append(None)
        else:
            db_connection.set_autocommit(
                False, force_begin_transaction_with_broken_autocommit=True
            )
            db_connection.in_atomic_block = True

        if db_connection.in_atomic_block:
            db_connection.atomic_blocks.append(self)

    def __exit__(self, exc_type, exc_value, traceback):
        if db_connection.in_atomic_block:
            db_connection.atomic_blocks.pop()

        if db_connection.savepoint_ids:
            sid = db_connection.savepoint_ids.pop()
        else:
            # Prematurely unset this flag to allow using commit or rollback.
            db_connection.in_atomic_block = False

        try:
            if db_connection.closed_in_transaction:
                # The database will perform a rollback by itself.
                # Wait until we exit the outermost block.
                pass

            elif exc_type is None and not db_connection.needs_rollback:
                if db_connection.in_atomic_block:
                    # Release savepoint if there is one
                    if sid is not None:
                        try:
                            db_connection.savepoint_commit(sid)
                        except DatabaseError:
                            try:
                                db_connection.savepoint_rollback(sid)
                                # The savepoint won't be reused. Release it to
                                # minimize overhead for the database server.
                                db_connection.savepoint_commit(sid)
                            except Error:
                                # If rolling back to a savepoint fails, mark for
                                # rollback at a higher level and avoid shadowing
                                # the original exception.
                                db_connection.needs_rollback = True
                            raise
                else:
                    # Commit transaction
                    try:
                        db_connection.commit()
                    except DatabaseError:
                        try:
                            db_connection.rollback()
                        except Error:
                            # An error during rollback means that something
                            # went wrong with the db_connection. Drop it.
                            db_connection.close()
                        raise
            else:
                # This flag will be set to True again if there isn't a savepoint
                # allowing to perform the rollback at this level.
                db_connection.needs_rollback = False
                if db_connection.in_atomic_block:
                    # Roll back to savepoint if there is one, mark for rollback
                    # otherwise.
                    if sid is None:
                        db_connection.needs_rollback = True
                    else:
                        try:
                            db_connection.savepoint_rollback(sid)
                            # The savepoint won't be reused. Release it to
                            # minimize overhead for the database server.
                            db_connection.savepoint_commit(sid)
                        except Error:
                            # If rolling back to a savepoint fails, mark for
                            # rollback at a higher level and avoid shadowing
                            # the original exception.
                            db_connection.needs_rollback = True
                else:
                    # Roll back transaction
                    try:
                        db_connection.rollback()
                    except Error:
                        # An error during rollback means that something
                        # went wrong with the db_connection. Drop it.
                        db_connection.close()

        finally:
            # Outermost block exit when autocommit was enabled.
            if not db_connection.in_atomic_block:
                if db_connection.closed_in_transaction:
                    db_connection.connection = None
                else:
                    db_connection.set_autocommit(True)
            # Outermost block exit when autocommit was disabled.
            elif not db_connection.savepoint_ids and not db_connection.commit_on_exit:
                if db_connection.closed_in_transaction:
                    db_connection.connection = None
                else:
                    db_connection.in_atomic_block = False


def atomic(func=None, *, savepoint=True, durable=False):
    """Create an atomic transaction context or decorator."""
    if callable(func):
        return Atomic(savepoint, durable)(func)
    return Atomic(savepoint, durable)
