from __future__ import annotations

from types import NoneType
from typing import TYPE_CHECKING, Any, Self

from plain.postgres.ddl import (
    build_include_sql,
    compile_expression_sql,
    compile_index_expressions_sql,
)
from plain.postgres.dialect import quote_name
from plain.postgres.expressions import Col, F, Func, OrderBy
from plain.postgres.query_utils import Q
from plain.utils.functional import partition

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.expressions import Expression

__all__ = ["Index"]


class Index:
    suffix = "idx"
    # Postgres identifier limit: NAMEDATALEN - 1 = 63
    max_name_length = 63

    def __init__(
        self,
        *expressions: Any,
        name: str,
        fields: tuple[str, ...] | list[str] = (),
        opclasses: tuple[str, ...] | list[str] = (),
        condition: Q | None = None,
        include: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        if not isinstance(condition, NoneType | Q):
            raise ValueError("Index.condition must be a Q instance.")
        if not isinstance(fields, list | tuple):
            raise ValueError("Index.fields must be a list or tuple.")
        if not isinstance(opclasses, list | tuple):
            raise ValueError("Index.opclasses must be a list or tuple.")
        if not expressions and not fields:
            raise ValueError(
                "At least one field or expression is required to define an index."
            )
        if expressions and fields:
            raise ValueError(
                "Index.fields and expressions are mutually exclusive.",
            )
        if expressions and opclasses:
            raise ValueError(
                "Index.opclasses cannot be used with expressions. Use "
                "a custom OpClass() instead."
            )
        if opclasses and len(fields) != len(opclasses):
            raise ValueError(
                "Index.fields and Index.opclasses must have the same number of "
                "elements."
            )
        if fields and not all(isinstance(field, str) for field in fields):
            raise ValueError("Index.fields must contain only strings with field names.")
        if not isinstance(include, NoneType | list | tuple):
            raise ValueError("Index.include must be a list or tuple.")
        self.fields = list(fields)
        # A list of 2-tuple with the field name and ordering ('' or 'DESC').
        self.fields_orders = [
            (field_name.removeprefix("-"), "DESC" if field_name.startswith("-") else "")
            for field_name in self.fields
        ]
        if not name:
            raise ValueError("Index.name is required.")
        self.name = name
        self.opclasses: tuple[str, ...] = tuple(opclasses)
        self.condition = condition
        self.include = tuple(include) if include else ()
        self.expressions: tuple[Expression, ...] = tuple(  # ty: ignore[invalid-assignment]
            F(expression) if isinstance(expression, str) else expression
            for expression in expressions
        )

    @property
    def contains_expressions(self) -> bool:
        return bool(self.expressions)

    def to_sql(self, model: type[Model]) -> str:
        """Generate CREATE INDEX CONCURRENTLY SQL as a plain string."""
        table = model.model_options.db_table
        condition = (
            compile_expression_sql(model, self.condition)
            if self.condition is not None
            else None
        )

        if self.expressions:
            columns_sql = compile_index_expressions_sql(model, self.expressions)
        else:
            col_parts = []
            for i, (field_name, suffix) in enumerate(self.fields_orders):
                field = model._model_meta.get_forward_field(field_name)
                col = quote_name(field.column)
                if self.opclasses:
                    col = f"{col} {self.opclasses[i]}"
                if suffix:
                    col = f"{col} {suffix}"
                col_parts.append(col)
            columns_sql = ", ".join(col_parts)

        include_sql = build_include_sql(model, self.include)
        name = quote_name(self.name)
        table = quote_name(table)
        condition_sql = f" WHERE ({condition})" if condition else ""
        return f"CREATE INDEX CONCURRENTLY {name} ON {table} ({columns_sql}){include_sql}{condition_sql}"

    def deconstruct(self) -> tuple[str, tuple[Expression, ...], dict[str, Any]]:
        path = f"{self.__class__.__module__}.{self.__class__.__name__}"
        path = path.replace("plain.postgres.indexes", "plain.postgres")
        kwargs = {"name": self.name}
        if self.fields:
            kwargs["fields"] = self.fields
        if self.opclasses:
            kwargs["opclasses"] = self.opclasses
        if self.condition:
            kwargs["condition"] = self.condition
        if self.include:
            kwargs["include"] = self.include
        return (path, self.expressions, kwargs)

    def clone(self) -> Index:
        """Create a copy of this Index."""
        _, args, kwargs = self.deconstruct()
        return self.__class__(*args, **kwargs)

    def __repr__(self) -> str:
        return "<{}:{}{}{}{}{}{}>".format(
            self.__class__.__qualname__,
            "" if not self.fields else f" fields={repr(self.fields)}",
            "" if not self.expressions else f" expressions={repr(self.expressions)}",
            "" if not self.name else f" name={repr(self.name)}",
            "" if self.condition is None else f" condition={self.condition}",
            "" if not self.include else f" include={repr(self.include)}",
            "" if not self.opclasses else f" opclasses={repr(self.opclasses)}",
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Index):
            return self.deconstruct() == other.deconstruct()
        return NotImplemented


class IndexExpression(Func):
    """Order and wrap expressions for CREATE INDEX statements."""

    template = "%(expressions)s"
    wrapper_classes = (OrderBy,)

    def resolve_expression(
        self,
        query: Any = None,
        allow_joins: bool = True,
        reuse: Any = None,
        summarize: bool = False,
        for_save: bool = False,
    ) -> Self:
        expressions = list(self.flatten())
        # Split expressions and wrappers.
        index_expressions, wrappers = partition(
            lambda e: isinstance(e, self.wrapper_classes),
            expressions,
        )
        wrapper_types = [type(wrapper) for wrapper in wrappers]
        if len(wrapper_types) != len(set(wrapper_types)):
            raise ValueError(
                "Multiple references to {} can't be used in an indexed "
                "expression.".format(
                    ", ".join(
                        [
                            wrapper_cls.__qualname__
                            for wrapper_cls in self.wrapper_classes
                        ]
                    )
                )
            )
        if expressions[1 : len(wrappers) + 1] != wrappers:
            raise ValueError(
                "{} must be topmost expressions in an indexed expression.".format(
                    ", ".join(
                        [
                            wrapper_cls.__qualname__
                            for wrapper_cls in self.wrapper_classes
                        ]
                    )
                )
            )
        # Wrap expressions in parentheses if they are not column references.
        root_expression = index_expressions[1]
        resolve_root_expression = root_expression.resolve_expression(
            query,
            allow_joins,
            reuse,
            summarize,
            for_save,
        )
        if not isinstance(resolve_root_expression, Col):
            root_expression = Func(root_expression, template="(%(expressions)s)")

        if wrappers:
            # Order wrappers and set their expressions.
            wrappers = sorted(
                wrappers,
                key=lambda w: self.wrapper_classes.index(type(w)),
            )
            wrappers = [wrapper.copy() for wrapper in wrappers]
            for i, wrapper in enumerate(wrappers[:-1]):
                wrapper.set_source_expressions([wrappers[i + 1]])
            # Set the root expression on the deepest wrapper.
            wrappers[-1].set_source_expressions([root_expression])
            self.set_source_expressions([wrappers[0]])
        else:
            # Use the root expression, if there are no wrappers.
            self.set_source_expressions([root_expression])
        return super().resolve_expression(
            query, allow_joins, reuse, summarize, for_save
        )
