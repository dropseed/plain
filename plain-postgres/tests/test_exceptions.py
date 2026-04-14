"""Test that exception classes work correctly with the new type annotations."""

import pytest
from app.examples.models.delete import DeleteParent
from app.examples.models.iteration import IterationExample

from plain.postgres.exceptions import MultipleObjectsReturned, ObjectDoesNotExist


def test_exception_classes_work_correctly():
    """Test that the exception classes still function properly at runtime."""

    assert issubclass(IterationExample.DoesNotExist, Exception)
    assert issubclass(IterationExample.MultipleObjectsReturned, Exception)
    assert issubclass(IterationExample.DoesNotExist, ObjectDoesNotExist)
    assert issubclass(IterationExample.MultipleObjectsReturned, MultipleObjectsReturned)
    assert IterationExample.DoesNotExist is not DeleteParent.DoesNotExist
    assert (
        IterationExample.MultipleObjectsReturned
        is not DeleteParent.MultipleObjectsReturned
    )

    # Test that they can be raised and caught
    try:
        raise IterationExample.DoesNotExist("test")
    except IterationExample.DoesNotExist:
        pass  # This should work
    else:
        pytest.fail("Should have caught DoesNotExist")

    # Test MultipleObjectsReturned too
    try:
        raise IterationExample.MultipleObjectsReturned("test")
    except IterationExample.MultipleObjectsReturned:
        pass  # This should work
    else:
        pytest.fail("Should have caught MultipleObjectsReturned")


def test_exception_classes_have_proper_names():
    """Test that exception classes have the correct names and modules."""

    assert IterationExample.DoesNotExist.__name__ == "DoesNotExist"
    assert (
        IterationExample.MultipleObjectsReturned.__name__ == "MultipleObjectsReturned"
    )

    # Should include the model name in qualname
    assert "IterationExample.DoesNotExist" in IterationExample.DoesNotExist.__qualname__
    assert (
        "IterationExample.MultipleObjectsReturned"
        in IterationExample.MultipleObjectsReturned.__qualname__
    )


def test_base_exceptions_from_plain_exceptions():
    """Test that base exceptions can be imported from plain.exceptions."""

    # Model-specific exceptions should be catchable by base exceptions
    try:
        raise IterationExample.DoesNotExist("model-specific exception")
    except ObjectDoesNotExist:
        pass  # Should work due to inheritance
    except Exception:
        pytest.fail("Should have caught with base ObjectDoesNotExist")  # ty: ignore[invalid-argument-type]

    try:
        raise IterationExample.MultipleObjectsReturned("model-specific exception")
    except MultipleObjectsReturned:
        pass  # Should work due to inheritance
    except Exception:
        pytest.fail("Should have caught with base MultipleObjectsReturned")  # ty: ignore[invalid-argument-type]
