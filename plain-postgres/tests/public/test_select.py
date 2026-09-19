"""Runtime behavior of `QuerySet.select()` — typed column selection that
returns honest rows (tuples, scalars, or dataclasses), never partial model
instances.

The static-typing contract lives in tests/typing/select_rows.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from app.examples.models.defaults import DefaultsExample
from app.examples.models.relationships import WidgetTag
from plain.postgres import RowQuerySet
from plain.postgres.expressions import F
from plain.postgres.functions import Upper


@pytest.fixture
def rows(db):
    DefaultsExample.query.create(name="alpha", priority=3, note="first")
    DefaultsExample.query.create(name="beta", priority=1, note=None)
    DefaultsExample.query.create(name="gamma", priority=2, note="third")


def test_select_returns_tuple_rows(rows):
    result = (
        DefaultsExample.query.order_by("priority")
        .select(DefaultsExample.name, DefaultsExample.priority)
        .all()
    )
    assert list(result) == [("beta", 1), ("gamma", 2), ("alpha", 3)]


def test_select_flat_returns_scalars(rows):
    names = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, flat=True)
        .all()
    )
    assert list(names) == ["alpha", "beta", "gamma"]


def test_select_single_column_is_one_tuple(rows):
    result = DefaultsExample.query.order_by("name").select(DefaultsExample.name)
    assert list(result) == [("alpha",), ("beta",), ("gamma",)]


def test_select_preserves_nullable_values(rows):
    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, DefaultsExample.note)
        .all()
    )
    assert list(result) == [("alpha", "first"), ("beta", None), ("gamma", "third")]


def test_select_chains_with_where(rows):
    result = DefaultsExample.query.where(DefaultsExample.priority.gte(2)).select(
        DefaultsExample.name, flat=True
    )
    assert sorted(result) == ["alpha", "gamma"]


def test_select_expression_column(rows):
    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.priority, Upper("name"))
        .all()
    )
    assert list(result) == [(3, "ALPHA"), (1, "BETA"), (2, "GAMMA")]


def test_select_f_expression_column(rows):
    """F() is a Combinable, not a BaseExpression -- select() takes it anyway,
    because values_list() does. Static half: tests/typing/select_rows.py."""
    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, F("priority"))
        .all()
    )
    assert list(result) == [("alpha", 3), ("beta", 1), ("gamma", 2)]


def test_select_combined_f_expression_column(rows):
    result = DefaultsExample.query.order_by("name").select(F("priority") + 1, flat=True)
    assert list(result) == [4, 2, 3]


def test_select_returns_row_queryset(rows):
    result = DefaultsExample.query.select(DefaultsExample.name)
    assert isinstance(result, RowQuerySet)


def test_select_first_returns_row(rows):
    row = (
        DefaultsExample.query.order_by("priority")
        .select(DefaultsExample.name, DefaultsExample.priority)
        .first()
    )
    assert row == ("beta", 1)


def test_select_get_returns_row(rows):
    row = (
        DefaultsExample.query.where(DefaultsExample.name.equals("alpha"))
        .select(DefaultsExample.name, DefaultsExample.priority)
        .get()
    )
    assert row == ("alpha", 3)


# ---- result_type=Dataclass ----


@dataclass
class NameStat:
    name: str
    priority: int


def test_select_result_type_builds_dataclass(rows):
    result = (
        DefaultsExample.query.order_by("priority")
        .select(DefaultsExample.name, DefaultsExample.priority, result_type=NameStat)
        .all()
    )
    assert list(result) == [
        NameStat(name="beta", priority=1),
        NameStat(name="gamma", priority=2),
        NameStat(name="alpha", priority=3),
    ]


def test_select_result_type_with_expression_column(rows):
    @dataclass
    class NameUpper:
        priority: int
        upper: str

    result = (
        DefaultsExample.query.order_by("name")
        .select(
            DefaultsExample.priority,
            Upper("name"),
            result_type=NameUpper,
        )
        .all()
    )
    assert result[0] == NameUpper(priority=3, upper="ALPHA")


# ---- error paths ----


def test_select_requires_at_least_one_column(db):
    with pytest.raises(TypeError, match="at least one column"):
        DefaultsExample.query.select()


def test_select_rejects_string_argument(db):
    with pytest.raises(TypeError, match="strings"):
        DefaultsExample.query.select("name")  # ty: ignore[no-matching-overload]


def test_select_rejects_fk_traversal(db):
    """The message names the values_list() spelling that does work."""
    with pytest.raises(TypeError, match=r'values_list\("widget__name"\)'):
        WidgetTag.query.select(WidgetTag.widget.name)


def test_select_rejects_fk_reference(db):
    """A relation is not a column, and its key column is out for now too."""
    with pytest.raises(TypeError, match="key column is not selectable yet"):
        WidgetTag.query.select(WidgetTag.widget)  # ty: ignore[no-matching-overload]


def test_select_flat_rejects_more_than_one_column(db):
    """The message names select(), not the values_list() plumbing underneath."""
    with pytest.raises(TypeError, match=r"select\(flat=True\) takes exactly one"):
        DefaultsExample.query.select(  # ty: ignore[no-matching-overload]
            DefaultsExample.name, DefaultsExample.priority, flat=True
        )


def test_select_rejects_the_foreign_key_column_for_now(db):
    """`WidgetTag.widget.id` is the FK column, but it still arrives over the
    relation, so it is refused with the rest of traversal until select() can
    say it is nullable."""
    with pytest.raises(TypeError, match=r'values_list\("widget__id"\)'):
        WidgetTag.query.select(WidgetTag.widget.id)


def test_select_result_type_must_be_dataclass(db):
    with pytest.raises(TypeError, match="dataclass"):
        DefaultsExample.query.select(DefaultsExample.name, result_type=dict)


def test_select_result_type_arity_must_match(db):
    with pytest.raises(TypeError, match="columns were selected"):
        DefaultsExample.query.select(DefaultsExample.name, result_type=NameStat)


def test_select_result_type_field_name_must_match(db):
    @dataclass
    class Renamed:
        label: str
        priority: int

    with pytest.raises(TypeError, match="positionally"):
        DefaultsExample.query.select(
            DefaultsExample.name, DefaultsExample.priority, result_type=Renamed
        )


def test_select_flat_and_result_type_conflict(db):
    with pytest.raises(TypeError, match="combine flat"):
        DefaultsExample.query.select(  # ty: ignore[no-matching-overload]
            DefaultsExample.name, flat=True, result_type=NameStat
        )


def test_select_result_type_ignores_init_false_fields(rows):
    """An init=False field is computed by the dataclass, so it is neither
    selected nor counted against the arity."""

    @dataclass
    class Computed:
        name: str
        priority: int
        label: str = field(default="", init=False)

        def __post_init__(self) -> None:
            self.label = f"{self.name}:{self.priority}"

    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, DefaultsExample.priority, result_type=Computed)
        .first()
    )
    assert result == Computed(name="alpha", priority=3)
    assert result.label == "alpha:3"


def test_get_or_create_after_select_raises(db):
    with pytest.raises(TypeError, match="get_or_create"):
        DefaultsExample.query.select(DefaultsExample.name).get_or_create(name="x")


def test_update_or_create_after_select_raises(db):
    with pytest.raises(TypeError, match="update_or_create"):
        DefaultsExample.query.select(DefaultsExample.name).update_or_create(name="x")


def test_select_after_values_raises(db):
    with pytest.raises(TypeError, match="after values"):
        DefaultsExample.query.values("name").select(DefaultsExample.name)


def test_values_after_select_raises(db):
    with pytest.raises(TypeError, match="after select"):
        DefaultsExample.query.select(DefaultsExample.name).values("name")


def test_update_after_select_raises(db):
    with pytest.raises(TypeError, match="update"):
        DefaultsExample.query.select(DefaultsExample.name).update(name="x")


def test_delete_after_select_raises(db):
    with pytest.raises(TypeError, match="delete"):
        DefaultsExample.query.select(DefaultsExample.name).delete()


def test_update_refuses_any_row_mode_queryset(db):
    """select() shares delete()'s guard rather than adding its own, so
    update() now refuses values()/values_list() for the same reason."""
    with pytest.raises(TypeError, match="Cannot call update"):
        DefaultsExample.query.values("name").update(name="x")
    with pytest.raises(TypeError, match="Cannot call update"):
        DefaultsExample.query.values_list("name").update(name="x")


def test_select_twice_last_wins(rows):
    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name)
        .select(DefaultsExample.priority, flat=True)
    )
    assert list(result) == [3, 1, 2]
