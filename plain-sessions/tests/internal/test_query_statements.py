"""The SQL SessionStore.save() emits, pinned statement by statement.

save() is one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`. It used to be
`update_or_create()`: a `SELECT ... FOR UPDATE` followed by an INSERT or an
UPDATE, inside a transaction. These pin the statement list so a regression back
to the read-then-write shape shows up as a failing test rather than as extra
round trips in production.

The SAVEPOINT / RELEASE SAVEPOINT statements come from save()'s own
`transaction.atomic()` nesting inside the `db` fixture's outer transaction.
"""

from __future__ import annotations

import concurrent.futures
import threading
from datetime import timedelta

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from plain.postgres.connection import DatabaseConnection
from plain.postgres.db import _db_conn, get_connection
from plain.postgres.sources import DirectSource
from plain.sessions.core import SessionStore
from plain.sessions.models import Session
from plain.utils import timezone


def statements(otel_spans: InMemorySpanExporter) -> list[str]:
    """Every SQL statement the captured spans carry, in the order it ran."""
    return [
        " ".join(str(span.attributes["db.query.text"]).split())
        for span in otel_spans.get_finished_spans()
        if span.attributes and "db.query.text" in span.attributes
    ]


def test_new_session_save_is_one_insert_on_conflict(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    store = SessionStore()
    store["a"] = 1

    otel_spans.clear()
    store.save()

    sql = statements(otel_spans)
    assert len(sql) == 4
    assert sql[0].startswith("SAVEPOINT")
    # _get_new_session_key() checks the key it minted isn't already taken.
    assert sql[1].startswith("SELECT")
    assert sql[2].startswith('INSERT INTO "plainsessions_session"')
    assert 'ON CONFLICT("session_key") DO UPDATE SET' in sql[2]
    assert "RETURNING" in sql[2]
    assert sql[3].startswith("RELEASE SAVEPOINT")


def test_resaving_a_session_is_one_insert_on_conflict(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    store = SessionStore()
    store["a"] = 1
    store.save()

    reopened = SessionStore(store.session_key)
    reopened["a"] = 2  # loads the row, before we start capturing

    otel_spans.clear()
    reopened.save()

    sql = statements(otel_spans)
    assert len(sql) == 3
    assert sql[0].startswith("SAVEPOINT")
    assert sql[1].startswith('INSERT INTO "plainsessions_session"')
    assert 'ON CONFLICT("session_key") DO UPDATE SET' in sql[1]
    assert "RETURNING" in sql[1]
    assert sql[2].startswith("RELEASE SAVEPOINT")

    # No SELECT ... FOR UPDATE: the conflict clause decides which row is written.
    assert not any("FOR UPDATE" in statement for statement in sql)


def test_conflict_updates_the_session_but_not_created_at(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    store = SessionStore()
    store["a"] = 1
    store.save()

    reopened = SessionStore(store.session_key)
    reopened["a"] = 2

    otel_spans.clear()
    reopened.save()

    insert = next(s for s in statements(otel_spans) if s.startswith("INSERT"))
    set_clause = insert.split("DO UPDATE SET")[1].split(" RETURNING ")[0]
    assert '"expires_at" = EXCLUDED."expires_at"' in set_clause
    assert '"session_data" = EXCLUDED."session_data"' in set_clause
    # created_at is the row's creation time -- a conflict must not reset it.
    assert '"created_at"' not in set_clause


def test_concurrent_saves_of_one_session_key_write_one_row(isolated_db: None) -> None:
    """Eight requests carrying the same session cookie, saving at once.

    One statement per save, so there is no read-then-write window for a second
    writer to slip into. Each thread needs its own connection: the connection
    ContextVar does not cross thread boundaries.
    """
    workers = 8
    session_key = "y" * 32
    Session(
        session_key=session_key,
        session_data={"seed": True},
        expires_at=timezone.now() + timedelta(days=14),
    ).create()

    config = get_connection().settings_dict
    barrier = threading.Barrier(workers)
    errors: list[str] = []

    def save_concurrently(i: int) -> None:
        connection = DatabaseConnection(DirectSource(config))
        _db_conn.set(connection)
        try:
            store = SessionStore(session_key)
            store[f"w{i}"] = i
            barrier.wait()
            store.save()
        except Exception as e:
            errors.append(repr(e))
        finally:
            connection.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(save_concurrently, range(workers)))

    assert errors == []
    assert Session.query.filter(session_key=session_key).count() == 1
