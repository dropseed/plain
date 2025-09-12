import pytest
from app.examples.models import Car

from plain.exceptions import ValidationError


def test_create_unique_constraint(db):
    Car.query.create(make="Toyota", model="Tundra")

    with pytest.raises(ValidationError) as e:
        Car.query.create(make="Toyota", model="Tundra")

    assert (
        str(e)
        == "<ExceptionInfo ValidationError({'__all__': ['A car with this make and model already exists.']}) tblen=4>"
    )

    assert Car.query.count() == 1


def test_update_or_create_unique_constraint(db):
    Car.query.update_or_create(make="Toyota", model="Tundra")
    Car.query.update_or_create(make="Toyota", model="Tundra")

    assert Car.query.count() == 1
