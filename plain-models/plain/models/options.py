from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from plain.models.backends.utils import truncate_name
from plain.models.db import db_connection
from plain.packages import packages_registry

if TYPE_CHECKING:
    from plain.models.base import Model
    from plain.models.constraints import BaseConstraint
    from plain.models.indexes import Index


class Options:
    """
    Model options descriptor and container.

    Acts as both a descriptor (for lazy initialization and access control)
    and the actual options instance (cached per model class).
    """

    # Type annotations for attributes set in _create_and_cache
    # These exist on cached instances, not on the descriptor itself
    model: type[Model]
    package_label: str
    db_table: str
    db_table_comment: str
    ordering: Sequence[str]
    indexes: Sequence[Index]
    constraints: Sequence[BaseConstraint]
    required_db_features: Sequence[str]
    required_db_vendor: str | None
    _provided_options: set[str]

    def __init__(
        self,
        *,
        db_table: str | None = None,
        db_table_comment: str | None = None,
        ordering: Sequence[str] | None = None,
        indexes: Sequence[Index] | None = None,
        constraints: Sequence[BaseConstraint] | None = None,
        required_db_features: Sequence[str] | None = None,
        required_db_vendor: str | None = None,
        package_label: str | None = None,
    ):
        """
        Initialize the descriptor with optional configuration.

        This is called ONCE when defining the base Model class, or when
        a user explicitly sets model_options = Options(...) on their model.
        The descriptor then creates cached instances per model subclass.
        """
        self._config = {
            "db_table": db_table,
            "db_table_comment": db_table_comment,
            "ordering": ordering,
            "indexes": indexes,
            "constraints": constraints,
            "required_db_features": required_db_features,
            "required_db_vendor": required_db_vendor,
            "package_label": package_label,
        }
        self._cache: dict[type[Model], Options] = {}

    def __get__(self, instance: Any, owner: type[Model]) -> Options:
        """
        Descriptor protocol - returns cached Options for the model class.

        This is called when accessing Model.model_options and returns a per-class
        cached instance created by _create_and_cache().

        Can be accessed from both class and instances:
        - MyModel.model_options (class access)
        - my_instance.model_options (instance access - returns class's options)
        """
        # Allow instance access - just return the class's options
        if instance is not None:
            owner = instance.__class__

        # Skip for the base Model class - return descriptor
        if owner.__name__ == "Model" and owner.__module__ == "plain.models.base":
            return self  # type: ignore

        # Return cached instance or create new one
        if owner not in self._cache:
            return self._create_and_cache(owner)

        return self._cache[owner]

    def _create_and_cache(self, model: type[Model]) -> Options:
        """Create Options and cache it."""
        # Create instance without calling __init__
        instance = Options.__new__(Options)

        # Track which options were explicitly provided by user
        # Note: package_label is excluded because it's passed separately in migrations
        instance._provided_options = {
            k for k, v in self._config.items() if v is not None and k != "package_label"
        }

        instance.model = model

        # Resolve package_label
        package_label = self._config.get("package_label")
        if package_label is None:
            module = model.__module__
            package_config = packages_registry.get_containing_package_config(module)
            if package_config is None:
                raise RuntimeError(
                    f"Model class {module}.{model.__name__} doesn't declare an explicit "
                    "package_label and isn't in an application in INSTALLED_PACKAGES."
                )
            instance.package_label = package_config.package_label
        else:
            instance.package_label = package_label

        # Set db_table
        db_table = self._config.get("db_table")
        if db_table is None:
            instance.db_table = truncate_name(
                f"{instance.package_label}_{model.__name__.lower()}",
                db_connection.ops.max_name_length(),
            )
        else:
            instance.db_table = db_table

        instance.db_table_comment = self._config.get("db_table_comment") or ""
        instance.ordering = self._config.get("ordering") or []
        instance.indexes = self._config.get("indexes") or []
        instance.constraints = self._config.get("constraints") or []
        instance.required_db_features = self._config.get("required_db_features") or []
        instance.required_db_vendor = self._config.get("required_db_vendor")

        # Format names with class interpolation
        instance.constraints = instance._format_names_with_class(instance.constraints)
        instance.indexes = instance._format_names_with_class(instance.indexes)

        # Cache early to prevent recursion if needed
        self._cache[model] = instance

        return instance

    @property
    def object_name(self) -> str:
        """The model class name."""
        return self.model.__name__

    @property
    def model_name(self) -> str:
        """The model class name in lowercase."""
        return self.object_name.lower()

    @property
    def label(self) -> str:
        """The model label: package_label.ClassName"""
        return f"{self.package_label}.{self.object_name}"

    @property
    def label_lower(self) -> str:
        """The model label in lowercase: package_label.classname"""
        return f"{self.package_label}.{self.model_name}"

    def _format_names_with_class(self, objs: list[Any]) -> list[Any]:
        """Package label/class name interpolation for object names."""
        new_objs = []
        for obj in objs:
            obj = obj.clone()
            obj.name = obj.name % {
                "package_label": self.package_label.lower(),
                "class": self.model.__name__.lower(),
            }
            new_objs.append(obj)
        return new_objs

    def export_for_migrations(self) -> dict[str, Any]:
        """Export user-provided options for migrations."""
        options = {}
        for name in self._provided_options:
            if name == "indexes":
                # Clone indexes and ensure names are set
                indexes = [idx.clone() for idx in self.indexes]
                for index in indexes:
                    if not index.name:
                        index.set_name_with_model(self.model)
                options["indexes"] = indexes
            elif name == "constraints":
                # Clone constraints
                options["constraints"] = [con.clone() for con in self.constraints]
            else:
                # Use current attribute value
                options[name] = getattr(self, name)
        return options

    @property
    def total_unique_constraints(self) -> list[Any]:
        """
        Return a list of total unique constraints. Useful for determining set
        of fields guaranteed to be unique for all rows.
        """
        from plain.models.constraints import UniqueConstraint

        return [
            constraint
            for constraint in self.constraints
            if (
                isinstance(constraint, UniqueConstraint)
                and constraint.condition is None
                and not constraint.contains_expressions
            )
        ]

    def can_migrate(self, connection: Any) -> bool:
        """
        Return True if the model can/should be migrated on the given
        `connection` object.
        """
        if self.required_db_vendor:
            return self.required_db_vendor == connection.vendor
        if self.required_db_features:
            return all(
                getattr(connection.features, feat, False)
                for feat in self.required_db_features
            )
        return True

    def __repr__(self) -> str:
        return f"<Options for {self.model.__name__}>"

    def __str__(self) -> str:
        return f"{self.package_label}.{self.model.__name__.lower()}"
