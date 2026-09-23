"""`select(Model.fk.id)` is the typed spelling of `values_list("fk")`.

The claim that made it safe to accept a foreign key's own key column is that
it reads a local column with no join, exactly as the string form always has.
That is a statement about the SQL, so it is pinned as SQL: if a future change
starts adding a join, or selects the related table's `id` instead of this
table's key column, these fail.

The user-facing half lives in tests/public/test_select.py.
"""

import pytest
from app.examples.models.relationships import Widget, WidgetTag
from plain.postgres.exceptions import FieldError


def compiled(queryset):
    return queryset.sql_query.get_compiler().as_sql()


def test_fk_column_compiles_like_the_relation_name(db):
    assert compiled(WidgetTag.query.select(WidgetTag.widget.id, flat=True)) == compiled(
        WidgetTag.query.values_list("widget", flat=True)
    )


def test_fk_column_selects_the_local_column_with_no_join(db):
    sql, params = compiled(WidgetTag.query.select(WidgetTag.widget.id, flat=True))
    assert sql == ('SELECT "examples_widgettag"."widget_id" FROM "examples_widgettag"')
    assert params == ()


def test_the_column_name_is_not_a_lookup_of_its_own(db):
    """`widget_id` is the database column, not a field name — there is no
    `attname` dual-keying in Plain, so `values_list("widget")` is the only
    string spelling of this column and the only one to compare against."""
    with pytest.raises(FieldError, match="widget_id"):
        WidgetTag.query.values_list("widget_id", flat=True).first()


def test_fk_column_as_a_subquery_compiles_like_the_relation_name(db):
    """The oauthserver chore's shape: a key column feeding `is_in()`."""
    selected = WidgetTag.query.select(WidgetTag.widget.id, flat=True)
    listed = WidgetTag.query.values_list("widget", flat=True)

    assert compiled(Widget.query.where(Widget.id.is_in(selected))) == compiled(
        Widget.query.where(Widget.id.is_in(listed))
    )
