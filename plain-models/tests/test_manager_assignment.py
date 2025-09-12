from app.examples.models import (
    CustomQuerySet,
    CustomQuerySetModel,
    CustomSpecialQuerySetModel,
    DefaultQuerySetModel,
)

from plain.models.query import QuerySet


def test_model_has_default_objects_queryset():
    """Test that models get objects QuerySet by default."""

    # Should have objects property
    assert hasattr(DefaultQuerySetModel, "objects")
    assert isinstance(DefaultQuerySetModel.objects, QuerySet)

    # objects should be a QuerySet instance
    assert isinstance(DefaultQuerySetModel._meta.queryset, QuerySet)
    # base_queryset may be different - it's used for internal operations
    assert DefaultQuerySetModel._meta.base_queryset is not None
    assert isinstance(DefaultQuerySetModel._meta.base_queryset, QuerySet)


def test_model_with_custom_queryset():
    """Test that custom QuerySets work correctly."""

    # Should have custom manager as objects
    assert hasattr(CustomQuerySetModel, "objects")
    assert isinstance(CustomQuerySetModel.objects, CustomQuerySet)
    assert hasattr(CustomQuerySetModel.objects, "get_custom")

    # Custom QuerySet should be the manager
    assert isinstance(CustomQuerySetModel._meta.queryset, CustomQuerySet)
    # base_queryset may be different - it's used for internal operations
    assert CustomQuerySetModel._meta.base_queryset is not None
    assert isinstance(CustomQuerySetModel._meta.base_queryset, QuerySet)


def test_field_named_objects_validation():
    """Test that objects is always a QuerySet property, fields can't override it."""
    from plain import models

    # Even if we define a field named objects, the property takes precedence
    @models.register_model
    class FieldObjectsModel(models.Model):
        objects = models.CharField(
            max_length=100
        )  # This field exists but won't override objects property
        name = models.CharField(max_length=100)

        class Meta:
            package_label = "test_app"

    # The objects property takes precedence over the field
    assert hasattr(FieldObjectsModel, "objects")
    assert isinstance(FieldObjectsModel.objects, QuerySet)


def test_base_queryset_consistency():
    """Test that base_queryset and queryset work consistently."""

    # Should have working base and queryset
    base_queryset = DefaultQuerySetModel._meta.base_queryset
    queryset = DefaultQuerySetModel._meta.queryset

    assert base_queryset is not None
    assert isinstance(base_queryset, QuerySet)
    assert queryset is not None
    assert isinstance(queryset, QuerySet)


def test_objects_queryset_contributes_to_class():
    """Test that objects QuerySet properly contributes to the class."""

    # The QuerySet should be properly set up with the model
    assert DefaultQuerySetModel.objects.model is DefaultQuerySetModel


def test_model_with_custom_special_queryset():
    """Test that QuerySet classes work as queryset_class directly."""

    # Should have QuerySet with custom methods
    assert hasattr(CustomSpecialQuerySetModel, "objects")
    assert isinstance(CustomSpecialQuerySetModel.objects, QuerySet)
    assert hasattr(CustomSpecialQuerySetModel.objects, "get_custom_qs")

    # The manager should be the custom QuerySet
    assert isinstance(CustomSpecialQuerySetModel._meta.queryset, QuerySet)
    assert hasattr(CustomSpecialQuerySetModel._meta.queryset, "get_custom_qs")


def test_objects_validation():
    """Test that objects property always returns a QuerySet regardless of class attributes."""
    from plain import models

    # Even if we set objects to something else, the property takes precedence
    @models.register_model
    class BadObjectsModel(models.Model):
        objects = "not a manager"  # This won't affect the objects property
        name = models.CharField(max_length=100)

        class Meta:
            package_label = "test_app"

    # Should have the default QuerySet, not the string
    assert isinstance(BadObjectsModel.objects, QuerySet)


def test_instance_cannot_access_objects():
    """Test that model instances don't have .objects attribute (should raise AttributeError)."""
    import pytest

    # Test accessing .objects on class (should work)
    assert hasattr(DefaultQuerySetModel, "objects")
    assert isinstance(DefaultQuerySetModel.objects, QuerySet)

    # Test accessing .objects on instance (should raise AttributeError)
    instance = DefaultQuerySetModel(name="test")
    with pytest.raises(AttributeError):
        _ = instance.objects
