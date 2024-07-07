"""All pytest-plain fixtures"""
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from functools import partial
from typing import Any, Optional, Union

import pytest

from ..testcases import TestCase, TransactionTestCase

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Literal

    import plain.runtime

    _DjangoDbDatabases = Optional[Union["Literal['__all__']", Iterable[str]]]
    # transaction, reset_sequences, databases, serialized_rollback
    _DjangoDb = tuple[bool, bool, _DjangoDbDatabases, bool]


__all__ = [
    "plain_db_setup",
    "db",
    "transactional_db",
    "plain_db_reset_sequences",
    "plain_db_serialized_rollback",
    "client",
    "rf",
    "settings",
    "plain_assert_num_queries",
    "plain_assert_max_num_queries",
]


@pytest.fixture(scope="session")
def plain_db_setup(
    request,
    plain_test_environment: None,
    plain_db_blocker,
) -> None:
    """Top level fixture to ensure test databases are available"""
    from plain.test.utils import setup_databases, teardown_databases

    setup_databases_args = {}

    if request.config.getvalue("reuse_db") and not request.config.getvalue("create_db"):
        setup_databases_args["keepdb"] = True

    with plain_db_blocker.unblock():
        db_cfg = setup_databases(
            verbosity=request.config.option.verbose,
            interactive=False,
            **setup_databases_args,
        )

    def teardown_database() -> None:
        with plain_db_blocker.unblock():
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
def _plain_db_helper(
    request,
    plain_db_setup: None,
    plain_db_blocker,
) -> None:
    marker = request.node.get_closest_marker("plain_db")
    if marker:
        (
            transactional,
            reset_sequences,
            databases,
            serialized_rollback,
        ) = validate_plain_db(marker)
    else:
        (
            transactional,
            reset_sequences,
            databases,
            serialized_rollback,
        ) = (
            False,
            False,
            None,
            False,
        )

    transactional = (
        transactional or reset_sequences or ("transactional_db" in request.fixturenames)
    )
    reset_sequences = reset_sequences or (
        "plain_db_reset_sequences" in request.fixturenames
    )
    serialized_rollback = serialized_rollback or (
        "plain_db_serialized_rollback" in request.fixturenames
    )

    plain_db_blocker.unblock()
    request.addfinalizer(plain_db_blocker.restore)

    if transactional:
        test_case_class = TransactionTestCase
    else:
        test_case_class = TestCase

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


def validate_plain_db(marker) -> "_DjangoDb":
    """Validate the plain_db marker.

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


@pytest.fixture()
def db(_plain_db_helper: None) -> None:
    """Require a plain test database.

    This database will be setup with the default fixtures and will have
    the transaction management disabled. At the end of the test the outer
    transaction that wraps the test itself will be rolled back to undo any
    changes to the database (in case the backend supports transactions).
    This is more limited than the ``transactional_db`` fixture but
    faster.

    If both ``db`` and ``transactional_db`` are requested,
    ``transactional_db`` takes precedence.
    """
    # The `_plain_db_helper` fixture checks if `db` is requested.


@pytest.fixture()
def transactional_db(_plain_db_helper: None) -> None:
    """Require a plain test database with transaction support.

    This will re-initialise the plain database for each test and is
    thus slower than the normal ``db`` fixture.

    If you want to use the database with transactions you must request
    this resource.

    If both ``db`` and ``transactional_db`` are requested,
    ``transactional_db`` takes precedence.
    """
    # The `_plain_db_helper` fixture checks if `transactional_db` is requested.


@pytest.fixture()
def plain_db_reset_sequences(
    _plain_db_helper: None,
    transactional_db: None,
) -> None:
    """Require a transactional test database with sequence reset support.

    This requests the ``transactional_db`` fixture, and additionally
    enforces a reset of all auto increment sequences.  If the enquiring
    test relies on such values (e.g. ids as primary keys), you should
    request this resource to ensure they are consistent across tests.
    """
    # The `_plain_db_helper` fixture checks if `plain_db_reset_sequences`
    # is requested.


@pytest.fixture()
def plain_db_serialized_rollback(
    _plain_db_helper: None,
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
    # The `_plain_db_helper` fixture checks if `plain_db_serialized_rollback`
    # is requested.


@pytest.fixture()
def client() -> "plain.test.client.Client":
    """A Plain test client instance."""
    from plain.test.client import Client

    return Client()


@pytest.fixture()
def rf() -> "plain.test.client.RequestFactory":
    """RequestFactory instance"""
    from plain.test.client import RequestFactory

    return RequestFactory()


class SettingsWrapper:
    _to_restore: list[Any] = []

    def __delattr__(self, attr: str) -> None:
        from plain.test import override_settings

        override = override_settings()
        override.enable()
        from plain.runtime import settings

        delattr(settings, attr)

        self._to_restore.append(override)

    def __setattr__(self, attr: str, value) -> None:
        from plain.test import override_settings

        override = override_settings(**{attr: value})
        override.enable()
        self._to_restore.append(override)

    def __getattr__(self, attr: str):
        from plain.runtime import settings

        return getattr(settings, attr)

    def finalize(self) -> None:
        for override in reversed(self._to_restore):
            override.disable()

        del self._to_restore[:]


@pytest.fixture()
def settings():
    """A Plain settings object which restores changes after the testrun"""
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
) -> Generator["plain.test.utils.CaptureQueriesContext", None, None]:
    from plain.test.utils import CaptureQueriesContext

    if connection is None:
        from plain.models import connection as conn
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


@pytest.fixture()
def plain_assert_num_queries(pytestconfig):
    return partial(_assert_num_queries, pytestconfig)


@pytest.fixture()
def plain_assert_max_num_queries(pytestconfig):
    return partial(_assert_num_queries, pytestconfig, exact=False)
