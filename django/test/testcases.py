import difflib
import json
import logging
import posixpath
import sys
import threading
import unittest
import warnings
from collections import Counter
from contextlib import contextmanager
from copy import copy, deepcopy
from difflib import get_close_matches
from functools import wraps
from unittest.suite import _DebugResult
from unittest.util import safe_repr
from urllib.parse import (
    parse_qsl,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlsplit,
    urlunparse,
)
from urllib.request import url2pathname

from django.apps import apps
from django.conf import settings
import boltmail as mail
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files import locks
from django.core.handlers.wsgi import WSGIHandler, get_path_info
from django.core.management import call_command
from django.core.management.color import no_style
from django.core.management.sql import emit_post_migrate_signal
from django.core.signals import setting_changed
from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.forms.fields import CharField
from django.http import QueryDict
from django.http.request import split_domain_port, validate_host
from django.test.client import Client
from django.test.html import HTMLParseError, parse_html
from django.test.signals import template_rendered
from django.test.utils import (
    CaptureQueriesContext,
    ContextList,
    compare_xml,
    modify_settings,
    override_settings,
)
from django.utils.deprecation import RemovedInDjango51Warning
from django.utils.functional import classproperty
from django.contrib.staticfiles.views import serve

logger = logging.getLogger("django.test")

__all__ = (
    "TestCase",
    "TransactionTestCase",
    "SimpleTestCase",
    "skipIfDBFeature",
    "skipUnlessDBFeature",
)


def to_list(value):
    """Put value into a list if it's not already one."""
    if not isinstance(value, list):
        value = [value]
    return value


class DatabaseOperationForbidden(AssertionError):
    pass


class _DatabaseFailure:
    def __init__(self, wrapped, message):
        self.wrapped = wrapped
        self.message = message

    def __call__(self):
        raise DatabaseOperationForbidden(self.message)


class SimpleTestCase(unittest.TestCase):
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
                    "%s.%s.databases refers to %r which is not defined in "
                    "settings.DATABASES."
                    % (
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
                    "test": "%s.%s" % (cls.__module__, cls.__qualname__),
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
        Wrapper around default __call__ method to perform common Django test
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
        mail.outbox = []

    def _post_teardown(self):
        """Perform post-test things."""
        pass

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


class TransactionTestCase(SimpleTestCase):
    # Subclasses can ask for resetting of auto increment sequence before each
    # test case
    reset_sequences = False

    # Subclasses can enable only a subset of apps for faster tests
    available_apps = None

    # Subclasses can define fixtures which will be automatically installed.
    fixtures = None

    databases = {DEFAULT_DB_ALIAS}
    _disallowed_database_msg = (
        "Database %(operation)s to %(alias)r are not allowed in this test. "
        "Add %(alias)r to %(test)s.databases to ensure proper test isolation "
        "and silence this failure."
    )

    # If transactions aren't available, Django will serialize the database
    # contents into a fixture during setup and flush and reload them
    # during teardown (as flush does not restore data from migrations).
    # This can be slow; this flag allows enabling on a per-case basis.
    serialized_rollback = False

    def _pre_setup(self):
        """
        Perform pre-test setup:
        * If the class has an 'available_apps' attribute, restrict the app
          registry to these applications, then fire the post_migrate signal --
          it must run with the correct set of applications for the test case.
        * If the class has a 'fixtures' attribute, install those fixtures.
        """
        super()._pre_setup()
        if self.available_apps is not None:
            apps.set_available_apps(self.available_apps)
            setting_changed.send(
                sender=settings._wrapped.__class__,
                setting="INSTALLED_APPS",
                value=self.available_apps,
                enter=True,
            )
            for db_name in self._databases_names(include_mirrors=False):
                emit_post_migrate_signal(verbosity=0, interactive=False, db=db_name)
        try:
            self._fixture_setup()
        except Exception:
            if self.available_apps is not None:
                apps.unset_available_apps()
                setting_changed.send(
                    sender=settings._wrapped.__class__,
                    setting="INSTALLED_APPS",
                    value=settings.INSTALLED_APPS,
                    enter=False,
                )
            raise
        # Clear the queries_log so that it's less likely to overflow (a single
        # test probably won't execute 9K queries). If queries_log overflows,
        # then assertNumQueries() doesn't work.
        for db_name in self._databases_names(include_mirrors=False):
            connections[db_name].queries_log.clear()

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

            # Provide replica initial data from migrated apps, if needed.
            if self.serialized_rollback and hasattr(
                connections[db_name], "_test_serialized_contents"
            ):
                if self.available_apps is not None:
                    apps.unset_available_apps()
                connections[db_name].creation.deserialize_db_from_string(
                    connections[db_name]._test_serialized_contents
                )
                if self.available_apps is not None:
                    apps.set_available_apps(self.available_apps)

            if self.fixtures:
                # We have to use this slightly awkward syntax due to the fact
                # that we're using *args and **kwargs together.
                call_command(
                    "loaddata", *self.fixtures, **{"verbosity": 0, "database": db_name}
                )

    def _should_reload_connections(self):
        return True

    def _post_teardown(self):
        """
        Perform post-test things:
        * Flush the contents of the database to leave a clean slate. If the
          class has an 'available_apps' attribute, don't fire post_migrate.
        * Force-close the connection so the next test gets a clean cursor.
        """
        try:
            self._fixture_teardown()
            super()._post_teardown()
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
            if self.available_apps is not None:
                apps.unset_available_apps()
                setting_changed.send(
                    sender=settings._wrapped.__class__,
                    setting="INSTALLED_APPS",
                    value=settings.INSTALLED_APPS,
                    enter=False,
                )

    def _fixture_teardown(self):
        # Allow TRUNCATE ... CASCADE and don't emit the post_migrate signal
        # when flushing only a subset of the apps
        for db_name in self._databases_names(include_mirrors=False):
            # Flush the database
            inhibit_post_migrate = (
                self.available_apps is not None
                or (  # Inhibit the post_migrate signal when using serialized
                    # rollback to avoid trying to recreate the serialized data.
                    self.serialized_rollback
                    and hasattr(connections[db_name], "_test_serialized_contents")
                )
            )
            call_command(
                "flush",
                verbosity=0,
                interactive=False,
                database=db_name,
                reset_sequences=False,
                allow_cascade=self.available_apps is not None,
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


class TestData:
    """
    Descriptor to provide TestCase instance isolation for attributes assigned
    during the setUpTestData() phase.

    Allow safe alteration of objects assigned in setUpTestData() by test
    methods by exposing deep copies instead of the original objects.

    Objects are deep copied using a memo kept on the test case instance in
    order to maintain their original relationships.
    """

    memo_attr = "_testdata_memo"

    def __init__(self, name, data):
        self.name = name
        self.data = data

    def get_memo(self, testcase):
        try:
            memo = getattr(testcase, self.memo_attr)
        except AttributeError:
            memo = {}
            setattr(testcase, self.memo_attr, memo)
        return memo

    def __get__(self, instance, owner):
        if instance is None:
            return self.data
        memo = self.get_memo(instance)
        data = deepcopy(self.data, memo)
        setattr(instance, self.name, data)
        return data

    def __repr__(self):
        return "<TestData: name=%r, data=%r>" % (self.name, self.data)


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
        pre_attrs = cls.__dict__.copy()
        try:
            cls.setUpTestData()
        except Exception:
            cls._rollback_atomics(cls.cls_atomics)
            raise
        for name, value in cls.__dict__.items():
            if value is not pre_attrs.get(name):
                setattr(cls, name, TestData(name, value))

    @classmethod
    def tearDownClass(cls):
        if cls._databases_support_transactions():
            cls._rollback_atomics(cls.cls_atomics)
            for conn in connections.all(initialized_only=True):
                conn.close()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        """Load initial data for the TestCase."""
        pass

    def _should_reload_connections(self):
        if self._databases_support_transactions():
            return False
        return super()._should_reload_connections()

    def _fixture_setup(self):
        if not self._databases_support_transactions():
            # If the backend does not support transactions, we should reload
            # class data before each test
            self.setUpTestData()
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


class CheckCondition:
    """Descriptor class for deferred condition checking."""

    def __init__(self, *conditions):
        self.conditions = conditions

    def add_condition(self, condition, reason):
        return self.__class__(*self.conditions, (condition, reason))

    def __get__(self, instance, cls=None):
        # Trigger access for all bases.
        if any(getattr(base, "__unittest_skip__", False) for base in cls.__bases__):
            return True
        for condition, reason in self.conditions:
            if condition():
                # Override this descriptor's value and set the skip reason.
                cls.__unittest_skip__ = True
                cls.__unittest_skip_why__ = reason
                return True
        return False


def _deferredSkip(condition, reason, name):
    def decorator(test_func):
        nonlocal condition
        if not (
            isinstance(test_func, type) and issubclass(test_func, unittest.TestCase)
        ):

            @wraps(test_func)
            def skip_wrapper(*args, **kwargs):
                if (
                    args
                    and isinstance(args[0], unittest.TestCase)
                    and connection.alias not in getattr(args[0], "databases", {})
                ):
                    raise ValueError(
                        "%s cannot be used on %s as %s doesn't allow queries "
                        "against the %r database."
                        % (
                            name,
                            args[0],
                            args[0].__class__.__qualname__,
                            connection.alias,
                        )
                    )
                if condition():
                    raise unittest.SkipTest(reason)
                return test_func(*args, **kwargs)

            test_item = skip_wrapper
        else:
            # Assume a class is decorated
            test_item = test_func
            databases = getattr(test_item, "databases", None)
            if not databases or connection.alias not in databases:
                # Defer raising to allow importing test class's module.
                def condition():
                    raise ValueError(
                        "%s cannot be used on %s as it doesn't allow queries "
                        "against the '%s' database."
                        % (
                            name,
                            test_item,
                            connection.alias,
                        )
                    )

            # Retrieve the possibly existing value from the class's dict to
            # avoid triggering the descriptor.
            skip = test_func.__dict__.get("__unittest_skip__")
            if isinstance(skip, CheckCondition):
                test_item.__unittest_skip__ = skip.add_condition(condition, reason)
            elif skip is not True:
                test_item.__unittest_skip__ = CheckCondition((condition, reason))
        return test_item

    return decorator


def skipIfDBFeature(*features):
    """Skip a test if a database has at least one of the named features."""
    return _deferredSkip(
        lambda: any(
            getattr(connection.features, feature, False) for feature in features
        ),
        "Database has feature(s) %s" % ", ".join(features),
        "skipIfDBFeature",
    )


def skipUnlessDBFeature(*features):
    """Skip a test unless a database has all the named features."""
    return _deferredSkip(
        lambda: not all(
            getattr(connection.features, feature, False) for feature in features
        ),
        "Database doesn't support feature(s): %s" % ", ".join(features),
        "skipUnlessDBFeature",
    )


def skipUnlessAnyDBFeature(*features):
    """Skip a test unless a database has any of the named features."""
    return _deferredSkip(
        lambda: not any(
            getattr(connection.features, feature, False) for feature in features
        ),
        "Database doesn't support any of the feature(s): %s" % ", ".join(features),
        "skipUnlessAnyDBFeature",
    )


# class QuietWSGIRequestHandler(WSGIRequestHandler):
#     """
#     A WSGIRequestHandler that doesn't log to standard output any of the
#     requests received, so as to not clutter the test result output.
#     """

#     def log_message(*args):
#         pass


class FSFilesHandler(WSGIHandler):
    """
    WSGI middleware that intercepts calls to a directory, as defined by one of
    the *_ROOT settings, and serves those files, publishing them under *_URL.
    """

    def __init__(self, application):
        self.application = application
        self.base_url = urlparse(self.get_base_url())
        super().__init__()

    def _should_handle(self, path):
        """
        Check if the path should be handled. Ignore the path if:
        * the host is provided as part of the base_url
        * the request's path isn't under the media path (or equal)
        """
        return path.startswith(self.base_url[2]) and not self.base_url[1]

    def file_path(self, url):
        """Return the relative path to the file on disk for the given URL."""
        relative_url = url.removeprefix(self.base_url[2])
        return url2pathname(relative_url)

    def get_response(self, request):
        from django.http import Http404

        if self._should_handle(request.path):
            try:
                return self.serve(request)
            except Http404:
                pass
        return super().get_response(request)

    def serve(self, request):
        os_rel_path = self.file_path(request.path)
        os_rel_path = posixpath.normpath(unquote(os_rel_path))
        # Emulate behavior of django.contrib.staticfiles.views.serve() when it
        # invokes staticfiles' finders functionality.
        # TODO: Modify if/when that internal API is refactored
        final_rel_path = os_rel_path.replace("\\", "/").lstrip("/")
        return serve(request, final_rel_path, document_root=self.get_base_dir())

    def __call__(self, environ, start_response):
        if not self._should_handle(get_path_info(environ)):
            return self.application(environ, start_response)
        return super().__call__(environ, start_response)


class _StaticFilesHandler(FSFilesHandler):
    """
    Handler for serving static files. A private class that is meant to be used
    solely as a convenience by LiveServerThread.
    """

    def get_base_dir(self):
        return settings.STATIC_ROOT

    def get_base_url(self):
        return settings.STATIC_URL


class _MediaFilesHandler(FSFilesHandler):
    """
    Handler for serving the media files. A private class that is meant to be
    used solely as a convenience by LiveServerThread.
    """

    def get_base_dir(self):
        return settings.MEDIA_ROOT

    def get_base_url(self):
        return settings.MEDIA_URL


class LiveServerThread(threading.Thread):
    """Thread for running a live HTTP server while the tests are running."""

    # server_class = ThreadedWSGIServer

    def __init__(self, host, static_handler, connections_override=None, port=0):
        self.host = host
        self.port = port
        self.is_ready = threading.Event()
        self.error = None
        self.static_handler = static_handler
        self.connections_override = connections_override
        super().__init__()

    def run(self):
        """
        Set up the live server and databases, and then loop over handling
        HTTP requests.
        """
        if self.connections_override:
            # Override this thread's database connections with the ones
            # provided by the main thread.
            for alias, conn in self.connections_override.items():
                connections[alias] = conn
        try:
            # Create the handler for serving static and media files
            handler = self.static_handler(_MediaFilesHandler(WSGIHandler()))
            self.httpd = self._create_server(
                connections_override=self.connections_override,
            )
            # If binding to port zero, assign the port allocated by the OS.
            if self.port == 0:
                self.port = self.httpd.server_address[1]
            self.httpd.set_app(handler)
            self.is_ready.set()
            self.httpd.serve_forever()
        except Exception as e:
            self.error = e
            self.is_ready.set()
        finally:
            connections.close_all()

    def _create_server(self, connections_override=None):
        return self.server_class(
            (self.host, self.port),
            QuietWSGIRequestHandler,
            allow_reuse_address=False,
            connections_override=connections_override,
        )

    def terminate(self):
        if hasattr(self, "httpd"):
            # Stop the WSGI server
            self.httpd.shutdown()
            self.httpd.server_close()
        self.join()


class LiveServerTestCase(TransactionTestCase):
    """
    Do basically the same as TransactionTestCase but also launch a live HTTP
    server in a separate thread so that the tests may use another testing
    framework, such as Selenium for example, instead of the built-in dummy
    client.
    It inherits from TransactionTestCase instead of TestCase because the
    threads don't share the same transactions (unless if using in-memory sqlite)
    and each thread needs to commit all their transactions so that the other
    thread can see the changes.
    """

    host = "localhost"
    port = 0
    server_thread_class = LiveServerThread
    static_handler = _StaticFilesHandler

    @classproperty
    def live_server_url(cls):
        return "http://%s:%s" % (cls.host, cls.server_thread.port)

    @classproperty
    def allowed_host(cls):
        return cls.host

    @classmethod
    def _make_connections_override(cls):
        connections_override = {}
        for conn in connections.all():
            # If using in-memory sqlite databases, pass the connections to
            # the server thread.
            if conn.vendor == "sqlite" and conn.is_in_memory_db():
                connections_override[conn.alias] = conn
        return connections_override

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._live_server_modified_settings = modify_settings(
            ALLOWED_HOSTS={"append": cls.allowed_host},
        )
        cls._live_server_modified_settings.enable()
        cls.addClassCleanup(cls._live_server_modified_settings.disable)
        cls._start_server_thread()

    @classmethod
    def _start_server_thread(cls):
        connections_override = cls._make_connections_override()
        for conn in connections_override.values():
            # Explicitly enable thread-shareability for this connection.
            conn.inc_thread_sharing()

        cls.server_thread = cls._create_server_thread(connections_override)
        cls.server_thread.daemon = True
        cls.server_thread.start()
        cls.addClassCleanup(cls._terminate_thread)

        # Wait for the live server to be ready
        cls.server_thread.is_ready.wait()
        if cls.server_thread.error:
            raise cls.server_thread.error

    @classmethod
    def _create_server_thread(cls, connections_override):
        return cls.server_thread_class(
            cls.host,
            cls.static_handler,
            connections_override=connections_override,
            port=cls.port,
        )

    @classmethod
    def _terminate_thread(cls):
        # Terminate the live server's thread.
        cls.server_thread.terminate()
        # Restore shared connections' non-shareability.
        for conn in cls.server_thread.connections_override.values():
            conn.dec_thread_sharing()


class SerializeMixin:
    """
    Enforce serialization of TestCases that share a common resource.

    Define a common 'lockfile' for each set of TestCases to serialize. This
    file must exist on the filesystem.

    Place it early in the MRO in order to isolate setUpClass()/tearDownClass().
    """

    lockfile = None

    def __init_subclass__(cls, /, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.lockfile is None:
            raise ValueError(
                "{}.lockfile isn't set. Set it to a unique value "
                "in the base class.".format(cls.__name__)
            )

    @classmethod
    def setUpClass(cls):
        cls._lockfile = open(cls.lockfile)
        cls.addClassCleanup(cls._lockfile.close)
        locks.lock(cls._lockfile, locks.LOCK_EX)
        super().setUpClass()
