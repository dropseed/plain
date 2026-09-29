"""
A run of the tests has databases of its own, and while it runs nothing in
the process reaches the configured one.

The first tests here are about this run. The rest run the tests of an app
made for the purpose, in a process of its own, against a configured
database that doesn't exist: so a connection to it can't go unnoticed.
"""

import threading

from plain.postgres import get_connection
from plain.postgres.databases import (
    create_database,
    database_exists,
    drop_database,
    list_databases,
)
from plain.postgres.test import isolated_db
from plain.postgres.test.database import RunDatabases, shared_database_name
from plain.runtime import settings
from postgres_test_helpers import ScratchApp, clean_connection, make_scratch_app


def current_database() -> str:
    with get_connection().cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
        assert row is not None
        return row[0]


def current_database_in_a_thread() -> list[str]:
    """What a thread started here finds. A thread has a context of its own,
    with no connection in it, so `get_connection()` makes it one."""
    found: list[str] = []
    thread = threading.Thread(target=lambda: found.append(current_database()))
    thread.start()
    thread.join(10)
    return found


def test_a_thread_reaches_the_test_database():
    mine = current_database()

    assert mine.startswith("test_")
    assert current_database_in_a_thread() == [mine]


@isolated_db
def test_a_thread_in_an_isolated_test_reaches_that_tests_database():
    mine = current_database()

    assert mine.startswith("test_")
    assert "_a_thread_in" in mine
    assert current_database_in_a_thread() == [mine]


def test_a_new_connection_in_a_context_without_one_reaches_the_test_database():
    mine = current_database()

    with clean_connection():
        assert current_database() == mine


def test_the_configured_database_is_the_test_database():
    mine = current_database()

    assert str(settings.POSTGRES_URL).endswith(f"/{mine}")


def test_a_threads_connection_is_not_the_tests():
    """It is another session: what the test wrote and hasn't committed
    isn't there for it to see."""
    with get_connection().cursor() as cursor:
        cursor.execute("CREATE TABLE made_by_the_test (id int)")

    found: list[bool] = []

    def look() -> None:
        with get_connection().cursor() as cursor:
            cursor.execute("SELECT to_regclass('made_by_the_test') IS NOT NULL")
            row = cursor.fetchone()
            assert row is not None
            found.append(row[0])

    thread = threading.Thread(target=look)
    thread.start()
    thread.join(10)

    assert found == [False]


# ---------------------------------------------------------------------------
# A run in a process of its own
# ---------------------------------------------------------------------------

_TESTS_THAT_CONNECT_EVERY_WAY = {
    "tests/test_connections.py": """
import os
import threading

from plain.postgres import get_connection
from plain.postgres.db import _db_conn, use_management_connection
from plain.postgres.test import isolated_db


def current_database(connection=None):
    connection = connection or get_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        return cursor.fetchone()[0]


def in_a_thread():
    found = []
    thread = threading.Thread(target=lambda: found.append(current_database()))
    thread.start()
    thread.join(10)
    return found


def in_a_context_without_a_connection():
    token = _db_conn.set(None)
    try:
        found = current_database()
        get_connection().close()
        return found
    finally:
        _db_conn.reset(token)


def test_the_rolled_back_way():
    mine = current_database()
    assert in_a_thread() == [mine]
    assert in_a_context_without_a_connection() == mine
    with use_management_connection() as management:
        assert current_database(management) == mine


@isolated_db
def test_the_isolated_way():
    mine = current_database()
    assert in_a_thread() == [mine]
    assert in_a_context_without_a_connection() == mine
    with use_management_connection() as management:
        assert current_database(management) == mine
""",
}


def test_no_connection_of_a_run_is_to_the_configured_database():
    app = make_scratch_app(_TESTS_THAT_CONNECT_EVERY_WAY)

    exit_code, output = app.run()

    assert exit_code == 0, output
    assert "2 passed" in output
    connected_to = app.connected_to()
    assert connected_to, "the run made connections, and none were recorded"
    assert app.configured_name not in connected_to
    start = shared_database_name(app.configured_name, run_token="r")
    assert {name for name in connected_to if not name.startswith(start)} == {"postgres"}


def test_a_management_url_of_its_own_is_pointed_at_the_test_database_too():
    app = make_scratch_app(_TESTS_THAT_CONNECT_EVERY_WAY)

    # Another URL for the same database, so it isn't the runtime URL and a
    # management connection is one of its own.
    exit_code, output = app.run(
        environment={
            "PLAIN_POSTGRES_MANAGEMENT_URL": f"{app.configured_url}?application_name=management"
        }
    )

    assert exit_code == 0, output
    assert app.configured_name not in app.connected_to()


_A_TEST_THAT_TAKES_A_WHILE = {
    "tests/test_slowly.py": """
import time

from plain.postgres import get_connection


def test_slowly():
    with get_connection().cursor() as cursor:
        cursor.execute("SELECT current_database()")
        print("database:", cursor.fetchone()[0])
    time.sleep(1.5)
""",
}


def _test_databases_of(app: ScratchApp) -> list[str]:
    """The test databases of an app that are on the server now."""
    start = shared_database_name(app.configured_name, run_token="")
    return [
        database.name
        for database in list_databases(app.config)
        if database.name.startswith(start)
    ]


def test_runs_at_the_same_moment_each_have_a_database():
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)

    runs = [app.start_run() for _ in range(3)]
    outputs = [run.communicate(timeout=120)[0] for run in runs]

    assert [run.returncode for run in runs] == [0, 0, 0], "\n".join(outputs)
    used = {name for name in app.connected_to() if name != "postgres"}
    assert len(used) == 3, used
    assert app.configured_name not in used
    assert _test_databases_of(app) == []


def test_what_a_killed_run_left_is_removed_by_the_next_run():
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    # What a run leaves when it is killed: its databases, and no lock held,
    # since the lock went with its connection.
    left_shared = shared_database_name(app.configured_name, run_token="r4000001")
    left_isolated = f"{left_shared}_something"
    create_database(app.config, name=left_shared)
    create_database(app.config, name=left_isolated)
    try:
        exit_code, output = app.run()

        assert exit_code == 0, output
        assert _test_databases_of(app) == []
    finally:
        drop_database(app.config, name=left_shared, force=True)
        drop_database(app.config, name=left_isolated, force=True)


def test_a_database_a_live_run_holds_is_left_alone():
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    # A run that is alive, and at the moment nothing is connected to its
    # database: it has created it and not yet connected.
    live = RunDatabases(runtime_url=app.configured_url, management_url="")
    live.claim()
    try:
        create_database(app.config, name=live.shared_name)

        exit_code, output = app.run()

        assert exit_code == 0, output
        assert _test_databases_of(app) == [live.shared_name]
    finally:
        drop_database(app.config, name=live.shared_name, force=True)
        live.release()


def test_a_run_that_ends_gives_its_name_up():
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    first = RunDatabases(runtime_url=app.configured_url, management_url="")
    second = RunDatabases(runtime_url=app.configured_url, management_url="")

    first.claim()
    try:
        # The same process, so the same process id: the name is taken.
        second.claim()
        try:
            assert second.shared_name != first.shared_name
            assert second.shared_name.startswith(f"{first.shared_name}x")
        finally:
            second.release()
    finally:
        first.release()

    second.claim()
    try:
        assert second.shared_name == first.shared_name
        assert not database_exists(app.config, name=second.shared_name)
    finally:
        second.release()
