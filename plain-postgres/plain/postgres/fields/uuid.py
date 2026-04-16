from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import cached_property
from typing import TYPE_CHECKING, Any
from uuid import UUID

from plain import exceptions

from .base import ColumnField

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.expressions import Func


class UUIDField(ColumnField[UUID]):
    db_type_sql = "uuid"
    empty_strings_allowed = False

    def __init__(
        self,
        *,
        generate: bool = False,
        required: bool = True,
        allow_null: bool = False,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        self.generate = generate
        super().__init__(
            required=required,
            allow_null=allow_null,
            validators=validators,
        )

    @cached_property
    def _db_default_expression(self) -> Func | None:
        if self.generate:
            from plain.postgres.functions.uuid import GenRandomUUID

            return GenRandomUUID()
        return None

    def get_db_default_expression(self) -> Func | None:
        return self._db_default_expression

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.generate:
            kwargs["generate"] = True
        return name, path, args, kwargs

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> UUID | None:
        # PostgreSQL has native UUID type
        if value is None:
            return None
        if not isinstance(value, UUID):
            value = self.to_python(value)
        return value

    def to_python(self, value: Any) -> UUID | None:
        if value is not None and not isinstance(value, UUID):
            input_form = "int" if isinstance(value, int) else "hex"
            try:
                return UUID(**{input_form: value})
            except (AttributeError, ValueError):
                raise exceptions.ValidationError(
                    '"%(value)s" is not a valid UUID.',
                    code="invalid",
                    params={"value": value},
                )
        return value
