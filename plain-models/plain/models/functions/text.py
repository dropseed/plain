from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.models.expressions import Func, Value
from plain.models.fields import CharField, IntegerField, TextField
from plain.models.functions import Cast, Coalesce
from plain.models.lookups import Transform

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.sql.compiler import SQLCompiler


class MySQLSHA2Mixin:
    def as_mysql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(  # type: ignore[misc]
            compiler,
            connection,
            template=f"SHA2(%(expressions)s, {self.function[3:]})",
            **extra_context,
        )


class PostgreSQLSHAMixin:
    def as_postgresql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(  # type: ignore[misc]
            compiler,
            connection,
            template="ENCODE(DIGEST(%(expressions)s, '%(function)s'), 'hex')",
            function=self.function.lower(),
            **extra_context,
        )


class Chr(Transform):
    function = "CHR"
    lookup_name = "chr"

    def as_mysql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(
            compiler,
            connection,
            function="CHAR",
            template="%(function)s(%(expressions)s USING utf16)",
            **extra_context,
        )

    def as_sqlite(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(compiler, connection, function="CHAR", **extra_context)


class ConcatPair(Func):
    """
    Concatenate two arguments together. This is used by `Concat` because not
    all backend databases support more than two arguments.
    """

    function = "CONCAT"

    def as_sqlite(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        coalesced = self.coalesce()
        return super(ConcatPair, coalesced).as_sql(
            compiler,
            connection,
            template="%(expressions)s",
            arg_joiner=" || ",
            **extra_context,
        )

    def as_postgresql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        copy = self.copy()
        copy.set_source_expressions(
            [
                Cast(expression, TextField())
                for expression in copy.get_source_expressions()
            ]
        )
        return super(ConcatPair, copy).as_sql(
            compiler,
            connection,
            **extra_context,
        )

    def as_mysql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        # Use CONCAT_WS with an empty separator so that NULLs are ignored.
        return super().as_sql(
            compiler,
            connection,
            function="CONCAT_WS",
            template="%(function)s('', %(expressions)s)",
            **extra_context,
        )

    def coalesce(self) -> ConcatPair:
        # null on either side results in null for expression, wrap with coalesce
        c = self.copy()
        c.set_source_expressions(
            [
                Coalesce(expression, Value(""))
                for expression in c.get_source_expressions()
            ]
        )
        return c


class Concat(Func):
    """
    Concatenate text fields together. Backends that result in an entire
    null expression when any arguments are null will wrap each argument in
    coalesce functions to ensure a non-null result.
    """

    function = None
    template = "%(expressions)s"

    def __init__(self, *expressions: Any, **extra: Any) -> None:
        if len(expressions) < 2:
            raise ValueError("Concat must take at least two expressions")
        paired = self._paired(expressions)
        super().__init__(paired, **extra)

    def _paired(self, expressions: tuple[Any, ...]) -> ConcatPair:
        # wrap pairs of expressions in successive concat functions
        # exp = [a, b, c, d]
        # -> ConcatPair(a, ConcatPair(b, ConcatPair(c, d))))
        if len(expressions) == 2:
            return ConcatPair(*expressions)
        return ConcatPair(expressions[0], self._paired(expressions[1:]))


class Left(Func):
    function = "LEFT"
    arity = 2
    output_field = CharField()

    def __init__(self, expression: Any, length: Any, **extra: Any) -> None:
        """
        expression: the name of a field, or an expression returning a string
        length: the number of characters to return from the start of the string
        """
        if not hasattr(length, "resolve_expression"):
            if length < 1:
                raise ValueError("'length' must be greater than 0.")
        super().__init__(expression, length, **extra)

    def get_substr(self) -> Substr:
        return Substr(self.source_expressions[0], Value(1), self.source_expressions[1])

    def as_sqlite(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return self.get_substr().as_sqlite(compiler, connection, **extra_context)


class Length(Transform):
    """Return the number of characters in the expression."""

    function = "LENGTH"
    lookup_name = "length"
    output_field = IntegerField()

    def as_mysql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(
            compiler, connection, function="CHAR_LENGTH", **extra_context
        )


class Lower(Transform):
    function = "LOWER"
    lookup_name = "lower"


class LPad(Func):
    function = "LPAD"
    output_field = CharField()

    def __init__(
        self, expression: Any, length: Any, fill_text: Any = Value(" "), **extra: Any
    ) -> None:
        if (
            not hasattr(length, "resolve_expression")
            and length is not None
            and length < 0
        ):
            raise ValueError("'length' must be greater or equal to 0.")
        super().__init__(expression, length, fill_text, **extra)


class LTrim(Transform):
    function = "LTRIM"
    lookup_name = "ltrim"


class MD5(Transform):
    function = "MD5"
    lookup_name = "md5"


class Ord(Transform):
    function = "ASCII"
    lookup_name = "ord"
    output_field = IntegerField()

    def as_mysql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(compiler, connection, function="ORD", **extra_context)

    def as_sqlite(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(compiler, connection, function="UNICODE", **extra_context)


class Repeat(Func):
    function = "REPEAT"
    output_field = CharField()

    def __init__(self, expression: Any, number: Any, **extra: Any) -> None:
        if (
            not hasattr(number, "resolve_expression")
            and number is not None
            and number < 0
        ):
            raise ValueError("'number' must be greater or equal to 0.")
        super().__init__(expression, number, **extra)


class Replace(Func):
    function = "REPLACE"

    def __init__(
        self, expression: Any, text: Any, replacement: Any = Value(""), **extra: Any
    ) -> None:
        super().__init__(expression, text, replacement, **extra)


class Reverse(Transform):
    function = "REVERSE"
    lookup_name = "reverse"


class Right(Left):
    function = "RIGHT"

    def get_substr(self) -> Substr:
        return Substr(
            self.source_expressions[0], self.source_expressions[1] * Value(-1)
        )


class RPad(LPad):
    function = "RPAD"


class RTrim(Transform):
    function = "RTRIM"
    lookup_name = "rtrim"


class SHA1(PostgreSQLSHAMixin, Transform):
    function = "SHA1"
    lookup_name = "sha1"


class SHA224(MySQLSHA2Mixin, PostgreSQLSHAMixin, Transform):
    function = "SHA224"
    lookup_name = "sha224"


class SHA256(MySQLSHA2Mixin, PostgreSQLSHAMixin, Transform):
    function = "SHA256"
    lookup_name = "sha256"


class SHA384(MySQLSHA2Mixin, PostgreSQLSHAMixin, Transform):
    function = "SHA384"
    lookup_name = "sha384"


class SHA512(MySQLSHA2Mixin, PostgreSQLSHAMixin, Transform):
    function = "SHA512"
    lookup_name = "sha512"


class StrIndex(Func):
    """
    Return a positive integer corresponding to the 1-indexed position of the
    first occurrence of a substring inside another string, or 0 if the
    substring is not found.
    """

    function = "INSTR"
    arity = 2
    output_field = IntegerField()

    def as_postgresql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(compiler, connection, function="STRPOS", **extra_context)


class Substr(Func):
    function = "SUBSTRING"
    output_field = CharField()

    def __init__(
        self, expression: Any, pos: Any, length: Any = None, **extra: Any
    ) -> None:
        """
        expression: the name of a field, or an expression returning a string
        pos: an integer > 0, or an expression returning an integer
        length: an optional number of characters to return
        """
        if not hasattr(pos, "resolve_expression"):
            if pos < 1:
                raise ValueError("'pos' must be greater than 0")
        expressions = [expression, pos]
        if length is not None:
            expressions.append(length)
        super().__init__(*expressions, **extra)

    def as_sqlite(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, tuple[Any, ...]]:
        return super().as_sql(compiler, connection, function="SUBSTR", **extra_context)


class Trim(Transform):
    function = "TRIM"
    lookup_name = "trim"


class Upper(Transform):
    function = "UPPER"
    lookup_name = "upper"
