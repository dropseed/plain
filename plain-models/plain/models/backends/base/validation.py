from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.models.backends.base.base import DatabaseWrapper
    from plain.models.fields import Field


class DatabaseValidation:
    """
    Encapsulate backend-specific validation.

    PostgreSQL supports all field types, so no validation is needed.
    """

    def __init__(self, connection: DatabaseWrapper) -> None:
        self.connection = connection

    def preflight(self) -> list[Any]:
        return []

    def check_field(self, field: Field, **kwargs: Any) -> list[Any]:
        # PostgreSQL supports all field types
        return []
