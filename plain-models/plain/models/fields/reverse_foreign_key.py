"""
Reverse ForeignKey descriptor for explicit reverse relation declaration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

if TYPE_CHECKING:
    from plain.models import Model
    from plain.models.fields.related_managers import ReverseManyToOneManager

T = TypeVar("T", bound="Model")


class ReverseForeignKey(Generic[T]):
    """
    Descriptor for the reverse side of a ForeignKey relation.

    Provides access to the related instances on the "one" side of a one-to-many
    relationship.

    Example:
        class Parent(Model):
            children: ReverseForeignKey[Child] = ReverseForeignKey(to="Child", field="parent")

        class Child(Model):
            parent: Parent = ForeignKey(Parent, on_delete=models.CASCADE)

    Args:
        to: The related model (string name or model class)
        field: The field name on the related model that points back to this model
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
                    f"'{related_model.__name__}' for ReverseForeignKey '{self.name}' "
                    f"on '{cls.__name__}'. Error: {e}"
                )

            # Validate that the field is a ForeignKey pointing to our model
            if not hasattr(self._resolved_field, "many_to_one"):
                raise ValueError(
                    f"Field '{self.field_name}' on '{related_model.__name__}' is not a "
                    f"ForeignKey. ReverseForeignKey requires a ForeignKey field."
                )

        # Use lazy operation to handle circular dependencies
        lazy_related_operation(resolve_related_field, cls, self.to)

    @overload
    def __get__(self, instance: None, owner: type[Model]) -> ReverseForeignKey[T]: ...

    @overload
    def __get__(
        self, instance: Model, owner: type[Model]
    ) -> ReverseManyToOneManager[T]: ...

    def __get__(
        self, instance: Model | None, owner: type[Model]
    ) -> ReverseForeignKey[T] | ReverseManyToOneManager[T]:
        """
        Get the related manager when accessed on an instance.

        When accessed on the class (e.g., Parent.children), returns the descriptor.
        When accessed on an instance (e.g., parent.children), returns a manager.
        """
        if instance is None:
            return self

        # Ensure the related model and field are resolved
        if self._resolved_field is None or self.model is None:
            model_name = self.model.__name__ if self.model else "Unknown"
            raise ValueError(
                f"ReverseForeignKey '{self.name}' on '{model_name}' "
                f"has not been resolved yet. The target model may not be registered."
            )

        # Return a manager bound to this instance
        from plain.models.fields.related_managers import ReverseManyToOneManager

        return ReverseManyToOneManager(
            instance=instance,
            field=self._resolved_field,
            related_model=self._resolved_model,  # type: ignore[arg-type]
        )

    def __set__(self, instance: Model, value: Any) -> None:
        """Prevent direct assignment to reverse relations."""
        raise TypeError(
            f"Direct assignment to the reverse side of a ForeignKey "
            f"('{self.name}') is prohibited. Use {self.name}.set() instead."
        )
