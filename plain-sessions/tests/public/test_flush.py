"""Flushing a session: what it deletes, and what it never has to look up.

A store that was never saved has no session key, so there is no row to delete
and flush() must not go to the database at all. A store with a saved key
deletes that row. Either way the store ends up empty with no key.
"""

from plain.postgres.test import span_sql_statements
from plain.sessions.core import SessionStore
from plain.sessions.models import Session
from plain.test import capture_spans


def test_flushing_a_keyless_session_queries_nothing() -> None:
    store = SessionStore()
    store["a"] = 1

    # Canary: prove the exporter is actually capturing statements, so the
    # zero-statement assertion below can't pass because capture is broken.
    with capture_spans() as canary_spans:
        Session.query.exists()
    assert span_sql_statements(canary_spans) != []

    with capture_spans() as spans:
        store.flush()

    assert span_sql_statements(spans) == []
    assert store.session_key is None
    assert store.is_empty()
    assert dict(store) == {}


def test_flushing_a_saved_session_deletes_the_row() -> None:
    store = SessionStore()
    store["a"] = 1
    store.save()
    key = store.session_key
    assert key is not None

    with capture_spans() as spans:
        store.flush()

    sql = span_sql_statements(spans)
    assert len(sql) == 2
    assert sql[0].startswith("SELECT")
    assert sql[1].startswith('DELETE FROM "plainsessions_session"')

    assert store.session_key is None
    assert store.is_empty()
    assert dict(store) == {}
    assert not Session.query.where(Session.session_key.equals(key)).exists()
