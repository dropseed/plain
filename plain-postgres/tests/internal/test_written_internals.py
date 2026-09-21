"""What `sql()` learns on a statement's first execution, and keeps.

The user-visible contract is in tests/public/test_written_sql.py. This pins
the machinery underneath it: the per-template plan cache, the batched catalog
lookup that resolves result columns back to model fields, the converters that
lookup attaches, and the query span.
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


@dataclass
class NameRow:
    name: str


def _catalog_queries(queries: list[dict]) -> list[str]:
    return [query["sql"] for query in queries if "pg_attribute" in query["sql"]]


def test_the_plan_is_built_once_per_template(db, capture_queries):
    def run() -> None:
        Widget.query.sql(
            "SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.size} = {size}",
            size="small",
            result_type=NameRow,
        ).all()

    with capture_queries() as first:
        run()
    assert len(_catalog_queries(first)) == 1
    assert len(written._plans) == 1

    with capture_queries() as second:
        run()
    # A second statement from the same template reuses the plan, so nothing
    # goes back to the catalog.
    assert _catalog_queries(second) == []
    assert len(written._plans) == 1


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

    (plan,) = written._plans.values()
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

    (plan,) = written._plans.values()
    assert plan.converters == {}


def test_a_statement_opens_a_client_span(db, otel_spans: InMemorySpanExporter):
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
