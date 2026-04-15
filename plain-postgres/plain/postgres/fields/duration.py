from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from plain import exceptions
from plain.utils.dateparse import parse_duration
from plain.utils.duration import duration_string

from .base import DefaultableField

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.connection import DatabaseConnection


class DurationField(DefaultableField[datetime.timedelta]):
    """Store timedelta objects using PostgreSQL's interval type."""

    db_type_sql = "interval"
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value has an invalid format. It must be in [DD] [[HH:]MM:]ss[.uuuuuu] format.',
    }
    description = "Duration"

    def to_python(self, value: Any) -> datetime.timedelta | None:
        if value is None:
            return value
        if isinstance(value, datetime.timedelta):
            return value
        try:
            parsed = parse_duration(value)
        except ValueError:
            pass
        else:
            if parsed is not None:
                return parsed

        raise exceptions.ValidationError(
            self.error_messages["invalid"],
            code="invalid",
            params={"value": value},
        )

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        # PostgreSQL has native interval (duration) type
        return value

    def get_db_converters(
        self, connection: DatabaseConnection
    ) -> list[Callable[..., Any]]:
        # PostgreSQL has native duration field, no converters needed
        return super().get_db_converters(connection)

    def value_to_string(self, obj: Model) -> str:
        val = self.value_from_object(obj)
        return "" if val is None else duration_string(val)
