from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.models.exceptions import FieldError, FullResultSet
from plain.models.expressions import Case, Func, Star, Value, When
from plain.models.fields import IntegerField
from plain.models.functions.comparison import Coalesce
from plain.models.functions.mixins import (
    FixDurationInputMixin,
    NumericOutputFieldMixin,
)

if TYPE_CHECKING:
    from plain.models.expressions import Expression
    from plain.models.query_utils import Q
    from plain.models.sql.compiler import SQLCompiler

__all__ = [
    "Aggregate",
    "Avg",
    "Count",
    "Max",
    "Min",
    "StdDev",
    "Sum",
    "Variance",
]


class Aggregate(Func):
    template = "%(function)s(%(distinct)s%(expressions)s)"
    contains_aggregate = True
    name = None
    filter_template = "%s FILTER (WHERE %%(filter)s)"
    window_compatible = True
    allow_distinct = False
    empty_result_set_value = None

    def __init__(
        self,
        *expressions: Any,
        distinct: bool = False,
        filter: Q | Expression | None = None,
        default: Any = None,
        **extra: Any,
    ) -> None:
        if distinct and not self.allow_distinct:
            raise TypeError(f"{self.__class__.__name__} does not allow distinct.")
        if default is not None and self.empty_result_set_value is not None:
            raise TypeError(f"{self.__class__.__name__} does not allow default.")
        self.distinct = distinct
        self.filter = filter
        self.default = default
        super().__init__(*expressions, **extra)

    def get_source_fields(self) -> list[Any]:
        # Don't return the filter expression since it's not a source field.
        return [e._output_field_or_none for e in super().get_source_expressions()]

    def get_source_expressions(self) -> list[Expression]:
        source_expressions = super().get_source_expressions()
        if self.filter:
            return source_expressions + [self.filter]
        return source_expressions

    def set_source_expressions(self, exprs: list[Expression]) -> list[Expression]:
        self.filter = self.filter and exprs.pop()
        return super().set_source_expressions(exprs)

    def resolve_expression(
        self,
        query: Any = None,
        allow_joins: bool = True,
        reuse: Any = None,
        summarize: bool = False,
        for_save: bool = False,
    ) -> Expression:
        # Aggregates are not allowed in UPDATE queries, so ignore for_save
        c = super().resolve_expression(query, allow_joins, reuse, summarize)
        c.filter = c.filter and c.filter.resolve_expression(
            query, allow_joins, reuse, summarize
        )
        if not summarize:
            # Call Aggregate.get_source_expressions() to avoid
            # returning self.filter and including that in this loop.
            expressions = super(Aggregate, c).get_source_expressions()
            for index, expr in enumerate(expressions):
                if expr.contains_aggregate:
                    before_resolved = self.get_source_expressions()[index]
                    name = (
                        before_resolved.name
                        if hasattr(before_resolved, "name")
                        else repr(before_resolved)
                    )
                    raise FieldError(
                        f"Cannot compute {c.name}('{name}'): '{name}' is an aggregate"
                    )
        if (default := c.default) is None:
            return c
        if hasattr(default, "resolve_expression"):
            default = default.resolve_expression(query, allow_joins, reuse, summarize)
            if default._output_field_or_none is None:
                default.output_field = c._output_field_or_none
        else:
            default = Value(default, c._output_field_or_none)
        c.default = None  # Reset the default argument before wrapping.
        coalesce = Coalesce(c, default, output_field=c._output_field_or_none)
        coalesce.is_summary = c.is_summary
        return coalesce

    @property
    def default_alias(self) -> str:
        expressions = self.get_source_expressions()
        if len(expressions) == 1 and hasattr(expressions[0], "name"):
            return f"{expressions[0].name}__{self.name.lower()}"
        raise TypeError("Complex expressions require an alias")

    def get_group_by_cols(self) -> list[Any]:
        return []

    def as_sql(
        self, compiler: SQLCompiler, connection: Any, **extra_context: Any
    ) -> tuple[str, tuple[Any, ...]]:
        extra_context["distinct"] = "DISTINCT " if self.distinct else ""
        if self.filter:
            if connection.features.supports_aggregate_filter_clause:
                try:
                    filter_sql, filter_params = self.filter.as_sql(compiler, connection)
                except FullResultSet:
                    pass
                else:
                    template = self.filter_template % extra_context.get(
                        "template", self.template
                    )
                    sql, params = super().as_sql(
                        compiler,
                        connection,
                        template=template,
                        filter=filter_sql,
                        **extra_context,
                    )
                    return sql, (*params, *filter_params)
            else:
                copy = self.copy()
                copy.filter = None
                source_expressions = copy.get_source_expressions()
                condition = When(self.filter, then=source_expressions[0])
                copy.set_source_expressions([Case(condition)] + source_expressions[1:])
                return super(Aggregate, copy).as_sql(
                    compiler, connection, **extra_context
                )
        return super().as_sql(compiler, connection, **extra_context)

    def _get_repr_options(self) -> dict[str, Any]:
        options = super()._get_repr_options()
        if self.distinct:
            options["distinct"] = self.distinct
        if self.filter:
            options["filter"] = self.filter
        return options


class Avg(FixDurationInputMixin, NumericOutputFieldMixin, Aggregate):
    function = "AVG"
    name = "Avg"
    allow_distinct = True


class Count(Aggregate):
    function = "COUNT"
    name = "Count"
    output_field = IntegerField()
    allow_distinct = True
    empty_result_set_value = 0

    def __init__(
        self, expression: Any, filter: Q | Expression | None = None, **extra: Any
    ) -> None:
        if expression == "*":
            expression = Star()
        if isinstance(expression, Star) and filter is not None:
            raise ValueError("Star cannot be used with filter. Please specify a field.")
        super().__init__(expression, filter=filter, **extra)


class Max(Aggregate):
    function = "MAX"
    name = "Max"


class Min(Aggregate):
    function = "MIN"
    name = "Min"


class StdDev(NumericOutputFieldMixin, Aggregate):
    name = "StdDev"

    def __init__(self, expression: Any, sample: bool = False, **extra: Any) -> None:
        self.function = "STDDEV_SAMP" if sample else "STDDEV_POP"
        super().__init__(expression, **extra)

    def _get_repr_options(self) -> dict[str, Any]:
        return {**super()._get_repr_options(), "sample": self.function == "STDDEV_SAMP"}


class Sum(FixDurationInputMixin, Aggregate):
    function = "SUM"
    name = "Sum"
    allow_distinct = True


class Variance(NumericOutputFieldMixin, Aggregate):
    name = "Variance"

    def __init__(self, expression: Any, sample: bool = False, **extra: Any) -> None:
        self.function = "VAR_SAMP" if sample else "VAR_POP"
        super().__init__(expression, **extra)

    def _get_repr_options(self) -> dict[str, Any]:
        return {**super()._get_repr_options(), "sample": self.function == "VAR_SAMP"}
