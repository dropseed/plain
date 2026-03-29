from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any

from plain import postgres
from plain.postgres.base import ModelBase
from plain.postgres.migrations.operations.base import Operation
from plain.postgres.migrations.state import ModelState
from plain.postgres.migrations.utils import field_references, resolve_relation

from .fields import AddField, AlterField, FieldOperation, RemoveField, RenameField

if TYPE_CHECKING:
    from plain.postgres.fields import Field
    from plain.postgres.migrations.state import ProjectState
    from plain.postgres.schema import DatabaseSchemaEditor


def _check_for_duplicates(arg_name: str, objs: Any) -> None:
    used_vals = set()
    for val in objs:
        if val in used_vals:
            raise ValueError(
                f"Found duplicate value {val} in CreateModel {arg_name} argument."
            )
        used_vals.add(val)


class ModelOperation(Operation):
    def __init__(self, name: str) -> None:
        self.name = name

    @cached_property
    def name_lower(self) -> str:
        return self.name.lower()

    def references_model(self, name: str, package_label: str) -> bool:
        return name.lower() == self.name_lower

    def reduce(
        self, operation: Operation, package_label: str
    ) -> bool | list[Operation]:
        return super().reduce(operation, package_label) or self.can_reduce_through(
            operation, package_label
        )

    def can_reduce_through(self, operation: Operation, package_label: str) -> bool:
        return not operation.references_model(self.name, package_label)


class CreateModel(ModelOperation):
    """Create a model's table."""

    serialization_expand_args = ["fields", "options"]

    def __init__(
        self,
        name: str,
        fields: list[tuple[str, Field]],
        options: dict[str, Any] | None = None,
        bases: tuple[Any, ...] | None = None,
    ) -> None:
        self.fields = fields
        self.options = options or {}
        self.bases = bases or (postgres.Model,)
        super().__init__(name)
        # Sanity-check that there are no duplicated field names or bases
        _check_for_duplicates("fields", (name for name, _ in self.fields))
        _check_for_duplicates(
            "bases",
            (
                base.model_options.label_lower
                if not isinstance(base, str)
                and base is not postgres.Model
                and hasattr(base, "_model_meta")
                else base.lower()
                if isinstance(base, str)
                else base
                for base in self.bases
            ),
        )

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
            "fields": self.fields,
        }
        if self.options:
            kwargs["options"] = self.options
        if self.bases and self.bases != (postgres.Model,):
            kwargs["bases"] = self.bases
        return (self.__class__.__qualname__, (), kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.add_model(
            ModelState(
                package_label,
                self.name,
                list(self.fields),
                dict(self.options),
                tuple(self.bases),
            )
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: DatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = to_state.models_registry.get_model(package_label, self.name)
        schema_editor.create_model(model)

    def describe(self) -> str:
        return f"Create model {self.name}"

    @property
    def migration_name_fragment(self) -> str:
        return self.name_lower

    def references_model(self, name: str, package_label: str) -> bool:
        name_lower = name.lower()
        if name_lower == self.name_lower:
            return True

        # Check we didn't inherit from the model
        reference_model_tuple = (package_label, name_lower)
        for base in self.bases:
            if (
                base is not postgres.Model
                and isinstance(base, ModelBase | str)
                and resolve_relation(base, package_label) == reference_model_tuple
            ):
                return True

        # Check we have no FKs/M2Ms with it
        for _name, field in self.fields:
            if field_references(
                (package_label, self.name_lower), field, reference_model_tuple
            ):
                return True
        return False

    def reduce(
        self, operation: Operation, package_label: str
    ) -> bool | list[Operation]:
        if (
            isinstance(operation, DeleteModel)
            and self.name_lower == operation.name_lower
        ):
            return []
        elif (
            isinstance(operation, RenameModel)
            and self.name_lower == operation.old_name_lower
        ):
            return [
                CreateModel(
                    operation.new_name,
                    fields=self.fields,
                    options=self.options,
                    bases=self.bases,
                ),
            ]
        elif (
            isinstance(operation, AlterModelOptions)
            and self.name_lower == operation.name_lower
        ):
            options = {**self.options, **operation.options}
            for key in operation.ALTER_OPTION_KEYS:
                if key not in operation.options:
                    options.pop(key, None)
            return [
                CreateModel(
                    self.name,
                    fields=self.fields,
                    options=options,
                    bases=self.bases,
                ),
            ]
        elif (
            isinstance(operation, FieldOperation)
            and self.name_lower == operation.model_name_lower
        ):
            if isinstance(operation, AddField):
                assert operation.field is not None
                return [
                    CreateModel(
                        self.name,
                        fields=self.fields + [(operation.name, operation.field)],
                        options=self.options,
                        bases=self.bases,
                    ),
                ]
            elif isinstance(operation, AlterField):
                assert operation.field is not None
                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (n, operation.field if n == operation.name else v)
                            for n, v in self.fields
                        ],
                        options=self.options,
                        bases=self.bases,
                    ),
                ]
            elif isinstance(operation, RemoveField):
                options = self.options.copy()

                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (n, v)
                            for n, v in self.fields
                            if n.lower() != operation.name_lower
                        ],
                        options=options,
                        bases=self.bases,
                    ),
                ]
            elif isinstance(operation, RenameField):
                options = self.options.copy()

                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (operation.new_name if n == operation.old_name else n, v)
                            for n, v in self.fields
                        ],
                        options=options,
                        bases=self.bases,
                    ),
                ]
        return super().reduce(operation, package_label)


class DeleteModel(ModelOperation):
    """Drop a model's table."""

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
        }
        return (self.__class__.__qualname__, (), kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.remove_model(package_label, self.name_lower)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: DatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = from_state.models_registry.get_model(package_label, self.name)
        schema_editor.delete_model(model)

    def references_model(self, name: str, package_label: str) -> bool:
        # The deleted model could be referencing the specified model through
        # related fields.
        return True

    def describe(self) -> str:
        return f"Delete model {self.name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"delete_{self.name_lower}"


class RenameModel(ModelOperation):
    """Rename a model."""

    def __init__(self, old_name: str, new_name: str) -> None:
        self.old_name = old_name
        self.new_name = new_name
        super().__init__(old_name)

    @cached_property
    def old_name_lower(self) -> str:
        return self.old_name.lower()

    @cached_property
    def new_name_lower(self) -> str:
        return self.new_name.lower()

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "old_name": self.old_name,
            "new_name": self.new_name,
        }
        return (self.__class__.__qualname__, (), kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.rename_model(package_label, self.old_name, self.new_name)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: DatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        new_model = to_state.models_registry.get_model(package_label, self.new_name)
        old_model = from_state.models_registry.get_model(package_label, self.old_name)
        # Move the main table
        schema_editor.alter_db_table(
            new_model,
            old_model.model_options.db_table,
            new_model.model_options.db_table,
        )
        # Alter the fields pointing to us
        for related_object in old_model._model_meta.related_objects:
            if related_object.related_model == old_model:
                model = new_model
                related_key = (package_label, self.new_name_lower)
            else:
                model = related_object.related_model
                related_key = (
                    related_object.related_model.model_options.package_label,
                    related_object.related_model.model_options.model_name,
                )
            to_field = to_state.models_registry.get_model(
                *related_key
            )._model_meta.get_forward_field(related_object.field.name)
            schema_editor.alter_field(
                model,
                related_object.field,
                to_field,
            )

    def references_model(self, name: str, package_label: str) -> bool:
        return (
            name.lower() == self.old_name_lower or name.lower() == self.new_name_lower
        )

    def describe(self) -> str:
        return f"Rename model {self.old_name} to {self.new_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"rename_{self.old_name_lower}_{self.new_name_lower}"

    def reduce(
        self, operation: Operation, package_label: str
    ) -> bool | list[Operation]:
        if (
            isinstance(operation, RenameModel)
            and self.new_name_lower == operation.old_name_lower
        ):
            return [
                RenameModel(
                    self.old_name,
                    operation.new_name,
                ),
            ]
        # Skip `ModelOperation.reduce` as we want to run `references_model`
        # against self.new_name.
        return super(ModelOperation, self).reduce(
            operation, package_label
        ) or not operation.references_model(self.new_name, package_label)


class ModelOptionOperation(ModelOperation):
    def reduce(
        self, operation: Operation, package_label: str
    ) -> bool | list[Operation]:
        # Use tuple syntax because self.__class__ is not compatible with union syntax in isinstance
        if isinstance(operation, (self.__class__, DeleteModel)) and (  # noqa: UP038
            self.name_lower == operation.name_lower
        ):
            return [operation]
        return super().reduce(operation, package_label)


class AlterModelTable(ModelOptionOperation):
    """Rename a model's table."""

    def __init__(self, name: str, table: str | None) -> None:
        self.table = table
        super().__init__(name)

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
            "table": self.table,
        }
        return (self.__class__.__qualname__, (), kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.alter_model_options(
            package_label, self.name_lower, {"db_table": self.table}
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: DatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        new_model = to_state.models_registry.get_model(package_label, self.name)
        old_model = from_state.models_registry.get_model(package_label, self.name)
        schema_editor.alter_db_table(
            new_model,
            old_model.model_options.db_table,
            new_model.model_options.db_table,
        )

    def describe(self) -> str:
        return "Rename table for {} to {}".format(
            self.name,
            self.table if self.table is not None else "(default)",
        )

    @property
    def migration_name_fragment(self) -> str:
        return f"alter_{self.name_lower}_table"


class AlterModelOptions(ModelOptionOperation):
    """
    Set new model options that don't directly affect the database schema
    (like ordering). Python code in migrations
    may still need them.
    """

    # Model options we want to compare and preserve in an AlterModelOptions op
    ALTER_OPTION_KEYS = [
        "ordering",
    ]

    def __init__(self, name: str, options: dict[str, Any]) -> None:
        self.options = options
        super().__init__(name)

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
            "options": self.options,
        }
        return (self.__class__.__qualname__, (), kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.alter_model_options(
            package_label,
            self.name_lower,
            self.options,
            self.ALTER_OPTION_KEYS,
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: DatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        pass

    def describe(self) -> str:
        return f"Change Meta options on {self.name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"alter_{self.name_lower}_options"
