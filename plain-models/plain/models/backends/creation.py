from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

from psycopg import errors

from plain.runtime import settings

if TYPE_CHECKING:
    from plain.models.backends.wrapper import DatabaseWrapper

# The prefix to put on the default database name when creating
# the test database.
TEST_DATABASE_PREFIX = "test_"


class DatabaseCreation:
    """
    Encapsulate backend-specific differences pertaining to creation and
    destruction of the test database.

    PostgreSQL is the only supported database backend.
    """

    def __init__(self, connection: DatabaseWrapper):
        self.connection = connection

    def _nodb_cursor(self) -> Any:
        return self.connection._nodb_cursor()

    def _quote_name(self, name: str) -> str:
        return self.connection.ops.quote_name(name)

    def log(self, msg: str) -> None:
        sys.stderr.write(msg + os.linesep)

    def create_test_db(self, verbosity: int = 1, prefix: str = "") -> str:
        """
        Create a test database, prompting the user for confirmation if the
        database already exists. Return the name of the test database created.

        If prefix is provided, it will be prepended to the database name
        to isolate it from other test databases.
        """
        from plain.models.cli.migrations import apply

        test_database_name = self._get_test_db_name(prefix)

        if verbosity >= 1:
            self.log(f"Creating test database '{test_database_name}'...")

        self._create_test_db(
            test_database_name=test_database_name, verbosity=verbosity, autoclobber=True
        )

        self.connection.close()
        settings.DATABASE["NAME"] = test_database_name
        self.connection.settings_dict["NAME"] = test_database_name

        apply.callback(
            package_label=None,
            migration_name=None,
            fake=False,
            plan=False,
            check_unapplied=False,
            backup=False,
            no_input=True,
            atomic_batch=False,  # No need for atomic batch when creating test database
            quiet=verbosity < 2,  # Show migration output when verbosity is 2+
        )

        # Ensure a connection for the side effect of initializing the test database.
        self.connection.ensure_connection()

        return test_database_name

    def _get_test_db_name(self, prefix: str = "") -> str:
        """
        Internal implementation - return the name of the test DB that will be
        created. Only useful when called from create_test_db() and
        _create_test_db() and when no external munging is done with the 'NAME'
        settings.

        If prefix is provided, it will be prepended to the database name.
        """
        # Determine the base name: explicit TEST.NAME overrides base NAME.
        base_name = (
            self.connection.settings_dict["TEST"]["NAME"]
            or self.connection.settings_dict["NAME"]
        )
        if prefix:
            return f"{prefix}_{base_name}"
        if self.connection.settings_dict["TEST"]["NAME"]:
            return self.connection.settings_dict["TEST"]["NAME"]
        name = self.connection.settings_dict["NAME"]
        assert name is not None, "DATABASE NAME must be set"
        return TEST_DATABASE_PREFIX + name

    def _get_database_create_suffix(
        self, encoding: str | None = None, template: str | None = None
    ) -> str:
        """Return PostgreSQL-specific CREATE DATABASE suffix."""
        suffix = ""
        if encoding:
            suffix += f" ENCODING '{encoding}'"
        if template:
            suffix += f" TEMPLATE {self._quote_name(template)}"
        return suffix and "WITH" + suffix

    def _execute_create_test_db(self, cursor: Any, parameters: dict[str, str]) -> None:
        try:
            cursor.execute("CREATE DATABASE {dbname} {suffix}".format(**parameters))
        except Exception as e:
            cause = e.__cause__
            if cause and not isinstance(cause, errors.DuplicateDatabase):
                # All errors except "database already exists" cancel tests.
                self.log(f"Got an error creating the test database: {e}")
                sys.exit(2)
            else:
                raise

    def _create_test_db(
        self, *, test_database_name: str, verbosity: int, autoclobber: bool
    ) -> str:
        """
        Internal implementation - create the test db tables.
        """
        test_db_params = {
            "dbname": self.connection.ops.quote_name(test_database_name),
            "suffix": self.sql_table_creation_suffix(),
        }
        # Create the test database and connect to it.
        with self._nodb_cursor() as cursor:
            try:
                self._execute_create_test_db(cursor, test_db_params)
            except Exception as e:
                self.log(f"Got an error creating the test database: {e}")
                if not autoclobber:
                    confirm = input(
                        "Type 'yes' if you would like to try deleting the test "
                        f"database '{test_database_name}', or 'no' to cancel: "
                    )
                if autoclobber or confirm == "yes":
                    try:
                        if verbosity >= 1:
                            self.log(
                                f"Destroying old test database '{test_database_name}'..."
                            )
                        cursor.execute(
                            "DROP DATABASE {dbname}".format(**test_db_params)
                        )
                        self._execute_create_test_db(cursor, test_db_params)
                    except Exception as e:
                        self.log(f"Got an error recreating the test database: {e}")
                        sys.exit(2)
                else:
                    self.log("Tests cancelled.")
                    sys.exit(1)

        return test_database_name

    def destroy_test_db(
        self, old_database_name: str | None = None, verbosity: int = 1
    ) -> None:
        """
        Destroy a test database, prompting the user for confirmation if the
        database already exists.
        """
        self.connection.close()

        test_database_name = self.connection.settings_dict["NAME"]
        assert test_database_name is not None, "Test database NAME must be set"

        if verbosity >= 1:
            self.log(f"Destroying test database '{test_database_name}'...")
        self._destroy_test_db(test_database_name, verbosity)

        # Restore the original database name
        if old_database_name is not None:
            settings.DATABASE["NAME"] = old_database_name
            self.connection.settings_dict["NAME"] = old_database_name

    def _destroy_test_db(self, test_database_name: str, verbosity: int) -> None:
        """
        Internal implementation - remove the test db tables.
        """
        # Remove the test database to clean up after
        # ourselves. Connect to the previous database (not the test database)
        # to do so, because it's not allowed to delete a database while being
        # connected to it.
        with self._nodb_cursor() as cursor:
            cursor.execute(
                f"DROP DATABASE {self.connection.ops.quote_name(test_database_name)}"
            )

    def sql_table_creation_suffix(self) -> str:
        """
        SQL to append to the end of the test table creation statements.
        """
        test_settings = self.connection.settings_dict["TEST"]
        return self._get_database_create_suffix(
            encoding=test_settings.get("CHARSET"),
            template=test_settings.get("TEMPLATE"),
        )

    def test_db_signature(self, prefix: str = "") -> tuple[str | int, ...]:
        """
        Return a tuple with elements of self.connection.settings_dict (a
        DATABASE setting value) that uniquely identify a database
        accordingly to the RDBMS particularities.
        """
        settings_dict = self.connection.settings_dict
        return (
            settings_dict.get("HOST") or "",
            settings_dict.get("PORT") or "",
            self._get_test_db_name(prefix),
        )
