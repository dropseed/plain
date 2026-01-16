from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from plain.models.expressions import Func
from plain.models.fields import DecimalField, Field, FloatField, IntegerField
from plain.models.functions import Cast

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.sql.compiler import SQLCompiler


class FixDecimalInputMixin(Func):
    """
    Mixin for Func subclasses that need to convert FloatField to DecimalField.

    PostgreSQL doesn't support the following function signatures:
    - LOG(double, double)
    - MOD(double, double)
    """

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        function: str | None = None,
        template: str | None = None,
        arg_joiner: str | None = None,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
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
        return super(FixDecimalInputMixin, clone).as_sql(
            compiler, connection, **extra_context
        )


class NumericOutputFieldMixin(Func):
    def _resolve_output_field(self) -> DecimalField | FloatField | Field:
        source_fields = self.get_source_fields()
        if any(isinstance(s, DecimalField) for s in source_fields):
            return DecimalField()
        if any(isinstance(s, IntegerField) for s in source_fields):
            return FloatField()
        if source_fields:
            if result := super()._resolve_output_field():
                return result
        return FloatField()
