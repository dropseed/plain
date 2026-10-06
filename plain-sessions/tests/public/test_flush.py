"""Flushing a session: what it deletes, and what it never has to look up.

A store that was never saved has no session key, so there is no row to delete
and flush() must not go to the database at all. A store with a saved key
deletes that row. Either way the store ends up empty with no key.
"""

from plain.postgres.testing import capture_queries
from plain.sessions.core import SessionStore
from plain.sessions.models import Session


def test_flushing_a_keyless_session_queries_nothing() -> None:
    store = SessionStore()
    store["a"] = 1

    # Canary: prove the exporter is actually capturing statements, so the
    # zero-statement assertion below can't pass because capture is broken.
    with capture_queries() as canary_queries:
        Session.query.exists()
    assert canary_queries.sql_statements() != []

    with capture_queries() as queries:
        store.flush()

    assert queries.sql_statements() == []
    assert store.session_key is None
    assert store.is_empty()
    assert dict(store) == {}


def test_flushing_a_saved_session_deletes_the_row() -> None:
    store = SessionStore()
    store["a"] = 1
    store.save()
    key = store.session_key
    assert key is not None

    with capture_queries() as queries:
        store.flush()

    sql = queries.sql_statements()
    assert len(sql) == 2
    assert sql[0].startswith("SELECT")
    assert sql[1].startswith('DELETE FROM "plainsessions_session"')

    assert store.session_key is None
    assert store.is_empty()
    assert dict(store) == {}
    assert not Session.query.where(Session.session_key.equals(key)).exists()
