"""Test that exception classes work correctly with the new type annotations."""

import pytest
from app.examples.models import Car, DeleteParent  # type: ignore[import-untyped]

from plain.models.exceptions import MultipleObjectsReturned, ObjectDoesNotExist


def test_exception_classes_work_correctly():
    """Test that the exception classes still function properly at runtime."""

    assert issubclass(Car.DoesNotExist, Exception)
    assert issubclass(Car.MultipleObjectsReturned, Exception)
    assert issubclass(Car.DoesNotExist, ObjectDoesNotExist)
    assert issubclass(Car.MultipleObjectsReturned, MultipleObjectsReturned)
    assert Car.DoesNotExist is not DeleteParent.DoesNotExist
    assert Car.MultipleObjectsReturned is not DeleteParent.MultipleObjectsReturned

    # Test that they can be raised and caught
    try:
        raise Car.DoesNotExist("test")
    except Car.DoesNotExist:
        pass  # This should work
    else:
        pytest.fail("Should have caught DoesNotExist")

    # Test MultipleObjectsReturned too
    try:
        raise Car.MultipleObjectsReturned("test")
    except Car.MultipleObjectsReturned:
        pass  # This should work
    else:
        pytest.fail("Should have caught MultipleObjectsReturned")


def test_exception_classes_have_proper_names():
    """Test that exception classes have the correct names and modules."""

    assert Car.DoesNotExist.__name__ == "DoesNotExist"
    assert Car.MultipleObjectsReturned.__name__ == "MultipleObjectsReturned"

    # Should include the model name in qualname
    assert "Car.DoesNotExist" in Car.DoesNotExist.__qualname__
    assert "Car.MultipleObjectsReturned" in Car.MultipleObjectsReturned.__qualname__


def test_base_exceptions_from_plain_exceptions():
    """Test that base exceptions can be imported from plain.exceptions."""

    # Model-specific exceptions should be catchable by base exceptions
    try:
        raise Car.DoesNotExist("model-specific exception")
    except ObjectDoesNotExist:
        pass  # Should work due to inheritance
    except Exception:
        pytest.fail("Should have caught with base ObjectDoesNotExist")

    try:
        raise Car.MultipleObjectsReturned("model-specific exception")
    except MultipleObjectsReturned:
        pass  # Should work due to inheritance
    except Exception:
        pytest.fail("Should have caught with base MultipleObjectsReturned")
