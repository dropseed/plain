from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.fields import Field


class BaseDatabaseValidation:
    """Encapsulate backend-specific validation."""

    def __init__(self, connection: BaseDatabaseWrapper) -> None:
        self.connection = connection

    def preflight(self) -> list[Any]:
        return []

    def check_field(self, field: Field, **kwargs: Any) -> list[Any]:
        errors = []
        # Backends may implement a check_field_type() method.
        if (
            hasattr(self, "check_field_type")
            and
            # Ignore any related fields.
            not getattr(field, "remote_field", None)
        ):
            # Ignore fields with unsupported features.
            db_supports_all_required_features = all(
                getattr(self.connection.features, feature, False)
                for feature in field.model.model_options.required_db_features
            )
            if db_supports_all_required_features:
                field_type = field.db_type(self.connection)
                # Ignore non-concrete fields.
                if field_type is not None:
                    errors.extend(self.check_field_type(field, field_type))
        return errors
