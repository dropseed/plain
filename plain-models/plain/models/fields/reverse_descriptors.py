"""
Reverse relation descriptors for explicit reverse relation declarations.

This module contains descriptors for the reverse side of ForeignKeyField and
ManyToManyField relations, allowing explicit declaration of reverse accessors
without relying on automatic related_name generation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from plain.models import Model
    from plain.models.fields.related_managers import BaseRelatedManager
    from plain.models.query import QuerySet

T = TypeVar("T", bound="Model")
# Default to QuerySet[Any] so users can omit the second type parameter
QS = TypeVar("QS", bound="QuerySet[Any]", default="QuerySet[Any]")


class BaseReverseDescriptor(Generic[T, QS]):
    """
    Base class for reverse relation descriptors.

    Provides common functionality for ReverseForeignKey and ReverseManyToMany
    descriptors, including field resolution, validation, and the descriptor protocol.
    """

    def __init__(self, to: str | type[T], field: str):
        self.to = to
        self.field_name = field
        self.name: str | None = None
        self.model: type[Model] | None = None
        self._resolved_model: type[T] | None = None
        self._resolved_field: Any = None

    def contribute_to_class(self, cls: type[Model], name: str) -> None:
        """
        Register this reverse relation with the model class.

        Called by the model metaclass when the model is created.
        """
        self.name = name
        self.model = cls

        # Set the descriptor on the class
        setattr(cls, name, self)

        # Register this as a related object for prefetch support
        # We'll do this lazily when the target model is resolved
        from plain.models.fields.related import lazy_related_operation

        def resolve_related_field(
            parent_model: type[Model], related_model: type[T]
        ) -> None:
            """Resolve the target model and field, then register."""
            self._resolved_model = related_model
            try:
                self._resolved_field = related_model._model_meta.get_field(
                    self.field_name
                )
            except Exception as e:
                raise ValueError(
                    f"Field '{self.field_name}' not found on model "
                    f"'{related_model.__name__}' for {self._get_descriptor_type()} '{self.name}' "
                    f"on '{cls.__name__}'. Error: {e}"
                )

            # Validate that the field is the correct type
            self._validate_field_type(related_model)

        # Use lazy operation to handle circular dependencies
        lazy_related_operation(resolve_related_field, cls, self.to)

    def __get__(
        self, instance: Model | None, owner: type[Model]
    ) -> BaseReverseDescriptor[T, QS] | BaseRelatedManager[T, QS]:
        """
        Get the related manager when accessed on an instance.

        When accessed on the class, returns the descriptor.
        When accessed on an instance, returns a manager.
        """
        if instance is None:
            return self

        # Ensure the related model and field are resolved
        if self._resolved_field is None or self.model is None:
            model_name = self.model.__name__ if self.model else "Unknown"
            raise ValueError(
                f"{self._get_descriptor_type()} '{self.name}' on '{model_name}' "
                f"has not been resolved yet. The target model may not be registered."
            )

        # _resolved_model is set alongside _resolved_field in resolve_related_field
        assert self._resolved_model is not None, "Model should be resolved with field"

        # Return a manager bound to this instance
        return self._create_manager(instance)

    def __set__(self, instance: Model, value: Any) -> None:
        """Prevent direct assignment to reverse relations."""
        raise TypeError(
            f"Direct assignment to the reverse side of a {self._get_field_type()} "
            f"('{self.name}') is prohibited. Use {self.name}.set() instead."
        )

    def _get_descriptor_type(self) -> str:
        """Return the name of this descriptor type for error messages."""
        raise NotImplementedError("Subclasses must implement _get_descriptor_type()")

    def _get_field_type(self) -> str:
        """Return the name of the forward field type for error messages."""
        raise NotImplementedError("Subclasses must implement _get_field_type()")

    def _validate_field_type(self, related_model: type[Model]) -> None:
        """Validate that the resolved field is the correct type."""
        raise NotImplementedError("Subclasses must implement _validate_field_type()")

    def _create_manager(self, instance: Model) -> Any:
        """Create and return the appropriate manager for this instance."""
        raise NotImplementedError("Subclasses must implement _create_manager()")


class ReverseForeignKey(BaseReverseDescriptor[T, QS]):
    """
    Descriptor for the reverse side of a ForeignKeyField relation.

    Provides access to the related instances on the "one" side of a one-to-many
    relationship.

    Example:
        class Parent(Model):
            # Basic usage (uses default QuerySet[Child])
            children: ReverseForeignKey[Child, QuerySet[Child]] = ReverseForeignKey(to="Child", field="parent")

            # With custom QuerySet
            children: ReverseForeignKey[Child, ChildQuerySet] = ReverseForeignKey(to="Child", field="parent")

        class Child(Model):
            parent: Parent = ForeignKeyField(Parent, on_delete=models.CASCADE)

    Args:
        to: The related model (string name or model class)
        field: The field name on the related model that points back to this model
    """

    def _get_descriptor_type(self) -> str:
        return "ReverseForeignKey"

    def _get_field_type(self) -> str:
        return "ForeignKey"

    def _validate_field_type(self, related_model: type[Model]) -> None:
        """Validate that the field is a ForeignKey."""
        from plain.models.fields.related import ForeignKeyField

        if not isinstance(self._resolved_field, ForeignKeyField):
            raise ValueError(
                f"Field '{self.field_name}' on '{related_model.__name__}' is not a "
                f"ForeignKey. ReverseForeignKey requires a ForeignKeyField field."
            )

    def _create_manager(self, instance: Model) -> Any:
        """Create a ReverseForeignKeyManager for this instance."""
        from plain.models.fields.related_managers import ReverseForeignKeyManager

        assert self._resolved_model is not None
        return ReverseForeignKeyManager(
            instance=instance,
            field=self._resolved_field,
            related_model=self._resolved_model,
        )


class ReverseManyToMany(BaseReverseDescriptor[T, QS]):
    """
    Descriptor for the reverse side of a ManyToManyField relation.

    Provides access to the related instances on the reverse side of a many-to-many
    relationship.

    Example:
        class Feature(Model):
            # Basic usage (uses default QuerySet[Car])
            cars: ReverseManyToMany[Car, QuerySet[Car]] = ReverseManyToMany(to="Car", field="features")

            # With custom QuerySet
            cars: ReverseManyToMany[Car, CarQuerySet] = ReverseManyToMany(to="Car", field="features")

        class Car(Model):
            features: ManyToManyField[Feature] = ManyToManyField(Feature, through=CarFeature)

    Args:
        to: The related model (string name or model class)
        field: The field name on the related model that points to this model
    """

    def _get_descriptor_type(self) -> str:
        return "ReverseManyToMany"

    def _get_field_type(self) -> str:
        return "ManyToManyField"

    def _validate_field_type(self, related_model: type[Model]) -> None:
        """Validate that the field is a ManyToManyField."""
        from plain.models.fields.related import ManyToManyField

        if not isinstance(self._resolved_field, ManyToManyField):
            raise ValueError(
                f"Field '{self.field_name}' on '{related_model.__name__}' is not a "
                f"ManyToManyField. ReverseManyToMany requires a ManyToManyField."
            )

    def _create_manager(self, instance: Model) -> Any:
        """Create a ManyToManyManager for this instance."""
        from plain.models.fields.related_managers import ManyToManyManager

        assert self._resolved_model is not None
        return ManyToManyManager(
            instance=instance,
            field=self._resolved_field,
            through=self._resolved_field.remote_field.through,
            related_model=self._resolved_model,
            is_reverse=True,
            symmetrical=False,
        )
