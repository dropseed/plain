from app.examples.models import (
    CustomManager,
    CustomManagerModel,
    CustomQuerySetModel,
    DefaultManagerModel,
)

from plain.models.manager import Manager


def test_model_has_default_objects_manager():
    """Test that models get objects manager by default."""

    # Should have objects property
    assert hasattr(DefaultManagerModel, "objects")
    assert isinstance(DefaultManagerModel.objects, Manager)

    # manager should be a Manager instance
    assert isinstance(DefaultManagerModel._meta.manager, Manager)
    # base_manager may be different - it's used for internal operations
    assert DefaultManagerModel._meta.base_manager is not None
    assert isinstance(DefaultManagerModel._meta.base_manager, Manager)


def test_model_with_custom_manager():
    """Test that custom managers work correctly."""

    # Should have custom manager as objects
    assert hasattr(CustomManagerModel, "objects")
    assert isinstance(CustomManagerModel.objects, CustomManager)
    assert hasattr(CustomManagerModel.objects, "get_custom")

    # Custom manager should be the manager
    assert isinstance(CustomManagerModel._meta.manager, CustomManager)
    # base_manager may be different - it's used for internal operations
    assert CustomManagerModel._meta.base_manager is not None
    assert isinstance(CustomManagerModel._meta.base_manager, Manager)


def test_field_named_objects_validation():
    """Test that objects is always a manager property, fields can't override it."""
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
    assert isinstance(FieldObjectsModel.objects, Manager)


def test_base_manager_manager_consistency():
    """Test that base_manager and manager work consistently."""

    # Should have working base and manager
    base_manager = DefaultManagerModel._meta.base_manager
    manager = DefaultManagerModel._meta.manager

    assert base_manager is not None
    assert isinstance(base_manager, Manager)
    assert manager is not None
    assert isinstance(manager, Manager)

    # base_manager should always exist for internal operations
    assert hasattr(base_manager, "get_queryset")

    # These managers should be usable for basic operations
    qs = base_manager.get_queryset()
    assert qs.model is DefaultManagerModel


def test_objects_manager_contributes_to_class():
    """Test that objects manager properly contributes to the class."""

    # The manager should be properly set up with the model
    assert DefaultManagerModel.objects.model is DefaultManagerModel


def test_model_with_custom_queryset_manager():
    """Test that QuerySet classes work as manager_class via Manager.from_queryset()."""

    # Should have manager created from Manager.from_queryset(CustomQuerySet)
    assert hasattr(CustomQuerySetModel, "objects")
    assert isinstance(CustomQuerySetModel.objects, Manager)
    assert hasattr(CustomQuerySetModel.objects, "get_custom_qs")

    # The manager should be created from Manager.from_queryset(CustomQuerySet)
    assert isinstance(CustomQuerySetModel._meta.manager, Manager)
    assert hasattr(CustomQuerySetModel._meta.manager, "get_custom_qs")


def test_objects_validation():
    """Test that objects property always returns a manager regardless of class attributes."""
    from plain import models

    # Even if we set objects to something else, the property takes precedence
    @models.register_model
    class BadObjectsModel(models.Model):
        objects = "not a manager"  # This won't affect the objects property
        name = models.CharField(max_length=100)

        class Meta:
            package_label = "test_app"

    # Should have the default manager, not the string
    assert isinstance(BadObjectsModel.objects, Manager)


def test_instance_cannot_access_objects():
    """Test that model instances don't have .objects attribute (should raise AttributeError)."""
    import pytest

    # Test accessing .objects on class (should work)
    assert hasattr(DefaultManagerModel, "objects")
    assert isinstance(DefaultManagerModel.objects, Manager)

    # Test accessing .objects on instance (should raise AttributeError)
    instance = DefaultManagerModel(name="test")
    with pytest.raises(AttributeError):
        _ = instance.objects
