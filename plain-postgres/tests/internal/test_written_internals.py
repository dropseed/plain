"""What `sql()` learns on a statement's first execution, and keeps.

The user-visible contract is in tests/public/test_written_sql.py. This pins the
machinery underneath it: the plan cache keyed on the result columns, the
batched catalog lookup that attaches converters, the row limits `first()` and
`get()` push into the statement, and the query span.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from app.examples.models.encrypted import SecretStore
from app.examples.models.relationships import Widget
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from plain.postgres import written
from plain.postgres.db import get_connection


@pytest.fixture(autouse=True)
def _empty_caches():
    """Start every test with nothing learned yet."""
    written._plans.clear()
    written._catalog_cache.clear()
    yield
    written._plans.clear()
    written._catalog_cache.clear()


def _plans() -> dict:
    """The plans learned on this connection.

    Both caches hang off the connection: a signature carries table OIDs, and
    those belong to one database.
    """
    return written._plans.get(get_connection(), {})


@dataclass
class NameRow:
    name: str


def _catalog_queries(queries: list[dict]) -> list[str]:
    return [query["sql"] for query in queries if "pg_attribute" in query["sql"]]


def test_the_plan_is_built_once_per_result_shape(db, capture_queries):
    def run() -> None:
        Widget.query.sql(
            "SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.size} = {size}",
            size="small",
            result_type=NameRow,
        ).all()

    with capture_queries() as first:
        run()
    assert len(_catalog_queries(first)) == 1
    assert len(_plans()) == 1

    with capture_queries() as second:
        run()
    # The same columns came back, so the plan is reused and nothing goes back
    # to the catalog.
    assert _catalog_queries(second) == []
    assert len(_plans()) == 1


def test_a_different_result_shape_gets_its_own_plan(db):
    """Two statements that return different columns can't share a plan."""

    @dataclass
    class SizeRow:
        size: str

    Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget}", result_type=NameRow
    ).all()
    Widget.query.sql(
        "SELECT {Widget.size} AS size FROM {Widget}", result_type=SizeRow
    ).all()

    assert len(_plans()) == 2


def test_a_per_call_result_type_does_not_grow_the_cache(db):
    """The cache is keyed on the columns, so a local dataclass can't leak."""

    def run() -> None:
        @dataclass
        class Row:
            name: str

        Widget.query.sql(
            "SELECT {Widget.name} AS name FROM {Widget}", result_type=Row
        ).all()

    for _ in range(3):
        run()

    assert len(_plans()) == 1


def test_the_catalog_lookup_is_one_query_for_every_column(db, capture_queries):
    @dataclass
    class SecretRow:
        name: str
        api_key: str
        notes: str
        config: dict | None

    SecretStore.query.create(name="prod", api_key="k", notes="n", config={"a": 1})

    with capture_queries() as queries:
        SecretStore.query.sql(
            """
            SELECT {SecretStore.name} AS name,
                   {SecretStore.api_key} AS api_key,
                   {SecretStore.notes} AS notes,
                   {SecretStore.config} AS config
            FROM {SecretStore}
            """,
            result_type=SecretRow,
        ).all()

    assert len(_catalog_queries(queries)) == 1


def test_converters_are_attached_to_the_columns_that_have_a_field(db):
    SecretStore.query.create(name="prod", api_key="k", notes="n", config={"a": 1})

    @dataclass
    class SecretRow:
        name: str
        api_key: str

    SecretStore.query.sql(
        """
        SELECT {SecretStore.name} AS name, {SecretStore.api_key} AS api_key
        FROM {SecretStore}
        """,
        result_type=SecretRow,
    ).all()

    (plan,) = _plans().values()
    # `name` is a plain TextField and needs no converter; `api_key` decrypts.
    assert list(plan.converters) == [1]
    converters, expression = plan.converters[1]
    assert expression.target.name == "api_key"
    assert converters


def test_an_expression_column_resolves_to_no_field(db):
    Widget.query.create(name="one", size="small")

    @dataclass
    class UpperRow:
        shouted: str

    Widget.query.sql(
        "SELECT upper({Widget.name}) AS shouted FROM {Widget}",
        result_type=UpperRow,
    ).all()

    (plan,) = _plans().values()
    assert plan.converters == {}


def test_first_and_get_push_a_limit_into_the_statement(db, capture_queries):
    for index in range(5):
        Widget.query.create(name=f"w{index}", size="small")

    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} ORDER BY {Widget.name}"
    )
    with capture_queries() as queries:
        assert statement.first() is not None

    limited = [query["sql"] for query in queries if "LIMIT 1" in query["sql"]]
    assert limited, "first() should have asked for one row"

    one = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.name} = {name}", name="w0"
    )
    with capture_queries() as queries:
        one.get()
    assert [query["sql"] for query in queries if "LIMIT 2" in query["sql"]]


def test_count_and_exists_are_memoised(db, capture_queries):
    Widget.query.create(name="one", size="small")
    statement = Widget.query.sql("SELECT {Widget.*} FROM {Widget}")

    with capture_queries() as queries:
        assert statement.count() == 1
        assert statement.count() == 1
        assert statement.exists() is True

    counted = [query["sql"] for query in queries if "count(*)" in query["sql"]]
    assert len(counted) == 1
    assert not [query["sql"] for query in queries if "EXISTS" in query["sql"]]

    # exists() on its own memoises too.
    fresh = Widget.query.sql("SELECT {Widget.*} FROM {Widget}")
    with capture_queries() as queries:
        assert fresh.exists() is True
        assert fresh.exists() is True
    assert len([q["sql"] for q in queries if "EXISTS" in q["sql"]]) == 1


def test_a_write_is_never_wrapped_for_counting(db, capture_queries):
    statement = Widget.query.sql(
        """
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget.*}
        """,
        name="one",
        size="small",
    )
    with capture_queries() as queries:
        assert statement.count() == 1
        assert statement.exists() is True

    assert not [query["sql"] for query in queries if "count(*)" in query["sql"]]
    assert Widget.query.filter(name="one").count() == 1


def test_a_statement_opens_a_client_span_with_the_sql_as_written(
    db, otel_spans: InMemorySpanExporter
):
    Widget.query.create(name="one", size="small")
    otel_spans.clear()

    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}", size="small"
    )
    statement.all()

    spans = [
        span
        for span in otel_spans.get_finished_spans()
        if span.attributes and span.attributes.get("db.query.text") == statement.sql
    ]
    assert spans, "no span carrying the rendered statement"
    assert spans[-1].kind is SpanKind.CLIENT
    # One span per statement -- the cursor wrapper's own is suppressed so the
    # span can carry the SQL as written rather than the escaped form.
    assert len(spans) == 1


def test_the_catalog_lookup_is_not_traced(db, otel_spans: InMemorySpanExporter):
    otel_spans.clear()

    Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget}", result_type=NameRow
    ).all()

    traced = [
        span
        for span in otel_spans.get_finished_spans()
        if span.attributes
        and "pg_attribute" in str(span.attributes.get("db.query.text"))
    ]
    assert traced == []


def test_the_catalog_cache_is_per_connection(db):
    Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget}", result_type=NameRow
    ).all()
    assert get_connection() in written._catalog_cache


def test_the_plan_cache_hangs_off_the_connection(db):
    Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget}", result_type=NameRow
    ).all()
    assert get_connection() in written._plans
