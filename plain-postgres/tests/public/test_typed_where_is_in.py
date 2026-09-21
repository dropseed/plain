"""`is_in()` binds its values as one array parameter.

`Field.is_in([...])` compiles to `"col" = ANY(%s::<type>[])`: the whole
collection is a single bound parameter, so the statement text is the same
whatever the list's length -- including empty, which used to produce no
statement at all. A queryset argument is untouched and still compiles to
`IN (SELECT ...)`.

The SQL shapes themselves are pinned in
`tests/internal/test_typed_where_any_of_sql.py`; this file is about what the
query comes back with.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from uuid import UUID

import pytest
from app.examples.models.defaults import DefaultsExample
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.forms import FormsExample
from app.examples.models.relationships import Tag, Widget, WidgetTag
from plain.postgres.expressions import F


def make_form_example(**overrides):
    values = {
        "name": "row",
        "count": 1,
        "ratio": 1.0,
        "amount": Decimal("1.50"),
        "is_active": True,
        "event_date": datetime.date(2026, 1, 1),
        "event_time": datetime.time(12, 0),
        "event_datetime": datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
        "duration": datetime.timedelta(hours=1),
        "external_id": UUID(int=1),
    }
    values.update(overrides)
    return FormsExample.query.create(**values)


# ---------------------------------------------------------------------------
# One value type at a time. The array cast has to name the column's own type
# for each of these, so each is its own chance for the parameter to arrive as
# the wrong array type.
# ---------------------------------------------------------------------------


def test_matches_on_an_integer_primary_key(db):
    wanted = make_form_example(name="wanted")
    make_form_example(name="other")

    rows = FormsExample.query.where(FormsExample.id.is_in([wanted.id]))
    assert [r.name for r in rows] == ["wanted"]


def test_matches_on_text(db):
    make_form_example(name="alice")
    make_form_example(name="bob")
    make_form_example(name="carol")

    rows = FormsExample.query.where(
        FormsExample.name.is_in(["alice", "carol"])
    ).order_by("name")
    assert [r.name for r in rows] == ["alice", "carol"]


def test_matches_on_a_choices_text_field(db):
    make_form_example(name="drafted", status="draft")
    make_form_example(name="live", status="published")

    rows = FormsExample.query.where(FormsExample.status.is_in(["published"]))
    assert [r.name for r in rows] == ["live"]


def test_matches_on_small_integers(db):
    """A small Python int is not an int8 to psycopg, so the column's own type
    is what the array has to be cast to."""
    make_form_example(name="one", count=1)
    make_form_example(name="nine", count=9)

    rows = FormsExample.query.where(FormsExample.count.is_in([1])).order_by("name")
    assert [r.name for r in rows] == ["one"]


def test_matches_on_decimal(db):
    make_form_example(name="cheap", amount=Decimal("1.50"))
    make_form_example(name="dear", amount=Decimal("99.00"))

    rows = FormsExample.query.where(FormsExample.amount.is_in([Decimal("99.00")]))
    assert [r.name for r in rows] == ["dear"]


def test_matches_on_boolean(db):
    make_form_example(name="on", is_active=True)
    make_form_example(name="off", is_active=False)

    rows = FormsExample.query.where(FormsExample.is_active.is_in([False]))
    assert [r.name for r in rows] == ["off"]


def test_matches_on_datetime(db):
    early = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)
    late = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC)
    make_form_example(name="early", event_datetime=early)
    make_form_example(name="late", event_datetime=late)

    rows = FormsExample.query.where(FormsExample.event_datetime.is_in([late]))
    assert [r.name for r in rows] == ["late"]


def test_matches_on_uuid(db):
    make_form_example(name="first", external_id=UUID(int=1))
    make_form_example(name="second", external_id=UUID(int=2))

    rows = FormsExample.query.where(FormsExample.external_id.is_in([UUID(int=2)]))
    assert [r.name for r in rows] == ["second"]


def test_matches_on_a_relation_key(db):
    """`parent.id` resolves to the local `parent_id` column, so the array is
    cast to the *target* column's type."""
    a = DeleteParent.query.create(name="a")
    b = DeleteParent.query.create(name="b")
    c = DeleteParent.query.create(name="c")
    for parent in (a, b, c):
        ChildCascade.query.create(parent=parent)

    rows = ChildCascade.query.where(ChildCascade.parent.id.is_in([a.id, c.id]))
    assert sorted(r.parent.id for r in rows) == sorted([a.id, c.id])


def test_matches_on_a_traversed_field(db):
    """The array type comes from the joined table's column, not the local
    one."""
    left = Widget.query.create(name="left", size="s")
    right = Widget.query.create(name="right", size="s")
    tag = Tag.query.create(name="tag")
    WidgetTag.query.create(widget=left, tag=tag)
    WidgetTag.query.create(widget=right, tag=tag)

    rows = WidgetTag.query.where(WidgetTag.widget.name.is_in(["right"]))
    assert [r.widget.name for r in rows] == ["right"]


# ---------------------------------------------------------------------------
# The collection itself
# ---------------------------------------------------------------------------


def test_an_empty_list_matches_nothing(db, capture_queries):
    """The behavior change: an empty list used to short-circuit to no
    statement at all. It now runs one, and comes back with the same nothing."""
    make_form_example(name="alice")

    empty = FormsExample.query.where(FormsExample.name.is_in([]))
    with capture_queries() as queries:
        rows = list(empty)
    assert rows == []
    assert len(queries) == 1

    assert empty.count() == 0
    assert empty.exists() is False


def test_an_empty_list_excludes_nothing_when_negated(db):
    make_form_example(name="alice")

    rows = FormsExample.query.where(~FormsExample.name.is_in([]))
    assert [r.name for r in rows] == ["alice"]


def test_negation_excludes_the_listed_values(db):
    make_form_example(name="alice")
    make_form_example(name="bob")
    make_form_example(name="carol")

    rows = FormsExample.query.where(
        ~FormsExample.name.is_in(["alice", "carol"])
    ).order_by("name")
    assert [r.name for r in rows] == ["bob"]


def test_a_generator_is_materialised_once(db):
    """A generator reaches `Q` and is copied and hashed on the way to the
    compiler, so it has to be turned into a list at the call site or the bind
    sees an exhausted iterator."""
    make_form_example(name="alice")
    make_form_example(name="bob")

    condition = FormsExample.name.is_in(n for n in ("alice", "bob"))
    assert condition.children == [("name__any_of", ["alice", "bob"])]

    rows = FormsExample.query.where(
        FormsExample.name.is_in(n for n in ("alice", "bob"))
    ).order_by("name")
    assert [r.name for r in rows] == ["alice", "bob"]


def test_a_set_works(db):
    make_form_example(name="alice")
    make_form_example(name="bob")

    rows = FormsExample.query.where(FormsExample.name.is_in({"alice"}))
    assert [r.name for r in rows] == ["alice"]


def test_a_none_in_the_list_is_refused(db):
    """NULL is not a value a comparison can match: it would match nothing, and
    negated it would exclude every row. `is_null()` is where it belongs."""
    with pytest.raises(ValueError, match=r"\.is_in\(\) does not accept None"):
        DefaultsExample.note.is_in(["keep", None])


def test_null_and_values_are_matched_by_combining_the_two_conditions(db):
    """The spelling the refusal points at."""
    DefaultsExample.query.create(name="has-note", note="keep")
    DefaultsExample.query.create(name="other-note", note="drop")
    DefaultsExample.query.create(name="no-note", note=None)

    rows = DefaultsExample.query.where(
        DefaultsExample.note.is_in(["keep"]) | DefaultsExample.note.is_null()
    ).order_by("name")
    assert [r.name for r in rows] == ["has-note", "no-note"]


def test_a_single_string_is_refused(db):
    with pytest.raises(TypeError, match=r"\.is_in\(\) takes a collection of values"):
        DefaultsExample.name.is_in("alice")


# ---------------------------------------------------------------------------
# A candidate the column can't hold
#
# The array is cast to the type the column *compares* as, not the one it's
# stored in. Casting to the storage type would let a constrained column
# rewrite the candidates -- rounding a decimal, or refusing an integer -- and
# change which rows come back. Every case here is checked against
# `filter(__in=...)`, which is the behavior being preserved.
# ---------------------------------------------------------------------------


def test_a_decimal_with_more_fractional_digits_than_the_column_matches_nothing(db):
    """`amount` is `numeric(10,2)`. Casting the array to `numeric(10,2)[]`
    would round 1.504 to 1.50 and match the row -- `IN (1.504)` does not."""
    make_form_example(name="cheap", amount=Decimal("1.50"))

    candidate = Decimal("1.504")
    assert [
        r.name for r in FormsExample.query.where(FormsExample.amount.is_in([candidate]))
    ] == []
    assert [r.name for r in FormsExample.query.filter(amount__in=[candidate])] == []


def test_a_decimal_beyond_the_columns_precision_matches_nothing(db):
    """No row can hold it, so it matches nothing -- it does not raise."""
    make_form_example(name="cheap", amount=Decimal("1.50"))

    candidate = Decimal("12345678901.50")  # max_digits=10
    assert [
        r.name for r in FormsExample.query.where(FormsExample.amount.is_in([candidate]))
    ] == []
    assert [r.name for r in FormsExample.query.filter(amount__in=[candidate])] == []


def test_a_decimal_that_does_fit_still_matches(db):
    make_form_example(name="cheap", amount=Decimal("1.50"))
    make_form_example(name="dear", amount=Decimal("99.00"))

    rows = FormsExample.query.where(FormsExample.amount.is_in([Decimal("1.50")]))
    assert [r.name for r in rows] == ["cheap"]


def test_an_integer_out_of_the_columns_range_matches_nothing(db):
    """`count` is an `integer`. A candidate no `integer` can hold matches no
    rows -- casting the array to `integer[]` would raise instead."""
    make_form_example(name="one", count=1)

    too_big = 2**40
    assert [
        r.name for r in FormsExample.query.where(FormsExample.count.is_in([too_big]))
    ] == []
    assert [r.name for r in FormsExample.query.filter(count__in=[too_big])] == []


def test_an_out_of_range_integer_mixed_with_valid_ones_matches_the_valid_ones(db):
    make_form_example(name="one", count=1)
    make_form_example(name="nine", count=9)

    candidates = [1, 2**40, 2**70]
    rows = FormsExample.query.where(FormsExample.count.is_in(candidates))
    assert [r.name for r in rows] == ["one"]
    assert [r.name for r in FormsExample.query.filter(count__in=candidates)] == ["one"]


def test_negating_an_out_of_range_integer_excludes_only_the_valid_ones(db):
    make_form_example(name="one", count=1)
    make_form_example(name="nine", count=9)

    candidates = [1, 2**40]
    rows = FormsExample.query.where(~FormsExample.count.is_in(candidates))
    assert [r.name for r in rows] == ["nine"]
    assert [r.name for r in FormsExample.query.exclude(count__in=candidates)] == [
        "nine"
    ]


def test_negating_an_all_out_of_range_integer_list_excludes_nothing(db):
    make_form_example(name="one", count=1)

    rows = FormsExample.query.where(~FormsExample.count.is_in([2**70]))
    assert [r.name for r in rows] == ["one"]
    assert [r.name for r in FormsExample.query.exclude(count__in=[2**70])] == ["one"]


def test_a_primary_key_out_of_bigint_range_matches_nothing(db):
    make_form_example(name="one")

    assert [
        r.name for r in FormsExample.query.where(FormsExample.id.is_in([2**70]))
    ] == []
    assert [r.name for r in FormsExample.query.filter(id__in=[2**70])] == []


# ---------------------------------------------------------------------------
# What did not change
# ---------------------------------------------------------------------------


def test_a_queryset_argument_stays_a_subquery(db, capture_queries, executed_sql):
    left = Widget.query.create(name="left", size="s")
    Widget.query.create(name="right", size="s")
    tag = Tag.query.create(name="tag")
    WidgetTag.query.create(widget=left, tag=tag)

    widget_ids = Widget.query.filter(name="left").values_list("id", flat=True)
    with capture_queries() as queries:
        rows = list(WidgetTag.query.where(WidgetTag.widget.id.is_in(widget_ids)))

    assert [r.widget.name for r in rows] == ["left"]
    # One statement, with the inner select inlined -- not two round trips.
    assert len(queries) == 1
    assert "IN (SELECT" in executed_sql(queries)


def test_the_in_kwarg_keeps_its_own_spelling(db, capture_queries, executed_sql):
    """`filter(field__in=[...])` is a separate lookup and is unchanged."""
    make_form_example(name="alice")

    with capture_queries() as queries:
        assert [r.name for r in FormsExample.query.filter(name__in=["alice"])] == [
            "alice"
        ]

    # `executed_sql` interpolates the parameters, so this is `IN ('alice')`.
    assert "IN (" in executed_sql(queries)
    assert "= ANY(" not in executed_sql(queries)


def test_the_in_kwarg_still_short_circuits_on_an_empty_list(db, capture_queries):
    """The kwarg path keeps `EmptyResultSet`: no statement runs at all."""
    make_form_example(name="alice")

    with capture_queries() as queries:
        assert list(FormsExample.query.filter(name__in=[])) == []

    assert queries == []


# ---------------------------------------------------------------------------
# The kwarg spelling
#
# `any_of` is a lookup name, so `filter(x__any_of=...)` reaches it without
# passing through `is_in()`. The guards live on the lookup so both spellings
# refuse the same things; `is_in()` keeps its own wording, which can name the
# field, by raising first.
# ---------------------------------------------------------------------------


def test_the_kwarg_spelling_refuses_a_none_element(db):
    DefaultsExample.query.create(name="alice", note="keep")

    with pytest.raises(ValueError, match=r"any_of does not accept None"):
        DefaultsExample.query.filter(note__any_of=["keep", None])


def test_the_kwarg_spelling_refuses_a_none_element_when_negated(db):
    """The case a silent drop would get wrong in the other direction."""
    DefaultsExample.query.create(name="alice", note="keep")

    with pytest.raises(ValueError, match=r"any_of does not accept None"):
        DefaultsExample.query.exclude(note__any_of=["keep", None])


def test_the_kwarg_spelling_refuses_a_queryset(db):
    """A subquery can't be an element of a bound array -- `__in` is for that."""
    ids = DefaultsExample.query.values_list("id", flat=True)

    with pytest.raises(TypeError, match=r"any_of takes a collection of values"):
        DefaultsExample.query.filter(id__any_of=ids)


def test_the_kwarg_spelling_refuses_an_expression(db):
    with pytest.raises(TypeError, match=r"any_of takes a collection of values"):
        DefaultsExample.query.filter(name__any_of=F("status"))


def test_the_kwarg_spelling_refuses_an_expression_element(db):
    with pytest.raises(TypeError, match=r"one element is an expression"):
        DefaultsExample.query.filter(name__any_of=[F("status"), "x"])


def test_the_typed_call_raises_its_own_message_first(db):
    """`is_in()` can name the field; the lookup's message can't."""
    with pytest.raises(ValueError, match=r"TextField 'note': \.is_in\(\)"):
        DefaultsExample.note.is_in(["keep", None])


def test_the_kwarg_spelling_matches_values_like_the_typed_one(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="bob")

    rows = DefaultsExample.query.filter(name__any_of=["alice"])
    assert [r.name for r in rows] == ["alice"]
