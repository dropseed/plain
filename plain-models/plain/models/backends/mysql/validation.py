from plain import preflight
from plain.models.backends.base.validation import BaseDatabaseValidation


class DatabaseValidation(BaseDatabaseValidation):
    def check(self, **kwargs):
        issues = super().check(**kwargs)
        issues.extend(self._check_sql_mode(**kwargs))
        return issues

    def _check_sql_mode(self, **kwargs):
        if not (
            self.connection.sql_mode & {"STRICT_TRANS_TABLES", "STRICT_ALL_TABLES"}
        ):
            return [
                preflight.Warning(
                    f"{self.connection.display_name} Strict Mode is not set for the database connection",
                    hint=(
                        f"{self.connection.display_name}'s Strict Mode fixes many data integrity problems in "
                        f"{self.connection.display_name}, such as data truncation upon insertion, by "
                        "escalating warnings into errors. It is strongly "
                        "recommended you activate it.",
                    ),
                    id="mysql.W002",
                )
            ]
        return []

    def check_field_type(self, field, field_type):
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
                preflight.Warning(
                    f"{self.connection.display_name} may not allow unique CharFields to have a max_length "
                    "> 255.",
                    obj=field,
                    id="mysql.W003",
                )
            )

        return errors
