from __future__ import annotations

from typing import TYPE_CHECKING

from plain.models.backends.base.validation import BaseDatabaseValidation
from plain.preflight import PreflightResult

if TYPE_CHECKING:
    from plain.models.fields import Field


class DatabaseValidation(BaseDatabaseValidation):
    def preflight(self) -> list[PreflightResult]:
        issues = super().preflight()
        issues.extend(self._check_sql_mode())
        return issues

    def _check_sql_mode(self) -> list[PreflightResult]:
        if not (
            self.connection.sql_mode & {"STRICT_TRANS_TABLES", "STRICT_ALL_TABLES"}
        ):
            return [
                PreflightResult(
                    fix=f"{self.connection.display_name} Strict Mode is not set for the database connection. "
                    f"{self.connection.display_name}'s Strict Mode fixes many data integrity problems in "
                    f"{self.connection.display_name}, such as data truncation upon insertion, by "
                    "escalating warnings into errors. It is strongly "
                    "recommended you activate it.",
                    id="mysql.strict_mode_not_enabled",
                    warning=True,
                )
            ]
        return []

    def check_field_type(self, field: Field, field_type: str) -> list[PreflightResult]:
        """
        MySQL has the following field length restriction:
        No character (varchar) fields can have a length exceeding 255
        characters if they have a unique index on them.
        MySQL doesn't support a database index on some data types.
        """
        errors = []
        if (
            field_type.startswith("varchar")
            and field.primary_key
            and (field.max_length is None or int(field.max_length) > 255)
        ):
            errors.append(
                PreflightResult(
                    fix=f"{self.connection.display_name} may not allow unique CharFields to have a max_length "
                    "> 255.",
                    obj=field,
                    id="mysql.unique_charfield_max_length_too_long",
                    warning=True,
                )
            )

        return errors
