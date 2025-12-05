import pytest
from app.examples.models import (
    Car,
    CarFeature,
    DeleteParent,
    Feature,
    MixinTestModel,
)

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


def test_mixin_fields_inherited(db):
    """Test that fields from mixins are properly inherited and processed."""
    # Verify mixin fields are present
    field_names = [f.name for f in MixinTestModel._model_meta.fields]
    assert "created_at" in field_names, "created_at from mixin should be present"
    assert "updated_at" in field_names, "updated_at from mixin should be present"
    assert "name" in field_names, "name from model should be present"

    # Verify ordering from Options works
    assert MixinTestModel.model_options.ordering == ["-created_at"]

    # Verify we can create instances
    instance = MixinTestModel.query.create(name="test")
    assert instance.created_at is not None
    assert instance.updated_at is not None
    assert instance.name == "test"


def test_many_to_many_forward_accessor(db):
    """Test that the forward ManyToManyField accessor works."""
    car = Car.query.create(make="Tesla", model="Model 3")
    gps = Feature.query.create(name="GPS")
    sunroof = Feature.query.create(name="Sunroof")

    # Add features to the car
    car.features.add(gps, sunroof)

    # Verify features are accessible through forward accessor
    assert car.features.query.count() == 2
    feature_names = {f.name for f in car.features.query.all()}
    assert feature_names == {"GPS", "Sunroof"}


def test_many_to_many_reverse_accessor(db):
    """Test that the reverse ManyToManyField accessor works."""
    car1 = Car.query.create(make="Tesla", model="Model 3")
    car2 = Car.query.create(make="Toyota", model="Camry")
    gps = Feature.query.create(name="GPS")

    # Add the same feature to multiple cars
    car1.features.add(gps)
    car2.features.add(gps)

    # Verify cars are accessible through reverse accessor
    assert gps.cars.query.count() == 2
    car_models = {c.model for c in gps.cars.query.all()}
    assert car_models == {"Model 3", "Camry"}


def test_many_to_many_remove(db):
    """Test removing items from a ManyToManyField."""
    car = Car.query.create(make="Honda", model="Accord")
    gps = Feature.query.create(name="GPS")
    sunroof = Feature.query.create(name="Sunroof")
    leather = Feature.query.create(name="Leather Seats")

    car.features.add(gps, sunroof, leather)
    assert car.features.query.count() == 3

    # Remove one feature
    car.features.remove(sunroof)
    assert car.features.query.count() == 2
    feature_names = {f.name for f in car.features.query.all()}
    assert feature_names == {"GPS", "Leather Seats"}


def test_many_to_many_clear(db):
    """Test clearing all items from a ManyToManyField."""
    car = Car.query.create(make="BMW", model="X5")
    gps = Feature.query.create(name="GPS")
    sunroof = Feature.query.create(name="Sunroof")

    car.features.add(gps, sunroof)
    assert car.features.query.count() == 2

    # Clear all features
    car.features.clear()
    assert car.features.query.count() == 0


def test_many_to_many_through_model(db):
    """Test accessing the through model directly."""
    car = Car.query.create(make="Ford", model="Mustang")
    gps = Feature.query.create(name="GPS")

    # Create relationship through the through model
    CarFeature.query.create(car=car, feature=gps)

    # Verify the relationship exists
    assert car.features.query.count() == 1
    assert car.features.query.first() == gps

    # Verify we can query the through model
    through_instances = CarFeature.query.filter(car=car)
    assert through_instances.count() == 1
    through_instance = through_instances.first()
    assert through_instance is not None
    assert through_instance.feature == gps


def test_meta_related_objects_includes_reverse_fk(db):
    """Test that Meta.related_objects includes reverse FK relations.

    Regression test: related_objects was checking obj.field.one_to_many
    instead of obj.one_to_many, which excluded all reverse FK relations.
    """
    # DeleteParent has multiple child models with FKs pointing to it
    related_objs = DeleteParent._model_meta.related_objects

    # Should have reverse FK relations from child models
    assert len(related_objs) > 0, "related_objects should not be empty"

    # Convert to list of field names for easier checking
    related_fields = [obj.field for obj in related_objs]
    related_names = [f.name for f in related_fields]

    # Should include the FK from ChildCascade
    assert "parent" in related_names, (
        "ChildCascade.parent reverse FK should be in related_objects"
    )

    # Find the reverse relation and verify it's a ForeignKeyRel (one_to_many)
    from plain.models.fields.reverse_related import ForeignKeyRel

    parent_rel = next(obj for obj in related_objs if obj.field.name == "parent")
    assert isinstance(parent_rel, ForeignKeyRel), (
        "Reverse FK should be ForeignKeyRel (one_to_many from parent's perspective)"
    )


def test_raw_query(db):
    """Test that raw SQL queries work correctly."""
    # Create some test data
    Car.query.create(make="Toyota", model="Camry")
    Car.query.create(make="Honda", model="Civic")
    Car.query.create(make="Ford", model="F-150")

    # Test raw query returns model instances
    cars = list(Car.query.raw("SELECT * FROM examples_car ORDER BY make"))
    assert len(cars) == 3
    assert all(isinstance(c, Car) for c in cars)

    # Verify the data is correct
    makes = [c.make for c in cars]
    assert makes == ["Ford", "Honda", "Toyota"]


def test_raw_query_with_params(db):
    """Test raw queries with parameters."""
    Car.query.create(make="Toyota", model="Camry")
    Car.query.create(make="Toyota", model="Corolla")
    Car.query.create(make="Honda", model="Civic")

    # Test with tuple params
    cars = list(
        Car.query.raw("SELECT * FROM examples_car WHERE make = %s", ("Toyota",))
    )
    assert len(cars) == 2
    assert all(c.make == "Toyota" for c in cars)

    # Test with list params (user-friendly - converted to tuple internally)
    cars = list(Car.query.raw("SELECT * FROM examples_car WHERE make = %s", ["Honda"]))
    assert len(cars) == 1
    assert cars[0].make == "Honda"
