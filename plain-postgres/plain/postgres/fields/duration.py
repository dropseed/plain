from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from plain import exceptions
from plain.utils.dateparse import parse_duration

from .base import DefaultableField

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection


class DurationField(DefaultableField[datetime.timedelta]):
    """Store timedelta objects using PostgreSQL's interval type."""

    db_type_sql = "interval"
    empty_strings_allowed = False

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
            '"%(value)s" value has an invalid format. It must be in [DD] [[HH:]MM:]ss[.uuuuuu] format.',
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
