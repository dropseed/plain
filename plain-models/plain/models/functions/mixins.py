from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from plain.models.fields import DecimalField, FloatField, IntegerField
from plain.models.functions import Cast

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.sql.compiler import SQLCompiler


class FixDecimalInputMixin:
    def as_postgresql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        # Cast FloatField to DecimalField as PostgreSQL doesn't support the
        # following function signatures:
        # - LOG(double, double)
        # - MOD(double, double)
        output_field = DecimalField(decimal_places=sys.float_info.dig, max_digits=1000)
        clone = self.copy()
        clone.set_source_expressions(
            [
                Cast(expression, output_field)
                if isinstance(expression.output_field, FloatField)
                else expression
                for expression in self.get_source_expressions()
            ]
        )
        return clone.as_sql(compiler, connection, **extra_context)


class FixDurationInputMixin:
    def as_mysql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        sql, params = super().as_sql(compiler, connection, **extra_context)  # type: ignore[misc]
        if self.output_field.get_internal_type() == "DurationField":  # type: ignore[attr-defined]
            sql = f"CAST({sql} AS SIGNED)"
        return sql, params


class NumericOutputFieldMixin:
    def _resolve_output_field(self) -> DecimalField | FloatField:
        source_fields = self.get_source_fields()  # type: ignore[attr-defined]
        if any(isinstance(s, DecimalField) for s in source_fields):
            return DecimalField()
        if any(isinstance(s, IntegerField) for s in source_fields):
            return FloatField()
        return super()._resolve_output_field() if source_fields else FloatField()  # type: ignore[misc]
