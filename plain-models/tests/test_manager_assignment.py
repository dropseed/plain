from app.examples.models import (
    CustomQuerySet,
    CustomQuerySetModel,
    CustomSpecialQuerySetModel,
    DefaultQuerySetModel,
)

from plain.models.query import QuerySet


def test_model_has_default_query_queryset():
    """Test that models get query QuerySet by default."""

    # Should have query property
    assert hasattr(DefaultQuerySetModel, "query")
    assert isinstance(DefaultQuerySetModel.query, QuerySet)

    # query should be a QuerySet instance
    assert isinstance(DefaultQuerySetModel._meta.queryset, QuerySet)
    # base_queryset may be different - it's used for internal operations
    assert DefaultQuerySetModel._meta.base_queryset is not None
    assert isinstance(DefaultQuerySetModel._meta.base_queryset, QuerySet)


def test_model_with_custom_queryset():
    """Test that custom QuerySets work correctly."""

    # Should have custom manager as query
    assert hasattr(CustomQuerySetModel, "query")
    assert isinstance(CustomQuerySetModel.query, CustomQuerySet)
    assert hasattr(CustomQuerySetModel.query, "get_custom")

    # Custom QuerySet should be the manager
    assert isinstance(CustomQuerySetModel._meta.queryset, CustomQuerySet)
    # base_queryset may be different - it's used for internal operations
    assert CustomQuerySetModel._meta.base_queryset is not None
    assert isinstance(CustomQuerySetModel._meta.base_queryset, QuerySet)


def test_field_named_objects_validation():
    """Test that query is always a QuerySet property, fields can't override it."""
    from plain import models

    # Even if we define a field named objects, the query property takes precedence
    @models.register_model
    class FieldObjectsModel(models.Model):
        objects = models.CharField(
            max_length=100
        )  # This field exists but won't override query property
        name = models.CharField(max_length=100)

        class Meta:
            package_label = "test_app"

    # The query property takes precedence over the field
    assert hasattr(FieldObjectsModel, "objects")
    assert isinstance(FieldObjectsModel.query, QuerySet)


def test_base_queryset_consistency():
    """Test that base_queryset and queryset work consistently."""

    # Should have working base and queryset
    base_queryset = DefaultQuerySetModel._meta.base_queryset
    queryset = DefaultQuerySetModel._meta.queryset

    assert base_queryset is not None
    assert isinstance(base_queryset, QuerySet)
    assert queryset is not None
    assert isinstance(queryset, QuerySet)


def test_query_queryset_contributes_to_class():
    """Test that query QuerySet properly contributes to the class."""

    # The QuerySet should be properly set up with the model
    assert DefaultQuerySetModel.query.model is DefaultQuerySetModel


def test_model_with_custom_special_queryset():
    """Test that QuerySet classes work as queryset_class directly."""

    # Should have QuerySet with custom methods
    assert hasattr(CustomSpecialQuerySetModel, "query")
    assert isinstance(CustomSpecialQuerySetModel.query, QuerySet)
    assert hasattr(CustomSpecialQuerySetModel.query, "get_custom_qs")

    # The manager should be the custom QuerySet
    assert isinstance(CustomSpecialQuerySetModel._meta.queryset, QuerySet)
    assert hasattr(CustomSpecialQuerySetModel._meta.queryset, "get_custom_qs")


def test_query_validation():
    """Test that query property always returns a QuerySet regardless of class attributes."""
    from plain import models

    # Even if we set objects to something else, the query property takes precedence
    @models.register_model
    class BadObjectsModel(models.Model):
        objects = "not a manager"  # This won't affect the query property
        name = models.CharField(max_length=100)

        class Meta:
            package_label = "test_app"

    # Should have the default QuerySet, not the string
    assert isinstance(BadObjectsModel.query, QuerySet)


def test_instance_cannot_access_query():
    """Test that model instances don't have .query attribute (should raise AttributeError)."""
    import pytest

    # Test accessing .query on class (should work)
    assert hasattr(DefaultQuerySetModel, "query")
    assert isinstance(DefaultQuerySetModel.query, QuerySet)

    # Test accessing .query on instance (should raise AttributeError)
    instance = DefaultQuerySetModel(name="test")
    with pytest.raises(AttributeError):
        _ = instance.query
