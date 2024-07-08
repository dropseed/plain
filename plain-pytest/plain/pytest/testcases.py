import logging
import sys
import unittest
from contextlib import contextmanager
from difflib import get_close_matches
from unittest.suite import _DebugResult

from plain.exceptions import ImproperlyConfigured
from plain.internal.legacy.management import call_command
from plain.internal.legacy.management.color import no_style
from plain.internal.legacy.management.sql import emit_post_migrate_signal
from plain.models import transaction
from plain.models.db import DEFAULT_DB_ALIAS, connections
from plain.packages import packages
from plain.test.client import Client
from plain.test.utils import (
    modify_settings,
    override_settings,
)

logger = logging.getLogger("plain.test")

__all__ = (
    "TestCase",
    "TransactionTestCase",
)


class DatabaseOperationForbidden(AssertionError):
    pass


class _DatabaseFailure:
    def __init__(self, wrapped, message):
        self.wrapped = wrapped
        self.message = message

    def __call__(self):
        raise DatabaseOperationForbidden(self.message)


class TransactionTestCase(unittest.TestCase):
    # The class we'll use for the test client self.client.
    # Can be overridden in derived classes.
    client_class = Client
    _overridden_settings = None
    _modified_settings = None

    databases = set()
    _disallowed_database_msg = (
        "Database %(operation)s to %(alias)r are not allowed in SimpleTestCase "
        "subclasses. Either subclass TestCase or TransactionTestCase to ensure "
        "proper test isolation or add %(alias)r to %(test)s.databases to silence "
        "this failure."
    )
    _disallowed_connection_methods = [
        ("connect", "connections"),
        ("temporary_connection", "connections"),
        ("cursor", "queries"),
        ("chunked_cursor", "queries"),
    ]

    # Subclasses can ask for resetting of auto increment sequence before each
    # test case
    reset_sequences = False

    # Subclasses can enable only a subset of packages for faster tests
    available_packages = None

    # Subclasses can define fixtures which will be automatically installed.
    fixtures = None

    databases = {DEFAULT_DB_ALIAS}
    _disallowed_database_msg = (
        "Database %(operation)s to %(alias)r are not allowed in this test. "
        "Add %(alias)r to %(test)s.databases to ensure proper test isolation "
        "and silence this failure."
    )

    # If transactions aren't available, Plain will serialize the database
    # contents into a fixture during setup and flush and reload them
    # during teardown (as flush does not restore data from migrations).
    # This can be slow; this flag allows enabling on a per-case basis.
    serialized_rollback = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls._overridden_settings:
            cls._cls_overridden_context = override_settings(**cls._overridden_settings)
            cls._cls_overridden_context.enable()
            cls.addClassCleanup(cls._cls_overridden_context.disable)
        if cls._modified_settings:
            cls._cls_modified_context = modify_settings(cls._modified_settings)
            cls._cls_modified_context.enable()
            cls.addClassCleanup(cls._cls_modified_context.disable)
        cls._add_databases_failures()
        cls.addClassCleanup(cls._remove_databases_failures)

    @classmethod
    def _validate_databases(cls):
        if cls.databases == "__all__":
            return frozenset(connections)
        for alias in cls.databases:
            if alias not in connections:
                message = (
                    "{}.{}.databases refers to {!r} which is not defined in "
                    "settings.DATABASES.".format(
                        cls.__module__,
                        cls.__qualname__,
                        alias,
                    )
                )
                close_matches = get_close_matches(alias, list(connections))
                if close_matches:
                    message += " Did you mean %r?" % close_matches[0]
                raise ImproperlyConfigured(message)
        return frozenset(cls.databases)

    @classmethod
    def _add_databases_failures(cls):
        cls.databases = cls._validate_databases()
        for alias in connections:
            if alias in cls.databases:
                continue
            connection = connections[alias]
            for name, operation in cls._disallowed_connection_methods:
                message = cls._disallowed_database_msg % {
                    "test": f"{cls.__module__}.{cls.__qualname__}",
                    "alias": alias,
                    "operation": operation,
                }
                method = getattr(connection, name)
                setattr(connection, name, _DatabaseFailure(method, message))

    @classmethod
    def _remove_databases_failures(cls):
        for alias in connections:
            if alias in cls.databases:
                continue
            connection = connections[alias]
            for name, _ in cls._disallowed_connection_methods:
                method = getattr(connection, name)
                setattr(connection, name, method.wrapped)

    def __call__(self, result=None):
        """
        Wrapper around default __call__ method to perform common Plain test
        set up. This means that user-defined Test Cases aren't required to
        include a call to super().setUp().
        """
        self._setup_and_call(result)

    def debug(self):
        """Perform the same as __call__(), without catching the exception."""
        debug_result = _DebugResult()
        self._setup_and_call(debug_result, debug=True)

    def _setup_and_call(self, result, debug=False):
        """
        Perform the following in order: pre-setup, run test, post-teardown,
        skipping pre/post hooks if test is set to be skipped.

        If debug=True, reraise any errors in setup and use super().debug()
        instead of __call__() to run the test.
        """
        testMethod = getattr(self, self._testMethodName)
        skipped = getattr(self.__class__, "__unittest_skip__", False) or getattr(
            testMethod, "__unittest_skip__", False
        )

        if not skipped:
            try:
                self._pre_setup()
            except Exception:
                if debug:
                    raise
                result.addError(self, sys.exc_info())
                return
        if debug:
            super().debug()
        else:
            super().__call__(result)
        if not skipped:
            try:
                self._post_teardown()
            except Exception:
                if debug:
                    raise
                result.addError(self, sys.exc_info())
                return

    def _pre_setup(self):
        """
        Perform pre-test setup:
        * Create a test client.
        * Clear the mail test outbox.
        """
        self.client = self.client_class()

        try:
            from plain import mail

            mail.outbox = []
        except ImportError:
            pass

        if self.available_packages is not None:
            packages.set_available_packages(self.available_packages)
            for db_name in self._databases_names(include_mirrors=False):
                emit_post_migrate_signal(verbosity=0, interactive=False, db=db_name)
        try:
            self._fixture_setup()
        except Exception:
            if self.available_packages is not None:
                packages.unset_available_packages()
            raise
        # Clear the queries_log so that it's less likely to overflow (a single
        # test probably won't execute 9K queries). If queries_log overflows,
        # then assertNumQueries() doesn't work.
        for db_name in self._databases_names(include_mirrors=False):
            connections[db_name].queries_log.clear()

    def _post_teardown(self):
        """
        Perform post-test things:
        * Flush the contents of the database to leave a clean slate. If the
          class has an 'available_packages' attribute, don't fire post_migrate.
        * Force-close the connection so the next test gets a clean cursor.
        """
        try:
            self._fixture_teardown()
            if self._should_reload_connections():
                # Some DB cursors include SQL statements as part of cursor
                # creation. If you have a test that does a rollback, the effect
                # of these statements is lost, which can affect the operation of
                # tests (e.g., losing a timezone setting causing objects to be
                # created with the wrong time). To make sure this doesn't
                # happen, get a clean connection at the start of every test.
                for conn in connections.all(initialized_only=True):
                    conn.close()
        finally:
            if self.available_packages is not None:
                packages.unset_available_packages()

    def settings(self, **kwargs):
        """
        A context manager that temporarily sets a setting and reverts to the
        original value when exiting the context.
        """
        return override_settings(**kwargs)

    def modify_settings(self, **kwargs):
        """
        A context manager that temporarily applies changes a list setting and
        reverts back to the original value when exiting the context.
        """
        return modify_settings(**kwargs)

    @classmethod
    def _databases_names(cls, include_mirrors=True):
        # Only consider allowed database aliases, including mirrors or not.
        return [
            alias
            for alias in connections
            if alias in cls.databases
            and (
                include_mirrors
                or not connections[alias].settings_dict["TEST"]["MIRROR"]
            )
        ]

    def _reset_sequences(self, db_name):
        conn = connections[db_name]
        if conn.features.supports_sequence_reset:
            sql_list = conn.ops.sequence_reset_by_name_sql(
                no_style(), conn.introspection.sequence_list()
            )
            if sql_list:
                with transaction.atomic(using=db_name):
                    with conn.cursor() as cursor:
                        for sql in sql_list:
                            cursor.execute(sql)

    def _fixture_setup(self):
        for db_name in self._databases_names(include_mirrors=False):
            # Reset sequences
            if self.reset_sequences:
                self._reset_sequences(db_name)

            # Provide replica initial data from migrated packages, if needed.
            # if self.serialized_rollback and hasattr(
            #     connections[db_name], "_test_serialized_contents"
            # ):
            #     if self.available_packages is not None:
            #         packages.unset_available_packages()
            #     connections[db_name].creation.deserialize_db_from_string(
            #         connections[db_name]._test_serialized_contents
            #     )
            #     if self.available_packages is not None:
            #         packages.set_available_packages(self.available_packages)

            if self.fixtures:
                # We have to use this slightly awkward syntax due to the fact
                # that we're using *args and **kwargs together.
                call_command(
                    "loaddata", *self.fixtures, **{"verbosity": 0, "database": db_name}
                )

    def _should_reload_connections(self):
        return True

    def _fixture_teardown(self):
        # Allow TRUNCATE ... CASCADE and don't emit the post_migrate signal
        # when flushing only a subset of the packages
        for db_name in self._databases_names(include_mirrors=False):
            # Flush the database
            inhibit_post_migrate = (
                self.available_packages is not None
                or (  # Inhibit the post_migrate signal when using serialized
                    # rollback to avoid trying to recreate the serialized data.
                    self.serialized_rollback
                    # and hasattr(connections[db_name], "_test_serialized_contents")
                )
            )
            call_command(
                "flush",
                verbosity=0,
                interactive=False,
                database=db_name,
                reset_sequences=False,
                allow_cascade=self.available_packages is not None,
                inhibit_post_migrate=inhibit_post_migrate,
            )


def connections_support_transactions(aliases=None):
    """
    Return whether or not all (or specified) connections support
    transactions.
    """
    conns = (
        connections.all()
        if aliases is None
        else (connections[alias] for alias in aliases)
    )
    return all(conn.features.supports_transactions for conn in conns)


class TestCase(TransactionTestCase):
    """
    Similar to TransactionTestCase, but use `transaction.atomic()` to achieve
    test isolation.

    In most situations, TestCase should be preferred to TransactionTestCase as
    it allows faster execution. However, there are some situations where using
    TransactionTestCase might be necessary (e.g. testing some transactional
    behavior).

    On database backends with no transaction support, TestCase behaves as
    TransactionTestCase.
    """

    @classmethod
    def _enter_atomics(cls):
        """Open atomic blocks for multiple databases."""
        atomics = {}
        for db_name in cls._databases_names():
            atomic = transaction.atomic(using=db_name)
            atomic._from_testcase = True
            atomic.__enter__()
            atomics[db_name] = atomic
        return atomics

    @classmethod
    def _rollback_atomics(cls, atomics):
        """Rollback atomic blocks opened by the previous method."""
        for db_name in reversed(cls._databases_names()):
            transaction.set_rollback(True, using=db_name)
            atomics[db_name].__exit__(None, None, None)

    @classmethod
    def _databases_support_transactions(cls):
        return connections_support_transactions(cls.databases)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls._databases_support_transactions():
            return
        cls.cls_atomics = cls._enter_atomics()

        if cls.fixtures:
            for db_name in cls._databases_names(include_mirrors=False):
                try:
                    call_command(
                        "loaddata",
                        *cls.fixtures,
                        **{"verbosity": 0, "database": db_name},
                    )
                except Exception:
                    cls._rollback_atomics(cls.cls_atomics)
                    raise

    @classmethod
    def tearDownClass(cls):
        if cls._databases_support_transactions():
            cls._rollback_atomics(cls.cls_atomics)
            for conn in connections.all(initialized_only=True):
                conn.close()
        super().tearDownClass()

    def _should_reload_connections(self):
        if self._databases_support_transactions():
            return False
        return super()._should_reload_connections()

    def _fixture_setup(self):
        if not self._databases_support_transactions():
            return super()._fixture_setup()

        if self.reset_sequences:
            raise TypeError("reset_sequences cannot be used on TestCase instances")
        self.atomics = self._enter_atomics()

    def _fixture_teardown(self):
        if not self._databases_support_transactions():
            return super()._fixture_teardown()
        try:
            for db_name in reversed(self._databases_names()):
                if self._should_check_constraints(connections[db_name]):
                    connections[db_name].check_constraints()
        finally:
            self._rollback_atomics(self.atomics)

    def _should_check_constraints(self, connection):
        return (
            connection.features.can_defer_constraint_checks
            and not connection.needs_rollback
            and connection.is_usable()
        )

    @classmethod
    @contextmanager
    def captureOnCommitCallbacks(cls, *, using=DEFAULT_DB_ALIAS, execute=False):
        """Context manager to capture transaction.on_commit() callbacks."""
        callbacks = []
        start_count = len(connections[using].run_on_commit)
        try:
            yield callbacks
        finally:
            while True:
                callback_count = len(connections[using].run_on_commit)
                for _, callback, robust in connections[using].run_on_commit[
                    start_count:
                ]:
                    callbacks.append(callback)
                    if execute:
                        if robust:
                            try:
                                callback()
                            except Exception as e:
                                logger.error(
                                    f"Error calling {callback.__qualname__} in "
                                    f"on_commit() (%s).",
                                    e,
                                    exc_info=True,
                                )
                        else:
                            callback()

                if callback_count == len(connections[using].run_on_commit):
                    break
                start_count = callback_count
