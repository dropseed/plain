"""Database functions that do comparisons or type conversions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.models.expressions import Func, Value
from plain.models.fields import Field, TextField
from plain.models.fields.json import JSONField
from plain.utils.regex_helper import _lazy_re_compile

if TYPE_CHECKING:
    from plain.models.backends.wrapper import DatabaseWrapper
    from plain.models.sql.compiler import SQLCompiler


class Cast(Func):
    """Coerce an expression to a new field type."""

    function = "CAST"
    # PostgreSQL :: shortcut syntax is more readable than standard CAST().
    template = "(%(expressions)s)::%(db_type)s"

    def __init__(self, expression: Any, output_field: Field) -> None:
        super().__init__(expression, output_field=output_field)

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: DatabaseWrapper,
        function: str | None = None,
        template: str | None = None,
        arg_joiner: str | None = None,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
        extra_context["db_type"] = self.output_field.cast_db_type(connection)
        return super().as_sql(
            compiler, connection, function, template, arg_joiner, **extra_context
        )


class Coalesce(Func):
    """Return, from left to right, the first non-null expression."""

    function = "COALESCE"

    def __init__(self, *expressions: Any, **extra: Any) -> None:
        if len(expressions) < 2:
            raise ValueError("Coalesce must take at least two expressions")
        super().__init__(*expressions, **extra)

    @property
    def empty_result_set_value(self) -> Any:
        for expression in self.get_source_expressions():
            result = expression.empty_result_set_value
            if result is NotImplemented or result is not None:
                return result
        return None


class Collate(Func):
    function = "COLLATE"
    template = "%(expressions)s %(function)s %(collation)s"
    # Inspired from
    # https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS
    collation_re = _lazy_re_compile(r"^[\w\-]+$")

    def __init__(self, expression: Any, collation: str) -> None:
        if not (collation and self.collation_re.match(collation)):
            raise ValueError(f"Invalid collation name: {collation!r}.")
        self.collation = collation
        super().__init__(expression)

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: DatabaseWrapper,
        function: str | None = None,
        template: str | None = None,
        arg_joiner: str | None = None,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
        extra_context.setdefault("collation", connection.ops.quote_name(self.collation))
        return super().as_sql(
            compiler, connection, function, template, arg_joiner, **extra_context
        )


class Greatest(Func):
    """
    Return the maximum expression.

    If any expression is null the return value is database-specific:
    On PostgreSQL, the maximum not-null expression is returned.
    """

    function = "GREATEST"

    def __init__(self, *expressions: Any, **extra: Any) -> None:
        if len(expressions) < 2:
            raise ValueError("Greatest must take at least two expressions")
        super().__init__(*expressions, **extra)


class JSONObject(Func):
    # PostgreSQL uses JSONB_BUILD_OBJECT for JSON object construction.
    function = "JSONB_BUILD_OBJECT"
    output_field = JSONField()

    def __init__(self, **fields: Any) -> None:
        expressions = []
        for key, value in fields.items():
            expressions.extend((Value(key), value))
        super().__init__(*expressions)

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: DatabaseWrapper,
        function: str | None = None,
        template: str | None = None,
        arg_joiner: str | None = None,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
        # PostgreSQL requires keys to be cast to text.
        copy = self.copy()
        copy.set_source_expressions(
            [
                Cast(expression, TextField()) if index % 2 == 0 else expression
                for index, expression in enumerate(copy.get_source_expressions())
            ]
        )
        return super(JSONObject, copy).as_sql(
            compiler, connection, function, template, arg_joiner, **extra_context
        )


class Least(Func):
    """
    Return the minimum expression.

    If any expression is null the return value is database-specific:
    On PostgreSQL, return the minimum not-null expression.
    """

    function = "LEAST"

    def __init__(self, *expressions: Any, **extra: Any) -> None:
        if len(expressions) < 2:
            raise ValueError("Least must take at least two expressions")
        super().__init__(*expressions, **extra)


class NullIf(Func):
    function = "NULLIF"
    arity = 2
