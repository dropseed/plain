"""`returning()` pins what update()/delete() hand back.

Without it both writes are an int rowcount. The no-arg overload hydrates model
instances; the field-reference overload hands back dicts of just those columns.
The overload ladder is the whole promise, so it is asserted statically.
"""

from typing import Any, assert_type

from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.querysets import CustomQuerySet, CustomQuerySetModel
from app.examples.models.relationships import Widget
from app.examples.models.returning import ReturningEvent


def must_accept_the_plain_writes() -> None:
    qs = ReturningEvent.query.filter(label="a")
    assert_type(qs.update(count=1), int)
    assert_type(qs.delete(), int)


def must_accept_no_arg_returning_as_instances() -> None:
    qs = ReturningEvent.query.filter(label="a")
    assert_type(qs.returning().update(count=1), list[ReturningEvent])
    assert_type(qs.returning().delete(), list[ReturningEvent])


def must_accept_field_returning_as_dicts() -> None:
    qs = ReturningEvent.query.filter(label="a")
    assert_type(qs.returning(ReturningEvent.id).update(count=1), list[dict[str, Any]])
    assert_type(qs.returning(ReturningEvent.id).delete(), list[dict[str, Any]])


def must_reject_string_field_names() -> None:
    # Runtime half: tests/public/test_returning.py::test_returning_string_arg_errors.
    ReturningEvent.query.returning("count")  # ty: ignore[invalid-argument-type]


def must_reject_a_relation_reference() -> None:
    # At class level a relation attribute is its descriptor, not a column --
    # forward FK, many-to-many and reverse FK alike.
    # Runtime half:
    # tests/public/test_returning.py::test_returning_relation_reference_errors.
    ChildCascade.query.returning(ChildCascade.parent)  # ty: ignore[invalid-argument-type]
    Widget.query.returning(Widget.tags)  # ty: ignore[invalid-argument-type]
    DeleteParent.query.returning(DeleteParent.childcascade_set)  # ty: ignore[invalid-argument-type]


def must_keep_the_return_shape_through_a_lock() -> None:
    # A lock on the read side of a write is the job-claim pattern, so the
    # lock methods have to hand back the same queryset kind they were called
    # on -- returning()'s pinned shape included, in either order.
    # Runtime half: tests/public/test_returning.py, the locking section.
    qs = ReturningEvent.query.filter(label="a")
    assert_type(qs.for_update().returning().update(count=1), list[ReturningEvent])
    assert_type(qs.returning().for_update().update(count=1), list[ReturningEvent])
    assert_type(
        qs.returning(ReturningEvent.id).for_update().delete(), list[dict[str, Any]]
    )


def must_keep_a_custom_queryset_reachable() -> None:
    """A custom QuerySet survives returning() at runtime; statically it is
    the declared ReturningQuerySet, so a custom method reads cleanly when
    it comes first -- and needs narrowing when it comes after.

    Runtime half: tests/public/test_returning.py, the custom-queryset tests.
    """
    # Custom method first, returning() on top: resolves with no narrowing.
    # (The model type is Unknown here only because CustomQuerySet is declared
    # unparameterized -- that is the example model's shape, not returning's.)
    CustomQuerySetModel.query.get_custom().returning().update(name="x")

    # Custom method after: the declared type is ReturningQuerySet, which
    # carries no custom methods. isinstance() is what recovers them.
    qs = CustomQuerySetModel.query.returning()
    assert isinstance(qs, CustomQuerySet)
    qs.get_custom()


def must_keep_the_return_shape_through_a_combination() -> None:
    """A combined queryset emits one RETURNING clause, so the shape carries
    from whichever side returning() was called on.

    Runtime half: tests/public/test_returning.py, the combining section.
    """
    left = ReturningEvent.query.filter(label="a")
    right = ReturningEvent.query.filter(label="b")

    assert_type((left.returning() | right).update(count=1), list[ReturningEvent])
    assert_type((left | right.returning()).update(count=1), list[ReturningEvent])
    assert_type(
        (left & right.returning(ReturningEvent.id)).delete(), list[dict[str, Any]]
    )
    assert_type(left.returning().none().update(count=1), list[ReturningEvent])

    # No returning() on either side stays an int.
    assert_type((left | right).update(count=1), int)


def must_keep_the_return_shape_through_column_selection() -> None:
    """defer(), only() and reverse() narrow or reorder a read; none of them
    changes what a following write hands back.

    They all return the queryset they were called on, so they have to say
    `Self` -- annotated `QuerySet[T]` they collapsed the returning() shape
    and the write read back as an int.

    Runtime half: tests/public/test_returning.py.
    """
    qs = ReturningEvent.query.filter(label="a").returning()

    assert_type(qs.defer("payload").update(count=1), list[ReturningEvent])
    assert_type(qs.only("label").update(count=1), list[ReturningEvent])
    assert_type(qs.reverse().delete(), list[ReturningEvent])
