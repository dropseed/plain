"""What `sql()` learns on a statement's first execution, and keeps.

The user-visible contract is in tests/public/test_written_sql.py. This pins the
machinery underneath it: how a `Template` is walked into SQL and parameters,
the plan cache keyed on the result columns, the batched catalog lookup that
attaches converters, the row limits `first()` and `get()` push into the
statement, and the query span.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from app.examples.models.encrypted import SecretStore
from app.examples.models.relationships import Tag, Widget
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


# ---------------------------------------------------------------------------
# The template walk
# ---------------------------------------------------------------------------


def test_the_template_walk_alternates_text_and_interpolations(db):
    """`strings` has one more entry than `interpolations`, and both land."""
    size = "small"
    rendered = written._render(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size}"
    )
    table = Widget.model_options.db_table
    assert rendered.sql.startswith("SELECT ")
    assert f'"{table}"."size" = %s' in rendered.sql
    assert rendered.params == ("small",)


def test_a_nested_template_renders_into_the_same_statement(db):
    """A nested `Template` is inlined, and its parameters merge in order."""
    first = "small"
    second = "large"
    inner = t"{Widget.size} = {first}"
    rendered = written._render(
        t"SELECT {Widget:*} FROM {Widget} WHERE {inner} OR {Widget.size} = {second}"
    )
    table = Widget.model_options.db_table
    assert rendered.sql.count(f'"{table}"."size" = %s') == 2
    assert rendered.params == ("small", "large")
    # The nesting is flattened -- one statement, one star expansion.
    assert len(rendered.stars) == 1


def test_a_star_records_the_model_columns_in_declared_order(db):
    rendered = written._render(t"SELECT {Widget:*} FROM {Widget}")
    (star,) = rendered.stars
    assert star.model is Widget
    assert star.columns == tuple(field.column for field in Widget._model_meta.fields)


def test_two_stars_are_two_expansions(db):
    rendered = written._render(t"SELECT {Widget:*}, {Tag:*} FROM {Widget}, {Tag}")
    assert [star.model for star in rendered.stars] == [Widget, Tag]


def test_author_text_is_percent_doubled_only_for_binding(db):
    """psycopg parses `%s` in the text it is handed; `.sql` shows it as written."""
    pattern = "small"
    rendered = written._render(
        t"SELECT 1 FROM {Widget} WHERE {Widget.name} LIKE {pattern} || '%'"
    )
    assert rendered.sql.endswith("|| '%'")
    assert rendered.bind_sql.endswith("|| '%%'")


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_the_plan_is_built_once_per_result_shape(db, capture_queries):
    def run() -> None:
        size = "small"
        Widget.query.sql(
            t"SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.size} = {size}",
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
        t"SELECT {Widget.name} AS name FROM {Widget}", result_type=NameRow
    ).all()
    Widget.query.sql(
        t"SELECT {Widget.size} AS size FROM {Widget}", result_type=SizeRow
    ).all()

    assert len(_plans()) == 2


def test_a_per_call_result_type_does_not_grow_the_cache(db):
    """The cache is keyed on the columns, so a local dataclass can't leak."""

    def run() -> None:
        @dataclass
        class Row:
            name: str

        Widget.query.sql(
            t"SELECT {Widget.name} AS name FROM {Widget}", result_type=Row
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
            t"""
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
        t"""
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
        t"SELECT upper({Widget.name}) AS shouted FROM {Widget}",
        result_type=UpperRow,
    ).all()

    (plan,) = _plans().values()
    assert plan.converters == {}


def test_first_and_get_push_a_limit_into_the_statement(db, capture_queries):
    for index in range(5):
        Widget.query.create(name=f"w{index}", size="small")

    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} ORDER BY {Widget.name}"
    )
    with capture_queries() as queries:
        assert statement.first() is not None

    limited = [query["sql"] for query in queries if "LIMIT 1" in query["sql"]]
    assert limited, "first() should have asked for one row"

    name = "w0"
    one = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.name} = {name}"
    )
    with capture_queries() as queries:
        one.get()
    assert [query["sql"] for query in queries if "LIMIT 2" in query["sql"]]


def test_count_and_exists_are_memoised(db, capture_queries):
    Widget.query.create(name="one", size="small")
    statement = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget}")

    with capture_queries() as queries:
        assert statement.count() == 1
        assert statement.count() == 1
        assert statement.exists() is True

    counted = [query["sql"] for query in queries if "count(*)" in query["sql"]]
    assert len(counted) == 1
    assert not [query["sql"] for query in queries if "EXISTS" in query["sql"]]

    # exists() on its own memoises too.
    fresh = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget}")
    with capture_queries() as queries:
        assert fresh.exists() is True
        assert fresh.exists() is True
    assert len([q["sql"] for q in queries if "EXISTS" in q["sql"]]) == 1


def test_a_write_is_never_wrapped_for_counting(db, capture_queries):
    name = "one"
    size = "small"
    statement = Widget.query.sql(
        t"""
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget:*}
        """
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

    size = "small"
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size}"
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
        t"SELECT {Widget.name} AS name FROM {Widget}", result_type=NameRow
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
        t"SELECT {Widget.name} AS name FROM {Widget}", result_type=NameRow
    ).all()
    assert get_connection() in written._catalog_cache


def test_the_plan_cache_hangs_off_the_connection(db):
    Widget.query.sql(
        t"SELECT {Widget.name} AS name FROM {Widget}", result_type=NameRow
    ).all()
    assert get_connection() in written._plans


def test_a_written_statement_is_never_prepared(db):
    """`prepare=False` has to reach psycopg, not just the docstring.

    A named prepared statement is the one thing a transaction-mode pooler
    can't follow, and `prepare_threshold` is configurable — at 0 psycopg
    names every statement it can unless told otherwise.
    """
    Widget.query.create(name="one", size="small")
    connection = get_connection()
    connection.ensure_connection()
    assert connection.connection is not None
    previous = connection.connection.prepare_threshold
    connection.connection.prepare_threshold = 0
    try:
        for _ in range(3):
            size = "small"
            Widget.query.sql(
                t"SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.size} = {size}",
                result_type=NameRow,
            ).all()

        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_prepared_statements")
            row = cursor.fetchone()
        assert row is not None
        assert row[0] == 0
    finally:
        connection.connection.prepare_threshold = previous
