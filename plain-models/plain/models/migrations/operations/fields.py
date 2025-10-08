from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any

from plain.models.fields import NOT_PROVIDED
from plain.models.migrations.utils import field_references

from .base import Operation

if TYPE_CHECKING:
    from plain.models.backends.base.schema import BaseDatabaseSchemaEditor
    from plain.models.fields import Field
    from plain.models.migrations.state import ProjectState


class FieldOperation(Operation):
    def __init__(self, model_name: str, name: str, field: Field | None = None) -> None:
        self.model_name = model_name
        self.name = name
        self.field = field

    @cached_property
    def model_name_lower(self) -> str:
        return self.model_name.lower()

    @cached_property
    def name_lower(self) -> str:
        return self.name.lower()

    def is_same_model_operation(self, operation: FieldOperation) -> bool:
        return self.model_name_lower == operation.model_name_lower

    def is_same_field_operation(self, operation: FieldOperation) -> bool:
        return (
            self.is_same_model_operation(operation)
            and self.name_lower == operation.name_lower
        )

    def references_model(self, name: str, package_label: str) -> bool:
        name_lower = name.lower()
        if name_lower == self.model_name_lower:
            return True
        if self.field:
            return bool(
                field_references(
                    (package_label, self.model_name_lower),
                    self.field,
                    (package_label, name_lower),
                )
            )
        return False

    def references_field(self, model_name: str, name: str, package_label: str) -> bool:
        model_name_lower = model_name.lower()
        # Check if this operation locally references the field.
        if model_name_lower == self.model_name_lower:
            if name == self.name:
                return True
        # Check if this operation remotely references the field.
        if self.field is None:
            return False
        return bool(
            field_references(
                (package_label, self.model_name_lower),
                self.field,
                (package_label, model_name_lower),
                name,
            )
        )

    def reduce(
        self, operation: Operation, package_label: str
    ) -> list[Operation] | bool:
        return super().reduce(
            operation, package_label
        ) or not operation.references_field(self.model_name, self.name, package_label)


class AddField(FieldOperation):
    """Add a field to a model."""

    def __init__(
        self, model_name: str, name: str, field: Field, preserve_default: bool = True
    ) -> None:
        self.preserve_default = preserve_default
        super().__init__(model_name, name, field)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "name": self.name,
            "field": self.field,
        }
        if self.preserve_default is not True:
            kwargs["preserve_default"] = self.preserve_default
        return (self.__class__.__name__, [], kwargs)

    def state_forwards(self, package_label: str, state: Any) -> None:
        state.add_field(
            package_label,
            self.model_name_lower,
            self.name,
            self.field,
            self.preserve_default,
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        to_model = to_state.models_registry.get_model(package_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection, to_model):
            from_model = from_state.models_registry.get_model(
                package_label, self.model_name
            )
            field = to_model._model_meta.get_field(self.name)
            if not self.preserve_default:
                field.default = self.field.default
            schema_editor.add_field(
                from_model,
                field,
            )
            if not self.preserve_default:
                field.default = NOT_PROVIDED

    def describe(self) -> str:
        return f"Add field {self.name} to {self.model_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"{self.model_name_lower}_{self.name_lower}"

    def reduce(
        self, operation: Operation, package_label: str
    ) -> list[Operation] | bool:
        if isinstance(operation, FieldOperation) and self.is_same_field_operation(
            operation
        ):
            if isinstance(operation, AlterField):
                assert operation.field is not None
                return [
                    AddField(
                        model_name=self.model_name,
                        name=operation.name,
                        field=operation.field,
                    ),
                ]
            elif isinstance(operation, RemoveField):
                return []
            elif isinstance(operation, RenameField):
                return [
                    AddField(
                        model_name=self.model_name,
                        name=operation.new_name,
                        field=self.field,
                    ),
                ]
        return super().reduce(operation, package_label)


class RemoveField(FieldOperation):
    """Remove a field from a model."""

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "name": self.name,
        }
        return (self.__class__.__name__, [], kwargs)

    def state_forwards(self, package_label: str, state: Any) -> None:
        state.remove_field(package_label, self.model_name_lower, self.name)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        from_model = from_state.models_registry.get_model(
            package_label, self.model_name
        )
        if self.allow_migrate_model(schema_editor.connection, from_model):
            schema_editor.remove_field(
                from_model, from_model._model_meta.get_field(self.name)
            )

    def describe(self) -> str:
        return f"Remove field {self.name} from {self.model_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"remove_{self.model_name_lower}_{self.name_lower}"

    def reduce(
        self, operation: Operation, package_label: str
    ) -> list[Operation] | bool:
        from .models import DeleteModel

        if (
            isinstance(operation, DeleteModel)
            and operation.name_lower == self.model_name_lower
        ):
            return [operation]
        return super().reduce(operation, package_label)


class AlterField(FieldOperation):
    """
    Alter a field's database column (e.g. null, max_length) to the provided
    new field.
    """

    def __init__(
        self, model_name: str, name: str, field: Field, preserve_default: bool = True
    ) -> None:
        self.preserve_default = preserve_default
        super().__init__(model_name, name, field)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "name": self.name,
            "field": self.field,
        }
        if self.preserve_default is not True:
            kwargs["preserve_default"] = self.preserve_default
        return (self.__class__.__name__, [], kwargs)

    def state_forwards(self, package_label: str, state: Any) -> None:
        state.alter_field(
            package_label,
            self.model_name_lower,
            self.name,
            self.field,
            self.preserve_default,
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        to_model = to_state.models_registry.get_model(package_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection, to_model):
            from_model = from_state.models_registry.get_model(
                package_label, self.model_name
            )
            from_field = from_model._model_meta.get_field(self.name)
            to_field = to_model._model_meta.get_field(self.name)
            if not self.preserve_default:
                to_field.default = self.field.default
            schema_editor.alter_field(from_model, from_field, to_field)
            if not self.preserve_default:
                to_field.default = NOT_PROVIDED

    def describe(self) -> str:
        return f"Alter field {self.name} on {self.model_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"alter_{self.model_name_lower}_{self.name_lower}"

    def reduce(
        self, operation: Operation, package_label: str
    ) -> list[Operation] | bool:
        if isinstance(
            operation, AlterField | RemoveField
        ) and self.is_same_field_operation(operation):
            return [operation]
        elif (
            isinstance(operation, RenameField)
            and self.is_same_field_operation(operation)
            and self.field.db_column is None
        ):
            return [
                operation,
                AlterField(
                    model_name=self.model_name,
                    name=operation.new_name,
                    field=self.field,
                ),
            ]
        return super().reduce(operation, package_label)


class RenameField(FieldOperation):
    """Rename a field on the model. Might affect db_column too."""

    def __init__(self, model_name: str, old_name: str, new_name: str) -> None:
        self.old_name = old_name
        self.new_name = new_name
        super().__init__(model_name, old_name)

    @cached_property
    def old_name_lower(self) -> str:
        return self.old_name.lower()

    @cached_property
    def new_name_lower(self) -> str:
        return self.new_name.lower()

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "old_name": self.old_name,
            "new_name": self.new_name,
        }
        return (self.__class__.__name__, [], kwargs)

    def state_forwards(self, package_label: str, state: Any) -> None:
        state.rename_field(
            package_label, self.model_name_lower, self.old_name, self.new_name
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        to_model = to_state.models_registry.get_model(package_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection, to_model):
            from_model = from_state.models_registry.get_model(
                package_label, self.model_name
            )
            schema_editor.alter_field(
                from_model,
                from_model._model_meta.get_field(self.old_name),
                to_model._model_meta.get_field(self.new_name),
            )

    def describe(self) -> str:
        return f"Rename field {self.old_name} on {self.model_name} to {self.new_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"rename_{self.old_name_lower}_{self.model_name_lower}_{self.new_name_lower}"

    def references_field(self, model_name: str, name: str, package_label: str) -> bool:
        return self.references_model(model_name, package_label) and (
            name.lower() == self.old_name_lower or name.lower() == self.new_name_lower
        )

    def reduce(
        self, operation: Operation, package_label: str
    ) -> list[Operation] | bool:
        if (
            isinstance(operation, RenameField)
            and self.is_same_model_operation(operation)
            and self.new_name_lower == operation.old_name_lower
        ):
            return [
                RenameField(
                    self.model_name,
                    self.old_name,
                    operation.new_name,
                ),
            ]
        # Skip `FieldOperation.reduce` as we want to run `references_field`
        # against self.old_name and self.new_name.
        return super(FieldOperation, self).reduce(operation, package_label) or not (
            operation.references_field(self.model_name, self.old_name, package_label)
            or operation.references_field(self.model_name, self.new_name, package_label)
        )
