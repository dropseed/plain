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


def test_a_none_in_the_list_matches_nothing(db):
    """SQL `= ANY` semantics, the same ones `IN` has: NULL never equals
    anything, so the None neither matches a row nor excludes one."""
    DefaultsExample.query.create(name="has-note", note="keep")
    DefaultsExample.query.create(name="no-note", note=None)

    matched = DefaultsExample.query.where(DefaultsExample.note.is_in(["keep", None]))
    assert [r.name for r in matched] == ["has-note"]


def test_a_single_string_is_refused(db):
    with pytest.raises(TypeError, match=r"\.is_in\(\) takes a collection of values"):
        DefaultsExample.name.is_in("alice")


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
