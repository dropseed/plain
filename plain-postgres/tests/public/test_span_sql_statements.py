"""`span_sql_statements()` — the SQL a block of code sent, read off its spans.

The contract: one string per database span, in the order the statements ran,
with the placeholders left in and whitespace collapsed; `table=` narrows the
list to the statements that name a table; spans with no SQL are skipped.
"""

from app.examples.models.relationships import Tag, Widget, WidgetTag
from opentelemetry import trace
from plain.postgres.test import span_sql_statements
from plain.test import capture_spans

TAG_BY_NAME = (
    'SELECT "examples_tag"."id", "examples_tag"."name" '
    'FROM "examples_tag" WHERE "examples_tag"."name" = %s LIMIT 1'
)
WIDGET_BY_NAME = (
    'SELECT "examples_widget"."id", "examples_widget"."name", '
    '"examples_widget"."size" '
    'FROM "examples_widget" WHERE "examples_widget"."name" = %s LIMIT 1'
)


def test_statements_come_back_in_the_order_they_ran():
    with capture_spans() as spans:
        Tag.query.filter(name="red").first()
        Widget.query.filter(name="small").first()

    assert span_sql_statements(spans) == [TAG_BY_NAME, WIDGET_BY_NAME]


def test_whitespace_is_collapsed_to_single_spaces():
    with capture_spans() as spans:
        Tag.query.sql(
            t"""
            SELECT {Tag:*}
            FROM   {Tag}
            """
        ).all()

    assert span_sql_statements(spans) == [
        'SELECT "examples_tag"."id", "examples_tag"."name" FROM "examples_tag"'
    ]


def test_no_statements_is_an_empty_list():
    with capture_spans() as spans:
        pass

    assert span_sql_statements(spans) == []


def test_table_keeps_only_the_statements_naming_that_table():
    with capture_spans() as spans:
        Tag.query.filter(name="red").first()
        Widget.query.filter(name="small").first()
        Tag.query.filter(name="blue").first()

    assert span_sql_statements(spans, table="examples_tag") == [
        TAG_BY_NAME,
        TAG_BY_NAME,
    ]
    assert span_sql_statements(spans, table="examples_widget") == [WIDGET_BY_NAME]


def test_table_matches_the_quoted_identifier_not_a_prefix():
    with capture_spans() as spans:
        WidgetTag.query.count()

    # "examples_widget" is a prefix of "examples_widgettag", but the statement
    # never names the widget table itself.
    assert span_sql_statements(spans, table="examples_widget") == []
    assert len(span_sql_statements(spans, table="examples_widgettag")) == 1


def test_a_span_that_carries_no_sql_is_skipped():
    with (
        capture_spans() as spans,
        trace.get_tracer("test").start_as_current_span("not a query"),
    ):
        Tag.query.filter(name="red").first()

    assert [span.name for span in spans.get_finished_spans()][-1] == "not a query"
    assert span_sql_statements(spans) == [TAG_BY_NAME]
