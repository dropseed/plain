from app.examples.models import (
    CustomManager,
    CustomManagerModel,
    DefaultManagerModel,
    NoObjectsModel,
)

from plain.models.manager import Manager


def test_model_has_default_objects_manager():
    """Test that models get objects manager by default."""

    # Should have objects manager
    assert hasattr(DefaultManagerModel, "objects")
    assert isinstance(DefaultManagerModel.objects, Manager)

    # objects should be the default manager
    assert DefaultManagerModel._default_manager is DefaultManagerModel.objects
    # base_manager may be different - it's used for internal operations
    assert DefaultManagerModel._base_manager is not None
    assert isinstance(DefaultManagerModel._base_manager, Manager)


def test_model_with_objects_none():
    """Test that setting objects = None removes the manager."""

    # Should not have objects manager
    assert not hasattr(NoObjectsModel, "objects") or NoObjectsModel.objects is None

    # Should still have base_manager and default_manager
    assert hasattr(NoObjectsModel, "_base_manager")
    assert hasattr(NoObjectsModel, "_default_manager")

    # These should be different Manager instances
    assert NoObjectsModel._base_manager is not None
    assert isinstance(NoObjectsModel._base_manager, Manager)


def test_model_with_custom_manager():
    """Test that custom managers work correctly."""

    # Should have custom manager as objects
    assert hasattr(CustomManagerModel, "objects")
    assert isinstance(CustomManagerModel.objects, CustomManager)
    assert hasattr(CustomManagerModel.objects, "get_custom")

    # Custom manager should be the default manager
    assert CustomManagerModel._default_manager is CustomManagerModel.objects
    # base_manager may be different - it's used for internal operations
    assert CustomManagerModel._base_manager is not None
    assert isinstance(CustomManagerModel._base_manager, Manager)


def test_field_named_objects_validation():
    """Test that defining a field named 'objects' raises a validation error."""
    import pytest

    from plain import models

    # This should fail - objects cannot be a field
    with pytest.raises(
        TypeError, match="attribute 'objects' must be either None or a Manager instance"
    ):

        @models.register_model
        class FieldObjectsModel(models.Model):
            objects = models.CharField(max_length=100)  # This should cause a TypeError
            name = models.CharField(max_length=100)

            class Meta:
                package_label = "test_app"


def test_base_manager_default_manager_without_objects():
    """Test that base_manager and default_manager work even without objects."""

    # Should have working base and default managers
    base_manager = NoObjectsModel._base_manager

    assert base_manager is not None
    assert isinstance(base_manager, Manager)

    # default_manager might be None if no managers are defined
    # but base_manager should always exist for internal operations
    assert hasattr(base_manager, "get_queryset")

    # These managers should be usable for basic operations
    qs = base_manager.get_queryset()
    assert qs.model is NoObjectsModel


def test_objects_manager_contributes_to_class():
    """Test that objects manager properly contributes to the class."""

    # The manager should be properly set up with the model
    assert DefaultManagerModel.objects.model is DefaultManagerModel
    assert DefaultManagerModel.objects.name == "objects"

    # Should be in the model's meta managers
    manager_names = [m.name for m in DefaultManagerModel._meta.managers]
    assert "objects" in manager_names


def test_objects_validation():
    """Test that objects attribute is validated to be None or Manager."""
    import pytest

    from plain import models

    # This should fail - objects is not None or a Manager
    with pytest.raises(
        TypeError, match="attribute 'objects' must be either None or a Manager instance"
    ):

        @models.register_model
        class BadObjectsModel(models.Model):
            objects = "not a manager"  # This should cause a TypeError
            name = models.CharField(max_length=100)

            class Meta:
                package_label = "test_app"
