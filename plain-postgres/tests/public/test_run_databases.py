"""
A run of the tests has databases of its own, and while it runs nothing in
the process reaches the configured one.

The first tests here are about this run. The rest run the tests of an app
made for the purpose, in a process of its own, against a configured
database that doesn't exist: so a connection to it can't go unnoticed.
"""

import json
import re
import subprocess
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace

import psycopg
from plain.postgres import get_connection
from plain.postgres.database_url import DatabaseConfig
from plain.postgres.databases import (
    create_database,
    database_exists,
    drop_database,
    list_databases,
    set_database_comment,
)
from plain.postgres.sources import build_connection_params
from plain.postgres.testing import isolated_db
from plain.postgres.testing.database import RunDatabases, shared_database_name
from plain.postgres.testing.leftovers import RunRecord, read_template_record
from plain.postgres.testing.schema import SchemaDigest
from plain.runtime import settings
from postgres_test_helpers import (
    ScratchApp,
    clean_connection,
    make_scratch_app,
    scratch_database_name,
    templates_of,
)

# A run claimed here, in this process, never builds or clones a template:
# it takes a name and looks at what is there. Any digest will do.
A_SCHEMA = SchemaDigest(hash="a" * 64, migrations=0)


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
from plain.postgres.testing import isolated_db


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
    # The run's own databases, and the template it built and cloned.
    start = shared_database_name(app.configured_name, run_token="")
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
    """The test databases of an app's runs that are on the server now. Not
    the template they clone, which stays."""
    start = shared_database_name(app.configured_name, run_token="")
    return [
        database.name
        for database in list_databases(app.config)
        if database.name.startswith(start)
        and read_template_record(database.comment) is None
    ]


def test_runs_at_the_same_moment_each_have_a_database():
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)

    runs = [app.start_run() for _ in range(3)]
    outputs = [run.communicate(timeout=120)[0] for run in runs]

    assert [run.returncode for run in runs] == [0, 0, 0], "\n".join(outputs)
    templates = templates_of(app)
    used = {
        name
        for name in app.connected_to()
        if name != "postgres" and name not in templates
    }
    assert len(used) == 3, used
    assert app.configured_name not in used
    assert _test_databases_of(app) == []


def a_process_id_nothing_has() -> int:
    """The id of a process that has just ended."""
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def what_a_killed_run_wrote(app: ScratchApp) -> RunRecord:
    """The record of a run of `app` that is gone: nobody holds its lock,
    and its process isn't running."""
    live = RunDatabases(runtime_url=app.configured_url, management_url="")
    live.claim(schema=A_SCHEMA)
    try:
        pid = a_process_id_nothing_has()
        return replace(
            live.record_for_a_database(),
            run=shared_database_name(app.configured_name, run_token=f"r{pid}"),
            pid=pid,
        )
    finally:
        live.release()


@contextmanager
def a_database(config: DatabaseConfig, *, record: RunRecord | None) -> Generator[str]:
    """A database made for the block, under a name that is only a test's.
    Dropped at the end by that name, if it is still there."""
    name = scratch_database_name("left")
    create_database(config, name=name)
    try:
        if record is not None:
            set_database_comment(config, name=name, comment=record.as_comment())
        yield name
    finally:
        drop_database(config, name=name, force=True)


def test_what_a_killed_run_left_is_removed_by_the_next_run():
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    record = what_a_killed_run_wrote(app)

    with (
        a_database(app.config, record=record) as shared,
        a_database(app.config, record=replace(record, token="another")) as isolated,
    ):
        exit_code, output = app.run()

        assert exit_code == 0, output
        assert not database_exists(app.config, name=shared)
        assert not database_exists(app.config, name=isolated)
    assert _test_databases_of(app) == []


def test_a_database_with_no_record_is_left_by_the_next_run():
    """It is named the way a run of this app names its databases, and that
    proves nothing."""
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    named_like_a_runs = shared_database_name(app.configured_name, run_token="r4000001")
    create_database(app.config, name=named_like_a_runs)
    try:
        exit_code, output = app.run()

        assert exit_code == 0, output
        assert database_exists(app.config, name=named_like_a_runs)
    finally:
        drop_database(app.config, name=named_like_a_runs, force=True)


def test_a_database_of_a_run_of_another_database_is_left():
    """The other database's name starts with this one's."""
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    other = replace(
        what_a_killed_run_wrote(app), database=f"{app.configured_name}_fixes"
    )

    with a_database(app.config, record=other) as name:
        exit_code, output = app.run()

        assert exit_code == 0, output
        assert database_exists(app.config, name=name)


def test_a_database_a_live_run_holds_is_left_alone():
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    # A run that is alive, and at the moment nothing is connected to its
    # database: it has created it and not yet connected.
    live = RunDatabases(runtime_url=app.configured_url, management_url="")
    live.claim(schema=A_SCHEMA)
    try:
        # The process that made it isn't running, so the lock is all that
        # says the run is alive.
        record = replace(live.record_for_a_database(), pid=a_process_id_nothing_has())
        with a_database(app.config, record=record) as name:
            exit_code, output = app.run()

            assert exit_code == 0, output
            assert database_exists(app.config, name=name)
            assert name not in output
    finally:
        live.release()


def test_a_database_something_is_connected_to_is_left_and_the_run_says_so():
    """Nobody holds its run's lock, and its process is gone. But something
    is using it."""
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    record = what_a_killed_run_wrote(app)

    with a_database(app.config, record=record) as name:
        config: DatabaseConfig = {**app.config, "DATABASE": name}
        with psycopg.connect(**build_connection_params(config)):
            exit_code, output = app.run()

        assert exit_code == 0, output
        assert database_exists(app.config, name=name)
        assert f"Left the test database {name!r}: 1 connection is open" in output
        assert f"plain db drop {name}" in output


def test_a_database_whose_process_is_running_is_left_and_the_run_says_so():
    """Nobody holds its run's lock: the run lost its connection to the
    maintenance database, and lives on."""
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    running = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        record = replace(what_a_killed_run_wrote(app), pid=running.pid)
        with a_database(app.config, record=record) as name:
            exit_code, output = app.run()

            assert exit_code == 0, output
            assert database_exists(app.config, name=name)
            assert f"process {running.pid}, which made it, is running" in output
    finally:
        running.kill()
        running.wait()


def written_by(test: str, output: str) -> tuple[str, str]:
    """The database's name and its record, as a test of the app printed them."""
    found = re.search(rf"{test} (\S+) (\{{.*\}})", output)
    assert found is not None, output
    return found[1], found[2]


def test_a_run_writes_its_record_into_the_databases_it_makes():
    app = make_scratch_app(
        {
            "tests/test_records.py": """
import json

from plain.postgres import get_connection
from plain.postgres.testing import isolated_db


def the_record():
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), shobj_description(oid, 'pg_database') "
            "FROM pg_database WHERE datname = current_database()"
        )
        name, comment = cursor.fetchone()
    return name, json.loads(comment)["plain_test_run"]


def test_the_shared_database():
    name, record = the_record()
    print("shared", name, json.dumps(record))


@isolated_db
def test_an_isolated_database():
    name, record = the_record()
    print("isolated", name, json.dumps(record))
""",
        }
    )

    exit_code, output = app.run(arguments=("--show-output",))

    assert exit_code == 0, output
    # Each line is a name and a record. With the output let through, the
    # runner's own progress can come before one on its line.
    shared_name, shared = written_by("shared", output)
    isolated_name, isolated = written_by("isolated", output)
    shared_record = json.loads(shared)
    isolated_record = json.loads(isolated)

    assert shared_record["database"] == app.configured_name
    assert shared_record["run"] == shared_name
    assert shared_record["directory"] == str(app.root)
    assert isolated_record["database"] == app.configured_name
    assert isolated_record["run"] == shared_name
    assert isolated_name.startswith(f"{shared_name}_")
    assert isolated_record["token"] != shared_record["token"]
    assert shared_record["pid"] == isolated_record["pid"]


def test_a_run_doesnt_replace_a_database_of_its_name_that_no_run_made():
    """A run that finds its name taken, by a database without its record,
    stops. It doesn't drop what it didn't make."""
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    process = app.start_run(hold_at_start=True)
    taken = shared_database_name(app.configured_name, run_token=f"r{process.pid}")
    create_database(app.config, name=taken)
    try:
        output, _ = process.communicate("go\n", timeout=120)

        assert process.returncode == 3, output
        assert f"A database named {taken!r} is already there" in output
        assert database_exists(app.config, name=taken)
    finally:
        drop_database(app.config, name=taken, force=True)


def test_a_run_that_ends_gives_its_name_up():
    app = make_scratch_app(_A_TEST_THAT_TAKES_A_WHILE)
    first = RunDatabases(runtime_url=app.configured_url, management_url="")
    second = RunDatabases(runtime_url=app.configured_url, management_url="")

    first.claim(schema=A_SCHEMA)
    try:
        # The same process, so the same process id: the name is taken.
        second.claim(schema=A_SCHEMA)
        try:
            assert second.shared_name != first.shared_name
            assert second.shared_name.startswith(f"{first.shared_name}x")
        finally:
            second.release()
    finally:
        first.release()

    second.claim(schema=A_SCHEMA)
    try:
        assert second.shared_name == first.shared_name
        assert not database_exists(app.config, name=second.shared_name)
    finally:
        second.release()
