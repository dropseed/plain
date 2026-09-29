"""`capture_queries()` — what the database was asked to do during a block.

The contract: a read-only sequence of `CapturedQuery`, in the order the
queries ran, readable once the block ends. Each query carries the statement
as it was sent and the statement with its values filled in.
`sql_statements()` is the list to compare against SQL written out in a test.
"""

from app.examples.models.relationships import Tag, Widget, WidgetTag
from plain.postgres import transaction
from plain.postgres.otel import suppress_db_tracing
from plain.postgres.test import CapturedQuery, capture_queries, isolated_db, max_queries
from plain.testing import capture_spans, raises

TAG_BY_NAME = (
    'SELECT "examples_tag"."id", "examples_tag"."name" '
    'FROM "examples_tag" WHERE "examples_tag"."name" = %s LIMIT 1'
)
WIDGET_BY_NAME = (
    'SELECT "examples_widget"."id", "examples_widget"."name", '
    '"examples_widget"."size" '
    'FROM "examples_widget" WHERE "examples_widget"."name" = %s LIMIT 1'
)


def test_it_is_a_sequence_of_the_queries_in_the_order_they_ran():
    with capture_queries() as queries:
        Tag.query.filter(name="red").first()
        Widget.query.filter(name="small").first()

    assert len(queries) == 2
    assert [query.sql for query in queries] == [TAG_BY_NAME, WIDGET_BY_NAME]
    assert isinstance(queries[0], CapturedQuery)
    assert queries[-1].sql == WIDGET_BY_NAME


def test_a_block_that_runs_nothing_captures_nothing():
    with capture_queries() as queries:
        pass

    assert not queries
    assert list(queries) == []
    assert queries.sql_statements() == []


def test_a_query_carries_the_statement_as_sent_and_with_its_values():
    with capture_queries() as queries:
        Tag.query.filter(name="red").first()

    [query] = queries
    assert query.sql == TAG_BY_NAME
    assert query.sql_with_params == TAG_BY_NAME.replace("%s", "'red'")


def test_reading_inside_the_block_raises():
    with capture_queries() as queries:
        Tag.query.filter(name="red").first()
        with raises(RuntimeError, match="after the `with capture_queries\\(\\)` block"):
            len(queries)

    assert len(queries) == 1


def test_a_block_that_raises_still_has_what_it_captured():
    with raises(ZeroDivisionError), capture_queries() as queries:
        Tag.query.filter(name="red").first()
        1 / 0  # noqa: B018

    assert queries.sql_statements() == [TAG_BY_NAME]


def test_it_sees_queries_that_are_not_traced():
    with capture_spans() as spans, capture_queries() as queries, suppress_db_tracing():
        Tag.query.filter(name="red").first()

    assert list(spans) == []
    assert queries.sql_statements() == [TAG_BY_NAME]


def test_sql_statements_collapses_whitespace():
    # The first written query against a model looks its columns up in the
    # catalog. Do that before the block, so the block is the one statement.
    Tag.query.sql(t"SELECT {Tag:*} FROM {Tag}").all()

    with capture_queries() as queries:
        Tag.query.sql(
            t"""
            SELECT {Tag:*}
            FROM   {Tag}
            """
        ).all()

    [query] = queries
    assert "\n" in query.sql
    assert queries.sql_statements() == [
        'SELECT "examples_tag"."id", "examples_tag"."name" FROM "examples_tag"'
    ]


def test_sql_statements_table_keeps_only_the_statements_naming_that_table():
    with capture_queries() as queries:
        Tag.query.filter(name="red").first()
        Widget.query.filter(name="small").first()
        Tag.query.filter(name="blue").first()

    assert queries.sql_statements(table="examples_tag") == [TAG_BY_NAME, TAG_BY_NAME]
    assert queries.sql_statements(table="examples_widget") == [WIDGET_BY_NAME]


def test_sql_statements_table_matches_the_quoted_identifier_not_a_prefix():
    with capture_queries() as queries:
        WidgetTag.query.count()

    # "examples_widget" is a prefix of "examples_widgettag", but the statement
    # never names the widget table itself.
    assert queries.sql_statements(table="examples_widget") == []
    assert len(queries.sql_statements(table="examples_widgettag")) == 1


def test_a_savepoint_is_a_statement():
    # Every test runs inside a transaction, so this atomic block is a
    # savepoint.
    with capture_queries() as queries, transaction.atomic():
        Tag.query.filter(name="red").first()

    statements = queries.sql_statements()
    assert len(statements) == 3
    assert statements[0].startswith("SAVEPOINT ")
    assert statements[1] == TAG_BY_NAME
    assert statements[2].startswith("RELEASE SAVEPOINT ")


@isolated_db
def test_begin_and_commit_are_queries_but_not_statements():
    with capture_queries() as queries, transaction.atomic():
        Tag.query.filter(name="red").first()

    assert [query.sql for query in queries] == ["BEGIN", TAG_BY_NAME, "COMMIT"]
    assert [query.is_statement for query in queries] == [False, True, False]
    assert queries.sql_statements() == [TAG_BY_NAME]


def test_a_capture_inside_another_leaves_the_outer_one_whole():
    with capture_queries() as outer:
        Tag.query.filter(name="red").first()
        with capture_queries() as inner:
            Widget.query.filter(name="small").first()
        Tag.query.filter(name="red").first()

    assert inner.sql_statements() == [WIDGET_BY_NAME]
    assert outer.sql_statements() == [TAG_BY_NAME, WIDGET_BY_NAME, TAG_BY_NAME]


def test_max_queries_inside_a_capture_leaves_the_capture_whole():
    with capture_queries() as queries:
        Tag.query.filter(name="red").first()
        with max_queries(1):
            Widget.query.filter(name="small").first()

    assert queries.sql_statements() == [TAG_BY_NAME, WIDGET_BY_NAME]


def test_an_earlier_capture_keeps_what_it_captured():
    with capture_queries() as first:
        Tag.query.filter(name="red").first()
    with capture_queries() as second:
        Widget.query.filter(name="small").first()

    assert first.sql_statements() == [TAG_BY_NAME]
    assert second.sql_statements() == [WIDGET_BY_NAME]


def test_max_queries_passes_within_the_budget():
    with max_queries(1):
        Tag.query.filter(name="red").first()


def test_max_queries_fails_over_the_budget_and_lists_what_ran():
    with raises(AssertionError) as caught, max_queries(1):
        Tag.query.filter(name="red").first()
        Tag.query.filter(name="blue").first()

    message = str(caught.exception)
    assert "Expected at most 1 queries, 2 were executed" in message
    assert "'red'" in message
    assert "'blue'" in message
