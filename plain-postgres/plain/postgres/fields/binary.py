from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import psycopg

from plain.validators import MaxLengthValidator

from .base import ColumnField

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.sql.compiler import SQLCompiler


class BinaryField(ColumnField[bytes | memoryview]):
    db_type_sql = "bytea"
    empty_values = [None, b""]
    _default_empty_value = b""

    def __init__(
        self,
        *,
        max_length: int | None = None,
        required: bool = True,
        allow_null: bool = False,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        # `default` is intentionally not accepted: a str default on a bytes
        # field is a type mismatch.
        self.max_length = max_length
        super().__init__(
            required=required,
            allow_null=allow_null,
            validators=validators,
        )
        if self.max_length is not None:
            self.validators.append(MaxLengthValidator(self.max_length))

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.max_length is not None:
            kwargs["max_length"] = self.max_length
        return name, path, args, kwargs

    def get_placeholder(
        self, value: Any, compiler: SQLCompiler, connection: DatabaseConnection
    ) -> Any:
        return "%s"

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        value = super().get_db_prep_value(value, connection, prepared)
        if value is not None:
            return psycopg.Binary(value)
        return value

    def value_to_string(self, obj: Model) -> str:
        """Binary data is serialized as base64"""
        val = self.value_from_object(obj)
        if val is None:
            return ""
        return b64encode(val).decode("ascii")

    def to_python(self, value: Any) -> bytes | memoryview | None:
        # If it's a string, it should be base64-encoded data
        if isinstance(value, str):
            return memoryview(b64decode(value.encode("ascii")))
        return value
