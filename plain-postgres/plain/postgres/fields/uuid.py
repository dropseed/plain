from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from plain import exceptions

from .base import Field

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection


class UUIDField(Field[UUID]):
    db_type_sql = "uuid"
    default_error_messages = {
        "invalid": '"%(value)s" is not a valid UUID.',
    }
    description = "Universally unique identifier"
    empty_strings_allowed = False

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
                    self.error_messages["invalid"],
                    code="invalid",
                    params={"value": value},
                )
        return value
