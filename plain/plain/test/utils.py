import collections
import os
import re
import sys
import time
import warnings
from contextlib import contextmanager
from functools import wraps
from io import StringIO
from itertools import chain
from types import SimpleNamespace
from unittest import TestCase
from xml.dom.minidom import Node, parseString

from jinja2 import Template

from plain.exceptions import ImproperlyConfigured
from plain.models import DEFAULT_DB_ALIAS, connections, reset_queries
from plain.packages import packages
from plain.runtime import settings
from plain.runtime.user_settings import UserSettingsHolder
from plain.signals import request_started

__all__ = (
    "ContextList",
    "CaptureQueriesContext",
    "ignore_warnings",
    "modify_settings",
    "override_settings",
    "setup_databases",
    "setup_test_environment",
    "teardown_test_environment",
)

TZ_SUPPORT = hasattr(time, "tzset")


class ContextList(list):
    """
    A wrapper that provides direct key access to context items contained
    in a list of context objects.
    """

    def __getitem__(self, key):
        if isinstance(key, str):
            for subcontext in self:
                if key in subcontext:
                    return subcontext[key]
            raise KeyError(key)
        else:
            return super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def __contains__(self, key):
        try:
            self[key]
        except KeyError:
            return False
        return True

    def keys(self):
        """
        Flattened keys of subcontexts.
        """
        return set(chain.from_iterable(d for subcontext in self for d in subcontext))


def instrumented_test_render(self, context):
    """
    An instrumented Template render method, providing a signal that can be
    intercepted by the test Client.
    """
    return self._original_render(context)


class _TestState:
    pass


def setup_test_environment(debug=None):
    """
    Perform global pre-test setup, such as installing the instrumented template
    renderer and setting the email backend to the locmem email backend.
    """
    if hasattr(_TestState, "saved_data"):
        # Executing this function twice would overwrite the saved values.
        raise RuntimeError(
            "setup_test_environment() was already called and can't be called "
            "again without first calling teardown_test_environment()."
        )

    if debug is None:
        debug = settings.DEBUG

    saved_data = SimpleNamespace()
    _TestState.saved_data = saved_data

    saved_data.allowed_hosts = settings.ALLOWED_HOSTS
    # Add the default host of the test client.
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

    saved_data.debug = settings.DEBUG
    settings.DEBUG = debug

    saved_data.template_render = Template.render
    Template._original_render = Template.render
    Template.render = instrumented_test_render

    try:
        from plain import mail

        mail.outbox = []
        saved_data.email_backend = settings.EMAIL_BACKEND
        settings.EMAIL_BACKEND = "plain.mail.backends.testing.EmailBackend"
    except ImportError:
        pass


def teardown_test_environment():
    """
    Perform any global post-test teardown, such as restoring the original
    template renderer and restoring the email sending functions.
    """
    saved_data = _TestState.saved_data

    settings.ALLOWED_HOSTS = saved_data.allowed_hosts
    settings.DEBUG = saved_data.debug
    Template._render = saved_data.template_render

    del _TestState.saved_data

    try:
        from plain import mail

        settings.EMAIL_BACKEND = saved_data.email_backend

        del mail.outbox
    except ImportError:
        pass


def setup_databases(
    verbosity,
    interactive,
    *,
    time_keeper=None,
    keepdb=False,
    debug_sql=False,
    parallel=0,
    aliases=None,
    serialized_aliases=None,
    **kwargs,
):
    """Create the test databases."""
    if time_keeper is None:
        time_keeper = NullTimeKeeper()

    test_databases, mirrored_aliases = get_unique_databases_and_mirrors(aliases)

    old_names = []

    for db_name, aliases in test_databases.values():
        first_alias = None
        for alias in aliases:
            connection = connections[alias]
            old_names.append((connection, db_name, first_alias is None))

            # Actually create the database for the first connection
            if first_alias is None:
                first_alias = alias
                with time_keeper.timed("  Creating '%s'" % alias):
                    serialize_alias = (
                        serialized_aliases is None or alias in serialized_aliases
                    )
                    connection.creation.create_test_db(
                        verbosity=verbosity,
                        autoclobber=not interactive,
                        keepdb=keepdb,
                        serialize=serialize_alias,
                    )
                if parallel > 1:
                    for index in range(parallel):
                        with time_keeper.timed("  Cloning '%s'" % alias):
                            connection.creation.clone_test_db(
                                suffix=str(index + 1),
                                verbosity=verbosity,
                                keepdb=keepdb,
                            )
            # Configure all other connections as mirrors of the first one
            else:
                connections[alias].creation.set_as_test_mirror(
                    connections[first_alias].settings_dict
                )

    # Configure the test mirrors.
    for alias, mirror_alias in mirrored_aliases.items():
        connections[alias].creation.set_as_test_mirror(
            connections[mirror_alias].settings_dict
        )

    if debug_sql:
        for alias in connections:
            connections[alias].force_debug_cursor = True

    return old_names


def iter_test_cases(tests):
    """
    Return an iterator over a test suite's unittest.TestCase objects.

    The tests argument can also be an iterable of TestCase objects.
    """
    for test in tests:
        if isinstance(test, str):
            # Prevent an unfriendly RecursionError that can happen with
            # strings.
            raise TypeError(
                f"Test {test!r} must be a test case or test suite not string "
                f"(was found in {tests!r})."
            )
        if isinstance(test, TestCase):
            yield test
        else:
            # Otherwise, assume it is a test suite.
            yield from iter_test_cases(test)


def dependency_ordered(test_databases, dependencies):
    """
    Reorder test_databases into an order that honors the dependencies
    described in TEST[DEPENDENCIES].
    """
    ordered_test_databases = []
    resolved_databases = set()

    # Maps db signature to dependencies of all its aliases
    dependencies_map = {}

    # Check that no database depends on its own alias
    for sig, (_, aliases) in test_databases:
        all_deps = set()
        for alias in aliases:
            all_deps.update(dependencies.get(alias, []))
        if not all_deps.isdisjoint(aliases):
            raise ImproperlyConfigured(
                "Circular dependency: databases %r depend on each other, "
                "but are aliases." % aliases
            )
        dependencies_map[sig] = all_deps

    while test_databases:
        changed = False
        deferred = []

        # Try to find a DB that has all its dependencies met
        for signature, (db_name, aliases) in test_databases:
            if dependencies_map[signature].issubset(resolved_databases):
                resolved_databases.update(aliases)
                ordered_test_databases.append((signature, (db_name, aliases)))
                changed = True
            else:
                deferred.append((signature, (db_name, aliases)))

        if not changed:
            raise ImproperlyConfigured("Circular dependency in TEST[DEPENDENCIES]")
        test_databases = deferred
    return ordered_test_databases


def get_unique_databases_and_mirrors(aliases=None):
    """
    Figure out which databases actually need to be created.

    Deduplicate entries in DATABASES that correspond the same database or are
    configured as test mirrors.

    Return two values:
    - test_databases: ordered mapping of signatures to (name, list of aliases)
                      where all aliases share the same underlying database.
    - mirrored_aliases: mapping of mirror aliases to original aliases.
    """
    if aliases is None:
        aliases = connections
    mirrored_aliases = {}
    test_databases = {}
    dependencies = {}
    default_sig = connections[DEFAULT_DB_ALIAS].creation.test_db_signature()

    for alias in connections:
        connection = connections[alias]
        test_settings = connection.settings_dict["TEST"]

        if test_settings["MIRROR"]:
            # If the database is marked as a test mirror, save the alias.
            mirrored_aliases[alias] = test_settings["MIRROR"]
        elif alias in aliases:
            # Store a tuple with DB parameters that uniquely identify it.
            # If we have two aliases with the same values for that tuple,
            # we only need to create the test database once.
            item = test_databases.setdefault(
                connection.creation.test_db_signature(),
                (connection.settings_dict["NAME"], []),
            )
            # The default database must be the first because data migrations
            # use the default alias by default.
            if alias == DEFAULT_DB_ALIAS:
                item[1].insert(0, alias)
            else:
                item[1].append(alias)

            if "DEPENDENCIES" in test_settings:
                dependencies[alias] = test_settings["DEPENDENCIES"]
            else:
                if (
                    alias != DEFAULT_DB_ALIAS
                    and connection.creation.test_db_signature() != default_sig
                ):
                    dependencies[alias] = test_settings.get(
                        "DEPENDENCIES", [DEFAULT_DB_ALIAS]
                    )

    test_databases = dict(dependency_ordered(test_databases.items(), dependencies))
    return test_databases, mirrored_aliases


def teardown_databases(old_config, verbosity, parallel=0, keepdb=False):
    """Destroy all the non-mirror databases."""
    for connection, old_name, destroy in old_config:
        if destroy:
            if parallel > 1:
                for index in range(parallel):
                    connection.creation.destroy_test_db(
                        suffix=str(index + 1),
                        verbosity=verbosity,
                        keepdb=keepdb,
                    )
            connection.creation.destroy_test_db(old_name, verbosity, keepdb)


class TestContextDecorator:
    """
    A base class that can either be used as a context manager during tests
    or as a test function or unittest.TestCase subclass decorator to perform
    temporary alterations.

    `attr_name`: attribute assigned the return value of enable() if used as
                 a class decorator.

    `kwarg_name`: keyword argument passing the return value of enable() if
                  used as a function decorator.
    """

    def __init__(self, attr_name=None, kwarg_name=None):
        self.attr_name = attr_name
        self.kwarg_name = kwarg_name

    def enable(self):
        raise NotImplementedError

    def disable(self):
        raise NotImplementedError

    def __enter__(self):
        return self.enable()

    def __exit__(self, exc_type, exc_value, traceback):
        self.disable()

    def decorate_class(self, cls):
        if issubclass(cls, TestCase):
            decorated_setUp = cls.setUp

            def setUp(inner_self):
                context = self.enable()
                inner_self.addCleanup(self.disable)
                if self.attr_name:
                    setattr(inner_self, self.attr_name, context)
                decorated_setUp(inner_self)

            cls.setUp = setUp
            return cls
        raise TypeError("Can only decorate subclasses of unittest.TestCase")

    def decorate_callable(self, func):
        @wraps(func)
        def inner(*args, **kwargs):
            with self as context:
                if self.kwarg_name:
                    kwargs[self.kwarg_name] = context
                return func(*args, **kwargs)

        return inner

    def __call__(self, decorated):
        if isinstance(decorated, type):
            return self.decorate_class(decorated)
        elif callable(decorated):
            return self.decorate_callable(decorated)
        raise TypeError("Cannot decorate object of type %s" % type(decorated))


class override_settings(TestContextDecorator):
    """
    Act as either a decorator or a context manager. If it's a decorator, take a
    function and return a wrapped function. If it's a contextmanager, use it
    with the ``with`` statement. In either event, entering/exiting are called
    before and after, respectively, the function/block is executed.
    """

    enable_exception = None

    def __init__(self, **kwargs):
        self.options = kwargs
        super().__init__()

    def enable(self):
        # Keep this code at the beginning to leave the settings unchanged
        # in case it raises an exception because INSTALLED_PACKAGES is invalid.
        if "INSTALLED_PACKAGES" in self.options:
            try:
                packages.set_installed_packages(self.options["INSTALLED_PACKAGES"])
            except Exception:
                packages.unset_installed_packages()
                raise
        override = UserSettingsHolder(settings._wrapped)
        for key, new_value in self.options.items():
            setattr(override, key, new_value)
        self.wrapped = settings._wrapped
        settings._wrapped = override
        # for key, new_value in self.options.items():
        #     try:
        #         setting_changed.send(
        #             sender=settings._wrapped.__class__,
        #             setting=key,
        #             value=new_value,
        #             enter=True,
        #         )
        #     except Exception as exc:
        #         self.enable_exception = exc
        #         self.disable()

    def disable(self):
        if "INSTALLED_PACKAGES" in self.options:
            packages.unset_installed_packages()
        settings._wrapped = self.wrapped
        del self.wrapped
        responses = []
        for key in self.options:
            getattr(settings, key, None)
            # responses_for_setting = setting_changed.send_robust(
            #     sender=settings._wrapped.__class__,
            #     setting=key,
            #     value=new_value,
            #     enter=False,
            # )
            # responses.extend(responses_for_setting)
        if self.enable_exception is not None:
            exc = self.enable_exception
            self.enable_exception = None
            raise exc
        for _, response in responses:
            if isinstance(response, Exception):
                raise response

    def save_options(self, test_func):
        if test_func._overridden_settings is None:
            test_func._overridden_settings = self.options
        else:
            # Duplicate dict to prevent subclasses from altering their parent.
            test_func._overridden_settings = {
                **test_func._overridden_settings,
                **self.options,
            }


class modify_settings(override_settings):
    """
    Like override_settings, but makes it possible to append, prepend, or remove
    items instead of redefining the entire list.
    """

    def __init__(self, *args, **kwargs):
        if args:
            # Hack used when instantiating from SimpleTestCase.setUpClass.
            assert not kwargs
            self.operations = args[0]
        else:
            assert not args
            self.operations = list(kwargs.items())
        super(override_settings, self).__init__()

    def save_options(self, test_func):
        if test_func._modified_settings is None:
            test_func._modified_settings = self.operations
        else:
            # Duplicate list to prevent subclasses from altering their parent.
            test_func._modified_settings = (
                list(test_func._modified_settings) + self.operations
            )

    def enable(self):
        self.options = {}
        for name, operations in self.operations:
            try:
                # When called from SimpleTestCase.setUpClass, values may be
                # overridden several times; cumulate changes.
                value = self.options[name]
            except KeyError:
                value = list(getattr(settings, name, []))
            for action, items in operations.items():
                # items my be a single value or an iterable.
                if isinstance(items, str):
                    items = [items]
                if action == "append":
                    value += [item for item in items if item not in value]
                elif action == "prepend":
                    value = [item for item in items if item not in value] + value
                elif action == "remove":
                    value = [item for item in value if item not in items]
                else:
                    raise ValueError("Unsupported action: %s" % action)
            self.options[name] = value
        super().enable()


def compare_xml(want, got):
    """
    Try to do a 'xml-comparison' of want and got. Plain string comparison
    doesn't always work because, for example, attribute ordering should not be
    important. Ignore comment nodes, processing instructions, document type
    node, and leading and trailing whitespaces.

    Based on https://github.com/lxml/lxml/blob/master/src/lxml/doctestcompare.py
    """
    _norm_whitespace_re = re.compile(r"[ \t\n][ \t\n]+")

    def norm_whitespace(v):
        return _norm_whitespace_re.sub(" ", v)

    def child_text(element):
        return "".join(
            c.data for c in element.childNodes if c.nodeType == Node.TEXT_NODE
        )

    def children(element):
        return [c for c in element.childNodes if c.nodeType == Node.ELEMENT_NODE]

    def norm_child_text(element):
        return norm_whitespace(child_text(element))

    def attrs_dict(element):
        return dict(element.attributes.items())

    def check_element(want_element, got_element):
        if want_element.tagName != got_element.tagName:
            return False
        if norm_child_text(want_element) != norm_child_text(got_element):
            return False
        if attrs_dict(want_element) != attrs_dict(got_element):
            return False
        want_children = children(want_element)
        got_children = children(got_element)
        if len(want_children) != len(got_children):
            return False
        return all(
            check_element(want, got) for want, got in zip(want_children, got_children)
        )

    def first_node(document):
        for node in document.childNodes:
            if node.nodeType not in (
                Node.COMMENT_NODE,
                Node.DOCUMENT_TYPE_NODE,
                Node.PROCESSING_INSTRUCTION_NODE,
            ):
                return node

    want = want.strip().replace("\\n", "\n")
    got = got.strip().replace("\\n", "\n")

    # If the string is not a complete xml document, we may need to add a
    # root element. This allow us to compare fragments, like "<foo/><bar/>"
    if not want.startswith("<?xml"):
        wrapper = "<root>%s</root>"
        want = wrapper % want
        got = wrapper % got

    # Parse the want and got strings, and compare the parsings.
    want_root = first_node(parseString(want))
    got_root = first_node(parseString(got))

    return check_element(want_root, got_root)


class CaptureQueriesContext:
    """
    Context manager that captures queries executed by the specified connection.
    """

    def __init__(self, connection):
        self.connection = connection

    def __iter__(self):
        return iter(self.captured_queries)

    def __getitem__(self, index):
        return self.captured_queries[index]

    def __len__(self):
        return len(self.captured_queries)

    @property
    def captured_queries(self):
        return self.connection.queries[self.initial_queries : self.final_queries]

    def __enter__(self):
        self.force_debug_cursor = self.connection.force_debug_cursor
        self.connection.force_debug_cursor = True
        # Run any initialization queries if needed so that they won't be
        # included as part of the count.
        self.connection.ensure_connection()
        self.initial_queries = len(self.connection.queries_log)
        self.final_queries = None
        request_started.disconnect(reset_queries)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.force_debug_cursor = self.force_debug_cursor
        request_started.connect(reset_queries)
        if exc_type is not None:
            return
        self.final_queries = len(self.connection.queries_log)


class ignore_warnings(TestContextDecorator):
    def __init__(self, **kwargs):
        self.ignore_kwargs = kwargs
        if "message" in self.ignore_kwargs or "module" in self.ignore_kwargs:
            self.filter_func = warnings.filterwarnings
        else:
            self.filter_func = warnings.simplefilter
        super().__init__()

    def enable(self):
        self.catch_warnings = warnings.catch_warnings()
        self.catch_warnings.__enter__()
        self.filter_func("ignore", **self.ignore_kwargs)

    def disable(self):
        self.catch_warnings.__exit__(*sys.exc_info())


@contextmanager
def extend_sys_path(*paths):
    """Context manager to temporarily add paths to sys.path."""
    _orig_sys_path = sys.path[:]
    sys.path.extend(paths)
    try:
        yield
    finally:
        sys.path = _orig_sys_path


@contextmanager
def captured_output(stream_name):
    """Return a context manager used by captured_stdout/stdin/stderr
    that temporarily replaces the sys stream *stream_name* with a StringIO.

    Note: This function and the following ``captured_std*`` are copied
          from CPython's ``test.support`` module."""
    orig_stdout = getattr(sys, stream_name)
    setattr(sys, stream_name, StringIO())
    try:
        yield getattr(sys, stream_name)
    finally:
        setattr(sys, stream_name, orig_stdout)


def captured_stdout():
    """Capture the output of sys.stdout:

    with captured_stdout() as stdout:
        print("hello")
    self.assertEqual(stdout.getvalue(), "hello\n")
    """
    return captured_output("stdout")


def captured_stderr():
    """Capture the output of sys.stderr:

    with captured_stderr() as stderr:
        print("hello", file=sys.stderr)
    self.assertEqual(stderr.getvalue(), "hello\n")
    """
    return captured_output("stderr")


def captured_stdin():
    """Capture the input to sys.stdin:

    with captured_stdin() as stdin:
        stdin.write('hello\n')
        stdin.seek(0)
        # call test code that consumes from sys.stdin
        captured = input()
    self.assertEqual(captured, "hello")
    """
    return captured_output("stdin")


@contextmanager
def freeze_time(t):
    """
    Context manager to temporarily freeze time.time(). This temporarily
    modifies the time function of the time module. Modules which import the
    time function directly (e.g. `from time import time`) won't be affected
    This isn't meant as a public API, but helps reduce some repetitive code in
    Plain's test suite.
    """
    _real_time = time.time
    time.time = lambda: t
    try:
        yield
    finally:
        time.time = _real_time


class TimeKeeper:
    def __init__(self):
        self.records = collections.defaultdict(list)

    @contextmanager
    def timed(self, name):
        self.records[name]
        start_time = time.perf_counter()
        try:
            yield
        finally:
            end_time = time.perf_counter() - start_time
            self.records[name].append(end_time)

    def print_results(self):
        for name, end_times in self.records.items():
            for record_time in end_times:
                record = f"{name} took {record_time:.3f}s"
                sys.stderr.write(record + os.linesep)


class NullTimeKeeper:
    @contextmanager
    def timed(self, name):
        yield

    def print_results(self):
        pass


@contextmanager
def register_lookup(field, *lookups, lookup_name=None):
    """
    Context manager to temporarily register lookups on a model field using
    lookup_name (or the lookup's lookup_name if not provided).
    """
    try:
        for lookup in lookups:
            field.register_lookup(lookup, lookup_name)
        yield
    finally:
        for lookup in lookups:
            field._unregister_lookup(lookup, lookup_name)
