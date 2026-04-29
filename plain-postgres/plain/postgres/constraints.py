from __future__ import annotations

from enum import Enum
from types import NoneType
from typing import TYPE_CHECKING, Any

from plain.exceptions import ValidationError
from plain.postgres.ddl import (
    build_include_sql,
    compile_expression_sql,
    compile_index_expressions_sql,
    deferrable_sql,
)
from plain.postgres.dialect import quote_name
from plain.postgres.exceptions import FieldError
from plain.postgres.expressions import (
    Exists,
    F,
    OrderBy,
    ReplaceableExpression,
)
from plain.postgres.lookups import Exact
from plain.postgres.query_utils import Q

if TYPE_CHECKING:
    from plain.postgres.base import Model

__all__ = ["BaseConstraint", "CheckConstraint", "Deferrable", "UniqueConstraint"]


ViolationError = str | dict[str, Any] | list[Any] | ValidationError


class BaseConstraint:
    violation_error: ViolationError | None = None

    def __init__(
        self,
        *,
        name: str,
        violation_error: ViolationError | None = None,
    ) -> None:
        self.name = name
        self.violation_error = violation_error

    @property
    def contains_expressions(self) -> bool:
        return False

    def to_sql(self, model: type[Model]) -> str:
        raise NotImplementedError(
            "subclasses of BaseConstraint must provide a to_sql() method"
        )

    def validate(
        self, model: type[Model], instance: Model, exclude: set[str] | None = None
    ) -> None:
        raise NotImplementedError(
            "subclasses of BaseConstraint must provide a validate() method"
        )

    def _build_violation_error(self) -> ValidationError:
        if self.violation_error is None:
            return ValidationError(f'Constraint "{self.name}" is violated.')
        if isinstance(self.violation_error, ValidationError):
            return self.violation_error
        return ValidationError(self.violation_error)

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        path = f"{self.__class__.__module__}.{self.__class__.__name__}"
        path = path.replace("plain.postgres.constraints", "plain.postgres")
        kwargs: dict[str, Any] = {"name": self.name}
        if self.violation_error is not None:
            kwargs["violation_error"] = self.violation_error
        return (path, (), kwargs)

    def clone(self) -> BaseConstraint:
        _, args, kwargs = self.deconstruct()
        return self.__class__(*args, **kwargs)


class CheckConstraint(BaseConstraint):
    def __init__(
        self,
        *,
        check: Q,
        name: str,
        violation_error: ViolationError | None = None,
    ) -> None:
        self.check = check
        if not getattr(check, "conditional", False):
            raise TypeError(
                "CheckConstraint.check must be a Q instance or boolean expression."
            )
        super().__init__(name=name, violation_error=violation_error)

    def to_sql(self, model: type[Model], *, not_valid: bool = False) -> str:
        """Generate ALTER TABLE ADD CONSTRAINT CHECK SQL as a plain string."""
        check = compile_expression_sql(model, self.check)
        table = quote_name(model.model_options.db_table)
        name = quote_name(self.name)
        sql = f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check})"
        if not_valid:
            sql += " NOT VALID"
        return sql

    def validate(
        self, model: type[Model], instance: Model, exclude: set[str] | None = None
    ) -> None:
        against = instance._get_field_value_map(meta=model._model_meta, exclude=exclude)
        try:
            if not Q(self.check).check(against):
                raise self._build_violation_error()
        except FieldError:
            pass

    def __repr__(self) -> str:
        return "<{}: check={} name={}{}>".format(
            self.__class__.__qualname__,
            self.check,
            repr(self.name),
            (
                ""
                if self.violation_error is None
                else f" violation_error={self.violation_error!r}"
            ),
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CheckConstraint):
            return (
                self.name == other.name
                and self.check == other.check
                and self.violation_error == other.violation_error
            )
        return super().__eq__(other)

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        path, args, kwargs = super().deconstruct()
        kwargs["check"] = self.check
        return path, args, kwargs


class Deferrable(Enum):
    DEFERRED = "deferred"
    IMMEDIATE = "immediate"

    # A similar format was proposed for Python 3.10.
    def __repr__(self) -> str:
        return f"{self.__class__.__qualname__}.{self._name_}"


class UniqueConstraint(BaseConstraint):
    expressions: tuple[ReplaceableExpression, ...]

    def __init__(
        self,
        *expressions: str | ReplaceableExpression,
        fields: tuple[str, ...] | list[str] = (),
        name: str | None = None,
        condition: Q | None = None,
        deferrable: Deferrable | None = None,
        include: tuple[str, ...] | list[str] | None = None,
        opclasses: tuple[str, ...] | list[str] = (),
        violation_error: ViolationError | None = None,
    ) -> None:
        if not name:
            raise ValueError("A unique constraint must be named.")
        if not expressions and not fields:
            raise ValueError(
                "At least one field or expression is required to define a "
                "unique constraint."
            )
        if expressions and fields:
            raise ValueError(
                "UniqueConstraint.fields and expressions are mutually exclusive."
            )
        if not isinstance(condition, NoneType | Q):
            raise ValueError("UniqueConstraint.condition must be a Q instance.")
        if condition and deferrable:
            raise ValueError("UniqueConstraint with conditions cannot be deferred.")
        if include and deferrable:
            raise ValueError("UniqueConstraint with include fields cannot be deferred.")
        if opclasses and deferrable:
            raise ValueError("UniqueConstraint with opclasses cannot be deferred.")
        if expressions and deferrable:
            raise ValueError("UniqueConstraint with expressions cannot be deferred.")
        if expressions and opclasses:
            raise ValueError(
                "UniqueConstraint.opclasses cannot be used with expressions. "
                "Use a custom OpClass() instead."
            )
        if not isinstance(deferrable, NoneType | Deferrable):
            raise ValueError(
                "UniqueConstraint.deferrable must be a Deferrable instance."
            )
        if not isinstance(include, NoneType | list | tuple):
            raise ValueError("UniqueConstraint.include must be a list or tuple.")
        if not isinstance(opclasses, list | tuple):
            raise ValueError("UniqueConstraint.opclasses must be a list or tuple.")
        if opclasses and len(fields) != len(opclasses):
            raise ValueError(
                "UniqueConstraint.fields and UniqueConstraint.opclasses must "
                "have the same number of elements."
            )
        self.fields = tuple(fields)
        self.condition = condition
        self.deferrable = deferrable
        self.include = tuple(include) if include else ()
        self.opclasses = opclasses
        self.expressions = tuple(
            F(expression) if isinstance(expression, str) else expression
            for expression in expressions
        )
        super().__init__(name=name, violation_error=violation_error)

    @property
    def contains_expressions(self) -> bool:
        return bool(self.expressions)

    @property
    def index_only(self) -> bool:
        """Whether PostgreSQL can only store this as a unique index, not a constraint.

        PostgreSQL rejects ALTER TABLE ADD CONSTRAINT UNIQUE USING INDEX for
        partial indexes, expression indexes, and indexes with non-default
        operator classes.
        """
        return bool(self.condition or self.expressions or self.opclasses)

    def to_sql(self, model: type[Model], *, concurrently: bool = False) -> str:
        """Generate CREATE UNIQUE INDEX or ALTER TABLE ADD CONSTRAINT UNIQUE SQL."""
        table = quote_name(model.model_options.db_table)
        name = quote_name(self.name)
        condition = (
            compile_expression_sql(model, self.condition)
            if self.condition is not None
            else None
        )

        if self.expressions:
            columns_sql = compile_index_expressions_sql(model, self.expressions)
        else:
            col_parts = []
            for i, field_name in enumerate(self.fields):
                field = model._model_meta.get_forward_field(field_name)
                col = quote_name(field.column)
                if self.opclasses:
                    col = f"{col} {self.opclasses[i]}"
                col_parts.append(col)
            columns_sql = ", ".join(col_parts)

        include_sql = build_include_sql(model, self.include)
        condition_sql = f" WHERE ({condition})" if condition else ""

        if concurrently:
            return f"CREATE UNIQUE INDEX CONCURRENTLY {name} ON {table} ({columns_sql}){include_sql}{condition_sql}"
        elif condition or self.include or self.opclasses or self.expressions:
            return f"CREATE UNIQUE INDEX {name} ON {table} ({columns_sql}){include_sql}{condition_sql}"
        else:
            return f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({columns_sql}){deferrable_sql(self.deferrable)}"

    def to_attach_sql(self, model: type[Model]) -> str:
        """Generate ALTER TABLE ADD CONSTRAINT UNIQUE USING INDEX SQL.

        Used after creating the unique index concurrently to attach it
        as a named constraint.
        """
        table = quote_name(model.model_options.db_table)
        name = quote_name(self.name)
        sql = f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE USING INDEX {name}"
        sql += deferrable_sql(self.deferrable)
        return sql

    def __repr__(self) -> str:
        return "<{}:{}{}{}{}{}{}{}{}>".format(
            self.__class__.__qualname__,
            "" if not self.fields else f" fields={repr(self.fields)}",
            "" if not self.expressions else f" expressions={repr(self.expressions)}",
            f" name={repr(self.name)}",
            "" if self.condition is None else f" condition={self.condition}",
            "" if self.deferrable is None else f" deferrable={self.deferrable!r}",
            "" if not self.include else f" include={repr(self.include)}",
            "" if not self.opclasses else f" opclasses={repr(self.opclasses)}",
            (
                ""
                if self.violation_error is None
                else f" violation_error={self.violation_error!r}"
            ),
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, UniqueConstraint):
            return (
                self.name == other.name
                and self.fields == other.fields
                and self.condition == other.condition
                and self.deferrable == other.deferrable
                and self.include == other.include
                and self.opclasses == other.opclasses
                and self.expressions == other.expressions
                and self.violation_error == other.violation_error
            )
        return super().__eq__(other)

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        path, args, kwargs = super().deconstruct()
        if self.fields:
            kwargs["fields"] = self.fields
        if self.condition:
            kwargs["condition"] = self.condition
        if self.deferrable:
            kwargs["deferrable"] = self.deferrable
        if self.include:
            kwargs["include"] = self.include
        if self.opclasses:
            kwargs["opclasses"] = self.opclasses
        return path, self.expressions, kwargs

    def validate(
        self, model: type[Model], instance: Model, exclude: set[str] | None = None
    ) -> None:
        queryset = model.query
        if self.fields:
            lookup_kwargs = {}
            for field_name in self.fields:
                if exclude and field_name in exclude:
                    return
                field = model._model_meta.get_forward_field(field_name)
                lookup_value = getattr(instance, field.attname)
                if lookup_value is None:
                    # A composite constraint containing NULL value cannot cause
                    # a violation since NULL != NULL in SQL.
                    return
                lookup_kwargs[field.name] = lookup_value
            queryset = queryset.filter(**lookup_kwargs)
        else:
            # Ignore constraints with excluded fields.
            if exclude:
                for expression in self.expressions:
                    if hasattr(expression, "flatten"):
                        for expr in expression.flatten():  # ty: ignore[call-non-callable]
                            if isinstance(expr, F) and expr.name in exclude:
                                return
                    elif isinstance(expression, F) and expression.name in exclude:
                        return
            replacements: dict[Any, Any] = {
                F(field): value
                for field, value in instance._get_field_value_map(
                    meta=model._model_meta, exclude=exclude
                ).items()
            }
            expressions = []
            for expr in self.expressions:
                # Ignore ordering.
                if isinstance(expr, OrderBy):
                    expr = expr.expression
                expressions.append(Exact(expr, expr.replace_expressions(replacements)))
            queryset = queryset.filter(*expressions)
        model_class_id = instance.id
        if not instance._state.adding and model_class_id is not None:
            queryset = queryset.exclude(id=model_class_id)
        if not self.condition:
            if queryset.exists():
                raise self._build_unique_violation(instance, model)
        else:
            against = instance._get_field_value_map(
                meta=model._model_meta, exclude=exclude
            )
            try:
                if (self.condition & Exists(queryset.filter(self.condition))).check(
                    against
                ):
                    raise self._build_unique_violation(instance, model)
            except FieldError:
                pass

    def _build_unique_violation(
        self, instance: Model, model: type[Model]
    ) -> ValidationError:
        """Build the ValidationError for a unique violation.

        Single-field unique constraints route the error to that field via the
        dict form so it surfaces under the field rather than NON_FIELD_ERRORS.
        """
        single_field = self.fields[0] if len(self.fields) == 1 else None

        if self.violation_error is not None:
            err = self._build_violation_error()
            # Only auto-route flat errors. A ValidationError that already has
            # an error_dict (from dict-form input or a caller-built instance)
            # already declares its own field routing — don't override it.
            if single_field and not hasattr(err, "error_dict"):
                return ValidationError({single_field: [err]})
            return err

        if self.fields:
            err = instance.unique_error_message(model, self.fields)
            if single_field:
                return ValidationError({single_field: [err]})
            return err
        return ValidationError(f'Constraint "{self.name}" is violated.')
