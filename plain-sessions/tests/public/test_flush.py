"""Flushing a session: what it deletes, and what it never has to look up.

A store that was never saved has no session key, so there is no row to delete
and flush() must not go to the database at all. A store with a saved key
deletes that row. Either way the store ends up empty with no key.
"""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from plain.sessions.core import SessionStore
from plain.sessions.models import Session


def statements(otel_spans: InMemorySpanExporter) -> list[str]:
    """Every SQL statement the captured spans carry, in the order it ran."""
    return [
        " ".join(str(span.attributes["db.query.text"]).split())
        for span in otel_spans.get_finished_spans()
        if span.attributes and "db.query.text" in span.attributes
    ]


def test_flushing_a_keyless_session_queries_nothing(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    store = SessionStore()
    store["a"] = 1

    # Canary: prove the exporter is actually capturing statements, so the
    # zero-statement assertion below can't pass because capture is broken.
    otel_spans.clear()
    Session.query.exists()
    assert statements(otel_spans) != []

    otel_spans.clear()
    store.flush()

    assert statements(otel_spans) == []
    assert store.session_key is None
    assert store.is_empty()
    assert dict(store) == {}


def test_flushing_a_saved_session_deletes_the_row(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    store = SessionStore()
    store["a"] = 1
    store.save()
    key = store.session_key
    assert key is not None

    otel_spans.clear()
    store.flush()

    sql = statements(otel_spans)
    assert len(sql) == 2
    assert sql[0].startswith("SELECT")
    assert sql[1].startswith('DELETE FROM "plainsessions_session"')

    assert store.session_key is None
    assert store.is_empty()
    assert dict(store) == {}
    assert not Session.query.where(Session.session_key.equals(key)).exists()
