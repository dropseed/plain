"""All pytest-django fixtures"""
from contextlib import contextmanager
from functools import partial
from typing import Any, Generator, Iterable, List, Optional, Tuple, Union

import pytest


TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Literal

    import django

    _DjangoDbDatabases = Optional[Union["Literal['__all__']", Iterable[str]]]
    # transaction, reset_sequences, databases, serialized_rollback
    _DjangoDb = Tuple[bool, bool, _DjangoDbDatabases, bool]


__all__ = [
    "django_db_setup",
    "db",
    "transactional_db",
    "django_db_reset_sequences",
    "django_db_serialized_rollback",
    "client",
    "rf",
    "settings",
    "django_assert_num_queries",
    "django_assert_max_num_queries",
]


@pytest.fixture(scope="session")
def django_db_setup(
    request,
    django_test_environment: None,
    django_db_blocker,
) -> None:
    """Top level fixture to ensure test databases are available"""
    from bolt.test.utils import setup_databases, teardown_databases

    setup_databases_args = {}

    if request.config.getvalue("reuse_db") and not request.config.getvalue("create_db"):
        setup_databases_args["keepdb"] = True

    with django_db_blocker.unblock():
        db_cfg = setup_databases(
            verbosity=request.config.option.verbose,
            interactive=False,
            **setup_databases_args
        )

    def teardown_database() -> None:
        with django_db_blocker.unblock():
            try:
                teardown_databases(db_cfg, verbosity=request.config.option.verbose)
            except Exception as exc:
                request.node.warn(
                    pytest.PytestWarning(
                        f"Error when trying to teardown test databases: {exc!r}"
                    )
                )

    if not request.config.getvalue("reuse_db"):
        request.addfinalizer(teardown_database)


@pytest.fixture()
def _django_db_helper(
    request,
    django_db_setup: None,
    django_db_blocker,
) -> None:
    from django import VERSION

    marker = request.node.get_closest_marker("django_db")
    if marker:
        (
            transactional,
            reset_sequences,
            databases,
            serialized_rollback,
        ) = validate_django_db(marker)
    else:
        (
            transactional,
            reset_sequences,
            databases,
            serialized_rollback,
        ) = False, False, None, False

    transactional = transactional or reset_sequences or (
        "transactional_db" in request.fixturenames
    )
    reset_sequences = reset_sequences or (
        "django_db_reset_sequences" in request.fixturenames
    )
    serialized_rollback = serialized_rollback or (
        "django_db_serialized_rollback" in request.fixturenames
    )

    django_db_blocker.unblock()
    request.addfinalizer(django_db_blocker.restore)

    import bolt.db
    import bolt.test

    if transactional:
        test_case_class = bolt.test.TransactionTestCase
    else:
        test_case_class = bolt.test.TestCase

    _reset_sequences = reset_sequences
    _serialized_rollback = serialized_rollback
    _databases = databases

    class PytestDjangoTestCase(test_case_class):  # type: ignore[misc,valid-type]
        reset_sequences = _reset_sequences
        serialized_rollback = _serialized_rollback
        if _databases is not None:
            databases = _databases

    PytestDjangoTestCase.setUpClass()

    request.addfinalizer(PytestDjangoTestCase.doClassCleanups)
    request.addfinalizer(PytestDjangoTestCase.tearDownClass)

    test_case = PytestDjangoTestCase(methodName="__init__")
    test_case._pre_setup()
    request.addfinalizer(test_case._post_teardown)


def validate_django_db(marker) -> "_DjangoDb":
    """Validate the django_db marker.

    It checks the signature and creates the ``transaction``,
    ``reset_sequences``, ``databases`` and ``serialized_rollback`` attributes on
    the marker which will have the correct values.

    Sequence reset and serialized_rollback are only allowed when combined with
    transaction.
    """

    def apifun(
        transaction: bool = False,
        reset_sequences: bool = False,
        databases: "_DjangoDbDatabases" = None,
        serialized_rollback: bool = False,
    ) -> "_DjangoDb":
        return transaction, reset_sequences, databases, serialized_rollback

    return apifun(*marker.args, **marker.kwargs)


# ############### User visible fixtures ################


@pytest.fixture(scope="function")
def db(_django_db_helper: None) -> None:
    """Require a django test database.

    This database will be setup with the default fixtures and will have
    the transaction management disabled. At the end of the test the outer
    transaction that wraps the test itself will be rolled back to undo any
    changes to the database (in case the backend supports transactions).
    This is more limited than the ``transactional_db`` fixture but
    faster.

    If both ``db`` and ``transactional_db`` are requested,
    ``transactional_db`` takes precedence.
    """
    # The `_django_db_helper` fixture checks if `db` is requested.


@pytest.fixture(scope="function")
def transactional_db(_django_db_helper: None) -> None:
    """Require a django test database with transaction support.

    This will re-initialise the django database for each test and is
    thus slower than the normal ``db`` fixture.

    If you want to use the database with transactions you must request
    this resource.

    If both ``db`` and ``transactional_db`` are requested,
    ``transactional_db`` takes precedence.
    """
    # The `_django_db_helper` fixture checks if `transactional_db` is requested.


@pytest.fixture(scope="function")
def django_db_reset_sequences(
    _django_db_helper: None,
    transactional_db: None,
) -> None:
    """Require a transactional test database with sequence reset support.

    This requests the ``transactional_db`` fixture, and additionally
    enforces a reset of all auto increment sequences.  If the enquiring
    test relies on such values (e.g. ids as primary keys), you should
    request this resource to ensure they are consistent across tests.
    """
    # The `_django_db_helper` fixture checks if `django_db_reset_sequences`
    # is requested.


@pytest.fixture(scope="function")
def django_db_serialized_rollback(
    _django_db_helper: None,
    db: None,
) -> None:
    """Require a test database with serialized rollbacks.

    This requests the ``db`` fixture, and additionally performs rollback
    emulation - serializes the database contents during setup and restores
    it during teardown.

    This fixture may be useful for transactional tests, so is usually combined
    with ``transactional_db``, but can also be useful on databases which do not
    support transactions.

    Note that this will slow down that test suite by approximately 3x.
    """
    # The `_django_db_helper` fixture checks if `django_db_serialized_rollback`
    # is requested.


@pytest.fixture()
def client() -> "bolt.test.client.Client":
    """A Django test client instance."""
    from bolt.test.client import Client

    return Client()


@pytest.fixture()
def rf() -> "bolt.test.client.RequestFactory":
    """RequestFactory instance"""
    from bolt.test.client import RequestFactory

    return RequestFactory()


class SettingsWrapper:
    _to_restore: List[Any] = []

    def __delattr__(self, attr: str) -> None:
        from bolt.test import override_settings

        override = override_settings()
        override.enable()
        from django.conf import settings

        delattr(settings, attr)

        self._to_restore.append(override)

    def __setattr__(self, attr: str, value) -> None:
        from bolt.test import override_settings

        override = override_settings(**{attr: value})
        override.enable()
        self._to_restore.append(override)

    def __getattr__(self, attr: str):
        from django.conf import settings

        return getattr(settings, attr)

    def finalize(self) -> None:
        for override in reversed(self._to_restore):
            override.disable()

        del self._to_restore[:]


@pytest.fixture()
def settings():
    """A Django settings object which restores changes after the testrun"""
    wrapper = SettingsWrapper()
    yield wrapper
    wrapper.finalize()


@contextmanager
def _assert_num_queries(
    config,
    num: int,
    exact: bool = True,
    connection=None,
    info=None,
) -> Generator["bolt.test.utils.CaptureQueriesContext", None, None]:
    from bolt.test.utils import CaptureQueriesContext

    if connection is None:
        from bolt.db import connection as conn
    else:
        conn = connection

    verbose = config.getoption("verbose") > 0
    with CaptureQueriesContext(conn) as context:
        yield context
        num_performed = len(context)
        if exact:
            failed = num != num_performed
        else:
            failed = num_performed > num
        if failed:
            msg = f"Expected to perform {num} queries "
            if not exact:
                msg += "or less "
            verb = "was" if num_performed == 1 else "were"
            msg += f"but {num_performed} {verb} done"
            if info:
                msg += f"\n{info}"
            if verbose:
                sqls = (q["sql"] for q in context.captured_queries)
                msg += "\n\nQueries:\n========\n\n" + "\n\n".join(sqls)
            else:
                msg += " (add -v option to show queries)"
            pytest.fail(msg)


@pytest.fixture(scope="function")
def django_assert_num_queries(pytestconfig):
    return partial(_assert_num_queries, pytestconfig)


@pytest.fixture(scope="function")
def django_assert_max_num_queries(pytestconfig):
    return partial(_assert_num_queries, pytestconfig, exact=False)
