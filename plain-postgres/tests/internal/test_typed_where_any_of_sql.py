"""Statement pins for the `any_of` lookup `Field.is_in()` builds.

Change detector: the point of `= ANY(%s::<type>[])` is that the statement
text doesn't move with the values, and that the cast names the column's own
type. If either drifts these fail and you decide whether it should have.

The contract -- which rows come back -- lives in
`tests/public/test_typed_where_is_in.py`.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from uuid import UUID

import pytest
from app.examples.models.delete import ChildCascade
from app.examples.models.forms import FormsExample
from app.examples.models.relationships import Widget, WidgetTag


def where_clause(queryset) -> tuple[str, tuple]:
    """The compiled WHERE clause and its parameters, without the SELECT."""
    sql, params = queryset.sql_query.get_compiler().as_sql()
    return sql.split("WHERE ", 1)[1], params


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        pytest.param(
            FormsExample.id.is_in([1, 2, 3]),
            '"examples_formsexample"."id" = ANY(%s::bigint[])',
            id="integer-primary-key",
        ),
        pytest.param(
            FormsExample.name.is_in(["a", "b"]),
            '"examples_formsexample"."name" = ANY(%s::text[])',
            id="text",
        ),
        pytest.param(
            FormsExample.status.is_in(["draft"]),
            '"examples_formsexample"."status" = ANY(%s::text[])',
            id="choices-text",
        ),
        pytest.param(
            FormsExample.count.is_in([1, 2]),
            '"examples_formsexample"."count" = ANY(%s::integer[])',
            id="integer",
        ),
        pytest.param(
            FormsExample.amount.is_in([Decimal("1.50")]),
            '"examples_formsexample"."amount" = ANY(%s::numeric(10,2)[])',
            id="decimal",
        ),
        pytest.param(
            FormsExample.is_active.is_in([True]),
            '"examples_formsexample"."is_active" = ANY(%s::boolean[])',
            id="boolean",
        ),
        pytest.param(
            FormsExample.event_datetime.is_in(
                [datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)]
            ),
            '"examples_formsexample"."event_datetime" '
            "= ANY(%s::timestamp with time zone[])",
            id="datetime",
        ),
        pytest.param(
            FormsExample.external_id.is_in([UUID(int=1)]),
            '"examples_formsexample"."external_id" = ANY(%s::uuid[])',
            id="uuid",
        ),
    ],
)
def test_the_cast_names_the_columns_own_type(db, condition, expected):
    clause, params = where_clause(FormsExample.query.where(condition))
    assert clause == expected
    # One parameter, and it is the whole list.
    assert len(params) == 1
    assert isinstance(params[0], list)


def test_a_relation_key_casts_to_the_target_columns_type(db):
    """`parent.id` compiles against the local `parent_id` column, so the array
    type has to come from the column the relation targets."""
    clause, _ = where_clause(
        ChildCascade.query.where(ChildCascade.parent.id.is_in([1, 2]))
    )
    assert clause == '"examples_childcascade"."parent_id" = ANY(%s::bigint[])'


def test_a_traversed_field_casts_to_the_joined_columns_type(db):
    clause, _ = where_clause(WidgetTag.query.where(WidgetTag.widget.name.is_in(["a"])))
    assert clause.endswith('"examples_widget"."name" = ANY(%s::text[])')


def test_the_statement_is_the_same_shape_for_every_length(db):
    """The whole point: no placeholder per value, so plan caching has one
    statement to cache."""
    shapes = {
        where_clause(FormsExample.query.where(FormsExample.name.is_in(names)))[0]
        for names in ([], ["a"], ["a", "b"], ["a", "b", "c"])
    }
    assert shapes == {'"examples_formsexample"."name" = ANY(%s::text[])'}


def test_negation_wraps_the_whole_comparison(db):
    clause, _ = where_clause(
        FormsExample.query.where(~FormsExample.name.is_in(["a", "b"]))
    )
    assert clause == 'NOT ("examples_formsexample"."name" = ANY(%s::text[]))'


def test_a_queryset_argument_still_compiles_to_a_subquery(db):
    widget_ids = Widget.query.values_list("id", flat=True)
    clause, _ = where_clause(
        WidgetTag.query.where(WidgetTag.widget.id.is_in(widget_ids))
    )
    assert clause == (
        '"examples_widgettag"."widget_id" IN (SELECT U0."id" FROM "examples_widget" U0)'
    )


def test_the_in_kwarg_keeps_a_placeholder_per_value(db):
    """`filter(field__in=[...])` builds the `in` lookup, which is unchanged."""
    clause, params = where_clause(FormsExample.query.filter(name__in=["a", "b"]))
    assert clause == '"examples_formsexample"."name" IN (%s, %s)'
    assert params == ("a", "b")
