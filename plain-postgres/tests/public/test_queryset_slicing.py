from __future__ import annotations

from app.examples.models.iteration import IterationExample

from plain.postgres import F, QuerySet
from plain.postgres.test import capture_queries
from plain.test import raises


def create_rows():
    for i in range(25):
        IterationExample.query.create(name=f"name{i:02d}", tag="t")


def test_slice_of_unevaluated_queryset_returns_queryset():
    create_rows()
    sliced = IterationExample.query.order_by("name")[:5]

    assert isinstance(sliced, QuerySet)
    assert [r.name for r in sliced] == [f"name{i:02d}" for i in range(5)]


def test_slice_of_evaluated_queryset_returns_queryset():
    """Slicing a cached queryset returns a QuerySet, not a list.

    Previously an evaluated queryset sliced to a plain list, so the return
    type depended on whether the queryset had been iterated first.
    """
    create_rows()
    qs = IterationExample.query.order_by("name")
    list(qs)  # evaluate -> populates _result_cache

    sliced = qs[:5]

    assert isinstance(sliced, QuerySet)
    assert [r.name for r in sliced] == [f"name{i:02d}" for i in range(5)]


def test_slice_of_evaluated_queryset_does_not_requery():
    """Iterating a cached slice reuses the cache instead of hitting the DB."""
    create_rows()
    qs = IterationExample.query.order_by("name")
    list(qs)  # evaluate

    with capture_queries() as queries:
        list(qs[:5])

    assert queries == []


def test_cached_slice_matches_sql_slice():
    """A cached slice yields the same rows as slicing via SQL limits."""
    create_rows()
    sql_slice = [r.name for r in IterationExample.query.order_by("name")[3:9]]

    evaluated = IterationExample.query.order_by("name")
    list(evaluated)  # evaluate
    cache_slice = [r.name for r in evaluated[3:9]]

    assert cache_slice == sql_slice == [f"name{i:02d}" for i in range(3, 9)]


def test_reslicing_cached_slice_composes():
    """Re-slicing a cached slice composes offsets correctly."""
    create_rows()
    qs = IterationExample.query.order_by("name")
    list(qs)

    inner = qs[5:15][2:4]

    assert isinstance(inner, QuerySet)
    assert [r.name for r in inner] == [f"name{i:02d}" for i in range(7, 9)]


def test_filtering_a_cached_slice_raises_like_any_slice():
    """A cached slice obeys the same "no filtering after slicing" rule."""
    create_rows()
    qs = IterationExample.query.order_by("name")
    list(qs)
    sliced = qs[:5]

    with raises(TypeError, match="once a slice has been taken"):
        sliced.filter(tag="t")


def test_step_slicing_raises_when_unevaluated():
    create_rows()
    with raises(ValueError, match="Step slicing is not supported"):
        IterationExample.query.all()[::2]


def test_step_slicing_raises_when_evaluated():
    create_rows()
    qs = IterationExample.query.all()
    list(qs)

    with raises(ValueError, match="Step slicing is not supported"):
        qs[::2]


def test_negative_slicing_raises():
    create_rows()
    with raises(ValueError, match="Negative indexing is not supported"):
        IterationExample.query.all()[-1:]


def test_slice_then_annotate_works_regardless_of_evaluation():
    """A function slicing then annotating behaves the same either way.

    This is the motivating case: previously, passing an already-evaluated
    queryset made `qs[:n]` a list and the `.annotate()` raised
    AttributeError. Now it works whether or not the caller evaluated first.
    """
    create_rows()

    def slice_then_annotate(qs):
        return qs[:5].annotate(name2=F("name"))

    unevaluated = IterationExample.query.order_by("name")
    from_unevaluated = [r.name2 for r in slice_then_annotate(unevaluated)]

    evaluated = IterationExample.query.order_by("name")
    list(evaluated)  # evaluate first
    from_evaluated = [r.name2 for r in slice_then_annotate(evaluated)]

    assert from_unevaluated == from_evaluated == [f"name{i:02d}" for i in range(5)]


def test_values_list_cached_slice_reuses_cache():
    """A cached values_list() slice stays a QuerySet and reuses the cache.

    values()/values_list() use a different iterable class than the default
    model iterable, so exercise that the cache-carry path works for it too.
    """
    create_rows()
    qs = IterationExample.query.order_by("name").values_list("name", flat=True)
    list(qs)  # evaluate -> cache holds the values

    sliced = qs[:3]
    with capture_queries() as queries:
        list(sliced)

    assert isinstance(sliced, QuerySet)
    assert queries == []
    assert list(sliced) == [f"name{i:02d}" for i in range(3)]


def test_integer_index_on_cached_queryset_returns_item():
    create_rows()
    qs = IterationExample.query.order_by("name")
    list(qs)

    item = qs[0]

    assert isinstance(item, IterationExample)
    assert item.name == "name00"
