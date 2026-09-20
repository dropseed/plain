"""The SQL cache.set_many() emits, pinned statement by statement.

set_many() is one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` per call,
whatever mix of new and existing keys it is handed. It used to be
`bulk_create(update_conflicts=True, ...)`, which produced the same statement
without the RETURNING clause and without sorting the rows by conflict key.
These pin the statement list, the SET clause, and the deadlock-freedom the
sorting buys.
"""

from __future__ import annotations

import concurrent.futures
import threading

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from plain.cache import cache
from plain.cache.models import CachedItem
from plain.postgres.connection import DatabaseConnection
from plain.postgres.db import _db_conn, get_connection
from plain.postgres.sources import DirectSource


def statements(otel_spans: InMemorySpanExporter) -> list[str]:
    """Every SQL statement the captured spans carry, in the order it ran."""
    return [
        " ".join(str(span.attributes["db.query.text"]).split())
        for span in otel_spans.get_finished_spans()
        if span.attributes and "db.query.text" in span.attributes
    ]


def assert_is_the_set_many_statement(sql: str) -> None:
    assert sql.startswith('INSERT INTO "plaincache_cacheditem"')
    assert 'ON CONFLICT("key") DO UPDATE SET' in sql
    assert "RETURNING" in sql

    set_clause = sql.split("DO UPDATE SET")[1].split(" RETURNING ")[0]
    assert '"value" = EXCLUDED."value"' in set_clause
    assert '"expires_at" = EXCLUDED."expires_at"' in set_clause
    assert '"updated_at" = EXCLUDED."updated_at"' in set_clause
    # created_at is the row's creation time -- a conflict must not reset it.
    assert '"created_at"' not in set_clause


def test_all_new_keys_is_one_statement(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    otel_spans.clear()
    cache.set_many({"a": 1, "b": 2})

    sql = statements(otel_spans)
    assert len(sql) == 1
    assert_is_the_set_many_statement(sql[0])


def test_all_existing_keys_is_one_statement(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    cache.set_many({"a": 1, "b": 2})

    otel_spans.clear()
    cache.set_many({"a": 10, "b": 20}, expiration=60)

    sql = statements(otel_spans)
    assert len(sql) == 1
    assert_is_the_set_many_statement(sql[0])


def test_mixed_new_and_existing_keys_is_one_statement(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    cache.set_many({"a": 1})

    otel_spans.clear()
    cache.set_many({"a": 100, "c": 3})

    sql = statements(otel_spans)
    assert len(sql) == 1
    assert_is_the_set_many_statement(sql[0])


def test_empty_mapping_runs_no_statements(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    otel_spans.clear()
    cache.set_many({})

    assert statements(otel_spans) == []


def test_concurrent_set_many_with_opposite_key_orders_does_not_deadlock(
    isolated_db: None,
) -> None:
    """Batches written in opposite orders at the same time.

    bulk_upsert() sorts the rows by conflict key, so every writer takes the
    row locks in the same order and none of them deadlock. Each thread needs
    its own connection: the connection ContextVar does not cross thread
    boundaries.
    """
    workers = 8
    keys = ["da", "db", "dc", "dd", "de"]

    config = get_connection().settings_dict
    barrier = threading.Barrier(workers)
    errors: list[str] = []

    def set_many_concurrently(i: int) -> None:
        connection = DatabaseConnection(DirectSource(config))
        _db_conn.set(connection)
        order = keys if i % 2 == 0 else list(reversed(keys))
        try:
            barrier.wait()
            for _ in range(10):
                cache.set_many({key: i for key in order})
        except Exception as e:
            errors.append(repr(e))
        finally:
            connection.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(set_many_concurrently, range(workers)))

    assert errors == []
    for key in keys:
        assert CachedItem.query.filter(key=key).count() == 1
