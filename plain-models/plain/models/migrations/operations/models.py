from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any

from plain import models
from plain.models.base import ModelBase
from plain.models.migrations.operations.base import Operation
from plain.models.migrations.state import ModelState
from plain.models.migrations.utils import field_references, resolve_relation

from .fields import AddField, AlterField, FieldOperation, RemoveField, RenameField

if TYPE_CHECKING:
    from plain.models.backends.base.schema import BaseDatabaseSchemaEditor
    from plain.models.fields import Field
    from plain.models.migrations.state import ProjectState


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
        return super().reduce(operation, package_label) or self.can_reduce_through(  # type: ignore[misc]
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
        self.bases = bases or (models.Model,)
        super().__init__(name)
        # Sanity-check that there are no duplicated field names or bases
        _check_for_duplicates("fields", (name for name, _ in self.fields))
        _check_for_duplicates(
            "bases",
            (
                base.model_options.label_lower
                if not isinstance(base, str)
                and base is not models.Model
                and hasattr(base, "_model_meta")
                else base.lower()
                if isinstance(base, str)
                else base
                for base in self.bases
            ),
        )

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
            "fields": self.fields,
        }
        if self.options:
            kwargs["options"] = self.options
        if self.bases and self.bases != (models.Model,):
            kwargs["bases"] = self.bases
        return (self.__class__.__qualname__, [], kwargs)

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
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = to_state.models_registry.get_model(package_label, self.name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, model):
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
                base is not models.Model
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
                return [
                    CreateModel(
                        self.name,
                        fields=self.fields + [(operation.name, operation.field)],
                        options=self.options,
                        bases=self.bases,
                    ),
                ]
            elif isinstance(operation, AlterField):
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

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.remove_model(package_label, self.name_lower)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = from_state.models_registry.get_model(package_label, self.name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, model):
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

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "old_name": self.old_name,
            "new_name": self.new_name,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.rename_model(package_label, self.old_name, self.new_name)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        new_model = to_state.models_registry.get_model(package_label, self.new_name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, new_model):
            old_model = from_state.models_registry.get_model(  # type: ignore[attr-defined]
                package_label, self.old_name
            )
            # Move the main table
            schema_editor.alter_db_table(
                new_model,
                old_model.model_options.db_table,
                new_model.model_options.db_table,
            )
            # Alter the fields pointing to us
            for related_object in old_model._model_meta.related_objects:
                if related_object.related_model == old_model:  # type: ignore[attr-defined]
                    model = new_model
                    related_key = (package_label, self.new_name_lower)
                else:
                    model = related_object.related_model  # type: ignore[attr-defined]
                    related_key = (
                        related_object.related_model.model_options.package_label,
                        related_object.related_model.model_options.model_name,
                    )
                to_field = to_state.models_registry.get_model(
                    *related_key
                )._model_meta.get_field(related_object.field.name)
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
        return super(ModelOperation, self).reduce(  # type: ignore[misc]
            operation, package_label
        ) or not operation.references_model(self.new_name, package_label)


class ModelOptionOperation(ModelOperation):
    def reduce(
        self, operation: Operation, package_label: str
    ) -> bool | list[Operation]:
        if (
            isinstance(operation, self.__class__ | DeleteModel)
            and self.name_lower == operation.name_lower
        ):
            return [operation]
        return super().reduce(operation, package_label)


class AlterModelTable(ModelOptionOperation):
    """Rename a model's table."""

    def __init__(self, name: str, table: str | None) -> None:
        self.table = table
        super().__init__(name)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
            "table": self.table,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.alter_model_options(
            package_label, self.name_lower, {"db_table": self.table}
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        new_model = to_state.models_registry.get_model(package_label, self.name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, new_model):
            old_model = from_state.models_registry.get_model(package_label, self.name)  # type: ignore[attr-defined]
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


class AlterModelTableComment(ModelOptionOperation):
    def __init__(self, name: str, table_comment: str | None) -> None:
        self.table_comment = table_comment
        super().__init__(name)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
            "table_comment": self.table_comment,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.alter_model_options(
            package_label, self.name_lower, {"db_table_comment": self.table_comment}
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        new_model = to_state.models_registry.get_model(package_label, self.name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, new_model):
            old_model = from_state.models_registry.get_model(package_label, self.name)  # type: ignore[attr-defined]
            schema_editor.alter_db_table_comment(
                new_model,
                old_model.model_options.db_table_comment,
                new_model.model_options.db_table_comment,
            )

    def describe(self) -> str:
        return f"Alter {self.name} table comment"

    @property
    def migration_name_fragment(self) -> str:
        return f"alter_{self.name_lower}_table_comment"


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

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "name": self.name,
            "options": self.options,
        }
        return (self.__class__.__qualname__, [], kwargs)

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
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        pass

    def describe(self) -> str:
        return f"Change Meta options on {self.name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"alter_{self.name_lower}_options"


class IndexOperation(Operation):
    option_name = "indexes"

    @cached_property
    def model_name_lower(self) -> str:
        return self.model_name.lower()  # type: ignore[attr-defined]


class AddIndex(IndexOperation):
    """Add an index on a model."""

    def __init__(self, model_name: str, index: Any) -> None:
        self.model_name = model_name
        if not index.name:  # type: ignore[attr-defined]
            raise ValueError(
                "Indexes passed to AddIndex operations require a name "
                f"argument. {index!r} doesn't have one."
            )
        self.index = index

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.add_index(package_label, self.model_name_lower, self.index)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = to_state.models_registry.get_model(package_label, self.model_name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, model):
            schema_editor.add_index(model, self.index)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "index": self.index,
        }
        return (
            self.__class__.__qualname__,
            [],
            kwargs,
        )

    def describe(self) -> str:
        if self.index.expressions:  # type: ignore[attr-defined]
            return "Create index {} on {} on model {}".format(
                self.index.name,  # type: ignore[attr-defined]
                ", ".join([str(expression) for expression in self.index.expressions]),  # type: ignore[attr-defined]
                self.model_name,
            )
        return "Create index {} on field(s) {} of model {}".format(
            self.index.name,  # type: ignore[attr-defined]
            ", ".join(self.index.fields),  # type: ignore[attr-defined]
            self.model_name,
        )

    @property
    def migration_name_fragment(self) -> str:
        return f"{self.model_name_lower}_{self.index.name.lower()}"  # type: ignore[attr-defined]


class RemoveIndex(IndexOperation):
    """Remove an index from a model."""

    def __init__(self, model_name: str, name: str) -> None:
        self.model_name = model_name
        self.name = name

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.remove_index(package_label, self.model_name_lower, self.name)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = from_state.models_registry.get_model(package_label, self.model_name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, model):
            from_model_state = from_state.models[package_label, self.model_name_lower]
            index = from_model_state.get_index_by_name(self.name)
            schema_editor.remove_index(model, index)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "name": self.name,
        }
        return (
            self.__class__.__qualname__,
            [],
            kwargs,
        )

    def describe(self) -> str:
        return f"Remove index {self.name} from {self.model_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"remove_{self.model_name_lower}_{self.name.lower()}"


class RenameIndex(IndexOperation):
    """Rename an index."""

    def __init__(
        self,
        model_name: str,
        new_name: str,
        old_name: str | None = None,
        old_fields: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        if not old_name and not old_fields:
            raise ValueError(
                "RenameIndex requires one of old_name and old_fields arguments to be "
                "set."
            )
        if old_name and old_fields:
            raise ValueError(
                "RenameIndex.old_name and old_fields are mutually exclusive."
            )
        self.model_name = model_name
        self.new_name = new_name
        self.old_name = old_name
        self.old_fields = old_fields

    @cached_property
    def old_name_lower(self) -> str:
        return self.old_name.lower()  # type: ignore[union-attr]

    @cached_property
    def new_name_lower(self) -> str:
        return self.new_name.lower()

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "new_name": self.new_name,
        }
        if self.old_name:
            kwargs["old_name"] = self.old_name
        if self.old_fields:
            kwargs["old_fields"] = self.old_fields
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        if self.old_fields:
            state.add_index(
                package_label,
                self.model_name_lower,
                models.Index(fields=self.old_fields, name=self.new_name),
            )
        else:
            state.rename_index(
                package_label,
                self.model_name_lower,
                self.old_name,
                self.new_name,  # type: ignore[arg-type]
            )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = to_state.models_registry.get_model(package_label, self.model_name)  # type: ignore[attr-defined]
        if not self.allow_migrate_model(schema_editor.connection, model):
            return None

        if self.old_fields:
            from_model = from_state.models_registry.get_model(  # type: ignore[attr-defined]
                package_label, self.model_name
            )
            columns = [
                from_model._model_meta.get_field(field).column
                for field in self.old_fields
            ]
            matching_index_name = schema_editor._constraint_names(
                from_model, column_names=columns, index=True
            )
            if len(matching_index_name) != 1:
                raise ValueError(
                    "Found wrong number ({}) of indexes for {}({}).".format(
                        len(matching_index_name),
                        from_model.model_options.db_table,
                        ", ".join(columns),
                    )
                )
            old_index = models.Index(
                fields=self.old_fields,
                name=matching_index_name[0],
            )
        else:
            from_model_state = from_state.models[package_label, self.model_name_lower]
            old_index = from_model_state.get_index_by_name(self.old_name)  # type: ignore[arg-type]
        # Don't alter when the index name is not changed.
        if old_index.name == self.new_name:  # type: ignore[attr-defined]
            return None

        to_model_state = to_state.models[package_label, self.model_name_lower]
        new_index = to_model_state.get_index_by_name(self.new_name)
        schema_editor.rename_index(model, old_index, new_index)
        return None

    def describe(self) -> str:
        if self.old_name:
            return (
                f"Rename index {self.old_name} on {self.model_name} to {self.new_name}"
            )
        return (
            f"Rename unnamed index for {self.old_fields} on {self.model_name} to "
            f"{self.new_name}"
        )

    @property
    def migration_name_fragment(self) -> str:
        if self.old_name:
            return f"rename_{self.old_name_lower}_{self.new_name_lower}"
        return "rename_{}_{}_{}".format(
            self.model_name_lower,
            "_".join(self.old_fields),  # type: ignore[arg-type]
            self.new_name_lower,
        )

    def reduce(
        self, operation: Operation, package_label: str
    ) -> bool | list[Operation]:
        if (
            isinstance(operation, RenameIndex)
            and self.model_name_lower == operation.model_name_lower
            and operation.old_name
            and self.new_name_lower == operation.old_name_lower
        ):
            return [
                RenameIndex(
                    self.model_name,
                    new_name=operation.new_name,
                    old_name=self.old_name,
                    old_fields=self.old_fields,
                )
            ]
        return super().reduce(operation, package_label)


class AddConstraint(IndexOperation):
    option_name = "constraints"

    def __init__(self, model_name: str, constraint: Any) -> None:
        self.model_name = model_name
        self.constraint = constraint

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.add_constraint(package_label, self.model_name_lower, self.constraint)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = to_state.models_registry.get_model(package_label, self.model_name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, model):
            schema_editor.add_constraint(model, self.constraint)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        return (
            self.__class__.__name__,
            [],
            {
                "model_name": self.model_name,
                "constraint": self.constraint,
            },
        )

    def describe(self) -> str:
        return f"Create constraint {self.constraint.name} on model {self.model_name}"  # type: ignore[attr-defined]

    @property
    def migration_name_fragment(self) -> str:
        return f"{self.model_name_lower}_{self.constraint.name.lower()}"  # type: ignore[attr-defined]


class RemoveConstraint(IndexOperation):
    option_name = "constraints"

    def __init__(self, model_name: str, name: str) -> None:
        self.model_name = model_name
        self.name = name

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        state.remove_constraint(package_label, self.model_name_lower, self.name)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        model = to_state.models_registry.get_model(package_label, self.model_name)  # type: ignore[attr-defined]
        if self.allow_migrate_model(schema_editor.connection, model):
            from_model_state = from_state.models[package_label, self.model_name_lower]
            constraint = from_model_state.get_constraint_by_name(self.name)
            schema_editor.remove_constraint(model, constraint)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        return (
            self.__class__.__name__,
            [],
            {
                "model_name": self.model_name,
                "name": self.name,
            },
        )

    def describe(self) -> str:
        return f"Remove constraint {self.name} from model {self.model_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"remove_{self.model_name_lower}_{self.name.lower()}"
