import sys

from psycopg import errors

from plain.exceptions import ImproperlyConfigured
from plain.models.backends.base.creation import BaseDatabaseCreation


class DatabaseCreation(BaseDatabaseCreation):
    def _quote_name(self, name):
        return self.connection.ops.quote_name(name)

    def _get_database_create_suffix(self, encoding=None, template=None):
        suffix = ""
        if encoding:
            suffix += f" ENCODING '{encoding}'"
        if template:
            suffix += f" TEMPLATE {self._quote_name(template)}"
        return suffix and "WITH" + suffix

    def sql_table_creation_suffix(self):
        test_settings = self.connection.settings_dict["TEST"]
        if test_settings.get("COLLATION") is not None:
            raise ImproperlyConfigured(
                "PostgreSQL does not support collation setting at database "
                "creation time."
            )
        return self._get_database_create_suffix(
            encoding=test_settings["CHARSET"],
            template=test_settings.get("TEMPLATE"),
        )

    def _execute_create_test_db(self, cursor, parameters):
        try:
            super()._execute_create_test_db(cursor, parameters)
        except Exception as e:
            cause = e.__cause__
            if cause and not isinstance(cause, errors.DuplicateDatabase):
                # All errors except "database already exists" cancel tests.
                self.log(f"Got an error creating the test database: {e}")
                sys.exit(2)
            else:
                raise
