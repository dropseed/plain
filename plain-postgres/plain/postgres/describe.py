"""Describe the data model as the registry sees it.

`describe_models()` reads the model registry and returns one
`ModelDescription` per model: its fields, its relations with their target,
on-delete rule and nullability, the relations pointing back at it, and its
constraints and indexes with their conditions compiled to SQL. Nothing here
touches the database.

This is what `plain postgres models` prints. It exists so that the facts a
reader can't reliably derive from a `models.py` by eye (a one-to-one that
lives in a unique constraint, a partial unique that only looks like one, a
reverse accessor's name) come from the framework instead. Views built on
these facts, such as a diagram, belong to whoever reads them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from plain.packages import packages_registry

from .constraints import CheckConstraint, UniqueConstraint
from .ddl import compile_expression_sql, compile_index_expressions_sql
from .exceptions import FieldError
from .fields.primary_key import PrimaryKeyField
from .fields.related import ForeignKeyField, RelatedField
from .fields.reverse_descriptors import BaseReverseDescriptor
from .fields.reverse_related import ManyToManyRel
from .registry import models_registry

if TYPE_CHECKING:
    from .base import Model
    from .query_utils import Q


@dataclass
class FieldDescription:
    name: str
    type: str  # The field class name, e.g. "TextField"
    column: str
    primary_key: bool
    null: bool
    # Effective uniqueness: true when an unconditional, single-field unique
    # constraint covers this field. A partial unique never counts.
    unique: bool


@dataclass
class RelationDescription:
    """A forward relation: a foreign key or many-to-many on this model."""

    name: str
    type: str  # "ForeignKeyField" or "ManyToManyField"
    to: str  # Target model label, e.g. "users.User"
    on_delete: str | None  # "CASCADE", "SET_NULL", "RESTRICT"; None for many-to-many
    null: bool
    unique: bool  # Effective uniqueness, which makes a foreign key one-to-one
    column: str | None  # None for many-to-many
    through: str | None  # The intermediary model label, many-to-many only
    query_name: str  # The name used to filter from the target back to this model


@dataclass
class ReverseDescription:
    """A relation on another model that points at this one."""

    from_model: str  # The pointing model's label
    field: str  # The field on the pointing model
    type: str  # "ForeignKeyField" or "ManyToManyField"
    one_to_one: bool
    query_name: str  # The name used to filter this model by the pointing one
    accessor: str | None  # A declared ReverseForeignKey/ReverseManyToMany, if any

    def to_dict(self) -> dict[str, Any]:
        # Written out rather than `asdict()`: the JSON key is "from", which
        # can't be an attribute name.
        return {
            "from": self.from_model,
            "field": self.field,
            "type": self.type,
            "one_to_one": self.one_to_one,
            "query_name": self.query_name,
            "accessor": self.accessor,
        }


@dataclass
class ConstraintDescription:
    name: str
    kind: str  # "unique" or "check"
    fields: list[str]  # Unique constraints only; empty for expression-based ones
    expressions: list[str]  # Unique constraints over expressions, as SQL
    condition: str | None  # Partial unique: the WHERE clause as SQL
    check: str | None  # Check constraints: the CHECK expression as SQL


@dataclass
class IndexDescription:
    name: str
    fields: list[str]
    expressions: list[str]  # Expression indexes, as SQL
    condition: str | None


@dataclass
class ModelDescription:
    label: str  # "package.ModelName"
    name: str
    package: str
    table: str
    fields: list[FieldDescription]
    relations: list[RelationDescription]
    reverse: list[ReverseDescription]
    constraints: list[ConstraintDescription]
    indexes: list[IndexDescription]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "name": self.name,
            "package": self.package,
            "table": self.table,
            "fields": [asdict(f) for f in self.fields],
            "relations": [asdict(r) for r in self.relations],
            "reverse": [r.to_dict() for r in self.reverse],
            "constraints": [asdict(c) for c in self.constraints],
            "indexes": [asdict(i) for i in self.indexes],
        }


def select_models(
    targets: tuple[str, ...], *, include_packages: bool
) -> list[type[Model]]:
    """Pick the models to describe.

    Each target matches a model by its label (`changes.Thread`), its class
    name (`Thread`), its table (`changes_thread`), or a whole package by
    label (`changes`), none of them case-sensitive, and the models come back
    in the order the targets name them. With no targets, every app model is
    selected in registry order, plus the installed packages' models when
    `include_packages` is set.
    """
    all_models = models_registry.get_models()

    if not targets:
        if include_packages:
            return list(all_models)
        app_package_labels = {
            package_config.package_label
            for package_config in packages_registry.get_package_configs()
            if package_config.is_app
        }
        return [
            model
            for model in all_models
            if model.model_options.package_label in app_package_labels
        ]

    selected: list[type[Model]] = []
    for target in targets:
        target_lower = target.lower()
        matches = [
            model
            for model in all_models
            if model.model_options.label_lower == target_lower
            or model.__name__.lower() == target_lower
            or model.model_options.db_table.lower() == target_lower
            or model.model_options.package_label.lower() == target_lower
        ]
        if not matches:
            raise LookupError(f"No model or package matches {target!r}")
        for model in matches:
            if model not in selected:
                selected.append(model)
    return selected


def describe_models(
    targets: tuple[str, ...] = (), *, include_packages: bool = False
) -> list[ModelDescription]:
    """Describe the selected models (see `select_models`), in that order."""
    return [
        describe_model(model)
        for model in select_models(targets, include_packages=include_packages)
    ]


def describe_model(model: type[Model]) -> ModelDescription:
    options = model.model_options
    meta = model._model_meta
    unique_fields = options.unique_field_names

    fields: list[FieldDescription] = []
    relations: list[RelationDescription] = []
    for model_field in meta.fields:
        if isinstance(model_field, ForeignKeyField):
            relations.append(
                RelationDescription(
                    name=model_field.name,
                    type="ForeignKeyField",
                    to=_label_of(model_field.remote_field.model_ref),
                    on_delete=model_field.remote_field.on_delete.name,
                    null=model_field.allow_null,
                    unique=model_field.name in unique_fields,
                    column=model_field.column,
                    through=None,
                    query_name=model_field.related_query_name(),
                )
            )
        else:
            fields.append(
                FieldDescription(
                    name=model_field.name,
                    type=type(model_field).__name__,
                    column=model_field.column,
                    primary_key=isinstance(model_field, PrimaryKeyField),
                    null=model_field.allow_null,
                    unique=model_field.name in unique_fields,
                )
            )

    for m2m_field in meta.many_to_many:
        relations.append(
            RelationDescription(
                name=m2m_field.name,
                type="ManyToManyField",
                to=_label_of(m2m_field.remote_field.model_ref),
                on_delete=None,
                null=False,
                unique=False,
                column=None,
                through=_label_of(m2m_field.remote_field.through_ref),
                query_name=m2m_field.related_query_name(),
            )
        )

    declared_accessors = _declared_reverse_accessors(model)
    reverse: list[ReverseDescription] = []
    for rel in meta.related_objects:
        pointing_field = rel.field
        pointing_model = pointing_field.model
        is_many_to_many = isinstance(rel, ManyToManyRel)
        reverse.append(
            ReverseDescription(
                from_model=pointing_model.model_options.label,
                field=pointing_field.name,
                type="ManyToManyField" if is_many_to_many else "ForeignKeyField",
                one_to_one=(
                    not is_many_to_many
                    and pointing_field.name
                    in pointing_model.model_options.unique_field_names
                ),
                query_name=rel.name,
                accessor=declared_accessors.get(pointing_field),
            )
        )

    constraints: list[ConstraintDescription] = []
    for constraint in options.constraints:
        if isinstance(constraint, UniqueConstraint):
            constraints.append(
                ConstraintDescription(
                    name=constraint.name,
                    kind="unique",
                    fields=list(constraint.fields),
                    expressions=_compile_expressions(
                        model=model, expressions=constraint.expressions
                    ),
                    condition=_compile_condition(
                        model=model, condition=constraint.condition
                    ),
                    check=None,
                )
            )
        elif isinstance(constraint, CheckConstraint):
            constraints.append(
                ConstraintDescription(
                    name=constraint.name,
                    kind="check",
                    fields=[],
                    expressions=[],
                    condition=None,
                    check=_compile_q(model=model, q=constraint.check),
                )
            )

    indexes = [
        IndexDescription(
            name=index.name,
            fields=list(index.fields),
            expressions=_compile_expressions(
                model=model, expressions=index.expressions
            ),
            condition=_compile_condition(model=model, condition=index.condition),
        )
        for index in options.indexes
    ]

    return ModelDescription(
        label=options.label,
        name=options.object_name,
        package=options.package_label,
        table=options.db_table,
        fields=fields,
        relations=relations,
        reverse=reverse,
        constraints=constraints,
        indexes=indexes,
    )


def _label_of(model_ref: str | type[Model]) -> str:
    """A model's label, or the reference as written when it never resolved.

    A foreign key to a model that doesn't exist (a typo, a package no longer
    installed) keeps its string reference; the description shows it rather
    than failing for every model.
    """
    if isinstance(model_ref, str):
        return model_ref
    return model_ref.model_options.label


def _compile_condition(*, model: type[Model], condition: Q | None) -> str | None:
    """A partial constraint or index condition as SQL, or None when there is none."""
    if condition is None:
        return None
    return _compile_q(model=model, q=condition)


def _compile_q(*, model: type[Model], q: Q) -> str:
    """The expression as SQL, or as written when it can't compile: a
    condition reaching through a relation that never resolved would otherwise
    fail the whole listing."""
    try:
        return compile_expression_sql(model, q)
    except FieldError, TypeError:
        return repr(q)


def _compile_expressions(
    *, model: type[Model], expressions: Sequence[Any]
) -> list[str]:
    """Each index or constraint expression as SQL, parenthesized as in its DDL."""
    return [
        compile_index_expressions_sql(model, (expression,))
        for expression in expressions
    ]


def _declared_reverse_accessors(model: type[Model]) -> dict[RelatedField, str]:
    """Map each pointing field to the ReverseForeignKey/ReverseManyToMany
    attribute declared on `model` for it.

    Every live descriptor sits in the model's own namespace: model setup
    copies inherited ones onto the model before contributing them.
    """
    accessors: dict[RelatedField, str] = {}
    for value in vars(model).values():
        if not isinstance(value, BaseReverseDescriptor):
            continue
        if value.name is None or value.reversed_field is None:
            continue
        accessors[value.reversed_field] = value.name
    return accessors
