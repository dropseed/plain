"""What one test leaves for the next.

Every test that isn't `@isolated_db` runs in a transaction that is rolled
back, on a connection the tests share. The rollback undoes what the test did
in its transaction. What belongs to the session carries over.

These tests come in pairs: the first does something, and the one after it
looks at what is left. The second of a pair run on its own has nothing to
look at, and is skipped.
"""

from app.examples.models.relationships import Tag
from plain.postgres import get_connection
from plain.testing import skip_test

backend_pids: list[int] = []
changed_the_session = []
committed_for_itself = []


def fetch_value(sql: str) -> object:
    with get_connection().cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_a_test_runs_on_a_connection():
    backend_pids.append(fetch_value("SELECT pg_backend_pid()"))  # ty: ignore[invalid-argument-type]


def test_the_next_test_runs_on_the_same_connection():
    if not backend_pids:
        skip_test("Compares with the connection the test above it ran on")

    assert fetch_value("SELECT pg_backend_pid()") == backend_pids[0]


def test_a_test_changes_what_a_transaction_can_change():
    Tag.query.create(name="left behind")
    with get_connection().cursor() as cursor:
        cursor.execute("SET statement_timeout = '123s'")
        cursor.execute("CREATE TEMPORARY TABLE left_behind (id integer)")
    changed_the_session.append(True)

    assert fetch_value("SHOW statement_timeout") == "123s"


def test_the_rollback_undid_all_of_it():
    if not changed_the_session:
        skip_test("Looks at what the test above it left behind")

    assert not Tag.query.filter(name="left behind").exists()
    assert fetch_value("SHOW statement_timeout") != "123s"
    assert fetch_value("SELECT to_regclass('pg_temp.left_behind')") is None


def test_a_test_opens_a_transaction_of_the_drivers_own_first():
    # With no transaction open, psycopg's `connection.transaction()` begins
    # one and commits it. A test's transaction is open before its first
    # statement, so this is a savepoint inside it.
    with get_connection().cursor() as cursor, cursor.connection.transaction():
        cursor.execute("CREATE TEMPORARY TABLE committed_for_itself (id integer)")
        Tag.query.create(name="committed for itself")
    committed_for_itself.append(True)


def test_the_rollback_undid_that_too():
    if not committed_for_itself:
        skip_test("Looks at what the test above it left behind")

    assert not Tag.query.filter(name="committed for itself").exists()
    assert fetch_value("SELECT to_regclass('pg_temp.committed_for_itself')") is None
