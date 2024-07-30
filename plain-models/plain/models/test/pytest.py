import pytest

from plain.signals import request_finished, request_started

from .. import transaction
from ..backends.base.base import BaseDatabaseWrapper
from ..db import close_old_connections, connections
from .utils import (
    setup_databases,
    teardown_databases,
)


@pytest.fixture(autouse=True)
def _db_disabled():
    """
    Every test should use this fixture by default to prevent
    access to the normal database.
    """

    def cursor_disabled(self):
        pytest.fail("Database access not allowed without the `db` fixture")

    BaseDatabaseWrapper._old_cursor = BaseDatabaseWrapper.cursor
    BaseDatabaseWrapper.cursor = cursor_disabled

    yield

    BaseDatabaseWrapper.cursor = BaseDatabaseWrapper._old_cursor


@pytest.fixture(scope="session")
def setup_db(request):
    """
    This fixture is called automatically by `db`,
    so a test database will only be setup if the `db` fixture is used.
    """
    verbosity = request.config.option.verbose

    # Set up the test db across the entire session
    _old_db_config = setup_databases(verbosity=verbosity)

    # Keep connections open during request client / testing
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)

    yield _old_db_config

    # Put the signals back...
    request_started.connect(close_old_connections)
    request_finished.connect(close_old_connections)

    # When the test session is done, tear down the test db
    teardown_databases(_old_db_config, verbosity=verbosity)


@pytest.fixture()
def db(setup_db):
    # Set .cursor() back to the original implementation
    BaseDatabaseWrapper.cursor = BaseDatabaseWrapper._old_cursor

    # Keep track of the atomic blocks so we can roll them back
    atomics = {}

    for connection in connections.all():
        # By default we use transactions to rollback changes,
        # so we need to ensure the database supports transactions
        if not connection.features.supports_transactions:
            pytest.fail("Database does not support transactions")

        # Clear the queries log before each test?
        # connection.queries_log.clear()

        atomic = transaction.atomic(using=connection.alias)
        atomic._from_testcase = True  # TODO remove this somehow?
        atomic.__enter__()
        atomics[connection] = atomic

    yield setup_db

    for connection, atomic in atomics.items():
        if (
            connection.features.can_defer_constraint_checks
            and not connection.needs_rollback
            and connection.is_usable()
        ):
            connection.check_constraints()

        transaction.set_rollback(True, using=connection.alias)
        atomic.__exit__(None, None, None)

        connection.close()


# @pytest.fixture(scope="function")
# def transactional_db(request, _plain_db_setup):
#     BaseDatabaseWrapper.cursor = BaseDatabaseWrapper._cursor

#     yield

#     # Flush databases instead of rolling back transactions...

#     connections.close_all()
